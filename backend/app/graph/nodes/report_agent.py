"""
ReportAgent — LangGraph Node 7 (terminal assembly node).

Assembles a Pydantic ContractReport from ContractState, writes a Markdown
report + JSON sibling under REPORT_OUTPUT_DIR, and returns a partial dict:
    {report_path, evidence_trail, current_node, node_timings}
plus error_count: 1 ONLY when the file write fails.

Makes NO LLM call (D3). Never writes processing_completed_at (runner-owned, D2).
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import app.config as _config
from app import blob_store
from app.graph.nodes.renderers import (
    assemble_report,
    build_evidence_trail,
    render_markdown,
)
from app.graph.state import ContractState

# Module-level names re-exposed for monkeypatching (mirrors risk_score_agent.py:42-49).
REPORT_OUTPUT_DIR = _config.REPORT_OUTPUT_DIR
REPORT_MD_FILENAME_TEMPLATE = _config.REPORT_MD_FILENAME_TEMPLATE
REPORT_JSON_FILENAME_TEMPLATE = _config.REPORT_JSON_FILENAME_TEMPLATE
REPORT_EVIDENCE_TEXT_MAX_CHARS = _config.REPORT_EVIDENCE_TEXT_MAX_CHARS
# Feature 038: honest LLM-failure surfacing — passed into assemble_report.
HONEST_FAILURE_SURFACING_ENABLED = _config.HONEST_FAILURE_SURFACING_ENABLED
ANALYSIS_DEGRADED_FAILSAFE_FRACTION = _config.ANALYSIS_DEGRADED_FAILSAFE_FRACTION

logger = logging.getLogger("contractsentinel.report")


def _cleanup_orphan(json_path: Path, md_path: Path) -> None:
    """If json_path exists but md_path does not, unlink the orphan JSON (AC-19a).
    Best-effort — swallows its own OSError so cleanup never masks the original error."""
    try:
        if json_path.exists() and not md_path.exists():
            json_path.unlink()
            logger.debug("ReportAgent: unlinked orphan JSON %s", json_path)
    except OSError as cleanup_exc:
        logger.debug("ReportAgent: cleanup of orphan JSON failed: %s", cleanup_exc)


def report_agent(state: ContractState) -> dict:
    """LangGraph Node 7 (ReportAgent), the terminal node.

    Assembles a Pydantic report from ContractState, writes a Markdown report +
    JSON sibling under REPORT_OUTPUT_DIR, and returns a partial dict:
    report_path, evidence_trail, current_node, node_timings — plus error_count:1
    ONLY when the file write fails.  Makes NO LLM call. Never writes
    processing_completed_at (runner-owned, D2).
    """
    start_time = time.monotonic()
    current_node = "report"  # pinned literal (spec §7.5)
    document_id = state.get("document_id", "unknown")
    generated_at = datetime.now(timezone.utc).isoformat()  # D8 — one timestamp per run

    # ── Step 1: Assemble report model (pure, no I/O) ──────────────────────────
    report_model = assemble_report(
        state,
        generated_at,
        REPORT_EVIDENCE_TEXT_MAX_CHARS,
        honest_enabled=HONEST_FAILURE_SURFACING_ENABLED,
        degraded_fraction=ANALYSIS_DEGRADED_FAILSAFE_FRACTION,
    )
    evidence_trail = build_evidence_trail(report_model, generated_at)

    # ── Warn on empty clauses (no ingest_error) ───────────────────────────────
    if not state.get("ingest_error") and not state.get("clauses"):
        logger.warning(
            "ReportAgent: document_id=%s has no clauses and no ingest_error — "
            "writing a clean (zero-findings) report.",
            document_id,
        )

    # ── Step 2: Render (pure, no I/O) ─────────────────────────────────────────
    md_text = render_markdown(report_model)
    json_text = report_model.model_dump_json(indent=2)

    # ── Step 3: Resolve paths ─────────────────────────────────────────────────
    out_dir = Path(REPORT_OUTPUT_DIR)
    json_path = out_dir / REPORT_JSON_FILENAME_TEMPLATE.format(document_id=document_id)
    md_path = out_dir / REPORT_MD_FILENAME_TEMPLATE.format(document_id=document_id)

    # ── Step 4: Write files (JSON first, then Markdown — AC-19a) ──────────────
    report_path: Optional[str] = None
    try:
        # Feature 052: persist via blob_store (local disk default, or Turso BLOBs when configured).
        blob_store.write(str(json_path), json_text.encode("utf-8"))  # JSON first (D1 / AC-19a)
        blob_store.write(str(md_path), md_text.encode("utf-8"))  # Markdown second
        report_path = str(md_path)
    except Exception as exc:  # any report-write failure (disk OSError / Turso libsql) → degrade
        logger.error(
            "ReportAgent: failed to write report for document_id=%s: %s",
            document_id,
            exc,
        )
        _cleanup_orphan(json_path, md_path)
        elapsed = time.monotonic() - start_time
        return {
            "report_path": None,
            "evidence_trail": evidence_trail,  # deliberate — computed pre-write (review item 2)
            "current_node": current_node,
            "node_timings": {current_node: elapsed},
            "error_count": 1,
        }

    elapsed = time.monotonic() - start_time

    logger.info(
        "ReportAgent completed",
        extra={
            "total_clauses": report_model.summary.total_clauses,
            "validated_findings": report_model.summary.validated_findings,
            "clean_clauses": report_model.summary.clean_clauses,
            "high": report_model.summary.high,
            "medium": report_model.summary.medium,
            "low": report_model.summary.low,
            "evidence_rows": len(evidence_trail),
            "report_chars": len(md_text),
            "write_ok": True,
            "elapsed_seconds": round(elapsed, 4),
        },
    )

    return {
        "report_path": report_path,
        "evidence_trail": evidence_trail,
        "current_node": current_node,
        "node_timings": {current_node: elapsed},
        # NOTE: no processing_completed_at (D2); no clauses key; no error_count on success.
    }
