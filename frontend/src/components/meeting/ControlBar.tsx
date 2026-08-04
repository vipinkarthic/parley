"use client";

import { useState, type ReactNode } from "react";
import {
  ChatIcon,
  HandIcon,
  MicIcon,
  MicOffIcon,
  PhoneEndIcon,
  ScreenShareIcon,
  ShieldIcon,
  UsersIcon,
  VideoCamIcon,
  VideoOffIcon,
} from "@/components/Icons";

const REACTIONS = ["👍", "❤️", "😂", "🎉", "👏", "😮"];

function Control({
  icon,
  label,
  onClick,
  active = false,
  badge,
}: {
  icon: ReactNode;
  label: string;
  onClick?: () => void;
  active?: boolean;
  badge?: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`relative flex min-w-[60px] flex-col items-center gap-1 rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition-colors ${
        active ? "text-zoom-blue" : "text-white/85 hover:bg-white/10"
      }`}
    >
      <span className="grid h-9 w-9 place-items-center rounded-lg">{icon}</span>
      <span className="leading-none">{label}</span>
      {badge !== undefined && badge > 0 && (
        <span className="absolute right-1.5 top-0 grid h-4 min-w-4 place-items-center rounded-full bg-zoom-blue px-1 text-[10px] font-bold text-white">
          {badge}
        </span>
      )}
    </button>
  );
}

export function ControlBar({
  micOn,
  camOn,
  onToggleMic,
  onToggleCam,
  onToggleParticipants,
  onToggleChat,
  isSharing,
  onToggleShare,
  handRaised,
  onToggleHand,
  onReact,
  view,
  onToggleView,
  isHost,
  onMuteAll,
  onLeave,
  onEndForAll,
  participantsActive,
  chatActive,
  participantCount,
}: {
  micOn: boolean;
  camOn: boolean;
  onToggleMic: () => void;
  onToggleCam: () => void;
  onToggleParticipants: () => void;
  onToggleChat: () => void;
  isSharing: boolean;
  onToggleShare: () => void;
  handRaised: boolean;
  onToggleHand: () => void;
  onReact: (emoji: string) => void;
  view: "gallery" | "speaker";
  onToggleView: () => void;
  isHost: boolean;
  onMuteAll: () => void;
  onLeave: () => void;
  onEndForAll: () => void;
  participantsActive: boolean;
  chatActive: boolean;
  participantCount: number;
}) {
  const [reactOpen, setReactOpen] = useState(false);
  const [leaveOpen, setLeaveOpen] = useState(false);

  return (
    <div className="flex items-center justify-center gap-0.5 border-t border-white/10 bg-zoom-darker px-2 py-2.5">
      <Control
        icon={micOn ? <MicIcon className="h-5 w-5" /> : <MicOffIcon className="h-5 w-5 text-[#FF6B6B]" />}
        label={micOn ? "Mute" : "Unmute"}
        onClick={onToggleMic}
      />
      <Control
        icon={camOn ? <VideoCamIcon className="h-5 w-5" /> : <VideoOffIcon className="h-5 w-5 text-[#FF6B6B]" />}
        label={camOn ? "Stop Video" : "Start Video"}
        onClick={onToggleCam}
      />

      <div className="mx-1 h-8 w-px bg-white/10" />

      <Control
        icon={<UsersIcon className="h-5 w-5" />}
        label="Participants"
        onClick={onToggleParticipants}
        active={participantsActive}
        badge={participantCount}
      />
      <Control icon={<ChatIcon className="h-5 w-5" />} label="Chat" onClick={onToggleChat} active={chatActive} />
      <Control
        icon={<ScreenShareIcon className="h-5 w-5" />}
        label={isSharing ? "Stop Share" : "Share"}
        onClick={onToggleShare}
        active={isSharing}
      />

      <div className="relative">
        <Control
          icon={<span className="text-lg leading-none">😊</span>}
          label="React"
          onClick={() => setReactOpen((v) => !v)}
          active={reactOpen}
        />
        {reactOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setReactOpen(false)} />
            <div className="absolute bottom-16 left-1/2 z-20 flex -translate-x-1/2 gap-1 rounded-full bg-zoom-panel px-2 py-1.5 shadow-modal animate-scale-in">
              {REACTIONS.map((e) => (
                <button
                  key={e}
                  onClick={() => {
                    onReact(e);
                    setReactOpen(false);
                  }}
                  className="grid h-9 w-9 place-items-center rounded-full text-xl transition-transform hover:scale-125"
                >
                  {e}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      <Control
        icon={<HandIcon className="h-5 w-5" />}
        label="Raise Hand"
        onClick={onToggleHand}
        active={handRaised}
      />
      <Control
        icon={<span className="grid h-5 w-5 grid-cols-2 gap-0.5">{[0,1,2,3].map(i=>(<span key={i} className="rounded-[1px] bg-current" />))}</span>}
        label={view === "gallery" ? "Speaker" : "Gallery"}
        onClick={onToggleView}
      />
      {isHost && (
        <Control icon={<ShieldIcon className="h-5 w-5" />} label="Mute All" onClick={onMuteAll} />
      )}

      <div className="mx-1 h-8 w-px bg-white/10" />

      <div className="relative">
        <button
          onClick={() => (isHost ? setLeaveOpen((v) => !v) : onLeave())}
          className="ml-1 rounded-lg bg-[#E02D2D] px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#C42525]"
        >
          <span className="flex items-center gap-2">
            <PhoneEndIcon className="h-5 w-5" />
            {isHost ? "End" : "Leave"}
          </span>
        </button>
        {isHost && leaveOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setLeaveOpen(false)} />
            <div className="absolute bottom-14 right-0 z-20 w-52 overflow-hidden rounded-xl bg-white py-1 text-zoom-ink shadow-modal animate-scale-in">
              <button
                onClick={() => { setLeaveOpen(false); onEndForAll(); }}
                className="block w-full px-4 py-2.5 text-left text-sm font-medium text-[#E02D2D] hover:bg-[#FEF3F2]"
              >
                End meeting for all
              </button>
              <button
                onClick={() => { setLeaveOpen(false); onLeave(); }}
                className="block w-full px-4 py-2.5 text-left text-sm text-zoom-ink hover:bg-zoom-field"
              >
                Leave meeting
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
