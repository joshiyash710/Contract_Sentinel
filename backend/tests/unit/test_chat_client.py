"""Unit tests for the feature-046 LLM provider seam (app/llm/chat_client.py).

Groq SDK is MOCKED — no network. Covers AC-1 (factory dispatch), AC-2 (param translation),
AC-3 (return shape), AC-4 (embeddings never route to Groq, §8), AC-6 (max_retries + missing-key
error + key-never-logged), EC-2 (optional keys).
"""

import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import ollama

import app.llm.chat_client as chat_client
from app.llm.chat_client import get_chat_client, GroqChatClient


def _resp(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _mock_groq(monkeypatch, content='{"risk_level":"high"}'):
    """Patch groq.Groq → a mock whose .chat.completions.create records kwargs and returns _resp."""
    create = MagicMock(return_value=_resp(content))
    instance = MagicMock()
    instance.chat.completions.create = create
    cls = MagicMock(return_value=instance)
    monkeypatch.setattr("groq.Groq", cls)
    return cls, create


# ── AC-1: factory dispatch ───────────────────────────────────────────────────
def test_factory_returns_ollama_client_by_default(monkeypatch):
    monkeypatch.setattr(chat_client, "LLM_PROVIDER", "ollama")
    client = get_chat_client(30)
    assert isinstance(client, ollama.Client)


def test_factory_returns_groq_client_when_configured(monkeypatch):
    monkeypatch.setattr(chat_client, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(chat_client, "GROQ_API_KEY", "gsk_teststub")
    _mock_groq(monkeypatch)
    client = get_chat_client(30)
    assert isinstance(client, GroqChatClient)


# ── AC-2: param translation ──────────────────────────────────────────────────
def test_groq_chat_translates_params(monkeypatch):
    monkeypatch.setattr(chat_client, "GROQ_API_KEY", "gsk_teststub")
    monkeypatch.setattr(chat_client, "GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(chat_client, "GROQ_REASONING_EFFORT", "low")
    monkeypatch.setattr(chat_client, "GROQ_MAX_RETRIES", 2)
    cls, create = _mock_groq(monkeypatch)

    client = GroqChatClient(45)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    client.chat(
        model="qwen3:8b",
        messages=msgs,
        format="json",
        think=False,
        options={"num_predict": 384, "temperature": 0.0, "seed": 42},
    )
    # SDK client constructed with retries + timeout (api_key present but not asserted by value).
    assert cls.call_args.kwargs["max_retries"] == 2
    assert cls.call_args.kwargs["timeout"] == 45.0
    kw = create.call_args.kwargs
    assert kw["model"] == "openai/gpt-oss-120b"  # D7: passed ollama model ignored
    assert kw["messages"] is msgs
    assert kw["response_format"] == {"type": "json_object"}
    assert kw["reasoning_effort"] == "low"
    assert kw["max_completion_tokens"] == 384
    assert kw["temperature"] == 0.0
    assert kw["seed"] == 42


# ── AC-3: return shape ───────────────────────────────────────────────────────
def test_groq_chat_returns_ollama_shape(monkeypatch):
    monkeypatch.setattr(chat_client, "GROQ_API_KEY", "gsk_teststub")
    _mock_groq(monkeypatch, content='{"risk_level":"high"}')
    out = GroqChatClient(30).chat(messages=[{"role": "user", "content": "u"}], format="json",
                                  options={"num_predict": 128, "temperature": 0.0})
    assert out == {"message": {"content": '{"risk_level":"high"}'}}


# ── EC-2: optional options keys omitted ──────────────────────────────────────
def test_groq_chat_omits_missing_optional_kwargs(monkeypatch):
    monkeypatch.setattr(chat_client, "GROQ_API_KEY", "gsk_teststub")
    _cls, create = _mock_groq(monkeypatch)
    GroqChatClient(30).chat(messages=[{"role": "user", "content": "u"}], format="json", options={})
    kw = create.call_args.kwargs
    assert "seed" not in kw
    assert "max_completion_tokens" not in kw


def test_groq_chat_non_json_format_omits_response_format(monkeypatch):
    monkeypatch.setattr(chat_client, "GROQ_API_KEY", "gsk_teststub")
    _cls, create = _mock_groq(monkeypatch)
    GroqChatClient(30).chat(messages=[{"role": "user", "content": "u"}], options={})
    assert "response_format" not in create.call_args.kwargs  # EC-1 defensive


# ── AC-6: retries + missing-key error + key never logged ─────────────────────
def test_missing_key_raises_clear_error_without_leaking_key(monkeypatch):
    monkeypatch.setattr(chat_client, "GROQ_API_KEY", "")
    import pytest

    with pytest.raises(ValueError) as exc:
        GroqChatClient(30)
    assert "GROQ_API_KEY" in str(exc.value)  # names the missing var
    # A missing key is empty, but the message must never echo any key material.
    assert "gsk_" not in str(exc.value)


def test_groq_api_key_never_logged(monkeypatch, caplog):
    secret = "gsk_supersecret_value_1234567890"
    monkeypatch.setattr(chat_client, "GROQ_API_KEY", secret)
    _mock_groq(monkeypatch)
    with caplog.at_level("DEBUG"):
        GroqChatClient(30).chat(messages=[{"role": "user", "content": "u"}], format="json",
                                options={"num_predict": 64})
    assert secret not in caplog.text


# ── AC-4: embeddings never route to Groq (§8) ────────────────────────────────
def test_embeddings_module_does_not_route_to_groq():
    src = pathlib.Path("app/graph/nodes/retrievers/embeddings.py").read_text(encoding="utf-8")
    assert "get_chat_client" not in src, "embeddings must NOT use the generative provider seam (§8)"
    # feature 050: embeddings route bge-m3 through the dedicated EMBEDDING seam (get_embed_client),
    # never the generative one — the §8 separation is preserved by the seam, not by a literal Client.
    assert "get_embed_client" in src, "embeddings must route bge-m3 through the embedding seam (§8)"
