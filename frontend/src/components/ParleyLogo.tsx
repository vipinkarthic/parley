export function ParleyLogo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      {/* Two chevrons turned toward each other across a gap - two sides at a
          table. The centre dot keeps the mark from reading hollow at 16px. */}
      <svg width="26" height="26" viewBox="0 0 24 24" aria-hidden>
        <g
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
          className="text-parley-brand"
        >
          <path d="M8.5 5.5 3.5 12l5 6.5" />
          <path d="M15.5 5.5 20.5 12l-5 6.5" />
        </g>
        <circle cx="12" cy="12" r="1.6" className="fill-parley-brand" />
      </svg>
      <span
        className="text-[22px] font-bold lowercase tracking-tight text-parley-brand"
        style={{ letterSpacing: "-0.04em" }}
      >
        parley
      </span>
    </span>
  );
}
