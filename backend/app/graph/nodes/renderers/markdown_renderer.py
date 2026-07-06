"""
Pure Markdown renderer for the ReportAgent (Node 7).

render_markdown(report) -> str: deterministic, no I/O, no LLM, no state
mutation. Walks a ContractReport Pydantic model and emits a Markdown string.
Never raises on None fields — uses defined placeholders throughout.

Accepted limitations (non-defects, inherent to a node rendering itself):
  (a) Self-timing: node_timings["report"] cannot appear in the footer because
      the node measures elapsed AFTER render_markdown returns. The footer shows
      upstream timings + a computed total-elapsed line only.
  (b) Footer error_count: reflects upstream errors only. The report body is
      serialized BEFORE the write attempt, so a write-failure error_count (AC-19)
      lives in ContractState, not in the rendered file.
"""

from datetime import datetime
from typing import Optional

from app.models.report import ContractReport


def render_markdown(report: ContractReport) -> str:
    """Render a ContractReport to a Markdown string. Pure — no I/O."""
    parts = []

    # ── Header ────────────────────────────────────────────────────────────────
    parts.append("# Contract Review Report")
    parts.append("")
    parts.append(f"**Document:** {report.original_filename}")
    parts.append(f"**Document ID:** {report.document_id}")
    parts.append(f"**Uploaded:** {report.uploaded_at}")
    parts.append(f"**Review generated:** {report.generated_at}")
    if report.processing_started_at:
        parts.append(f"**Processing started:** {report.processing_started_at}")

    if report.ocr_used:
        conf_note = (
            f" (confidence: {report.ocr_confidence:.0%})"
            if report.ocr_confidence is not None
            else ""
        )
        parts.append("")
        parts.append(
            f"> **OCR caveat:** This document was processed via OCR{conf_note}. "
            f"Text extraction may be imperfect; review source document for accuracy."
        )

    # Ingest-error short-circuit (Edge Case 1 / AC-20)
    if report.ingest_error:
        err_msg = report.ingest_error.get("message", str(report.ingest_error))
        parts.append("")
        parts.append("## Document Could Not Be Processed")
        parts.append("")
        parts.append(f"This document could not be ingested: **{err_msg}**")
        parts.append("")
        parts.append(
            "No clause analysis was performed. Please check the source file and re-upload."
        )
        return "\n".join(parts)

    s = report.summary
    parts.append("")
    parts.append(
        f"**{s.total_clauses} clauses reviewed · "
        f"{s.validated_findings} findings "
        f"({s.high} high / {s.medium} medium / {s.low} low) · "
        f"{s.clean_clauses} clean**"
    )

    # ── Findings ──────────────────────────────────────────────────────────────
    if not report.findings:
        parts.append("")
        parts.append("## No Findings")
        parts.append("")
        parts.append(
            f"No clauses were flagged as requiring attention. All {s.clean_clauses} reviewed "
            f"clauses were found to be clean."
        )
    else:
        for f in sorted(report.findings, key=lambda x: x.position):
            locator = f.section_number if f.section_number is not None else "§ n/a"
            ctype = f.clause_type if f.clause_type is not None else "uncategorized"
            severity = (
                f.risk_level if f.risk_level is not None else "severity unavailable"
            )

            parts.append("")
            parts.append(
                f"## Finding {f.position} — {locator} ({ctype}) `{f.clause_id}`"
            )
            parts.append("")
            parts.append(f"**Severity:** {severity}")
            if f.risk_rationale:
                parts.append(f"**Rationale:** {f.risk_rationale}")
            parts.append("")
            parts.append("**Original clause:**")
            parts.append("")
            parts.append(f"> {f.clause_text}")

            if f.path_taken is not None or f.confidence_score is not None:
                prov_parts = []
                if f.path_taken is not None:
                    prov_parts.append(f"path: {f.path_taken}")
                if f.confidence_score is not None:
                    prov_parts.append(f"confidence: {f.confidence_score:.2f}")
                parts.append("")
                parts.append(f"*Provenance — {', '.join(prov_parts)}*")

            if f.evidence:
                parts.append("")
                parts.append("**Supporting evidence:**")
                for ev in f.evidence:
                    parts.append("")
                    parts.append(f"- *{ev.source_reference}*: {ev.snippet_text}")

            parts.append("")
            if f.rewrite_state == "rewritten" and f.suggested_rewrite:
                parts.append("**Suggested rewrite:**")
                parts.append("")
                parts.append(f"> {f.suggested_rewrite}")
            elif f.rewrite_state == "unavailable":
                parts.append("**Suggested rewrite:** _no rewrite available_")
            # "not_eligible" → nothing rendered

    # ── Clean-clause summary (D4 — count only, never enumerated) ─────────────
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append(
        f"**Clean clauses:** {s.clean_clauses} clause(s) passed review without findings."
    )

    # ── Processing footer ─────────────────────────────────────────────────────
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append("### Processing details")
    parts.append("")
    if report.node_timings:
        parts.append("**Node timings (upstream):**")
        for node, elapsed in report.node_timings.items():
            parts.append(f"- {node}: {elapsed:.4f}s")
        parts.append("")

    # Total elapsed — computed from ISO timestamps (review item 1)
    total_elapsed_str = _compute_total_elapsed(
        report.processing_started_at, report.generated_at
    )
    parts.append(f"**Total elapsed:** {total_elapsed_str}")
    parts.append("")
    if report.error_count:
        parts.append(f"**Upstream errors:** {report.error_count}")
        parts.append("")

    return "\n".join(parts)


def _compute_total_elapsed(
    processing_started_at: Optional[str],
    generated_at: str,
) -> str:
    """Compute total elapsed seconds between processing_started_at and generated_at.
    Returns 'unknown' when processing_started_at is None or unparseable."""
    if processing_started_at is None:
        return "unknown"
    try:
        start = datetime.fromisoformat(processing_started_at)
        end = datetime.fromisoformat(generated_at)
        elapsed = (end - start).total_seconds()
        return f"{elapsed:.2f}s"
    except (ValueError, TypeError):
        return "unknown"
