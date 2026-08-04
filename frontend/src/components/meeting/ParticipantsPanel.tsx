"use client";

import { useState } from "react";
import type { Participant } from "@/lib/types";
import { Avatar } from "@/components/Avatar";
import {
  CloseIcon,
  MicIcon,
  MicOffIcon,
  MoreIcon,
  ShieldIcon,
} from "@/components/Icons";

export function ParticipantsPanel({
  participants,
  myId,
  isHost,
  onClose,
  onToggleMute,
  onRemove,
  onMuteAll,
}: {
  participants: Participant[];
  myId: number | null;
  isHost: boolean;
  onClose: () => void;
  onToggleMute: (p: Participant) => void;
  onRemove: (p: Participant) => void;
  onMuteAll: () => void;
}) {
  const [menuFor, setMenuFor] = useState<number | null>(null);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-zoom-line px-4 py-3">
        <h3 className="font-semibold text-zoom-ink">
          Participants{" "}
          <span className="text-zoom-muted">({participants.length})</span>
        </h3>
        <button
          onClick={onClose}
          aria-label="Close panel"
          className="grid h-7 w-7 place-items-center rounded-full text-zoom-muted hover:bg-black/5"
        >
          <CloseIcon className="h-4 w-4" />
        </button>
      </div>

      <div className="scroll-thin flex-1 overflow-y-auto px-2 py-2">
        {participants.map((p) => {
          const isMe = p.id === myId;
          return (
            <div
              key={p.id}
              className="group relative flex items-center gap-3 rounded-lg px-2 py-2 hover:bg-zoom-field"
            >
              <Avatar name={p.display_name} size={36} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-zoom-ink">
                  {p.display_name}
                  {isMe && " (You)"}
                </p>
                {p.is_host && (
                  <p className="inline-flex items-center gap-1 text-xs text-zoom-muted">
                    <ShieldIcon className="h-3 w-3" /> Host
                  </p>
                )}
              </div>

              <span className="text-zoom-muted">
                {p.is_muted ? (
                  <MicOffIcon className="h-4 w-4 text-[#EF4444]" />
                ) : (
                  <MicIcon className="h-4 w-4 text-[#12B76A]" />
                )}
              </span>

              {isHost && !isMe && (
                <div className="relative">
                  <button
                    onClick={() =>
                      setMenuFor(menuFor === p.id ? null : p.id)
                    }
                    className="grid h-7 w-7 place-items-center rounded-full text-zoom-muted opacity-0 transition-opacity hover:bg-black/10 group-hover:opacity-100"
                    aria-label="Manage participant"
                  >
                    <MoreIcon className="h-4 w-4" />
                  </button>
                  {menuFor === p.id && (
                    <>
                      <div
                        className="fixed inset-0 z-10"
                        onClick={() => setMenuFor(null)}
                      />
                      <div className="absolute right-0 top-8 z-20 w-40 overflow-hidden rounded-lg border border-zoom-line bg-white py-1 shadow-modal animate-scale-in">
                        <button
                          onClick={() => {
                            onToggleMute(p);
                            setMenuFor(null);
                          }}
                          className="block w-full px-3 py-2 text-left text-sm text-zoom-ink hover:bg-zoom-field"
                        >
                          {p.is_muted ? "Ask to unmute" : "Mute"}
                        </button>
                        <button
                          onClick={() => {
                            onRemove(p);
                            setMenuFor(null);
                          }}
                          className="block w-full px-3 py-2 text-left text-sm text-[#EF4444] hover:bg-[#FEF3F2]"
                        >
                          Remove
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {isHost && (
        <div className="border-t border-zoom-line p-3">
          <button
            onClick={onMuteAll}
            className="btn-outline w-full !py-2 text-sm"
          >
            <MicOffIcon className="h-4 w-4" />
            Mute All
          </button>
        </div>
      )}
    </div>
  );
}
