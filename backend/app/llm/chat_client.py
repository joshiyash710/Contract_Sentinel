"""LLM provider seam (feature 046).

`get_chat_client(timeout_seconds)` returns either today's `ollama.Client` (default) or a
`GroqChatClient` that mimics `ollama.Client.chat`'s signature and `{"message": {"content": ...}}`
return shape — so the 5 generative chat call sites swap ONE line and their `.chat(...)` call +
`response["message"]["content"]` parse are untouched.

Constitution rules observed:
  §3 — provider + Groq settings come from app.config named constants (re-exposed as bare module names
        so tests can monkeypatch); read at call time
  §7 — pure translation, TDD-unit-tested with the Groq SDK mocked (no network in the suite)
  §8 — model separation: EMBEDDINGS never use this seam (bge-m3 stays on Ollama). Only generation.

Privacy (spec §1): when LLM_PROVIDER="groq", clause/evidence/rationale prompts are sent to Groq (a
third party). Opt-in, OFF by default. GROQ_API_KEY is read from env/.env and is NEVER logged.
"""

import ollama

import app.config as _config

# Re-exposed as bare module-level names (read at call time in get_chat_client / GroqChatClient) so
# tests can monkeypatch them.
LLM_PROVIDER = _config.LLM_PROVIDER
GROQ_API_KEY = _config.GROQ_API_KEY
GROQ_MODEL = _config.GROQ_MODEL
GROQ_REASONING_EFFORT = _config.GROQ_REASONING_EFFORT
GROQ_MAX_RETRIES = _config.GROQ_MAX_RETRIES


class GroqChatClient:
    """Adapter that exposes the ollama `.chat()` interface backed by Groq's OpenAI-compatible API.

    Only the generative nodes use this; embeddings never do (§8). The Groq SDK sets a proper
    User-Agent (raw urllib is blocked by Groq's edge with Cloudflare 403 error 1010) and provides
    built-in exponential backoff via `max_retries` (so a 429 retries instead of tripping the failsafe).
    """

    def __init__(self, timeout_seconds: float):
        if not GROQ_API_KEY:
            # Never echo key material — the key is empty here, and the message must not leak one.
            raise ValueError(
                "LLM_PROVIDER=groq but GROQ_API_KEY is empty. Set it in backend/.env "
                "(see docs/DEPLOYMENT.md). The key value is intentionally not shown."
            )
        from groq import Groq  # lazy: the dep is only needed on the groq path

        self._client = Groq(
            api_key=GROQ_API_KEY,
            max_retries=GROQ_MAX_RETRIES,
            timeout=float(timeout_seconds),
        )

    def chat(self, model=None, messages=None, format=None, think=None, options=None, **_):
        """Translate an ollama-style chat() call to Groq and return ollama's response shape.

        `model` (the ollama name) is ignored — GROQ_MODEL wins (D7). `think` is ignored; reasoning is
        controlled by GROQ_REASONING_EFFORT (D4). `format="json"` → response_format json_object.
        `options` (num_predict/temperature/seed) map to Groq's max_completion_tokens/temperature/seed.
        """
        opts = options or {}
        kwargs = {
            "model": GROQ_MODEL,
            "messages": messages,
            "temperature": opts.get("temperature", 0.0),
            "reasoning_effort": GROQ_REASONING_EFFORT,
        }
        if format == "json":
            kwargs["response_format"] = {"type": "json_object"}
        if "num_predict" in opts:
            kwargs["max_completion_tokens"] = opts["num_predict"]
        if opts.get("seed") is not None:
            kwargs["seed"] = opts["seed"]

        resp = self._client.chat.completions.create(**kwargs)
        return {"message": {"content": resp.choices[0].message.content}}


def get_chat_client(timeout_seconds: float):
    """Return the generative chat client for the configured provider.

    `LLM_PROVIDER="groq"` → `GroqChatClient`; anything else (default `"ollama"`) → `ollama.Client`,
    byte-for-byte today's behavior. Read `LLM_PROVIDER` live so tests/deploys can toggle it.
    """
    if LLM_PROVIDER == "groq":
        return GroqChatClient(timeout_seconds)
    return ollama.Client(timeout=timeout_seconds)
