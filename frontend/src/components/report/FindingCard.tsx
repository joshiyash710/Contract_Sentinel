"use client";

import { useState } from "react";
import { ChevronDown, Sparkles, FileText, Quote, BookOpen } from "lucide-react";
import type { ReportFinding } from "@/lib/api/types";
import { findingTitle } from "@/lib/reportFormat";
import { FindingRiskBadge } from "./FindingRiskBadge";

const CLAUSE_PREVIEW_CHARS = 240;

// Left accent stripe color by risk level (real risk_level; null → neutral).
const ACCENT: Record<string, string> = {
  high: "before:bg-risk-high",
  medium: "before:bg-risk-medium",
  low: "before:bg-risk-low",
};

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
  const accent = (finding.risk_level && ACCENT[finding.risk_level]) || "before:bg-card-raised";

  return (
    <div
      data-testid="finding-card"
      className={`relative overflow-hidden rounded-card border border-subtle bg-card pl-1.5 transition hover:border-subtle before:absolute before:left-0 before:top-0 before:h-full before:w-1.5 before:content-[''] ${accent}`}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 p-4 text-left hover:bg-card-raised"
      >
        <ChevronDown
          size={18}
          className={`shrink-0 text-text-tertiary transition-transform ${open ? "" : "-rotate-90"}`}
        />
        <span className="flex-1 min-w-0">
          <span data-testid="finding-title" className="font-semibold text-text-primary">
            {title}
          </span>
          {finding.section_number && (
            <span className="ml-2 text-small text-text-tertiary">§ {finding.section_number}</span>
          )}
        </span>
        {finding.confidence_score != null && (
          <span className="hidden shrink-0 text-small text-text-tertiary sm:inline">
            {Math.round(finding.confidence_score * 100)}% confidence
          </span>
        )}
        <FindingRiskBadge level={finding.risk_level} />
      </button>

      {open && (
        <div className="space-y-4 border-t border-subtle p-4 pt-4">
          {/* AI Explanation */}
          <section>
            <SectionLabel icon={<Sparkles size={13} />}>AI Explanation</SectionLabel>
            {finding.risk_rationale ? (
              <p className="text-body text-text-secondary">{finding.risk_rationale}</p>
            ) : (
              <p className="text-body italic text-text-tertiary">No explanation provided.</p>
            )}
          </section>

          {/* Clause text */}
          <section>
            <SectionLabel icon={<FileText size={13} />}>Text</SectionLabel>
            <blockquote className="rounded-input border-l-2 border-subtle bg-app px-3 py-2 font-mono text-small leading-relaxed text-text-secondary">
              {clauseShown}
            </blockquote>
            {long && (
              <button
                type="button"
                onClick={() => setShowFullClause((s) => !s)}
                className="mt-1.5 text-small font-medium text-accent hover:underline"
              >
                {showFullClause ? "Show less" : "Show full clause"}
              </button>
            )}
          </section>

          {/* Suggested rewrite — three-way (D3/AC-6) */}
          {finding.rewrite_state === "rewritten" && finding.suggested_rewrite && (
            <section data-testid="rewrite-block">
              <SectionLabel icon={<Quote size={13} />} tone="text-risk-low">
                Suggested rewrite
              </SectionLabel>
              <p className="rounded-input border border-risk-low/20 bg-risk-low/10 px-3 py-2 text-body text-text-primary">
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
              <SectionLabel icon={<BookOpen size={13} />}>Supporting sources</SectionLabel>
              <ul className="space-y-2">
                {finding.evidence.map((e, i) => (
                  <li key={i} className="rounded-input bg-app px-3 py-2 text-small">
                    <span className="font-mono text-text-tertiary">{e.source_reference}</span>
                    <p className="mt-0.5 text-text-secondary">{e.snippet_text}</p>
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

function SectionLabel({
  icon,
  tone = "text-text-tertiary",
  children,
}: {
  icon: React.ReactNode;
  tone?: string;
  children: React.ReactNode;
}) {
  return (
    <h4 className={`mb-1.5 flex items-center gap-1.5 text-small font-semibold uppercase tracking-wide ${tone}`}>
      {icon}
      {children}
    </h4>
  );
}

export { CLAUSE_PREVIEW_CHARS };
