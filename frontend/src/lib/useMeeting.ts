"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface RemotePeer {
  id: number;
  displayName: string;
  isHost: boolean;
  muted: boolean;
  videoOn: boolean;
  hand: boolean;
  sharing: boolean;
  stream: MediaStream | null;
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
  stream: MediaStream;
}

const ICE_SERVERS: RTCIceServer[] = [
  { urls: "stun:stun.l.google.com:19302" },
  { urls: "stun:stun1.l.google.com:19302" },
];

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

export interface UseMeetingOptions {
  number: string;
  participantId: number;
  wsToken: string;
  displayName: string;
  isHost: boolean;
  localStream: MediaStream | null;
  initialMicOn: boolean;
  initialCamOn: boolean;
  onRemoved?: () => void;
  onEnded?: () => void;
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
    onRemoved,
    onEnded,
  } = opts;

  const [micOn, setMicOn] = useState(initialMicOn);
  const [camOn, setCamOn] = useState(initialCamOn);
  const [peers, setPeers] = useState<RemotePeer[]>([]);
  const [messages, setMessages] = useState<LiveChatMessage[]>([]);
  const [reactions, setReactions] = useState<FloatingReaction[]>([]);
  const [handRaised, setHandRaised] = useState(false);
  const [isSharing, setIsSharing] = useState(false);
  const [screenStream, setScreenStream] = useState<MediaStream | null>(null);
  const [activeSpeakerId, setActiveSpeakerId] = useState<number | "me" | null>(null);
  const [status, setStatus] = useState<"connecting" | "live" | "error">("connecting");

  const wsRef = useRef<WebSocket | null>(null);
  const pcsRef = useRef<Map<number, PeerBox>>(new Map());
  const startedRef = useRef(false);
  const stateRef = useRef({ muted: !initialMicOn, videoOn: initialCamOn });
  const localStreamRef = useRef<MediaStream | null>(localStream);
  const screenTrackRef = useRef<MediaStreamTrack | null>(null);
  const sharingRef = useRef(false);
  const cameraTrackRef = useRef<MediaStreamTrack | null>(null);

  useEffect(() => {
    localStreamRef.current = localStream;
    cameraTrackRef.current = localStream?.getVideoTracks()[0] ?? null;
  }, [localStream]);

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
              hand: false,
              sharing: false,
              stream: null,
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

  const removePeerLocal = useCallback((id: number) => {
    const box = pcsRef.current.get(id);
    if (box) {
      box.pc.onicecandidate = null;
      box.pc.ontrack = null;
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

      const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
      const remoteStream = new MediaStream();
      pcsRef.current.set(peerId, { pc, stream: remoteStream });

      const local = localStreamRef.current;
      if (local) {
        for (const track of local.getTracks()) {
          if (track.kind === "video" && sharingRef.current && screenTrackRef.current) {
            pc.addTrack(screenTrackRef.current, local);
          } else {
            pc.addTrack(track, local);
          }
        }
      }

      pc.onicecandidate = (e) => {
        if (e.candidate) send({ type: "ice", to: peerId, candidate: e.candidate });
      };
      pc.ontrack = (e) => {
        for (const track of e.streams[0]?.getTracks() ?? [e.track]) {
          if (!remoteStream.getTracks().includes(track)) remoteStream.addTrack(track);
        }
        upsertPeer(peerId, { stream: remoteStream });
      };
      return pc;
    },
    [send, upsertPeer]
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
        { id: seq++, from: "me", sender: displayName, text: trimmed, self: true, time: nowTime() },
      ]);
      send({ type: "chat", text: trimmed });
    },
    [displayName, send]
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
  const removePeer = useCallback((id: number) => send({ type: "remove-peer", target: id }), [send]);
  const endMeeting = useCallback(() => send({ type: "end-meeting" }), [send]);

  const stopShare = useCallback(() => {
    const cam = cameraTrackRef.current;
    pcsRef.current.forEach(({ pc }) => {
      const sender = pc.getSenders().find((s) => s.track?.kind === "video");
      if (sender && cam) sender.replaceTrack(cam).catch(() => {});
    });
    screenTrackRef.current?.stop();
    screenTrackRef.current = null;
    sharingRef.current = false;
    setIsSharing(false);
    setScreenStream(null);
    send({ type: "share", on: false });
  }, [send]);

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
      sharingRef.current = true;
      setIsSharing(true);
      setScreenStream(display);
      pcsRef.current.forEach(({ pc }) => {
        const sender = pc.getSenders().find((s) => s.track?.kind === "video");
        if (sender) sender.replaceTrack(screenTrack).catch(() => {});
      });
      send({ type: "share", on: true });
      screenTrack.addEventListener("ended", stopShare);
    } catch {
    }
  }, [send, stopShare]);

  useEffect(() => {
    const AudioCtx =
      (window.AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext })
          .webkitAudioContext);
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
      pcsRef.current.forEach((box, id) => attach(id, box.stream));

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
    let cancelled = false;

    const url =
      `${wsBase()}/ws/meetings/${encodeURIComponent(number)}` +
      `?pid=${participantId}&token=${encodeURIComponent(wsToken)}` +
      `&muted=${stateRef.current.muted ? 1 : 0}&video=${stateRef.current.videoOn ? 1 : 0}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => !cancelled && setStatus("live");
    ws.onerror = () => !cancelled && setStatus("error");

    ws.onmessage = async (event) => {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case "peers":
          for (const peer of msg.peers as RemotePeer[]) {
            upsertPeer(peer.id, {}, peer);
            ensurePc(peer.id);
          }
          break;
        case "peer-joined": {
          const peer = msg.peer as RemotePeer;
          upsertPeer(peer.id, {}, peer);
          ensurePc(peer.id);
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
            {
              id: seq++,
              from: msg.from,
              sender: msg.displayName,
              text: msg.text,
              self: false,
              time: nowTime(),
            },
          ]);
          break;
        case "reaction":
          pushReaction(msg.from, msg.emoji);
          break;
        case "hand":
          upsertPeer(msg.from, { hand: msg.raised });
          break;
        case "share":
          upsertPeer(msg.from, { sharing: msg.on });
          break;
        case "force-mute":
          forceMuteSelf();
          break;
        case "removed":
          onRemoved?.();
          break;
        case "meeting-ended":
          onEnded?.();
          break;
        case "peer-left":
          removePeerLocal(msg.id);
          break;
      }
    };

    return () => {
      cancelled = true;
      wsRef.current?.close();
      wsRef.current = null;
      pcsRef.current.forEach((box) => box.pc.close());
      pcsRef.current.clear();
      screenTrackRef.current?.stop();
      startedRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [number, participantId, wsToken]);

  return {
    micOn,
    camOn,
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
    muteAll,
    mutePeer,
    removePeer,
    endMeeting,
    status,
  };
}
