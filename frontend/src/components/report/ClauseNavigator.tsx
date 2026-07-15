"use client";

import type { ReportFinding } from "@/lib/api/types";
import { findingTitle } from "@/lib/reportFormat";

// Risk dot color by level (real risk_level; null → neutral). The level is conveyed to
// assistive tech + tests via aria-label/title, NOT visible band text, so it never collides
// with the header's "High risk" / "Severity unavailable" copy (spec 022 plan §6).
const DOT: Record<string, string> = {
  high: "bg-risk-high",
  medium: "bg-risk-medium",
  low: "bg-risk-low",
};
const DOT_LABEL: Record<string, string> = {
  high: "High risk",
  medium: "Medium risk",
  low: "Low risk",
};

/**
 * Left rail of the Analysis Workspace (spec 022 §2.2 / D1): a "table of contents" over the
 * report's flagged clauses. It is NOT a full-document viewer — the 009 report stores only
 * flagged clauses. Selecting an entry drives the main panel (focus + expand the matching card).
 */
export function ClauseNavigator({
  findings,
  activeId,
  onSelect,
}: {
  findings: ReportFinding[];
  activeId: string | null;
  onSelect: (clauseId: string) => void;
}) {
  return (
    <nav
      data-testid="clause-navigator"
      aria-label="Flagged clauses"
      className="lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto rounded-card border border-subtle bg-card p-3"
    >
      <div className="mb-2 flex items-center justify-between px-1">
        <h2 className="text-small font-semibold uppercase tracking-wide text-text-tertiary">
          Flagged clauses
        </h2>
        <span className="text-small text-text-tertiary">{findings.length}</span>
      </div>

      {findings.length === 0 ? (
        <p className="px-1 py-2 text-small italic text-text-tertiary">No flagged clauses.</p>
      ) : (
        <ul className="space-y-1">
          {findings.map((f) => {
            const active = activeId === f.clause_id;
            const dot = (f.risk_level && DOT[f.risk_level]) || "bg-text-tertiary";
            const dotLabel = (f.risk_level && DOT_LABEL[f.risk_level]) || "Severity unavailable";
            return (
              <li key={f.clause_id}>
                <button
                  type="button"
                  data-testid="nav-clause"
                  aria-current={active ? "true" : undefined}
                  data-active={active ? "true" : undefined}
                  onClick={() => onSelect(f.clause_id)}
                  className={`flex w-full items-start gap-2.5 rounded-input px-2 py-2 text-left transition hover:bg-card-raised ${
                    active ? "bg-card-raised ring-1 ring-accent/40" : ""
                  }`}
                >
                  <span
                    className={`mt-1.5 h-2 w-2 shrink-0 rounded-pill ${dot}`}
                    role="img"
                    aria-label={dotLabel}
                    title={dotLabel}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-body font-medium text-text-primary">
                      {f.position}. {findingTitle(f)}
                    </span>
                    {f.section_number && (
                      <span className="text-small text-text-tertiary">§ {f.section_number}</span>
                    )}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}
