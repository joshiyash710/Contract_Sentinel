import type { CSSProperties } from "react";

/**
 * ContractSentinel brand logomark — a sentinel *shield* (guardianship / risk protection)
 * enclosing a *verification checkmark* (a contract vetted & cleared). Rendered on the
 * accent-gradient badge so it stays consistent with the rest of the brand system. Replaces
 * the old plain "C" letter mark. Reused by the sidebar header and the auth screen.
 *
 * `size` is the badge edge length in px; the glyph scales with it.
 */
export function LogoMark({
  size = 32,
  className = "",
  title = "ContractSentinel",
}: {
  size?: number;
  className?: string;
  title?: string;
}) {
  const style: CSSProperties = { width: size, height: size };
  return (
    <span
      role="img"
      aria-label={title}
      style={style}
      className={`flex shrink-0 items-center justify-center rounded-lg bg-accent-gradient text-accent-fg shadow-glow ${className}`}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        width={Math.round(size * 0.62)}
        height={Math.round(size * 0.62)}
        aria-hidden="true"
      >
        {/* Sentinel shield */}
        <path
          d="M12 2.5 5 5.2v5.5c0 4.3 2.9 7.6 7 8.8 4.1-1.2 7-4.5 7-8.8V5.2L12 2.5Z"
          fill="currentColor"
          fillOpacity="0.16"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        {/* Verification check */}
        <path
          d="m8.8 11.8 2.2 2.2L15.2 9.8"
          stroke="currentColor"
          strokeWidth="1.9"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}
