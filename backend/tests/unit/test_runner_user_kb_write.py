"""Feature 061 — runner write-side: post-run append of VALIDATED findings. AC-1/2/3/6/9/10.

Exercises the factored helpers _validated_finding_items and _maybe_write_user_kb directly, plus a mocked-
graph run_pipeline to confirm user_id is forwarded on the (checkpointed) config channel and withheld on the
no-checkpointer path. No Ollama/graph: build_graph + deliver_report_sync are mocked.
"""

import pytest

import app.runner.core as core
import app.rag.user_kb as user_kb
from app.graph.state import ValidationStatus, RiskLevel


def _final_state():
    return {
        "original_filename": "lease.pdf",
        "document_id": "d1",
        "clauses": {
            "c1": {"text": "risky A", "final_status": ValidationStatus.VALIDATED, "risk_level": RiskLevel.HIGH},
            "c2": {"text": "boilerplate", "final_status": ValidationStatus.DISCARDED, "risk_level": None},
            # checkpoint round-trip: str values instead of enums
            "c3": {"text": "risky B", "final_status": "validated", "risk_level": "medium"},
        },
    }


def test_validated_finding_items_selects_validated_only():
    # AC-3: only VALIDATED clauses become items (str round-trip counts); source_reference carries file + risk.
    items = core._validated_finding_items(_final_state())
    assert {i["text"] for i in items} == {"risky A", "risky B"}
    refs = " ".join(i["source_reference"] for i in items)
    assert "lease.pdf" in refs
    assert "high" in refs and "medium" in refs  # risk normalized via _enum_value (enum + str)


def test_maybe_write_calls_append_when_enabled(monkeypatch):
    # AC-2: flag on + user_id + validated items → append_clauses invoked with those items.
    calls = []
    monkeypatch.setattr(core._config, "CRAG_USER_KB_ENABLED", True)
    monkeypatch.setattr(user_kb, "append_clauses", lambda uid, items: calls.append((uid, list(items))))
    core._maybe_write_user_kb(_final_state(), "u1")
    assert len(calls) == 1
    uid, items = calls[0]
    assert uid == "u1" and len(items) == 2


@pytest.mark.parametrize("flag,user_id,state_key", [
    (False, "u1", "full"),   # AC-1: flag off
    (True, None, "full"),    # AC-10: no user_id
    (True, "u1", "none"),    # AC-10: zero validated findings
])
def test_maybe_write_skips(monkeypatch, flag, user_id, state_key):
    calls = []
    monkeypatch.setattr(core._config, "CRAG_USER_KB_ENABLED", flag)
    monkeypatch.setattr(user_kb, "append_clauses", lambda uid, items: calls.append(uid))
    fs = _final_state() if state_key == "full" else {"clauses": {}}
    core._maybe_write_user_kb(fs, user_id)
    assert calls == []


def test_maybe_write_swallows_errors(monkeypatch):
    # AC-9: an append failure never propagates out of the best-effort write.
    monkeypatch.setattr(core._config, "CRAG_USER_KB_ENABLED", True)

    def _boom(uid, items):
        raise RuntimeError("faiss/disk error")

    monkeypatch.setattr(user_kb, "append_clauses", _boom)
    core._maybe_write_user_kb(_final_state(), "u1")  # must not raise


class _FakeGraph:
    def __init__(self):
        self.captured_config = "UNSET"

    def stream(self, stream_input, stream_mode=None, config=None):
        self.captured_config = config
        return iter([{"current_node": "report_agent", "clauses": {}}])


def _mock_graph(monkeypatch):
    fake = _FakeGraph()
    monkeypatch.setattr(core, "build_graph", lambda checkpointer=None: fake)
    monkeypatch.setattr(core, "deliver_report_sync", lambda *a, **k: {})
    return fake


def test_run_pipeline_forwards_user_id_when_checkpointed(monkeypatch):
    # AC-6 (forward side): user_id rides config.configurable on the authenticated/checkpointed path.
    fake = _mock_graph(monkeypatch)
    core.run_pipeline("doc.pdf", user_id="u1", checkpointer=object(), thread_id="t1")
    assert fake.captured_config["configurable"]["user_id"] == "u1"


def test_run_pipeline_no_checkpointer_leaves_config_none(monkeypatch):
    # The CLI/no-checkpointer path stays config=None (byte-identical streaming) → CRAG resolves user_id None.
    fake = _mock_graph(monkeypatch)
    core.run_pipeline("doc.pdf", user_id="u1", checkpointer=None)
    assert fake.captured_config is None
