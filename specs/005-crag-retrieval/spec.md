# CRAG Retrieval Specification

## 1. Problem Statement

The CRAG (Corrective Retrieval-Augmented Generation) retrieval node is **Node 3** of the fixed 7-node pipeline defined in `specs/000-constitution.md`. Its responsibility is to gather supporting **evidence** for each clause produced by ClauseSplitterAgent (Node 2), so that the downstream Self-RAG validation node (Node 4) has grounded material to judge each clause against.

Per constitution §2, this node operates **per clause** and scores a **retrieval confidence** for each one, then routes that clause down one of two evidence-gathering paths:

- **confidence ≥ `CRAG_CONFIDENCE_THRESHOLD` (0.73)** → **Local clause KB** (FAISS vector search over a curated legal-clause knowledge base)
- **confidence < `CRAG_CONFIDENCE_THRESHOLD` (0.73)** → **Live legal search** (web fallback via DuckDuckGo)

Regardless of which path a clause takes, the retrieved evidence is **merged into that clause's record** in a uniform shape (`evidence_snippets`), so downstream nodes never need to know which source path produced the evidence.

This node is the site of the **first of the two conditional routing decisions** the constitution permits (the second being `route_on_risk` at Node 6). The "corrective" nature of CRAG is exactly this: when local retrieval is not confident enough to be trustworthy, the node *corrects* by reaching out to a live external source rather than proceeding on weak local matches.

**Why this node exists where it does:** Clause boundaries must already be established (Node 2) before evidence can be retrieved per clause, and evidence must be gathered (Node 3) before it can be validated (Node 4). CRAG is the bridge between "we have discrete clauses" and "we have grounded evidence to reason about each clause."

**Model-separation note (constitution §8):** This node is the first to use the **embedding model** (BGE-M3 via Ollama). The embedding model is a distinct concern from the generative Qwen3 models and MUST NOT be the same model object or the same config constant as `OLLAMA_MODEL_NAME`. A separate `OLLAMA_EMBED_MODEL_NAME` constant is introduced by this spec (see §6).

## 2. Inputs and Outputs

### Inputs

CRAG retrieval reads the following from `ContractState` (as defined in `specs/001-contract-state-schema.md`):

- `clauses`: `Dict[str, Dict[str, Any]]` — the per-clause dict produced by Node 2. For each clause record, this node reads:
  - `text`: `str` — the clause text; the retrieval query is derived from this
  - `position`: `int` — used for ordering/logging only
  - `section_number`: `Optional[str]` — used for logging only
  - `clause_type`: `Optional[ClauseType]` — read for logging only; it does NOT scope retrieval in Phase 1 (Decision §7.7)
- `document_id`: `str` — for logging only
- `ingest_error`: `Optional[Dict[str, str]]` — checked defensively; if set, the node returns without processing (routing already prevents reaching this node on error, but the node checks defensively — same pattern as Node 2)

### Outputs

CRAG retrieval writes back into the **existing `clauses` dict** using the `merge_nested_clause_dicts` reducer defined in `specs/001-contract-state-schema.md`. It adds the following fields to **each** clause record (it does NOT create new clause IDs and does NOT modify `text`, `position`, `section_number`, or `clause_type`):

| Field | Type | Description |
|-------|------|-------------|
| `confidence_score` | `Optional[float]` | Retrieval confidence for this clause, in `[0.0, 1.0]`. This is the score compared against `CRAG_CONFIDENCE_THRESHOLD`. `None` only if scoring could not be performed (e.g. embedding failure — see Edge Cases). |
| `path_taken` | `Optional[RetrievalPath]` | Which path produced this clause's evidence: `RetrievalPath.LOCAL_KB` (`"local_kb"`) or `RetrievalPath.WEB_FALLBACK` (`"web_fallback"`). `None` only if no retrieval path could be executed. |
| `evidence_snippets` | `Optional[List[Dict[str, Any]]]` | The merged evidence for this clause. Each entry has exactly: `snippet_text: str` and `source_reference: str` (as specified in 001). An empty list `[]` means "path executed but no evidence found"; `None` means "no path executed". |

These field names are already reserved for exactly this purpose in `specs/001-contract-state-schema.md` §3 (the clause-record comment block). This spec introduces no new clause-record field names.

**Partial-update rule (constitution §5):** The node returns ONLY `clauses` (carrying the per-clause evidence updates), plus `current_node` and `node_timings` for pipeline metadata. It does NOT return or modify any IngestAgent-owned keys, any Self-RAG/RiskScore/Redline/Report keys, or the top-level `evidence_trail` — that list is compiled later by ReportAgent (Node 7) from the per-clause `evidence_snippets` (Decision §7.4).

**Pinned state-key value:** `current_node` is set to the string `"crag_retrieval"`, and that same string is the key used in the `node_timings` update. This is the node's *state-key identity* and is fixed here so it does not drift from the graph node name registered in `builder.py` (constitution §8 — nothing may be left to a smaller model's inference). Note this mirrors how Node 2 pins `"clause_splitter"` as its own value rather than deriving it.

**Error accounting:** CRAG does NOT increment the top-level `error_count`. Every failure mode in this node (embedding failure, KB-unavailable, web-search failure/timeout) is a **graceful degradation** with a defined fallback, not a pipeline error. Keeping `error_count` out of the return dict is deliberate and required for the partial-update guarantee in Acceptance Criterion 12.

### `RetrievalPath` enum

Already defined in `specs/001-contract-state-schema.md`:

```python
class RetrievalPath(str, Enum):
    LOCAL_KB = "local_kb"
    WEB_FALLBACK = "web_fallback"
```

This spec introduces no new enum values.

## 3. Acceptance Criteria

Each criterion below is written to become a test case directly. Throughout, `confidence_score` is the **concrete scoring function pinned in Decision §7.1**: `max(0.0, top-1 cosine similarity)` — i.e. the single highest cosine among the top-K FAISS neighbors, clamped at 0. This exact definition is what makes ACs 2–4 constructible as fixtures (mock the KB to return a neighbor at a chosen cosine and assert the route).

1. **Per-clause coverage**: Given a state whose `clauses` dict has N clauses (N ≥ 1), after the node runs, every one of the N clause records has all three output fields present (`confidence_score`, `path_taken`, `evidence_snippets`) — no clause is skipped.

2. **High-confidence → local KB**: For a clause whose `confidence_score` (top-1 KB cosine per §7.1) is ≥ `CRAG_CONFIDENCE_THRESHOLD`, the clause's `path_taken` is `RetrievalPath.LOCAL_KB` and its `evidence_snippets` are drawn from the FAISS KB (their `source_reference` values point to KB entries, not web URLs).

3. **Low-confidence → web fallback**: For a clause whose `confidence_score` (top-1 KB cosine per §7.1) is < `CRAG_CONFIDENCE_THRESHOLD`, the clause's `path_taken` is `RetrievalPath.WEB_FALLBACK` and its `evidence_snippets` (if any) have `source_reference` values pointing to web results.

4. **Threshold boundary is inclusive at the local side**: A clause whose top-1 KB cosine equals exactly `CRAG_CONFIDENCE_THRESHOLD` routes to `LOCAL_KB` (the comparison is `score >= threshold`, matching constitution §2's `>=`). This is directly testable because §7.1 pins scoring to top-1: a fixture returning a single neighbor at cosine `== 0.73` must route local.

5. **Confidence score recorded and in range**: Every processed clause has a `confidence_score` that is either `None` (only on scoring failure) or a float in `[0.0, 1.0]`.

6. **Evidence snippet shape**: Every entry in any clause's `evidence_snippets` is a dict with exactly the keys `snippet_text` (non-empty `str`) and `source_reference` (non-empty `str`), matching the shape reserved in 001-contract-state-schema.md §3.

7. **Snippet count cap**: No clause's `evidence_snippets` list exceeds `CRAG_MAX_EVIDENCE_SNIPPETS` entries. (Note for the test author: with the default constants all equal to 5, this cap never actually truncates; the test MUST set `CRAG_MAX_EVIDENCE_SNIPPETS` below `CRAG_TOP_K` / `CRAG_WEB_MAX_RESULTS` — via the module-level monkeypatch pattern used in Node 2 — to exercise truncation.)

8. **Embedding model separation**: The clause-embedding call uses `OLLAMA_EMBED_MODEL_NAME` (the BGE-M3 embedding model), NOT `OLLAMA_MODEL_NAME` (the generative Qwen3 model). A test asserts these two constants are read from distinct config names and are not equal.

9. **Uses configured constants**: The confidence threshold, top-K, web result count, snippet cap, and timeouts are all read from `app.config` (per constitution §3), never hardcoded inline in node logic.

10. **Defensive `ingest_error` check**: If `ingest_error` is set (non-`None`) in the input state, the node returns immediately with an unchanged/empty `clauses` update (no embedding calls, no FAISS search, no web search).

11. **Empty clauses input**: If the input `clauses` dict is empty (`{}`), the node returns an empty `clauses` update without any embedding, FAISS, or web calls, and logs a warning.

12. **Partial update only**: The returned dict contains ONLY the keys `clauses`, `current_node`, and `node_timings`. It contains no IngestAgent-owned keys, no Self-RAG/risk/report keys, and specifically NO `error_count` (CRAG degradations are graceful, not pipeline errors — see §2 "Error accounting").

13. **Graceful web-fallback failure**: If the web search backend raises or times out for a clause on the web path, that clause receives `path_taken = RetrievalPath.WEB_FALLBACK`, `evidence_snippets = []`, and a recorded `confidence_score`; the pipeline does NOT crash and other clauses still process.

14. **Graceful KB-unavailable failure**: If the FAISS index cannot be loaded (missing/corrupt index file), every clause routes to `RetrievalPath.WEB_FALLBACK` (local KB is treated as unavailable → zero local confidence), a single warning is logged, and the pipeline does NOT crash.

15. **Determinism of the local path**: Given the same clause text, the same loaded FAISS index, and a deterministic embedding, the local-KB retrieval produces the same top-K snippets and the same `confidence_score` across runs. (The web path is inherently non-deterministic and is exempt.)

16. **Embedding-backend circuit breaker**: When embedding fails for `CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD` clauses **consecutively**, the node marks the embedding backend as down for the remainder of the run and stops issuing embedding calls — all remaining clauses go straight to the web path without waiting on `CRAG_EMBED_TIMEOUT_SECONDS` each. A single "circuit opened" warning is logged, and the consecutive-failure counter resets on any successful embedding. (Prevents the ~50s × N worst case when Ollama is down — see Edge Case 13.)

## 4. Edge Cases

1. **`ingest_error` set**: Return immediately with no retrieval work (Acceptance Criterion 10). Same defensive pattern as Node 2.

2. **Empty `clauses` dict**: Return an empty `clauses` update, log a warning, make no external calls (Acceptance Criterion 11).

3. **Empty or whitespace-only clause text**: Skip embedding for that clause; set `confidence_score = None`, `path_taken = None`, `evidence_snippets = None` (nothing to retrieve on), and log a warning. Other clauses still process.

4. **Embedding call fails/times out for a clause**: On embedding failure (Ollama unreachable, embed timeout > `CRAG_EMBED_TIMEOUT_SECONDS`, malformed vector), treat that clause as un-scorable: `confidence_score = None`. Per the corrective principle, fall back to the **web** path for that clause (local KB cannot be consulted without an embedding) and record `path_taken = RetrievalPath.WEB_FALLBACK`. Log a warning per failure (rate-limited/aggregated to avoid log bloat on large docs). **Consecutive-failure protection:** if the embedding backend is down entirely, paying the full `CRAG_EMBED_TIMEOUT_SECONDS` for every clause would be pathological (~`(embed_timeout + web_timeout)` × N — hours for a large contract); the circuit breaker in Edge Case 13 caps this.

5. **FAISS index missing / empty / corrupt**: The local KB is treated as unavailable. Every clause routes to the web fallback path. A single node-level warning is logged (not one per clause). See Acceptance Criterion 14.

6. **Local KB returns fewer than `CRAG_TOP_K` neighbors** (small KB): Use whatever neighbors exist. Confidence is scored on the available results; if zero neighbors exist, confidence is `0.0` → web fallback.

7. **Web search returns zero results**: `evidence_snippets = []`, `path_taken = RetrievalPath.WEB_FALLBACK`, `confidence_score` recorded from the (low) local score. Downstream Self-RAG (Node 4) is responsible for handling a clause with no evidence.

8. **Web search rate-limited / raises**: Caught and treated as "zero results" (Edge Case 7) — no crash (Acceptance Criterion 13). DuckDuckGo reliability limits are acknowledged in `specs/002-tech-stack.md` §3c. This is the **most fragile part of the design** (DDG rate-limiting plus the `duckduckgo-search` library's ongoing rename to `ddgs` upstream), so AC-13's graceful-failure guarantee is load-bearing: the exception boundary around the web call must catch broadly (any exception → zero results), not just a specific timeout type. `plan.md` pins the exact import/package name so the implementer does not guess it.

9. **All clauses take the web path**: Valid outcome (e.g. empty/unavailable KB, or a document whose clauses are all novel). The node must not assume any clause takes the local path.

10. **Very large clause count**: The node processes clauses strictly sequentially (Decision §7.6). Per-clause runtime is bounded by the embedding and web timeouts. The *aggregate* worst case (backend down → every clause pays `CRAG_EMBED_TIMEOUT_SECONDS` then `CRAG_WEB_TIMEOUT_SECONDS`) is bounded by the **circuit breaker** in Edge Case 13, which collapses the embedding cost to a fixed constant once the backend is detected down. Healthy-path latency headroom is still required per constitution §9.

11. **Very long single clause text**: The retrieval query is derived from the clause text truncated to a bounded length (`CRAG_QUERY_MAX_CHARS`) before embedding / web querying, to bound embedding input size and web query length. Truncation is logged at debug level.

12. **Clause already carries partial evidence fields** (defensive, e.g. a re-run): The node overwrites `confidence_score`, `path_taken`, and `evidence_snippets` for each clause it processes; the `merge_nested_clause_dicts` reducer preserves the non-evidence fields (`text`, `position`, etc.).

13. **Embedding backend down mid-run (circuit breaker)**: After `CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD` **consecutive** embedding failures, the node stops attempting embeddings for the rest of this run and sends every remaining clause straight to the web path (no per-clause embed timeout wait, `confidence_score = None`, `path_taken = RetrievalPath.WEB_FALLBACK`). A single "circuit opened" warning is logged. The counter resets on any successful embedding, so intermittent single failures never trip it. This is a **routing-semantics guarantee**, not just an optimization: it bounds aggregate node runtime when Ollama is unreachable (Edge Case 10). The circuit is per-run only; it is not persisted across pipeline invocations.

## 5. Out of Scope

CRAG retrieval does NOT handle:

1. **Judging whether the evidence actually supports flagging the clause** — relevance / ISREL / ISSUP checks and the discard-vs-validate decision belong to **Self-RAG validation (Node 4)**, `specs/006-self-rag-validation` (future). CRAG only *gathers* evidence; it does not *evaluate the finding*.

2. **The retry-with-max-3-attempts loop** — that retry behavior belongs to Self-RAG (Node 4), not here. CRAG has per-call timeouts and per-clause graceful degradation, but no validation-retry loop.

3. **Risk scoring, redlining, and report compilation** — Nodes 5, 6, 7 respectively.

4. **Curating / authoring the legal-clause knowledge base corpus** — the *content* of the FAISS KB (which reference clauses, from what legal sources) is a data-curation concern. What this spec owns is the KB **loader interface**, the on-disk **format**, and (pending Open Question §7.3) whether a minimal seed corpus + build utility ships with this feature. Ongoing corpus expansion is explicitly deferred.

5. **Query rewriting / knowledge decompose-recompose refinement** — classic CRAG includes a "knowledge refinement" step that decomposes retrieved documents into strips and recomposes the relevant ones. Phase 1 uses whole retrieved snippets. Advanced refinement is deferred (Open Question §7.5).

6. **A third "ambiguous" confidence bucket** — classic CRAG has three buckets (Correct / Ambiguous / Incorrect). The constitution §2 mandates a **binary** split at 0.73 (≥ → local, < → web). This spec implements the binary split exactly; the ambiguous/blended bucket is intentionally NOT implemented.

7. **Persisting or versioning the KB across documents** — the KB is a static, read-only asset at pipeline runtime. Building/updating it is an offline concern, not part of the per-document pipeline run.

8. **Any web source beyond the configured DuckDuckGo search** — no paid search APIs, no arbitrary URL scraping beyond what the search library returns (consistent with `specs/002-tech-stack.md` §5).

## 6. Configurable Constants

Per constitution §3, all thresholds live in `backend/app/config.py`. `CRAG_CONFIDENCE_THRESHOLD` already exists as a placeholder; this spec **confirms** it and adds the remaining constants:

```python
# ── CRAG retrieval thresholds ──────────────────────────────────────────────────
# Source: specs/005-crag-retrieval/spec.md §6

CRAG_CONFIDENCE_THRESHOLD: float = 0.73
# Retrieval-confidence split per constitution §2.
# score >= threshold  → Local clause KB (FAISS)
# score <  threshold  → Live web legal search (fallback).
# Confidence = max(0.0, TOP-1 cosine among the top-K neighbors), so the
# threshold is interpretable directly as a cosine value (Decision §7.1).
# EXPECT to tune this against real sample contracts after implementation.

OLLAMA_EMBED_MODEL_NAME: str = "bge-m3"
# The Ollama EMBEDDING model — distinct from OLLAMA_MODEL_NAME (generative Qwen3)
# per constitution §8 (model-separation rule). MUST NEVER be set equal to
# OLLAMA_MODEL_NAME or used for generation. Serves CRAG (and future Self-RAG)
# clause/query embedding only.

CRAG_TOP_K: int = 5
# Number of nearest neighbors to retrieve from the local FAISS KB per clause.

CRAG_WEB_MAX_RESULTS: int = 5
# Max results to request from the web-search fallback per clause.

CRAG_MAX_EVIDENCE_SNIPPETS: int = 5
# Hard cap on evidence_snippets stored per clause, regardless of path.

CRAG_QUERY_MAX_CHARS: int = 2000
# Clause text is truncated to this length before embedding / web querying,
# to bound embedding input and web query size. See Edge Case §4.11.

CRAG_EMBED_TIMEOUT_SECONDS: int = 30
# Wall-clock timeout for a single embedding call via Ollama. On timeout the
# clause is treated as un-scorable and falls back to the web path (§4.4).
# Generous headroom for local BGE-M3 on CPU-only hardware, per constitution §9.

CRAG_WEB_TIMEOUT_SECONDS: int = 20
# Wall-clock timeout for a single web-search call. On timeout the clause's
# evidence is treated as empty (§4.8).

CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD: int = 5
# Number of CONSECUTIVE embedding failures after which the node declares the
# embedding backend down for the rest of the run and routes all remaining
# clauses straight to web (skipping the per-clause embed timeout). Resets on
# any successful embedding. Bounds aggregate runtime when Ollama is down
# (Edge Case 13). Routing-semantics guarantee, not just an optimization.

CRAG_KB_INDEX_PATH: str = "data/kb/clauses.faiss"
# Filesystem path to the prebuilt FAISS index for the local clause KB.
# ANCHOR: relative to the backend/ directory (the process working directory
# when the pipeline runs — the same anchor IngestAgent uses for file paths).
# The implementation resolves it against that base rather than the raw CWD of
# whatever invoked Python, so tests and the app agree on one location.

CRAG_KB_METADATA_PATH: str = "data/kb/clauses_meta.jsonl"
# Sidecar file mapping each FAISS vector row -> {snippet_text, source_reference}.
# Loaded alongside the index so retrieved vector IDs can be resolved to text.
# Same backend/-relative anchor as CRAG_KB_INDEX_PATH.
```

(Exact default values above are starting points to be tuned post-implementation. The `CRAG_KB_INDEX_PATH` / `CRAG_KB_METADATA_PATH` layout is produced by the KB build utility that ships with this feature — Decision §7.3. Both paths are resolved relative to the `backend/` directory; `plan.md` pins the exact base-path resolution mechanism.)

## 7. Resolved Decisions

All open questions have been resolved with the decisions below. This spec is considered final.

### 7.1 Confidence-scoring mechanism — RESOLVED: FAISS cosine similarity

Confidence is computed from **FAISS vector similarity**, not a separate learned/LLM retrieval evaluator. Clauses are embedded with BGE-M3 into an **L2-normalized** vector; the FAISS index uses **inner product** so the score is cosine similarity. The scoring function is pinned to **top-1**: `confidence_score = max(0.0, highest cosine among the top-K neighbors)` — the single best neighbor, clamped at 0, yielding a value in `[0.0, 1.0]` compared directly against `CRAG_CONFIDENCE_THRESHOLD`. Top-1 (not mean-of-top-K) is chosen because it makes the routing boundary a concrete, testable function (Acceptance Criteria 2–4 construct fixtures against it) and because "is there at least one strong local match?" is the right question for a corrective-retrieval gate. This keeps Node 3 purely about *retrieval + routing* (leaving *judgment* to Self-RAG, Node 4), is fully deterministic, and adds no per-clause generative LLM cost — important given local-model latency (constitution §9) over potentially 100–200 clauses. An LLM-based grader was rejected as expensive, non-deterministic, and an overreach into Node 4's responsibility.

**Normalization invariant:** cosine-via-inner-product is only correct if vectors are L2-normalized on **both** sides. The offline KB build utility (§7.3) MUST L2-normalize every KB vector before adding it to the index, and the node MUST L2-normalize each query embedding before searching. If either side is un-normalized the scores are not cosines and the 0.73 threshold is meaningless — `plan.md` and the build utility must both assert this.

### 7.2 Per-clause "conditional edge" realization — RESOLVED: internal node branching

CRAG is implemented as a **single LangGraph node** whose local-vs-web decision is internal Python control flow (`if score >= CRAG_CONFIDENCE_THRESHOLD`) inside a loop over clauses. The "CRAG confidence-based routing" that constitution §2 counts as one of the two conditional edges is therefore realized **logically, as the node's internal branching**, NOT as a graph-level `add_conditional_edges`. `builder.py` adds exactly one node (`crag_retrieval`) with a plain linear `add_edge` to Node 4. This keeps the "7 sequential nodes" framing intact and is the simplest faithful realization of per-clause routing (a graph-level conditional edge cannot express per-clause branching because a single node holds all clauses in one `ContractState`). The `Send`-API map-reduce alternative (a real per-clause conditional edge in a subgraph) was rejected for Phase 1 as unnecessary complexity. **`plan.md` MUST document this interpretation of constitution §2 explicitly** so the deviation from a literal graph edge is recorded.

### 7.3 Local clause KB provenance — RESOLVED: seed corpus + build utility ship with this feature

This feature ships:
- an **offline KB build utility** (a script, not part of the runtime pipeline) that embeds a curated `.jsonl` of reference clauses with BGE-M3, **L2-normalizes every vector** (required for the cosine-via-inner-product invariant in §7.1), and writes the FAISS inner-product index (`CRAG_KB_INDEX_PATH`) plus a JSONL metadata sidecar (`CRAG_KB_METADATA_PATH`) mapping each vector row to `{snippet_text, source_reference}` — row order in the sidecar corresponds 1:1 to vector IDs in the index; and
- a **small bundled seed corpus** (a few dozen common contract-clause references) so the local path is runnable and testable end-to-end from day one.

Ongoing corpus *curation/expansion* remains out of scope (§5.4). The seed-corpus source and exact sidecar schema are finalized in `plan.md`.

### 7.4 `evidence_trail` ownership — RESOLVED: ReportAgent compiles it

CRAG stores evidence **only** in each clause's `evidence_snippets`. The top-level `evidence_trail` list is compiled later by **ReportAgent (Node 7)** from the per-clause records. This keeps Node 3's partial update minimal (constitution §5/§6) and matches how 001-contract-state-schema.md groups `evidence_trail` under ReportAgent.

**Known, accepted semantic compromise on `retrieved_at`:** 001-contract-state-schema.md (its Open Question #3) defines `retrieved_at` as "when evidence was retrieved/validated." Because CRAG does not write `evidence_trail`, the timestamp ReportAgent (Node 7) stamps is a **report-compilation time, not a true retrieval time** — the two can differ by the full duration of Nodes 4–6. This spec **explicitly accepts that drift** for Phase 1 rather than pretending it is exact: the `evidence_snippets` shape is fixed by 001 to exactly `{snippet_text, source_reference}`, so there is nowhere to record a per-snippet retrieval instant without a 001-schema change, and adding one is not justified for Phase 1. If a *true* retrieval-time timestamp is later required (e.g. for auditability), that is a deliberate future 001-schema change under constitution §10 — at which point CRAG would either add a per-snippet timestamp field or take over writing `evidence_trail` (the §7.4 alternative that was rejected here). Flagging this as a **known-now compromise**, not an open unknown.

### 7.5 Web-fallback query construction — RESOLVED: truncated clause text

The web query is the clause text truncated to `CRAG_QUERY_MAX_CHARS`, optionally prefixed with `clause_type` when known. No extra LLM call. LLM-generated search queries are noted as a future retrieval-quality improvement but are out of scope for Phase 1.

### 7.6 Per-clause processing model — RESOLVED: sequential

The first implementation processes clauses **strictly sequentially** (safest against Ollama concurrency limits and simplest to reason about). A bounded-parallelism config knob is deferred until real documents are benchmarked (constitution §9).

### 7.7 `clause_type`-scoped retrieval — RESOLVED: no (flat index) for Phase 1

The FAISS KB is a single flat index; retrieval is pure vector similarity and is NOT filtered/biased by the clause's inferred `clause_type`. Revisit only if evaluation reveals cross-type contamination.

## 8. Evaluation

Because this node performs confidence scoring and confidence-based routing, the following metrics MUST be logged per run for later tuning (per `specs/002-tech-stack.md` §3i eval tooling, and to calibrate `CRAG_CONFIDENCE_THRESHOLD`).

**Where these live:** `ContractState` holds only aggregate `node_timings[\"crag_retrieval\"]` (one float for the whole node). All of the *per-clause* granular metrics below (per-clause confidence, path, latencies, snippet counts) live in **structured log records** emitted by the node's logger — NOT in state — following the `logger.info(..., extra={...})` pattern established in `clause_splitter_agent.py`. The eval harness (§3i tooling) consumes these from logs; the spec does not add per-clause metric fields to `ContractState`.

1. **Confidence score distribution** — histogram of per-clause `confidence_score` across all clauses (to calibrate the 0.73 threshold against real contracts).
2. **Retrieval-path hit rate** — fraction of clauses routed to `LOCAL_KB` vs. `WEB_FALLBACK` (per document and aggregate). Tells us how often the local KB is trusted.
3. **Empty-evidence rate** — fraction of clauses whose `evidence_snippets` ended up `[]` (esp. on the web path), a signal of retrieval coverage gaps.
4. **Web-fallback failure rate** — fraction of web-path clauses where the search raised / timed out / returned zero results.
5. **Embedding-failure rate** — fraction of clauses where embedding failed and forced a degraded web fallback.
6. **KB-unavailable events** — count of runs where the FAISS index could not be loaded (should be ~0 in a healthy deployment).
7. **Latency** — per-clause embedding latency and per-clause web-search latency (log records only), plus total node wall-clock time (the single value that also feeds `node_timings`). Supports constitution §9 tuning.
8. **Snippet yield** — average number of `evidence_snippets` per clause, per path.

These metrics directly support tuning `CRAG_CONFIDENCE_THRESHOLD`, `CRAG_TOP_K`, `CRAG_WEB_MAX_RESULTS`, and the timeout constants against real sample contracts once implementation is complete.
