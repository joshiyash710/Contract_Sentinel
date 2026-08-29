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

# HF probe (2026-08-29): the router domain + explicit /pipeline/feature-extraction path returns a single
# pooled EMBED_DIM-float vector. The legacy api-inference.huggingface.co host no longer resolves, and the
# bare model path routes to a SentenceSimilarity pipeline (400). Do NOT change this URL shape without
# re-probing (see specs/050-embedding-provider/plan.md §2).
_HF_URL = "https://router.huggingface.co/hf-inference/models/{model}/pipeline/feature-extraction"


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


def get_embed_client(timeout_seconds: float):
    """Return the embedding client for the configured provider (EMBED_PROVIDER read live).

    `"hf"` → `HFEmbedClient`; anything else (default `"ollama"`) → `ollama.Client`, byte-for-byte
    today's behavior.
    """
    if EMBED_PROVIDER == "hf":
        return HFEmbedClient(timeout_seconds)
    return ollama.Client(timeout=timeout_seconds)
