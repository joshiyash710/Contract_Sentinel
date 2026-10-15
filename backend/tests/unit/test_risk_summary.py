"""Feature 066 — the shared risk-summary helper (app/runner/risk_summary.py).

Pure unit tests: summarize_report builds the compact per-clause-type map the dashboard uses; to_row_fields /
from_row round-trip; parity with the legacy read_report_data extraction (AC-7).
"""

import json
from unittest.mock import MagicMock

import app.runner.risk_summary as rs_mod
from app.runner.risk_summary import RiskSummary, summarize_report, to_row_fields, from_row


_REPORT = {
    "summary": {"high": 2, "medium": 1, "low": 3, "total_clauses": 10, "validated_findings": 6},
    "analysis_degraded": False,
    "findings": [
        {"clause_type": "liability", "risk_level": "high"},
        {"clause_type": "liability", "risk_level": "medium"},
        {"clause_type": "indemnification", "risk_level": "high"},
        {"clause_type": None, "risk_level": "low"},          # → Uncategorized
        {"clause_type": "termination", "risk_level": "unknown"},  # excluded (not a severity)
    ],
}


def test_summarize_report_fields_and_by_type():  # AC-7 core
    s = summarize_report(_REPORT)
    assert (s.high, s.medium, s.low) == (2, 1, 3)
    assert s.total_clauses == 10 and s.validated_findings == 6
    assert s.analysis_degraded is False
    assert s.risk_by_type["liability"] == {"low": 0, "medium": 1, "high": 1}
    assert s.risk_by_type["indemnification"]["high"] == 1
    assert s.risk_by_type["Uncategorized"]["low"] == 1
    assert "termination" not in s.risk_by_type  # unknown-severity finding excluded


def test_to_row_fields_and_from_row_roundtrip():  # AC-2 helper
    s = summarize_report(_REPORT)
    fields = to_row_fields(s)
    assert fields["risk_high"] == 2 and fields["analysis_degraded"] is False
    assert isinstance(fields["risk_by_type"], dict)
    # simulate a JobRow carrying those fields (risk_by_type decoded to a dict by the store)
    row = MagicMock(risk_high=2, risk_medium=1, risk_low=3, validated_findings=6,
                    total_clauses=10, analysis_degraded=False, risk_by_type=s.risk_by_type)
    back = from_row(row)
    assert back == s


def test_from_row_none_when_no_summary():  # legacy row
    row = MagicMock(risk_high=None)
    assert from_row(row) is None


def test_from_row_tolerates_json_string_and_malformed():
    s = summarize_report(_REPORT)
    row = MagicMock(risk_high=2, risk_medium=1, risk_low=3, validated_findings=6,
                    total_clauses=10, analysis_degraded=False, risk_by_type=json.dumps(s.risk_by_type))
    assert from_row(row).risk_by_type == s.risk_by_type  # JSON string decoded
    bad = MagicMock(risk_high=2, risk_medium=0, risk_low=0, validated_findings=1,
                    total_clauses=1, analysis_degraded=False, risk_by_type="{not json")
    assert from_row(bad) is None  # malformed → treat as no summary (EC-7)


def test_load_report_summary_best_effort(monkeypatch):  # EC-3
    monkeypatch.setattr(rs_mod.blob_store, "exists", lambda k: True)
    monkeypatch.setattr(rs_mod.blob_store, "read", lambda k: json.dumps(_REPORT).encode("utf-8"))
    s = rs_mod.load_report_summary("/r/x.md")
    assert s.high == 2 and s.risk_by_type["liability"]["high"] == 1
    # unset path → None; unreadable → None (never raises)
    assert rs_mod.load_report_summary(None) is None
    monkeypatch.setattr(rs_mod.blob_store, "exists", lambda k: (_ for _ in ()).throw(OSError("boom")))
    assert rs_mod.load_report_summary("/r/x.md") is None
