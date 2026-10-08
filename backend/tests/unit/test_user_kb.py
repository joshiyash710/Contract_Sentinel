"""Feature 061 — per-user learned KB helper (user_kb.py). AC-2/AC-4/AC-7/AC-8, EC-8.

No Ollama: embed_query is mocked to deterministic unit vectors. CRAG_USER_KB_DIR is pointed at tmp_path and
the module caches are reset per test so nothing leaks between tests.
"""

import threading

import numpy as np
import pytest

import app.rag.user_kb as user_kb


def _unit(i: int, dim: int = 8) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[i % dim] = 1.0
    return v  # already L2-normalized


@pytest.fixture
def kbdir(tmp_path, monkeypatch):
    monkeypatch.setattr(user_kb._config, "CRAG_USER_KB_DIR", str(tmp_path))
    monkeypatch.setattr(user_kb, "_USER_KB_CACHE", {})
    monkeypatch.setattr(user_kb, "_USER_KB_LOCKS", {})

    # deterministic embedder: a distinct unit vector per unique text
    seen: dict = {}

    def fake_embed(text, timeout, model):
        if text == "__none__":
            return None
        idx = seen.setdefault(text, len(seen))
        return _unit(idx)

    monkeypatch.setattr(user_kb, "embed_query", fake_embed)
    return tmp_path


def test_append_creates_accumulates_and_marks_provider(kbdir):
    n = user_kb.append_clauses(
        "u1",
        [{"text": "alpha", "source_reference": "ref A"},
         {"text": "beta", "source_reference": "ref B"}],
    )
    assert n == 2
    kb = user_kb.load_user_kb("u1")
    assert kb is not None
    assert kb.index.ntotal == 2
    assert len(kb.meta) == 2
    assert kb.meta[0] == {"snippet_text": "alpha", "source_reference": "ref A"}

    index_path, _meta_path, marker_path = user_kb._user_paths("u1")
    assert marker_path.exists()  # AC-8: 050 provider marker written on create

    # second append accumulates (and the cache was invalidated so load sees the new count — AC-7)
    user_kb.append_clauses("u1", [{"text": "gamma", "source_reference": "ref C"}])
    assert user_kb.load_user_kb("u1").index.ntotal == 3


def test_cache_invalidated_after_append(kbdir):
    user_kb.append_clauses("u5", [{"text": "a", "source_reference": "r"}])
    assert user_kb.load_user_kb("u5").index.ntotal == 1  # populates cache
    user_kb.append_clauses("u5", [{"text": "b", "source_reference": "r"}])
    assert user_kb.load_user_kb("u5").index.ntotal == 2  # AC-7: cache was invalidated


@pytest.mark.parametrize("bad", ["../evil", "a/b", "a\\b", "..", ""])
def test_slug_rejects_path_escape(kbdir, bad):
    with pytest.raises(ValueError):
        user_kb.append_clauses(bad, [{"text": "x", "source_reference": "r"}])
    with pytest.raises(ValueError):
        user_kb.load_user_kb(bad)


def test_embed_none_item_is_skipped(kbdir):
    n = user_kb.append_clauses(
        "u2",
        [{"text": "good", "source_reference": "r"},
         {"text": "__none__", "source_reference": "r2"}],
    )
    assert n == 1  # the un-embeddable item is skipped, no vector/row desync
    kb = user_kb.load_user_kb("u2")
    assert kb.index.ntotal == 1
    assert kb.meta[0]["snippet_text"] == "good"


def test_corrupt_index_returns_none(kbdir, monkeypatch):
    user_kb.append_clauses("u3", [{"text": "a", "source_reference": "r"}])
    index_path, _m, _p = user_kb._user_paths("u3")
    index_path.write_text("garbage not a faiss index", encoding="utf-8")
    monkeypatch.setattr(user_kb, "_USER_KB_CACHE", {})  # force a reload from disk
    assert user_kb.load_user_kb("u3") is None  # EC-8: no raise


def test_concurrent_appends_same_user_no_loss(kbdir):
    def work(i):
        user_kb.append_clauses("u4", [{"text": f"c{i}", "source_reference": f"r{i}"}])

    threads = [threading.Thread(target=work, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    kb = user_kb.load_user_kb("u4")
    assert kb.index.ntotal == 10  # AC-7/EC-5: per-user lock serialized the appends
    assert len(kb.meta) == 10
