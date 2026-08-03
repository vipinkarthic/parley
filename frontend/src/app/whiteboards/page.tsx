"use client";

import { PageShell } from "@/components/PageShell";
import { useToast } from "@/components/Toast";
import { PlusIcon } from "@/components/Icons";

const SAMPLE = [
  { name: "Sprint Planning Board", edited: "Edited 2 days ago", tint: "#EEF3FF" },
  { name: "Product Roadmap 2026", edited: "Edited 5 days ago", tint: "#FEF0EC" },
  { name: "Architecture Diagram", edited: "Edited last week", tint: "#EDFCF2" },
];

export default function WhiteboardsPage() {
  const toast = useToast();
  const notImplemented = () =>
    toast("Whiteboard editing is a placeholder in this demo", "info");

  return (
    <PageShell
      title="Whiteboards"
      subtitle="Brainstorm and collaborate on an infinite canvas"
      action={
        <button onClick={notImplemented} className="btn-primary">
          <PlusIcon className="h-4.5 w-4.5" />
          New Whiteboard
        </button>
      }
    >
      <div className="mb-5 flex items-center gap-2 rounded-xl border border-dashed border-zoom-blue/40 bg-[#EEF3FF] px-4 py-3 text-sm text-zoom-ink">
        <span className="rounded-full bg-zoom-blue px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
          Coming soon
        </span>
        Whiteboards are a preview — the boards below are samples and aren&apos;t
        editable yet.
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <button
          onClick={notImplemented}
          className="flex aspect-[4/3] flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-zoom-line bg-white text-zoom-muted transition-colors hover:border-zoom-blue hover:text-zoom-blue"
        >
          <PlusIcon className="h-7 w-7" />
          <span className="text-sm font-medium">New Whiteboard</span>
        </button>

        {SAMPLE.map((w) => (
          <button
            key={w.name}
            onClick={notImplemented}
            className="group overflow-hidden rounded-2xl bg-white text-left shadow-card ring-1 ring-zoom-line transition-all hover:-translate-y-0.5 hover:shadow-cardhover"
          >
            <div
              className="flex aspect-[4/3] items-center justify-center"
              style={{ background: w.tint }}
            >
              <WhiteboardGlyph />
            </div>
            <div className="p-3">
              <p className="truncate text-sm font-semibold text-zoom-ink">
                {w.name}
              </p>
              <p className="mt-0.5 text-xs text-zoom-muted">{w.edited}</p>
            </div>
          </button>
        ))}
      </div>
    </PageShell>
  );
}

function WhiteboardGlyph() {
  return (
    <svg width="56" height="56" viewBox="0 0 24 24" fill="none" className="opacity-70">
      <rect x="3" y="4" width="18" height="13" rx="2" stroke="#0B5CFF" strokeWidth="1.4" />
      <path d="M7 9h6M7 12h10M12 17v3M9 20h6" stroke="#0B5CFF" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}
