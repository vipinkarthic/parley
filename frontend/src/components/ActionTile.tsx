"use client";

import type { ReactNode } from "react";

export function ActionTile({
  icon,
  label,
  sublabel,
  color,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  sublabel: string;
  color: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="group flex flex-col items-center gap-3 rounded-2xl bg-white p-6 text-center shadow-card ring-1 ring-zoom-line transition-all hover:-translate-y-0.5 hover:shadow-cardhover"
    >
      <span
        className="grid h-14 w-14 place-items-center rounded-2xl text-white transition-transform group-hover:scale-105"
        style={{ background: color }}
      >
        {icon}
      </span>
      <span>
        <span className="block text-[15px] font-semibold text-zoom-ink">
          {label}
        </span>
        <span className="mt-0.5 block text-xs text-zoom-muted">{sublabel}</span>
      </span>
    </button>
  );
}
