import { AlertTriangle } from "lucide-react";

/**
 * Feature 038 — honest LLM-failure surfacing. Shown at the top of a report whose
 * `analysis_degraded` flag is set, i.e. the AI model was unavailable for part or all of
 * the run and some severities were auto-assigned by a fail-safe default rather than by
 * model judgment. Makes the degradation impossible to miss so the auto-defaulted
 * severities are not mistaken for genuine analysis.
 */
export function DegradedBanner() {
  return (
    <div
      data-testid="degraded-banner"
      role="alert"
      className="flex items-start gap-3 rounded-card border border-risk-high/40 bg-risk-high/10 p-4"
    >
      <AlertTriangle size={20} className="mt-0.5 shrink-0 text-risk-high" />
      <div className="text-body text-text-secondary">
        <span className="font-semibold text-risk-high">Degraded analysis</span> — the AI
        model was unavailable for part or all of this run. Severities marked{" "}
        <span className="font-medium text-text-primary">(auto)</span> were set by a fail-safe
        default, not by model judgment. <span className="font-semibold">Do not rely on them</span>
        {" "}— re-run this analysis when the model is available.
      </div>
    </div>
  );
}
