"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { JoinResult, Meeting, Preferences } from "@/lib/types";
import { useMeeting } from "@/lib/useMeeting";
import { VideoTile } from "@/components/meeting/VideoTile";
import { ControlBar } from "@/components/meeting/ControlBar";
import { ParticipantsPanel, type PanelPerson } from "@/components/meeting/ParticipantsPanel";
import { ChatPanel } from "@/components/meeting/ChatPanel";
import { PreJoin } from "@/components/meeting/PreJoin";
import { ReactionsOverlay } from "@/components/meeting/ReactionsOverlay";
import { useToast } from "@/components/Toast";
import { formatMeetingNumber, formatMeetingTime } from "@/lib/utils";
import { CheckIcon, ClockIcon, CopyIcon, PinIcon, ShieldIcon } from "@/components/Icons";

type Panel = "participants" | "chat" | null;
type Phase =
  | "loading"
  | "scheduled"
  | "preview"
  | "in"
  | "notfound"
  | "left"
  | "removed"
  | "ended"
  | "denied";

interface JoinedState {
  join: JoinResult;
  name: string;
  stream: MediaStream | null;
  micOn: boolean;
  camOn: boolean;
}

export default function MeetingRoomPage() {
  const params = useParams<{ number: string }>();
  const search = useSearchParams();
  const toast = useToast();
  const number = params.number;

  const [phase, setPhase] = useState<Phase>("loading");
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [defaultName, setDefaultName] = useState("");
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [joined, setJoined] = useState<JoinedState | null>(null);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const pwd = search.get("pwd") || "";

  useEffect(() => {
    (async () => {
      let m: Meeting;
      try {
        m = await api.getMeeting(number);
      } catch {
        setPhase("notfound");
        return;
      }
      if (m.status === "ended") {
        setPhase("notfound");
        return;
      }
      setMeeting(m);
      const qName = search.get("name");
      if (qName) setDefaultName(qName);
      else {
        try {
          setDefaultName((await api.me()).name);
        } catch {
          setDefaultName("");
        }
      }
      try {
        setPrefs(await api.preferences());
      } catch {
      }
      const isHostViewer = !!m.passcode;
      const notStarted =
        m.meeting_type === "scheduled" &&
        m.start_time !== null &&
        new Date(m.start_time).getTime() > Date.now();
      if (notStarted && !isHostViewer && !m.settings.join_before_host) {
        setPhase("scheduled");
      } else {
        setPhase("preview");
      }
    })();
  }, [number, search]);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => () => stopStream(), [stopStream]);

  const handleJoin = async (o: {
    name: string;
    passcode: string;
    stream: MediaStream | null;
    micOn: boolean;
    camOn: boolean;
  }) => {
    if (joining) return;
    setJoining(true);
    setJoinError(null);
    try {
      const passcode = meeting?.passcode || pwd || o.passcode;
      const join = await api.join(number, o.name, passcode);
      streamRef.current = o.stream;
      setJoined({ join, name: o.name, stream: o.stream, micOn: o.micOn, camOn: o.camOn });
      setPhase("in");
    } catch (err) {
      if (err instanceof ApiError && err.status === 425) {
        setJoining(false);
        setPhase("scheduled");
        return;
      }
      setJoinError(
        err instanceof ApiError ? err.message : "Could not join the meeting."
      );
      setJoining(false);
    }
  };

  if (phase === "loading") {
    return (
      <Centered>
        <span className="h-9 w-9 animate-spin rounded-full border-[3px] border-white/20 border-t-white" />
        <p className="text-sm text-white/70">Loading meeting…</p>
      </Centered>
    );
  }

  if (phase === "notfound") {
    return (
      <Centered>
        <p className="text-lg font-semibold">This meeting isn&apos;t available</p>
        <p className="text-sm text-white/60">It may have ended or the ID is incorrect.</p>
        <Link href="/" className="btn-primary mt-2">Back to home</Link>
      </Centered>
    );
  }

  if (phase === "removed") {
    return (
      <Centered>
        <p className="text-lg font-semibold">You were removed from the meeting</p>
        <p className="text-sm text-white/60">The host removed you from this call.</p>
        <Link href="/" className="btn-primary mt-2">Back to home</Link>
      </Centered>
    );
  }

  if (phase === "denied") {
    return (
      <Centered>
        <p className="text-lg font-semibold">The host didn&apos;t admit you</p>
        <p className="text-sm text-white/60">
          Your request to join this meeting was declined.
        </p>
        <Link href="/" className="btn-primary mt-2">Back to home</Link>
      </Centered>
    );
  }

  if (phase === "ended") {
    return (
      <Centered>
        <p className="text-lg font-semibold">This meeting has ended</p>
        <p className="text-sm text-white/60">The host ended the meeting for everyone.</p>
        <Link href="/" className="btn-primary mt-2">Back to home</Link>
      </Centered>
    );
  }

  if (phase === "left") {
    return (
      <Centered>
        <div className="mx-auto mb-1 grid h-14 w-14 place-items-center rounded-full bg-white/10">
          <CheckIcon className="h-7 w-7 text-[#12B76A]" />
        </div>
        <p className="text-lg font-semibold">You left the meeting</p>
        <div className="mt-3 flex gap-3">
          <Link href="/" className="btn-outline !border-white/30 !bg-transparent !text-white hover:!bg-white/10">
            Back to home
          </Link>
          <button onClick={() => location.reload()} className="btn-primary">Rejoin</button>
        </div>
      </Centered>
    );
  }

  if (phase === "scheduled" && meeting) {
    return (
      <ScheduledGate
        meeting={meeting}
        onReady={() => setPhase("preview")}
      />
    );
  }

  if (phase === "preview" && meeting) {
    const requirePasscode = !meeting.passcode && !pwd;
    return (
      <PreJoin
        meeting={meeting}
        defaultName={defaultName}
        requirePasscode={requirePasscode}
        joining={joining}
        error={joinError}
        initialMicOn={prefs ? !prefs.pref_join_muted : true}
        initialCamOn={prefs ? prefs.pref_video_on_join : true}
        onJoin={handleJoin}
      />
    );
  }

  return (
    <LiveRoom
      number={number}
      meeting={meeting!}
      joined={joined!}
      mirrorVideo={prefs ? prefs.pref_mirror_video : true}
      onExit={(p) => {
        stopStream();
        setPhase(p);
      }}
      onToast={toast}
    />
  );
}

function LiveRoom({
  number,
  meeting,
  joined,
  mirrorVideo,
  onExit,
  onToast,
}: {
  number: string;
  meeting: Meeting;
  joined: JoinedState;
  mirrorVideo: boolean;
  onExit: (phase: "left" | "removed" | "ended" | "denied") => void;
  onToast: (m: string, k?: "success" | "error" | "info") => void;
}) {
  const isHost = joined.join.is_host;
  const myId = joined.join.id;

  const m = useMeeting({
    number,
    participantId: myId,
    wsToken: joined.join.ws_token,
    displayName: joined.name,
    isHost,
    localStream: joined.stream,
    initialMicOn: joined.micOn && !(meeting.settings.mute_on_entry && !isHost),
    initialCamOn: joined.camOn,
    initialAdmission: joined.join.admission,
    initialSettings: meeting.settings,
    onRemoved: () => onExit("removed"),
    onEnded: () => onExit("ended"),
    onDenied: () => onExit("denied"),
    onAskUnmute: () => onToast("The host is asking you to unmute", "info"),
    onShareDenied: () => onToast("The host has disabled screen sharing", "info"),
  });
  const myName = m.myName;

  const prevWaiting = useRef(0);
  useEffect(() => {
    if (isHost && m.waitingList.length > prevWaiting.current) {
      const newest = m.waitingList[m.waitingList.length - 1];
      onToast(`${newest.displayName} is waiting to join`, "info");
    }
    prevWaiting.current = m.waitingList.length;
  }, [m.waitingList, isHost, onToast]);

  const [panel, setPanel] = useState<Panel>(null);
  const [view, setView] = useState<"gallery" | "speaker">("gallery");
  const [pinnedId, setPinnedId] = useState<number | "me" | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const sharingPeer = m.peers.find((p) => p.sharing);
  const sharingKey: number | "me" | null = m.isSharing
    ? "me"
    : sharingPeer
    ? sharingPeer.id
    : null;
  useEffect(() => {
    if (sharingKey !== null) {
      setPinnedId(sharingKey);
      setView("speaker");
    }
  }, [sharingKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const copyInvite = async () => {
    await navigator.clipboard.writeText(meeting.invite_link);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const toggleShare = () => {
    if (m.isSharing) m.stopShare();
    else if (!joined.stream) onToast("Enable your camera/mic to share your screen", "info");
    else m.startShare();
  };

  const handleMuteAll = () => {
    m.muteAll();
    onToast("Muted everyone", "success");
  };
  const handleRemove = (id: number) => {
    const peer = m.peers.find((p) => p.id === id);
    m.removePeer(id);
    onToast(`${peer?.displayName ?? "Participant"} was removed`, "success");
  };
  const endForAll = () => {
    m.endMeeting();
    onExit("ended");
  };

  type Tile = {
    key: number | "me";
    name: string;
    isSelf: boolean;
    isHost: boolean;
    muted: boolean;
    videoOn: boolean;
    hand: boolean;
    sharing: boolean;
    mirror: boolean;
    stream: MediaStream | null;
  };
  const selfTile: Tile = {
    key: "me",
    name: myName,
    isSelf: true,
    isHost,
    muted: !m.micOn,
    videoOn: m.camOn,
    hand: m.handRaised,
    sharing: m.isSharing,
    mirror: mirrorVideo,
    stream: joined.stream,
  };
  const peerTiles: Tile[] = m.peers.map((p) => ({
    key: p.id,
    name: p.displayName,
    isSelf: false,
    isHost: p.isHost,
    muted: p.muted,
    videoOn: p.videoOn,
    hand: p.hand,
    sharing: p.sharing,
    mirror: false,
    stream: p.cameraStream,
  }));
  const tiles = [selfTile, ...peerTiles];
  const total = tiles.length;

  const screenShare: { name: string; stream: MediaStream | null } | null = m.isSharing
    ? { name: `${myName} (You)`, stream: m.screenStream }
    : (() => {
        const sp = m.peers.find((p) => p.sharing && p.screenStream);
        return sp ? { name: sp.displayName, stream: sp.screenStream } : null;
      })();

  const renderTile = (t: Tile) => (
    <div key={t.key} className="group relative">
      <VideoTile
        name={t.name}
        isSelf={t.isSelf}
        isHost={t.isHost}
        muted={t.muted}
        videoOn={t.videoOn}
        hand={t.hand}
        sharing={t.sharing}
        mirror={t.mirror}
        speaking={m.activeSpeakerId === t.key}
        stream={t.stream}
      />
      <button
        onClick={() => {
          setPinnedId((cur) => (cur === t.key && view === "speaker" ? null : t.key));
          setView((v) => (pinnedId === t.key && v === "speaker" ? "gallery" : "speaker"));
        }}
        className="absolute right-2 bottom-2 hidden h-7 w-7 place-items-center rounded-md bg-black/50 text-white opacity-0 transition-opacity hover:bg-black/70 group-hover:opacity-100 group-hover:grid"
        title="Pin"
      >
        <PinIcon className="h-4 w-4" />
      </button>
    </div>
  );

  const galleryClass =
    total <= 1 ? "grid-cols-1 max-w-3xl mx-auto"
    : total === 2 ? "grid-cols-1 sm:grid-cols-2"
    : total <= 4 ? "grid-cols-1 sm:grid-cols-2"
    : total <= 9 ? "grid-cols-2 lg:grid-cols-3"
    : "grid-cols-2 lg:grid-cols-4";

  const focusKey = m.spotlightId ?? pinnedId;
  const mainTile =
    tiles.find((t) => t.key === focusKey) ||
    tiles.find((t) => t.key === m.activeSpeakerId) ||
    selfTile;
  const filmstrip = tiles.filter((t) => t.key !== mainTile.key);

  const people: PanelPerson[] = [
    { id: myId, name: myName, isHost, muted: !m.micOn, hand: m.handRaised, isSelf: true },
    ...m.peers.map((p) => ({
      id: p.id, name: p.displayName, isHost: p.isHost, muted: p.muted, hand: p.hand, isSelf: false,
    })),
  ];

  if (m.admission === "waiting") {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-zoom-dark px-4 text-center text-white">
        <span className="h-12 w-12 animate-spin rounded-full border-[3px] border-white/20 border-t-white" />
        <div>
          <p className="text-lg font-semibold">Please wait, the meeting host will let you in soon</p>
          <p className="mt-1 text-sm text-white/60">
            {m.hostPresent
              ? `"${meeting.topic}" — waiting for the host to admit you`
              : "Waiting for the host to start this meeting"}
          </p>
        </div>
        <p className="text-sm text-white/50">Joining as {myName}</p>
        <button
          onClick={() => onExit("left")}
          className="mt-2 rounded-full bg-white/10 px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-white/20"
        >
          Leave
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col bg-zoom-dark text-white">
      <header className="flex items-center justify-between gap-3 bg-zoom-darker px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid h-8 w-8 place-items-center rounded-md bg-[#12B76A]/15 text-[#12B76A]">
            <ShieldIcon className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{meeting.topic}</p>
            <p className="text-xs text-white/50">
              ID: {formatMeetingNumber(number)}
              {meeting.passcode ? ` · Passcode: ${meeting.passcode}` : ""}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`hidden items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium sm:flex ${
              m.status === "live" ? "bg-[#12B76A]/15 text-[#12B76A]" : "bg-white/10 text-white/70"
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${m.status === "live" ? "bg-[#12B76A]" : "bg-white/50"}`} />
            {m.status === "live" ? "Live" : m.status === "error" ? "Reconnecting…" : "Connecting…"}
          </span>
          <span className="hidden rounded-md bg-white/10 px-2.5 py-1 text-xs font-medium tabular-nums sm:block">
            {formatElapsed(elapsed)}
          </span>
          <button
            onClick={copyInvite}
            className="flex items-center gap-1.5 rounded-md bg-white/10 px-3 py-1.5 text-xs font-medium transition-colors hover:bg-white/15"
          >
            {copied ? <CheckIcon className="h-4 w-4 text-[#12B76A]" /> : <CopyIcon className="h-4 w-4" />}
            {copied ? "Copied" : "Invite"}
          </button>
        </div>
      </header>

      {isHost && m.waitingList.length > 0 && (
        <div className="flex items-center justify-between gap-3 bg-[#FFB020] px-4 py-2 text-sm font-medium text-[#1A1A24]">
          <span>
            {m.waitingList.length === 1
              ? `${m.waitingList[0].displayName} is waiting`
              : `${m.waitingList.length} people are waiting`}{" "}
            to join
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPanel("participants")}
              className="rounded-full bg-black/10 px-3 py-1 text-xs font-semibold hover:bg-black/20"
            >
              View
            </button>
            <button
              onClick={m.admitAll}
              className="rounded-full bg-[#1A1A24] px-3 py-1 text-xs font-semibold text-white hover:bg-black"
            >
              Admit all
            </button>
          </div>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="relative flex min-w-0 flex-1 flex-col">
          <div className="flex-1 overflow-hidden p-3 sm:p-5">
            {screenShare ? (
              <div className="flex h-full gap-3">
                <div className="min-w-0 flex-1">
                  <ScreenView name={screenShare.name} stream={screenShare.stream} />
                </div>
                <div className="scroll-thin-dark flex w-44 shrink-0 flex-col gap-3 overflow-y-auto sm:w-52">
                  {tiles.map(renderTile)}
                </div>
              </div>
            ) : view === "gallery" ? (
              <div className={`grid h-full gap-3 overflow-y-auto ${galleryClass}`}>
                {tiles.map(renderTile)}
              </div>
            ) : (
              <div className="flex h-full flex-col gap-3">
                <div className="min-h-0 flex-1">{renderTile(mainTile)}</div>
                {filmstrip.length > 0 && (
                  <div className="flex gap-3 overflow-x-auto pb-1">
                    {filmstrip.map((t) => (
                      <div key={t.key} className="w-48 shrink-0">
                        {renderTile(t)}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {total === 1 && !screenShare && (
              <p className="mt-6 text-center text-sm text-white/50">
                You&apos;re the only one here. Share the invite link to bring others in.
              </p>
            )}
          </div>
          <ReactionsOverlay reactions={m.reactions} />
        </div>

        {panel && (
          <>
            <div className="fixed inset-0 z-20 bg-black/40 md:hidden" onClick={() => setPanel(null)} />
            <aside className="fixed inset-y-0 right-0 z-30 w-[340px] max-w-[85vw] bg-white text-zoom-ink shadow-modal md:static md:z-0 md:w-[340px] md:shadow-none md:ring-1 md:ring-zoom-line">
              {panel === "participants" ? (
                <ParticipantsPanel
                  people={people}
                  waiting={m.waitingList}
                  isHost={isHost}
                  waitingRoomOn={m.waitingRoomOn}
                  allowRename={m.settings.allow_rename}
                  onClose={() => setPanel(null)}
                  onMute={m.mutePeer}
                  onAskUnmute={m.askToUnmute}
                  onRemove={handleRemove}
                  onSpotlight={m.spotlight}
                  onLowerHand={m.lowerHand}
                  onRenameSelf={m.renameSelf}
                  onMuteAll={handleMuteAll}
                  onAdmit={m.admitPeer}
                  onDeny={m.denyPeer}
                  onAdmitAll={m.admitAll}
                  onToggleWaitingRoom={m.toggleWaitingRoom}
                />
              ) : (
                <ChatPanel
                  messages={m.messages}
                  onSend={m.sendChat}
                  onClose={() => setPanel(null)}
                  disabled={!isHost && !m.settings.allow_chat}
                />
              )}
            </aside>
          </>
        )}
      </div>

      <ControlBar
        micOn={m.micOn}
        camOn={m.camOn}
        onToggleMic={m.toggleMic}
        onToggleCam={m.toggleCam}
        onToggleParticipants={() => setPanel((p) => (p === "participants" ? null : "participants"))}
        onToggleChat={() => setPanel((p) => (p === "chat" ? null : "chat"))}
        isSharing={m.isSharing}
        onToggleShare={toggleShare}
        handRaised={m.handRaised}
        onToggleHand={m.toggleHand}
        onReact={m.sendReaction}
        view={view}
        onToggleView={() => setView((v) => (v === "gallery" ? "speaker" : "gallery"))}
        isHost={isHost}
        settings={m.settings}
        onUpdateSettings={m.updateSettings}
        onMuteAll={handleMuteAll}
        onLeave={() => onExit("left")}
        onEndForAll={endForAll}
        participantsActive={panel === "participants"}
        chatActive={panel === "chat"}
        participantCount={total}
      />
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-3 bg-zoom-dark px-4 text-center text-white">
      {children}
    </div>
  );
}

function formatElapsed(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
}

function ScreenView({ name, stream }: { name: string; stream: MediaStream | null }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (ref.current && stream && ref.current.srcObject !== stream) {
      ref.current.srcObject = stream;
    }
  }, [stream]);
  return (
    <div className="relative flex h-full items-center justify-center overflow-hidden rounded-xl bg-black ring-1 ring-white/10">
      <video ref={ref} autoPlay playsInline muted className="max-h-full max-w-full object-contain" />
      <div className="absolute left-3 top-3 rounded-md bg-black/60 px-2.5 py-1 text-xs font-medium text-white backdrop-blur-sm">
        {name} is sharing
      </div>
    </div>
  );
}

function ScheduledGate({
  meeting,
  onReady,
}: {
  meeting: Meeting;
  onReady: () => void;
}) {
  const [now, setNow] = useState(Date.now());
  const start = meeting.start_time ? new Date(meeting.start_time).getTime() : 0;
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    if (start && now >= start) onReady();
  }, [now, start, onReady]);

  const remaining = Math.max(0, Math.floor((start - now) / 1000));
  const d = Math.floor(remaining / 86400);
  const h = Math.floor((remaining % 86400) / 3600);
  const mm = Math.floor((remaining % 3600) / 60);
  const ss = remaining % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  const countdown =
    d > 0 ? `${d}d ${h}h ${mm}m` : h > 0 ? `${h}:${pad(mm)}:${pad(ss)}` : `${pad(mm)}:${pad(ss)}`;

  return (
    <Centered>
      <div className="mx-auto mb-1 grid h-14 w-14 place-items-center rounded-full bg-white/10">
        <ClockIcon className="h-7 w-7 text-white/80" />
      </div>
      <p className="text-lg font-semibold">{meeting.topic}</p>
      <p className="text-sm text-white/60">
        This meeting is scheduled for {formatMeetingTime(meeting.start_time)}
      </p>
      <p className="mt-2 text-3xl font-bold tabular-nums">{countdown}</p>
      <p className="text-xs text-white/50">until it starts — you&apos;ll join automatically</p>
      <Link
        href="/"
        className="btn-outline mt-4 !border-white/30 !bg-transparent !text-white hover:!bg-white/10"
      >
        Back to home
      </Link>
    </Centered>
  );
}
