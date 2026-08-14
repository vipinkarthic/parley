"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchIceConfig, type IceConfig } from "./api";
import type { MeetingSettings } from "./types";

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

export interface WaitingPerson {
  id: number;
  displayName: string;
}

interface PeerBox {
  pc: RTCPeerConnection;
  streams: Map<string, MediaStream>;
  screenSid: string | null;
  screenSender: RTCRtpSender | null;
}

// Used only until GET /api/ice answers. STUN alone cannot relay media, so a
// peer behind symmetric NAT or a corporate firewall has no path at all with
// this list - which is why the real one is fetched rather than compiled in.
const ICE_FALLBACK: IceConfig = {
  iceServers: [
    { urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] },
  ],
};

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

function nowTime(): string {
  const d = new Date();
  let h = d.getHours();
  const m = d.getMinutes().toString().padStart(2, "0");
  const ampm = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${h}:${m} ${ampm}`;
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

// Close codes the client must not retry: the participant is not coming back
// into this meeting, so retrying would be an infinite loop against a server
// that is answering correctly. See the matching constants in ws.py.
const TERMINAL_CLOSE_CODES = new Set([
  4001, // malformed participant id
  4003, // token rejected
  4004, // the host denied this guest
  4005, // the meeting has ended
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
  const iceConfigRef = useRef<IceConfig>(ICE_FALLBACK);
  const startedRef = useRef(false);
  const stateRef = useRef({ muted: !initialMicOn, videoOn: initialCamOn });
  const localStreamRef = useRef<MediaStream | null>(localStream);
  const screenTrackRef = useRef<MediaStreamTrack | null>(null);
  const screenStreamRef = useRef<MediaStream | null>(null);
  const sharingRef = useRef(false);
  const handRaisedRef = useRef(false);
  const myNameRef = useRef(displayName);

  useEffect(() => {
    localStreamRef.current = localStream;
    // keep the real tracks matching the mic/cam state, else the UI says muted while audio is still live
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
    setPeers((prev) => prev.filter((p) => p.id !== id));
  }, []);

  const send = useCallback((msg: object) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }, []);

  const ensurePc = useCallback(
    (peerId: number): RTCPeerConnection => {
      const existing = pcsRef.current.get(peerId);
      if (existing) return existing.pc;

      const cfg = iceConfigRef.current;
      const pc = new RTCPeerConnection({
        iceServers: cfg.iceServers,
        iceCandidatePoolSize: cfg.iceCandidatePoolSize,
      });
      const box: PeerBox = { pc, streams: new Map(), screenSid: null, screenSender: null };
      pcsRef.current.set(peerId, box);

      const local = localStreamRef.current;
      if (local) for (const t of local.getTracks()) pc.addTrack(t, local);
      if (sharingRef.current && screenTrackRef.current && screenStreamRef.current) {
        box.screenSender = pc.addTrack(screenTrackRef.current, screenStreamRef.current);
      }

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
    [send, recompute, participantId]
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
        { id: seq++, from: "me", sender: myNameRef.current, text: trimmed, self: true, time: nowTime() },
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

  useEffect(() => {
    const AudioCtx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const analysers = new Map<
      number | "me",
      { node: AnalyserNode; data: Uint8Array<ArrayBuffer> }
    >();

    const attach = (idKey: number | "me", stream: MediaStream | null) => {
      if (!stream || analysers.has(idKey) || stream.getAudioTracks().length === 0)
        return;
      try {
        const src = ctx.createMediaStreamSource(stream);
        const node = ctx.createAnalyser();
        node.fftSize = 512;
        src.connect(node);
        analysers.set(idKey, {
          node,
          data: new Uint8Array(new ArrayBuffer(node.frequencyBinCount)),
        });
      } catch {
      }
    };

    const interval = setInterval(() => {
      attach("me", localStreamRef.current);
      pcsRef.current.forEach((box, id) => {
        for (const s of Array.from(box.streams.values())) {
          if (s.getAudioTracks().length) {
            attach(id, s);
            break;
          }
        }
      });

      let loudest: number | "me" | null = null;
      let max = 12;
      analysers.forEach(({ node, data }, idKey) => {
        node.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i];
        const avg = sum / data.length;
        if (idKey === "me" && stateRef.current.muted) return;
        if (avg > max) {
          max = avg;
          loudest = idKey;
        }
      });
      setActiveSpeakerId(loudest);
    }, 500);

    return () => {
      clearInterval(interval);
      ctx.close().catch(() => {});
    };
  }, []);

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
            // The lower participant id owns the offer for a pair. Ids are
            // handed out in ascending order, so on a first join ours is
            // always the highest and the peers already in the room do the
            // offering - which is why this loop never used to offer at all.
            // A reconnect keeps our original, lower id, and then every peer
            // evaluates "their id < ours" as false and nobody offers: the
            // socket comes back and the video never does.
            if (participantId < peer.id) makeOffer(peer.id);
          }
          break;
        case "peer-joined": {
          const peer = msg.peer as RemotePeer;
          upsertPeer(peer.id, {}, peer);
          ensurePc(peer.id);
          applyPeerShareInfo(peer);
          if (participantId < peer.id) makeOffer(peer.id);
          break;
        }
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
            { id: seq++, from: msg.from, sender: msg.displayName, text: msg.text, self: false, time: nowTime() },
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
      iceConfigRef.current = await fetchIceConfig();
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
