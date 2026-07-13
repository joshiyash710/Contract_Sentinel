"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { ReportFinding } from "@/lib/api/types";
import { findingTitle } from "@/lib/reportFormat";
import { FindingRiskBadge } from "./FindingRiskBadge";

const CLAUSE_PREVIEW_CHARS = 240;

/**
 * One 009 ReportFinding as an expandable card (spec 017 D3, screen 7's AI Analysis card).
 * Header (always visible): title, section locator, risk badge, confidence. Body (when open):
 * explanation (risk_rationale), collapsible clause_text, three-way rewrite, evidence.
 * NO "Business Impact" — that field does not exist in 009 (D4); nothing fabricated.
 */
export function FindingCard({
  finding,
  defaultOpen = false,
}: {
  finding: ReportFinding;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [showFullClause, setShowFullClause] = useState(false);

  const title = findingTitle(finding);
  const long = finding.clause_text.length > CLAUSE_PREVIEW_CHARS;
  const clauseShown =
    long && !showFullClause
      ? finding.clause_text.slice(0, CLAUSE_PREVIEW_CHARS) + "…"
      : finding.clause_text;

  return (
    <div
      data-testid="finding-card"
      className="bg-card border border-subtle rounded-card overflow-hidden"
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 p-4 text-left hover:bg-card-raised"
      >
        {open ? (
          <ChevronDown size={18} className="shrink-0 text-text-tertiary" />
        ) : (
          <ChevronRight size={18} className="shrink-0 text-text-tertiary" />
        )}
        <span className="flex-1">
          <span data-testid="finding-title" className="font-semibold text-text-primary">
            {title}
          </span>
          {finding.section_number && (
            <span className="ml-2 text-small text-text-tertiary">§ {finding.section_number}</span>
          )}
        </span>
        {finding.confidence_score != null && (
          <span className="shrink-0 text-small text-text-tertiary">
            {Math.round(finding.confidence_score * 100)}% confidence
          </span>
        )}
        <FindingRiskBadge level={finding.risk_level} />
      </button>

      {open && (
        <div className="space-y-4 border-t border-subtle p-4 pt-3">
          {/* AI Explanation */}
          <section>
            <h4 className="mb-1 text-small font-semibold uppercase tracking-wide text-text-tertiary">
              AI Explanation
            </h4>
            {finding.risk_rationale ? (
              <p className="text-body text-text-secondary">{finding.risk_rationale}</p>
            ) : (
              <p className="text-body italic text-text-tertiary">No explanation provided.</p>
            )}
          </section>

          {/* Clause text */}
          <section>
            <h4 className="mb-1 text-small font-semibold uppercase tracking-wide text-text-tertiary">
              Text
            </h4>
            <blockquote className="rounded-input border-l-2 border-subtle bg-app px-3 py-2 font-mono text-small text-text-secondary">
              {clauseShown}
            </blockquote>
            {long && (
              <button
                type="button"
                onClick={() => setShowFullClause((s) => !s)}
                className="mt-1 text-small font-medium text-accent hover:underline"
              >
                {showFullClause ? "Show less" : "Show full clause"}
              </button>
            )}
          </section>

          {/* Suggested rewrite — three-way (D3/AC-6) */}
          {finding.rewrite_state === "rewritten" && finding.suggested_rewrite && (
            <section data-testid="rewrite-block">
              <h4 className="mb-1 text-small font-semibold uppercase tracking-wide text-risk-low">
                Suggested rewrite
              </h4>
              <p className="rounded-input bg-risk-low/10 px-3 py-2 text-body text-text-primary">
                {finding.suggested_rewrite}
              </p>
            </section>
          )}
          {finding.rewrite_state === "unavailable" && (
            <p className="text-small italic text-text-tertiary">
              A safer rewrite couldn&apos;t be generated for this clause.
            </p>
          )}

          {/* Evidence */}
          {finding.evidence.length > 0 && (
            <section>
              <h4 className="mb-1 text-small font-semibold uppercase tracking-wide text-text-tertiary">
                Supporting sources
              </h4>
              <ul className="space-y-2">
                {finding.evidence.map((e, i) => (
                  <li key={i} className="text-small">
                    <span className="font-mono text-text-tertiary">{e.source_reference}</span>
                    <p className="text-text-secondary">{e.snippet_text}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

export { CLAUSE_PREVIEW_CHARS };
