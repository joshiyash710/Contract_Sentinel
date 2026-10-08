"""Unit tests for the feature-050 embedding provider seam (app/llm/embed_client.py).

HuggingFace HTTP (httpx) is MOCKED — no network. Covers AC-1 (factory dispatch), AC-2 (return shape +
request shape), AC-3 (model override + HF path is embedding-only, §8), AC-4 (adapter raises on
transport/status/shape failure; only transport is retried), AC-6 (missing-token error + token never
logged), AC-8 (dimension parity guard).
"""

from unittest.mock import MagicMock

import httpx
import pytest

import app.llm.embed_client as embed_client
from app.llm.embed_client import get_embed_client, HFEmbedClient, CloudflareEmbedClient

DIM = 1024


class _FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("POST", "http://test")
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=req,
                response=httpx.Response(self.status_code, request=req),
            )


def _patch_hf(monkeypatch, token="hf_teststub", provider="hf", retries=2):
    monkeypatch.setattr(embed_client, "EMBED_PROVIDER", provider)
    monkeypatch.setattr(embed_client, "HF_API_TOKEN", token)
    monkeypatch.setattr(embed_client, "HF_EMBED_MODEL", "BAAI/bge-m3")
    monkeypatch.setattr(embed_client, "HF_EMBED_MAX_RETRIES", retries)
    monkeypatch.setattr(embed_client, "EMBED_DIM", DIM)
    monkeypatch.setattr(embed_client.time, "sleep", lambda *_: None)  # no real backoff sleeps


# ── AC-1: factory dispatch ───────────────────────────────────────────────────
def test_factory_returns_ollama_client_by_default(monkeypatch):
    import ollama
    monkeypatch.setattr(embed_client, "EMBED_PROVIDER", "ollama")
    assert isinstance(get_embed_client(30), ollama.Client)


def test_factory_returns_hf_client_when_configured(monkeypatch):
    _patch_hf(monkeypatch)
    assert isinstance(get_embed_client(30), HFEmbedClient)


# ── AC-2: return shape + request shape ───────────────────────────────────────
def test_hf_embeddings_returns_ollama_shape_and_posts_correctly(monkeypatch):
    _patch_hf(monkeypatch)
    vec = [0.01] * DIM
    post = MagicMock(return_value=_FakeResp(200, vec))
    monkeypatch.setattr(embed_client.httpx, "post", post)

    out = HFEmbedClient(45).embeddings(model="bge-m3", prompt="the clause text")

    assert out == {"embedding": vec}
    url = post.call_args.args[0] if post.call_args.args else post.call_args.kwargs["url"]
    assert "BAAI/bge-m3" in url and url.endswith("/pipeline/feature-extraction")
    assert post.call_args.kwargs["json"] == {"inputs": "the clause text"}
    assert post.call_args.kwargs["timeout"] == 45.0


# ── AC-3: model override + HF path only ever serves the embedding model (§8) ──
def test_hf_ignores_passed_model_uses_embed_model(monkeypatch):
    _patch_hf(monkeypatch)
    post = MagicMock(return_value=_FakeResp(200, [0.01] * DIM))
    monkeypatch.setattr(embed_client.httpx, "post", post)
    # Even if a caller passes a generative model name, the URL targets HF_EMBED_MODEL only.
    HFEmbedClient(30).embeddings(model="qwen3:8b", prompt="x")
    url = post.call_args.args[0] if post.call_args.args else post.call_args.kwargs["url"]
    assert "BAAI/bge-m3" in url
    assert "qwen3" not in url


# ── AC-4: failure modes raise out of the adapter; only transport is retried ───
def test_transport_error_retried_then_raised(monkeypatch):
    _patch_hf(monkeypatch, retries=2)
    post = MagicMock(side_effect=httpx.ConnectError("boom"))
    monkeypatch.setattr(embed_client.httpx, "post", post)
    with pytest.raises(httpx.RequestError):
        HFEmbedClient(30).embeddings(prompt="x")
    assert post.call_count == 3  # initial + 2 retries


def test_persistent_503_retried_then_raises_status(monkeypatch):
    _patch_hf(monkeypatch, retries=2)
    post = MagicMock(return_value=_FakeResp(503, None))
    monkeypatch.setattr(embed_client.httpx, "post", post)
    with pytest.raises(httpx.HTTPStatusError):
        HFEmbedClient(30).embeddings(prompt="x")
    assert post.call_count == 3  # 503 retried to exhaustion, then raise_for_status raises


def test_non_retriable_status_raises_immediately(monkeypatch):
    _patch_hf(monkeypatch, retries=2)
    post = MagicMock(return_value=_FakeResp(400, None))
    monkeypatch.setattr(embed_client.httpx, "post", post)
    with pytest.raises(httpx.HTTPStatusError):
        HFEmbedClient(30).embeddings(prompt="x")
    assert post.call_count == 1  # 400 is not retried


def test_wrong_shape_raises_immediately(monkeypatch):
    _patch_hf(monkeypatch, retries=2)
    post = MagicMock(return_value=_FakeResp(200, [[0.1] * DIM]))  # nested (per-token) matrix
    monkeypatch.setattr(embed_client.httpx, "post", post)
    with pytest.raises(ValueError):
        HFEmbedClient(30).embeddings(prompt="x")
    assert post.call_count == 1  # deterministic shape error not retried


# ── AC-8: dimension parity guard ─────────────────────────────────────────────
def test_correct_dim_passes_wrong_dim_rejected(monkeypatch):
    _patch_hf(monkeypatch)
    good = MagicMock(return_value=_FakeResp(200, [0.0] * DIM))
    monkeypatch.setattr(embed_client.httpx, "post", good)
    assert len(HFEmbedClient(30).embeddings(prompt="x")["embedding"]) == DIM

    bad = MagicMock(return_value=_FakeResp(200, [0.0] * (DIM + 1)))
    monkeypatch.setattr(embed_client.httpx, "post", bad)
    with pytest.raises(ValueError):
        HFEmbedClient(30).embeddings(prompt="x")


# ── AC-6: missing token error + token never logged ───────────────────────────
def test_missing_token_raises_without_leaking(monkeypatch):
    monkeypatch.setattr(embed_client, "HF_API_TOKEN", "")
    with pytest.raises(ValueError) as exc:
        HFEmbedClient(30)
    assert "HF_API_TOKEN" in str(exc.value)  # names the missing var
    assert "hf_" not in str(exc.value)  # never echoes token material


def test_token_never_logged(monkeypatch, caplog):
    secret = "hf_supersecret_value_1234567890"
    _patch_hf(monkeypatch, token=secret)
    monkeypatch.setattr(embed_client.httpx, "post", MagicMock(return_value=_FakeResp(200, [0.0] * DIM)))
    with caplog.at_level("DEBUG"):
        HFEmbedClient(30).embeddings(prompt="x")
    assert secret not in caplog.text


# ── Feature 062: Cloudflare Workers AI embedding provider ─────────────────────
def _cf_body(vec):
    """The Workers AI feature-extraction response shape (probed): result.data is a list-of-vectors."""
    return {"result": {"shape": [1, len(vec)], "data": [vec]}, "success": True, "errors": [], "messages": []}


def _patch_cf(monkeypatch, account="acct123", token="cf_teststub", retries=2):
    monkeypatch.setattr(embed_client, "EMBED_PROVIDER", "cloudflare")
    monkeypatch.setattr(embed_client, "CF_ACCOUNT_ID", account)
    monkeypatch.setattr(embed_client, "CF_API_TOKEN", token)
    monkeypatch.setattr(embed_client, "CF_EMBED_MODEL", "@cf/baai/bge-m3")
    monkeypatch.setattr(embed_client, "CF_EMBED_MAX_RETRIES", retries)
    monkeypatch.setattr(embed_client, "EMBED_DIM", DIM)
    monkeypatch.setattr(embed_client.time, "sleep", lambda *_: None)


def test_factory_returns_cloudflare_client_when_configured(monkeypatch):  # AC-1
    _patch_cf(monkeypatch)
    assert isinstance(get_embed_client(30), CloudflareEmbedClient)


def test_cf_embeddings_returns_ollama_shape_and_posts_correctly(monkeypatch):  # AC-2/AC-3
    _patch_cf(monkeypatch)
    vec = [0.02] * DIM
    post = MagicMock(return_value=_FakeResp(200, _cf_body(vec)))
    monkeypatch.setattr(embed_client.httpx, "post", post)

    out = CloudflareEmbedClient(45).embeddings(model="bge-m3", prompt="the clause text")

    assert out == {"embedding": vec}
    url = post.call_args.args[0] if post.call_args.args else post.call_args.kwargs["url"]
    assert "acct123" in url and "@cf/baai/bge-m3" in url
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer cf_teststub"
    assert post.call_args.kwargs["json"] == {"text": "the clause text"}
    assert post.call_args.kwargs["timeout"] == 45.0


def test_cf_ignores_passed_model(monkeypatch):  # §8 — embedding model only
    _patch_cf(monkeypatch)
    post = MagicMock(return_value=_FakeResp(200, _cf_body([0.01] * DIM)))
    monkeypatch.setattr(embed_client.httpx, "post", post)
    CloudflareEmbedClient(30).embeddings(model="qwen3:8b", prompt="x")
    url = post.call_args.args[0] if post.call_args.args else post.call_args.kwargs["url"]
    assert "@cf/baai/bge-m3" in url and "qwen3" not in url


def test_cf_transport_error_retried_then_raised(monkeypatch):  # AC-5 — only transport retries
    _patch_cf(monkeypatch, retries=2)
    post = MagicMock(side_effect=httpx.ConnectError("boom"))
    monkeypatch.setattr(embed_client.httpx, "post", post)
    with pytest.raises(httpx.RequestError):
        CloudflareEmbedClient(30).embeddings(prompt="x")
    assert post.call_count == 3  # initial + 2 retries


@pytest.mark.parametrize("status", [401, 402, 429, 500, 503])
def test_cf_non2xx_raises_immediately(monkeypatch, status):  # AC-5 — non-2xx NOT retried (unlike HF 503)
    _patch_cf(monkeypatch, retries=2)
    post = MagicMock(return_value=_FakeResp(status, None))
    monkeypatch.setattr(embed_client.httpx, "post", post)
    with pytest.raises(httpx.HTTPStatusError):
        CloudflareEmbedClient(30).embeddings(prompt="x")
    assert post.call_count == 1


def test_cf_wrong_shape_raises(monkeypatch):  # AC-5
    _patch_cf(monkeypatch)
    post = MagicMock(return_value=_FakeResp(200, {"success": True}))  # no result.data
    monkeypatch.setattr(embed_client.httpx, "post", post)
    with pytest.raises(ValueError):
        CloudflareEmbedClient(30).embeddings(prompt="x")


def test_cf_dim_mismatch_rejected(monkeypatch):  # AC-5 / dimension parity
    _patch_cf(monkeypatch)
    post = MagicMock(return_value=_FakeResp(200, _cf_body([0.0] * (DIM + 1))))
    monkeypatch.setattr(embed_client.httpx, "post", post)
    with pytest.raises(ValueError):
        CloudflareEmbedClient(30).embeddings(prompt="x")


def test_cf_missing_creds_raises_without_leaking(monkeypatch):  # AC-4
    monkeypatch.setattr(embed_client, "CF_ACCOUNT_ID", "acct")
    monkeypatch.setattr(embed_client, "CF_API_TOKEN", "")
    with pytest.raises(ValueError) as exc:
        CloudflareEmbedClient(30)
    assert "CF_API_TOKEN" in str(exc.value) or "CF_ACCOUNT_ID" in str(exc.value)
    assert "cf_" not in str(exc.value)  # never echoes token material


def test_cf_token_never_logged(monkeypatch, caplog):  # AC-4
    secret = "cf_supersecret_value_1234567890"
    _patch_cf(monkeypatch, token=secret)
    monkeypatch.setattr(embed_client.httpx, "post", MagicMock(return_value=_FakeResp(200, _cf_body([0.0] * DIM))))
    with caplog.at_level("DEBUG"):
        CloudflareEmbedClient(30).embeddings(prompt="x")
    assert secret not in caplog.text
