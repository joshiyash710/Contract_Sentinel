import type { ReactNode } from "react";

type Accent = "accent" | "high" | "medium" | "low";

const ICON_BG: Record<Accent, string> = {
  accent: "bg-accent/15 text-accent",
  high: "bg-risk-high/15 text-risk-high",
  medium: "bg-risk-medium/15 text-risk-medium",
  low: "bg-risk-low/15 text-risk-low",
};

/**
 * A KPI stat card (feature 018 UI polish) — the hallmark of a trustworthy analytics
 * dashboard: labelled metric, big tabular value, an accent-tinted icon, and an optional
 * sub-line for context. Data-driven; no baked strings.
 */
export function StatCard({
  label,
  value,
  sub,
  icon,
  accent = "accent",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon: ReactNode;
  accent?: Accent;
}) {
  return (
    <div className="relative overflow-hidden rounded-card border border-subtle bg-card p-5 transition hover:bg-card-raised">
      <div className="flex items-start justify-between">
        <span className="text-small font-medium text-text-tertiary">{label}</span>
        <span className={`flex h-9 w-9 items-center justify-center rounded-lg ${ICON_BG[accent]}`}>
          {icon}
        </span>
      </div>
      <div className="mt-3 text-display font-bold leading-none text-text-primary tabular-nums">
        {value}
      </div>
      {sub != null && <div className="mt-2 text-small text-text-secondary">{sub}</div>}
    </div>
  );
}
