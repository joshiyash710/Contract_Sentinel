import clsx from "clsx";

export type AvatarSize = "sm" | "md" | "lg";

interface AvatarProps {
  /** Image URL; when absent, initials from `name` are shown. */
  src?: string;
  /** Used for the initials fallback and the alt text. Never hardcoded (spec EC-5). */
  name: string;
  size?: AvatarSize;
  className?: string;
}

const SIZES: Record<AvatarSize, string> = {
  sm: "h-7 w-7 text-caption",
  md: "h-10 w-10 text-small",
  lg: "h-24 w-24 text-h2",
};

function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

export function Avatar({ src, name, size = "md", className }: AvatarProps) {
  const base = clsx(
    "inline-flex items-center justify-center rounded-pill overflow-hidden shrink-0",
    SIZES[size],
    className,
  );
  if (src) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={src} alt={name} className={clsx(base, "object-cover")} />;
  }
  return (
    <span
      className={clsx(base, "bg-accent-gradient text-accent-fg font-semibold")}
      role="img"
      aria-label={name}
    >
      {initials(name)}
    </span>
  );
}
