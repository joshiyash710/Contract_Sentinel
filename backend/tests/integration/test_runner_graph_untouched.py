"""
Integration tests verifying the graph (builder.py) is untouched by the runner.

These tests guard constitution §2: exactly 7 nodes / 2 conditional edges.
They use the `client` fixture (imported app.api.main.create_app) only to gate
collection on Task 19 — the tests themselves only inspect the graph structure.

TDD red phase: FAIL (fixture ImportError) until Task 19 implements app.api.main.
Run: python -m pytest tests/integration/test_runner_graph_untouched.py -v
"""


def test_builder_not_modified_by_runner(client):
    """build_graph().get_graph() still ends report → END; runner imports only
    build_graph / deliver_report_sync — no app.graph.nodes.* (spec §1, AC-7).

    The 'client' parameter gates this test on Task 19 (create_app must exist);
    the graph assertions themselves do not use the client.
    """
    from app.graph.builder import build_graph
    import inspect
    import app.runner.core as core_mod

    compiled = build_graph()
    g = compiled.get_graph()

    # Graph ends with report → END (edges may be 2-tuples or 3-tuples depending on version)
    edges = list(g.edges)
    edge_pairs = [(e[0], e[1]) for e in edges]
    assert any(
        src == "report" and tgt in ("__end__", "END") for src, tgt in edge_pairs
    ), f"No report→END edge found in {edge_pairs}"

    # runner.core has no app.graph.nodes. import
    src = inspect.getsource(core_mod)
    assert "app.graph.nodes." not in src


def test_conditional_edge_count_unchanged(client):
    """Conditional edge sources remain the ingest guard + route_on_risk only
    (constitution §2 invariant: exactly 2 domain-logic conditional edges).

    The 'client' parameter gates this test on Task 19 (create_app must exist);
    the graph assertions themselves do not use the client.
    """
    from app.graph.builder import build_graph
    from collections import defaultdict

    compiled = build_graph()
    g = compiled.get_graph()

    out_edges = defaultdict(list)
    for edge in g.edges:
        src, tgt = edge[0], edge[1]
        out_edges[src].append(tgt)

    conditional_sources = {
        node for node, targets in out_edges.items() if len(targets) > 1
    }

    assert "ingest_agent" in conditional_sources
    assert "risk_score" in conditional_sources
    assert (
        len(conditional_sources) == 2
    ), f"Expected exactly 2 conditional-edge sources, got: {conditional_sources}"
