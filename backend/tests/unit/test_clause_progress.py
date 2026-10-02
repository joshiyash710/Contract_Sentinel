"""
Feature 059 — live per-clause CRAG progress (polled). Backend unit tests.

Covers: CRAG per-clause emit + guarded writer acquisition (AC-1/2/3/7/8), runner-core dual-mode
forwarding (AC-4/3), JobRecord clause-progress + no-persist (AC-5/9), and JobStatus back-compat (AC-6).

Run: python -m pytest tests/unit/test_clause_progress.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.graph.nodes.crag_retrieval_agent as crag_mod
from app.graph.nodes.crag_retrieval_agent import crag_retrieval_agent
from app.graph.nodes.retrievers import RetrievalResult
from app.graph.state import RetrievalPath


# ── CRAG emit helpers (mirror test_crag_retrieval_agent.py) ──────────────────────
def _clause(text="A contract clause.", position=1, clause_type=None):
    return {"text": text, "position": position, "section_number": None, "clause_type": clause_type}


def _kb_result(top_score, n=2):
    return RetrievalResult(
        snippets=[{"snippet_text": f"kb {i}", "source_reference": f"kb://{i}"} for i in range(n)],
        top_score=top_score,
    )


def _web_result(n=2):
    return RetrievalResult(
        snippets=[{"snippet_text": f"web {i}", "source_reference": f"https://w/{i}"} for i in range(n)],
        top_score=None,
    )


@pytest.fixture(autouse=True)
def _reset_kb_cache():
    import app.graph.nodes.retrievers.kb_retriever as kb_mod

    kb_mod._KB_CACHE = None
    yield
    kb_mod._KB_CACHE = None


def _patch_crag(monkeypatch, *, top_scores):
    """Patch embed/kb/web so each clause gets the next top_score (>=0.73 → local_kb, else web)."""
    monkeypatch.setattr(crag_mod, "load_kb", lambda: MagicMock())
    monkeypatch.setattr(crag_mod, "embed_query", lambda *a, **k: [0.1] * 8)
    scores = iter(top_scores)
    monkeypatch.setattr(crag_mod, "search_kb", lambda kb, vec, k: _kb_result(next(scores)))
    monkeypatch.setattr(crag_mod, "web_search", lambda *a, **k: _web_result())


def test_ac1_ac7_emits_one_payload_per_clause_with_parity(monkeypatch):
    captured = []
    monkeypatch.setattr(crag_mod, "CRAG_LIVE_CLAUSE_PROGRESS_ENABLED", True)
    monkeypatch.setattr(crag_mod, "_clause_writer", lambda: captured.append)
    _patch_crag(monkeypatch, top_scores=[0.90, 0.40])  # clause1 → local_kb, clause2 → web_fallback

    state = {
        "document_id": "d1",
        "ingest_error": None,
        "clauses": {
            "c1": _clause("Clause one.", 1, clause_type="liability"),
            "c2": _clause("Clause two.", 2),
        },
    }
    result = crag_retrieval_agent(state)

    assert len(captured) == 2
    assert [p["clause_index"] for p in captured] == [1, 2]
    assert all(p["clause_total"] == 2 and p["kind"] == "clause" for p in captured)
    assert captured[0]["retrieval_path"] == "local_kb"
    assert captured[0]["clause_type"] == "liability"  # enum/str → value
    assert captured[1]["retrieval_path"] == "web_fallback"
    # AC-7: streamed retrieval_path == the path_taken each clause ends up with
    for cid, payload in zip(("c1", "c2"), captured):
        path_taken = result["clauses"][cid]["path_taken"]
        assert payload["retrieval_path"] == (path_taken.value if path_taken is not None else None)


def test_ac8_empty_text_clause_emits_none_path(monkeypatch):
    captured = []
    monkeypatch.setattr(crag_mod, "CRAG_LIVE_CLAUSE_PROGRESS_ENABLED", True)
    monkeypatch.setattr(crag_mod, "_clause_writer", lambda: captured.append)
    _patch_crag(monkeypatch, top_scores=[0.90])  # only the non-empty clause reaches search_kb

    state = {
        "document_id": "d1",
        "ingest_error": None,
        "clauses": {"c1": _clause("", 1), "c2": _clause("Real clause.", 2)},
    }
    crag_retrieval_agent(state)

    assert [p["clause_index"] for p in captured] == [1, 2]  # no index skipped
    assert captured[0]["retrieval_path"] is None and captured[0]["confidence"] is None  # empty clause


def test_ac2_direct_call_with_flag_on_does_not_raise(monkeypatch):
    """Real _clause_writer: a direct node call has no runnable context → get_stream_writer raises at
    acquisition → guarded → None → no emit, no error (byte-identical partial dict)."""
    monkeypatch.setattr(crag_mod, "CRAG_LIVE_CLAUSE_PROGRESS_ENABLED", True)
    _patch_crag(monkeypatch, top_scores=[0.90])
    state = {"document_id": "d1", "ingest_error": None, "clauses": {"c1": _clause("Clause.", 1)}}

    result = crag_retrieval_agent(state)  # must not raise
    assert "clauses" in result and result["current_node"] == "crag_retrieval"


def test_ac3_flag_off_no_writer(monkeypatch):
    monkeypatch.setattr(crag_mod, "CRAG_LIVE_CLAUSE_PROGRESS_ENABLED", False)
    assert crag_mod._clause_writer() is None  # off ⇒ no writer ⇒ node emits nothing


# ── Runner-core dual-mode forwarding (AC-4 / AC-3) ───────────────────────────────
def _make_dual_graph(items):
    """items: list of ("values", state) / ("custom", payload). Yields tuples for a list stream_mode,
    plain states for single-mode "values"."""
    fake = MagicMock()

    def fake_stream(initial, stream_mode=None, config=None):
        if isinstance(stream_mode, (list, tuple)):
            yield from items
        else:
            yield from [chunk for mode, chunk in items if mode == "values"]

    fake.stream = fake_stream
    return fake


def _vstate(node):
    return {"current_node": node, "node_timings": {node: 0.1}}


def test_ac4_core_forwards_custom_chunks_without_touching_dedup(monkeypatch):
    import app.runner.core as core_mod

    items = [
        ("values", _vstate("ingest_agent")),
        ("values", _vstate("crag_retrieval")),
        ("custom", {"kind": "clause", "clause_index": 1, "clause_total": 2, "retrieval_path": "local_kb"}),
        ("custom", {"kind": "clause", "clause_index": 2, "clause_total": 2, "retrieval_path": "web_fallback"}),
        ("values", _vstate("report")),
    ]
    monkeypatch.setattr(core_mod, "build_graph", lambda checkpointer=None: _make_dual_graph(items))
    monkeypatch.setattr(core_mod, "deliver_report_sync", lambda *a, **k: {"mcp_delivery_status": {}})

    nodes, clauses = [], []
    core_mod.run_pipeline(
        "c.pdf",
        on_progress=lambda p: nodes.append(p.node),
        on_clause=lambda payload: clauses.append(payload),
    )

    assert clauses == [items[2][1], items[3][1]]            # both custom payloads forwarded (AC-4)
    assert nodes == ["ingest_agent", "crag_retrieval", "report"]  # node progress unaffected by custom


def test_ac3_core_single_mode_when_no_on_clause(monkeypatch):
    import app.runner.core as core_mod

    items = [("values", _vstate("ingest_agent")), ("values", _vstate("report"))]
    captured_mode = {}

    fake = MagicMock()

    def fake_stream(initial, stream_mode=None, config=None):
        captured_mode["mode"] = stream_mode
        yield from [chunk for _, chunk in items]

    fake.stream = fake_stream
    monkeypatch.setattr(core_mod, "build_graph", lambda checkpointer=None: fake)
    monkeypatch.setattr(core_mod, "deliver_report_sync", lambda *a, **k: {"mcp_delivery_status": {}})

    nodes = []
    core_mod.run_pipeline("c.pdf", on_progress=lambda p: nodes.append(p.node))  # no on_clause
    assert captured_mode["mode"] == "values"  # single-mode, byte-identical
    assert nodes == ["ingest_agent", "report"]


# ── JobRecord clause-progress (AC-5 / AC-9 / no-persist) ─────────────────────────
def _record(store=None):
    from app.runner.registry import JobRecord

    rec = JobRecord(job_id="j1", document_path="c.pdf", submitted_at="t", buffer=MagicMock())
    rec._store = store
    return rec


def _payload(i, n, path, conf=0.5, ctype=None):
    return {
        "kind": "clause", "clause_index": i, "clause_total": n,
        "clause_type": ctype, "retrieval_path": path, "confidence": conf,
    }


def test_ac5_update_and_to_status():
    rec = _record()
    assert rec.to_status().clause_progress is None  # none until first update
    rec.update_clause_progress(_payload(1, 3, "local_kb", 0.82))
    rec.update_clause_progress(_payload(2, 3, "web_fallback", 0.61))
    rec.update_clause_progress(_payload(3, 3, "web_fallback", None))

    cp = rec.to_status().clause_progress
    assert cp is not None
    assert cp.clauses_done == 3 and cp.clauses_total == 3 and cp.web_fallbacks == 2
    assert len(cp.recent) == 3
    assert cp.recent[0].retrieval_path == "local_kb" and cp.recent[0].confidence == 0.82


def test_ac9_recent_ring_buffer_capped(monkeypatch):
    import app.config as cfg

    monkeypatch.setattr(cfg, "CRAG_PROGRESS_RECENT_MAX", 4)
    rec = _record()
    for i in range(1, 11):  # 10 clauses, cap 4
        rec.update_clause_progress(_payload(i, 10, "local_kb"))
    cp = rec.to_status().clause_progress
    assert cp.clauses_done == 10 and cp.clauses_total == 10  # counters count all
    assert len(cp.recent) == 4  # ring buffer capped
    assert [l.clause_index for l in cp.recent] == [7, 8, 9, 10]  # newest kept


def test_no_persist_jobrow_has_no_clause_fields():
    rec = _record()
    rec.update_clause_progress(_payload(1, 1, "local_kb"))
    row = rec._to_row()
    assert not hasattr(row, "clause_progress")
    assert not hasattr(row, "clauses_done")  # progress is in-memory only


# ── JobStatus back-compat (AC-6) ─────────────────────────────────────────────────
def test_ac6_jobstatus_backcompat():
    from app.runner.models import JobStatus

    js = JobStatus(job_id="j", status="running", submitted_at="t")
    assert js.clause_progress is None  # default absent
    # pre-059 dict (no clause_progress key) deserializes fine
    js2 = JobStatus(**{"job_id": "j", "status": "completed", "submitted_at": "t"})
    assert js2.clause_progress is None


# ── Worker gating + apply (AC-5 / AC-3) ──────────────────────────────────────────
def _worker_setup(job_id="j1"):
    import asyncio
    from app.runner.registry import JobRegistry, JobRecord
    from app.runner.events import JobEventBuffer
    from app.runner.worker import PipelineWorker

    loop = asyncio.new_event_loop()
    reg = JobRegistry(store=None, saver=None, loop=None, max_jobs=50)
    rec = JobRecord(job_id=job_id, document_path="c.pdf", submitted_at="t", buffer=JobEventBuffer(loop))
    reg.add(rec)
    return PipelineWorker(reg), reg, rec


def _stub_run_pipeline(captured, *, emit=None):
    def stub(*args, **kwargs):
        captured["on_clause"] = kwargs.get("on_clause")
        if emit is not None and kwargs.get("on_clause") is not None:
            for payload in emit:
                kwargs["on_clause"](payload)
        return SimpleNamespace(
            final_state={}, report_path="data/reports/doc.md",
            mcp_delivery_status={}, ingest_error=None,
        )

    return stub


def test_ac5_worker_wires_on_clause_and_record_updates(monkeypatch):
    import app.config as cfg
    import app.runner.worker as worker_mod

    monkeypatch.setattr(cfg, "CRAG_LIVE_CLAUSE_PROGRESS_ENABLED", True)
    worker, reg, rec = _worker_setup()
    captured = {}
    monkeypatch.setattr(
        worker_mod, "run_pipeline",
        _stub_run_pipeline(captured, emit=[_payload(1, 2, "local_kb", 0.8), _payload(2, 2, "web_fallback", 0.6)]),
    )

    worker._run_one(("j1", False))

    assert captured["on_clause"] is not None  # flag on → on_clause passed
    cp = rec.to_status().clause_progress    # the stub-driven emits reached the record
    assert cp is not None and cp.clauses_done == 2 and cp.web_fallbacks == 1


def test_ac3_worker_passes_no_on_clause_when_flag_off(monkeypatch):
    import app.config as cfg
    import app.runner.worker as worker_mod

    monkeypatch.setattr(cfg, "CRAG_LIVE_CLAUSE_PROGRESS_ENABLED", False)
    worker, reg, rec = _worker_setup()
    captured = {}
    monkeypatch.setattr(worker_mod, "run_pipeline", _stub_run_pipeline(captured))

    worker._run_one(("j1", False))

    assert captured["on_clause"] is None              # flag off → no on_clause
    assert rec.to_status().clause_progress is None
