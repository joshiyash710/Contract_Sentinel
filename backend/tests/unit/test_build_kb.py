"""Unit tests for scripts/build_kb.py — feature-050 embedding-seam wire-in + provenance marker.

Loads build_kb by file path (scripts is not a package) and mocks the embedding seam — no Ollama / no
network. Covers AC-5 (offline site routes through get_embed_client, embed-model-not-generative), AC-8
(a wrong-shape adapter error propagates loudly), and the D3 provenance marker.
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

_BK_PATH = Path(__file__).resolve().parents[2] / "scripts" / "build_kb.py"
_spec = importlib.util.spec_from_file_location("build_kb", _BK_PATH)
build_kb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_kb)


def _seam_returning(embedding):
    client = MagicMock()
    client.embeddings.return_value = {"embedding": embedding}
    return MagicMock(return_value=client), client


# ── AC-5: offline site routes through get_embed_client; embed model, not generative ──
def test_embed_routes_through_seam_and_normalizes(monkeypatch):
    get_client, client = _seam_returning([3.0, 4.0])  # norm 5 → [0.6, 0.8]
    monkeypatch.setattr(build_kb, "get_embed_client", get_client)

    vec = build_kb._embed("clause text")

    assert np.linalg.norm(vec) == pytest.approx(1.0, abs=1e-6)
    np.testing.assert_allclose(vec, [0.6, 0.8], atol=1e-6)
    call = str(client.embeddings.call_args)
    assert build_kb.config.OLLAMA_EMBED_MODEL_NAME in call
    assert build_kb.config.OLLAMA_MODEL_NAME not in call


# ── AC-8: a deterministic adapter shape error propagates (loud offline failure) ──
def test_embed_propagates_adapter_shape_error(monkeypatch):
    client = MagicMock()
    client.embeddings.side_effect = ValueError("unexpected HF embedding shape (dim=1025)")
    monkeypatch.setattr(build_kb, "get_embed_client", MagicMock(return_value=client))

    with pytest.raises(ValueError):
        build_kb._embed("clause text")


# ── D3: provenance marker reflects the active provider/model ──
def test_provider_marker_hf(monkeypatch):
    monkeypatch.setattr(build_kb.config, "EMBED_PROVIDER", "hf")
    monkeypatch.setattr(build_kb.config, "HF_EMBED_MODEL", "BAAI/bge-m3")
    assert json.loads(build_kb._provider_marker()) == {"provider": "hf", "model": "BAAI/bge-m3"}


def test_provider_marker_ollama(monkeypatch):
    monkeypatch.setattr(build_kb.config, "EMBED_PROVIDER", "ollama")
    marker = json.loads(build_kb._provider_marker())
    assert marker == {"provider": "ollama", "model": build_kb.config.OLLAMA_EMBED_MODEL_NAME}
