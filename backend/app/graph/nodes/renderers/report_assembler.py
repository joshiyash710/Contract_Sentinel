"""
Pure state→model transform for the ReportAgent (Node 7).

assemble_report: ContractState → ContractReport (Pydantic boundary model).
build_evidence_trail: ContractReport → List[dict] (001-shaped trail rows).

PURE — no file I/O, no LLM, no state mutation, no app.config imports
(limits are passed in as arguments). The node (report_agent.py) owns all I/O
and failure handling.
"""

from enum import Enum
from typing import Any, Dict, List

from app.graph.state import (
    ContractState,
    RiskLevel,
    ValidationStatus,
)
from app.models.report import (
    ContractReport,
    ReportEvidence,
    ReportFinding,
    ReportSummary,
)

_MISSING = object()  # sentinel to distinguish "key absent" from "value None"

_SNIPPET_TEXT_PLACEHOLDER = "[snippet text unavailable]"
_SOURCE_REF_PLACEHOLDER = "[source reference unavailable]"


def _enum_value(raw: Any) -> Any:
    """Return raw.value for an Enum, raw unchanged for a str, None for None."""
    if raw is None:
        return None
    if isinstance(raw, Enum):
        return raw.value
    return raw


def assemble_report(
    state: ContractState,
    generated_at: str,
    evidence_text_max_chars: int,
) -> ContractReport:
    """Build a ContractReport from ContractState. Pure — reads state, returns a
    validated Pydantic model. Findings = VALIDATED clauses only (spec §2.4, D5),
    ordered by `position`. Clean clauses are counted, not enumerated (D4). On
    ingest_error, returns a minimal report (empty findings, ingest_error populated)
    — Edge Case 1. generated_at is the shared D8 timestamp."""

    base_kwargs = dict(
        document_id=state.get("document_id", "unknown"),
        original_filename=state.get("original_filename", "unknown"),
        uploaded_at=state.get("uploaded_at", ""),
        processing_started_at=state.get("processing_started_at"),
        generated_at=generated_at,
        ocr_used=state.get("ocr_used", False),
        ocr_confidence=state.get("ocr_confidence"),
        node_timings=state.get("node_timings", {}),
        error_count=state.get("error_count", 0),
    )

    ingest_error = state.get("ingest_error")
    if ingest_error:
        return ContractReport(
            **base_kwargs,
            ingest_error=ingest_error,
            summary=ReportSummary(
                total_clauses=0,
                validated_findings=0,
                clean_clauses=0,
                high=0,
                medium=0,
                low=0,
            ),
            findings=[],
        )

    clauses: Dict[str, Any] = state.get("clauses", {})
    total_clauses = len(clauses)

    findings: List[ReportFinding] = []
    for clause_id, record in clauses.items():
        if record.get("final_status") != ValidationStatus.VALIDATED:
            continue

        # Normalize enum-or-str fields (robust after checkpoint round-trips)
        risk_level = _enum_value(record.get("risk_level"))
        clause_type = _enum_value(record.get("clause_type"))
        path_taken = _enum_value(record.get("path_taken"))

        # Three-state rewrite: absent key → "not_eligible"; None → "unavailable"; str → "rewritten"
        raw_rewrite = record.get("suggested_rewrite", _MISSING)
        if raw_rewrite is _MISSING:
            rewrite_state = "not_eligible"
            suggested_rewrite = None
        elif raw_rewrite is None:
            rewrite_state = "unavailable"
            suggested_rewrite = None
        else:
            rewrite_state = "rewritten"
            suggested_rewrite = raw_rewrite

        # Build evidence list with truncation and missing-field placeholders
        raw_snippets = record.get("evidence_snippets") or []
        evidence = []
        for snip in raw_snippets:
            snippet_text = snip.get("snippet_text", _SNIPPET_TEXT_PLACEHOLDER)
            source_reference = snip.get("source_reference", _SOURCE_REF_PLACEHOLDER)
            evidence.append(
                ReportEvidence(
                    source_reference=str(source_reference),
                    snippet_text=str(snippet_text)[:evidence_text_max_chars],
                )
            )

        findings.append(
            ReportFinding(
                clause_id=clause_id,
                position=record.get("position", 0),
                section_number=record.get("section_number"),
                clause_type=clause_type,
                risk_level=risk_level,
                risk_rationale=record.get("risk_rationale"),
                clause_text=record.get("text", ""),
                rewrite_state=rewrite_state,
                suggested_rewrite=suggested_rewrite,
                path_taken=path_taken,
                confidence_score=record.get("confidence_score"),
                evidence=evidence,
            )
        )

    findings.sort(key=lambda f: f.position)
    validated_findings = len(findings)
    clean_clauses = total_clauses - validated_findings

    high = sum(1 for f in findings if f.risk_level == RiskLevel.HIGH.value)
    medium = sum(1 for f in findings if f.risk_level == RiskLevel.MEDIUM.value)
    low = sum(1 for f in findings if f.risk_level == RiskLevel.LOW.value)

    return ContractReport(
        **base_kwargs,
        summary=ReportSummary(
            total_clauses=total_clauses,
            validated_findings=validated_findings,
            clean_clauses=clean_clauses,
            high=high,
            medium=medium,
            low=low,
        ),
        findings=findings,
    )


def build_evidence_trail(
    report: ContractReport,
    generated_at: str,
) -> List[Dict[str, Any]]:
    """Flatten the report's validated findings into 001-shaped evidence_trail rows
    (spec §2.2, D5). One row per (finding, evidence snippet). retrieved_at =
    generated_at for every row (D8). Returns [] when no finding has evidence."""
    rows = []
    for f in report.findings:  # already validated-only, ordered
        for ev in f.evidence:
            rows.append(
                {
                    "clause_id": f.clause_id,
                    "evidence_source": ev.source_reference,
                    "evidence_text": ev.snippet_text,  # already truncated by assemble_report
                    "retrieved_at": generated_at,  # D8 — shared timestamp
                }
            )
    return rows
