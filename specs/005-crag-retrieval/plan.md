# CRAG Retrieval Technical Plan

## Git Branch

`feature/005-crag-retrieval` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

This plan details how to implement the **CRAG retrieval node (Node 3)** as specified in `specs/005-crag-retrieval/spec.md`. The node gathers supporting **evidence** for each clause produced by ClauseSplitterAgent (Node 2) and routes each clause down one of two evidence-gathering paths based on a per-clause **retrieval confidence**:

- **confidence ≥ `CRAG_CONFIDENCE_THRESHOLD` (0.73)** → Local FAISS clause KB
- **confidence < `CRAG_CONFIDENCE_THRESHOLD` (0.73)** → Live web legal search (DuckDuckGo)

The evidence is merged into each clause's record in the uniform `evidence_snippets` shape, so downstream nodes never need to know which source produced it. The node writes only `clauses` (via the `merge_nested_clause_dicts` reducer) plus `current_node` and `node_timings`, per the partial-update rule (constitution §5).

All configurable thresholds live in `app/config.py` per constitution §3. The embedding model is the BGE-M3 model via `OLLAMA_EMBED_MODEL_NAME`, kept strictly distinct from the generative `OLLAMA_MODEL_NAME` per constitution §8 (model-separation rule).

**Resolved design decisions** (from spec §7):
- **Confidence scoring** (§7.1): `confidence_score = max(0.0, top-1 cosine among top-K FAISS neighbors)`. Query embedding is L2-normalized; the index is inner-product, so inner product = cosine.
- **"Conditional edge" realization** (§7.2): internal Python branching inside a single LangGraph node — **not** a graph-level `add_conditional_edges`. See §5 "Constitution §2 interpretation" below (spec §7.2 requires this plan to document it explicitly).
- **KB provenance** (§7.3): a two-stage offline build pipeline ships with this feature (already built — see §2 "Knowledge base" below).
- **`evidence_trail` ownership** (§7.4): CRAG writes only per-clause `evidence_snippets`; ReportAgent (Node 7) compiles the top-level `evidence_trail` later.
- **Web query** (§7.5): truncated clause text, optionally prefixed with `clause_type`.
- **Processing model** (§7.6): strictly sequential over clauses.
- **KB scoping** (§7.7): single flat index; no `clause_type` filtering.

### Build reality reconciled with spec (the two deltas from KB review)

The knowledge base is already built and validated end-to-end (query-side smoke test: a termination query retrieved `§14.3 — Termination` at cosine 0.8015 → LOCAL_KB). Two elaborations over the spec §7.3 text are recorded here so they are part of the plan of record:

1. **Two-stage build pipeline, not a single utility.** `scripts/build_corpus.py` parses the bundled reference contracts in `app/db/*.md` into `data/kb/clauses_corpus.jsonl` (curation only — no embeddings); `scripts/build_kb.py` embeds that corpus with BGE-M3, L2-normalizes every vector, and writes the FAISS inner-product index + JSONL metadata sidecar. This cleanly separates *curation* from *embedding*.
2. **Real-document seed corpus (109 clauses), not "a few dozen hand-picked."** The corpus is derived from two real Bonterms reference documents (Cloud Terms v1.0 + Data Protection Addendum v1.0) under `app/db/`, yielding 109 reference clauses at BGE-M3 dim 1024. This is richer and more realistic than the spec's illustrative "few dozen."

Neither delta changes a spec decision; both are already implemented. This plan documents the artifacts as they exist.

---

## 2. Files to Create / Modify

### Shared Config Module

#### [MODIFY] `backend/app/config.py`

The four KB-facing constants already exist (`CRAG_CONFIDENCE_THRESHOLD`, `OLLAMA_EMBED_MODEL_NAME`, `CRAG_KB_INDEX_PATH`, `CRAG_KB_METADATA_PATH`). Add the remaining **runtime** constants from spec §6 in the same `# ── CRAG thresholds ──` block, and drop the "only build-utility constants populated so far" note:

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

---

### Knowledge base (ALREADY BUILT — verify only)

The KB artifacts and build scripts already exist and are validated. This plan does **not** rebuild them; the implementation consumes them read-only at runtime.

| Path | Role | Status |
|------|------|--------|
| `backend/scripts/build_corpus.py` | Stage 1: `app/db/*.md` → `data/kb/clauses_corpus.jsonl` (curation) | ✅ exists |
| `backend/scripts/build_kb.py` | Stage 2: corpus → FAISS index + metadata sidecar (embeds + L2-normalizes) | ✅ exists |
| `backend/data/kb/clauses_corpus.jsonl` | 109 curated reference clauses | ✅ 109 rows |
| `backend/data/kb/clauses.faiss` | `IndexFlatIP`, 109 vectors, dim 1024 | ✅ metric = inner product |
| `backend/data/kb/clauses_meta.jsonl` | Sidecar, 1:1 with vector rows, `{snippet_text, source_reference}` | ✅ 109 rows |

The runtime node must mirror `build_kb.py`'s embedding contract exactly (same model, same L2-normalization) — see the shared embedder below.

---

### Retrievers Package

New package `backend/app/graph/nodes/retrievers/`, following the same structure precedent as `parsers/` (Node 1) and `splitters/` (Node 2): a package `__init__.py` exporting the shared return type, plus one module per retrieval concern, each independently testable.

#### [NEW] `backend/app/graph/nodes/retrievers/__init__.py`

Exports the shared `RetrievalResult` dataclass returned by both retrievers, and a snippet-builder helper that enforces the 001 evidence shape.

```python
from dataclasses import dataclass
from typing import Optional, List, Dict, Any


@dataclass
class RetrievalResult:
    """Outcome of one retriever call for a single clause.

    Attributes:
        snippets: Evidence snippets, each a dict with EXACTLY the keys
            {"snippet_text": str, "source_reference": str} (001-schema §3).
            Empty list means "path executed but found nothing".
        top_score: Top-1 cosine similarity for the local-KB path
            (in [0.0, 1.0]); None for the web path (which has no score).
    """
    snippets: List[Dict[str, Any]]
    top_score: Optional[float]


def make_snippet(snippet_text: str, source_reference: str) -> Dict[str, str]:
    """Build an evidence snippet dict in the exact 001 shape.

    Guarantees only the two reserved keys are present so AC-6 holds
    regardless of source path.
    """
    return {"snippet_text": snippet_text, "source_reference": source_reference}
```

Rationale for placement: both `kb_retriever.py` and `web_retriever.py` produce `RetrievalResult` and build snippets via `make_snippet`. Putting these in the package init avoids a cross-dependency between the two retriever modules — identical rationale to `ClauseBoundary` in `splitters/__init__.py` and `ParseResult` in `parsers/__init__.py`.

#### [NEW] `backend/app/graph/nodes/retrievers/embeddings.py`

The single query-embedding entry point, shared by the node. Mirrors `build_kb.py`'s embedding contract so build side and query side agree (spec §7.1 invariant).

```python
def embed_query(text: str, timeout_seconds: int, model_name: str) -> Optional[np.ndarray]:
    """Embed clause/query text with BGE-M3 via Ollama and L2-normalize it.

    Returns a float32 unit vector (L2-normalized so inner product == cosine),
    or None on ANY failure (Ollama unreachable, timeout, zero-norm vector,
    malformed response). Never raises — the caller treats None as
    "un-scorable → web fallback" (spec §4.4).
    """
```

Implementation notes:
- Call `ollama.Client(timeout=timeout_seconds).embeddings(model=model_name, prompt=text)` — the same embeddings API `build_kb.py` uses, but **through a `Client` with the timeout set**, exactly as `llm_refiner.py:102` does for `chat`. (Confirmed at build time: BGE-M3 returns a 1024-d vector with raw norm ≈ 25.7, i.e. it is NOT self-normalized — query-side L2-normalization is load-bearing, not cosmetic.)
- **The `Client(timeout=…)` is the primary bound, not the executor.** This is the correction the reviewer flagged: `build_kb.py` uses the *bare* `ollama.embeddings(...)` with no timeout (acceptable for an offline script where blocking is fine), but the runtime node must NOT copy that. `llm_refiner`'s timeout is robust because the underlying `httpx` call itself aborts via `ollama.Client(timeout=…)` — which lets the worker thread die so exiting the `ThreadPoolExecutor` context manager (`shutdown(wait=True)`) returns promptly. If `embed_query` bounded only with `future.result(timeout=30)` over a *bare* `ollama.embeddings` call, then on a hung Ollama socket `future.result` would return after 30s but the worker thread would still be blocked in the HTTP read, and exiting the `with ThreadPoolExecutor(...)` block would hang indefinitely on `shutdown(wait=True)`. That would defeat both `CRAG_EMBED_TIMEOUT_SECONDS` and the circuit breaker (whose entire justification — spec Edge Case 13, Risk row 1 — is bounding runtime when Ollama is unreachable). So: `Client(timeout=…)` aborts the call; the `ThreadPoolExecutor(max_workers=1)` + `future.result(timeout=timeout_seconds)` is a backstop, not the sole bound.
- Catch `concurrent.futures.TimeoutError`, `httpx.TimeoutException`, and any `Exception` → return `None` with a rate-limited warning.
- L2-normalize: `vec / norm`; if `norm < 1e-12` return `None` (same zero-norm guard as `build_kb.py`).
- Model-separation assertion belongs in the node/config layer, not here; this function trusts the passed-in `model_name`.

#### [NEW] `backend/app/graph/nodes/retrievers/kb_retriever.py`

Loads the FAISS index + metadata sidecar once (cached), and searches per clause.

```python
def load_kb() -> Optional["_LoadedKB"]:
    """Load and cache the FAISS index + metadata sidecar.

    Returns a handle exposing the loaded index and the row->snippet metadata,
    or None if the KB is unavailable (missing/corrupt index, missing sidecar,
    or a row/vector count mismatch). Logs a SINGLE node-level warning on the
    first unavailability (spec §4.5 / AC-14). Cached module-level so the index
    is not re-read per clause.
    """

def search_kb(kb, query_vec: np.ndarray, top_k: int) -> RetrievalResult:
    """Search the loaded KB with an L2-normalized query vector.

    Returns RetrievalResult(snippets=top_k KB snippets in the 001 shape,
    top_score=max(0.0, best cosine)). If the index holds fewer than top_k
    vectors, returns whatever exists. If zero vectors, top_score=0.0 and
    snippets=[] (spec §4.6).
    """
```

Implementation notes:
- **Path resolution (spec §6 anchor):** resolve `config.CRAG_KB_INDEX_PATH` / `CRAG_KB_METADATA_PATH` against the **backend/ directory**, computed as `Path(config.__file__).resolve().parent.parent` (config lives at `backend/app/config.py`), *not* the raw CWD. A private `_resolve_backend_path(rel)` helper does this so tests and the app agree on one location regardless of where Python was launched. This matches how `build_kb.py` anchors via `BACKEND_DIR`.
- **Metadata load:** read the JSONL sidecar into a `list[dict]`; row index = FAISS vector ID (the 1:1 guarantee from §7.3). Assert `len(meta) == index.ntotal`; on mismatch treat the KB as unavailable (corrupt) → `None`.
- **`top_score` clamp:** `max(0.0, float(D[0][0]))` — the top-1 clamp pinned in §7.1. Inner-product on unit vectors is already in `[-1, 1]`; clamping at 0 yields `[0, 1]`.
- **Caching + tests:** the loaded KB is cached in a module-level global; expose a way to reset/replace it (or load lazily on first call) so tests can monkeypatch `load_kb` / inject a tiny fixture index. Follow the module-level-name re-exposure convention used in Node 2 so `CRAG_TOP_K` etc. are monkeypatchable.

#### [NEW] `backend/app/graph/nodes/retrievers/web_retriever.py`

The DuckDuckGo web-search fallback. **Never raises** — the exception boundary here is load-bearing (spec §4.8 / AC-13).

```python
def web_search(query: str, max_results: int, timeout_seconds: int) -> RetrievalResult:
    """Search the web via DuckDuckGo for legal evidence on a clause.

    Returns RetrievalResult(snippets=up to max_results snippets in the 001
    shape, top_score=None). On ANY failure (rate-limit, network, library
    error, timeout, zero results) returns RetrievalResult([], None) — never
    raises (spec §4.7, §4.8, AC-13).
    """
```

Implementation notes:
- **Import name (spec §4.8 pin):** use `from duckduckgo_search import DDGS` — this is the package currently installed (`duckduckgo-search>=6.0.0`, per `specs/002-tech-stack.md` §3c). The library is being renamed to `ddgs` upstream; if the import fails, fall back to `from ddgs import DDGS`. Wrap the import so an unavailable library degrades to "zero results," never an import crash at node load.
- **Exact invocation + result mapping (spec §4.8 pin; constitution §8 — leave nothing for the impl model to invent):** call `DDGS().text(query, max_results=max_results)`. Each DDG result is a dict `{"title": ..., "href": ..., "body": ...}`. Map it as:
  - `snippet_text` ← `result["body"]` (the text snippet)
  - `source_reference` ← `result["href"]` (the result URL)
  via `make_snippet(...)`. Skip any result missing a non-empty `body` or `href` rather than emitting an empty-keyed snippet (protects AC-6). Iterate the `.text()` result (it may be a generator) and stop at `max_results`.
- **Query construction (spec §7.5):** the passed-in `query` is already the truncated clause text (optionally `clause_type`-prefixed by the node).
- **Broad catch:** wrap the whole call in `try/except Exception` → return `RetrievalResult([], None)`, logging a rate-limited warning. Do not catch only a specific timeout type.
- **Timeout — and its limit (reviewer #1, web half):** enforce `CRAG_WEB_TIMEOUT_SECONDS` via the same `ThreadPoolExecutor` + `future.result(timeout=…)` pattern. **Unlike `embed_query`, there is no `Client(timeout=…)` equivalent for `DDGS`**, so the executor is the *only* bound: on a hung socket `future.result` returns after the timeout but the worker thread stays blocked in the HTTP read, and `shutdown(wait=True)` at context-manager exit would hang. Mitigate by passing a session/socket timeout into `DDGS` if the installed version supports it (e.g. its `timeout=` constructor arg); if it does not, **document that the web worker thread can outlive `CRAG_WEB_TIMEOUT_SECONDS`** and use a non-blocking executor exit (do not rely on `with ThreadPoolExecutor` implicit `shutdown(wait=True)`; submit and abandon the future, or use `shutdown(wait=False)`). Either way the node itself must not block past the timeout — the whole point of AC-13.

---

### CRAG Retrieval Node

#### [NEW] `backend/app/graph/nodes/crag_retrieval_agent.py`

The LangGraph node — the only file that touches `ContractState`. Owns the per-clause loop, the confidence routing, and the circuit breaker.

```python
import app.config as _config  # module import so tests can monkeypatch (Node 2 precedent)

logger = logging.getLogger("contractsentinel.crag_retrieval")

# Re-exposed module-level names for monkeypatching (mirrors clause_splitter_agent.py):
OLLAMA_EMBED_MODEL_NAME = _config.OLLAMA_EMBED_MODEL_NAME
OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME
CRAG_CONFIDENCE_THRESHOLD = _config.CRAG_CONFIDENCE_THRESHOLD
CRAG_TOP_K = _config.CRAG_TOP_K
CRAG_WEB_MAX_RESULTS = _config.CRAG_WEB_MAX_RESULTS
CRAG_MAX_EVIDENCE_SNIPPETS = _config.CRAG_MAX_EVIDENCE_SNIPPETS
CRAG_QUERY_MAX_CHARS = _config.CRAG_QUERY_MAX_CHARS
CRAG_EMBED_TIMEOUT_SECONDS = _config.CRAG_EMBED_TIMEOUT_SECONDS
CRAG_WEB_TIMEOUT_SECONDS = _config.CRAG_WEB_TIMEOUT_SECONDS
CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD = _config.CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD


def crag_retrieval_agent(state: ContractState) -> dict:
    """LangGraph Node 3. Reads clauses/document_id/ingest_error; returns partial
    dict: clauses (per-clause evidence updates), current_node, node_timings."""
```

**Internal flow:**

```
1.  current_node = "crag_retrieval"; record start_time.
2.  Defensive: if state.get("ingest_error") is not None → return empty update
    (clauses={}, current_node, node_timings). No embed/FAISS/web calls. (AC-10)
3.  clauses = state.get("clauses", {}).
    If not clauses → log warning, return empty update. No external calls. (AC-11)
4.  kb = load_kb()  # None if KB unavailable → single warning (AC-14); every
    clause will route web with confidence 0.0.
5.  Circuit-breaker state: consecutive_failures = 0; circuit_open = False.
6.  For each clause_id, record in document order (by position):
      a. text = (record.get("text") or "").strip()
         If empty → confidence=None, path=None, snippets=None; log warning;
         continue. (spec §4.3)
      b. query = text[:CRAG_QUERY_MAX_CHARS]  (log at debug if truncated, §4.11)
      c. query_vec = None
         if not circuit_open:
             query_vec = embed_query(query, CRAG_EMBED_TIMEOUT_SECONDS,
                                     OLLAMA_EMBED_MODEL_NAME)
             if query_vec is None:                       # embed failed
                 consecutive_failures += 1
                 if consecutive_failures >= CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD:
                     circuit_open = True
                     logger.warning("CRAG embedding circuit opened ...")  # once
             else:
                 consecutive_failures = 0                # reset on success
      d. Decide confidence + path (initialize kb_result = None first, so the
         LOCAL_KB read in step 6e can never hit UnboundLocalError — reviewer #5):
           if kb is None:                 # KB unavailable
               confidence = 0.0 if query_vec is not None else None
               path = WEB_FALLBACK
           elif query_vec is None:        # couldn't embed (or circuit open)
               confidence = None
               path = WEB_FALLBACK
           else:
               kb_result = search_kb(kb, query_vec, CRAG_TOP_K)
               confidence = kb_result.top_score          # max(0, top-1 cosine)
               if confidence >= CRAG_CONFIDENCE_THRESHOLD:  # inclusive (AC-4)
                   path = LOCAL_KB
               else:
                   path = WEB_FALLBACK
      e. Gather evidence for the chosen path:
           if path == LOCAL_KB:
               snippets = kb_result.snippets
           else:  # WEB_FALLBACK
               web_result = web_search(query, CRAG_WEB_MAX_RESULTS,
                                       CRAG_WEB_TIMEOUT_SECONDS)
               snippets = web_result.snippets            # [] on any failure
      f. Cap: snippets = snippets[:CRAG_MAX_EVIDENCE_SNIPPETS]  (AC-7)
      g. Stage per-clause update: {clause_id: {confidence_score, path_taken,
         evidence_snippets}}  — only the three evidence fields; the reducer
         preserves text/position/etc. (spec §4.12)
      h. Emit a per-clause structured log record (confidence, path, snippet
         count, embed/web latency) via logger.info(..., extra={...}). (spec §8)
7.  elapsed = time.monotonic() - start_time
8.  Return {"clauses": <merged per-clause updates>, "current_node": current_node,
    "node_timings": {current_node: elapsed}}.   ONLY these keys — no error_count. (AC-12)
```

**Confidence semantics — `None` vs `0.0` (plan refinement of spec §4.4–§4.6):** the spec leaves a small ambiguity between "un-scorable" and "zero local confidence." This plan pins the distinction so it is testable:
- `confidence_score = None` → **could not produce a query vector** (empty text handled separately; embedding failure; circuit open). No cosine exists.
- `confidence_score = 0.0` → **a query vector exists but the KB yielded no usable match** (KB unavailable, or zero/weak neighbors below threshold that still routes web).
Both route to `WEB_FALLBACK`; only the recorded score differs. This honors AC-5 ("`None` only on scoring failure") and Edge Cases 5/6 ("zero local confidence").

**Return shape (success):**
```python
{"clauses": clause_updates, "current_node": "crag_retrieval",
 "node_timings": {"crag_retrieval": elapsed}}
```

**Return shape (defensive — ingest_error set, or empty clauses):**
```python
{"clauses": {}, "current_node": "crag_retrieval",
 "node_timings": {"crag_retrieval": elapsed}}
```

Like Node 2, this node never sets `error_count` — every failure mode is a graceful degradation, not a pipeline error (spec §2 "Error accounting", AC-12).

---

### Graph Wiring

#### [MODIFY] `backend/app/graph/builder.py`

Register the CRAG node and replace the temporary `clause_splitter → END` edge with `clause_splitter → crag_retrieval → END`:

```python
from app.graph.nodes.crag_retrieval_agent import crag_retrieval_agent

# Inside build_graph():
graph.add_node("crag_retrieval", crag_retrieval_agent)
graph.add_edge("clause_splitter", "crag_retrieval")  # was END temporarily
graph.add_edge("crag_retrieval", END)                # → END until feature-006
```

**Constitution §2 interpretation (spec §7.2 requires this be documented):** CRAG's "confidence-based routing" is one of the two conditional edges the constitution permits, but it is realized as **internal Python branching inside `crag_retrieval_agent`**, NOT as a graph-level `add_conditional_edges`. The reason is structural: a graph-level conditional edge routes the *whole* `ContractState` to one successor, but CRAG routes **per clause**, and all clauses live in one state object held by one node. A single node with an internal `if confidence >= threshold` loop is therefore the only faithful realization of per-clause routing without a `Send`-API map-reduce subgraph (rejected for Phase 1 as unnecessary complexity, §7.2). `builder.py` adds exactly one node with a plain linear `add_edge`, keeping the "7 sequential nodes" framing intact. The node name string `"crag_retrieval"` matches the pinned `current_node` value (spec §2) so state-key identity never drifts from the graph node name.

---

### Unit Tests

#### [NEW] `backend/tests/unit/test_embeddings.py`

Tests for `embed_query()` — mocks `ollama.embeddings`, no running Ollama:

| Test | Verifies |
|------|----------|
| `test_embed_returns_l2_normalized_vector` | Output vector has L2 norm ≈ 1.0 (query-side normalization applied) |
| `test_embed_uses_embed_model_not_generative` | `ollama.embeddings` called with `OLLAMA_EMBED_MODEL_NAME`, never `OLLAMA_MODEL_NAME` (AC-8) |
| `test_embed_timeout_returns_none` | Simulated timeout → `None`, warning logged |
| `test_embed_connection_error_returns_none` | Ollama unreachable → `None` |
| `test_embed_zero_norm_returns_none` | Zero-norm vector → `None` (guard) |
| `test_embed_malformed_response_returns_none` | Missing `"embedding"` key → `None` |

#### [NEW] `backend/tests/unit/test_kb_retriever.py`

Tests for `load_kb()` / `search_kb()` — build a tiny in-memory FAISS index fixture (a handful of known unit vectors) so cosines are exact and routing is deterministic:

| Test | Verifies |
|------|----------|
| `test_search_returns_top1_cosine` | `top_score` == max cosine among neighbors (§7.1) |
| `test_search_snippet_shape` | Each snippet has exactly `snippet_text` + `source_reference` (AC-6) |
| `test_search_cosine_exactly_threshold_routes_local` | A neighbor at cosine == 0.73 yields `top_score == 0.73` (feeds AC-4) |
| `test_search_fewer_than_topk` | KB with < `CRAG_TOP_K` vectors → returns all available (§4.6) |
| `test_search_zero_vectors_score_zero` | Empty index → `top_score == 0.0`, snippets == [] |
| `test_load_kb_missing_index_returns_none` | Missing index file → `None`, single warning (AC-14) |
| `test_load_kb_row_count_mismatch_returns_none` | `len(meta) != index.ntotal` → treated as corrupt → `None` |
| `test_load_kb_cached` | Second `load_kb()` does not re-read the index file |
| `test_path_resolved_relative_to_backend` | Paths resolve against backend/ dir, not raw CWD |

#### [NEW] `backend/tests/unit/test_web_retriever.py`

Tests for `web_search()` — mocks `DDGS`, no network:

| Test | Verifies |
|------|----------|
| `test_web_maps_results_to_snippet_shape` | DDG results → snippets with exactly the two 001 keys (AC-6) |
| `test_web_respects_max_results` | No more than `CRAG_WEB_MAX_RESULTS` requested |
| `test_web_top_score_is_none` | `RetrievalResult.top_score is None` on the web path |
| `test_web_zero_results_returns_empty` | Empty results → `RetrievalResult([], None)` (§4.7) |
| `test_web_raises_returns_empty` | DDG raises (rate-limit/network) → `([], None)`, no crash (AC-13) |
| `test_web_timeout_returns_empty` | Simulated timeout → `([], None)` (§4.8) |
| `test_web_import_fallback` | Library-unavailable degrades to zero results, not an import crash |

#### [NEW] `backend/tests/unit/test_crag_retrieval_agent.py`

Tests for the node function — mock `embed_query`, `load_kb`/`search_kb`, and `web_search` at the module level (Node 2 monkeypatch precedent):

| Test | Verifies |
|------|----------|
| `test_all_clauses_get_three_fields` | Every clause gets `confidence_score`, `path_taken`, `evidence_snippets` (AC-1) |
| `test_high_confidence_routes_local` | top-1 cosine ≥ threshold → `LOCAL_KB`, KB-sourced snippets (AC-2) |
| `test_low_confidence_routes_web` | top-1 cosine < threshold → `WEB_FALLBACK`, web snippets (AC-3) |
| `test_threshold_boundary_inclusive_local` | cosine == 0.73 → `LOCAL_KB` (AC-4) |
| `test_confidence_in_range_or_none` | Every `confidence_score` is `None` or in `[0,1]` (AC-5) |
| `test_snippet_cap_enforced` | With `CRAG_MAX_EVIDENCE_SNIPPETS` monkeypatched **below** `CRAG_TOP_K` / `CRAG_WEB_MAX_RESULTS`, no clause exceeds the cap (AC-7 — the cap only truncates when set below the source counts) |
| `test_embed_model_separation` | Embedding uses `OLLAMA_EMBED_MODEL_NAME` ≠ `OLLAMA_MODEL_NAME` (AC-8) |
| `test_ingest_error_returns_empty` | `ingest_error` set → empty update, no embed/FAISS/web calls (AC-10) |
| `test_empty_clauses_returns_empty` | `clauses == {}` → empty update, warning, no calls (AC-11) |
| `test_partial_update_only` | Return dict keys are exactly `{clauses, current_node, node_timings}`; no `error_count` (AC-12) |
| `test_web_failure_graceful` | Web raises/timeout → `WEB_FALLBACK`, `[]`, recorded score, no crash, other clauses proceed (AC-13) |
| `test_kb_unavailable_all_web` | `load_kb()` → None → every clause `WEB_FALLBACK`, one warning (AC-14) |
| `test_local_path_deterministic` | Same text + same index + deterministic embed → same snippets + score (AC-15) |
| `test_circuit_breaker_opens` | After `CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD` consecutive embed failures, remaining clauses skip embedding (no timeout), one "circuit opened" warning (AC-16) |
| `test_circuit_resets_on_success` | An interleaved success resets the consecutive counter (circuit does not trip on intermittent failures) |
| `test_empty_clause_text_skipped` | Whitespace-only clause → all three fields `None`, no embed call (§4.3) |
| `test_current_node_pinned` | `current_node == "crag_retrieval"` and same key in `node_timings` |
| `test_confidence_none_vs_zero` | Embed-failure → `None`; KB-unavailable-with-vector → `0.0` (plan refinement) |

> **AC-9 coverage note (reviewer #4):** AC-9 ("all constants read from `app.config`, never hardcoded") has **no dedicated test row** — it is covered only *implicitly*: a hardcoded threshold or cap would break `test_threshold_boundary_inclusive_local`, `test_snippet_cap_enforced`, and the circuit-breaker tests (all of which rely on monkeypatching the module-level names). This is accepted coverage, not full coverage; flagged so it isn't mistaken for a direct assertion.

#### [MODIFY] `backend/tests/unit/test_config.py`

| Test | Verifies |
|------|----------|
| `test_crag_runtime_constants_match_spec` | `CRAG_TOP_K`, `CRAG_WEB_MAX_RESULTS`, `CRAG_MAX_EVIDENCE_SNIPPETS`, `CRAG_QUERY_MAX_CHARS`, `CRAG_EMBED_TIMEOUT_SECONDS`, `CRAG_WEB_TIMEOUT_SECONDS`, `CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD` match spec §6 |
| `test_crag_constants_correct_types` | Types: `int` for the counts/timeouts, `float` for the threshold, `str` for model/paths |
| `test_embed_model_distinct_from_generative` | `OLLAMA_EMBED_MODEL_NAME != OLLAMA_MODEL_NAME` (constitution §8, AC-8) |

---

### Integration Tests

#### [NEW] `backend/tests/integration/test_crag_retrieval_graph.py`

CRAG wired into the graph. Embedding and web calls are mocked (no live Ollama / no network); the **real built FAISS KB** is used so the local path is exercised end-to-end:

| Test | Verifies |
|------|----------|
| `test_graph_ingest_clause_crag_success` | Full path Node1→Node2→Node3 reaches END with every clause carrying the three evidence fields |
| `test_graph_ingest_error_skips_crag` | Ingest error short-circuits to END without reaching CRAG |
| `test_graph_crag_local_path_real_kb` | A clause routes `LOCAL_KB` (cosine ≥ 0.73) against the real 109-vector index, using the fixture vector described below |
| `test_graph_crag_web_fallback_on_low_confidence` | A clause routes `WEB_FALLBACK` — mock `embed_query` to return a vector orthogonal to the KB (e.g. a random unit vector, top-1 cosine well below 0.73); mocked web |
| `test_graph_checkpointing_after_crag` | State is checkpointed after CRAG completes |

**Deterministic-embed fixture (reviewer #3):** `test_graph_crag_local_path_real_kb` mocks `embed_query`, so the returned vector must be one that actually clears 0.73 against the real index — an arbitrary vector will not. Obtain it deterministically by **reading row 0 back out of the real FAISS index** at test setup: `faiss.read_index(<resolved CRAG_KB_INDEX_PATH>).reconstruct(0)` yields the exact (already L2-normalized) vector for corpus row 0, whose top-1 self-similarity is 1.0 → guaranteed `LOCAL_KB`. Mock `embed_query` to return that vector, and assert the routed snippet's `source_reference` equals `clauses_meta.jsonl` row 0's `source_reference`. This keeps the test fully deterministic and offline (no live Ollama) while still exercising the real index. (Reconstructing a stored row avoids re-embedding, so it does not depend on BGE-M3 being installed in CI.)

**Note:** a separate *manual* end-to-end test (not in the automated suite) can run with live Ollama (`bge-m3`) + real DuckDuckGo, as validated during the KB smoke test.

---

## 3. Dependency & Import Map

```
app/config.py
    └── (no imports — pure constants)

app/graph/nodes/retrievers/__init__.py
    └── dataclasses, typing (stdlib — defines RetrievalResult, make_snippet)

app/graph/nodes/retrievers/embeddings.py
    ├── concurrent.futures, logging (stdlib)
    ├── numpy
    ├── httpx (timeout type), ollama
    └── (no app imports — model_name passed in)

app/graph/nodes/retrievers/kb_retriever.py
    ├── json, logging (stdlib); pathlib.Path
    ├── faiss, numpy
    ├── app.graph.nodes.retrievers (RetrievalResult, make_snippet)
    └── app.config — for CRAG_KB_INDEX_PATH / CRAG_KB_METADATA_PATH and the
                     backend/-dir anchor (Path(config.__file__).parent.parent)

app/graph/nodes/retrievers/web_retriever.py
    ├── concurrent.futures, logging (stdlib)
    ├── duckduckgo_search.DDGS  (fallback: ddgs.DDGS) — guarded import
    └── app.graph.nodes.retrievers (RetrievalResult, make_snippet)

app/graph/nodes/crag_retrieval_agent.py
    ├── time, logging (stdlib)
    ├── app.graph.state (ContractState, RetrievalPath)
    ├── app.graph.nodes.retrievers.embeddings (embed_query)
    ├── app.graph.nodes.retrievers.kb_retriever (load_kb, search_kb)
    ├── app.graph.nodes.retrievers.web_retriever (web_search)
    └── app.config — imported AS A MODULE (`import app.config as _config`) with
                     the CRAG constants re-exposed as module-level names, read by
                     bare name so tests can monkeypatch them (Node 2 precedent,
                     clause_splitter_agent.py:29,40-43).

app/graph/builder.py
    ├── langgraph.graph (StateGraph, END)
    ├── app.graph.state (ContractState)
    ├── app.graph.nodes.ingest_agent (ingest_agent)
    ├── app.graph.nodes.clause_splitter_agent (clause_splitter_agent)
    └── app.graph.nodes.crag_retrieval_agent (crag_retrieval_agent)
```

---

## 4. Implementation Order

Following TDD per constitution §7 — tests written and confirmed failing before implementation.

| Step | Action | Files |
|------|--------|-------|
| 1 | Write config tests for new CRAG runtime constants (confirm failing) | `tests/unit/test_config.py` |
| 2 | Add CRAG runtime constants to config | `app/config.py` |
| 3 | Run config tests (confirm passing) | — |
| 4 | Implement `RetrievalResult` + `make_snippet` in retrievers package | `app/graph/nodes/retrievers/__init__.py` |
| 5 | Write unit tests for `embed_query` (confirm failing) | `tests/unit/test_embeddings.py` |
| 6 | Implement `embeddings.py` | `app/graph/nodes/retrievers/embeddings.py` |
| 7 | Run embed tests (confirm passing) | — |
| 8 | Write unit tests for KB retriever with a tiny fixture index (confirm failing) | `tests/unit/test_kb_retriever.py` |
| 9 | Implement `kb_retriever.py` | `app/graph/nodes/retrievers/kb_retriever.py` |
| 10 | Run KB retriever tests (confirm passing) | — |
| 11 | Write unit tests for web retriever (confirm failing) | `tests/unit/test_web_retriever.py` |
| 12 | Implement `web_retriever.py` | `app/graph/nodes/retrievers/web_retriever.py` |
| 13 | Run web retriever tests (confirm passing) | — |
| 14 | Write unit tests for `crag_retrieval_agent` node (confirm failing) | `tests/unit/test_crag_retrieval_agent.py` |
| 15 | Implement `crag_retrieval_agent.py` | `app/graph/nodes/crag_retrieval_agent.py` |
| 16 | Run node tests (confirm passing) | — |
| 17 | Update graph builder (add crag node, rewire clause_splitter → crag → END) | `app/graph/builder.py` |
| 18 | Write and run integration tests (real KB, mocked embed/web) | `tests/integration/test_crag_retrieval_graph.py` |
| 19 | Full test suite pass (all existing + new) | all tests |

> **Note on Step 4**: `RetrievalResult`/`make_snippet` in `retrievers/__init__.py` are shared types (like `ClauseBoundary` / `ParseResult`) — data structures, not feature logic, so they precede the retriever tests that import them, without their own TDD cycle.

---

## 5. Design Decisions & Rationale

### Confidence = top-1 FAISS cosine (spec §7.1)
Pinned so ACs 2–4 are constructible fixtures: mock the KB to return a neighbor at a chosen cosine and assert the route. Top-1 answers the right question for a corrective-retrieval gate ("is there at least one strong local match?"), is fully deterministic, and adds zero per-clause generative-LLM cost over 100–200 clauses (constitution §9). An LLM grader was rejected as expensive, non-deterministic, and an overreach into Node 4's job.

### Normalization on both sides is load-bearing (spec §7.1)
Inner-product == cosine only if vectors are unit-length. `build_kb.py` normalizes every KB vector; `embed_query` normalizes every query vector. Confirmed empirically that BGE-M3 raw output norm ≈ 25.7 (not self-normalized), so skipping query-side normalization would silently break the 0.73 threshold. Both `test_embed_returns_l2_normalized_vector` and the build script's zero-norm guard enforce this.

### Internal branching, not a graph conditional edge (spec §7.2)
Documented in §2 "Graph Wiring" above. Per-clause routing cannot be expressed as a graph-level conditional edge because one node holds all clauses; the `Send` map-reduce alternative is deferred as unnecessary for Phase 1.

### Circuit breaker as a routing guarantee, not an optimization (spec §4.13, AC-16)
Without it, an unreachable Ollama makes every clause pay `CRAG_EMBED_TIMEOUT_SECONDS` (~30s) before falling back — pathological over a large contract. After `CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD` **consecutive** embed failures, the node stops embedding for the rest of the run and routes remaining clauses straight to web. The counter resets on any success, so intermittent single failures never trip it. Per-run only; not persisted.

### `None` vs `0.0` confidence
Pinned in §2 (node flow) to remove the spec's §4.4–§4.6 ambiguity: `None` = no query vector could be produced; `0.0` = a vector exists but the KB gave no usable match. Both route web; the distinction keeps AC-5 and Edge Cases 5/6 mutually consistent and testable.

### Separate retriever modules
`embeddings.py` / `kb_retriever.py` / `web_retriever.py` are independently testable (embed + KB need no network; web is mock-only) and independently replaceable — same rationale as splitting `regex_splitter.py` / `llm_refiner.py` in Node 2 and the parsers in Node 1.

### No `error_count` increment
Every CRAG failure mode has a defined graceful fallback (web on embed failure, `[]` on web failure, all-web on KB-unavailable). None compromises pipeline correctness, so `error_count` stays out of the partial update — required for AC-12. Same stance as Node 2.

### Logging strategy (spec §8)
Named logger `contractsentinel.crag_retrieval`. `ContractState` carries only aggregate `node_timings["crag_retrieval"]`; all per-clause metrics (confidence, path, embed/web latency, snippet count) are emitted as `logger.info(..., extra={...})` structured records for the eval harness (`specs/002-tech-stack.md` §3i) — never added as per-clause state fields. Mirrors `clause_splitter_agent.py`.

---

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Ollama / `bge-m3` not running at pipeline time | Every embed fails | `embed_query` uses `ollama.Client(timeout=…)` so each call actually aborts (not just the executor — see embeddings.py notes); circuit breaker then collapses the remaining cost to a fixed constant; all clauses route web with `confidence=None`; single warning |
| Hung Ollama/DDG socket outliving the executor timeout | Node blocks past the configured timeout, defeating the breaker | Embed: `Client(timeout=…)` aborts the underlying call. Web: no client timeout available → pass a `DDGS(timeout=…)` if supported, else non-blocking executor exit (`shutdown(wait=False)`/abandon future) so the node never blocks past `CRAG_WEB_TIMEOUT_SECONDS` |
| DuckDuckGo rate-limiting / library rename to `ddgs` | Web path raises or import fails | Broad `except Exception` → zero results (AC-13); guarded import with `ddgs` fallback; tech-stack §3c accepts the reliability tradeoff |
| FAISS index / sidecar missing or corrupt | Local path unusable | `load_kb()` → None, single warning, all clauses web (AC-14); row/vector count mismatch treated as corrupt |
| Query-side normalization forgotten | 0.73 threshold silently meaningless | `embed_query` normalizes + unit-norm test; build script normalizes + zero-norm guard |
| Embedding dim drift (index built at 1024) | FAISS search dimension mismatch → crash | Same model on both sides (`OLLAMA_EMBED_MODEL_NAME`); integration test searches the real index; mismatch surfaces immediately |
| Large clause count × per-call timeouts | Slow aggregate runtime | Circuit breaker bounds the embed cost; sequential processing keeps memory flat; per-call timeouts bound each call (constitution §9) |
| Windows path / CWD ambiguity for KB files | KB "not found" depending on launch dir | Resolve against backend/ dir via `Path(config.__file__).parent.parent`, not raw CWD |
| `retrieved_at` drift (spec §7.4) | Report timestamp ≠ true retrieval time | Explicitly accepted for Phase 1; a true per-snippet timestamp is a future 001-schema change under constitution §10 |

---

## 7. Out of Scope for This Plan

- **Nodes 4–7**: not wired or implemented. `builder.py` routes `crag_retrieval` → END until feature-006 (Self-RAG).
- **Evidence evaluation / ISREL / ISSUP / discard-vs-validate**: Self-RAG (Node 4), `specs/006`.
- **The retry-with-max-3 loop**: Self-RAG, not here.
- **`evidence_trail` compilation**: ReportAgent (Node 7).
- **KB corpus curation / expansion**: the build scripts and 109-clause seed already ship; ongoing curation is deferred (spec §5.4).
- **LLM-generated search queries / knowledge refinement (strip decompose-recompose)**: deferred (spec §5.5, §7.5).
- **A third "ambiguous" confidence bucket**: constitution §2 mandates the binary 0.73 split (spec §5.6).
- **Bounded-parallelism over clauses**: sequential for Phase 1; a config knob is deferred (spec §7.6).
- **`clause_type`-scoped retrieval**: flat index only (spec §7.7).
- **Paid search APIs / arbitrary URL scraping**: excluded (spec §5.8, tech-stack §5).
- **API endpoints, DB storage, MCP delivery, privacy/security**: per Phase 2 deferral / other specs.
