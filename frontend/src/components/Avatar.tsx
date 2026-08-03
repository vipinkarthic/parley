import { colorFromName, initials } from "@/lib/utils";

export function Avatar({
  name,
  color,
  size = 36,
  className = "",
}: {
  name: string;
  color?: string;
  size?: number;
  className?: string;
}) {
  const bg = color || colorFromName(name);
  return (
    <span
      className={`inline-grid shrink-0 place-items-center rounded-full font-semibold text-white ${className}`}
      style={{
        width: size,
        height: size,
        background: bg,
        fontSize: size * 0.4,
      }}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}
