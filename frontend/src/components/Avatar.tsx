import { colorFromName, initials } from "@/lib/utils";

export function Avatar({
  name,
  color,
  src,
  size = 36,
  className = "",
}: {
  name: string;
  color?: string;
  src?: string | null;
  size?: number;
  className?: string;
}) {
  if (src) {
    // eslint-disable-next-line @next/next/no-img-element
    return (
      <img
        src={src}
        alt={name}
        width={size}
        height={size}
        className={`inline-block shrink-0 rounded-full object-cover ${className}`}
        style={{ width: size, height: size }}
      />
    );
  }
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
