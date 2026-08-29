"""
Unit tests for app.graph.nodes.retrievers.embeddings.embed_query.

Mocks the feature-050 embedding seam (`embeddings.get_embed_client`) — no running Ollama / no network.
The client construction moved to app/llm/embed_client.py (feature 050), so these tests patch
`get_embed_client` (returning a mock client) instead of `ollama.Client`; the normalization / model /
failure→None assertions are unchanged (constitution §7 — updated for the moved seam, not weakened).
Run: python -m pytest tests/unit/test_embeddings.py -v
"""

import concurrent.futures
from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest

from app.graph.nodes.retrievers.embeddings import embed_query
from app.config import OLLAMA_EMBED_MODEL_NAME, OLLAMA_MODEL_NAME

_SEAM = "app.graph.nodes.retrievers.embeddings.get_embed_client"


def _mock_client_returning(embedding: list):
    """Return a mock embedding client whose .embeddings() returns the given vector."""
    client = MagicMock()
    client.embeddings.return_value = {"embedding": embedding}
    return client


def test_embed_returns_l2_normalized_vector():
    """Returned vector is L2-normalized (norm ≈ 1.0)."""
    raw = [3.0, 4.0]  # norm = 5.0 → normalized = [0.6, 0.8]
    mock_client = _mock_client_returning(raw)
    with patch(_SEAM, return_value=mock_client):
        result = embed_query(
            "test text", timeout_seconds=5, model_name=OLLAMA_EMBED_MODEL_NAME
        )

    assert result is not None
    assert np.linalg.norm(result) == pytest.approx(1.0, abs=1e-6)
    np.testing.assert_allclose(result, [0.6, 0.8], atol=1e-6)


def test_embed_routes_through_seam_with_timeout():
    """AC-5: embed_query routes through get_embed_client with the passed timeout (provider seam)."""
    mock_client = _mock_client_returning([1.0, 0.0])
    with patch(_SEAM, return_value=mock_client) as mock_get:
        embed_query("some text", timeout_seconds=7, model_name=OLLAMA_EMBED_MODEL_NAME)
    mock_get.assert_called_once_with(7)


def test_embed_uses_embed_model_not_generative():
    """embed_query calls the client with OLLAMA_EMBED_MODEL_NAME, not OLLAMA_MODEL_NAME (§8)."""
    mock_client = _mock_client_returning([1.0, 0.0])
    with patch(_SEAM, return_value=mock_client):
        embed_query("some text", timeout_seconds=5, model_name=OLLAMA_EMBED_MODEL_NAME)

    mock_client.embeddings.assert_called_once()
    call = mock_client.embeddings.call_args
    assert (
        call.kwargs.get("model") == OLLAMA_EMBED_MODEL_NAME
        or (call.args and call.args[0] == OLLAMA_EMBED_MODEL_NAME)
        or ("model" in str(call) and OLLAMA_EMBED_MODEL_NAME in str(call))
    )
    # The generative model name must NOT appear
    assert OLLAMA_MODEL_NAME not in str(mock_client.embeddings.call_args)


def test_embed_timeout_returns_none(caplog):
    """Simulated timeout → None, warning logged."""
    mock_client = MagicMock()
    mock_client.embeddings.side_effect = concurrent.futures.TimeoutError("timed out")

    with patch(_SEAM, return_value=mock_client):
        with caplog.at_level("WARNING"):
            result = embed_query(
                "text", timeout_seconds=1, model_name=OLLAMA_EMBED_MODEL_NAME
            )

    assert result is None
    assert any("warn" in r.levelname.lower() or r.levelno >= 30 for r in caplog.records)


def test_embed_connection_error_returns_none(caplog):
    """Backend unreachable (Ollama or HF transport error) → None."""
    mock_client = MagicMock()
    mock_client.embeddings.side_effect = httpx.ConnectError("connection refused")

    with patch(_SEAM, return_value=mock_client):
        with caplog.at_level("WARNING"):
            result = embed_query(
                "text", timeout_seconds=5, model_name=OLLAMA_EMBED_MODEL_NAME
            )

    assert result is None


def test_embed_hf_shape_error_returns_none(caplog):
    """AC-4: an HF adapter ValueError (wrong shape) → None (feeds the CRAG circuit breaker)."""
    mock_client = MagicMock()
    mock_client.embeddings.side_effect = ValueError("unexpected HF embedding shape (dim=1025)")

    with patch(_SEAM, return_value=mock_client):
        with caplog.at_level("WARNING"):
            result = embed_query(
                "text", timeout_seconds=5, model_name=OLLAMA_EMBED_MODEL_NAME
            )

    assert result is None


def test_embed_zero_norm_returns_none(caplog):
    """Zero-norm embedding → None (zero-norm guard)."""
    mock_client = _mock_client_returning([0.0, 0.0, 0.0])

    with patch(_SEAM, return_value=mock_client):
        with caplog.at_level("WARNING"):
            result = embed_query(
                "text", timeout_seconds=5, model_name=OLLAMA_EMBED_MODEL_NAME
            )

    assert result is None


def test_embed_malformed_response_returns_none(caplog):
    """Response missing 'embedding' key → None."""
    mock_client = MagicMock()
    mock_client.embeddings.return_value = {"something_else": [1.0, 2.0]}

    with patch(_SEAM, return_value=mock_client):
        with caplog.at_level("WARNING"):
            result = embed_query(
                "text", timeout_seconds=5, model_name=OLLAMA_EMBED_MODEL_NAME
            )

    assert result is None
