"use client";

import type { FloatingReaction } from "@/lib/useMeeting";

export function ReactionsOverlay({ reactions }: { reactions: FloatingReaction[] }) {
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-4 z-20 flex justify-center">
      <div className="relative h-1 w-64">
        {reactions.map((r) => (
          <span
            key={r.key}
            className="reaction-float absolute bottom-0 text-4xl"
            style={{ left: `${(r.key * 37) % 90}%` }}
          >
            {r.emoji}
          </span>
        ))}
      </div>
    </div>
  );
}
