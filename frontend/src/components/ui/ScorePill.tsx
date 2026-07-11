import clsx from "clsx";

/**
 * Numeric "n/100" risk-score pill (screens 7/8/10/11/12). PRESENTATIONAL ONLY — 001 defines
 * no numeric-score field, so this renders an arbitrary prop value with no backend dependency
 * (spec Q7 / §2.2 numeric-score note). The tone ramp is display-only.
 */
function tone(value: number): string {
  if (value >= 67) return "bg-risk-high/15 text-risk-high";
  if (value >= 34) return "bg-risk-medium/15 text-risk-medium";
  return "bg-risk-low/15 text-risk-low";
}

export function ScorePill({
  value,
  className,
}: {
  value: number;
  className?: string;
}) {
  return (
    <span
      data-testid="score-pill"
      className={clsx(
        "inline-flex items-center rounded-pill px-2.5 py-0.5 text-small font-semibold tabular-nums",
        tone(value),
        className,
      )}
    >
      {value}/100
    </span>
  );
}
