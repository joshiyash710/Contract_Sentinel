# CRAG Retrieval Implementation Tasks

Reference documents:
- Spec: `specs/005-crag-retrieval/spec.md`
- Plan: `specs/005-crag-retrieval/plan.md`
- State schema: `specs/001-contract-state-schema.md`
- Tech stack: `specs/002-tech-stack.md`
- Constitution: `specs/000-constitution.md`

All file paths below are relative to `backend/` unless stated otherwise.

**Workflow reminders:**
- Follow TDD per constitution §7 — write tests, confirm they FAIL, then implement to make them PASS.
- Node returns ONLY the state keys it updates per constitution §5 (Partial-Update Rule): `clauses`, `current_node`, `node_timings`. Never `error_count` (spec §2 "Error accounting", AC-12).
- All thresholds live in `app/config.py` per constitution §3 — never hardcode inline.
- Model separation (constitution §8): embedding uses `OLLAMA_EMBED_MODEL_NAME` (bge-m3); it MUST NEVER equal or be used as `OLLAMA_MODEL_NAME` (generative Qwen3).
- Confidence = `max(0.0, top-1 cosine among top-K FAISS neighbors)` — pinned in spec §7.1. Requires L2-normalized vectors on BOTH build and query sides.
- Branch: `feature/005-crag-retrieval` per constitution §11.

---

## Task 0: Create feature branch

- [ ] From an up-to-date `main`, create and check out `feature/005-crag-retrieval`

**Why**: Per constitution §11, every feature is developed on its own branch. ClauseSplitterAgent (004) is already merged to `main`.

**Verify**: `git branch --show-current` prints `feature/005-crag-retrieval`.

**Note**: The KB build artifacts and scripts (`scripts/build_corpus.py`, `scripts/build_kb.py`, `data/kb/*`, `app/db/*.md`) and the four already-added CRAG config constants are in the working tree. Confirm with the user whether these should already be committed (they are prerequisites this feature consumes read-only) before branching, so 005 starts from a clean tree. The runtime node does **not** rebuild the KB.

---

## Task 1: Write config tests for CRAG runtime constants (confirm FAILING)

- [ ] Open `tests/unit/test_config.py`
- [ ] Add 3 new test functions for the CRAG runtime constants and model separation:

```python
def test_crag_runtime_constants_match_spec():
    """Verify CRAG runtime constants match specs/005 §6."""
    from app.config import (
        CRAG_TOP_K,
        CRAG_WEB_MAX_RESULTS,
        CRAG_MAX_EVIDENCE_SNIPPETS,
        CRAG_QUERY_MAX_CHARS,
        CRAG_EMBED_TIMEOUT_SECONDS,
        CRAG_WEB_TIMEOUT_SECONDS,
        CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD,
    )
    assert CRAG_TOP_K == 5
    assert CRAG_WEB_MAX_RESULTS == 5
    assert CRAG_MAX_EVIDENCE_SNIPPETS == 5
    assert CRAG_QUERY_MAX_CHARS == 2000
    assert CRAG_EMBED_TIMEOUT_SECONDS == 30
    assert CRAG_WEB_TIMEOUT_SECONDS == 20
    assert CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD == 5


def test_crag_constants_correct_types():
    """Verify types: int counts/timeouts, float threshold, str model/paths."""
    from app import config
    assert isinstance(config.CRAG_TOP_K, int)
    assert isinstance(config.CRAG_WEB_MAX_RESULTS, int)
    assert isinstance(config.CRAG_MAX_EVIDENCE_SNIPPETS, int)
    assert isinstance(config.CRAG_QUERY_MAX_CHARS, int)
    assert isinstance(config.CRAG_EMBED_TIMEOUT_SECONDS, int)
    assert isinstance(config.CRAG_WEB_TIMEOUT_SECONDS, int)
    assert isinstance(config.CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD, int)
    assert isinstance(config.CRAG_CONFIDENCE_THRESHOLD, float)
    assert isinstance(config.OLLAMA_EMBED_MODEL_NAME, str)
    assert isinstance(config.CRAG_KB_INDEX_PATH, str)
    assert isinstance(config.CRAG_KB_METADATA_PATH, str)


def test_embed_model_distinct_from_generative():
    """Constitution §8 model-separation rule (AC-8): the embedding model must
    NOT be the same constant/value as the generative model."""
    from app.config import OLLAMA_EMBED_MODEL_NAME, OLLAMA_MODEL_NAME
    assert OLLAMA_EMBED_MODEL_NAME != OLLAMA_MODEL_NAME
    assert OLLAMA_EMBED_MODEL_NAME == "bge-m3"
```

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — `test_crag_runtime_constants_match_spec` must FAIL with `ImportError` (the 7 runtime constants not defined yet). `test_embed_model_distinct_from_generative` may already PASS (the KB-facing constants exist). Existing config tests must still PASS.

---

## Task 2: Add CRAG runtime constants to config

- [ ] Open `app/config.py`
- [ ] The `# ── CRAG thresholds ──` block already has `CRAG_CONFIDENCE_THRESHOLD`, `OLLAMA_EMBED_MODEL_NAME`, `CRAG_KB_INDEX_PATH`, `CRAG_KB_METADATA_PATH`. **Remove the "only build-utility constants populated so far" NOTE comment**, and add the 7 runtime constants below them:

```python
CRAG_TOP_K: int = 5
# Number of nearest neighbors to retrieve from the local FAISS KB per clause.

CRAG_WEB_MAX_RESULTS: int = 5
# Max results to request from the web-search fallback per clause.

CRAG_MAX_EVIDENCE_SNIPPETS: int = 5
# Hard cap on evidence_snippets stored per clause, regardless of path.

CRAG_QUERY_MAX_CHARS: int = 2000
# Clause text is truncated to this length before embedding / web querying,
# to bound embedding input and web query size (spec §4.11).

CRAG_EMBED_TIMEOUT_SECONDS: int = 30
# Wall-clock timeout for a single embedding call via Ollama. On timeout the
# clause is treated as un-scorable and falls back to the web path (spec §4.4).

CRAG_WEB_TIMEOUT_SECONDS: int = 20
# Wall-clock timeout for a single web-search call. On timeout the clause's
# evidence is treated as empty (spec §4.8).

CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD: int = 5
# Number of CONSECUTIVE embedding failures after which the node declares the
# embedding backend down for the rest of the run and routes all remaining
# clauses straight to web (skipping the per-clause embed timeout). Resets on
# any successful embedding. Routing-semantics guarantee (spec §4.13, AC-16).
```

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — all config tests (IngestAgent + ClauseSplitter + CRAG) must now PASS.

---

## Task 3: Implement the retrievers package shared types (no dedicated TDD cycle)

- [ ] Create directory `app/graph/nodes/retrievers/`
- [ ] Create file `app/graph/nodes/retrievers/__init__.py`
- [ ] Contents:

```python
"""
Shared types for CRAG retriever modules.

RetrievalResult is the return type for both kb_retriever.search_kb() and
web_retriever.web_search(). make_snippet() builds an evidence dict in the exact
001-schema shape. Placing them in the package __init__ (like ClauseBoundary in
splitters/__init__.py) lets kb_retriever.py and web_retriever.py both import
them without a cross-dependency.
"""
from dataclasses import dataclass
from typing import Optional, List, Dict, Any


@dataclass
class RetrievalResult:
    """Outcome of one retriever call for a single clause.

    Attributes:
        snippets: Evidence snippets, each a dict with EXACTLY the keys
            {"snippet_text": str, "source_reference": str} (001-schema §3).
            Empty list = "path executed but found nothing".
        top_score: Top-1 cosine for the local-KB path (in [0.0, 1.0]);
            None for the web path (which has no score).
    """
    snippets: List[Dict[str, Any]]
    top_score: Optional[float]


def make_snippet(snippet_text: str, source_reference: str) -> Dict[str, str]:
    """Build an evidence snippet in the exact 001 shape (only the two reserved
    keys), so AC-6 holds regardless of source path."""
    return {"snippet_text": snippet_text, "source_reference": source_reference}
```

**Why**: `RetrievalResult`/`make_snippet` are shared data structures, not feature logic — like `ClauseBoundary`/`ParseResult`, they need no TDD cycle and are implemented before the retriever tests that import them (plan §4 Step 4 note).

**Verify**: Run from `backend/`:
```
python -c "from app.graph.nodes.retrievers import RetrievalResult, make_snippet; print(make_snippet('t','r'), RetrievalResult([], None))"
```

---

## Task 4: Write unit tests for `embed_query` (confirm FAILING)

- [ ] Create file `tests/unit/test_embeddings.py`
- [ ] The import `from app.graph.nodes.retrievers.embeddings import embed_query` will fail until Task 5 — expected for TDD.
- [ ] **Mocking strategy (reviewer #5 — name the target)**: patch `ollama.Client` at `app.graph.nodes.retrievers.embeddings.ollama.Client` (equivalently `patch("ollama.Client")` since `embeddings.py` does `import ollama`). Configure `mock_client.return_value.embeddings.return_value = {"embedding": [...]}` and assert on `mock_client.call_args` that it was constructed with `timeout=<passed timeout_seconds>` (this is exactly the correctness hinge from Task 5) and on `.embeddings.call_args` for the model name. **No real Ollama instance.**
- [ ] Write these 6 test functions (plan §2 test matrix):

| Test function | Verifies |
|---------------|----------|
| `test_embed_returns_l2_normalized_vector` | Returned vector has L2 norm ≈ 1.0 (query-side normalization applied) |
| `test_embed_uses_embed_model_not_generative` | `.embeddings(...)` called with `model=OLLAMA_EMBED_MODEL_NAME`, never `OLLAMA_MODEL_NAME` (AC-8) |
| `test_embed_timeout_returns_none` | Simulated timeout → `None`, warning logged |
| `test_embed_connection_error_returns_none` | Ollama unreachable (`ConnectionError`/`httpx.ConnectError`) → `None` |
| `test_embed_zero_norm_returns_none` | Mock returns an all-zeros embedding → `None` (zero-norm guard) |
| `test_embed_malformed_response_returns_none` | Response missing the `"embedding"` key → `None` |

- [ ] For `test_embed_returns_l2_normalized_vector`: mock the client's `.embeddings` to return `{"embedding": [3.0, 4.0]}` and assert `np.linalg.norm(result) == pytest.approx(1.0)` (and that `result` equals `[0.6, 0.8]`).
- [ ] For `test_embed_timeout_returns_none`: make the mocked call sleep longer than a tiny passed `timeout_seconds` (e.g. `0.05`) or raise `concurrent.futures.TimeoutError` / `httpx.TimeoutException`; assert `None`.
- [ ] Warning assertions use pytest's `caplog` at `WARNING` level.

**Verify**: Run `python -m pytest tests/unit/test_embeddings.py -v` — all 6 tests must FAIL (ImportError). Confirms the TDD cycle.

---

## Task 5: Implement `embed_query`

- [ ] Create file `app/graph/nodes/retrievers/embeddings.py`
- [ ] **Imports**: `concurrent.futures`, `logging` (stdlib); `numpy as np`; `httpx` (timeout type); `ollama`. No app imports (`model_name` is passed in).
- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.crag_retrieval.embeddings")`
- [ ] Public interface:

```python
def embed_query(text: str, timeout_seconds: int, model_name: str) -> "Optional[np.ndarray]":
    """Embed clause/query text with BGE-M3 via Ollama and L2-normalize it.
    Returns a float32 unit vector, or None on ANY failure. Never raises."""
```

- [ ] **CRITICAL — client-level timeout is the primary bound (reviewer #1)**: the embedding call MUST go through `ollama.Client(timeout=timeout_seconds).embeddings(model=model_name, prompt=text)`, mirroring `llm_refiner.py:102`'s `ollama.Client(timeout=...)`. Do NOT copy `build_kb.py`'s bare `ollama.embeddings(...)` (no timeout) — that is fine for an offline script but wrong here. If the call were bare and bounded only by `future.result(timeout=...)`, a hung Ollama socket would leave the worker thread blocked in the HTTP read, and exiting the `with ThreadPoolExecutor(...)` block (`shutdown(wait=True)`) would hang **indefinitely**, defeating both `CRAG_EMBED_TIMEOUT_SECONDS` and the circuit breaker (spec Edge Case 13, Risk row 1). The `Client(timeout=…)` makes the underlying call abort; the executor is a backstop only.
- [ ] **Timeout enforcement** — same `concurrent.futures.ThreadPoolExecutor(max_workers=1)` + `future.result(timeout=timeout_seconds)` pattern as `llm_refiner.refine_with_llm`. Submit a private `_call_embed(text, model_name, timeout_seconds)` that constructs the timed `Client` and returns the normalized vector.
- [ ] **L2-normalization** (spec §7.1 query-side invariant): `vec = np.asarray(resp["embedding"], dtype=np.float32)`; `norm = float(np.linalg.norm(vec))`; if `norm < 1e-12` → raise (caught → `None`); else return `vec / norm`. This mirrors `build_kb.py`'s zero-norm guard and normalization exactly, so build and query sides agree.
- [ ] **Failure handling** — catch `concurrent.futures.TimeoutError`, `httpx.TimeoutException`, and any `Exception` → log a warning (rate-limited to avoid bloat on large docs) and return `None`. Never raise. Malformed response (missing `"embedding"`) and zero-norm both funnel to `None`.

**Verify**: Run `python -m pytest tests/unit/test_embeddings.py -v` — all 6 tests must PASS.

---

## Task 6: Write unit tests for the KB retriever (confirm FAILING)

- [ ] Create file `tests/unit/test_kb_retriever.py`
- [ ] **Fixture strategy — build a tiny in-memory FAISS index** of a handful of known **unit** vectors (so cosines are exact and routing is deterministic), written to a `tmp_path` alongside a matching metadata sidecar. **Redirect the retriever at those temp files via the exact seam (reviewer #4): monkeypatch `kb_retriever._resolve_backend_path`** to return the `tmp_path` index/meta files directly (dispatch on the passed relative path), and reset the module-level `_KB_CACHE` in the `autouse` teardown fixture (below) so a cached KB never leaks between cases. No real Ollama, no network.
- [ ] The import `from app.graph.nodes.retrievers.kb_retriever import load_kb, search_kb` will fail until Task 7 — expected.
- [ ] Write these 9 test functions (plan §2 test matrix):

| Test function | Verifies |
|---------------|----------|
| `test_search_returns_top1_cosine` | `top_score` == max cosine among neighbors (§7.1); clamped `max(0.0, …)` |
| `test_search_snippet_shape` | Each snippet has exactly `snippet_text` + `source_reference` (AC-6) |
| `test_search_cosine_exactly_threshold_routes_local` | A neighbor engineered at cosine == 0.73 yields `top_score == pytest.approx(0.73)` (feeds AC-4) |
| `test_search_fewer_than_topk` | Index with < `CRAG_TOP_K` vectors → returns all available, no crash (§4.6) |
| `test_search_zero_vectors_score_zero` | Empty index → `top_score == 0.0`, `snippets == []` |
| `test_load_kb_missing_index_returns_none` | Missing index file → `None`, single warning (AC-14) |
| `test_load_kb_row_count_mismatch_returns_none` | `len(meta) != index.ntotal` → treated as corrupt → `None` |
| `test_load_kb_cached` | Second `load_kb()` does not re-read the index file (patch `faiss.read_index`, assert called once) |
| `test_path_resolved_relative_to_backend` | Configured relative paths resolve against the backend/ dir, not raw CWD |

- [ ] For `test_search_cosine_exactly_threshold_routes_local`: construct a query unit vector and a KB unit vector whose dot product is exactly 0.73 (e.g. `kb = [0.73, sqrt(1-0.73**2)]`, `query = [1, 0]`).
- [ ] For `test_load_kb_cached`: reset any module-level cache in a fixture (`autouse` teardown) so tests don't leak a cached KB between them.
- [ ] Warning assertions use `caplog` at `WARNING`.

**Verify**: Run `python -m pytest tests/unit/test_kb_retriever.py -v` — all 9 tests must FAIL (ImportError). Confirms the TDD cycle.

---

## Task 7: Implement the KB retriever

- [ ] Create file `app/graph/nodes/retrievers/kb_retriever.py`
- [ ] **Imports**: `json`, `logging` (stdlib); `from pathlib import Path`; `faiss`; `numpy as np`; `from app.graph.nodes.retrievers import RetrievalResult, make_snippet`; `import app.config as _config`.
- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.crag_retrieval.kb")`
- [ ] Public interface:

```python
def load_kb() -> "Optional[_LoadedKB]":
    """Load and cache the FAISS index + metadata sidecar. Returns a handle
    (index + row->snippet metadata) or None if the KB is unavailable
    (missing/corrupt index, missing sidecar, or row/vector count mismatch).
    Logs a SINGLE node-level warning on first unavailability (AC-14). Cached."""

def search_kb(kb, query_vec: "np.ndarray", top_k: int) -> RetrievalResult:
    """Search the loaded KB with an L2-normalized query vector. Returns
    RetrievalResult(snippets=top-k KB snippets in 001 shape,
    top_score=max(0.0, best cosine)). Fewer than top_k vectors → returns what
    exists; zero vectors → top_score=0.0, snippets=[] (§4.6)."""
```

- [ ] **Path resolution (spec §6 anchor)** — a private helper resolving config-relative paths against the **backend/ directory**, not the raw CWD:

```python
def _resolve_backend_path(rel: str) -> Path:
    # config.py lives at backend/app/config.py → backend/ is parent.parent
    backend_dir = Path(_config.__file__).resolve().parent.parent
    return backend_dir / rel
```

  Use it for both `_config.CRAG_KB_INDEX_PATH` and `_config.CRAG_KB_METADATA_PATH`. This matches how `build_kb.py` anchors via `BACKEND_DIR` and satisfies `test_path_resolved_relative_to_backend`.
- [ ] **Loading + caching**: store the loaded KB in a module-level global (e.g. `_KB_CACHE`), populated lazily on first `load_kb()`. Provide an internal reset seam (a private function or sentinel) so tests can clear it between cases. Return `None` (not raise) on:
  - missing index file or missing sidecar file;
  - `faiss.read_index` failure (corrupt);
  - `len(meta) != index.ntotal` (sidecar/index mismatch — treat as corrupt).
  Log exactly ONE warning at node level on first unavailability (AC-14 — not one per clause).
- [ ] **Metadata**: read the JSONL sidecar into a `list[dict]`; row index == FAISS vector ID (the 1:1 guarantee from spec §7.3). Each row already has `{snippet_text, source_reference}`.
- [ ] **Search**:
  - **Guard the empty index FIRST (reviewer #1)** — before calling `index.search`, `if index.ntotal == 0: return RetrievalResult([], 0.0)`. Passing `k=0` to FAISS is version-dependent (some builds assert `k > 0`); this explicit early return is what makes `test_search_zero_vectors_score_zero` pass deterministically.
  - Otherwise `D, I = index.search(query_vec.reshape(1, -1), min(top_k, index.ntotal))`. Build snippets from `meta[i]` for each returned `i` via `make_snippet(meta[i]["snippet_text"], meta[i]["source_reference"])`. `top_score = max(0.0, float(D[0][0]))`. Wrap in `RetrievalResult(snippets, top_score)`.
- [ ] The query vector is assumed already L2-normalized by `embed_query`; the index is `IndexFlatIP`, so inner product == cosine (spec §7.1). Do NOT re-normalize here.

**Verify**: Run `python -m pytest tests/unit/test_kb_retriever.py -v` — all 9 tests must PASS.

---

## Task 8: Write unit tests for the web retriever (confirm FAILING)

- [ ] Create file `tests/unit/test_web_retriever.py`
- [ ] **Mocking strategy**: patch `DDGS` where `web_retriever` imports it (`app.graph.nodes.retrievers.web_retriever.DDGS`). The mock's `.text(query, max_results=...)` returns a list of `{"title", "href", "body"}` dicts. **No network.**
- [ ] The import `from app.graph.nodes.retrievers.web_retriever import web_search` will fail until Task 9 — expected.
- [ ] Write these 7 test functions (plan §2 test matrix):

| Test function | Verifies |
|---------------|----------|
| `test_web_maps_results_to_snippet_shape` | DDG `{title,href,body}` → snippets with exactly `snippet_text`(=body) + `source_reference`(=href) (AC-6) |
| `test_web_respects_max_results` | No more than `CRAG_WEB_MAX_RESULTS` snippets returned; `.text` called with `max_results=` |
| `test_web_top_score_is_none` | `RetrievalResult.top_score is None` on the web path |
| `test_web_zero_results_returns_empty` | Empty results list → `RetrievalResult([], None)` (§4.7) |
| `test_web_raises_returns_empty` | `.text` raises (rate-limit/network) → `([], None)`, no crash (AC-13) |
| `test_web_timeout_returns_empty` | Simulated timeout → `([], None)` (§4.8) |
| `test_web_import_fallback` | Library-unavailable path degrades to zero results, not an import crash at call time |

- [ ] For `test_web_maps_results_to_snippet_shape`: also assert a result missing `body` or `href` is **skipped** (not emitted as an empty-keyed snippet).
- [ ] For `test_web_import_fallback`: simulate `DDGS is None` (guarded-import failure) and assert `web_search(...)` returns `([], None)`.
- [ ] Warning assertions use `caplog` at `WARNING`.

**Verify**: Run `python -m pytest tests/unit/test_web_retriever.py -v` — all 7 tests must FAIL (ImportError). Confirms the TDD cycle.

---

## Task 9: Implement the web retriever

- [ ] Create file `app/graph/nodes/retrievers/web_retriever.py`
- [ ] **Imports**: `concurrent.futures`, `logging` (stdlib); `from app.graph.nodes.retrievers import RetrievalResult, make_snippet`.
- [ ] **Guarded import (spec §4.8 pin)** — at module load, try `from duckduckgo_search import DDGS`; on `ImportError` fall back to `from ddgs import DDGS`; if both fail, set `DDGS = None`. Never let an unavailable library crash node import:

```python
try:
    from duckduckgo_search import DDGS
except ImportError:  # library renamed to `ddgs` upstream
    try:
        from ddgs import DDGS
    except ImportError:
        DDGS = None
```

- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.crag_retrieval.web")`
- [ ] Public interface:

```python
def web_search(query: str, max_results: int, timeout_seconds: int) -> RetrievalResult:
    """Search the web via DuckDuckGo. Returns RetrievalResult(snippets up to
    max_results in 001 shape, top_score=None). On ANY failure (rate-limit,
    network, library error, timeout, zero results) returns ([], None). Never
    raises (AC-13)."""
```

- [ ] **CRITICAL — exact invocation + mapping (reviewer #2, spec §4.8 pin)**: call `DDGS().text(query, max_results=max_results)`. Each result is `{"title", "href", "body"}`. Map:
  - `snippet_text` ← `result["body"]`
  - `source_reference` ← `result["href"]`
  via `make_snippet(...)`. **Skip** any result missing a non-empty `body` or `href` (protects AC-6). The `.text()` return may be a generator — iterate and stop at `max_results`.
- [ ] **If `DDGS is None`** → return `RetrievalResult([], None)` immediately (with a one-time warning). This is `test_web_import_fallback`.
- [ ] **Timeout — and its limit (reviewer #1, web half)**: enforce `CRAG_WEB_TIMEOUT_SECONDS` via `concurrent.futures.ThreadPoolExecutor(max_workers=1)` + `future.result(timeout=timeout_seconds)`. Unlike `embed_query`, **there is no client-level timeout for `DDGS`**, so the executor is the only bound. To ensure the node never blocks past the timeout on a hung socket:
  - if the installed `DDGS` supports a constructor `timeout=` (or per-call socket timeout), pass `CRAG_WEB_TIMEOUT_SECONDS` into it; AND
  - do NOT rely on the implicit `shutdown(wait=True)` at `with ThreadPoolExecutor(...)` exit — construct the executor without the `with` block and call `executor.shutdown(wait=False)` (or submit-and-abandon the future) so a stuck worker thread cannot block the node. Document this in a code comment referencing plan §2 / Risk table.
- [ ] **Broad catch**: wrap the whole call in `try/except Exception` → return `RetrievalResult([], None)`, logging a rate-limited warning. Do NOT catch only a specific timeout type (AC-13's guarantee is load-bearing given DDG's fragility).

**Verify**: Run `python -m pytest tests/unit/test_web_retriever.py -v` — all 7 tests must PASS.

---

## Task 10: Write unit tests for the `crag_retrieval_agent` node (confirm FAILING)

- [ ] Create file `tests/unit/test_crag_retrieval_agent.py`
- [ ] **Mocking strategy**: patch `embed_query`, `load_kb`, `search_kb`, and `web_search` **at the node module level** (`app.graph.nodes.crag_retrieval_agent`) so no real embed/FAISS/web work runs. Control confidence by having the mocked `search_kb` return a `RetrievalResult` with a chosen `top_score`.
- [ ] Helper: `make_crag_state(clauses, ingest_error=None, document_id="doc-1")` returning a minimal state dict with the keys the node reads. Clause records need at least `{text, position}`.
- [ ] Write these 19 test functions (the 18 from the plan §2 matrix + `test_query_truncated_before_embed`, closing the §4.11 coverage gap):

| Test function | Verifies |
|---------------|----------|
| `test_all_clauses_get_three_fields` | Every clause gets `confidence_score`, `path_taken`, `evidence_snippets` (AC-1) |
| `test_high_confidence_routes_local` | `search_kb` top_score ≥ threshold → `LOCAL_KB`, KB-sourced snippets (AC-2) |
| `test_low_confidence_routes_web` | top_score < threshold → `WEB_FALLBACK`, web snippets (AC-3) |
| `test_threshold_boundary_inclusive_local` | top_score == 0.73 → `LOCAL_KB` (comparison is `>=`) (AC-4) |
| `test_confidence_in_range_or_none` | Every `confidence_score` is `None` or a float in `[0,1]` (AC-5) |
| `test_snippet_cap_enforced` | With `CRAG_MAX_EVIDENCE_SNIPPETS` monkeypatched **below** the source counts, no clause exceeds the cap (AC-7 — see note) |
| `test_embed_model_separation` | `embed_query` invoked with `OLLAMA_EMBED_MODEL_NAME`, never `OLLAMA_MODEL_NAME` (AC-8) |
| `test_ingest_error_returns_empty` | `ingest_error` set → empty update; embed/KB/web NOT called (AC-10) |
| `test_empty_clauses_returns_empty` | `clauses == {}` → empty update, warning, no external calls (AC-11) |
| `test_partial_update_only` | Return dict keys are exactly `{clauses, current_node, node_timings}`; no `error_count` (AC-12) |
| `test_web_failure_graceful` | `web_search` returns `([], None)` (raise/timeout upstream) → `WEB_FALLBACK`, `[]`, recorded score, no crash, other clauses proceed (AC-13) |
| `test_kb_unavailable_all_web` | `load_kb()` → None → every clause `WEB_FALLBACK`, one warning (AC-14) |
| `test_local_path_deterministic` | Same text + same mocked KB + same embed → identical snippets + score across two runs (AC-15) |
| `test_circuit_breaker_opens` | After `CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD` consecutive embed failures (`embed_query` → None), remaining clauses skip embedding (assert `embed_query` call count stops), one "circuit opened" warning (AC-16) |
| `test_circuit_resets_on_success` | A success between failures resets the consecutive counter — circuit does NOT trip on intermittent single failures |
| `test_empty_clause_text_skipped` | Whitespace-only clause → all three fields `None`; `embed_query` NOT called for it (§4.3) |
| `test_current_node_pinned` | `current_node == "crag_retrieval"` and the same string keys `node_timings` |
| `test_confidence_none_vs_zero` | Embed-failure → `confidence_score is None`; KB-unavailable-with-successful-embed → `0.0` (plan §2 refinement) |
| `test_query_truncated_before_embed` | A clause longer than a monkeypatched-small `CRAG_QUERY_MAX_CHARS` → the string passed to the mocked `embed_query` is truncated to the cap (spec §4.11) |

- [ ] For `test_ingest_error_returns_empty` and `test_empty_clauses_returns_empty`: assert `embed_query`, `load_kb`, `search_kb`, `web_search` were **not** called (`mock.assert_not_called()`).
- [ ] For `test_snippet_cap_enforced` (AC-7): monkeypatch `CRAG_MAX_EVIDENCE_SNIPPETS` on the **node module** to a value **below** `CRAG_TOP_K` / `CRAG_WEB_MAX_RESULTS` (e.g. 2), and have the mocked `search_kb` / `web_search` return more snippets than that (e.g. 5). With the defaults all equal to 5 the cap never truncates, so the test MUST lower it. Assert `len(clause["evidence_snippets"]) == 2`.
- [ ] For `test_circuit_breaker_opens`: set the breaker threshold small (monkeypatch to e.g. 3), make `embed_query` always return `None`, feed more clauses than the threshold, and assert `embed_query.call_count == 3` (stops issuing embed calls once open) while later clauses still get `WEB_FALLBACK`.
- [ ] For `test_partial_update_only`: assert forbidden keys absent — `document_id`, `extracted_text`, `ocr_used`, `ingest_error`, `report_path`, `evidence_trail`, `mcp_delivery_status`, and specifically `error_count`.

**Verify**: Run `python -m pytest tests/unit/test_crag_retrieval_agent.py -v` — all 19 tests must FAIL (ImportError). Confirms the TDD cycle.

---

## Task 11: Implement the `crag_retrieval_agent` node function

- [ ] Create file `app/graph/nodes/crag_retrieval_agent.py`
- [ ] **Imports**: `time`, `logging` (stdlib); `from app.graph.state import ContractState, RetrievalPath`; `from app.graph.nodes.retrievers.embeddings import embed_query`; `from app.graph.nodes.retrievers.kb_retriever import load_kb, search_kb`; `from app.graph.nodes.retrievers.web_retriever import web_search`.
- [ ] **CRITICAL — config import pattern (mirror `clause_splitter_agent.py`)**: `import app.config as _config` and re-expose each tunable as a monkeypatchable module-level name that the function reads by **bare name** (never `_config.NAME`):

```python
import app.config as _config

OLLAMA_EMBED_MODEL_NAME = _config.OLLAMA_EMBED_MODEL_NAME
OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME  # re-exposed so the AC-8 test can compare
CRAG_CONFIDENCE_THRESHOLD = _config.CRAG_CONFIDENCE_THRESHOLD
CRAG_TOP_K = _config.CRAG_TOP_K
CRAG_WEB_MAX_RESULTS = _config.CRAG_WEB_MAX_RESULTS
CRAG_MAX_EVIDENCE_SNIPPETS = _config.CRAG_MAX_EVIDENCE_SNIPPETS
CRAG_QUERY_MAX_CHARS = _config.CRAG_QUERY_MAX_CHARS
CRAG_EMBED_TIMEOUT_SECONDS = _config.CRAG_EMBED_TIMEOUT_SECONDS
CRAG_WEB_TIMEOUT_SECONDS = _config.CRAG_WEB_TIMEOUT_SECONDS
CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD = _config.CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD
```

- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.crag_retrieval")`
- [ ] Public interface:

```python
def crag_retrieval_agent(state: ContractState) -> dict:
    """LangGraph Node 3. Reads clauses/document_id/ingest_error; returns partial
    dict: clauses (per-clause evidence updates), current_node, node_timings."""
```

- [ ] **Internal flow** (plan §2):
  1. `start_time = time.monotonic()`; `current_node = "crag_retrieval"`; `document_id = state.get("document_id", "unknown")`.
  2. **Defensive `ingest_error` check** — if `state.get("ingest_error") is not None` → return empty update (`clauses={}`, `current_node`, `node_timings`); NO embed/KB/web calls (AC-10).
  3. `clauses = state.get("clauses", {})`. If falsy → log warning, return empty update; NO external calls (AC-11).
  4. `kb = load_kb()` — `None` if unavailable (single warning inside `load_kb`, AC-14).
  5. Circuit-breaker locals: `consecutive_failures = 0`; `circuit_open = False`.
  6. Build `clause_updates = {}`. Iterate clauses **in document order** (sort by `position`). For each `clause_id`, `record`:
     - **a.** `text = (record.get("text") or "").strip()`. If empty → stage `{confidence_score: None, path_taken: None, evidence_snippets: None}`, log a warning, `continue` (do NOT call `embed_query`) — §4.3.
     - **b.** `query = text[: CRAG_QUERY_MAX_CHARS]` (log at DEBUG if truncated — §4.11).
     - **c.** `kb_result = None` **(initialize up front — reviewer #5, avoids UnboundLocalError)**. `query_vec = None`.
     - **d.** If `not circuit_open`: `query_vec = embed_query(query, CRAG_EMBED_TIMEOUT_SECONDS, OLLAMA_EMBED_MODEL_NAME)`.
       - If `query_vec is None`: `consecutive_failures += 1`; if `consecutive_failures >= CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD` and not already open → `circuit_open = True`, log ONE "circuit opened" warning.
       - Else: `consecutive_failures = 0` (reset on success).
     - **e.** Decide `confidence` + `path` (the None-vs-0.0 rule, plan §2):
       - `kb is None` → `confidence = 0.0 if query_vec is not None else None`; `path = WEB_FALLBACK`.
       - `query_vec is None` (embed failed or circuit open) → `confidence = None`; `path = WEB_FALLBACK`.
       - else → `kb_result = search_kb(kb, query_vec, CRAG_TOP_K)`; `confidence = kb_result.top_score`; `path = LOCAL_KB if confidence >= CRAG_CONFIDENCE_THRESHOLD else WEB_FALLBACK` (inclusive `>=`, AC-4).
     - **f.** Gather evidence for the chosen path:
       - `LOCAL_KB` → `snippets = kb_result.snippets`.
       - `WEB_FALLBACK` → `snippets = web_search(query, CRAG_WEB_MAX_RESULTS, CRAG_WEB_TIMEOUT_SECONDS).snippets` (`[]` on any failure — never raises).
     - **g.** Cap: `snippets = snippets[: CRAG_MAX_EVIDENCE_SNIPPETS]` (AC-7).
     - **h.** Stage `clause_updates[clause_id] = {"confidence_score": confidence, "path_taken": path, "evidence_snippets": snippets}` — ONLY the three evidence fields (the reducer preserves `text`/`position`/etc. — §4.12).
     - **i.** Emit a per-clause structured log record via `logger.info(..., extra={...})` with confidence, path value, snippet count, and (where measured) embed/web latency (spec §8 — logs only, NOT state).
  7. `elapsed = time.monotonic() - start_time`.
  8. Return `{"clauses": clause_updates, "current_node": current_node, "node_timings": {current_node: elapsed}}`.

- [ ] **`path_taken` value**: store the `RetrievalPath` enum member (`RetrievalPath.LOCAL_KB` / `RetrievalPath.WEB_FALLBACK`), matching the clause-record type in 001-schema. For the structured log, log `path.value`.
- [ ] **CRITICAL — no `error_count`**: every failure mode here is graceful degradation, not a pipeline error. Return ONLY the three keys (AC-12). Same stance as ClauseSplitterAgent.
- [ ] **Return shape (defensive — ingest_error set or empty clauses)**: same three keys with `"clauses": {}`.
- [ ] **Pinned `current_node`**: the literal string `"crag_retrieval"` (spec §2) — same value used as the `node_timings` key and as the graph node name in Task 12. Do NOT derive it.

**Verify**: Run `python -m pytest tests/unit/test_crag_retrieval_agent.py -v` — all 19 tests must PASS.

---

## Task 12: Wire the node into the graph builder

- [ ] Open `app/graph/builder.py`
- [ ] Add the import: `from app.graph.nodes.crag_retrieval_agent import crag_retrieval_agent`
- [ ] Register the node and rewire the tail so `clause_splitter → crag_retrieval → END`:

```python
graph.add_node("crag_retrieval", crag_retrieval_agent)
graph.add_edge("clause_splitter", "crag_retrieval")  # was END temporarily
graph.add_edge("crag_retrieval", END)                # → END until feature-006
```

- [ ] Remove the old `graph.add_edge("clause_splitter", END)` line (it is replaced by the edge into `crag_retrieval`).
- [ ] Update the module docstring: Node 3 (crag_retrieval) is now wired and routes to END temporarily until feature-006 (Self-RAG).
- [ ] **Document the constitution §2 interpretation (spec §7.2 REQUIRES this be recorded)** — add a comment near the `crag_retrieval` node explaining that CRAG's confidence-based routing is one of the two permitted conditional edges but is realized as **internal Python branching inside the node**, NOT a graph-level `add_conditional_edges`, because per-clause routing cannot be expressed as a whole-state graph edge. This mirrors the existing comment style on `route_after_ingest` (which documents that the error short-circuit is NOT one of the two domain conditional edges).

**Verify**: Run from `backend/`:
```
python -c "from app.graph.builder import build_graph; g = build_graph(); print(type(g))"
```
Should print the compiled graph type without errors.

---

## Task 13: Write and run integration tests

- [ ] Create file `tests/integration/test_crag_retrieval_graph.py`
- [ ] Tests exercise IngestAgent → ClauseSplitterAgent → CRAG through the compiled graph. **Mock the embedding and web calls, but use the real built FAISS KB** so the local path is exercised end-to-end.
- [ ] **CRITICAL — patch targets (reviewer #2)**: patch `app.graph.nodes.crag_retrieval_agent.embed_query` and `app.graph.nodes.crag_retrieval_agent.web_search` — i.e. **on the node module**, because `crag_retrieval_agent.py` does `from ...embeddings import embed_query` / `from ...web_retriever import web_search`, binding those names into the node module. Patching `retrievers.embeddings.embed_query` would NOT affect the node and the test would silently hit real Ollama/DuckDuckGo. Leave `load_kb`/`search_kb` **real** (this test uses the real KB).
- [ ] Also mock `ollama.chat` (ClauseSplitter's LLM) as in the 004 integration tests, so Node 2 doesn't need live Ollama either.
- [ ] Reuse existing conftest fixtures (`sample_pdf_path`, `unsupported_txt_path`) and the inline `{"document_path": ...}` initial-state pattern.
- [ ] Write these 5 test functions (plan §2 test matrix):

| Test function | Verifies |
|---------------|----------|
| `test_graph_ingest_clause_crag_success` | Node1→Node2→Node3 reaches END; every clause carries `confidence_score`, `path_taken`, `evidence_snippets` |
| `test_graph_ingest_error_skips_crag` | Ingest error short-circuits to END; CRAG not reached; assert with `assert not final_state.get("clauses")` (KeyError caution below) |
| `test_graph_crag_local_path_real_kb` | A clause routes `LOCAL_KB` (cosine ≥ 0.73) against the real 109-vector index, using the reconstruct(0) fixture below |
| `test_graph_crag_web_fallback_on_low_confidence` | A clause routes `WEB_FALLBACK` — mock `embed_query` to return `-kb_vec0` (see below); mocked `web_search` returns snippets |
| `test_graph_checkpointing_after_crag` | State is checkpointed after CRAG completes (SqliteSaver; `pytest.skip` if the import path is unavailable, mirroring `test_ingest_graph.py`) |

- [ ] **Deterministic-embed fixture (reviewer #3)** for `test_graph_crag_local_path_real_kb`: an arbitrary mock vector will not reliably clear 0.73 against the real index. Obtain a guaranteed match by reading row 0 back out of the real index at test setup:

```python
import faiss
from app.graph.nodes.retrievers.kb_retriever import _resolve_backend_path  # or read via config
idx = faiss.read_index(str(_resolve_backend_path(config.CRAG_KB_INDEX_PATH)))
kb_vec0 = idx.reconstruct(0)  # already L2-normalized; self-similarity == 1.0
```

  Mock `embed_query` to return `kb_vec0`, and assert the routed clause's `path_taken == RetrievalPath.LOCAL_KB` and that a returned snippet's `source_reference` equals `clauses_meta.jsonl` row 0's `source_reference`. Deterministic and offline — reconstructing a stored row does NOT require BGE-M3 in CI.
- [ ] **Deterministic web-fallback vector (reviewer #3)** for `test_graph_crag_web_fallback_on_low_confidence`: do NOT use a bare random vector (flaky in principle). Use **`-kb_vec0`** — the negation of row 0. Its cosine with every mostly-non-negative KB vector is ≤ 0; the top-1 clamps to `0.0` (`max(0.0, …)`), guaranteed below 0.73 → `WEB_FALLBACK`. (If a provably-below-threshold *positive* vector is preferred instead, use a fixed seed: `v = np.random.default_rng(42).standard_normal(1024).astype("float32"); v /= np.linalg.norm(v)` — but `-kb_vec0` is the cleaner guarantee.)
- [ ] **KeyError caution** (`test_graph_ingest_error_skips_crag`): `clauses` is an `Annotated[dict, merge_nested_clause_dicts]` channel with no default. On the error short-circuit it is never written, so `final_state["clauses"]` raises `KeyError`. Assert `assert not final_state.get("clauses")` instead (same subtlety noted in the 004 tasks).
- [ ] For the checkpointing test, attach the checkpointer the same way `test_ingest_graph.py` / `test_clause_splitter_graph.py` do.

**Verify**: Run `python -m pytest tests/integration/test_crag_retrieval_graph.py -v` — all 5 tests must PASS (checkpointing may skip if the SQLite saver import path is unavailable — acceptable).

---

## Task 14: Full test suite pass

- [ ] Run the complete suite:
```
python -m pytest tests/ -v --tb=short
```
- [ ] All existing IngestAgent (003) and ClauseSplitterAgent (004) tests must still pass — the CRAG changes must not regress them. In particular, the previously-terminal `clause_splitter → END` edge is now `clause_splitter → crag_retrieval`; any 004 integration test asserting the graph ends right after ClauseSplitter must be updated to expect the CRAG node (it should still reach END, now via Node 3).
- [ ] Expected NEW test count for feature 005: 3 (config) + 6 (embeddings) + 9 (KB retriever) + 7 (web retriever) + 19 (node) + 5 (integration) = **49 new tests**.
- [ ] OCR-gated IngestAgent tests may skip if Tesseract is absent — acceptable. No CRAG test requires Tesseract, a live Ollama, or network.

---

## Task 15: Linting and type checking

- [ ] Run `black app/ tests/ scripts/` — auto-format.
- [ ] Run `ruff check app/ tests/ scripts/` — no lint errors.
- [ ] Run `mypy app/` — no type errors (if mypy is installed). Note `faiss` / `duckduckgo_search` may lack stubs; add narrow `# type: ignore[import-untyped]` on those imports only if needed — do NOT broaden.
- [ ] Do NOT weaken tests to satisfy lint/type checks — fix the implementation instead (constitution §7).

---

## Task 16: Manual live smoke test (optional, not in automated suite)

- [ ] Ensure Ollama is running with both models: `ollama pull bge-m3` (embedding) and `ollama pull qwen3:14b` (Node 2). Confirm `bge-m3` is present (it was installed during planning; the KB was built with it).
- [ ] Run the full graph on a real multi-clause contract with live Ollama + real DuckDuckGo.
- [ ] Confirm: some clauses route `LOCAL_KB` (against the 109-vector KB) and some `WEB_FALLBACK`; `confidence_score` values are populated and in `[0,1]`; `evidence_snippets` carry the `{snippet_text, source_reference}` shape; observed per-clause embed latency is well under `CRAG_EMBED_TIMEOUT_SECONDS`.
- [ ] Record the observed confidence distribution and path hit-rate (spec §8) — use it to consider tuning `CRAG_CONFIDENCE_THRESHOLD` (0.73) and `CRAG_TOP_K` in a follow-up.

**Why**: The automated suite mocks embedding + web, so this is the only step that validates the real bge-m3 query embedding, live DuckDuckGo behavior (rate-limits included), and the true latency envelope (plan §6 risks). The query-side path was already smoke-validated during planning (a termination query hit `§14.3 — Termination` at cosine 0.8015 → `LOCAL_KB`).

---

## Summary of all files created/modified

| # | File | Action |
|---|------|--------|
| 1 | `app/config.py` | MODIFIED (add 7 CRAG runtime constants; drop the "build-utility only" note) |
| 2 | `app/graph/nodes/retrievers/__init__.py` | NEW (`RetrievalResult`, `make_snippet`) |
| 3 | `app/graph/nodes/retrievers/embeddings.py` | NEW (`embed_query`) |
| 4 | `app/graph/nodes/retrievers/kb_retriever.py` | NEW (`load_kb`, `search_kb`) |
| 5 | `app/graph/nodes/retrievers/web_retriever.py` | NEW (`web_search`) |
| 6 | `app/graph/nodes/crag_retrieval_agent.py` | NEW (node function) |
| 7 | `app/graph/builder.py` | MODIFIED (add node + rewire clause_splitter → crag → END) |
| 8 | `tests/unit/test_config.py` | MODIFIED (+3 tests) |
| 9 | `tests/unit/test_embeddings.py` | NEW (6 tests) |
| 10 | `tests/unit/test_kb_retriever.py` | NEW (9 tests) |
| 11 | `tests/unit/test_web_retriever.py` | NEW (7 tests) |
| 12 | `tests/unit/test_crag_retrieval_agent.py` | NEW (19 tests) |
| 13 | `tests/integration/test_crag_retrieval_graph.py` | NEW (5 tests) |

(The KB build scripts `scripts/build_corpus.py` / `scripts/build_kb.py` and `data/kb/*` already exist and are consumed read-only — not created by this feature's implementation.)

---

## Acceptance-criteria traceability (spec §3 → tasks)

| Spec §3 criterion | Covered by |
|-------------------|-----------|
| 1. Per-clause coverage | Task 10/11 (`test_all_clauses_get_three_fields`) |
| 2. High-confidence → local KB | Task 10/11 (`test_high_confidence_routes_local`) |
| 3. Low-confidence → web fallback | Task 10/11 (`test_low_confidence_routes_web`) |
| 4. Threshold boundary inclusive at local side | Task 10/11 (`test_threshold_boundary_inclusive_local`) + Task 6/7 (`test_search_cosine_exactly_threshold_routes_local`) |
| 5. Confidence recorded and in range | Task 10/11 (`test_confidence_in_range_or_none`, `test_confidence_none_vs_zero`) |
| 6. Evidence snippet shape | Task 6/7 (`test_search_snippet_shape`), Task 8/9 (`test_web_maps_results_to_snippet_shape`) |
| 7. Snippet count cap | Task 10/11 (`test_snippet_cap_enforced`) |
| 8. Embedding model separation | Task 1 (`test_embed_model_distinct_from_generative`), Task 4/5 (`test_embed_uses_embed_model_not_generative`), Task 10/11 (`test_embed_model_separation`) |
| 9. Uses configured constants | Implicit — see AC-9 coverage note (plan §2); a hardcoded value breaks `test_snippet_cap_enforced` / `test_threshold_boundary_inclusive_local` / circuit-breaker tests |
| 10. Defensive ingest_error check | Task 10/11 (`test_ingest_error_returns_empty`) |
| 11. Empty clauses input | Task 10/11 (`test_empty_clauses_returns_empty`) |
| 12. Partial update only (no error_count) | Task 10/11 (`test_partial_update_only`) |
| 13. Graceful web-fallback failure | Task 10/11 (`test_web_failure_graceful`), Task 8/9 (`test_web_raises_returns_empty`, `test_web_timeout_returns_empty`) |
| 14. Graceful KB-unavailable failure | Task 10/11 (`test_kb_unavailable_all_web`), Task 6/7 (`test_load_kb_missing_index_returns_none`, `test_load_kb_row_count_mismatch_returns_none`) |
| 15. Determinism of the local path | Task 10/11 (`test_local_path_deterministic`), Task 13 (`test_graph_crag_local_path_real_kb`) |
| 16. Embedding-backend circuit breaker | Task 10/11 (`test_circuit_breaker_opens`, `test_circuit_resets_on_success`) |
