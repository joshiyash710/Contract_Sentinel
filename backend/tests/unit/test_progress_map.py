"""
Unit tests for app.runner.progress — node-name → stage-index mapping.

TDD red phase: all tests must FAIL (ImportError) until Task 7 implements the module.
Run: python -m pytest tests/unit/test_progress_map.py -v
"""


def test_redline_and_skip_share_index_6():
    """Both branching paths map to the same stage index."""
    from app.runner.progress import NODE_INDEX

    assert NODE_INDEX["redline"] == NODE_INDEX["skip_redline"] == 6


def test_indices_cover_seven_stages():
    """Distinct index values are exactly {1,2,3,4,5,6,7}; TOTAL_STAGES == 7."""
    from app.runner.progress import NODE_INDEX, TOTAL_STAGES

    assert set(NODE_INDEX.values()) == {1, 2, 3, 4, 5, 6, 7}
    assert TOTAL_STAGES == 7


def test_node_names_match_builder():
    """Every NODE_INDEX key is a node name build_graph() actually registers."""
    from app.runner.progress import NODE_INDEX
    from app.graph.builder import build_graph

    graph_nodes = set(build_graph().get_graph().nodes.keys())
    for name in NODE_INDEX:
        assert name in graph_nodes, f"{name!r} not in graph nodes: {graph_nodes}"


def test_unknown_node_returns_none():
    """Defensive: unknown node name returns None, never raises."""
    from app.runner.progress import node_index

    assert node_index("nope") is None
    assert node_index("") is None
