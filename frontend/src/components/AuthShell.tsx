import Link from "next/link";
import type { ReactNode } from "react";
import { ZoomLogo } from "./ZoomLogo";
import { CheckIcon } from "./Icons";

export function AuthShell({
  headerRight,
  children,
}: {
  headerRight: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-white">
      <header className="border-b border-zoom-line">
        <div className="mx-auto flex h-16 max-w-[1280px] items-center justify-between px-4 sm:px-6">
          <Link href="/login" aria-label="Home">
            <ZoomLogo />
          </Link>
          <div className="text-sm text-zoom-muted">{headerRight}</div>
        </div>
      </header>

      <main className="grid flex-1 lg:grid-cols-2">
        <BrandPanel />
        <div className="flex items-center justify-center px-4 py-10 sm:px-6">
          <div className="w-full max-w-sm">{children}</div>
        </div>
      </main>
    </div>
  );
}

const FEATURES = [
  "Free HD video & audio meetings",
  "Instant or scheduled meetings",
  "Screen sharing & host controls",
  "Secure email verification",
];

function BrandPanel() {
  return (
    <div className="relative hidden overflow-hidden bg-gradient-to-br from-zoom-blue to-[#0A3AA8] lg:flex lg:flex-col lg:items-center lg:justify-center lg:px-12">
      <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-white/10 blur-2xl" />
      <div className="pointer-events-none absolute -bottom-28 -left-16 h-80 w-80 rounded-full bg-white/10 blur-2xl" />

      <div className="relative z-10 flex w-full max-w-md flex-col items-center text-center">
        <h2 className="text-[32px] font-bold leading-tight text-white xl:text-[36px]">
          Bring everyone together, anywhere
        </h2>
        <p className="mt-3 max-w-sm text-[15px] leading-relaxed text-white/80">
          HD video meetings - instant or scheduled - with screen sharing, chat,
          reactions and host controls, right in your browser.
        </p>

        <GalleryMock />

        <ul className="mt-8 space-y-3">
          {FEATURES.map((f) => (
            <li key={f} className="flex items-center gap-3 text-[15px] text-white/90">
              <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-white/20">
                <CheckIcon className="h-3.5 w-3.5 text-white" />
              </span>
              {f}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

const TILES: [string, string][] = [
  ["#FF7A59", "AR"],
  ["#12B76A", "MJ"],
  ["#7A5AF8", "KP"],
  ["#F79009", "LS"],
  ["#06AED4", "DT"],
  ["#EC4899", "NF"],
];

function GalleryMock() {
  return (
    <div className="mt-8 w-full max-w-sm rounded-2xl bg-white/10 p-3 shadow-modal ring-1 ring-white/15 backdrop-blur">
      <div className="grid grid-cols-3 gap-2">
        {TILES.map(([c, initials], i) => (
          <div
            key={initials}
            className="relative flex aspect-[4/3] items-center justify-center rounded-lg bg-[#0E0E14]/40"
          >
            <span
              className="grid h-9 w-9 place-items-center rounded-full text-xs font-semibold text-white"
              style={{ background: c }}
            >
              {initials}
            </span>
            <span className="absolute bottom-1 left-1 rounded bg-black/40 px-1 py-0.5 text-[8px] font-medium text-white">
              {i === 0 ? "You" : initials}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center justify-center gap-2.5 rounded-lg bg-[#0E0E14]/50 py-2">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-white/10 text-white">
          <MockMic className="h-4 w-4" />
        </span>
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-white/10 text-white">
          <MockVideo className="h-4 w-4" />
        </span>
        <span className="flex h-7 items-center gap-1 rounded-lg bg-[#E5484D] px-2.5 text-[11px] font-semibold text-white">
          <MockLeave className="h-3.5 w-3.5" />
          End
        </span>
      </div>
    </div>
  );
}

function MockMic({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path
        d="M6 11a6 6 0 0 0 12 0M12 17v3M9 20h6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}
function MockVideo({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <rect x="2.5" y="6.5" width="12" height="11" rx="2.5" />
      <path d="M14.5 10.5 20.6 7.4a.6.6 0 0 1 .9.5v8.2a.6.6 0 0 1-.9.5l-6.1-3.1Z" />
    </svg>
  );
}
function MockLeave({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M2.5 13.2c5.2-4 13.8-4 19 0 .8.6 1 1.2.5 2l-1.3 1.9c-.4.6-1 .7-1.7.4l-2.7-1.1c-.6-.2-.9-.7-.9-1.3v-1.6c-2.8-.9-5.9-.9-8.8 0v1.6c0 .6-.3 1.1-.9 1.3l-2.7 1.1c-.7.3-1.3.2-1.7-.4L.3 15.2c-.5-.8-.3-1.4.5-2Z" />
    </svg>
  );
}
