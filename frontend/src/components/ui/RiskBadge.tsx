import clsx from "clsx";
import type { RiskLevel } from "@/lib/api/types";

const LABEL: Record<RiskLevel, string> = {
  low: "Low Risk",
  medium: "Medium Risk",
  high: "High Risk",
};

// Token-backed classes (defined in globals via Tailwind color map). Exactly three levels
// (spec AC-2) — no "amber"/4th value; medium IS amber.
const TONE: Record<RiskLevel, string> = {
  low: "bg-risk-low/15 text-risk-low risk-low",
  medium: "bg-risk-medium/15 text-risk-medium risk-medium",
  high: "bg-risk-high/15 text-risk-high risk-high",
};

export function RiskBadge({ level, className }: { level: RiskLevel; className?: string }) {
  return (
    <span
      data-testid={`risk-badge-${level}`}
      className={clsx(
        "inline-flex items-center rounded-pill px-2.5 py-0.5 text-small font-medium",
        TONE[level],
        className,
      )}
    >
      {LABEL[level]}
    </span>
  );
}
