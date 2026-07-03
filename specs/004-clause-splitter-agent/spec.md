# ClauseSplitterAgent Specification

## 1. Problem Statement

The ClauseSplitterAgent is Node 2 of the fixed 7-node pipeline defined in `specs/000-constitution.md`. Its responsibility is to segment the full extracted text produced by IngestAgent (Node 1) into discrete, individually addressable clauses that can be consumed by downstream nodes (CRAG retrieval, Self-RAG validation, RiskScoreAgent, RedlineAgent, and ReportAgent — Nodes 3–7).

This node exists at position 2 because clause-level granularity is the fundamental unit of analysis for the entire risk-assessment pipeline: retrieval searches per clause, validation judges per clause, risk scores are assigned per clause, and redlining rewrites individual clauses. Without a reliable segmentation step between raw text and per-clause analysis, every downstream node would need to re-solve the segmentation problem independently.

The ClauseSplitterAgent uses a hybrid approach:
1. **Regex pre-pass** — detects numbered/lettered clause boundaries using structural markers to produce candidate boundaries. This is fast, deterministic, and requires no LLM.
2. **LLM semantic refinement** — uses Qwen3 14B (via Ollama, running locally) to review and correct the candidate boundaries, merging fragments that belong together and splitting run-on segments. This is the ONLY LLM call in this node.
3. **Clause type inference** — uses the same LLM call (or a separate small call if needed) to infer `ClauseType` for each clause from the enum values defined in `specs/001-contract-state-schema.md`.

The LLM serves as a refinement layer, not the primary segmentation engine. The regex pre-pass handles the common case (structurally marked contracts) cheaply and reliably; the LLM improves quality on edge cases (run-on clauses, missing markers, ambiguous boundaries) without being a single point of failure.

## 2. Inputs and Outputs

### Inputs

The ClauseSplitterAgent reads the following fields from `ContractState` (as defined in `specs/001-contract-state-schema.md`):

- `extracted_text`: `str` — the full contract text, already parsed by IngestAgent
- `document_id`: `str` — unique identifier for the document (used in logging, not in clause processing)
- `ingest_error`: `Optional[Dict[str, str]]` — checked defensively; if set, the node returns an empty clauses dict immediately without any processing

### Outputs

The ClauseSplitterAgent writes the following field to `ContractState`:

- `clauses`: `Dict[str, Dict[str, Any]]` — keyed by `clause_id`, uses the `merge_nested_clause_dicts` reducer

Each clause record in the dict contains:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | `str` | Yes | The full text content of the clause |
| `position` | `int` | Yes | 1-indexed position of the clause in the document |
| `section_number` | `Optional[str]` | Yes (field required, value may be `None`) | Detected section number (e.g. `"1.2"`, `"Article 5"`, `"§3"`). `None` if no section marker detected |
| `clause_type` | `Optional[ClauseType]` | Yes (field required, value may be `None`) | Inferred clause type from the `ClauseType` enum in `state.py`. `None` if the LLM cannot confidently infer a type, or if the LLM was not called (timeout/fallback) |

**Clause ID scheme**: Each clause is keyed by a stable, deterministic string — NOT a UUID. The scheme is positional: `"clause_001"`, `"clause_002"`, etc., zero-padded to 3 digits. See Open Questions §7.1 for the alternative (section-number-based keys) and rationale for why positional is recommended.

**Partial-update rule** (constitution §5): The node returns ONLY the `clauses` key (plus `current_node` and `node_timings` for pipeline metadata). It does NOT return or modify any other `ContractState` keys.

## 3. Acceptance Criteria

1. **Boundary detection — numbered contracts**: Given a standard numbered contract (e.g. `"1. Definitions\n1.1 ...\n1.2 ..."`), the agent correctly identifies each numbered section as a separate clause.

2. **Non-empty output**: For any non-empty `extracted_text`, the agent produces at least 1 clause in the output dict.

3. **Required fields**: Every clause record in the output dict contains all four required fields: `text`, `position`, `section_number`, `clause_type`.

4. **No-section-markers fallback**: Given a contract with NO numbered sections (pure prose), the agent falls back to paragraph-based splitting (double-newline boundaries) or semantic-only splitting via the LLM, and still produces valid clause records.

5. **Defensive ingest_error check**: If `ingest_error` is set (non-None) in the input state, the node returns an empty `clauses` dict (`{}`) immediately without calling the regex splitter or the LLM. The pipeline's `builder.py` routing already prevents reaching this node on error, but the node checks defensively.

6. **Ollama client usage**: The LLM call uses the `ollama` Python client library, with the model name read from `app.config.OLLAMA_MODEL_NAME`.

7. **Timeout fallback**: If the LLM call exceeds `CLAUSE_SPLITTER_TIMEOUT_SECONDS` (defined in `app/config.py`), the node falls back to regex-only output rather than failing. A warning is logged via the node's named logger.

8. **Optional clause_type**: `clause_type` is `Optional` — if the LLM cannot confidently infer a type, `None` is acceptable. The node must NOT force a classification; a wrong `clause_type` is worse than `None` because downstream risk scoring may weight clause type in its assessment.

9. **Partial update only**: The return dict contains ONLY `clauses`, `current_node`, and `node_timings` keys. It does NOT contain any IngestAgent-owned keys (`document_id`, `extracted_text`, etc.), any CRAG/Self-RAG keys, or any report keys.

10. **Clause ID determinism**: Given the same `extracted_text`, the regex pre-pass produces the same clause boundaries and the same clause IDs. The LLM refinement may vary across calls (non-deterministic), but the fallback (regex-only) path is fully deterministic.

11. **Position correctness**: `position` values are 1-indexed, sequential, and contiguous (1, 2, 3, ..., N) with no gaps.

## 4. Edge Cases

1. **Empty `extracted_text`**: If `extracted_text` is an empty string (despite no `ingest_error` — a defensive case), the node returns an empty clauses dict (`{}`). No LLM call is made. A warning is logged.

2. **Very short document**: If `extracted_text` has fewer than `MIN_CLAUSE_LENGTH` characters (configurable constant in `app/config.py`), the entire text is treated as a single clause with `clause_id = "clause_001"`, `position = 1`, `section_number = None`, and `clause_type` inferred by the LLM if available.

3. **No recognizable section markers**: For pure prose contracts with no numbered sections, lettered subsections, or structural headers, the regex pre-pass falls back to paragraph splitting using double-newline (`\n\n`) boundaries. If paragraph splitting produces zero boundaries (single unbroken block of text), the entire text is treated as one clause.

4. **LLM timeout**: If the Ollama LLM call exceeds `CLAUSE_SPLITTER_TIMEOUT_SECONDS`, the node uses the regex-only output as-is (no semantic refinement, `clause_type = None` for all clauses). A warning is logged with the document_id, timeout value, and clause count from regex-only output.

5. **LLM malformed response**: If the LLM returns malformed JSON, unparseable text, or a response that cannot be mapped to the expected output schema, the node falls back to the regex-only output. A warning is logged with the raw LLM response (truncated to avoid log bloat). The pipeline does NOT crash.

6. **Extremely long document**: `MAX_CLAUSES_LIMIT` (configurable constant in `app/config.py`) is enforced as a **two-stage cap** so the §6 invariant "maximum number of clauses the node will produce" always holds:
   - **Pre-LLM cap**: if the regex pre-pass produces more than `MAX_CLAUSES_LIMIT` boundaries, the list is truncated to the first `MAX_CLAUSES_LIMIT` before being sent to the LLM (this also bounds the prompt size). A warning is logged with the original count.
   - **Post-refinement re-clamp**: because the LLM is permitted to split run-on segments (§1, §2), the refined output can again exceed `MAX_CLAUSES_LIMIT`. The node re-truncates the refined output to `MAX_CLAUSES_LIMIT` and re-numbers `clause_id`/`position` contiguously, logging a warning.

   The pipeline does NOT crash. The guaranteed invariant is on the **final produced** clause count, not merely on the regex output.

7. **Mixed numbering schemes**: Documents with mixed numbering (e.g. `"Article 1"` then `"Section 1.1"` then `"1.1.1"` then `"(a)"`) are handled best-effort by the regex pre-pass, which supports all common patterns. The LLM refinement step is expected to improve boundary quality for these cases. The node does NOT crash on unexpected numbering patterns.

8. **Ollama server not running**: If the Ollama server is unreachable (connection refused, DNS failure, etc.), the node treats this as an LLM timeout — falls back to regex-only output with a warning log. The node does NOT crash or set any error state beyond the warning.

9. **Single-line document**: A document with no newlines at all is treated as a single clause (same as the very-short-document case if under `MIN_CLAUSE_LENGTH`, or as a single regex-boundary clause otherwise).

## 5. Out of Scope

The ClauseSplitterAgent does NOT handle:

1. **Semantic analysis of clause content** — any understanding of what a clause means, its risk implications, or its legal significance is the responsibility of Nodes 3–7 (CRAG retrieval, Self-RAG validation, RiskScoreAgent, RedlineAgent, ReportAgent).

2. **Risk scoring, redlining, or any output beyond clause boundaries and basic type classification** — the only semantic output is `clause_type`, which is a lightweight classification, not an analysis.

3. **Multi-document splitting** — one invocation of this node processes exactly one document. Batch processing across multiple documents is not supported.

4. **Language detection or non-English contract handling** — Phase 1 assumes English contracts only. The regex patterns target English structural markers (e.g. "Article", "Section", "WHEREAS"). Non-English contracts may produce degraded results. This is explicitly out of scope for Phase 1.

5. **Clause-level deduplication** — if the same text appears in multiple positions (e.g. repeated boilerplate), each occurrence is treated as a separate clause. Deduplication, if ever needed, would be a downstream concern.

6. **Sub-clause decomposition** — the node splits at the clause level, not at the sub-clause or sentence level. If a clause contains multiple sub-provisions (e.g. "(a)", "(b)" within a section), these are NOT split into separate clauses unless the regex pre-pass detects them as independent boundaries. The LLM may refine this, but exhaustive sub-clause decomposition is not a goal.

7. **Document structure reconstruction** — the node does not produce a hierarchical document outline, table of contents, or parent-child relationship between clauses. It produces a flat list of clauses.

## 6. Configurable Constants

The following named constants must be added to `backend/app/config.py` per the constitution's configurable-thresholds rule (§3):

```python
# ── ClauseSplitterAgent thresholds ─────────────────────────────────────────────
# Source: specs/004-clause-splitter-agent/spec.md §6

OLLAMA_MODEL_NAME: str = "qwen3:14b"
# The Ollama model identifier for LLM calls in the pipeline.
# Qwen3 14B runs locally via Ollama — no cloud API cost.
# Fits in ~10GB VRAM at Q4_K_M quantization (any 12–16GB GPU).
# Used by ClauseSplitterAgent for semantic refinement and clause_type inference.
# Future nodes (CRAG, Self-RAG, etc.) may also use this constant.

CLAUSE_SPLITTER_TIMEOUT_SECONDS: int = 120
# Wall-clock timeout for the LLM call in ClauseSplitterAgent.
# Set to 120s as a conservative starting value — Qwen3 14B running locally
# is fast on GPU (~20–40 tok/sec) but needs headroom for long contracts
# and CPU-only or lower-end hardware — per constitution §9.
# On timeout, the node falls back to regex-only output.
# Benchmark on first real integration test and tune down if possible.

MIN_CLAUSE_LENGTH: int = 100
# Minimum character count for extracted_text to be worth splitting.
# Documents shorter than this are treated as a single clause.
# 100 chars ≈ 1–2 short sentences — below this, splitting is meaningless.

MAX_CLAUSES_LIMIT: int = 500
# Maximum number of clauses the node will produce.
# Documents exceeding this are truncated with a logged warning.
# 500 is generous — a typical 50-page contract has 100–200 clauses.
# This is a safety valve against pathological regex matches on unusual
# formatting (e.g. every line treated as a separate clause).
```

**Note on `OLLAMA_MODEL_NAME`**: This constant is not currently present in `app/config.py`. It is intentionally defined as a shared pipeline-level constant (not ClauseSplitterAgent-specific) because future nodes (CRAG, Self-RAG) will also call the LLM via Ollama. If IngestAgent's plan had already added it, this spec would reference the existing constant rather than re-adding it.

## 7. Resolved Questions

All previously open questions have been resolved with the following decisions:

1. ~~**Clause ID scheme: positional vs section-number-based**~~ — **RESOLVED**: Positional (`"clause_001"`, `"clause_002"`, etc., zero-padded to 3 digits). Section numbers are preserved in the `section_number` field of each clause record for display and analysis but are not used as dict keys. Rationale: uniform format, no collision risk, predictable for downstream nodes.

2. ~~**LLM semantic refinement: structured output (JSON mode) vs free-text parsing**~~ — **RESOLVED**: Use JSON mode with explicit JSON schema in the prompt and `format="json"` in the Ollama `ollama.chat()` call. The `ollama` Python client supports this for Qwen3 14B. Fall back to regex-only output if JSON parsing fails (same fallback as timeout).

3. ~~**Clause type inference: same LLM call or separate call**~~ — **RESOLVED**: Same call. A single LLM call handles both boundary refinement and clause_type inference. This halves latency vs two round-trips. If the combined call fails, the fallback is regex-only output with `clause_type = None` for all clauses.

4. ~~**Timeout value**~~ — **RESOLVED**: `CLAUSE_SPLITTER_TIMEOUT_SECONDS = 120` as a conservative starting value. Benchmark on first real integration test and tune down if possible. 120s provides headroom for long contracts on variable hardware (GPU and CPU-only).

## 8. Evaluation

When the ClauseSplitterAgent runs, the following metrics should be logged for later analysis:

1. **Clause count**: Number of clauses produced per document
2. **Regex-only vs LLM-refined**: Whether the output used regex-only (fallback) or LLM-refined boundaries
3. **LLM latency**: Wall-clock time for the Ollama call (if made)
4. **Clause type distribution**: Count of each `ClauseType` value (including `None`) across clauses
5. **Section marker detection rate**: Percentage of clauses with non-None `section_number`
6. **Fallback trigger rate**: Percentage of invocations that fell back to regex-only output (timeout, parse failure, Ollama unreachable)

These metrics will help tune `CLAUSE_SPLITTER_TIMEOUT_SECONDS`, `MIN_CLAUSE_LENGTH`, and `MAX_CLAUSES_LIMIT` against real contract documents.
