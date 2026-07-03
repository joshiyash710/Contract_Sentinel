"""
Query embedding for CRAG retrieval (Node 3).

embed_query() is the single entry point: it embeds clause text with BGE-M3
via Ollama and L2-normalizes the result so inner-product == cosine against the
FAISS index built by scripts/build_kb.py.

Design notes (plan §2 / spec §7.1):
  - ollama.Client(timeout=timeout_seconds) is the PRIMARY timeout bound, not the
    executor. A bare ollama.embeddings() call with only future.result(timeout=…)
    would leave the worker thread blocked in the HTTP read if Ollama hangs,
    causing shutdown(wait=True) to block indefinitely and defeating the circuit
    breaker (spec Edge Case 13, plan Risk row 1).
  - The ThreadPoolExecutor + future.result(timeout=…) is a backstop only.
  - BGE-M3 raw output norm ≈ 25.7 (not self-normalized), so L2-normalization
    here is load-bearing, not cosmetic (plan §5 "Normalization on both sides").
"""

import concurrent.futures
import logging
from typing import Optional

import httpx
import numpy as np
import ollama

logger = logging.getLogger("contractsentinel.crag_retrieval.embeddings")


def embed_query(
    text: str, timeout_seconds: int, model_name: str
) -> Optional[np.ndarray]:
    """Embed clause/query text with BGE-M3 via Ollama and L2-normalize it.

    Returns a float32 unit vector (L2-normalized so inner product == cosine),
    or None on ANY failure. Never raises.
    """
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_call_embed, text, model_name, timeout_seconds)
            try:
                # +5s over the Client timeout: the Client(timeout=…) is the
                # primary abort mechanism (plan §2); this future.result timeout
                # is a backstop so the executor never blocks indefinitely if the
                # Client timeout somehow fails to fire.
                return future.result(timeout=timeout_seconds + 5)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "embed_query: future.result timed out for model=%s (backstop hit)",
                    model_name,
                )
                return None
    except Exception as exc:
        logger.warning("embed_query: unexpected executor error: %s", exc)
        return None


def _call_embed(
    text: str, model_name: str, timeout_seconds: int
) -> Optional[np.ndarray]:
    """Submit one embedding call via a timed Client and return a normalized vector.

    Returns None on any failure so the caller treats it as un-scorable.
    """
    try:
        client = ollama.Client(timeout=timeout_seconds)
        resp = client.embeddings(model=model_name, prompt=text)
        # Support both old Ollama client (returns plain dict) and new client
        # (returns EmbeddingsResponse Pydantic model with .embedding attribute).
        if isinstance(resp, dict):
            raw = resp.get("embedding")
        else:
            raw = getattr(resp, "embedding", None)
        if raw is None:
            logger.warning(
                "embed_query: response missing 'embedding' key for model=%s", model_name
            )
            return None
        vec = np.asarray(raw, dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        if norm < 1e-12:
            logger.warning(
                "embed_query: zero-norm vector returned by model=%s", model_name
            )
            return None
        return vec / norm
    except (concurrent.futures.TimeoutError, httpx.TimeoutException) as exc:
        logger.warning("embed_query: timeout calling model=%s: %s", model_name, exc)
        return None
    except Exception as exc:
        logger.warning("embed_query: failed calling model=%s: %s", model_name, exc)
        return None
