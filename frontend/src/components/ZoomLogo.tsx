export function ZoomLogo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <svg width="26" height="26" viewBox="0 0 24 24" aria-hidden>
        <rect x="1.5" y="6" width="14" height="12" rx="3" fill="#0B5CFF" />
        <path
          d="M15.5 10.5 21.4 7.4a.7.7 0 0 1 1 .6v8c0 .5-.6.9-1 .6l-5.9-3.1Z"
          fill="#0B5CFF"
        />
      </svg>
      <span
        className="text-[22px] font-bold lowercase tracking-tight text-zoom-blue"
        style={{ letterSpacing: "-0.04em" }}
      >
        zoom
      </span>
    </span>
  );
}
