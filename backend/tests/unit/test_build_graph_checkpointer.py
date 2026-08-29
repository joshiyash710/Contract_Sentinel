"""
Unit tests for build_graph checkpointer param + persistence module.

Written red (Task 5) — green after builder.py param + persistence.py.
"""


# ── AC-8: default graph structure is unchanged ─────────────────────────────────

def test_default_structure_unchanged():
    """build_graph() default must produce the same 7-node graph as 011 (spec AC-8)."""
    from app.graph.builder import build_graph

    g = build_graph()
    node_names = set(g.get_graph().nodes)
    expected = {
        "ingest_agent",
        "clause_splitter",
        "crag_retrieval",
        "self_rag_validation",
        "risk_score",
        "redline",
        "skip_redline",
        "report",
    }
    assert expected <= node_names


def test_default_compile_succeeds():
    """build_graph() with no args must compile without error (011 behavior)."""
    from app.graph.builder import build_graph

    g = build_graph()
    assert g is not None


# ── AC-9: checkpointer writes a thread ────────────────────────────────────────

def test_checkpointer_writes_thread(tmp_path):
    """A graph compiled with a saver writes a checkpoint entry for the thread (spec AC-9)."""
    from langgraph.graph import END, StateGraph
    from typing import TypedDict

    from app.runner.persistence import build_saver, has_checkpoint

    db = str(tmp_path / "ckpt.db")
    saver = build_saver(db)

    class FakeState(TypedDict):
        value: int

    def node_a(state):
        return {"value": state["value"] + 1}

    def node_b(state):
        return {"value": state["value"] + 1}

    graph = StateGraph(FakeState)
    graph.add_node("a", node_a)
    graph.add_node("b", node_b)
    graph.add_edge("a", "b")
    graph.add_edge("b", END)
    graph.set_entry_point("a")
    compiled = graph.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "t1"}}
    list(compiled.stream({"value": 0}, config=config))

    assert has_checkpoint(saver, "t1") is True
    assert has_checkpoint(saver, "absent") is False

    saver.conn.close()


def test_checkpointer_stays_local_sqlite_ignores_turso(tmp_path):
    """Feature 051 (AC-8): the checkpointer is always a local SqliteSaver, never routed to Turso.

    The spike showed SqliteSaver is libsql-incompatible, so the checkpointer stays local/ephemeral.
    """
    import pathlib

    from langgraph.checkpoint.sqlite import SqliteSaver

    from app.runner.persistence import build_saver

    saver = build_saver(str(tmp_path / "ckpt.db"))
    assert isinstance(saver, SqliteSaver)

    # persistence.py must not consult the Turso config or the store factory.
    src = pathlib.Path("app/runner/persistence.py").read_text(encoding="utf-8")
    assert "TURSO" not in src
    assert "db_backend" not in src
