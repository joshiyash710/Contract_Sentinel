"""Embedding provider seam (feature 050).

`get_embed_client(timeout_seconds)` returns either today's `ollama.Client` (default) or an
`HFEmbedClient` that mimics `ollama.Client.embeddings(model, prompt) -> {"embedding": [...]}`, backed by
the HuggingFace Inference API — so the two `bge-m3` call sites (CRAG query embedding + the offline KB
index build) swap ONE line each.

This is the EMBEDDING seam, entirely separate from the generation seam (feature 046,
`app/llm/chat_client.py`). The HF path serves ONLY the `bge-m3` embedding model, never a generative
model (constitution §8). `HF_API_TOKEN` is read from config (env/.env) and is NEVER logged.

Switching `EMBED_PROVIDER` REQUIRES rebuilding `data/kb/clauses.faiss` through the same provider — the
indexed and query vectors must come from the same embedding model or cosine similarity is meaningless
(spec §1 invariant). L2-normalization stays in the call sites (this adapter returns RAW vectors).
"""

import time

import httpx
import ollama

import app.config as _config

# Bare module-level names (read at call time) so tests can monkeypatch them, mirroring chat_client.py.
EMBED_PROVIDER = _config.EMBED_PROVIDER
HF_API_TOKEN = _config.HF_API_TOKEN
HF_EMBED_MODEL = _config.HF_EMBED_MODEL
HF_EMBED_MAX_RETRIES = _config.HF_EMBED_MAX_RETRIES
EMBED_DIM = _config.EMBED_DIM
# Feature 062 — Cloudflare Workers AI (read at call time; monkeypatchable). NEVER log CF_API_TOKEN.
CF_ACCOUNT_ID = _config.CF_ACCOUNT_ID
CF_API_TOKEN = _config.CF_API_TOKEN
CF_EMBED_MODEL = _config.CF_EMBED_MODEL
CF_EMBED_MAX_RETRIES = _config.CF_EMBED_MAX_RETRIES

# HF probe (2026-08-29): the router domain + explicit /pipeline/feature-extraction path returns a single
# pooled EMBED_DIM-float vector. The legacy api-inference.huggingface.co host no longer resolves, and the
# bare model path routes to a SentenceSimilarity pipeline (400). Do NOT change this URL shape without
# re-probing (see specs/050-embedding-provider/plan.md §2).
_HF_URL = "https://router.huggingface.co/hf-inference/models/{model}/pipeline/feature-extraction"

# Feature 062 — Cloudflare Workers AI run endpoint for the embedding model.
_CF_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"


def _backoff(attempt: int) -> float:
    return min(2.0 ** attempt, 8.0)  # 1s, 2s, 4s… bounded (D5)


def _dim(vec) -> object:
    """Token-free shape descriptor for error messages (never echoes the token)."""
    return len(vec) if isinstance(vec, list) else type(vec).__name__


class HFEmbedClient:
    """Mimics ollama.Client for the `.embeddings(model, prompt)` call the two sites make."""

    def __init__(self, timeout_seconds: float):
        if not HF_API_TOKEN:
            # The token is empty here; the message must never echo any token material.
            raise ValueError(
                "EMBED_PROVIDER=hf but HF_API_TOKEN is empty. Set it in backend/.env "
                "(see docs/DEPLOYMENT.md). The token value is intentionally not shown."
            )
        self._timeout = float(timeout_seconds)
        self._url = _HF_URL.format(model=HF_EMBED_MODEL)  # HF_EMBED_MODEL wins; embedding model only
        self._headers = {
            "Authorization": f"Bearer {HF_API_TOKEN}",
            "Content-Type": "application/json",
        }

    def embeddings(self, model=None, prompt=""):
        """Ignore `model` (HF_EMBED_MODEL wins); return {"embedding": <raw EMBED_DIM-float list>}.

        Only transport errors (httpx.RequestError: timeout/connection/transport) are retried; a
        non-retriable HTTP status (raise_for_status) and a wrong-shape 200 body (ValueError) raise
        immediately — retrying a deterministic failure cannot help. Any terminal error propagates to the
        caller, whose existing handling turns it into None (runtime) / a loud failure (offline build).
        """
        last_exc = None
        for attempt in range(HF_EMBED_MAX_RETRIES + 1):
            try:
                r = httpx.post(
                    self._url, headers=self._headers,
                    json={"inputs": prompt}, timeout=self._timeout,
                )
            except httpx.RequestError as exc:  # retriable transport failure
                last_exc = exc
                if attempt < HF_EMBED_MAX_RETRIES:
                    time.sleep(_backoff(attempt))
                    continue
                raise
            if r.status_code in (503, 429) and attempt < HF_EMBED_MAX_RETRIES:
                time.sleep(_backoff(attempt))  # cold-start / rate-limit (EC-1/EC-2)
                continue
            r.raise_for_status()  # other 4xx/5xx → HTTPStatusError (not RequestError) → propagates
            vec = r.json()
            if (not isinstance(vec, list) or len(vec) != EMBED_DIM
                    or (vec and isinstance(vec[0], list))):
                raise ValueError(f"unexpected HF embedding shape (dim={_dim(vec)})")  # no token
            return {"embedding": vec}  # RAW; caller L2-normalizes (idempotent — HF vector is unit-norm)
        raise last_exc  # retries exhausted on a transport error


def _cf_extract_vector(body):
    """Normalize the Workers AI feature-extraction response to a flat float list (feature 062).

    Probed shape (@cf/baai/bge-m3, confirmed 2026-10-09): {"result": {"data": [[...1024 floats...]], "shape":
    [1, 1024], "meta": …, "pooling": …}, "success": true, "errors": []} → vector = result.data[0].
    Defensive: result.data as a list-of-lists → take [0]; as a flat float list → as-is; else fall back to a
    top-level `data`. Any other shape raises ValueError (the adapter's caller turns it into None/a loud
    failure). Never echoes the token (no secrets are in the body)."""
    if not isinstance(body, dict):
        raise ValueError("unexpected Cloudflare response (not an object)")
    data = (body.get("result") or {}).get("data")
    if data is None:
        data = body.get("data")
    if isinstance(data, list) and data:
        if isinstance(data[0], list):
            return data[0]
        if isinstance(data[0], (int, float)):
            return data
    raise ValueError("unexpected Cloudflare response shape (no embedding vector)")


class CloudflareEmbedClient:
    """Mimics ollama.Client's `.embeddings(model, prompt) -> {"embedding": [...]}`, backed by Cloudflare
    Workers AI (`@cf/baai/bge-m3`) — a free, card-free embedding path (feature 062). Serves ONLY the bge-m3
    embedding model, never a generative one (§8). Retries ONLY transport errors (`httpx.RequestError`); every
    non-2xx (401/402/429/5xx) is a deterministic verdict → raise immediately (unlike `HFEmbedClient`, which
    retries 503/429 cold-starts). `CF_API_TOKEN` is NEVER echoed in an error or log."""

    def __init__(self, timeout_seconds: float):
        if not CF_ACCOUNT_ID or not CF_API_TOKEN:
            raise ValueError(
                "EMBED_PROVIDER=cloudflare but CF_ACCOUNT_ID or CF_API_TOKEN is empty. Set them in "
                "backend/.env (see docs/DEPLOYMENT.md). The token value is intentionally not shown."
            )
        self._timeout = float(timeout_seconds)
        self._url = _CF_URL.format(account_id=CF_ACCOUNT_ID, model=CF_EMBED_MODEL)
        self._headers = {
            "Authorization": f"Bearer {CF_API_TOKEN}",
            "Content-Type": "application/json",
        }

    def embeddings(self, model=None, prompt=""):
        """Ignore `model` (CF_EMBED_MODEL wins); return {"embedding": <raw EMBED_DIM-float list>}.

        Only transport errors are retried; a non-2xx status (raise_for_status) and a wrong-shape/wrong-dim
        200 body raise immediately — retrying a deterministic failure cannot help."""
        last_exc = None
        for attempt in range(CF_EMBED_MAX_RETRIES + 1):
            try:
                r = httpx.post(
                    self._url, headers=self._headers,
                    json={"text": prompt}, timeout=self._timeout,
                )
            except httpx.RequestError as exc:  # retriable transport failure
                last_exc = exc
                if attempt < CF_EMBED_MAX_RETRIES:
                    time.sleep(_backoff(attempt))
                    continue
                raise
            r.raise_for_status()  # any non-2xx (401/402/429/5xx) → HTTPStatusError, NOT retried
            vec = _cf_extract_vector(r.json())
            if (not isinstance(vec, list) or len(vec) != EMBED_DIM
                    or (vec and isinstance(vec[0], list))):
                raise ValueError(f"unexpected Cloudflare embedding shape (dim={_dim(vec)})")  # no token
            return {"embedding": vec}  # RAW; caller L2-normalizes
        raise last_exc  # retries exhausted on a transport error


def get_embed_client(timeout_seconds: float):
    """Return the embedding client for the configured provider (EMBED_PROVIDER read live).

    `"hf"` → `HFEmbedClient`; `"cloudflare"` → `CloudflareEmbedClient`; anything else (default `"ollama"`) →
    `ollama.Client`, byte-for-byte today's behavior.
    """
    if EMBED_PROVIDER == "hf":
        return HFEmbedClient(timeout_seconds)
    if EMBED_PROVIDER == "cloudflare":
        return CloudflareEmbedClient(timeout_seconds)
    return ollama.Client(timeout=timeout_seconds)
