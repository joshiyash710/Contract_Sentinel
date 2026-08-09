import type { CSSProperties } from "react";

/**
 * ContractSentinel brand logomark — a modern app-icon: an accent-gradient rounded square
 * (cyan/violet → blue) framing a darker rounded-square aperture, echoing the design-refs
 * (2026-08). Fully token-driven: the gradient comes from the accent-gradient utility and the
 * inner aperture uses the --bg-app surface token, so it stays consistent in the one dark theme.
 * Reused by the sidebar header, marketing nav and the auth screen.
 *
 * `size` is the badge edge length in px; the inner aperture scales with it.
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
  const style: CSSProperties = { width: size, height: size, borderRadius: size * 0.3 };
  const inner: CSSProperties = {
    width: size * 0.46,
    height: size * 0.46,
    borderRadius: size * 0.16,
    background: "var(--bg-app)",
  };
  return (
    <span
      role="img"
      aria-label={title}
      style={style}
      className={`relative flex shrink-0 items-center justify-center bg-accent-gradient shadow-glow ${className}`}
    >
      <span style={inner} />
    </span>
  );
}
