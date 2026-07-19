"""
Unit tests for app.graph.nodes.drafters.redline_drafter.draft_rewrite.

All tests mock ollama.Client — no running Ollama required.
Run: python -m pytest tests/unit/test_redline_drafter.py -v
"""

import json
from unittest.mock import MagicMock, patch, call

import pytest

from app.graph.nodes.drafters.redline_drafter import draft_rewrite
from app.config import OLLAMA_MODEL_NAME, OLLAMA_EMBED_MODEL_NAME


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_client(content: str) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = {"message": {"content": content}}
    return client


def _ok_response(text: str = "safer clause text") -> str:
    return json.dumps({"suggested_rewrite": text})


_DEFAULT_KWARGS = dict(
    risk_rationale="Unlimited liability exposure.",
    evidence_snippets=None,
    clause_type="liability",
    timeout_seconds=30,
    model_name=OLLAMA_MODEL_NAME,
    prompt_max_chars=500,
    rationale_reserve=100,
)


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_returns_rewrite_string():
    """Valid JSON with suggested_rewrite → returns the string."""
    with patch("app.graph.nodes.drafters.redline_drafter.ollama.Client") as MockClient:
        MockClient.return_value = _make_client(_ok_response("safer text"))
        result = draft_rewrite("The vendor bears unlimited liability.", **_DEFAULT_KWARGS)
    assert result == "safer text"


def test_timeout_returns_none(caplog):
    """Simulated timeout → returns None, warning logged."""
    import concurrent.futures
    with patch("app.graph.nodes.drafters.redline_drafter.ollama.Client") as MockClient:
        MockClient.return_value.chat.side_effect = concurrent.futures.TimeoutError()
        with caplog.at_level("WARNING", logger="contractsentinel.redline.drafter"):
            result = draft_rewrite("clause text", **_DEFAULT_KWARGS)
    assert result is None
    assert any("timed out" in r.message for r in caplog.records)


def test_connection_error_returns_none(caplog):
    """Ollama unreachable → returns None, warning logged."""
    with patch("app.graph.nodes.drafters.redline_drafter.ollama.Client") as MockClient:
        MockClient.return_value.chat.side_effect = ConnectionError("refused")
        with caplog.at_level("WARNING", logger="contractsentinel.redline.drafter"):
            result = draft_rewrite("clause text", **_DEFAULT_KWARGS)
    assert result is None


def test_malformed_json_returns_none(caplog):
    """Non-JSON body → None, warning logged."""
    with patch("app.graph.nodes.drafters.redline_drafter.ollama.Client") as MockClient:
        MockClient.return_value = _make_client("not json at all")
        with caplog.at_level("WARNING", logger="contractsentinel.redline.drafter"):
            result = draft_rewrite("clause text", **_DEFAULT_KWARGS)
    assert result is None
    assert any("non-JSON" in r.message for r in caplog.records)


def test_missing_field_returns_none(caplog):
    """JSON without suggested_rewrite key → None, warning logged."""
    with patch("app.graph.nodes.drafters.redline_drafter.ollama.Client") as MockClient:
        MockClient.return_value = _make_client(json.dumps({"other_key": "value"}))
        with caplog.at_level("WARNING", logger="contractsentinel.redline.drafter"):
            result = draft_rewrite("clause text", **_DEFAULT_KWARGS)
    assert result is None


def test_empty_rewrite_returns_none(caplog):
    """Empty/whitespace suggested_rewrite is a drafting failure (AC-19)."""
    with patch("app.graph.nodes.drafters.redline_drafter.ollama.Client") as MockClient:
        MockClient.return_value = _make_client(json.dumps({"suggested_rewrite": "   "}))
        with caplog.at_level("WARNING", logger="contractsentinel.redline.drafter"):
            result = draft_rewrite("clause text", **_DEFAULT_KWARGS)
    assert result is None
    assert any("empty" in r.message.lower() for r in caplog.records)


def test_non_string_rewrite_returns_none():
    """Non-str suggested_rewrite (int, null) → None."""
    for bad_value in [5, None, [], {}]:
        with patch("app.graph.nodes.drafters.redline_drafter.ollama.Client") as MockClient:
            MockClient.return_value = _make_client(
                json.dumps({"suggested_rewrite": bad_value})
            )
            result = draft_rewrite("clause text", **_DEFAULT_KWARGS)
        assert result is None, f"Expected None for {bad_value!r}, got {result!r}"


def test_uses_generative_model_only():
    """chat called with OLLAMA_MODEL_NAME; OLLAMA_EMBED_MODEL_NAME never referenced (AC-12)."""
    with patch("app.graph.nodes.drafters.redline_drafter.ollama.Client") as MockClient:
        mock_client = _make_client(_ok_response())
        MockClient.return_value = mock_client
        draft_rewrite("clause text", **_DEFAULT_KWARGS)
        chat_call = mock_client.chat.call_args
    assert chat_call is not None
    model_used = chat_call.kwargs.get("model") or chat_call.args[0] if chat_call.args else chat_call.kwargs["model"]
    # Extract from keyword args
    assert mock_client.chat.call_args[1]["model"] == OLLAMA_MODEL_NAME
    assert OLLAMA_MODEL_NAME != OLLAMA_EMBED_MODEL_NAME


def test_prompt_truncated_to_max_chars():
    """Oversized clause+rationale+evidence are bounded by prompt_max_chars (AC-22).

    Uses characters (§ and ®) that don't appear in the prompt template so the counts
    are exact.
    """
    long_clause = "§" * 300   # unique marker absent from all template text
    long_rationale = "®" * 200  # unique marker absent from all template text
    small_budget = 200
    small_reserve = 50

    captured_prompt = {}

    def capture_call(prompt, timeout_seconds, model_name):
        captured_prompt["prompt"] = prompt
        return "safer text"

    with patch(
        "app.graph.nodes.drafters.redline_drafter._run_drafting",
        side_effect=capture_call,
    ):
        draft_rewrite(
            long_clause,
            risk_rationale=long_rationale,
            evidence_snippets=None,
            clause_type="liability",
            timeout_seconds=30,
            model_name=OLLAMA_MODEL_NAME,
            prompt_max_chars=small_budget,
            rationale_reserve=small_reserve,
        )

    # The combined variable portion in the prompt must be bounded by the budget.
    prompt_text = captured_prompt["prompt"]
    clause_count = prompt_text.count("§")    # unique to clause
    rationale_count = prompt_text.count("®")  # unique to rationale
    assert clause_count + rationale_count <= small_budget


def test_long_clause_preserves_rationale():
    """A clause longer than prompt_max_chars still includes the risk_rationale (AC-22).

    The rationale floor must not be starved to zero — this locks the reserve logic,
    the one piece of new logic vs. Node 5.
    """
    marker = "UNCAPPED_LIABILITY_MARKER"
    long_clause = "A" * 300  # longer than the small budget of 200
    small_budget = 200
    small_reserve = 50

    captured_prompt = {}

    def capture_call(prompt, timeout_seconds, model_name):
        captured_prompt["prompt"] = prompt
        return "safer text"

    with patch(
        "app.graph.nodes.drafters.redline_drafter._run_drafting",
        side_effect=capture_call,
    ):
        draft_rewrite(
            long_clause,
            risk_rationale=marker,
            evidence_snippets=None,
            clause_type="liability",
            timeout_seconds=30,
            model_name=OLLAMA_MODEL_NAME,
            prompt_max_chars=small_budget,
            rationale_reserve=small_reserve,
        )

    assert marker in captured_prompt["prompt"], (
        "risk_rationale must appear in the prompt even when the clause exceeds the budget"
    )


def test_empty_evidence_drafts_on_text():
    """evidence_snippets=None/[] uses the text-only prompt variant; no crash (AC-26)."""
    for evidence in [None, []]:
        with patch("app.graph.nodes.drafters.redline_drafter.ollama.Client") as MockClient:
            MockClient.return_value = _make_client(_ok_response("safer clause"))
            result = draft_rewrite(
                "clause text",
                risk_rationale="Too risky.",
                evidence_snippets=evidence,
                clause_type="general",
                timeout_seconds=30,
                model_name=OLLAMA_MODEL_NAME,
                prompt_max_chars=500,
                rationale_reserve=100,
            )
        assert result == "safer clause", f"Failed for evidence={evidence!r}"


def test_rationale_included_in_prompt():
    """The provided risk_rationale text appears in the built prompt."""
    captured_prompt = {}

    def capture_call(prompt, timeout_seconds, model_name):
        captured_prompt["prompt"] = prompt
        return "safer text"

    with patch(
        "app.graph.nodes.drafters.redline_drafter._run_drafting",
        side_effect=capture_call,
    ):
        draft_rewrite(
            "clause text",
            risk_rationale="DISTINCTIVE_RATIONALE_MARKER",
            evidence_snippets=None,
            clause_type="liability",
            timeout_seconds=30,
            model_name=OLLAMA_MODEL_NAME,
            prompt_max_chars=500,
            rationale_reserve=100,
        )

    assert "DISTINCTIVE_RATIONALE_MARKER" in captured_prompt["prompt"]


def test_clause_type_included_in_prompt():
    """clause_type label appears in the prompt; None → 'unspecified' wording."""
    for clause_type, expected in [("liability", "liability"), (None, "unspecified")]:
        captured_prompt = {}

        def capture_call(prompt, timeout_seconds, model_name):
            captured_prompt["prompt"] = prompt
            return "safer text"

        with patch(
            "app.graph.nodes.drafters.redline_drafter._run_drafting",
            side_effect=capture_call,
        ):
            draft_rewrite(
                "clause text",
                risk_rationale="Too risky.",
                evidence_snippets=None,
                clause_type=clause_type,
                timeout_seconds=30,
                model_name=OLLAMA_MODEL_NAME,
                prompt_max_chars=500,
                rationale_reserve=100,
            )

        assert expected in captured_prompt["prompt"], (
            f"Expected {expected!r} in prompt for clause_type={clause_type!r}"
        )


def test_drafter_never_raises():
    """Any injected exception inside the call → None, nothing propagates."""
    with patch("app.graph.nodes.drafters.redline_drafter.ollama.Client") as MockClient:
        MockClient.side_effect = RuntimeError("unexpected boom")
        result = draft_rewrite("clause text", **_DEFAULT_KWARGS)
    assert result is None


def test_rewrite_returned_untruncated():
    """The drafter returns the full rewrite string; the NODE applies REDLINE_REWRITE_MAX_CHARS."""
    long_rewrite = "X" * 5000  # longer than REDLINE_REWRITE_MAX_CHARS=4000
    with patch("app.graph.nodes.drafters.redline_drafter.ollama.Client") as MockClient:
        MockClient.return_value = _make_client(
            json.dumps({"suggested_rewrite": long_rewrite})
        )
        result = draft_rewrite("clause text", **_DEFAULT_KWARGS)
    assert result == long_rewrite  # drafter does NOT truncate
    assert len(result) == 5000


# ── Determinism sampling options (feature 028, AC-2/3/4) ────────────────────────
def _rd_options():
    client = _make_client(_ok_response("safer text"))
    with patch("app.graph.nodes.drafters.redline_drafter.ollama.Client") as MockClient:
        MockClient.return_value = client
        draft_rewrite("The vendor bears unlimited liability.", **_DEFAULT_KWARGS)
    return client.chat.call_args.kwargs["options"]


def test_chat_options_carry_sampling_config():
    """AC-2/AC-3: options carry temperature + seed, preserve num_predict."""
    from app.config import OLLAMA_TEMPERATURE, OLLAMA_SEED

    opts = _rd_options()
    assert opts["num_predict"] == 1536
    assert opts["temperature"] == OLLAMA_TEMPERATURE
    assert opts["seed"] == OLLAMA_SEED


def test_chat_options_omit_seed_when_none(monkeypatch):
    """AC-3: OLLAMA_SEED None → 'seed' key absent."""
    import app.graph.nodes.drafters.redline_drafter as node

    monkeypatch.setattr(node, "OLLAMA_SEED", None)
    opts = _rd_options()
    assert "seed" not in opts
    assert opts["num_predict"] == 1536


def test_chat_options_reversible_to_sampling(monkeypatch):
    """AC-4: temp 0.8 + seed None → pre-028 behavior."""
    import app.graph.nodes.drafters.redline_drafter as node

    monkeypatch.setattr(node, "OLLAMA_TEMPERATURE", 0.8)
    monkeypatch.setattr(node, "OLLAMA_SEED", None)
    opts = _rd_options()
    assert opts["temperature"] == 0.8
    assert "seed" not in opts
    assert opts["num_predict"] == 1536
