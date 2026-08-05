"use client";

import { useEffect, useRef, useState } from "react";
import type { MeetingSettings } from "@/lib/types";
import { ShieldIcon } from "@/components/Icons";

function Row({
  label,
  on,
  onToggle,
}: {
  label: string;
  on: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      aria-label={`security: ${label}`}
      className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm text-zoom-ink hover:bg-zoom-field"
    >
      <span>{label}</span>
      <span
        className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
          on ? "bg-zoom-blue" : "bg-zoom-line"
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${
            on ? "left-[18px]" : "left-0.5"
          }`}
        />
      </span>
    </button>
  );
}

export function SecurityMenu({
  settings,
  onUpdate,
}: {
  settings: MeetingSettings;
  onUpdate: (patch: Partial<MeetingSettings>) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={`relative flex min-w-[60px] flex-col items-center gap-1 rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition-colors ${
          open ? "text-zoom-blue" : "text-white/85 hover:bg-white/10"
        }`}
      >
        <span className="grid h-9 w-9 place-items-center rounded-lg">
          <ShieldIcon className="h-5 w-5" />
        </span>
        <span className="leading-none">Security</span>
      </button>

      {open && (
        <div className="absolute bottom-16 left-1/2 z-30 w-64 -translate-x-1/2 overflow-hidden rounded-xl bg-white py-1 text-zoom-ink shadow-modal animate-scale-in">
          <p className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-zoom-muted">
            Security
          </p>
          <Row label="Lock meeting" on={settings.locked} onToggle={() => onUpdate({ locked: !settings.locked })} />
          <Row label="Enable waiting room" on={settings.waiting_room} onToggle={() => onUpdate({ waiting_room: !settings.waiting_room })} />
          <Row label="Mute participants on entry" on={settings.mute_on_entry} onToggle={() => onUpdate({ mute_on_entry: !settings.mute_on_entry })} />
          <Row label="Join before host" on={settings.join_before_host} onToggle={() => onUpdate({ join_before_host: !settings.join_before_host })} />

          <p className="px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wide text-zoom-muted">
            Allow participants to
          </p>
          <Row label="Share screen" on={settings.allow_screen_share} onToggle={() => onUpdate({ allow_screen_share: !settings.allow_screen_share })} />
          <Row label="Unmute themselves" on={settings.allow_unmute} onToggle={() => onUpdate({ allow_unmute: !settings.allow_unmute })} />
          <Row label="Start their video" on={settings.allow_video} onToggle={() => onUpdate({ allow_video: !settings.allow_video })} />
          <Row label="Rename themselves" on={settings.allow_rename} onToggle={() => onUpdate({ allow_rename: !settings.allow_rename })} />
          <Row label="Chat" on={settings.allow_chat} onToggle={() => onUpdate({ allow_chat: !settings.allow_chat })} />
          <Row label="React" on={settings.allow_reactions} onToggle={() => onUpdate({ allow_reactions: !settings.allow_reactions })} />
        </div>
      )}
    </div>
  );
}
