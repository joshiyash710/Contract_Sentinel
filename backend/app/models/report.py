"""
Boundary serialization models for the ReportAgent (Node 7).

These Pydantic models are built FROM ContractState (TypedDict) and are NEVER
stored in graph state — constitution §4. The JSON output is
`ContractReport.model_dump_json()`; the Markdown renderer walks the same model,
so the two output formats cannot structurally drift (D1, spec §8a).
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class ReportEvidence(BaseModel):
    """One evidence snippet behind a finding (001 snippet shape).

    `snippet_text` is already truncated by the assembler to
    REPORT_EVIDENCE_TEXT_MAX_CHARS before model construction.
    """

    source_reference: str
    snippet_text: str


class ReportFinding(BaseModel):
    """One VALIDATED clause rendered as a finding (spec §2.3 item 2).

    `rewrite_state` is a three-way enum flattened by the assembler from the raw
    ContractState `suggested_rewrite` key (absent / None / str):
        "rewritten"    — a rewrite exists; `suggested_rewrite` is set
        "unavailable"  — the key was present but None (LLM failed / circuit open)
        "not_eligible" — the key was absent (clause not sent to Redline)
    This flattening lives in one place (the assembler) so both renderers consume it
    without re-deriving the three-way logic (spec AC-8).
    """

    clause_id: str
    position: int
    section_number: Optional[str] = None
    clause_type: Optional[str] = None  # ClauseType.value, or None
    risk_level: Optional[str] = (
        None  # RiskLevel.value; None → "severity unavailable" (Edge Case 4)
    )
    risk_rationale: Optional[str] = None
    clause_text: str
    rewrite_state: str  # "rewritten" | "unavailable" | "not_eligible"
    suggested_rewrite: Optional[str] = (
        None  # present only when rewrite_state == "rewritten"
    )
    path_taken: Optional[str] = None  # RetrievalPath.value, or None
    confidence_score: Optional[float] = None
    evidence: List[ReportEvidence] = Field(default_factory=list)
    # Feature 038: True when this finding's risk_level was assigned by the RiskScoreAgent
    # fail-safe path (LLM failure/unparseable/circuit-open/empty text) rather than a genuine
    # model judgment. Defaults False so legacy report JSON deserializes unchanged.
    is_failsafe: bool = False


class ReportSummary(BaseModel):
    """Header roll-up counts (D4 — clean clauses counted, not enumerated)."""

    total_clauses: int
    validated_findings: int
    clean_clauses: int  # non-validated (discarded / status None) — count only (D4)
    high: int
    medium: int
    low: int
    # Feature 038: number of validated findings whose severity was fail-safe (auto-defaulted).
    failsafe_count: int = 0


class ContractReport(BaseModel):
    """The whole serialized report. Built from ContractState; never stored in state."""

    document_id: str
    original_filename: str
    uploaded_at: str
    processing_started_at: Optional[str] = None
    generated_at: str  # the D8 report-generation timestamp
    ocr_used: bool = False
    ocr_confidence: Optional[float] = None
    ingest_error: Optional[dict] = (
        None  # set → minimal "could not process" report (Edge Case 1)
    )
    summary: ReportSummary
    findings: List[ReportFinding] = Field(default_factory=list)  # ordered by position
    node_timings: dict = Field(default_factory=dict)
    error_count: int = 0
    # Feature 038: True when this run's analysis is materially unreliable — the risk-score
    # circuit breaker tripped OR the fail-safe fraction crossed the configured threshold.
    # Renderers/frontend key off this to show a "degraded analysis" banner. Defaults False.
    analysis_degraded: bool = False
