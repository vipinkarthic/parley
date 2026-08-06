import Link from "next/link";
import type { ReactNode } from "react";
import { ZoomLogo } from "./ZoomLogo";
import { CheckIcon, MicIcon, VideoCamIcon, PhoneEndIcon } from "./Icons";

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
    <div className="relative hidden overflow-hidden bg-gradient-to-br from-zoom-blue to-[#0A3AA8] lg:flex lg:flex-col lg:justify-center lg:px-12 xl:px-16">
      <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-white/10 blur-2xl" />
      <div className="pointer-events-none absolute -bottom-28 -left-16 h-80 w-80 rounded-full bg-white/10 blur-2xl" />

      <div className="relative z-10 max-w-md">
        <h2 className="text-[32px] font-bold leading-tight text-white xl:text-[38px]">
          Bring everyone together, anywhere
        </h2>
        <p className="mt-3 text-[15px] leading-relaxed text-white/80">
          HD video meetings — instant or scheduled — with screen sharing, chat,
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
    <div className="mt-8 rounded-2xl bg-white/10 p-3 shadow-modal ring-1 ring-white/15 backdrop-blur">
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
            {i === 0 && (
              <span className="absolute bottom-1 left-1 rounded bg-black/40 px-1 py-0.5 text-[8px] font-medium text-white">
                You
              </span>
            )}
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center justify-center gap-2 rounded-lg bg-[#0E0E14]/50 py-2">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-white/10 text-white">
          <MicIcon className="h-4 w-4" />
        </span>
        <span className="grid h-7 w-7 place-items-center rounded-md bg-white/10 text-white">
          <VideoCamIcon className="h-4 w-4" />
        </span>
        <span className="grid h-7 w-7 place-items-center rounded-md bg-[#E02D2D] text-white">
          <PhoneEndIcon className="h-4 w-4" />
        </span>
      </div>
    </div>
  );
}
