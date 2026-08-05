"use client";

import { useState } from "react";
import type { WaitingPerson } from "@/lib/types";
import { Avatar } from "@/components/Avatar";
import { CloseIcon, MicIcon, MicOffIcon, MoreIcon, ShieldIcon } from "@/components/Icons";

export interface PanelPerson {
  id: number;
  name: string;
  isHost: boolean;
  muted: boolean;
  hand: boolean;
  isSelf: boolean;
}

export function ParticipantsPanel({
  people,
  waiting,
  isHost,
  waitingRoomOn,
  allowRename,
  onClose,
  onMute,
  onAskUnmute,
  onRemove,
  onSpotlight,
  onLowerHand,
  onRenameSelf,
  onMuteAll,
  onAdmit,
  onDeny,
  onAdmitAll,
  onToggleWaitingRoom,
}: {
  people: PanelPerson[];
  waiting: WaitingPerson[];
  isHost: boolean;
  waitingRoomOn: boolean;
  allowRename: boolean;
  onClose: () => void;
  onMute: (id: number) => void;
  onAskUnmute: (id: number) => void;
  onRemove: (id: number) => void;
  onSpotlight: (id: number) => void;
  onLowerHand: (id: number) => void;
  onRenameSelf: (name: string) => void;
  onMuteAll: () => void;
  onAdmit: (id: number) => void;
  onDeny: (id: number) => void;
  onAdmitAll: () => void;
  onToggleWaitingRoom: () => void;
}) {
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [nameDraft, setNameDraft] = useState("");

  const raisedHands = people.filter((p) => p.hand);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-zoom-line px-4 py-3">
        <h3 className="font-semibold text-zoom-ink">
          Participants <span className="text-zoom-muted">({people.length})</span>
        </h3>
        <button
          onClick={onClose}
          aria-label="Close panel"
          className="grid h-7 w-7 place-items-center rounded-full text-zoom-muted hover:bg-black/5"
        >
          <CloseIcon className="h-4 w-4" />
        </button>
      </div>

      {isHost && waiting.length > 0 && (
        <div className="border-b border-zoom-line bg-[#FFF9EC] px-3 py-2.5">
          <div className="mb-1.5 flex items-center justify-between">
            <p className="text-sm font-semibold text-zoom-ink">Waiting ({waiting.length})</p>
            <button onClick={onAdmitAll} className="text-xs font-semibold text-zoom-blue hover:underline">
              Admit all
            </button>
          </div>
          {waiting.map((w) => (
            <div key={w.id} className="flex items-center gap-2 py-1">
              <Avatar name={w.displayName} size={30} />
              <span className="min-w-0 flex-1 truncate text-sm text-zoom-ink">{w.displayName}</span>
              <button
                onClick={() => onAdmit(w.id)}
                className="rounded-full bg-zoom-blue px-3 py-1 text-xs font-semibold text-white hover:bg-zoom-bluehover"
              >
                Admit
              </button>
              <button
                onClick={() => onDeny(w.id)}
                className="rounded-full px-2 py-1 text-xs font-semibold text-[#EF4444] hover:bg-[#FEF3F2]"
              >
                Deny
              </button>
            </div>
          ))}
        </div>
      )}

      {raisedHands.length > 0 && (
        <div className="border-b border-zoom-line bg-[#FFFBEB] px-4 py-2 text-xs text-zoom-ink">
          ✋ {raisedHands.length} raised {raisedHands.length === 1 ? "hand" : "hands"}
          {": "}
          {raisedHands.map((p) => p.name).join(", ")}
        </div>
      )}

      <div className="scroll-thin flex-1 overflow-y-auto px-2 py-2">
        {people.map((p) => (
          <div
            key={p.id}
            className="group relative flex items-center gap-3 rounded-lg px-2 py-2 hover:bg-zoom-field"
          >
            <Avatar name={p.name} size={36} />
            <div className="min-w-0 flex-1">
              {p.isSelf && renaming ? (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (nameDraft.trim()) onRenameSelf(nameDraft.trim());
                    setRenaming(false);
                  }}
                >
                  <input
                    autoFocus
                    value={nameDraft}
                    onChange={(e) => setNameDraft(e.target.value)}
                    onBlur={() => setRenaming(false)}
                    className="w-full rounded border border-zoom-line px-1.5 py-0.5 text-sm text-zoom-ink outline-none focus:border-zoom-blue"
                    maxLength={40}
                  />
                </form>
              ) : (
                <p className="flex items-center gap-1.5 truncate text-sm font-medium text-zoom-ink">
                  {p.name}
                  {p.isSelf && " (You)"}
                  {p.hand && <span title="Raised hand">✋</span>}
                  {p.isSelf && allowRename && (
                    <button
                      onClick={() => {
                        setNameDraft(p.name);
                        setRenaming(true);
                      }}
                      className="text-xs font-normal text-zoom-blue opacity-0 hover:underline group-hover:opacity-100"
                    >
                      Rename
                    </button>
                  )}
                </p>
              )}
              {p.isHost && (
                <p className="inline-flex items-center gap-1 text-xs text-zoom-muted">
                  <ShieldIcon className="h-3 w-3" /> Host
                </p>
              )}
            </div>

            <span className="text-zoom-muted">
              {p.muted ? (
                <MicOffIcon className="h-4 w-4 text-[#EF4444]" />
              ) : (
                <MicIcon className="h-4 w-4 text-[#12B76A]" />
              )}
            </span>

            {isHost && !p.isSelf && (
              <div className="relative">
                <button
                  onClick={() => setMenuFor(menuFor === p.id ? null : p.id)}
                  className="grid h-7 w-7 place-items-center rounded-full text-zoom-muted opacity-0 transition-opacity hover:bg-black/10 group-hover:opacity-100"
                  aria-label="Manage participant"
                >
                  <MoreIcon className="h-4 w-4" />
                </button>
                {menuFor === p.id && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setMenuFor(null)} />
                    <div className="absolute right-0 top-8 z-20 w-44 overflow-hidden rounded-lg border border-zoom-line bg-white py-1 shadow-modal animate-scale-in">
                      <MenuItem
                        label={p.muted ? "Ask to unmute" : "Mute"}
                        onClick={() => {
                          if (p.muted) onAskUnmute(p.id);
                          else onMute(p.id);
                          setMenuFor(null);
                        }}
                      />
                      <MenuItem
                        label="Spotlight"
                        onClick={() => {
                          onSpotlight(p.id);
                          setMenuFor(null);
                        }}
                      />
                      {p.hand && (
                        <MenuItem
                          label="Lower hand"
                          onClick={() => {
                            onLowerHand(p.id);
                            setMenuFor(null);
                          }}
                        />
                      )}
                      <MenuItem
                        label="Remove"
                        danger
                        onClick={() => {
                          onRemove(p.id);
                          setMenuFor(null);
                        }}
                      />
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {isHost && (
        <div className="space-y-2 border-t border-zoom-line p-3">
          <div className="flex items-center justify-between px-1">
            <span className="text-sm text-zoom-ink">Waiting room</span>
            <button
              onClick={onToggleWaitingRoom}
              className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
                waitingRoomOn ? "bg-zoom-blue" : "bg-zoom-line"
              }`}
              aria-pressed={waitingRoomOn}
              aria-label="Toggle waiting room"
            >
              <span
                className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${
                  waitingRoomOn ? "left-[18px]" : "left-0.5"
                }`}
              />
            </button>
          </div>
          <button onClick={onMuteAll} className="btn-outline w-full !py-2 text-sm">
            <MicOffIcon className="h-4 w-4" />
            Mute All
          </button>
        </div>
      )}
    </div>
  );
}

function MenuItem({
  label,
  onClick,
  danger = false,
}: {
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`block w-full px-3 py-2 text-left text-sm hover:bg-zoom-field ${
        danger ? "text-[#EF4444] hover:bg-[#FEF3F2]" : "text-zoom-ink"
      }`}
    >
      {label}
    </button>
  );
}
