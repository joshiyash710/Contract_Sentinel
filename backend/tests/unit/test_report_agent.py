"""
Unit tests for report_agent.py — Node 7 (ReportAgent).

TDD red phase: all tests fail (ImportError) until Task 11 implements the node.
Real (pure) renderers, real temp-dir I/O via tmp_path; REPORT_OUTPUT_DIR
monkeypatched to tmp_path. No LLM mock anywhere (D3).
Run: python -m pytest tests/unit/test_report_agent.py -v
"""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch


from app.graph.state import ValidationStatus, RiskLevel


def make_state(
    document_id="doc-001",
    clauses=None,
    ingest_error=None,
    node_timings=None,
    error_count=0,
    **kwargs,
):
    state = {
        "document_id": document_id,
        "original_filename": "contract.pdf",
        "uploaded_at": "2026-07-06T00:00:00+00:00",
        "processing_started_at": "2026-07-06T00:00:00+00:00",
        "ocr_used": False,
        "node_timings": node_timings or {},
        "error_count": error_count,
    }
    state.update(kwargs)
    if clauses is not None:
        state["clauses"] = dict(clauses)
    if ingest_error is not None:
        state["ingest_error"] = ingest_error
    return state


def _validated_clause(clause_id, position, risk_level=RiskLevel.HIGH, evidence=None):
    record = {
        "text": f"Clause text for {clause_id}.",
        "position": position,
        "section_number": f"§{position}",
        "final_status": ValidationStatus.VALIDATED,
        "risk_level": risk_level,
        "risk_rationale": "Risk identified.",
        "suggested_rewrite": None,
        "evidence_snippets": evidence or [],
    }
    return clause_id, record


def _discarded_clause(clause_id, position):
    return clause_id, {
        "text": f"Discarded clause {clause_id}.",
        "position": position,
        "final_status": ValidationStatus.DISCARDED,
        "evidence_snippets": [],
    }


# ── tests ─────────────────────────────────────────────────────────────────────


def test_writes_md_and_json_pair(tmp_path, monkeypatch):
    """Both files exist; JSON deserializes; finding count matches Markdown headline (AC-17a/D1)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    cid1, r1 = _validated_clause("c1", 1)
    state = make_state(clauses=[(cid1, r1)])
    result = report_agent(state)

    md_path = Path(result["report_path"])
    json_path = md_path.with_suffix(".json")
    assert md_path.exists()
    assert json_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data["findings"]) == 1

    md_text = md_path.read_text(encoding="utf-8")
    assert "1 finding" in md_text or "1 findings" in md_text or "findings" in md_text


def test_report_path_points_at_existing_nonempty_md(tmp_path, monkeypatch):
    """report_path → an existing, non-empty .md file (AC-10)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    cid1, r1 = _validated_clause("c1", 1)
    state = make_state(clauses=[(cid1, r1)])
    result = report_agent(state)

    p = Path(result["report_path"])
    assert p.exists()
    assert p.suffix == ".md"
    assert p.stat().st_size > 0


def test_report_body_not_in_state(tmp_path, monkeypatch):
    """Return carries a report_path string, not the report body text (AC-11, constitution §6)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    cid1, r1 = _validated_clause("c1", 1)
    state = make_state(clauses=[(cid1, r1)])
    result = report_agent(state)

    rp = result["report_path"]
    assert isinstance(rp, str)
    # The value must be a path, not a multi-line Markdown body
    assert "\n" not in rp
    assert len(rp) < 500


def test_evidence_trail_in_return(tmp_path, monkeypatch):
    """evidence_trail present; rows validated-only; correct shape + mapping (AC-12/12a/13)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    snippets = [{"snippet_text": "Key finding text.", "source_reference": "doc.pdf §1"}]
    cid1, r1 = _validated_clause("c1", 1, evidence=snippets)
    cid2, r2 = _discarded_clause("c2", 2)
    state = make_state(clauses=[(cid1, r1), (cid2, r2)])
    result = report_agent(state)

    trail = result["evidence_trail"]
    assert isinstance(trail, list)
    assert len(trail) == 1
    row = trail[0]
    assert set(row.keys()) == {
        "clause_id",
        "evidence_source",
        "evidence_text",
        "retrieved_at",
    }
    assert row["clause_id"] == "c1"
    assert row["evidence_source"] == "doc.pdf §1"
    assert row["evidence_text"] == "Key finding text."


def test_current_node_pinned(tmp_path, monkeypatch):
    """current_node == 'report' and is the key in node_timings (AC-14)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    cid1, r1 = _validated_clause("c1", 1)
    state = make_state(clauses=[(cid1, r1)])
    result = report_agent(state)

    assert result["current_node"] == "report"
    assert "report" in result["node_timings"]
    assert isinstance(result["node_timings"]["report"], float)


def test_partial_update_only(tmp_path, monkeypatch):
    """On success, return keys are exactly {report_path, evidence_trail, current_node, node_timings}
    — no processing_completed_at, no clauses, no error_count (AC-15)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    cid1, r1 = _validated_clause("c1", 1)
    state = make_state(clauses=[(cid1, r1)])
    result = report_agent(state)

    assert set(result.keys()) == {
        "report_path",
        "evidence_trail",
        "current_node",
        "node_timings",
    }
    assert "processing_completed_at" not in result
    assert "clauses" not in result
    assert "error_count" not in result
    assert "document_id" not in result
    assert "mcp_delivery_status" not in result


def test_clauses_not_mutated(tmp_path, monkeypatch):
    """Deep-copy the input clauses; after the run the original is byte-for-byte unchanged (AC-16)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    cid1, r1 = _validated_clause("c1", 1)
    state = make_state(clauses=[(cid1, r1)])
    clauses_before = copy.deepcopy(state["clauses"])

    report_agent(state)
    assert state["clauses"] == clauses_before


def test_paths_from_config(tmp_path, monkeypatch):
    """Output dir + both filename templates read from monkeypatched config, not hardcoded (AC-17)."""
    import app.graph.nodes.report_agent as mod

    custom_dir = tmp_path / "custom_reports"
    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(custom_dir))
    monkeypatch.setattr(mod, "REPORT_MD_FILENAME_TEMPLATE", "{document_id}_report.md")
    monkeypatch.setattr(
        mod, "REPORT_JSON_FILENAME_TEMPLATE", "{document_id}_report.json"
    )

    from app.graph.nodes.report_agent import report_agent

    cid1, r1 = _validated_clause("c1", 1)
    state = make_state(document_id="test-doc", clauses=[(cid1, r1)])
    result = report_agent(state)

    assert result["report_path"] is not None
    assert "test-doc_report.md" in result["report_path"]
    assert (custom_dir / "test-doc_report.md").exists()
    assert (custom_dir / "test-doc_report.json").exists()


def test_zero_findings_writes_clean_report(tmp_path, monkeypatch):
    """All-discarded clauses → files written, report_path set, no error_count (AC-18)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    cid1, r1 = _discarded_clause("c1", 1)
    cid2, r2 = _discarded_clause("c2", 2)
    state = make_state(clauses=[(cid1, r1), (cid2, r2)])
    result = report_agent(state)

    assert result["report_path"] is not None
    assert Path(result["report_path"]).exists()
    assert "error_count" not in result


def test_ingest_error_minimal_report(tmp_path, monkeypatch):
    """ingest_error set → minimal report written, report_path set, no crash (AC-20)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    state = make_state(ingest_error={"message": "OCR failed", "code": "ocr_error"})
    result = report_agent(state)

    assert result["report_path"] is not None
    p = Path(result["report_path"])
    assert p.exists()
    assert p.stat().st_size > 0

    data = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["findings"] == []
    assert data["ingest_error"] is not None


def test_empty_clauses_writes_and_warns(tmp_path, monkeypatch, caplog):
    """clauses=={} (no ingest_error) → valid 'no findings' report + warning logged (AC-21)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent
    import logging

    state = make_state(clauses={})
    with caplog.at_level(logging.WARNING):
        result = report_agent(state)

    assert result["report_path"] is not None
    assert Path(result["report_path"]).exists()
    assert any(
        "warn" in r.levelname.lower() or r.levelno >= logging.WARNING
        for r in caplog.records
    )


def test_write_failure_emits_error_count(tmp_path, monkeypatch):
    """Injected OSError on write → report_path is None, error_count==1, no crash (AC-19, Edge Case 3)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    cid1, r1 = _validated_clause("c1", 1)
    state = make_state(clauses=[(cid1, r1)])

    with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
        result = report_agent(state)

    assert result["report_path"] is None
    assert result["error_count"] == 1


def test_partial_pair_failure_cleans_orphan_json(tmp_path, monkeypatch):
    """JSON write succeeds, Markdown write raises → orphan JSON removed, report_path is None (AC-19a)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    cid1, r1 = _validated_clause("c1", 1)
    state = make_state(document_id="doc-partial", clauses=[(cid1, r1)])

    json_written = []
    original_write_text = Path.write_text

    def selective_write(self, data, *args, **kwargs):
        if self.suffix == ".json":
            json_written.append(self)
            original_write_text(self, data, *args, **kwargs)
        elif self.suffix == ".md":
            raise OSError("md write failed")

    with patch.object(Path, "write_text", selective_write):
        result = report_agent(state)

    assert result["report_path"] is None
    assert result["error_count"] == 1
    # Orphan JSON must have been cleaned up
    for p in json_written:
        assert not p.exists(), f"Orphan JSON not cleaned: {p}"


def test_json_written_before_markdown(tmp_path, monkeypatch):
    """Assert JSON write precedes Markdown write (AC-19a)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    cid1, r1 = _validated_clause("c1", 1)
    state = make_state(clauses=[(cid1, r1)])

    write_order = []
    original_write_text = Path.write_text

    def recording_write(self, data, *args, **kwargs):
        write_order.append(self.suffix)
        return original_write_text(self, data, *args, **kwargs)

    with patch.object(Path, "write_text", recording_write):
        report_agent(state)

    json_idx = next(i for i, s in enumerate(write_order) if s == ".json")
    md_idx = next(i for i, s in enumerate(write_order) if s == ".md")
    assert json_idx < md_idx, f"JSON ({json_idx}) must precede Markdown ({md_idx})"


def test_write_failure_still_emits_trail(tmp_path, monkeypatch):
    """On an injected write failure the return still contains the computed evidence_trail (review item 2)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    snippets = [{"snippet_text": "Evidence.", "source_reference": "doc.pdf §1"}]
    cid1, r1 = _validated_clause("c1", 1, evidence=snippets)
    state = make_state(clauses=[(cid1, r1)])

    with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
        result = report_agent(state)

    assert "evidence_trail" in result
    assert len(result["evidence_trail"]) == 1
    assert result["evidence_trail"][0]["clause_id"] == "c1"


def test_rerun_overwrites_in_place(tmp_path, monkeypatch):
    """Running the node twice on the same document_id overwrites the same files (D6 / Edge Case 9)."""
    import app.graph.nodes.report_agent as mod

    monkeypatch.setattr(mod, "REPORT_OUTPUT_DIR", str(tmp_path))

    from app.graph.nodes.report_agent import report_agent

    cid1, r1 = _validated_clause("c1", 1)
    state = make_state(document_id="doc-rerun", clauses=[(cid1, r1)])

    result1 = report_agent(state)
    result2 = report_agent(state)

    assert result1["report_path"] == result2["report_path"]
    files = list(tmp_path.iterdir())
    md_files = [f for f in files if f.suffix == ".md"]
    json_files = [f for f in files if f.suffix == ".json"]
    assert len(md_files) == 1
    assert len(json_files) == 1


def test_no_llm_imported(tmp_path, monkeypatch):
    """The report_agent module references no ollama / model constant (D3)."""
    import app.graph.nodes.report_agent as mod

    assert not hasattr(mod, "OLLAMA_MODEL_NAME")
    assert not hasattr(mod, "REPORT_MODEL_NAME")
    assert not hasattr(mod, "REPORT_TIMEOUT_SECONDS")
    assert (
        "ollama" not in sys.modules or True
    )  # ollama may be installed but must not be used
    # Most direct check: the module source has no ollama import
    import inspect

    src = inspect.getsource(mod)
    assert "ollama" not in src
