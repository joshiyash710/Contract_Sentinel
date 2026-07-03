"""
Unit tests for app.graph.nodes.retrievers.web_retriever.web_search.

Mocks DDGS — no network calls.
Run: python -m pytest tests/unit/test_web_retriever.py -v
"""

import concurrent.futures
from unittest.mock import MagicMock, patch


from app.graph.nodes.retrievers.web_retriever import web_search
import app.graph.nodes.retrievers.web_retriever as web_retriever_mod


def _make_ddgs_results(n: int) -> list:
    """Build n fake DDG result dicts."""
    return [
        {
            "title": f"Result {i}",
            "href": f"https://example.com/{i}",
            "body": f"Body text {i}",
        }
        for i in range(n)
    ]


def test_web_maps_results_to_snippet_shape():
    """DDG {title,href,body} → snippets with exactly snippet_text(=body) + source_reference(=href).
    Also: a result missing body or href is skipped (protects AC-6)."""
    good_result = {"title": "t", "href": "https://good.example/", "body": "Good body"}
    bad_no_body = {"title": "t2", "href": "https://bad.example/", "body": ""}
    bad_no_href = {"title": "t3", "href": "", "body": "Some text"}

    mock_ddgs = MagicMock()
    mock_ddgs.return_value.__enter__ = MagicMock(return_value=mock_ddgs.return_value)
    mock_ddgs.return_value.__exit__ = MagicMock(return_value=False)
    mock_ddgs.return_value.text.return_value = [good_result, bad_no_body, bad_no_href]

    with patch.object(web_retriever_mod, "DDGS", mock_ddgs):
        result = web_search("liability clause", max_results=5, timeout_seconds=10)

    assert len(result.snippets) == 1
    s = result.snippets[0]
    assert set(s.keys()) == {"snippet_text", "source_reference"}
    assert s["snippet_text"] == "Good body"
    assert s["source_reference"] == "https://good.example/"


def test_web_respects_max_results():
    """No more than max_results snippets; .text() called with max_results=."""
    mock_ddgs = MagicMock()
    mock_ddgs.return_value.__enter__ = MagicMock(return_value=mock_ddgs.return_value)
    mock_ddgs.return_value.__exit__ = MagicMock(return_value=False)
    mock_ddgs.return_value.text.return_value = _make_ddgs_results(10)

    with patch.object(web_retriever_mod, "DDGS", mock_ddgs):
        result = web_search("query", max_results=3, timeout_seconds=10)

    assert len(result.snippets) <= 3
    mock_ddgs.return_value.text.assert_called_once()
    call_kwargs = mock_ddgs.return_value.text.call_args
    assert call_kwargs.kwargs.get("max_results") == 3 or (
        len(call_kwargs.args) > 1 and call_kwargs.args[1] == 3
    )


def test_web_top_score_is_none():
    """Web path returns top_score=None (no cosine on web path)."""
    mock_ddgs = MagicMock()
    mock_ddgs.return_value.__enter__ = MagicMock(return_value=mock_ddgs.return_value)
    mock_ddgs.return_value.__exit__ = MagicMock(return_value=False)
    mock_ddgs.return_value.text.return_value = _make_ddgs_results(2)

    with patch.object(web_retriever_mod, "DDGS", mock_ddgs):
        result = web_search("query", max_results=5, timeout_seconds=10)

    assert result.top_score is None


def test_web_zero_results_returns_empty():
    """Empty results → RetrievalResult([], None) (spec §4.7)."""
    mock_ddgs = MagicMock()
    mock_ddgs.return_value.__enter__ = MagicMock(return_value=mock_ddgs.return_value)
    mock_ddgs.return_value.__exit__ = MagicMock(return_value=False)
    mock_ddgs.return_value.text.return_value = []

    with patch.object(web_retriever_mod, "DDGS", mock_ddgs):
        result = web_search("query", max_results=5, timeout_seconds=10)

    assert result.snippets == []
    assert result.top_score is None


def test_web_raises_returns_empty(caplog):
    """DDG .text() raises → ([], None), no crash (AC-13)."""
    mock_ddgs = MagicMock()
    mock_ddgs.return_value.__enter__ = MagicMock(return_value=mock_ddgs.return_value)
    mock_ddgs.return_value.__exit__ = MagicMock(return_value=False)
    mock_ddgs.return_value.text.side_effect = Exception("rate limited")

    with patch.object(web_retriever_mod, "DDGS", mock_ddgs):
        with caplog.at_level("WARNING"):
            result = web_search("query", max_results=5, timeout_seconds=10)

    assert result.snippets == []
    assert result.top_score is None


def test_web_timeout_returns_empty(caplog):
    """Simulated timeout → ([], None) (spec §4.8)."""
    mock_ddgs = MagicMock()
    mock_ddgs.return_value.__enter__ = MagicMock(return_value=mock_ddgs.return_value)
    mock_ddgs.return_value.__exit__ = MagicMock(return_value=False)
    mock_ddgs.return_value.text.side_effect = concurrent.futures.TimeoutError(
        "timed out"
    )

    with patch.object(web_retriever_mod, "DDGS", mock_ddgs):
        with caplog.at_level("WARNING"):
            result = web_search("query", max_results=5, timeout_seconds=10)

    assert result.snippets == []
    assert result.top_score is None


def test_web_import_fallback():
    """DDGS=None (import failure) → ([], None), not an import crash at call time."""
    with patch.object(web_retriever_mod, "DDGS", None):
        result = web_search("query", max_results=5, timeout_seconds=10)

    assert result.snippets == []
    assert result.top_score is None
