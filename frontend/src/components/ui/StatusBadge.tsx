import clsx from "clsx";

export type BadgeTone = "neutral" | "success" | "warning" | "danger";

const TONE: Record<BadgeTone, string> = {
  neutral: "bg-card-raised text-text-secondary",
  success: "bg-risk-low/15 text-risk-low",
  warning: "bg-risk-medium/15 text-risk-medium",
  danger: "bg-risk-high/15 text-risk-high",
};

// Labels are a PROP, not hardcoded to Analysed/Redlined/Needs Review — screen 017 owns the
// real set (spec AC-12).
export function StatusBadge({
  label,
  tone = "neutral",
  className,
}: {
  label: string;
  tone?: BadgeTone;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-pill px-2.5 py-0.5 text-small font-medium",
        TONE[tone],
        className,
      )}
    >
      {label}
    </span>
  );
}
