"""
Unit tests for app.graph.nodes.retrievers.embeddings.embed_query.

Mocks ollama.Client — no running Ollama required.
Run: python -m pytest tests/unit/test_embeddings.py -v
"""

import concurrent.futures
from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest

from app.graph.nodes.retrievers.embeddings import embed_query
from app.config import OLLAMA_EMBED_MODEL_NAME, OLLAMA_MODEL_NAME


def _mock_client_returning(embedding: list):
    """Return a mock ollama.Client whose .embeddings() returns the given vector."""
    client = MagicMock()
    client.embeddings.return_value = {"embedding": embedding}
    return client


def test_embed_returns_l2_normalized_vector():
    """Returned vector is L2-normalized (norm ≈ 1.0)."""
    raw = [3.0, 4.0]  # norm = 5.0 → normalized = [0.6, 0.8]
    mock_client = _mock_client_returning(raw)
    with patch(
        "app.graph.nodes.retrievers.embeddings.ollama.Client", return_value=mock_client
    ):
        result = embed_query(
            "test text", timeout_seconds=5, model_name=OLLAMA_EMBED_MODEL_NAME
        )

    assert result is not None
    assert np.linalg.norm(result) == pytest.approx(1.0, abs=1e-6)
    np.testing.assert_allclose(result, [0.6, 0.8], atol=1e-6)


def test_embed_uses_embed_model_not_generative():
    """embed_query calls ollama with OLLAMA_EMBED_MODEL_NAME, not OLLAMA_MODEL_NAME (AC-8)."""
    mock_client = _mock_client_returning([1.0, 0.0])
    with patch(
        "app.graph.nodes.retrievers.embeddings.ollama.Client", return_value=mock_client
    ) as mock_cls:
        embed_query("some text", timeout_seconds=5, model_name=OLLAMA_EMBED_MODEL_NAME)

    # Client constructed with the embed model timeout
    mock_cls.assert_called_once()
    # embeddings called with the right model name
    mock_client.embeddings.assert_called_once()
    call_kwargs = mock_client.embeddings.call_args
    assert (
        call_kwargs.kwargs.get("model") == OLLAMA_EMBED_MODEL_NAME
        or call_kwargs.args[0] == OLLAMA_EMBED_MODEL_NAME
        or ("model" in str(call_kwargs) and OLLAMA_EMBED_MODEL_NAME in str(call_kwargs))
    )
    # The generative model name must NOT appear
    assert OLLAMA_MODEL_NAME not in str(mock_client.embeddings.call_args)


def test_embed_timeout_returns_none(caplog):
    """Simulated timeout → None, warning logged."""
    mock_client = MagicMock()
    mock_client.embeddings.side_effect = concurrent.futures.TimeoutError("timed out")

    with patch(
        "app.graph.nodes.retrievers.embeddings.ollama.Client", return_value=mock_client
    ):
        with caplog.at_level("WARNING"):
            result = embed_query(
                "text", timeout_seconds=1, model_name=OLLAMA_EMBED_MODEL_NAME
            )

    assert result is None
    assert any("warn" in r.levelname.lower() or r.levelno >= 30 for r in caplog.records)


def test_embed_connection_error_returns_none(caplog):
    """Ollama unreachable → None."""
    mock_client = MagicMock()
    mock_client.embeddings.side_effect = httpx.ConnectError("connection refused")

    with patch(
        "app.graph.nodes.retrievers.embeddings.ollama.Client", return_value=mock_client
    ):
        with caplog.at_level("WARNING"):
            result = embed_query(
                "text", timeout_seconds=5, model_name=OLLAMA_EMBED_MODEL_NAME
            )

    assert result is None


def test_embed_zero_norm_returns_none(caplog):
    """Zero-norm embedding → None (zero-norm guard)."""
    mock_client = _mock_client_returning([0.0, 0.0, 0.0])

    with patch(
        "app.graph.nodes.retrievers.embeddings.ollama.Client", return_value=mock_client
    ):
        with caplog.at_level("WARNING"):
            result = embed_query(
                "text", timeout_seconds=5, model_name=OLLAMA_EMBED_MODEL_NAME
            )

    assert result is None


def test_embed_malformed_response_returns_none(caplog):
    """Response missing 'embedding' key → None."""
    mock_client = MagicMock()
    mock_client.embeddings.return_value = {"something_else": [1.0, 2.0]}

    with patch(
        "app.graph.nodes.retrievers.embeddings.ollama.Client", return_value=mock_client
    ):
        with caplog.at_level("WARNING"):
            result = embed_query(
                "text", timeout_seconds=5, model_name=OLLAMA_EMBED_MODEL_NAME
            )

    assert result is None
