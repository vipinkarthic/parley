export function SoonBadge({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full bg-parley-tint px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-parley-brand ${className}`}
    >
      Soon
    </span>
  );
}
