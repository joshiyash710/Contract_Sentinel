"use client";

import { useRef, useState } from "react";
import { CheckCircle2 } from "lucide-react";
import type { ContractReport } from "@/lib/api/types";
import { ReportHeader } from "./ReportHeader";
import { SummaryStrip } from "./SummaryStrip";
import { RiskOverview } from "./RiskOverview";
import { FindingCard } from "./FindingCard";
import { ClauseNavigator } from "./ClauseNavigator";

/**
 * The "Analysis Workspace" (spec 022) — the restyled happy-path layout for a loaded report.
 * Full-width header zone (reused 017 header + summary), then a two-pane clause zone: a left
 * ClauseNavigator rail (D1 — a table of contents over the flagged clauses, not a document
 * viewer) driving a main "AI Analysis Panel" of expandable FindingCards. The mockup's chat
 * column, 78/100 score, and "Business Impact" are deliberately absent (D3/D4/D5).
 */
export function AnalysisWorkspace({ jobId, report }: { jobId: string; report: ContractReport }) {
  const findings = report.findings;
  // Card expansion is workspace-owned so the navigator and each card's chevron share it.
  // Seed with the first finding open (mirrors 017's defaultOpen={i===0}).
  const [openIds, setOpenIds] = useState<Set<string>>(
    () => new Set(findings[0] ? [findings[0].clause_id] : []),
  );
  const [activeId, setActiveId] = useState<string | null>(null);
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const toggle = (id: string) =>
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const handleSelect = (id: string) => {
    setActiveId(id);
    setOpenIds((prev) => new Set(prev).add(id));
    cardRefs.current[id]?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      {/* Header zone (full width) */}
      <div className="space-y-6">
        <p className="text-small font-semibold uppercase tracking-wide text-text-tertiary">
          Analysis Workspace
        </p>
        <ReportHeader jobId={jobId} report={report} />
        <SummaryStrip summary={report.summary} />
      </div>

      {findings.length === 0 ? (
        <>
          <div className="rounded-card border border-subtle bg-card p-10 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-risk-low/15">
              <CheckCircle2 size={30} className="text-risk-low" />
            </div>
            <h2 className="mt-4 text-h3 font-semibold">No risky clauses found</h2>
            <p className="mx-auto mt-1 max-w-md text-body text-text-secondary">
              We analyzed this contract and didn&apos;t flag any clauses for review. You can still
              download the full report above.
            </p>
          </div>
          <ClauseNavigator findings={[]} activeId={null} onSelect={() => {}} />
        </>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,18rem)_1fr]">
          <ClauseNavigator findings={findings} activeId={activeId} onSelect={handleSelect} />

          <section
            data-testid="analysis-panel"
            aria-label="AI Analysis Panel"
            className="min-w-0 space-y-4"
          >
            <RiskOverview summary={report.summary} />
            {findings.map((f) => (
              <div
                key={f.clause_id}
                ref={(el) => {
                  cardRefs.current[f.clause_id] = el;
                }}
              >
                <FindingCard
                  finding={f}
                  open={openIds.has(f.clause_id)}
                  onToggle={() => toggle(f.clause_id)}
                  active={activeId === f.clause_id}
                />
              </div>
            ))}
          </section>
        </div>
      )}
    </div>
  );
}
