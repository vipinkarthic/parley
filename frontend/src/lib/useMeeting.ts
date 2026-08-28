"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { STUN_ONLY, fetchIceConfig, type IceConfig } from "@/lib/api";
import type { MeetingSettings, WaitingPerson } from "@/lib/types";
import { to12Hour } from "@/lib/utils";

export interface RemotePeer {
  id: number;
  displayName: string;
  isHost: boolean;
  muted: boolean;
  videoOn: boolean;
  hand: boolean;
  sharing: boolean;
  cameraStream: MediaStream | null;
  screenStream: MediaStream | null;
}

export interface LiveChatMessage {
  id: number;
  from: number | "me";
  sender: string;
  text: string;
  self: boolean;
  time: string;
}

export interface FloatingReaction {
  key: number;
  from: number | "me";
  emoji: string;
}

interface PeerBox {
  pc: RTCPeerConnection;
  streams: Map<string, MediaStream>;
  screenSid: string | null;
  screenSender: RTCRtpSender | null;
  // The sender carrying our camera to this one peer. Paging works by
  // swapping the track on it, never by touching the transceiver.
  cameraSender: RTCRtpSender | null;
}

const DEFAULT_SETTINGS: MeetingSettings = {
  waiting_room: true,
  locked: false,
  mute_on_entry: false,
  join_before_host: false,
  allow_screen_share: true,
  allow_unmute: true,
  allow_video: true,
  allow_rename: true,
  allow_chat: true,
  allow_reactions: true,
};

function wsBase(): string {
  const base =
    process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ||
    "http://localhost:8000";
  return base.replace(/^http/, "ws");
}

let seq = 1;

// Reconnect tuning.
//
// A dropped signalling socket used to end the meeting outright. It now comes
// back, and these are the numbers that decide how it feels: fast enough that
// a redeploy is a blink, slow enough that a backend which is genuinely down
// is not being hammered by every open tab.
const BASE_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 15_000;
// Every 20s, cheap: one JSON frame. This is the only thing that notices a
// half-open socket - the kind a laptop leaves behind when it sleeps, which
// reports OPEN and never fires a close event.
const HEARTBEAT_MS = 20_000;
// How long a probe ping gets before the socket is declared dead.
const PONG_GRACE_MS = 5_000;

// --- Active-speaker paging and encoder caps (Phase 4) ----------------------
//
// A mesh makes every participant upload one copy of their video per other
// participant, so the room's cost is O(n^2) and it is paid by the clients.
// Paging cuts most of those edges: you only send your camera to the people
// who currently have a reason to see it.

// How often we look at our own microphone. Cheap - one FFT read.
const LEVEL_SAMPLE_MS = 150;
// Two thresholds, not one. A single threshold makes a voice sitting right on
// it chatter on and off several times a second, and every one of those is a
// message and possibly a track swap.
const SPEAKING_ENTER = 18;
const SPEAKING_RELEASE = 12;
// Never report more often than this, even mid-sentence.
const SPEAKING_REPORT_MIN_MS = 300;
// While still speaking, refresh at this rate so the server has a live level
// to rank by and can time us out if our "stopped" message is lost.
const SPEAKING_REFRESH_MS = 1_000;

// How many remote cameras this client subscribes to at once. Pins, the
// spotlight and anyone screensharing are additional to this, never counted
// against it - dropping the video of the person you deliberately pinned in
// order to honour a budget would be the wrong trade.
const DEFAULT_VIDEO_BUDGET = 5;

// Encoder caps, keyed on how many peers currently want our camera. Sending
// the same 1.2Mbps stream to seven people is 8.4Mbps of uplink, which is
// more than most home connections have; the ladder is what keeps a large
// room inside a small pipe.
const ENCODER_TIERS: {
  upTo: number;
  maxBitrate: number;
  scaleResolutionDownBy: number;
  maxFramerate: number;
}[] = [
  { upTo: 1, maxBitrate: 1_200_000, scaleResolutionDownBy: 1, maxFramerate: 30 },
  { upTo: 3, maxBitrate: 600_000, scaleResolutionDownBy: 1.5, maxFramerate: 24 },
  { upTo: 6, maxBitrate: 350_000, scaleResolutionDownBy: 2, maxFramerate: 20 },
  {
    upTo: Number.POSITIVE_INFINITY,
    maxBitrate: 200_000,
    scaleResolutionDownBy: 3,
    maxFramerate: 15,
  },
];

// The server's application close codes, named here as they are in ws.py.
// The 4000-4999 range is reserved for the application by the WebSocket spec.
const WS_BAD_PID = 4001; // malformed participant id
const WS_UNAUTHORISED = 4003; // token rejected
const WS_DENIED = 4004; // the host denied this guest
const WS_MEETING_ENDED = 4005; // the meeting has ended
const WS_ROOM_FULL = 4006; // the room is full

// Terminal for this participant: they are not coming back into this meeting,
// so retrying would be an infinite loop against a server that is answering
// correctly. 4009 is deliberately absent - "this socket was replaced" means
// the newer socket carries on, and this one simply stops.
const TERMINAL_CLOSE_CODES = new Set([
  WS_BAD_PID,
  WS_UNAUTHORISED,
  WS_DENIED,
  WS_MEETING_ENDED,
  WS_ROOM_FULL,
]);

export interface UseMeetingOptions {
  number: string;
  participantId: number;
  wsToken: string;
  displayName: string;
  isHost: boolean;
  localStream: MediaStream | null;
  initialMicOn: boolean;
  initialCamOn: boolean;
  initialAdmission?: "admitted" | "waiting";
  initialSettings?: MeetingSettings;
  // How many remote cameras to subscribe to. The server enforces the room
  // cap; this is only about what this client asks to receive.
  videoBudget?: number;
  // Whoever this client has pinned. Pinned peers are always subscribed, and
  // a pin is what keeps one sender's upstream alive even when nobody else
  // wants it.
  pinnedId?: number | "me" | null;
  onRemoved?: () => void;
  onEnded?: () => void;
  onDenied?: () => void;
  onAskUnmute?: () => void;
  onShareDenied?: () => void;
}

export function useMeeting(opts: UseMeetingOptions) {
  const {
    number,
    participantId,
    wsToken,
    displayName,
    localStream,
    initialMicOn,
    initialCamOn,
    initialAdmission = "admitted",
    initialSettings = DEFAULT_SETTINGS,
    videoBudget = DEFAULT_VIDEO_BUDGET,
    pinnedId = null,
    onRemoved,
    onEnded,
    onDenied,
    onAskUnmute,
    onShareDenied,
  } = opts;

  const [micOn, setMicOn] = useState(initialMicOn);
  const [camOn, setCamOn] = useState(initialCamOn);
  const [myName, setMyName] = useState(displayName);
  const [peers, setPeers] = useState<RemotePeer[]>([]);
  const [messages, setMessages] = useState<LiveChatMessage[]>([]);
  const [reactions, setReactions] = useState<FloatingReaction[]>([]);
  const [handRaised, setHandRaised] = useState(false);
  const [isSharing, setIsSharing] = useState(false);
  const [screenStream, setScreenStream] = useState<MediaStream | null>(null);
  const [activeSpeakerId, setActiveSpeakerId] = useState<number | "me" | null>(null);
  const [status, setStatus] = useState<
    "connecting" | "live" | "reconnecting" | "error"
  >("connecting");

  const [admission, setAdmission] = useState<"admitted" | "waiting">(initialAdmission);
  const [waitingList, setWaitingList] = useState<WaitingPerson[]>([]);
  const [hostPresent, setHostPresent] = useState(true);
  const [settings, setSettings] = useState<MeetingSettings>(initialSettings);
  const [spotlightId, setSpotlightId] = useState<number | "me" | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const pcsRef = useRef<Map<number, PeerBox>>(new Map());
  const iceConfigRef = useRef<IceConfig>(STUN_ONLY);
  const startedRef = useRef(false);
  const stateRef = useRef({ muted: !initialMicOn, videoOn: initialCamOn });
  const localStreamRef = useRef<MediaStream | null>(localStream);
  const screenTrackRef = useRef<MediaStreamTrack | null>(null);
  const screenStreamRef = useRef<MediaStream | null>(null);
  const sharingRef = useRef(false);
  const handRaisedRef = useRef(false);
  const myNameRef = useRef(displayName);

  // Paging state. All refs: it is read from inside the socket effect's
  // closure and from timers, and none of it should re-render anything.
  //
  //   rankRef      the server's authoritative ordering, most deserving first
  //   toldRef      what we last told each peer about wanting their camera.
  //                A map rather than a set of wanted ids, because "not in
  //                the set" and "told to stop" are different things: a peer
  //                we never wanted has never been told anything, and a
  //                sender's default is to send.
  //   wantersRef   peers who have asked for OURS (drives the encoder caps)
  //   sharingRemote  peers currently screensharing - always subscribed
  const rankRef = useRef<number[]>([]);
  const toldRef = useRef<Map<number, boolean>>(new Map());
  const wantersRef = useRef<Set<number>>(new Set());
  const sharingRemoteRef = useRef<Set<number>>(new Set());
  const pinnedRef = useRef<number | "me" | null>(pinnedId);
  const spotlightRef = useRef<number | "me" | null>(null);
  const speakingRef = useRef({ on: false, lastSent: 0 });

  useEffect(() => {
    localStreamRef.current = localStream;
    // Keep the real tracks in step with the mic/cam state. Without this the
    // UI can say muted while the track is still live and still sending.
    if (localStream) {
      localStream.getAudioTracks().forEach((t) => (t.enabled = !stateRef.current.muted));
      localStream.getVideoTracks().forEach((t) => (t.enabled = stateRef.current.videoOn));
    }
  }, [localStream]);
  useEffect(() => {
    myNameRef.current = myName;
  }, [myName]);
  useEffect(() => {
    handRaisedRef.current = handRaised;
  }, [handRaised]);

  const upsertPeer = useCallback(
    (id: number, patch: Partial<RemotePeer>, base?: Partial<RemotePeer>) => {
      setPeers((prev) => {
        const idx = prev.findIndex((p) => p.id === id);
        if (idx === -1) {
          return [
            ...prev,
            {
              id,
              displayName: base?.displayName ?? "Guest",
              isHost: base?.isHost ?? false,
              muted: base?.muted ?? false,
              videoOn: base?.videoOn ?? true,
              hand: base?.hand ?? false,
              sharing: base?.sharing ?? false,
              cameraStream: null,
              screenStream: null,
              ...patch,
            },
          ];
        }
        const next = [...prev];
        next[idx] = { ...next[idx], ...patch };
        return next;
      });
    },
    []
  );

  const recompute = useCallback((peerId: number) => {
    const box = pcsRef.current.get(peerId);
    if (!box) return;
    const screen = box.screenSid ? box.streams.get(box.screenSid) ?? null : null;
    let camera: MediaStream | null = null;
    for (const [sid, s] of Array.from(box.streams)) {
      if (sid !== box.screenSid) {
        camera = s;
        break;
      }
    }
    upsertPeer(peerId, { cameraStream: camera, screenStream: screen });
  }, [upsertPeer]);

  const removePeerLocal = useCallback((id: number) => {
    const box = pcsRef.current.get(id);
    if (box) {
      box.pc.onicecandidate = null;
      box.pc.ontrack = null;
      box.pc.oniceconnectionstatechange = null;
      box.pc.close();
      pcsRef.current.delete(id);
    }
    wantersRef.current.delete(id);
    toldRef.current.delete(id);
    sharingRemoteRef.current.delete(id);
    setPeers((prev) => prev.filter((p) => p.id !== id));
  }, []);

  const send = useCallback((msg: object) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }, []);

  // How hard to encode, given how many peers currently want our camera.
  const applyEncoderCaps = useCallback(() => {
    const receivers = Math.max(1, wantersRef.current.size);
    const tier =
      ENCODER_TIERS.find((t) => receivers <= t.upTo) ??
      ENCODER_TIERS[ENCODER_TIERS.length - 1];
    pcsRef.current.forEach((box) => {
      const sender = box.cameraSender;
      if (!sender) return;
      try {
        const params = sender.getParameters();
        // Chrome hands back an empty encodings array on a sender that has
        // not negotiated yet; setParameters rejects that, so seed it.
        if (!params.encodings || params.encodings.length === 0) {
          params.encodings = [{}];
        }
        params.encodings[0].maxBitrate = tier.maxBitrate;
        params.encodings[0].scaleResolutionDownBy = tier.scaleResolutionDownBy;
        params.encodings[0].maxFramerate = tier.maxFramerate;
        void sender.setParameters(params).catch(() => {});
      } catch {
      }
    });
  }, []);

  // A peer told us whether they want our camera. This is the whole of the
  // sending side of paging.
  //
  // replaceTrack, and never transceiver.direction + renegotiate: swapping
  // the track on an existing sender needs no SDP round trip, whereas
  // flipping direction does, and six people talking over each other would
  // produce a renegotiation storm costing more than the problem it solves.
  // The transceiver stays sendrecv throughout and the m-line never moves.
  const setSendingVideoTo = useCallback(
    (peerId: number, want: boolean) => {
      if (want) wantersRef.current.add(peerId);
      else wantersRef.current.delete(peerId);
      const box = pcsRef.current.get(peerId);
      if (box?.cameraSender) {
        const track = want
          ? localStreamRef.current?.getVideoTracks()[0] ?? null
          : null;
        // Idempotent: replacing null with null, or the same track with
        // itself, is a no-op. So a duplicated or lost request costs nothing
        // and there is no resync protocol to get wrong.
        void box.cameraSender.replaceTrack(track).catch(() => {});
      }
      applyEncoderCaps();
    },
    [applyEncoderCaps]
  );

  // What this client wants to receive, recomputed from the server's ranking.
  //
  //     want = top-K by rank  u  pinned  u  spotlight  u  screensharing
  //
  // Derived from the *server's* order rather than from anything measured
  // locally, which is what makes every grid in the meeting agree. A client
  // could not do this itself even if it wanted to: once paging drops a
  // track there is no longer any way to measure that peer's audio.
  const recomputeWants = useCallback(() => {
    const desired = new Set<number>();
    const consider = (id: number | "me" | null | undefined) => {
      if (typeof id === "number" && pcsRef.current.has(id)) desired.add(id);
    };
    consider(pinnedRef.current);
    consider(spotlightRef.current);
    for (const id of Array.from(sharingRemoteRef.current)) consider(id);

    for (const id of rankRef.current) {
      if (desired.size >= videoBudget) break;
      consider(id);
    }
    // A quiet room has no ranking worth the name, and showing nobody's
    // video because nobody has spoken yet would be absurd. Fill whatever
    // budget is left with whoever is connected.
    if (desired.size < videoBudget) {
      for (const id of Array.from(pcsRef.current.keys())) {
        if (desired.size >= videoBudget) break;
        desired.add(id);
      }
    }

    // Diffed against what each peer was last *told*, over every connected
    // peer - not against the previous desired set.
    //
    // Getting this wrong made the whole feature inert, and it took real
    // browsers to notice: diffing desired-against-previous only ever emits
    // want:false for a peer that was in the set and fell out. A peer who
    // was never in it is never told anything at all, and since a sender
    // defaults to sending, it streams forever. Seven peers with a budget of
    // five produced 35 want:true, zero want:false, and not one dropped
    // track.
    const told = toldRef.current;
    for (const id of Array.from(pcsRef.current.keys())) {
      const want = desired.has(id);
      if (told.get(id) !== want) {
        send({ type: "video-request", to: id, want });
        told.set(id, want);
      }
    }
    for (const id of Array.from(told.keys())) {
      if (!pcsRef.current.has(id)) told.delete(id);
    }
  }, [send, videoBudget]);

  useEffect(() => {
    pinnedRef.current = pinnedId;
    recomputeWants();
  }, [pinnedId, recomputeWants]);

  const ensurePc = useCallback(
    (peerId: number): RTCPeerConnection => {
      const existing = pcsRef.current.get(peerId);
      if (existing) return existing.pc;

      // A bad ICE server entry makes this THROW, not degrade - and a throw
      // here takes the whole meeting down rather than one relay path.
      //
      // fetchIceConfig already falls back to STUN_ONLY, but only when the
      // *fetch* fails. A successful fetch of a malformed payload sails past
      // it, which is exactly what happened in production on 2026-09-14: a
      // TURN_URLS value had lost the "?" from "?transport=tcp" on its way
      // through a shell, and the constructor rejected it outright - Chrome
      // with `SyntaxError: Invalid port`, Firefox with `NS_ERROR_UNEXPECTED`.
      // Video was dead, not merely unrelayed.
      //
      // So: fall back to STUN and carry on. Peers with a direct path still
      // connect; peers behind symmetric NAT still cannot, which is the same
      // position as having no relay configured at all. Degraded beats dead.
      // The fallback is latched into the ref so the next peer does not repeat
      // a construction already known to fail.
      const cfg = iceConfigRef.current;
      let pc: RTCPeerConnection;
      try {
        pc = new RTCPeerConnection({
          iceServers: cfg.iceServers,
          iceCandidatePoolSize: cfg.iceCandidatePoolSize,
        });
      } catch {
        iceConfigRef.current = STUN_ONLY;
        pc = new RTCPeerConnection({
          iceServers: STUN_ONLY.iceServers,
          iceCandidatePoolSize: cfg.iceCandidatePoolSize,
        });
      }
      const box: PeerBox = {
        pc,
        streams: new Map(),
        screenSid: null,
        screenSender: null,
        cameraSender: null,
      };
      pcsRef.current.set(peerId, box);

      const local = localStreamRef.current;
      if (local) {
        for (const t of local.getTracks()) {
          const sender = pc.addTrack(t, local);
          if (t.kind === "video") box.cameraSender = sender;
        }
      }
      if (sharingRef.current && screenTrackRef.current && screenStreamRef.current) {
        box.screenSender = pc.addTrack(screenTrackRef.current, screenStreamRef.current);
      }

      // Prefer H.264, which is the codec most likely to have a hardware
      // encoder behind it - and in a mesh this machine is running one
      // encoder per peer, so it is the difference that matters most.
      //
      // Done here, before any offer exists. setCodecPreferences only affects
      // the next negotiation, and calling it later would need one.
      try {
        const caps = RTCRtpSender.getCapabilities?.("video");
        const tx = pc
          .getTransceivers()
          .find((t) => t.sender === box.cameraSender);
        if (caps?.codecs && tx?.setCodecPreferences) {
          const h264 = caps.codecs.filter((c) => /h264/i.test(c.mimeType));
          const rest = caps.codecs.filter((c) => !/h264/i.test(c.mimeType));
          if (h264.length) tx.setCodecPreferences([...h264, ...rest]);
        }
      } catch {
      }

      // Assume they want our camera until they say otherwise. A new peer
      // connection has to carry a video m-line anyway, and one unwanted
      // stream for the length of one round trip is cheaper than the
      // handshake that would avoid it.
      wantersRef.current.add(peerId);
      applyEncoderCaps();

      pc.onicecandidate = (e) => {
        if (e.candidate) send({ type: "ice", to: peerId, candidate: e.candidate });
      };
      pc.ontrack = (e) => {
        const stream = e.streams[0] ?? new MediaStream([e.track]);
        if (!box.streams.has(stream.id)) box.streams.set(stream.id, stream);
        recompute(peerId);
      };
      // "failed" is terminal - ICE will not retry by itself, so a peer whose
      // candidates all died (network change, relay allocation expired) stays
      // black forever without this. Only the lower participant id restarts,
      // because two simultaneous offers on one connection is glare.
      pc.oniceconnectionstatechange = () => {
        if (pc.iceConnectionState !== "failed") return;
        if (participantId >= peerId) return;
        void (async () => {
          try {
            const offer = await pc.createOffer({ iceRestart: true });
            await pc.setLocalDescription(offer);
            send({ type: "offer", to: peerId, sdp: pc.localDescription });
          } catch {
          }
        })();
      };
      return pc;
    },
    [send, recompute, participantId, applyEncoderCaps]
  );

  const makeOffer = useCallback(
    async (peerId: number) => {
      const pc = ensurePc(peerId);
      try {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        send({ type: "offer", to: peerId, sdp: pc.localDescription });
      } catch {
      }
    },
    [ensurePc, send]
  );

  const broadcastState = useCallback(() => {
    send({ type: "state", muted: stateRef.current.muted, videoOn: stateRef.current.videoOn });
  }, [send]);

  const toggleMic = useCallback(() => {
    setMicOn((on) => {
      const next = !on;
      localStreamRef.current?.getAudioTracks().forEach((t) => (t.enabled = next));
      stateRef.current.muted = !next;
      broadcastState();
      return next;
    });
  }, [broadcastState]);

  const toggleCam = useCallback(() => {
    setCamOn((on) => {
      const next = !on;
      localStreamRef.current?.getVideoTracks().forEach((t) => (t.enabled = next));
      stateRef.current.videoOn = next;
      broadcastState();
      return next;
    });
  }, [broadcastState]);

  const forceMuteSelf = useCallback(() => {
    setMicOn(() => {
      localStreamRef.current?.getAudioTracks().forEach((t) => (t.enabled = false));
      stateRef.current.muted = true;
      broadcastState();
      return false;
    });
  }, [broadcastState]);

  const sendChat = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      setMessages((m) => [
        ...m,
        { id: seq++, from: "me", sender: myNameRef.current, text: trimmed, self: true, time: to12Hour(new Date()) },
      ]);
      send({ type: "chat", text: trimmed });
    },
    [send]
  );

  const pushReaction = useCallback((from: number | "me", emoji: string) => {
    const key = seq++;
    setReactions((r) => [...r, { key, from, emoji }]);
    setTimeout(() => setReactions((r) => r.filter((x) => x.key !== key)), 3500);
  }, []);

  const sendReaction = useCallback(
    (emoji: string) => {
      pushReaction("me", emoji);
      send({ type: "reaction", emoji });
    },
    [pushReaction, send]
  );

  const toggleHand = useCallback(() => {
    setHandRaised((h) => {
      const next = !h;
      send({ type: "hand", raised: next });
      return next;
    });
  }, [send]);

  const muteAll = useCallback(() => send({ type: "mute-all" }), [send]);
  const mutePeer = useCallback((id: number) => send({ type: "mute-peer", target: id }), [send]);
  const askToUnmute = useCallback((id: number) => send({ type: "ask-unmute", target: id }), [send]);
  const removePeer = useCallback((id: number) => send({ type: "remove-peer", target: id }), [send]);
  const endMeeting = useCallback(() => send({ type: "end-meeting" }), [send]);
  const admitPeer = useCallback((id: number) => send({ type: "admit", target: id }), [send]);
  const denyPeer = useCallback((id: number) => send({ type: "deny", target: id }), [send]);
  const admitAll = useCallback(() => send({ type: "admit-all" }), [send]);
  const lowerHand = useCallback((id: number) => send({ type: "lower-hand", target: id }), [send]);
  const spotlight = useCallback(
    (id: number | "me" | null) => {
      setSpotlightId(id);
      send({ type: "spotlight", target: id });
    },
    [send]
  );
  const toggleWaitingRoom = useCallback(() => {
    setSettings((s) => {
      const next = !s.waiting_room;
      send({ type: "waiting-room", on: next });
      return { ...s, waiting_room: next };
    });
  }, [send]);
  const updateSettings = useCallback(
    (patch: Partial<MeetingSettings>) => {
      setSettings((s) => ({ ...s, ...patch }));
      send({ type: "settings", settings: patch });
    },
    [send]
  );
  const renameSelf = useCallback(
    (name: string) => {
      const n = name.trim().slice(0, 120);
      if (!n) return;
      setMyName(n);
      send({ type: "rename", name: n });
    },
    [send]
  );

  const stopShare = useCallback(async () => {
    for (const [peerId, box] of Array.from(pcsRef.current)) {
      if (box.screenSender) {
        try {
          box.pc.removeTrack(box.screenSender);
        } catch {
        }
        box.screenSender = null;
        await makeOffer(peerId);
      }
    }
    screenTrackRef.current?.stop();
    screenTrackRef.current = null;
    screenStreamRef.current = null;
    sharingRef.current = false;
    setIsSharing(false);
    setScreenStream(null);
    send({ type: "share", on: false });
  }, [makeOffer, send]);

  const startShare = useCallback(async () => {
    if (!localStreamRef.current) return;
    try {
      const display = await (
        navigator.mediaDevices as MediaDevices & {
          getDisplayMedia: (c: unknown) => Promise<MediaStream>;
        }
      ).getDisplayMedia({ video: true });
      const screenTrack = display.getVideoTracks()[0];
      screenTrackRef.current = screenTrack;
      screenStreamRef.current = display;
      sharingRef.current = true;
      setIsSharing(true);
      setScreenStream(display);
      for (const [peerId, box] of Array.from(pcsRef.current)) {
        box.screenSender = box.pc.addTrack(screenTrack, display);
        await makeOffer(peerId);
      }
      send({ type: "share", on: true, streamId: display.id });
      screenTrack.addEventListener("ended", () => void stopShare());
    } catch {
    }
  }, [makeOffer, send, stopShare]);

  // Report our OWN microphone, and nothing else.
  //
  // This used to run an AnalyserNode over every *remote* stream and pick the
  // loudest locally. That was wrong twice over: independent rankings meant
  // two people in one meeting saw different grids, and - fatally for paging -
  // you cannot measure the audio level of a peer whose track you just
  // dropped. The server ranks; each client only reports itself.
  useEffect(() => {
    const AudioCtx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    let node: AnalyserNode | null = null;
    let data: Uint8Array<ArrayBuffer> | null = null;
    let attachedTo: MediaStream | null = null;

    const attach = () => {
      const stream = localStreamRef.current;
      if (!stream || stream === attachedTo) return;
      if (stream.getAudioTracks().length === 0) return;
      try {
        const src = ctx.createMediaStreamSource(stream);
        node = ctx.createAnalyser();
        node.fftSize = 512;
        src.connect(node);
        data = new Uint8Array(new ArrayBuffer(node.frequencyBinCount));
        attachedTo = stream;
      } catch {
      }
    };

    const interval = setInterval(() => {
      attach();
      if (!node || !data) return;
      node.getByteFrequencyData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += data[i];
      const avg = sum / data.length;

      const state = speakingRef.current;
      // Muted means not speaking, whatever the microphone hears - otherwise
      // muting yourself mid-sentence keeps you at the top of everyone's grid.
      const on = stateRef.current.muted
        ? false
        : state.on
          ? avg > SPEAKING_RELEASE
          : avg > SPEAKING_ENTER;

      const now = Date.now();
      const crossed = on !== state.on;
      const refreshDue = on && now - state.lastSent >= SPEAKING_REFRESH_MS;
      if (!crossed && !refreshDue) return;
      if (now - state.lastSent < SPEAKING_REPORT_MIN_MS) return;

      state.on = on;
      state.lastSent = now;
      send({
        type: "speaking",
        on,
        // Normalised to 0-100. The absolute scale is arbitrary; all the
        // server does with it is order simultaneous speakers.
        level: Math.max(0, Math.min(100, Math.round((avg / 60) * 100))),
      });
    }, LEVEL_SAMPLE_MS);

    return () => {
      clearInterval(interval);
      ctx.close().catch(() => {});
    };
  }, [send]);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    // Everything below lives in this closure rather than in refs because it
    // is all one connection's worth of state, and the effect owns exactly one
    // connection lifecycle at a time.
    let cancelled = false;
    let socket: WebSocket | null = null;
    let attempt = 0;
    let terminal = false;
    let awaitingPong = false;
    let heartbeat: ReturnType<typeof setInterval> | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let probeTimer: ReturnType<typeof setTimeout> | null = null;

    // Rebuilt per attempt: mic and camera state travels in the query string,
    // and by the time we reconnect it may not be what it was at first join.
    const socketUrl = () =>
      `${wsBase()}/ws/meetings/${encodeURIComponent(number)}` +
      `?pid=${participantId}&token=${encodeURIComponent(wsToken)}` +
      `&muted=${stateRef.current.muted ? 1 : 0}&video=${stateRef.current.videoOn ? 1 : 0}`;

    const applyPeerShareInfo = (peer: RemotePeer & { screenSid?: string | null }) => {
      if (peer.sharing && peer.screenSid) {
        const box = pcsRef.current.get(peer.id);
        if (box) {
          box.screenSid = peer.screenSid;
          recompute(peer.id);
        }
      }
    };

    const onMessage = async (event: MessageEvent) => {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case "peers":
          for (const peer of msg.peers as RemotePeer[]) {
            upsertPeer(peer.id, {}, peer);
            ensurePc(peer.id);
            applyPeerShareInfo(peer);
            if (peer.sharing) sharingRemoteRef.current.add(peer.id);
            // The lower participant id owns the offer for a pair. Ids are
            // handed out in ascending order, so on a first join ours is
            // always the highest and the peers already in the room do the
            // offering - which is why this loop never used to offer at all.
            // A reconnect keeps our original, lower id, and then every peer
            // evaluates "their id < ours" as false and nobody offers: the
            // socket comes back and the video never does.
            if (participantId < peer.id) makeOffer(peer.id);
          }
          recomputeWants();
          break;
        case "peer-joined": {
          const peer = msg.peer as RemotePeer;
          upsertPeer(peer.id, {}, peer);
          ensurePc(peer.id);
          applyPeerShareInfo(peer);
          if (peer.sharing) sharingRemoteRef.current.add(peer.id);
          if (participantId < peer.id) makeOffer(peer.id);
          recomputeWants();
          break;
        }
        // The server's ranking. Every client in the room gets the identical
        // list and derives its desired set from it, which is what stops two
        // grids disagreeing and the tracks between them thrashing.
        case "active-speakers": {
          rankRef.current = (msg.ranked as number[]) ?? [];
          const speaking = new Set((msg.speaking as number[]) ?? []);
          const loudest =
            rankRef.current.find((id) => speaking.has(id)) ?? null;
          setActiveSpeakerId(
            loudest === null ? null : loudest === participantId ? "me" : loudest
          );
          recomputeWants();
          break;
        }
        // A peer telling us whether to send them our camera.
        case "video-request":
          setSendingVideoTo(msg.from, !!msg.want);
          break;
        case "offer": {
          const pc = ensurePc(msg.from);
          await pc.setRemoteDescription(msg.sdp);
          const answer = await pc.createAnswer();
          await pc.setLocalDescription(answer);
          send({ type: "answer", to: msg.from, sdp: pc.localDescription });
          break;
        }
        case "answer": {
          const box = pcsRef.current.get(msg.from);
          if (box) await box.pc.setRemoteDescription(msg.sdp);
          break;
        }
        case "ice": {
          const box = pcsRef.current.get(msg.from);
          if (box && msg.candidate) {
            try {
              await box.pc.addIceCandidate(msg.candidate);
            } catch {
            }
          }
          break;
        }
        case "state":
          upsertPeer(msg.from, { muted: msg.muted, videoOn: msg.videoOn });
          break;
        case "chat":
          setMessages((m) => [
            ...m,
            { id: seq++, from: msg.from, sender: msg.displayName, text: msg.text, self: false, time: to12Hour(new Date()) },
          ]);
          break;
        case "reaction":
          pushReaction(msg.from, msg.emoji);
          break;
        case "hand":
          upsertPeer(msg.from, { hand: msg.raised });
          break;
        case "share": {
          const box = pcsRef.current.get(msg.from);
          if (box) {
            box.screenSid = msg.on ? msg.streamId ?? null : null;
            recompute(msg.from);
          }
          upsertPeer(msg.from, { sharing: msg.on });
          // A screenshare is always subscribed - it is the one thing in the
          // room nobody can follow from an avatar.
          if (msg.on) sharingRemoteRef.current.add(msg.from);
          else sharingRemoteRef.current.delete(msg.from);
          recomputeWants();
          break;
        }
        case "rename":
          if (msg.from === participantId) setMyName(msg.displayName);
          else upsertPeer(msg.from, { displayName: msg.displayName });
          break;
        case "settings":
          setSettings((s) => ({ ...s, ...msg.settings }));
          break;
        case "spotlight":
          setSpotlightId(msg.target ?? null);
          spotlightRef.current = msg.target ?? null;
          recomputeWants();
          break;
        case "lower-hand":
          setHandRaised(false);
          break;
        case "ask-unmute":
          onAskUnmute?.();
          break;
        case "share-denied":
          onShareDenied?.();
          break;
        case "force-mute":
          forceMuteSelf();
          break;
        case "pong":
          awaitingPong = false;
          break;
        // These three end this participant's meeting. Flagging them stops the
        // reconnect loop, which would otherwise cheerfully dial back in to a
        // meeting the host just removed us from.
        case "removed":
          terminal = true;
          onRemoved?.();
          break;
        case "meeting-ended":
          terminal = true;
          onEnded?.();
          break;
        case "waiting":
          setAdmission("waiting");
          setHostPresent(!!msg.hostPresent);
          break;
        case "admitted":
          setAdmission("admitted");
          break;
        case "waiting-list":
          setWaitingList(msg.waiting || []);
          break;
        case "host-present":
          setHostPresent(!!msg.present);
          break;
        case "waiting-room":
          setSettings((s) => ({ ...s, waiting_room: !!msg.on }));
          break;
        case "denied":
          terminal = true;
          onDenied?.();
          break;
        case "peer-left":
          removePeerLocal(msg.id);
          recomputeWants();
          break;
      }
    };

    const clearTimers = () => {
      if (heartbeat) clearInterval(heartbeat);
      if (retryTimer) clearTimeout(retryTimer);
      if (probeTimer) clearTimeout(probeTimer);
      heartbeat = retryTimer = probeTimer = null;
      awaitingPong = false;
    };

    const closePeers = () => {
      // Peer connections are rebuilt from scratch on reconnect, so every
      // subscription is void. Cleared here rather than remembered, so the
      // recompute that follows the next `peers` frame re-asks from nothing
      // instead of diffing against a set that no longer exists.
      toldRef.current.clear();
      wantersRef.current.clear();
      pcsRef.current.forEach((box) => {
        box.pc.onicecandidate = null;
        box.pc.ontrack = null;
        box.pc.oniceconnectionstatechange = null;
        box.pc.close();
      });
      pcsRef.current.clear();
    };

    const ping = () => {
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      awaitingPong = true;
      try {
        socket.send(JSON.stringify({ type: "ping" }));
      } catch {
        socket.close();
      }
    };

    const startHeartbeat = () => {
      if (heartbeat) clearInterval(heartbeat);
      heartbeat = setInterval(() => {
        if (!socket || socket.readyState !== WebSocket.OPEN) return;
        if (awaitingPong) {
          // The previous ping was never answered. A socket in this state
          // reports OPEN and will never fire a close event on its own, so
          // closing it by hand is the only way back.
          socket.close();
          return;
        }
        ping();
      }, HEARTBEAT_MS);
    };

    const scheduleRetry = () => {
      if (cancelled || terminal) return;
      const backoff = Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * 2 ** attempt);
      attempt += 1;
      // Jitter matters here: one redeploy drops every socket at once, and
      // without it every client in every meeting comes back in lockstep and
      // hits the new instance as a thundering herd.
      const delay = backoff * (0.5 + Math.random());
      setStatus("reconnecting");
      retryTimer = setTimeout(connect, delay);
    };

    function connect() {
      if (cancelled || terminal) return;
      retryTimer = null;
      const ws = new WebSocket(socketUrl());
      socket = ws;
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled || socket !== ws) {
          ws.close();
          return;
        }
        attempt = 0;
        setStatus("live");
        startHeartbeat();
        // The instance we just landed on rebuilt our presence from the query
        // string, which carries mic and camera but not these two - so without
        // re-announcing them a raised hand silently drops and, worse, a live
        // screenshare becomes invisible to everyone else.
        if (handRaisedRef.current) send({ type: "hand", raised: true });
        if (sharingRef.current && screenStreamRef.current) {
          send({ type: "share", on: true, streamId: screenStreamRef.current.id });
        }
      };

      ws.onmessage = onMessage;
      // A failed connection always produces a close event too, so recovery is
      // driven from one place rather than two.
      ws.onerror = () => {};

      ws.onclose = (event) => {
        if (socket !== ws) return; // already replaced; its own handler owns it
        clearTimers();
        if (cancelled) return;
        if (TERMINAL_CLOSE_CODES.has(event.code)) {
          terminal = true;
          setStatus("error");
          return;
        }
        // Signalling carries offers, answers, candidates and ICE restarts, so
        // once it is gone every peer connection is unmanageable even if its
        // media is momentarily still flowing. Rebuilding on the new socket is
        // deterministic; keeping them alive and hoping invites glare, because
        // the far end may have torn its own down on a different schedule.
        closePeers();
        setPeers([]);
        scheduleRetry();
      };
    }

    // Waking from sleep or regaining a network is information: act on it
    // instead of sitting out the rest of a backoff.
    const wake = () => {
      if (cancelled || terminal) return;
      if (socket && socket.readyState === WebSocket.CONNECTING) return;
      if (socket && socket.readyState === WebSocket.OPEN) {
        // It may only look open. Probe, and hold it to a short deadline
        // rather than the full heartbeat interval.
        ping();
        if (probeTimer) clearTimeout(probeTimer);
        probeTimer = setTimeout(() => {
          if (awaitingPong && socket && socket.readyState === WebSocket.OPEN) {
            socket.close();
          }
        }, PONG_GRACE_MS);
        return;
      }
      if (retryTimer) clearTimeout(retryTimer);
      retryTimer = null;
      attempt = 0;
      connect();
    };

    const onVisible = () => {
      if (document.visibilityState === "visible") wake();
    };

    // The relay list must be in hand before the first RTCPeerConnection is
    // constructed - a peer connection cannot be given ICE servers after the
    // fact - so the socket waits on it. One fetch per page load, cached.
    void (async () => {
      iceConfigRef.current = await fetchIceConfig(participantId, wsToken);
      if (cancelled) return;
      connect();
    })();

    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      window.removeEventListener("online", wake);
      document.removeEventListener("visibilitychange", onVisible);
      clearTimers();
      const closing = socket;
      socket = null;
      closing?.close();
      wsRef.current = null;
      closePeers();
      screenTrackRef.current?.stop();
      startedRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [number, participantId, wsToken]);

  return {
    micOn,
    camOn,
    myName,
    toggleMic,
    toggleCam,
    peers,
    messages,
    sendChat,
    reactions,
    sendReaction,
    handRaised,
    toggleHand,
    isSharing,
    screenStream,
    startShare,
    stopShare,
    activeSpeakerId,
    spotlightId,
    spotlight,
    muteAll,
    mutePeer,
    askToUnmute,
    removePeer,
    lowerHand,
    endMeeting,
    renameSelf,
    status,
    admission,
    waitingList,
    hostPresent,
    settings,
    updateSettings,
    waitingRoomOn: settings.waiting_room,
    admitPeer,
    denyPeer,
    admitAll,
    toggleWaitingRoom,
  };
}
