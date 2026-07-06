"""
Unit tests for report_assembler.py — assemble_report + build_evidence_trail.

TDD red phase: all tests fail (ImportError) until Task 7 implements the module.
Pure function tests — no mocks, no I/O. Fixture ContractState dicts are built
directly. Fixed generated_at = "2026-07-06T00:00:00+00:00" throughout.
Run: python -m pytest tests/unit/test_report_assembler.py -v
"""

import copy

GENERATED_AT = "2026-07-06T00:00:00+00:00"
MAX_CHARS = 2000


def make_clause(
    clause_id="c1",
    text="The contractor shall indemnify the client.",
    position=1,
    section_number="§1",
    clause_type=None,
    final_status=None,
    risk_level=None,
    risk_rationale=None,
    suggested_rewrite=None,
    suggested_rewrite_absent=False,  # if True, key not included at all
    evidence_snippets=None,
    confidence_score=None,
    path_taken=None,
):
    """Build a clause record dict as it would appear in ContractState.clauses."""

    record = {
        "text": text,
        "position": position,
        "section_number": section_number,
        "final_status": final_status,
        "evidence_snippets": evidence_snippets or [],
    }
    if clause_type is not None:
        record["clause_type"] = clause_type
    if risk_level is not None:
        record["risk_level"] = risk_level
    if risk_rationale is not None:
        record["risk_rationale"] = risk_rationale
    if confidence_score is not None:
        record["confidence_score"] = confidence_score
    if path_taken is not None:
        record["path_taken"] = path_taken
    if not suggested_rewrite_absent:
        record["suggested_rewrite"] = suggested_rewrite
    return clause_id, record


def make_state(clauses=None, ingest_error=None, **kwargs):
    state = {
        "document_id": "doc-001",
        "original_filename": "contract.pdf",
        "uploaded_at": "2026-07-06T00:00:00+00:00",
        "processing_started_at": "2026-07-06T00:00:00+00:00",
        "ocr_used": False,
        "node_timings": {},
        "error_count": 0,
    }
    state.update(kwargs)
    if clauses is not None:
        state["clauses"] = dict(clauses)
    if ingest_error is not None:
        state["ingest_error"] = ingest_error
    return state


def _validated_clause(clause_id, position, **kwargs):
    from app.graph.state import ValidationStatus, RiskLevel

    return make_clause(
        clause_id=clause_id,
        position=position,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
        **kwargs,
    )


def _discarded_clause(clause_id, position):
    from app.graph.state import ValidationStatus

    return make_clause(
        clause_id=clause_id,
        position=position,
        final_status=ValidationStatus.DISCARDED,
    )


# ── assemble_report tests ──────────────────────────────────────────────────────


def test_only_validated_become_findings():
    """Mixed VALIDATED / DISCARDED / final_status=None → only VALIDATED in findings (AC-1)."""
    from app.graph.nodes.renderers.report_assembler import assemble_report

    cid1, r1 = _validated_clause("c1", 1)
    cid2, r2 = _discarded_clause("c2", 2)
    cid3, r3 = make_clause("c3", final_status=None)
    state = make_state(clauses=[(cid1, r1), (cid2, r2), (cid3, r3)])

    report = assemble_report(state, GENERATED_AT, MAX_CHARS)
    assert len(report.findings) == 1
    assert report.findings[0].clause_id == "c1"


def test_findings_ordered_by_position():
    """Findings sorted by position regardless of clauses dict insertion order (AC-2)."""
    from app.graph.nodes.renderers.report_assembler import assemble_report

    cid3, r3 = _validated_clause("c3", 3)
    cid1, r1 = _validated_clause("c1", 1)
    cid2, r2 = _validated_clause("c2", 2)
    state = make_state(clauses=[(cid3, r3), (cid1, r1), (cid2, r2)])

    report = assemble_report(state, GENERATED_AT, MAX_CHARS)
    positions = [f.position for f in report.findings]
    assert positions == sorted(positions)
    assert [f.clause_id for f in report.findings] == ["c1", "c2", "c3"]


def test_summary_counts_correct():
    """total_clauses, validated_findings, clean_clauses, H/M/L match fixture (D4/AC-9)."""
    from app.graph.nodes.renderers.report_assembler import assemble_report
    from app.graph.state import ValidationStatus, RiskLevel

    cid1, r1 = make_clause(
        "c1",
        position=1,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
    )
    cid2, r2 = make_clause(
        "c2",
        position=2,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.MEDIUM,
    )
    cid3, r3 = make_clause(
        "c3",
        position=3,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.LOW,
    )
    cid4, r4 = _discarded_clause("c4", 4)
    cid5, r5 = _discarded_clause("c5", 5)
    state = make_state(
        clauses=[(cid1, r1), (cid2, r2), (cid3, r3), (cid4, r4), (cid5, r5)]
    )

    report = assemble_report(state, GENERATED_AT, MAX_CHARS)
    s = report.summary
    assert s.total_clauses == 5
    assert s.validated_findings == 3
    assert s.clean_clauses == 2
    assert s.high == 1
    assert s.medium == 1
    assert s.low == 1


def test_rewrite_state_three_way():
    """absent key → "not_eligible"; None value → "unavailable"; str → "rewritten" (AC-8)."""
    from app.graph.nodes.renderers.report_assembler import assemble_report
    from app.graph.state import ValidationStatus, RiskLevel

    # Key absent — not_eligible
    cid1, r1 = make_clause(
        "c1",
        position=1,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
        suggested_rewrite_absent=True,
    )
    # Key present, value None — unavailable
    cid2, r2 = make_clause(
        "c2",
        position=2,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
        suggested_rewrite=None,
    )
    # Key present, value str — rewritten
    cid3, r3 = make_clause(
        "c3",
        position=3,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
        suggested_rewrite="New clause text.",
    )
    state = make_state(clauses=[(cid1, r1), (cid2, r2), (cid3, r3)])

    report = assemble_report(state, GENERATED_AT, MAX_CHARS)
    by_id = {f.clause_id: f for f in report.findings}
    assert by_id["c1"].rewrite_state == "not_eligible"
    assert by_id["c1"].suggested_rewrite is None
    assert by_id["c2"].rewrite_state == "unavailable"
    assert by_id["c2"].suggested_rewrite is None
    assert by_id["c3"].rewrite_state == "rewritten"
    assert by_id["c3"].suggested_rewrite == "New clause text."


def test_evidence_text_truncated():
    """A snippet longer than the cap is truncated to evidence_text_max_chars (AC-12a, Edge Case 6)."""
    from app.graph.nodes.renderers.report_assembler import assemble_report
    from app.graph.state import ValidationStatus, RiskLevel

    long_text = "x" * 300
    snippets = [{"snippet_text": long_text, "source_reference": "doc.pdf §1"}]
    cid1, r1 = make_clause(
        "c1",
        position=1,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
        evidence_snippets=snippets,
    )
    state = make_state(clauses=[(cid1, r1)])

    cap = 100
    report = assemble_report(state, GENERATED_AT, cap)
    assert len(report.findings[0].evidence[0].snippet_text) == cap


def test_missing_snippet_fields_placeholder():
    """Snippet missing snippet_text / source_reference → defined placeholder, no KeyError (Edge Case 7)."""
    from app.graph.nodes.renderers.report_assembler import assemble_report
    from app.graph.state import ValidationStatus, RiskLevel

    snippets = [{}]  # entirely empty dict
    cid1, r1 = make_clause(
        "c1",
        position=1,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
        evidence_snippets=snippets,
    )
    state = make_state(clauses=[(cid1, r1)])

    report = assemble_report(state, GENERATED_AT, MAX_CHARS)
    ev = report.findings[0].evidence[0]
    assert isinstance(ev.snippet_text, str)
    assert isinstance(ev.source_reference, str)


def test_empty_evidence_finding():
    """Validated finding with evidence_snippets==[] / None → evidence==[], no crash (AC-7)."""
    from app.graph.nodes.renderers.report_assembler import assemble_report
    from app.graph.state import ValidationStatus, RiskLevel

    cid1, r1 = make_clause(
        "c1",
        position=1,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
        evidence_snippets=[],
    )
    cid2, r2 = make_clause(
        "c2",
        position=2,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
        evidence_snippets=None,
    )
    state = make_state(clauses=[(cid1, r1), (cid2, r2)])

    report = assemble_report(state, GENERATED_AT, MAX_CHARS)
    for f in report.findings:
        assert f.evidence == []


def test_missing_risk_level_placeholder_path():
    """Validated finding with risk_level=None still assembles (Edge Case 4)."""
    from app.graph.nodes.renderers.report_assembler import assemble_report
    from app.graph.state import ValidationStatus

    cid1, r1 = make_clause(
        "c1", position=1, final_status=ValidationStatus.VALIDATED, risk_level=None
    )
    state = make_state(clauses=[(cid1, r1)])

    report = assemble_report(state, GENERATED_AT, MAX_CHARS)
    assert report.findings[0].risk_level is None


def test_ingest_error_minimal_report():
    """ingest_error set → findings==[], ingest_error populated, zeroed ReportSummary (Edge Case 1/AC-20)."""
    from app.graph.nodes.renderers.report_assembler import assemble_report

    state = make_state(ingest_error={"message": "OCR failed", "code": "ocr_error"})
    report = assemble_report(state, GENERATED_AT, MAX_CHARS)

    assert report.findings == []
    assert report.ingest_error == {"message": "OCR failed", "code": "ocr_error"}
    assert report.summary.total_clauses == 0
    assert report.summary.validated_findings == 0
    assert report.summary.clean_clauses == 0
    assert report.summary.high == 0
    assert report.summary.medium == 0
    assert report.summary.low == 0


def test_enum_or_str_risk_level():
    """risk_level given as a RiskLevel enum or its str both normalize to the same .value."""
    from app.graph.nodes.renderers.report_assembler import assemble_report
    from app.graph.state import ValidationStatus, RiskLevel

    cid1, r1 = make_clause(
        "c1",
        position=1,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
    )  # enum
    cid2, r2 = make_clause(
        "c2", position=2, final_status=ValidationStatus.VALIDATED, risk_level="high"
    )  # str
    state = make_state(clauses=[(cid1, r1), (cid2, r2)])

    report = assemble_report(state, GENERATED_AT, MAX_CHARS)
    by_id = {f.clause_id: f for f in report.findings}
    assert by_id["c1"].risk_level == by_id["c2"].risk_level == "high"


def test_assembler_does_not_mutate_state():
    """Input state/clauses unchanged after assemble_report (AC-16 precondition)."""
    from app.graph.nodes.renderers.report_assembler import assemble_report
    from app.graph.state import ValidationStatus, RiskLevel

    cid1, r1 = make_clause(
        "c1",
        position=1,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
    )
    state = make_state(clauses=[(cid1, r1)])
    state_before = copy.deepcopy(state)

    assemble_report(state, GENERATED_AT, MAX_CHARS)
    assert state == state_before


# ── build_evidence_trail tests ─────────────────────────────────────────────────


def test_trail_validated_only():
    """build_evidence_trail emits rows only for validated findings with ≥1 snippet;
    discarded/None clauses contribute none (D5/AC-13)."""
    from app.graph.nodes.renderers.report_assembler import (
        assemble_report,
        build_evidence_trail,
    )
    from app.graph.state import ValidationStatus, RiskLevel

    snippets = [{"snippet_text": "Found.", "source_reference": "doc.pdf §1"}]
    cid1, r1 = make_clause(
        "c1",
        position=1,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
        evidence_snippets=snippets,
    )
    cid2, r2 = _discarded_clause("c2", 2)
    state = make_state(clauses=[(cid1, r1), (cid2, r2)])

    report = assemble_report(state, GENERATED_AT, MAX_CHARS)
    trail = build_evidence_trail(report, GENERATED_AT)
    assert len(trail) == 1
    assert trail[0]["clause_id"] == "c1"


def test_trail_row_shape_and_mapping():
    """Every trail row has exactly {clause_id, evidence_source, evidence_text, retrieved_at};
    evidence_source == snippet.source_reference, evidence_text == snippet.snippet_text (AC-12/12a).
    """
    from app.graph.nodes.renderers.report_assembler import (
        assemble_report,
        build_evidence_trail,
    )
    from app.graph.state import ValidationStatus, RiskLevel

    snippets = [{"snippet_text": "Relevant text.", "source_reference": "doc.pdf §2"}]
    cid1, r1 = make_clause(
        "c1",
        position=1,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
        evidence_snippets=snippets,
    )
    state = make_state(clauses=[(cid1, r1)])

    report = assemble_report(state, GENERATED_AT, MAX_CHARS)
    trail = build_evidence_trail(report, GENERATED_AT)
    assert len(trail) == 1
    row = trail[0]
    assert set(row.keys()) == {
        "clause_id",
        "evidence_source",
        "evidence_text",
        "retrieved_at",
    }
    assert row["clause_id"] == "c1"
    assert row["evidence_source"] == "doc.pdf §2"
    assert row["evidence_text"] == "Relevant text."
    assert row["retrieved_at"] == GENERATED_AT


def test_trail_shared_timestamp():
    """All rows from one call share one retrieved_at == generated_at (D8/AC-12a)."""
    from app.graph.nodes.renderers.report_assembler import (
        assemble_report,
        build_evidence_trail,
    )
    from app.graph.state import ValidationStatus, RiskLevel

    snippets = [
        {"snippet_text": "A.", "source_reference": "doc.pdf §1"},
        {"snippet_text": "B.", "source_reference": "doc.pdf §2"},
    ]
    cid1, r1 = make_clause(
        "c1",
        position=1,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
        evidence_snippets=snippets,
    )
    state = make_state(clauses=[(cid1, r1)])

    report = assemble_report(state, GENERATED_AT, MAX_CHARS)
    trail = build_evidence_trail(report, GENERATED_AT)
    assert len(trail) == 2
    assert all(row["retrieved_at"] == GENERATED_AT for row in trail)


def test_trail_empty_when_no_evidence():
    """Validated findings all without evidence → build_evidence_trail returns []."""
    from app.graph.nodes.renderers.report_assembler import (
        assemble_report,
        build_evidence_trail,
    )
    from app.graph.state import ValidationStatus, RiskLevel

    cid1, r1 = make_clause(
        "c1",
        position=1,
        final_status=ValidationStatus.VALIDATED,
        risk_level=RiskLevel.HIGH,
        evidence_snippets=[],
    )
    state = make_state(clauses=[(cid1, r1)])

    report = assemble_report(state, GENERATED_AT, MAX_CHARS)
    trail = build_evidence_trail(report, GENERATED_AT)
    assert trail == []
