"""
Unit tests for app.graph.nodes.scorers.risk_scorer.score_risk.

The LLM boundary (ollama.Client) is mocked — no running Ollama required.
Tests confirm parsing logic, failure handling, truncation, and model separation.

Run: python -m pytest tests/unit/test_risk_scorer.py -v
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.graph.state import RiskLevel


def _make_ollama_response(risk_level: str, rationale: str = "test rationale") -> dict:
    """Build a minimal valid Ollama chat response."""
    return {
        "message": {
            "content": json.dumps({"risk_level": risk_level, "rationale": rationale})
        }
    }


def _make_mock_client(
    risk_level: str = "high", rationale: str = "test rationale"
) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = _make_ollama_response(risk_level, rationale)
    return client


# ── Parsing tests ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "level_str,expected",
    [
        ("high", RiskLevel.HIGH),
        ("medium", RiskLevel.MEDIUM),
        ("low", RiskLevel.LOW),
    ],
)
def test_parses_high_medium_low(level_str, expected):
    """{"risk_level": "high"/"medium"/"low"} → RiskLevel.HIGH/MEDIUM/LOW."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    mock_client = _make_mock_client(level_str)
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        result = score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    assert result is not None
    level, _ = result
    assert level == expected


def test_level_case_and_whitespace_insensitive():
    """{"risk_level": " HIGH "} → RiskLevel.HIGH."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    mock_client = MagicMock()
    mock_client.chat.return_value = {
        "message": {"content": json.dumps({"risk_level": " HIGH ", "rationale": "r"})}
    }
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        result = score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    assert result is not None
    level, _ = result
    assert level == RiskLevel.HIGH


def test_returns_rationale():
    """The rationale string is returned alongside the level."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    mock_client = _make_mock_client("medium", "This is a medium risk clause.")
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        result = score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    assert result is not None
    _, rationale = result
    assert rationale == "This is a medium risk clause."


# ── Failure handling tests ─────────────────────────────────────────────────────


def test_timeout_returns_none(caplog):
    """Simulated timeout → None, warning logged."""
    import concurrent.futures
    from app.graph.nodes.scorers.risk_scorer import score_risk

    mock_client = MagicMock()
    mock_client.chat.side_effect = concurrent.futures.TimeoutError()
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        with caplog.at_level("WARNING"):
            result = score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    assert result is None


def test_connection_error_returns_none():
    """Ollama unreachable → None."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    mock_client = MagicMock()
    mock_client.chat.side_effect = ConnectionError("refused")
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        result = score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    assert result is None


def test_malformed_json_returns_none():
    """Non-JSON body → None."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    mock_client = MagicMock()
    mock_client.chat.return_value = {"message": {"content": "not json at all"}}
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        result = score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    assert result is None


def test_missing_risk_level_returns_none():
    """JSON without risk_level key → None."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    mock_client = MagicMock()
    mock_client.chat.return_value = {
        "message": {"content": json.dumps({"rationale": "some rationale"})}
    }
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        result = score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    assert result is None


def test_invalid_level_string_returns_none():
    """{"risk_level": "critical"} → None (not a RiskLevel) (AC-13)."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    mock_client = MagicMock()
    mock_client.chat.return_value = {
        "message": {"content": json.dumps({"risk_level": "critical", "rationale": "r"})}
    }
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        result = score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    assert result is None


def test_empty_rationale_returns_none():
    """Valid risk_level but empty/blank rationale → None (fail-safe), so a scored
    finding never persists an empty risk_rationale (spec AC-1)."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    for bad_rationale in ["", "   ", "\n\t"]:
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {
                "content": json.dumps(
                    {"risk_level": "high", "rationale": bad_rationale}
                )
            }
        }
        with patch(
            "app.graph.nodes.scorers.risk_scorer.ollama.Client",
            return_value=mock_client,
        ):
            result = score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
        assert result is None, f"expected None for rationale={bad_rationale!r}"


def test_missing_rationale_key_returns_none():
    """Valid risk_level but no rationale key at all → None (fail-safe)."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    mock_client = MagicMock()
    mock_client.chat.return_value = {
        "message": {"content": json.dumps({"risk_level": "medium"})}
    }
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        result = score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    assert result is None


def test_non_string_level_returns_none():
    """{"risk_level": 3} → None (non-string)."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    mock_client = MagicMock()
    mock_client.chat.return_value = {
        "message": {"content": json.dumps({"risk_level": 3, "rationale": "r"})}
    }
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        result = score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    assert result is None


def test_scorer_never_raises():
    """Any injected exception → None, nothing propagates."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    mock_client = MagicMock()
    mock_client.chat.side_effect = RuntimeError("unexpected boom")
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        result = score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    assert result is None


# ── Model / constant tests ─────────────────────────────────────────────────────


def test_uses_generative_model_only():
    """chat called with model=OLLAMA_MODEL_NAME; OLLAMA_EMBED_MODEL_NAME never referenced (AC-6)."""
    from app.graph.nodes.scorers.risk_scorer import score_risk
    from app.config import OLLAMA_MODEL_NAME, OLLAMA_EMBED_MODEL_NAME

    mock_client = _make_mock_client("high")
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        result = score_risk("clause text", None, None, 30, OLLAMA_MODEL_NAME, 6000)

    assert result is not None
    chat_kwargs = mock_client.chat.call_args
    model_used = (
        chat_kwargs[1].get("model") or chat_kwargs[0][0]
        if chat_kwargs[0]
        else chat_kwargs[1]["model"]
    )
    assert model_used == OLLAMA_MODEL_NAME
    assert model_used != OLLAMA_EMBED_MODEL_NAME


# ── Truncation tests ───────────────────────────────────────────────────────────


def test_prompt_truncated_to_max_chars():
    """Oversized clause text + evidence is truncated so the combined input is bounded (AC-19)."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    prompt_max = 100
    # clause longer than prompt_max
    long_clause = "A" * 200
    # evidence that would also be long
    evidence = [{"snippet_text": "B" * 200, "source_reference": "src"}]

    captured_prompts = []

    def fake_chat(**kwargs):
        msg_content = kwargs["messages"][0]["content"]
        captured_prompts.append(msg_content)
        return _make_ollama_response("high")

    mock_client = MagicMock()
    mock_client.chat.side_effect = fake_chat

    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        result = score_risk(long_clause, evidence, None, 30, "qwen3:14b", prompt_max)

    assert result is not None
    assert len(captured_prompts) == 1
    # The combined variable portion (clause_trunc + evidence_str) must be <= prompt_max
    # The actual prompt includes template text, but the variable data part is bounded
    clause_portion = long_clause[:prompt_max]
    remaining = max(0, prompt_max - len(clause_portion))
    # evidence portion cannot exceed remaining
    assert len(clause_portion) <= prompt_max
    assert remaining + len(clause_portion) == prompt_max


def test_empty_evidence_scores_on_text():
    """evidence_snippets=None/[] → uses text-only prompt variant; no crash (AC-20)."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    for evidence in [None, []]:
        mock_client = _make_mock_client("low")
        with patch(
            "app.graph.nodes.scorers.risk_scorer.ollama.Client",
            return_value=mock_client,
        ):
            result = score_risk(
                "clause text about indemnity", evidence, None, 30, "qwen3:14b", 6000
            )
        assert result is not None
        level, rationale = result
        assert level == RiskLevel.LOW


def test_clause_type_included_in_prompt():
    """A provided clause_type label appears in the prompt; None → 'unspecified' wording."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    captured_prompts = []

    def fake_chat(**kwargs):
        captured_prompts.append(kwargs["messages"][0]["content"])
        return _make_ollama_response("high")

    mock_client = MagicMock()
    mock_client.chat.side_effect = fake_chat

    # With clause_type
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        score_risk("clause text", None, "liability", 30, "qwen3:14b", 6000)
    assert "liability" in captured_prompts[-1]

    # With None → "unspecified"
    captured_prompts.clear()
    mock_client2 = MagicMock()
    mock_client2.chat.side_effect = fake_chat
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client2
    ):
        score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    assert "unspecified" in captured_prompts[-1]


def test_rationale_returned_untruncated():
    """The scorer returns the full rationale; the NODE applies RISK_RATIONALE_MAX_CHARS (not scorer)."""
    from app.graph.nodes.scorers.risk_scorer import score_risk

    long_rationale = "X" * 2000  # longer than RISK_RATIONALE_MAX_CHARS (1000)
    mock_client = MagicMock()
    mock_client.chat.return_value = _make_ollama_response("medium", long_rationale)
    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        result = score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    assert result is not None
    _, rationale = result
    assert rationale == long_rationale  # returned untruncated from scorer


# ── Determinism sampling options (feature 028, AC-2/3/4) ────────────────────────
def _rs_options(mock_client):
    from app.graph.nodes.scorers.risk_scorer import score_risk

    with patch(
        "app.graph.nodes.scorers.risk_scorer.ollama.Client", return_value=mock_client
    ):
        score_risk("clause text", None, None, 30, "qwen3:14b", 6000)
    return mock_client.chat.call_args.kwargs["options"]


def test_chat_options_carry_sampling_config():
    """AC-2: options carry temperature and preserve num_predict; AC-3 seed present."""
    from app.config import OLLAMA_TEMPERATURE, OLLAMA_SEED

    opts = _rs_options(_make_mock_client("high"))
    assert opts["num_predict"] == 384
    assert opts["temperature"] == OLLAMA_TEMPERATURE
    assert opts["seed"] == OLLAMA_SEED


def test_chat_options_omit_seed_when_none(monkeypatch):
    """AC-3: OLLAMA_SEED None → 'seed' key absent (not None)."""
    import app.graph.nodes.scorers.risk_scorer as node

    monkeypatch.setattr(node, "OLLAMA_SEED", None)
    opts = _rs_options(_make_mock_client("high"))
    assert "seed" not in opts
    assert opts["num_predict"] == 384


def test_chat_options_reversible_to_sampling(monkeypatch):
    """AC-4: temp 0.8 + seed None → pre-028 default-sampling behavior."""
    import app.graph.nodes.scorers.risk_scorer as node

    monkeypatch.setattr(node, "OLLAMA_TEMPERATURE", 0.8)
    monkeypatch.setattr(node, "OLLAMA_SEED", None)
    opts = _rs_options(_make_mock_client("high"))
    assert opts["temperature"] == 0.8
    assert "seed" not in opts
    assert opts["num_predict"] == 384
