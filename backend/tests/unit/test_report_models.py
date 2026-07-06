"""
Unit tests for app.models.report — Pydantic boundary models for Node 7.

TDD red phase: all tests fail (ImportError) until Task 4 implements the models.
Run: python -m pytest tests/unit/test_report_models.py -v
"""

import pytest
from pydantic import ValidationError


def _make_evidence(**kwargs):
    from app.models.report import ReportEvidence

    defaults = {"source_reference": "doc.pdf §1", "snippet_text": "Some snippet text."}
    defaults.update(kwargs)
    return ReportEvidence(**defaults)


def _make_finding(**kwargs):
    from app.models.report import ReportFinding

    defaults = {
        "clause_id": "c1",
        "position": 1,
        "clause_text": "The contractor shall indemnify...",
        "rewrite_state": "not_eligible",
    }
    defaults.update(kwargs)
    return ReportFinding(**defaults)


def _make_summary(**kwargs):
    from app.models.report import ReportSummary

    defaults = {
        "total_clauses": 5,
        "validated_findings": 2,
        "clean_clauses": 3,
        "high": 1,
        "medium": 1,
        "low": 0,
    }
    defaults.update(kwargs)
    return ReportSummary(**defaults)


def _make_report(**kwargs):
    from app.models.report import ContractReport

    defaults = {
        "document_id": "doc-001",
        "original_filename": "contract.pdf",
        "uploaded_at": "2026-07-06T00:00:00+00:00",
        "generated_at": "2026-07-06T00:01:00+00:00",
        "summary": _make_summary(),
    }
    defaults.update(kwargs)
    return ContractReport(**defaults)


def test_contract_report_roundtrips_json():
    """A fully-built ContractReport serializes via model_dump_json and re-parses equal."""
    from app.models.report import ContractReport

    finding = _make_finding(
        rewrite_state="rewritten",
        suggested_rewrite="The contractor shall not be liable...",
        risk_level="high",
        evidence=[_make_evidence()],
    )
    report = _make_report(findings=[finding])

    json_str = report.model_dump_json()
    parsed = ContractReport.model_validate_json(json_str)
    assert parsed == report
    assert parsed.findings[0].rewrite_state == "rewritten"
    assert parsed.findings[0].evidence[0].snippet_text == "Some snippet text."


def test_finding_rewrite_state_values():
    """`rewrite_state` accepts the three valid labels; `suggested_rewrite` semantics."""
    for state in ("rewritten", "unavailable", "not_eligible"):
        f = _make_finding(rewrite_state=state)
        assert f.rewrite_state == state

    f_rewritten = _make_finding(
        rewrite_state="rewritten", suggested_rewrite="New clause text."
    )
    assert f_rewritten.suggested_rewrite == "New clause text."

    f_none = _make_finding(rewrite_state="unavailable", suggested_rewrite=None)
    assert f_none.suggested_rewrite is None


def test_summary_counts_are_ints():
    """`ReportSummary` fields are int; a built summary's H+M+L == validated_findings
    and clean_clauses == total_clauses - validated_findings when constructed consistently.
    """

    s = _make_summary(
        total_clauses=10, validated_findings=4, clean_clauses=6, high=2, medium=1, low=1
    )
    assert isinstance(s.total_clauses, int)
    assert isinstance(s.validated_findings, int)
    assert isinstance(s.clean_clauses, int)
    assert isinstance(s.high, int)
    assert isinstance(s.medium, int)
    assert isinstance(s.low, int)
    assert s.high + s.medium + s.low == s.validated_findings
    assert s.clean_clauses == s.total_clauses - s.validated_findings


def test_optional_fields_default_none():
    """`section_number`, `clause_type`, `risk_level`, `risk_rationale`, `path_taken`,
    `confidence_score`, and `suggested_rewrite` default to None;
    `evidence` and `findings` default to []."""

    f = _make_finding()
    assert f.section_number is None
    assert f.clause_type is None
    assert f.risk_level is None
    assert f.risk_rationale is None
    assert f.path_taken is None
    assert f.confidence_score is None
    assert f.suggested_rewrite is None
    assert f.evidence == []

    report = _make_report()
    assert report.findings == []
    assert report.processing_started_at is None
    assert report.ocr_used is False
    assert report.ocr_confidence is None
    assert report.ingest_error is None
    assert report.error_count == 0


def test_malformed_finding_raises():
    """Constructing `ReportFinding` without `clause_text` raises `pydantic.ValidationError`."""
    from app.models.report import ReportFinding

    with pytest.raises(ValidationError):
        ReportFinding(clause_id="c1", position=1, rewrite_state="not_eligible")
        # clause_text is required — omitting it must raise

    with pytest.raises(ValidationError):
        ReportFinding(
            clause_id="c1",
            position="not-an-int",  # wrong type for position
            clause_text="text",
            rewrite_state="not_eligible",
        )
