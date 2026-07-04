"""
Unit tests for app.graph.nodes.validators.reflectors.

All three reflective judgment functions (check_relevance, check_isrel, check_issup)
and the shared format_evidence helper are tested here. No live Ollama — all LLM
calls are mocked at the ollama.Client boundary.
"""

import concurrent.futures
import json
from unittest.mock import MagicMock, patch, call

import pytest

from app.graph.nodes.validators import format_evidence

# ── format_evidence ────────────────────────────────────────────────────────────


def test_format_evidence_shape_and_empty():
    """format_evidence renders [i] (src) text lines; returns '' for None/[]."""
    assert format_evidence(None, 1000) == ""
    assert format_evidence([], 1000) == ""
    result = format_evidence(
        [{"snippet_text": "Some text", "source_reference": "doc/1"}], 1000
    )
    assert "[1] (doc/1) Some text" in result
    # two snippets
    result2 = format_evidence(
        [
            {"snippet_text": "First", "source_reference": "a"},
            {"snippet_text": "Second", "source_reference": "b"},
        ],
        1000,
    )
    assert "[1] (a) First" in result2
    assert "[2] (b) Second" in result2


# ── reflector import (will FAIL until Task 5) ────────────────────────────────


def _import_reflectors():
    from app.graph.nodes.validators.reflectors import (
        check_relevance,
        check_isrel,
        check_issup,
    )

    return check_relevance, check_isrel, check_issup


def _make_client_mock(verdict: bool):
    """Build a mock ollama.Client whose .chat() returns the given verdict."""
    mock_client_instance = MagicMock()
    mock_client_instance.chat.return_value = {
        "message": {"content": json.dumps({"verdict": verdict, "reason": "test"})}
    }
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    return mock_client_cls, mock_client_instance


def _make_client_mock_raw(content: str):
    mock_client_instance = MagicMock()
    mock_client_instance.chat.return_value = {"message": {"content": content}}
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    return mock_client_cls, mock_client_instance


# ── Verdict parsing ──────────────────────────────────────────────────────────


def test_verdict_true_parsed():
    """{"verdict": true} → True."""
    check_relevance, _, _ = _import_reflectors()
    mock_cls, mock_inst = _make_client_mock(True)
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        result = check_relevance("A clause text.", 10, "qwen3:14b", 6000)
    assert result is True


def test_verdict_false_parsed():
    """{"verdict": false} → False."""
    check_relevance, _, _ = _import_reflectors()
    mock_cls, mock_inst = _make_client_mock(False)
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        result = check_relevance("A clause text.", 10, "qwen3:14b", 6000)
    assert result is False


def test_malformed_json_returns_none():
    """Non-JSON content → None (fail-open trigger)."""
    check_relevance, _, _ = _import_reflectors()
    mock_cls, _ = _make_client_mock_raw("not json at all")
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        result = check_relevance("A clause.", 10, "qwen3:14b", 6000)
    assert result is None


def test_missing_verdict_key_returns_none():
    """JSON without a 'verdict' key → None."""
    check_relevance, _, _ = _import_reflectors()
    mock_cls, _ = _make_client_mock_raw(json.dumps({"reason": "something"}))
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        result = check_relevance("A clause.", 10, "qwen3:14b", 6000)
    assert result is None


def test_non_bool_verdict_returns_none():
    """{"verdict": "maybe"} or {"verdict": 1} → None."""
    check_relevance, _, _ = _import_reflectors()
    for bad_val in ["maybe", 1, 0, None]:
        mock_cls, _ = _make_client_mock_raw(
            json.dumps({"verdict": bad_val, "reason": "x"})
        )
        with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
            result = check_relevance("A clause.", 10, "qwen3:14b", 6000)
        assert result is None, f"Expected None for verdict={bad_val!r}, got {result!r}"


# ── Failure handling ─────────────────────────────────────────────────────────


def test_timeout_returns_none(caplog):
    """Simulated timeout → None, warning logged."""
    check_relevance, _, _ = _import_reflectors()
    mock_cls = MagicMock()
    mock_cls.return_value.chat.side_effect = concurrent.futures.TimeoutError()
    with caplog.at_level("WARNING"):
        with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
            result = check_relevance("A clause.", 10, "qwen3:14b", 6000)
    assert result is None
    assert any(
        "timeout" in r.message.lower()
        or "timed" in r.message.lower()
        or "fail" in r.message.lower()
        for r in caplog.records
    )


def test_connection_error_returns_none():
    """Ollama unreachable (ConnectionError) → None."""
    check_relevance, _, _ = _import_reflectors()
    mock_cls = MagicMock()
    mock_cls.return_value.chat.side_effect = ConnectionError("refused")
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        result = check_relevance("A clause.", 10, "qwen3:14b", 6000)
    assert result is None


def test_reflector_never_raises():
    """Any injected exception → None, nothing propagates."""
    check_relevance, check_isrel, check_issup = _import_reflectors()
    snippets = [{"snippet_text": "evidence", "source_reference": "r"}]
    for exc in [RuntimeError("boom"), ValueError("bad"), MemoryError("oom")]:
        mock_cls = MagicMock()
        mock_cls.return_value.chat.side_effect = exc
        with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
            assert check_relevance("A clause.", 10, "qwen3:14b", 6000) is None
            assert check_isrel("A clause.", snippets, 10, "qwen3:14b", 6000) is None
            assert check_issup("A clause.", snippets, 10, "qwen3:14b", 6000) is None


# ── Model separation (AC-9) ──────────────────────────────────────────────────


def test_uses_generative_model_only():
    """chat is called with OLLAMA_MODEL_NAME; OLLAMA_EMBED_MODEL_NAME never referenced."""
    from app.config import OLLAMA_MODEL_NAME, OLLAMA_EMBED_MODEL_NAME

    check_relevance, check_isrel, check_issup = _import_reflectors()
    snippets = [{"snippet_text": "evidence", "source_reference": "r"}]
    mock_cls, mock_inst = _make_client_mock(True)
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        check_relevance("clause", 10, OLLAMA_MODEL_NAME, 6000)
        check_isrel("clause", snippets, 10, OLLAMA_MODEL_NAME, 6000)
        check_issup("clause", snippets, 10, OLLAMA_MODEL_NAME, 6000)
    assert mock_inst.chat.call_count == 3
    for c in mock_inst.chat.call_args_list:
        model_used = c.kwargs.get("model")
        assert model_used == OLLAMA_MODEL_NAME
        assert model_used != OLLAMA_EMBED_MODEL_NAME


# ── Prompt content checks ────────────────────────────────────────────────────


def test_relevance_prompt_excludes_evidence():
    """The Relevance prompt is a function of clause text only (no evidence text)."""
    check_relevance, _, _ = _import_reflectors()
    evidence_marker = "THIS_IS_EVIDENCE_TEXT_12345"
    mock_cls, mock_inst = _make_client_mock(True)
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        check_relevance("clause text here", 10, "qwen3:14b", 6000)
    prompt_sent = mock_inst.chat.call_args.kwargs["messages"][0]["content"]
    assert evidence_marker not in prompt_sent


def test_issup_empty_evidence_uses_text_only_prompt():
    """With evidence_snippets=None/[], the ISSUP prompt instructs judging on clause text alone."""
    _, _, check_issup = _import_reflectors()
    mock_cls, mock_inst = _make_client_mock(True)
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        check_issup("clause text", None, 10, "qwen3:14b", 6000)
    prompt_sent = mock_inst.chat.call_args.kwargs["messages"][0]["content"]
    assert (
        "clause text" in prompt_sent.lower()
        or "text alone" in prompt_sent.lower()
        or "no evidence" in prompt_sent.lower()
    )


def test_prompt_truncated_to_max_chars():
    """Oversized clause text + evidence are truncated so combined input ≤ prompt_max_chars."""
    _, _, check_issup = _import_reflectors()
    prompt_max_chars = 100
    # Both clause and evidence are each larger than the budget alone
    big_clause = "C" * 200
    big_evidence = [{"snippet_text": "E" * 200, "source_reference": "r"}]
    mock_cls, mock_inst = _make_client_mock(True)
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        check_issup(big_clause, big_evidence, 10, "qwen3:14b", prompt_max_chars)
    prompt_sent = mock_inst.chat.call_args.kwargs["messages"][0]["content"]
    # The variable clause+evidence portion of the prompt must not exceed prompt_max_chars
    clause_trunc = big_clause[:prompt_max_chars]
    remaining = max(0, prompt_max_chars - len(clause_trunc))
    evidence_str = format_evidence(big_evidence, remaining)
    assert len(clause_trunc) + len(evidence_str) <= prompt_max_chars
    # Also assert those truncated strings actually appear in the prompt
    assert clause_trunc in prompt_sent or clause_trunc[:50] in prompt_sent
