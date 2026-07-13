import { RiskBadge } from "@/components/ui/RiskBadge";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { RISK_LEVELS, type RiskLevel } from "@/lib/api/types";

/**
 * Risk badge for a report finding (spec 017 D3 / AC-5). Reuses the design-system RiskBadge for
 * the three known levels; a null/unknown risk_level renders a neutral "Severity unavailable"
 * badge (009 ReportFinding.risk_level is Optional[str]) rather than crashing.
 */
export function FindingRiskBadge({ level }: { level?: string | null }) {
  if (level && (RISK_LEVELS as readonly string[]).includes(level)) {
    return <RiskBadge level={level as RiskLevel} />;
  }
  return <StatusBadge label="Severity unavailable" tone="neutral" />;
}
