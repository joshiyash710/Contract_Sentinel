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


def _joined(mock_inst) -> str:
    """Feature 035: the outgoing prompt now spans a [system, user] message list; join both so
    assertions about untrusted (clause/evidence) content see the whole prompt, not just messages[0]
    (which is the SYSTEM instruction message under the defense-ON path)."""
    return "".join(m["content"] for m in mock_inst.chat.call_args.kwargs["messages"])


def test_relevance_prompt_excludes_evidence():
    """The Relevance prompt is a function of clause text only (no evidence text)."""
    check_relevance, _, _ = _import_reflectors()
    evidence_marker = "THIS_IS_EVIDENCE_TEXT_12345"
    mock_cls, mock_inst = _make_client_mock(True)
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        check_relevance("clause text here", 10, "qwen3:14b", 6000)
    # Negative-assert against the JOINED content so it cannot pass trivially (035 tasks §C).
    assert evidence_marker not in _joined(mock_inst)


def test_issup_empty_evidence_uses_text_only_prompt():
    """With evidence_snippets=None/[], the ISSUP prompt instructs judging on clause text alone."""
    _, _, check_issup = _import_reflectors()
    mock_cls, mock_inst = _make_client_mock(True)
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        check_issup("clause text", None, 10, "qwen3:14b", 6000)
    # This asserts TRUSTED instruction wording, which lives in the system message (messages[0]).
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
    # Untrusted clause text lives in the user message → assert against the JOINED content (035).
    prompt_sent = _joined(mock_inst)
    # The variable clause+evidence portion of the prompt must not exceed prompt_max_chars
    clause_trunc = big_clause[:prompt_max_chars]
    remaining = max(0, prompt_max_chars - len(clause_trunc))
    evidence_str = format_evidence(big_evidence, remaining)
    assert len(clause_trunc) + len(evidence_str) <= prompt_max_chars
    # Also assert those truncated strings actually appear in the prompt
    assert clause_trunc in prompt_sent or clause_trunc[:50] in prompt_sent


# ── Determinism sampling options (feature 028, AC-2/3/4) ────────────────────────
def _rf_options():
    check_relevance, _, _ = _import_reflectors()
    mock_cls, mock_inst = _make_client_mock(True)
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        check_relevance("A clause text.", 10, "qwen3:14b", 6000)
    return mock_inst.chat.call_args.kwargs["options"]


def test_chat_options_carry_sampling_config():
    """AC-2/AC-3: options carry temperature + seed, preserve num_predict."""
    from app.config import OLLAMA_TEMPERATURE, OLLAMA_SEED

    opts = _rf_options()
    assert opts["num_predict"] == 256
    assert opts["temperature"] == OLLAMA_TEMPERATURE
    assert opts["seed"] == OLLAMA_SEED


def test_chat_options_omit_seed_when_none(monkeypatch):
    """AC-3: OLLAMA_SEED None → 'seed' key absent."""
    import app.graph.nodes.validators.reflectors as node

    monkeypatch.setattr(node, "OLLAMA_SEED", None)
    opts = _rf_options()
    assert "seed" not in opts
    assert opts["num_predict"] == 256


def test_chat_options_reversible_to_sampling(monkeypatch):
    """AC-4: temp 0.8 + seed None → pre-028 behavior."""
    import app.graph.nodes.validators.reflectors as node

    monkeypatch.setattr(node, "OLLAMA_TEMPERATURE", 0.8)
    monkeypatch.setattr(node, "OLLAMA_SEED", None)
    opts = _rf_options()
    assert opts["temperature"] == 0.8
    assert "seed" not in opts
    assert opts["num_predict"] == 256


# ── check_combined — Lever C (feature 029, AC-1/2/6/7) ──────────────────────────
def _import_combined():
    from app.graph.nodes.validators.reflectors import check_combined

    return check_combined


_SNIPPETS = [{"snippet_text": "evidence", "source_reference": "r"}]


def test_combined_happy_path_returns_three_bools_one_call():
    """AC-1/AC-2: a well-formed object → {relevance,isrel,issup} bools, chat called ONCE."""
    check_combined = _import_combined()
    mock_cls, mock_inst = _make_client_mock_raw(
        json.dumps({"relevance": True, "isrel": True, "issup": True, "reason": "x"})
    )
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        result = check_combined("A clause.", _SNIPPETS, 10, "qwen3:14b", 6000)
    assert result == {"relevance": True, "isrel": True, "issup": True}
    assert mock_inst.chat.call_count == 1


def test_combined_mixed_bools_preserved():
    """Each key carries its own genuine bool."""
    check_combined = _import_combined()
    mock_cls, _ = _make_client_mock_raw(
        json.dumps({"relevance": True, "isrel": False, "issup": True})
    )
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        result = check_combined("A clause.", _SNIPPETS, 10, "qwen3:14b", 6000)
    assert result == {"relevance": True, "isrel": False, "issup": True}


def test_combined_non_json_returns_none():
    """AC-6: non-JSON content → None (whole-call failure → caller fail-opens)."""
    check_combined = _import_combined()
    mock_cls, _ = _make_client_mock_raw("not json at all")
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        result = check_combined("A clause.", _SNIPPETS, 10, "qwen3:14b", 6000)
    assert result is None


def test_combined_non_object_json_returns_none():
    """AC-6: JSON that is not an object (array / scalar) → None."""
    check_combined = _import_combined()
    for raw in ["[1, 2, 3]", "true", "42", '"a string"']:
        mock_cls, _ = _make_client_mock_raw(raw)
        with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
            result = check_combined("A clause.", _SNIPPETS, 10, "qwen3:14b", 6000)
        assert result is None, f"expected None for raw={raw!r}, got {result!r}"


def test_combined_exception_and_timeout_return_none():
    """AC-6: a raised exception / timeout → None; never raises."""
    check_combined = _import_combined()
    for exc in [concurrent.futures.TimeoutError(), ConnectionError("refused"), RuntimeError("boom")]:
        mock_cls = MagicMock()
        mock_cls.return_value.chat.side_effect = exc
        with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
            result = check_combined("A clause.", _SNIPPETS, 10, "qwen3:14b", 6000)
        assert result is None


def test_combined_missing_key_is_per_key_none():
    """AC-7: object parses but a key is missing → that verdict is None, others preserved."""
    check_combined = _import_combined()
    mock_cls, _ = _make_client_mock_raw(
        json.dumps({"relevance": True, "isrel": True})  # issup missing
    )
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        result = check_combined("A clause.", _SNIPPETS, 10, "qwen3:14b", 6000)
    assert result == {"relevance": True, "isrel": True, "issup": None}


def test_combined_non_bool_key_is_per_key_none():
    """AC-7: non-bool key value (str / int / None) → that verdict is None (reject ints/strings)."""
    check_combined = _import_combined()
    mock_cls, _ = _make_client_mock_raw(
        json.dumps({"relevance": "yes", "isrel": 1, "issup": False})
    )
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        result = check_combined("A clause.", _SNIPPETS, 10, "qwen3:14b", 6000)
    assert result == {"relevance": None, "isrel": None, "issup": False}


def test_combined_num_predict_uses_merged_cap():
    """suggestion #3: options carry SELF_RAG_MERGED_NUM_PREDICT (sized for 3-verdict object)."""
    from app.config import SELF_RAG_MERGED_NUM_PREDICT, OLLAMA_TEMPERATURE

    check_combined = _import_combined()
    mock_cls, mock_inst = _make_client_mock_raw(
        json.dumps({"relevance": True, "isrel": True, "issup": True})
    )
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        check_combined("A clause.", _SNIPPETS, 10, "qwen3:14b", 6000)
    opts = mock_inst.chat.call_args.kwargs["options"]
    assert opts["num_predict"] == SELF_RAG_MERGED_NUM_PREDICT
    assert opts["temperature"] == OLLAMA_TEMPERATURE


def test_combined_uses_generative_model_and_evidence_in_prompt():
    """The combined prompt includes the evidence text and uses the generative model."""
    from app.config import OLLAMA_MODEL_NAME

    check_combined = _import_combined()
    mock_cls, mock_inst = _make_client_mock_raw(
        json.dumps({"relevance": True, "isrel": True, "issup": True})
    )
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        check_combined("A clause.", _SNIPPETS, 10, OLLAMA_MODEL_NAME, 6000)
    kwargs = mock_inst.chat.call_args.kwargs
    assert kwargs["model"] == OLLAMA_MODEL_NAME
    # The evidence snippet text + clause both reach the model (in the wrapped user body under 035).
    assert "evidence" in _joined(mock_inst)
    assert "A clause." in _joined(mock_inst)


# ── Feature 035: prompt-injection defense (reflectors) ───────────────────────


def test_035_off_path_byte_identical_relevance(monkeypatch):
    """AC-7: with the defense OFF, the reflectors send the exact pre-035 single user message."""
    from app.graph.nodes.validators.reflectors import _RELEVANCE_PROMPT
    from app.llm import prompt_guard

    monkeypatch.setattr(prompt_guard, "PROMPT_INJECTION_DEFENSE_ENABLED", False)
    check_relevance, _, _ = _import_reflectors()
    mock_cls, mock_inst = _make_client_mock(True)
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        check_relevance("hello clause", 10, "qwen3:8b", 6000)
    msgs = mock_inst.chat.call_args.kwargs["messages"]
    assert msgs == [{"role": "user", "content": _RELEVANCE_PROMPT.format(clause_text="hello clause")}]


def test_035_on_path_wraps_clause_in_user_message(monkeypatch):
    """AC-4/AC-5: ON path → [system,user]; the clause appears ONLY inside a ⟦CLAUSE:…⟧ fence in the
    user message, and the anti-injection preamble is in the system message."""
    from app.llm import prompt_guard

    monkeypatch.setattr(prompt_guard, "PROMPT_INJECTION_DEFENSE_ENABLED", True)
    check_relevance, _, _ = _import_reflectors()
    mock_cls, mock_inst = _make_client_mock(True)
    with patch("app.graph.nodes.validators.reflectors.ollama.Client", mock_cls):
        check_relevance("UNIQUE_CLAUSE_MARKER_777", 10, "qwen3:8b", 6000)
    msgs = mock_inst.chat.call_args.kwargs["messages"]
    assert len(msgs) == 2 and msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
    assert prompt_guard.ANTI_INJECTION_PREAMBLE in msgs[0]["content"]
    # clause only inside the fence in the user message, not in the system message
    assert "UNIQUE_CLAUSE_MARKER_777" in msgs[1]["content"]
    assert "UNIQUE_CLAUSE_MARKER_777" not in msgs[0]["content"]
    assert "⟦CLAUSE:" in msgs[1]["content"] and "⟦/CLAUSE:" in msgs[1]["content"]
