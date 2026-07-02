"""
Unit tests for app.graph.nodes.splitters.llm_refiner.refine_with_llm().

All tests mock ollama.chat — no real Ollama instance required.
Written BEFORE the implementation (TDD red phase).

Run: python -m pytest tests/unit/test_llm_refiner.py -v
Expected before Task 7: FAIL (ImportError)
Expected after Task 7:  all 13 PASS
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from app.graph.nodes.splitters import ClauseBoundary
from app.graph.nodes.splitters.llm_refiner import refine_with_llm

# ── Fixtures ───────────────────────────────────────────────────────────────────


def make_boundary(clause_id, text, position, section_number=None, clause_type=None):
    return ClauseBoundary(
        clause_id=clause_id,
        text=text,
        position=position,
        section_number=section_number,
        clause_type=clause_type,
    )


@pytest.fixture
def two_clauses():
    return [
        make_boundary(
            "clause_001", "Definitions of all terms in this agreement.", 1, "1"
        ),
        make_boundary(
            "clause_002", "Payment is due within 30 days of invoice.", 2, "2"
        ),
    ]


def _mock_response(clauses_list: list) -> MagicMock:
    """Build a mock ollama.chat return value with the given clauses."""
    content = json.dumps({"clauses": clauses_list})
    mock = MagicMock()
    mock.__getitem__ = lambda self, key: {
        "message": MagicMock(
            **{"__getitem__": lambda s, k: content if k == "content" else None}
        )
    }[key]
    # More reliable: use a real dict structure
    return {"message": {"content": content}}


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_refine_merges_fragments(two_clauses):
    """LLM response merging two regex fragments into one clause is parsed correctly."""
    merged_response = {
        "clauses": [
            {
                "text": "Definitions of all terms. Payment is due within 30 days.",
                "section_number": "1",
                "clause_type": "definitions",
            }
        ]
    }
    with patch(
        "ollama.chat",
        return_value={"message": {"content": json.dumps(merged_response)}},
    ):
        result = refine_with_llm(
            two_clauses, timeout_seconds=10, model_name="qwen3:14b"
        )
    assert len(result) == 1
    assert result[0].clause_id == "clause_001"
    assert result[0].position == 1


def test_refine_splits_runon(two_clauses):
    """LLM response splitting one clause into two is parsed correctly."""
    split_response = {
        "clauses": [
            {
                "text": "First part of definitions.",
                "section_number": "1",
                "clause_type": "definitions",
            },
            {
                "text": "Second part of definitions.",
                "section_number": "1.1",
                "clause_type": "definitions",
            },
            {
                "text": "Payment is due within 30 days.",
                "section_number": "2",
                "clause_type": "payment",
            },
        ]
    }
    with patch(
        "ollama.chat", return_value={"message": {"content": json.dumps(split_response)}}
    ):
        result = refine_with_llm(
            two_clauses, timeout_seconds=10, model_name="qwen3:14b"
        )
    assert len(result) == 3
    assert result[0].clause_id == "clause_001"
    assert result[1].clause_id == "clause_002"
    assert result[2].clause_id == "clause_003"


def test_refine_infers_clause_type(two_clauses):
    """clause_type strings from LLM are stored on ClauseBoundary (raw string)."""
    response = {
        "clauses": [
            {
                "text": "Definitions here.",
                "section_number": "1",
                "clause_type": "definitions",
            },
            {
                "text": "Payment is due.",
                "section_number": "2",
                "clause_type": "payment",
            },
        ]
    }
    with patch(
        "ollama.chat", return_value={"message": {"content": json.dumps(response)}}
    ):
        result = refine_with_llm(
            two_clauses, timeout_seconds=10, model_name="qwen3:14b"
        )
    assert result[0].clause_type == "definitions"
    assert result[1].clause_type == "payment"


def test_refine_null_clause_type_accepted(two_clauses):
    """LLM returning null clause_type yields None in output."""
    response = {
        "clauses": [
            {"text": "Some clause.", "section_number": None, "clause_type": None},
            {"text": "Another clause.", "section_number": None, "clause_type": None},
        ]
    }
    with patch(
        "ollama.chat", return_value={"message": {"content": json.dumps(response)}}
    ):
        result = refine_with_llm(
            two_clauses, timeout_seconds=10, model_name="qwen3:14b"
        )
    assert result[0].clause_type is None
    assert result[1].clause_type is None


def test_refine_invalid_clause_type_becomes_none(two_clauses):
    """Unrecognised clause_type string → None (not stored as-is)."""
    response = {
        "clauses": [
            {"text": "Some clause.", "section_number": None, "clause_type": "banana"},
            {
                "text": "Another clause.",
                "section_number": None,
                "clause_type": "XYZ_INVALID",
            },
        ]
    }
    with patch(
        "ollama.chat", return_value={"message": {"content": json.dumps(response)}}
    ):
        result = refine_with_llm(
            two_clauses, timeout_seconds=10, model_name="qwen3:14b"
        )
    assert result[0].clause_type is None
    assert result[1].clause_type is None


def test_refine_clause_ids_renumbered():
    """Output clause IDs are renumbered sequentially regardless of merge/split."""
    regex_clauses = [
        make_boundary("clause_001", "First.", 1),
        make_boundary("clause_002", "Second.", 2),
        make_boundary("clause_003", "Third.", 3),
    ]
    response = {
        "clauses": [
            {
                "text": "First and Second merged.",
                "section_number": None,
                "clause_type": None,
            },
            {"text": "Third.", "section_number": None, "clause_type": None},
        ]
    }
    with patch(
        "ollama.chat", return_value={"message": {"content": json.dumps(response)}}
    ):
        result = refine_with_llm(
            regex_clauses, timeout_seconds=10, model_name="qwen3:14b"
        )
    assert result[0].clause_id == "clause_001"
    assert result[0].position == 1
    assert result[1].clause_id == "clause_002"
    assert result[1].position == 2


def test_refine_timeout_returns_regex_output(two_clauses):
    """Timeout → returns input regex_clauses unchanged."""

    def slow_chat(*args, **kwargs):
        time.sleep(5)
        return {"message": {"content": '{"clauses": []}'}}

    with patch("ollama.chat", side_effect=slow_chat):
        result = refine_with_llm(
            two_clauses, timeout_seconds=0.05, model_name="qwen3:14b"
        )
    assert result is two_clauses


def test_refine_malformed_json_returns_regex_output(two_clauses, caplog):
    """Invalid JSON response → fallback to regex output, warning logged."""
    with patch("ollama.chat", return_value={"message": {"content": "NOT_VALID_JSON"}}):
        with caplog.at_level("WARNING"):
            result = refine_with_llm(
                two_clauses, timeout_seconds=10, model_name="qwen3:14b"
            )
    assert result is two_clauses
    assert any(
        "warning" in r.levelname.lower()
        or "fallback" in r.message.lower()
        or "failed" in r.message.lower()
        for r in caplog.records
    )


def test_refine_missing_clauses_key_returns_regex_output(two_clauses, caplog):
    """JSON without 'clauses' key → fallback to regex output."""
    response = {"wrong_key": []}
    with patch(
        "ollama.chat", return_value={"message": {"content": json.dumps(response)}}
    ):
        with caplog.at_level("WARNING"):
            result = refine_with_llm(
                two_clauses, timeout_seconds=10, model_name="qwen3:14b"
            )
    assert result is two_clauses


def test_refine_empty_clause_text_returns_regex_output(two_clauses, caplog):
    """Clause with empty 'text' value → fallback to regex output."""
    response = {
        "clauses": [
            {"text": "", "section_number": None, "clause_type": None},
        ]
    }
    with patch(
        "ollama.chat", return_value={"message": {"content": json.dumps(response)}}
    ):
        with caplog.at_level("WARNING"):
            result = refine_with_llm(
                two_clauses, timeout_seconds=10, model_name="qwen3:14b"
            )
    assert result is two_clauses


def test_refine_connection_error_returns_regex_output(two_clauses, caplog):
    """Ollama unreachable (ConnectionError) → fallback to regex output, warning logged."""
    with patch("ollama.chat", side_effect=ConnectionError("Connection refused")):
        with caplog.at_level("WARNING"):
            result = refine_with_llm(
                two_clauses, timeout_seconds=10, model_name="qwen3:14b"
            )
    assert result is two_clauses
    assert any(
        "warning" in r.levelname.lower() or "failed" in r.message.lower()
        for r in caplog.records
    )


def test_refine_preserves_all_text(two_clauses):
    """All input text appears in output (no text dropped)."""
    response = {
        "clauses": [
            {
                "text": two_clauses[0].text,
                "section_number": "1",
                "clause_type": "definitions",
            },
            {
                "text": two_clauses[1].text,
                "section_number": "2",
                "clause_type": "payment",
            },
        ]
    }
    with patch(
        "ollama.chat", return_value={"message": {"content": json.dumps(response)}}
    ):
        result = refine_with_llm(
            two_clauses, timeout_seconds=10, model_name="qwen3:14b"
        )
    output_texts = {c.text for c in result}
    for clause in two_clauses:
        assert clause.text in output_texts


def test_refine_json_mode_used(two_clauses):
    """Ollama call includes format='json' parameter."""
    response = {
        "clauses": [
            {"text": "Some text.", "section_number": None, "clause_type": None},
        ]
    }
    with patch(
        "ollama.chat", return_value={"message": {"content": json.dumps(response)}}
    ) as mock_chat:
        refine_with_llm(two_clauses, timeout_seconds=10, model_name="qwen3:14b")
    mock_chat.assert_called_once()
    call_kwargs = mock_chat.call_args
    # format="json" may be positional or keyword
    assert call_kwargs.kwargs.get("format") == "json" or (
        len(call_kwargs.args) > 2 and call_kwargs.args[2] == "json"
    )
