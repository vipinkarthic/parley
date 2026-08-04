"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { JoinResult, Meeting, Participant } from "@/lib/types";
import { useMeeting } from "@/lib/useMeeting";
import { VideoTile } from "@/components/meeting/VideoTile";
import { ControlBar } from "@/components/meeting/ControlBar";
import { ParticipantsPanel } from "@/components/meeting/ParticipantsPanel";
import { ChatPanel } from "@/components/meeting/ChatPanel";
import { PreJoin } from "@/components/meeting/PreJoin";
import { ReactionsOverlay } from "@/components/meeting/ReactionsOverlay";
import { useToast } from "@/components/Toast";
import { formatMeetingNumber } from "@/lib/utils";
import { CheckIcon, CopyIcon, PinIcon, ShieldIcon } from "@/components/Icons";

type Panel = "participants" | "chat" | null;
type Phase = "loading" | "preview" | "in" | "notfound" | "left" | "removed" | "ended";

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
  const [defaultName, setDefaultName] = useState("Guest");
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [joined, setJoined] = useState<JoinedState | null>(null);
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
          setDefaultName("Guest");
        }
      }
      setPhase("preview");
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

  if (phase === "preview" && meeting) {
    const requirePasscode = !meeting.passcode && !pwd;
    return (
      <PreJoin
        meeting={meeting}
        defaultName={defaultName}
        requirePasscode={requirePasscode}
        joining={joining}
        error={joinError}
        onJoin={handleJoin}
      />
    );
  }

  return (
    <LiveRoom
      number={number}
      meeting={meeting!}
      joined={joined!}
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
  onExit,
  onToast,
}: {
  number: string;
  meeting: Meeting;
  joined: JoinedState;
  onExit: (phase: "left" | "removed" | "ended") => void;
  onToast: (m: string, k?: "success" | "error" | "info") => void;
}) {
  const isHost = joined.join.is_host;
  const myId = joined.join.id;
  const myName = joined.name;

  const m = useMeeting({
    number,
    participantId: myId,
    wsToken: joined.join.ws_token,
    displayName: myName,
    isHost,
    localStream: joined.stream,
    initialMicOn: joined.micOn,
    initialCamOn: joined.camOn,
    onRemoved: () => onExit("removed"),
    onEnded: () => onExit("ended"),
  });

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
  const handleRemove = (id: number, name: string) => {
    m.removePeer(id);
    onToast(`${name} was removed`, "success");
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
    videoOn: m.isSharing ? true : m.camOn,
    hand: m.handRaised,
    sharing: m.isSharing,
    mirror: !m.isSharing,
    stream: m.isSharing ? m.screenStream : joined.stream,
  };
  const peerTiles: Tile[] = m.peers.map((p) => ({
    key: p.id,
    name: p.displayName,
    isSelf: false,
    isHost: p.isHost,
    muted: p.muted,
    videoOn: p.sharing ? true : p.videoOn,
    hand: p.hand,
    sharing: p.sharing,
    mirror: false,
    stream: p.stream,
  }));
  const tiles = [selfTile, ...peerTiles];
  const total = tiles.length;

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
        title="Pin / spotlight"
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

  const mainTile =
    tiles.find((t) => t.key === pinnedId) ||
    tiles.find((t) => t.sharing) ||
    tiles.find((t) => t.key === m.activeSpeakerId) ||
    selfTile;
  const filmstrip = tiles.filter((t) => t.key !== mainTile.key);

  const panelParticipants: Participant[] = [
    { id: myId, display_name: myName, is_host: isHost, is_muted: !m.micOn, is_video_on: m.camOn, is_active: true, joined_at: "" },
    ...m.peers.map((p) => ({
      id: p.id, display_name: p.displayName, is_host: p.isHost, is_muted: p.muted,
      is_video_on: p.videoOn, is_active: true, joined_at: "",
    })),
  ];

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

      <div className="flex min-h-0 flex-1">
        <div className="relative flex min-w-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto p-3 sm:p-5">
            {view === "gallery" ? (
              <div className={`grid gap-3 ${galleryClass}`}>{tiles.map(renderTile)}</div>
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

            {total === 1 && (
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
                  participants={panelParticipants}
                  myId={myId}
                  isHost={isHost}
                  onClose={() => setPanel(null)}
                  onToggleMute={(p) => m.mutePeer(p.id)}
                  onRemove={(p) => handleRemove(p.id, p.display_name)}
                  onMuteAll={handleMuteAll}
                />
              ) : (
                <ChatPanel messages={m.messages} onSend={m.sendChat} onClose={() => setPanel(null)} />
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
