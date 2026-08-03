export function SoonBadge({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full bg-[#EEF3FF] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zoom-blue ${className}`}
    >
      Soon
    </span>
  );
}
