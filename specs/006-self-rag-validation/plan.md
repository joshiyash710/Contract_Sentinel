# Self-RAG Validation Technical Plan

## Git Branch

`feature/006-self-rag-validation` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

This plan details how to implement the **Self-RAG validation node (Node 4)** as specified in `specs/006-self-rag-validation/spec.md`. The node is the **quality gate** between "we have evidence per clause" (Node 3, CRAG) and "we have findings worth acting on" (Node 5, RiskScore). For **each clause** it runs up to three reflective LLM judgments against that clause's merged evidence and produces a binary `final_status` — `VALIDATED` (flows on to Node 5) or `DISCARDED` (marked inert, never shown to the user).

The three checks run as a **sequential short-circuit gate** (spec §7.1 / §8a R2):

- **Relevance** — is this clause a substantive, analyzable provision at all? (a property of the *clause*)
- **ISREL** — is the retrieved evidence relevant to this clause? (a property of the *evidence*)
- **ISSUP ("worth flagging")** — does the evidence support surfacing this clause as a concern? (retried on `False`, up to `SELF_RAG_MAX_ATTEMPTS`)

The node writes only `clauses` (via the `merge_nested_clause_dicts` reducer) plus `current_node` and `node_timings`, per the partial-update rule (constitution §5). The **one** exception is the circuit-open health signal: a single `error_count: 1` when the LLM backend is declared down for the run (spec §8a R5).

All configurable thresholds live in `app/config.py` per constitution §3. Every LLM call uses the **generative** model `OLLAMA_MODEL_NAME` (Qwen3 via Ollama) — the same model Node 2 uses. The node makes **no vector calls** and never references `OLLAMA_EMBED_MODEL_NAME` (constitution §8 model-separation; CRAG already produced the evidence).

**Resolved design decisions carried from the spec (§8a):**
- **R1 — Retry re-runs the same ISSUP judgment** (a self-consistency re-sample), never regenerates a candidate finding. Node 4 is a *gate*, not a generator; finding text is authored downstream (Nodes 5–6). No 001-schema change; no finding-text persistence.
- **R2 — Three sequential LLM calls with short-circuit**, not one combined call. Keeps "retry only ISSUP" clean and avoids LLM calls on clauses destined to be discarded (constitution §9).
- **R3 — Fail-open** — an unrecoverable LLM failure defaults the clause to `VALIDATED` (surface for human review; a false negative is the costlier error in a risk tool).
- **R4 — Empty-evidence is `clause_type`-gated** — no evidence sets `isrel_verdict = None` (not-assessable); a **high-risk** `clause_type` is rescued via an evidence-free ISSUP-on-clause-text judgment, everything else is discarded with **zero LLM calls**.
- **R5 — Circuit-open health signal** — the circuit breaker opening emits `error_count: 1` **once** per run so a wholesale fail-open run is distinguishable from a clean one.

This node's outgoing graph edge is a **plain linear `add_edge`** (`self_rag_validation → risk_score`, wired to `END` until feature-007). Self-RAG is **not** one of the two conditional edges the constitution permits (those are CRAG's confidence routing and Node 6's `route_on_risk`). Discarded findings are marked, not routed away — the node never removes clause IDs.

---

## 2. Files to Create / Modify

### Shared Config Module

#### [MODIFY] `backend/app/config.py`

The `# ── Self-RAG thresholds ──` block currently holds only the `SELF_RAG_MAX_RETRIES = 3` **placeholder** (config.py:92–94). Replace that placeholder with the spec §6 constants. Per spec §8b Q2 the placeholder is **renamed** `SELF_RAG_MAX_RETRIES → SELF_RAG_MAX_ATTEMPTS` (treating "3" as total ISSUP *attempts*, so `retry_count ∈ {0,1,2}`). A repo grep confirms the placeholder has **no current references** (Node 4 is not yet implemented), so the rename is safe.

```python
# ── Self-RAG validation thresholds ─────────────────────────────────────────────
# Source: specs/006-self-rag-validation/spec.md §6

SELF_RAG_MAX_ATTEMPTS: int = 3
# Maximum number of ISSUP ("worth flagging") judgment attempts per clause, per
# constitution §2 ("retry on ISSUP fail, max 3 attempts"). First attempt + retries
# together may not exceed this. retry_count = attempts_taken - 1, so
# retry_count ∈ {0, 1, 2} at this default. Renames the old SELF_RAG_MAX_RETRIES
# placeholder (spec §8b Q2).

SELF_RAG_TIMEOUT_SECONDS: int = 120
# Wall-clock timeout for a single Self-RAG LLM call (Relevance / ISREL / one ISSUP
# attempt) via Ollama. Mirrors CLAUSE_SPLITTER_TIMEOUT_SECONDS; headroom for local
# Qwen3 per constitution §9. On timeout the clause takes the fail-open default
# outcome (spec §4.4).

SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD: int = 5
# Number of CONSECUTIVE LLM failures after which the node declares the generative
# backend down for the rest of the run and applies the fail-open default outcome to
# all remaining clauses (skipping per-clause timeouts). Resets on any success.
# Opening emits the error_count health signal once (spec §4.8, §8a R5, AC-15/20).
# Mirrors CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD.

SELF_RAG_PROMPT_MAX_CHARS: int = 6000
# Clause text + concatenated evidence snippets are truncated to this length before
# each LLM call, to bound prompt size (spec §4.9).

SELF_RAG_HIGH_RISK_CLAUSE_TYPES: frozenset = frozenset({
    "liability",
    "termination",
    "intellectual_property",
    "dispute_resolution",
})
# ClauseType.value strings for which an EMPTY-EVIDENCE clause is rescued via an
# evidence-free clause-text judgment instead of a zero-LLM discard (spec §4.3 /
# §7.5 / §8a R4). Deliberately narrow: the categories where a silent miss is
# costliest. Types NOT listed (and clause_type=None) fall through to discard.
# Widen only if the empty-evidence discard metric (spec §9.6) shows real misses.
```

The node also reuses the existing `OLLAMA_MODEL_NAME` — it introduces no new model constant.

---

### Validators Package

New package `backend/app/graph/nodes/validators/`, following the same structure precedent as `splitters/` (Node 2) and `retrievers/` (Node 3): a package `__init__.py` exporting shared helpers, plus one module for the reflective judgments, independently testable with the LLM mocked at the boundary.

#### [NEW] `backend/app/graph/nodes/validators/__init__.py`

Exports the shared evidence-formatting helper used to build judgment prompts, keeping the "exactly the 001 evidence shape" assumption in one place.

```python
from typing import List, Dict, Any, Optional


def format_evidence(snippets: Optional[List[Dict[str, Any]]], max_chars: int) -> str:
    """Render evidence snippets into a single prompt-ready block, truncated to
    max_chars.

    Each snippet is the 001 shape {"snippet_text": str, "source_reference": str}.
    Returns "" when snippets is None/empty (the empty-evidence path formats a
    "no evidence" sentinel in the reflector instead). Truncation is applied to the
    concatenated block so total prompt input is bounded (spec §4.9).
    """
```

Rationale for placement: `reflectors.py` is the only consumer today, but keeping `format_evidence` in the package init mirrors how `make_snippet`/`RetrievalResult` live in `retrievers/__init__.py` — a shared, dependency-free helper that the node and the reflectors can both reference without a cross-module cycle.

#### [NEW] `backend/app/graph/nodes/validators/reflectors.py`

The three reflective judgments. Each returns `Optional[bool]` and **never raises** — the exception boundary here is load-bearing (spec §4.4). The contract for the caller (the node) is deliberately simple:

- `True` / `False` → a real verdict from the model
- `None` → the judgment **could not be run** (Ollama unreachable, timeout, or unparseable/malformed response) → the node treats this as an unrecoverable LLM failure and fail-opens (spec §4.4 / §8a R3)

```python
def check_relevance(clause_text: str, timeout_seconds: int, model_name: str,
                    prompt_max_chars: int) -> Optional[bool]:
    """Relevance check: is this clause a substantive, analyzable provision worth
    evaluating at all? A property of the CLAUSE — does not read evidence.
    Returns True/False, or None on any LLM failure. Never raises."""

def check_isrel(clause_text: str, evidence_snippets: list, timeout_seconds: int,
                model_name: str, prompt_max_chars: int) -> Optional[bool]:
    """ISREL check: is the retrieved evidence relevant to this clause? A property of
    the EVIDENCE. Only called when evidence is present (the empty-evidence path sets
    isrel_verdict=None without calling this). Returns True/False, or None on failure."""

def check_issup(clause_text: str, evidence_snippets: Optional[list],
                timeout_seconds: int, model_name: str,
                prompt_max_chars: int) -> Optional[bool]:
    """ISSUP ('worth flagging') check: does the evidence support surfacing this clause
    as a concern? If evidence_snippets is empty/None (the high-risk empty-evidence
    rescue path, spec §7.5), the prompt instructs the model to judge on the CLAUSE
    TEXT ALONE. Returns True/False, or None on failure. Never raises."""
```

Implementation notes:
- **Shared invocation core.** A private `_run_judgment(prompt: str, timeout_seconds, model_name) -> Optional[bool]` performs the Ollama call and parses the verdict, so the three public functions differ only in their prompt. This mirrors `llm_refiner.py`'s `_call_ollama` + `_parse_response` split.
- **Ollama call + timeout — copy the Node 2 pattern exactly (spec §4.4, constitution §9).** Use `ollama.Client(timeout=timeout_seconds).chat(model=model_name, messages=[...], format="json", options={"num_predict": <small, e.g. 256>})` **inside** a `concurrent.futures.ThreadPoolExecutor(max_workers=1)` with `future.result(timeout=timeout_seconds)` (llm_refiner.py:67–80, 102–108). The `Client(timeout=…)` is the **primary** bound (it aborts the underlying `httpx` call so the worker thread dies and `shutdown(wait=True)` returns promptly); the executor `future.result(timeout=…)` is the backstop. This is the same correctness argument the CRAG plan makes for `embed_query` — do **not** use a bare `ollama.chat` bounded only by the executor, or a hung socket would outlive the timeout and defeat the circuit breaker. `num_predict` is small because each judgment returns a tiny JSON object, not prose.
- **JSON verdict contract.** Prompt each check to return `{"verdict": true|false, "reason": "<short>"}`. Parse `verdict` as a bool: `True`/`False` → return it; `reason` is logged at debug only and never stored in state (spec §5.6). If the response is not valid JSON, is missing `verdict`, or `verdict` is not a bool → treat as an **unrecoverable failure** and return `None` (fail-open), matching "unparseable response" in spec §4.4. Catch `concurrent.futures.TimeoutError`, `httpx.TimeoutException`, and any `Exception` → `None` with a rate-limited warning.
- **Prompt truncation.** Each function truncates `clause_text` and (via `format_evidence`) the evidence block so their combined length is bounded by `prompt_max_chars` before the call (spec §4.9). Truncation logged at debug.
- **Distinct, focused prompts (spec §8b Q1 — pinned, plan-safe).** Relevance asks only about the clause; ISREL asks whether the given evidence is on-topic for the clause; ISSUP asks whether the evidence (or, in the rescue path, the clause text alone) supports flagging it as a concern. The wording is tunable later without changing control flow.

---

### Self-RAG Validation Node

#### [NEW] `backend/app/graph/nodes/self_rag_validation_agent.py`

The LangGraph node — the only file that touches `ContractState`. Owns the per-clause loop, the short-circuit gate, the ISSUP retry loop, the empty-evidence `clause_type` gate, the circuit breaker, and the health signal.

```python
import app.config as _config  # module import so tests can monkeypatch (Node 2 precedent)

logger = logging.getLogger("contractsentinel.self_rag_validation")

# Re-exposed module-level names for monkeypatching (mirrors clause_splitter_agent.py):
OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME
SELF_RAG_MAX_ATTEMPTS = _config.SELF_RAG_MAX_ATTEMPTS
SELF_RAG_TIMEOUT_SECONDS = _config.SELF_RAG_TIMEOUT_SECONDS
SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD = _config.SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD
SELF_RAG_PROMPT_MAX_CHARS = _config.SELF_RAG_PROMPT_MAX_CHARS
SELF_RAG_HIGH_RISK_CLAUSE_TYPES = _config.SELF_RAG_HIGH_RISK_CLAUSE_TYPES


def self_rag_validation_agent(state: ContractState) -> dict:
    """LangGraph Node 4. Reads clauses/document_id/ingest_error; returns partial
    dict: clauses (per-clause verdict updates), current_node, node_timings, and
    error_count:1 ONLY when the circuit breaker opened."""
```

**Internal flow:**

```
1.  current_node = "self_rag_validation"; record start_time.
2.  Defensive: if state.get("ingest_error") is not None → return empty update
    (clauses={}, current_node, node_timings). No LLM calls. (AC-11)
3.  clauses = state.get("clauses", {}).
    If not clauses → log warning, return empty update. No LLM calls. (AC-12)
4.  Circuit-breaker state — a SINGLE MUTABLE HOLDER (see "Circuit-state holder"
    note below; do NOT use bare int/bool locals):
        cb = {"consecutive_failures": 0, "open": False, "tripped": False}
5.  clause_updates = {}.
6.  For each clause_id, record in document order (by position):
      a. text = (record.get("text") or "").strip()
         If empty → verdict = all-None, final_status = DISCARDED; log warning;
         stage & continue. No LLM calls. (Edge Case 6)
      b. evidence = record.get("evidence_snippets")
         empty_evidence = (evidence is None) or (len(evidence) == 0)
      c. clause_type_value = _clause_type_value(record.get("clause_type"))
         # normalizes ClauseType enum OR str OR None -> Optional[str]
      d. Compute the clause's verdict via one of three branches:

         BRANCH A — empty_evidence AND clause_type_value in HIGH_RISK set:
            isrel_verdict = None            # not-assessable, NOT False (spec §7.5)
            if cb["open"]:
                → fail-open default: relevance=None, issup=None, retry=None,
                  final_status=VALIDATED       # can't run rescue; surface it
            else:
                relevance = check_relevance(text, ...)      # 1 LLM call
                _account(relevance, cb)                     # circuit bookkeeping
                if relevance is None:  → fail-open (relevance=None, VALIDATED)
                elif relevance is False: → DISCARD (relevance=False, issup=None, retry=None)
                else:  # relevance True → ISSUP-on-clause-text loop (evidence empty)
                    (issup_verdict, retry_count, final_status) = _issup_loop(text, None, cb)

         BRANCH B — empty_evidence AND NOT high-risk (incl. clause_type None):
            → DISCARD with ZERO LLM calls (EXEMPT from the circuit's fail-open bulk
              outcome — this branch never consults the LLM, so it stays DISCARDED
              even when cb["open"] is True; spec §4.8 / AC-15):
              relevance=None, isrel=None, issup=None, retry=None,
              final_status=DISCARDED           # (AC-16b; counter untouched)

         BRANCH C — evidence present (normal 3-check short-circuit gate, §7.1):
            if cb["open"]: → fail-open default (all verdicts None, VALIDATED)
            else:
                relevance = check_relevance(text, ...);  _account(relevance, cb)
                if relevance is None:  → fail-open (VALIDATED, verdicts None)
                elif relevance is False: → DISCARD (relevance=False, isrel=None,
                                                    issup=None, retry=None)   # AC-2
                else:
                    isrel = check_isrel(text, evidence, ...);  _account(isrel, cb)
                    if isrel is None:  → fail-open (relevance=True, isrel=None, VALIDATED)
                    elif isrel is False: → DISCARD (relevance=True, isrel=False,
                                                    issup=None, retry=None)   # AC-3
                    else:
                        (issup_verdict, retry_count, final_status)
                            = _issup_loop(text, evidence, cb)

      e. Stage: clause_updates[clause_id] = {relevance_verdict, isrel_verdict,
         issup_verdict, retry_count, final_status}   # only the 5 verdict fields
      f. Per-clause structured log via logger.info(..., extra={...}). (spec §9)
7.  elapsed = time.monotonic() - start_time
8.  out = {"clauses": clause_updates, "current_node": current_node,
           "node_timings": {current_node: elapsed}}
    if cb["tripped"]:  out["error_count"] = 1                # health signal (R5)
    return out
```

**`_issup_loop(text, evidence, cb)` (shared by Branch A rescue and Branch C):**
```
for attempt in 1 .. SELF_RAG_MAX_ATTEMPTS:
    issup = check_issup(text, evidence, ...)      # evidence may be None (rescue)
    _account(issup, cb)                           # circuit bookkeeping
    if issup is None:                             # LLM failure mid-loop
        → return (issup_verdict=None, retry_count=None, final_status=VALIDATED)  # fail-open
    if issup is True:
        → return (issup_verdict=True, retry_count=attempt-1, final_status=VALIDATED)  # AC-4/5
    # issup is False → retry (a real verdict; _account reset the counter)
# exhausted all attempts, every ISSUP returned False:
→ return (issup_verdict=False, retry_count=SELF_RAG_MAX_ATTEMPTS-1, final_status=DISCARDED)  # AC-6
```

**`_account(verdict, cb)` — circuit-breaker bookkeeping (spec §4.8 / §8a R5):**
```
if verdict is None:                     # an LLM failure
    cb["consecutive_failures"] += 1
    if cb["consecutive_failures"] >= SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD and not cb["open"]:
        cb["open"] = True
        cb["tripped"] = True                # emit error_count:1 once at return
        logger.warning("Self-RAG LLM circuit opened after %d consecutive failures ...")
else:                                    # any real verdict = a successful call
    cb["consecutive_failures"] = 0
```
Only ISSUP `False` is a *retry* trigger; an LLM failure (`None`) short-circuits to fail-open and never spins the retry loop. Zero-LLM branches (Branch B, empty-text skip) touch neither counter.

**Circuit-state holder (implementation note — do not skip; per CLAUDE.md the implementer must not infer this):** `cb` is a **single mutable dict** threaded through `_account`/`_issup_loop`, NOT three bare `int`/`bool` locals. The reason is a Python scoping gotcha: `_account` and `_issup_loop` are nested helpers that *mutate* the breaker state, and rebinding an outer `int`/`bool` from a nested function requires a `nonlocal` declaration — omit it and Python either raises `UnboundLocalError` or silently creates a shadowing local, so the breaker would never actually open (defeating spec §4.8). Mutating a dict's **contents** (`cb["open"] = True`) needs no `nonlocal`, so the holder form removes the gotcha entirely. Pass `cb` explicitly into both helpers (`_account(verdict, cb)`, `_issup_loop(text, evidence, cb)`) — or define them as closures over `cb` — but do **not** use standalone `consecutive_failures`/`circuit_open`/`circuit_tripped_this_run` locals. (A tiny `@dataclass` with mutable fields is an acceptable equivalent; the dict is the lightest form.)

**Key invariants (make these explicit so they are testable):**
- **`isrel_verdict = None` on absent evidence, never `False`** — so no clause is ever left in the contradictory `isrel_verdict=False + final_status=VALIDATED` state (the class of inconsistency fixed in the 001 example). `False` is reserved for present-but-off-topic evidence (Branch C ISREL). (AC-16a)
- **Fail-open sets the *affected* verdict field to `None`** and `final_status = VALIDATED` — a fail-opened VALIDATED (`issup_verdict=None`) is thus distinguishable downstream from a genuinely model-validated one (`issup_verdict=True`). (spec §7.4, AC-14)
- **`error_count` increments at most once per run** — only when the breaker opens, never per-clause. (AC-20)

**Helper — `_clause_type_value(raw) -> Optional[str]`:** `clause_splitter_agent` stores `clause_type` as a `ClauseType` enum (or `None`). Normalize defensively: `raw.value if isinstance(raw, ClauseType) else (raw if isinstance(raw, str) else None)`, so membership against the `frozenset[str]` `SELF_RAG_HIGH_RISK_CLAUSE_TYPES` works whether the record carries the enum or its string value.

**Return shape (success):**
```python
{"clauses": clause_updates, "current_node": "self_rag_validation",
 "node_timings": {"self_rag_validation": elapsed}}
# + "error_count": 1  IFF the circuit opened during the run
```

**Return shape (defensive — ingest_error set, or empty clauses):**
```python
{"clauses": {}, "current_node": "self_rag_validation",
 "node_timings": {"self_rag_validation": elapsed}}
```

---

### Graph Wiring

#### [MODIFY] `backend/app/graph/builder.py`

Register the Self-RAG node and replace the temporary `crag_retrieval → END` edge with `crag_retrieval → self_rag_validation → END`:

```python
from app.graph.nodes.self_rag_validation_agent import self_rag_validation_agent

# Inside build_graph():
graph.add_node("self_rag_validation", self_rag_validation_agent)
graph.add_edge("crag_retrieval", "self_rag_validation")   # was END temporarily
graph.add_edge("self_rag_validation", END)                # → END until feature-007 (RiskScore)
```

Update the module docstring's "Current scope" note (builder.py:4–8) to include Node 4 and move the "→ END temporarily" comment to the Self-RAG edge.

**Constitution §2 note:** Self-RAG's outgoing edge is a **plain linear `add_edge`**. It is deliberately **not** an `add_conditional_edges` — the two conditional edges the constitution permits are CRAG's confidence routing (Node 3) and `route_on_risk` (Node 6). Discarded findings remain in `ContractState` marked `DISCARDED` and flow along the linear edge; downstream nodes filter on `final_status`. The node-name string `"self_rag_validation"` matches the pinned `current_node` value (spec §2) so state-key identity never drifts from the graph node name (constitution §8).

---

### Unit Tests

#### [NEW] `backend/tests/unit/test_self_rag_reflectors.py`

Tests for `check_relevance` / `check_isrel` / `check_issup` and `format_evidence` — mock `ollama.Client.chat`, no running Ollama:

| Test | Verifies |
|------|----------|
| `test_verdict_true_parsed` | `{"verdict": true}` → `True` |
| `test_verdict_false_parsed` | `{"verdict": false}` → `False` |
| `test_timeout_returns_none` | Simulated timeout → `None`, warning logged |
| `test_connection_error_returns_none` | Ollama unreachable → `None` |
| `test_malformed_json_returns_none` | Non-JSON body → `None` (fail-open trigger) |
| `test_missing_verdict_key_returns_none` | JSON without `verdict` → `None` |
| `test_non_bool_verdict_returns_none` | `{"verdict": "maybe"}` → `None` |
| `test_uses_generative_model_only` | `chat` called with `OLLAMA_MODEL_NAME`; `OLLAMA_EMBED_MODEL_NAME` never referenced (AC-9) |
| `test_relevance_prompt_excludes_evidence` | Relevance prompt is a function of clause text only |
| `test_issup_empty_evidence_uses_text_only_prompt` | With empty/None evidence, ISSUP prompt instructs "clause text alone" (spec §7.5) |
| `test_prompt_truncated_to_max_chars` | Oversized text+evidence truncated to `prompt_max_chars` before the call (spec §4.9) |
| `test_format_evidence_shape_and_empty` | `format_evidence` renders the 001 snippet shape; returns "" for None/empty |
| `test_reflector_never_raises` | Any injected exception → `None`, no propagation |

#### [NEW] `backend/tests/unit/test_self_rag_validation_agent.py`

Tests for the node — mock `check_relevance`, `check_isrel`, `check_issup` at the module level (Node 2 monkeypatch precedent) so verdicts are deterministic fixtures and call counts are assertable:

| Test | Verifies |
|------|----------|
| `test_all_clauses_get_final_status` | Every clause ends with non-None `final_status` (AC-1) |
| `test_relevance_fail_discards_short_circuit` | Relevance False → relevance=False, isrel=None, issup=None, retry=None, DISCARDED; **no** ISREL/ISSUP call (AC-2, AC-8) |
| `test_isrel_fail_discards_short_circuit` | Relevance True, ISREL False → isrel=False, issup=None, retry=None, DISCARDED; **no** ISSUP call (AC-3, AC-8) |
| `test_issup_pass_first_attempt_validated` | ISSUP True first try → issup=True, retry_count=0, VALIDATED (AC-4) |
| `test_issup_retry_then_pass_validated` | ISSUP False then True → issup=True, retry_count=(#priorFalse), VALIDATED (AC-5) |
| `test_issup_exhaustion_discarded` | ISSUP False every attempt → issup=False, retry_count=MAX-1, DISCARDED (AC-6) |
| `test_attempt_cap_enforced` | ≤ `SELF_RAG_MAX_ATTEMPTS` ISSUP calls (constant monkeypatched small) (AC-7) |
| `test_only_issup_retries` | Exactly one Relevance call and, when reached, one ISREL call — never retried (AC-8) |
| `test_uses_generative_not_embedding_model` | Passed model is `OLLAMA_MODEL_NAME` ≠ `OLLAMA_EMBED_MODEL_NAME` (AC-9) |
| `test_ingest_error_returns_empty` | `ingest_error` set → empty update, no LLM calls (AC-11) |
| `test_empty_clauses_returns_empty` | `clauses == {}` → empty update, warning, no LLM calls (AC-12) |
| `test_partial_update_only_no_error_count` | Non-outage run → keys exactly `{clauses, current_node, node_timings}`; no `error_count` (AC-13) |
| `test_graceful_llm_failure_fail_open` | A check returns None → clause VALIDATED, affected verdict None, no crash, other clauses proceed; `error_count` NOT incremented for a single failure (AC-14) |
| `test_circuit_breaker_opens` | After `THRESHOLD` consecutive failures, remaining clauses take default outcome with **no** further LLM calls; one "circuit opened" warning (AC-15) |
| `test_circuit_resets_on_success` | An interleaved real verdict resets the consecutive counter (breaker not tripped by intermittent single failures) |
| `test_empty_evidence_high_risk_validates_on_text` | Empty evidence + high-risk type + Relevance True + text-ISSUP True → relevance=True, isrel=None, issup=True, VALIDATED (AC-16, AC-16a) |
| `test_empty_evidence_high_risk_relevance_false_discards` | Empty evidence + high-risk type + Relevance **False** → relevance=False, isrel=None, issup=None, retry=None, DISCARDED; **no** ISSUP call (rescue path Relevance-fail branch, spec §7.5) |
| `test_empty_evidence_high_risk_issup_false_discards` | Same but text-ISSUP False to exhaustion → DISCARDED, isrel=None |
| `test_empty_evidence_non_high_risk_zero_llm_discard` | Empty evidence + non-high-risk type → all verdicts None, DISCARDED, **zero** LLM calls (AC-16b) |
| `test_zero_llm_branches_exempt_from_fail_open_after_trip` | After the circuit opens, a subsequent Branch-B (non-high-risk empty-evidence) clause and an empty-text clause still reach **DISCARDED**, not fail-open VALIDATED (spec §4.8 / AC-15 carve-out) |
| `test_empty_evidence_clause_type_none_discards` | Empty evidence + `clause_type=None` → zero-LLM DISCARD (residual-gap case, spec §7.5) |
| `test_no_isrel_false_with_validated` | Invariant: no clause ends `isrel_verdict=False` + `VALIDATED` (AC-16a) |
| `test_current_node_pinned` | `current_node == "self_rag_validation"` and same key in `node_timings` (AC-17) |
| `test_rerun_overwrites_verdicts` | Pre-existing verdict fields overwritten; reducer preserves text/evidence (AC-18) |
| `test_discarded_clause_still_present` | DISCARDED clause remains in the update; no clause IDs removed (AC-19) |
| `test_circuit_open_emits_error_count_once` | Breaker opens → return includes `error_count: 1` exactly once; never-open run has no `error_count` key (AC-20) |
| `test_empty_clause_text_skipped` | Whitespace-only text → all verdicts None, DISCARDED, no LLM call (Edge Case 6) |
| `test_clause_type_enum_or_str_gate` | High-risk gate matches whether `clause_type` is a `ClauseType` enum or its `.value` string |

> **AC-10 coverage note:** AC-10 ("all constants read from `app.config`, never hardcoded") has no dedicated row — it is covered *implicitly*: a hardcoded attempt cap, threshold, or high-risk set would break `test_attempt_cap_enforced`, `test_circuit_breaker_opens`, and the empty-evidence gate tests, all of which monkeypatch the re-exposed module-level names. Accepted coverage, flagged so it isn't mistaken for a direct assertion (same stance as the CRAG plan's AC-9 note).

#### [MODIFY] `backend/tests/unit/test_config.py`

| Test | Verifies |
|------|----------|
| `test_self_rag_constants_match_spec` | `SELF_RAG_MAX_ATTEMPTS`, `SELF_RAG_TIMEOUT_SECONDS`, `SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD`, `SELF_RAG_PROMPT_MAX_CHARS` match spec §6 |
| `test_self_rag_constants_correct_types` | `int` for the numeric constants; `frozenset` of `str` for the high-risk set |
| `test_self_rag_high_risk_types_are_valid_clause_types` | Every entry in `SELF_RAG_HIGH_RISK_CLAUSE_TYPES` is a valid `ClauseType.value` (guards against typos / enum drift) |
| `test_self_rag_max_retries_renamed` | Old `SELF_RAG_MAX_RETRIES` is gone; `SELF_RAG_MAX_ATTEMPTS` exists (spec §8b Q2) |
| `test_self_rag_uses_generative_model` | Node's generative model is `OLLAMA_MODEL_NAME`, and `OLLAMA_MODEL_NAME != OLLAMA_EMBED_MODEL_NAME` (constitution §8) |

---

### Integration Tests

#### [NEW] `backend/tests/integration/test_self_rag_validation_graph.py`

Self-RAG wired into the graph. The three reflective judgments are mocked (no live Ollama); CRAG's evidence is either produced by the real upstream nodes with embed/web mocked, or injected as a pre-built `clauses` fixture, depending on the case:

| Test | Verifies |
|------|----------|
| `test_graph_reaches_self_rag_and_ends` | Full path Node1→2→3→4 reaches END with every clause carrying a `final_status` |
| `test_graph_ingest_error_skips_self_rag` | Ingest error short-circuits to END without reaching Self-RAG |
| `test_graph_validated_and_discarded_coexist` | A mixed fixture yields both VALIDATED and DISCARDED clauses, all still present in state (AC-19, Edge Case 12) |
| `test_graph_empty_evidence_gate_end_to_end` | A high-risk empty-evidence clause validates on text while a non-high-risk empty-evidence clause is discarded, in one run |
| `test_graph_circuit_open_sets_error_count` | Forcing all judgments to fail opens the breaker → final state `error_count == 1` and remaining clauses VALIDATED (fail-open) (AC-15, AC-20) |
| `test_graph_checkpointing_after_self_rag` | State is checkpointed after Self-RAG completes |

**Note:** a separate *manual* end-to-end test (not in the automated suite) can run with live Ollama (`qwen3:14b`) against a real contract to sanity-check judgment quality and tune the prompts / thresholds.

---

## 3. Dependency & Import Map

```
app/config.py
    └── (no imports — pure constants; frozenset from builtins)

app/graph/nodes/validators/__init__.py
    └── typing (stdlib — defines format_evidence)

app/graph/nodes/validators/reflectors.py
    ├── concurrent.futures, json, logging (stdlib)
    ├── httpx (timeout type), ollama
    └── app.graph.nodes.validators (format_evidence)
        # model_name/timeout/limits passed in — no app.config import here

app/graph/nodes/self_rag_validation_agent.py
    ├── time, logging (stdlib)
    ├── app.graph.state (ContractState, ClauseType, ValidationStatus)
    ├── app.graph.nodes.validators.reflectors (check_relevance, check_isrel, check_issup)
    └── app.config — imported AS A MODULE (`import app.config as _config`) with the
                     Self-RAG constants re-exposed as module-level names, read by bare
                     name so tests can monkeypatch them (Node 2 precedent,
                     clause_splitter_agent.py:28,39-42).

app/graph/builder.py
    ├── langgraph.graph (StateGraph, END)
    ├── app.graph.state (ContractState)
    ├── app.graph.nodes.ingest_agent (ingest_agent)
    ├── app.graph.nodes.clause_splitter_agent (clause_splitter_agent)
    ├── app.graph.nodes.crag_retrieval_agent (crag_retrieval_agent)
    └── app.graph.nodes.self_rag_validation_agent (self_rag_validation_agent)
```

No `numpy` / `faiss` / `duckduckgo_search` — Self-RAG is purely generative-LLM, no vectors or retrieval (constitution §8; spec §5.4).

---

## 4. Implementation Order

Following TDD per constitution §7 — tests written and confirmed failing before implementation.

| Step | Action | Files |
|------|--------|-------|
| 1 | Write config tests for the new Self-RAG constants + rename (confirm failing) | `tests/unit/test_config.py` |
| 2 | Replace the `SELF_RAG_MAX_RETRIES` placeholder with the spec §6 constants | `app/config.py` |
| 3 | Run config tests (confirm passing) | — |
| 4 | Implement `format_evidence` in the validators package | `app/graph/nodes/validators/__init__.py` |
| 5 | Write unit tests for the three reflectors (confirm failing) | `tests/unit/test_self_rag_reflectors.py` |
| 6 | Implement `reflectors.py` (shared `_run_judgment` + 3 prompts) | `app/graph/nodes/validators/reflectors.py` |
| 7 | Run reflector tests (confirm passing) | — |
| 8 | Write unit tests for the node (confirm failing) | `tests/unit/test_self_rag_validation_agent.py` |
| 9 | Implement `self_rag_validation_agent.py` | `app/graph/nodes/self_rag_validation_agent.py` |
| 10 | Run node tests (confirm passing) | — |
| 11 | Update graph builder (add node, rewire crag → self_rag → END) | `app/graph/builder.py` |
| 12 | Write and run integration tests (mocked judgments) | `tests/integration/test_self_rag_validation_graph.py` |
| 13 | Full test suite pass (all existing + new) | all tests |

> **Note on Step 4**: `format_evidence` is a shared, dependency-free helper (like `make_snippet` in `retrievers/__init__.py`) — it precedes the reflector tests that import it, without its own TDD cycle.

---

## 5. Design Decisions & Rationale

### Reflectors return `Optional[bool]`, node interprets `None` as failure
A three-valued return (`True`/`False`/`None`) is the smallest contract that lets the node distinguish a real verdict from an un-runnable judgment, exactly as `embed_query` returns `Optional[np.ndarray]` in CRAG. It keeps the fail-open policy (spec §8a R3) and the circuit-breaker bookkeeping entirely in the node, where all state lives — the reflectors stay pure, stateless, and independently testable with the LLM mocked.

### Sequential short-circuit, retry only ISSUP (spec §8a R1/R2)
Relevance → ISREL → ISSUP as three focused calls, stopping at the first `False`. Each call gets the model's full attention on one judgment (a single combined call invites conflating the three), and short-circuiting spends **zero** LLM calls on clauses that fail an early gate — material over 100–200 clauses (constitution §9). Only ISSUP retries, and a retry re-runs the *same* judgment (a self-consistency re-sample against LLM non-determinism), never regenerates a finding — Node 4 is a gate, not a generator, so no finding text is produced or persisted (spec §5.6).

### Empty-evidence: `clause_type`-gated, `isrel=None` not `False` (spec §8a R4 / §7.5)
Blanket-discard risks dropping a genuinely dangerous clause CRAG simply failed to retrieve for; blanket-validate-on-text risks a false-positive flood and heavy LLM load. Gating on `clause_type` — which Node 2 already assigns — spends the unaided-LLM judgment only on the high-stakes categories where a silent miss is costliest, and short-circuits everything else to a no-LLM discard. Setting `isrel_verdict = None` (not `False`) on absent evidence keeps the field honest ("not assessable" ≠ "off-topic") and structurally prevents the `isrel=False + VALIDATED` contradiction. The residual gap (a dangerous clause left `clause_type=None` by Node 2) is accepted for Phase 1 and made observable via the §9.2/§9.6 metrics; the high-risk set is a config knob to widen if the data warrants.

### Fail-open, with a circuit-open health signal (spec §8a R3/R5)
For a risk detector, a missed risk is costlier than a spurious flag, so an unrecoverable LLM failure surfaces the clause (`VALIDATED`) rather than dropping it. But a *wholesale* outage that fail-opens everything must not masquerade as a clean run — so the circuit breaker opening emits `error_count: 1` **once**. A single flaky call stays silent (matching Nodes 2/3); only the breaker speaks. And because a fail-opened clause carries `issup_verdict=None` (vs `True` for a model-validated one), downstream nodes and the report can still tell the two apart.

### Circuit breaker as a runtime guarantee (spec §4.8, AC-15)
Without it, an unreachable Ollama makes every clause pay `SELF_RAG_TIMEOUT_SECONDS` per check — pathological over a large contract. After `SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD` **consecutive** failures the node stops calling the LLM and applies the fail-open default to the rest. The counter resets on any success, so intermittent single failures never trip it. Per-run only; not persisted. Directly mirrors CRAG's embed circuit breaker.

### `ThreadPoolExecutor` + `Client(timeout=…)` for the LLM bound
Copied from `llm_refiner.py`: `ollama.Client(timeout=…)` aborts the underlying HTTP call (so a hung socket can't outlive the timeout and defeat the breaker), and `future.result(timeout=…)` is the backstop. This is the same correctness argument the CRAG plan makes for `embed_query`; using a bare `ollama.chat` bounded only by the executor would be a latent hang.

### Separate validators package
`reflectors.py` is independently testable (LLM mocked, no network, no vectors) and independently replaceable — same rationale as splitting `regex_splitter.py` / `llm_refiner.py` in Node 2 and the retrievers in Node 3.

### Logging strategy (spec §9)
Named logger `contractsentinel.self_rag_validation`. `ContractState` carries only aggregate `node_timings["self_rag_validation"]`; all eval metrics (validation rate, discard-reason breakdown incl. the empty-evidence gate outcomes, retry distribution, per-check verdicts, per-check/per-clause latency, circuit events) are emitted as `logger.info(..., extra={...})` structured records for the eval harness (`specs/002-tech-stack.md` §3i) — never added as per-clause state fields. Mirrors `crag_retrieval_agent.py`.

---

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Ollama / `qwen3:14b` not running at pipeline time | Every judgment fails | Reflectors use `ollama.Client(timeout=…)` so each call aborts; circuit breaker then collapses remaining cost to a constant and fail-opens the rest; `error_count:1` health signal surfaces the degraded run (R5) |
| Hung Ollama socket outliving the executor timeout | Node blocks past timeout, defeating the breaker | `Client(timeout=…)` aborts the underlying call (primary bound); `future.result(timeout=…)` is the backstop — same pattern as `llm_refiner.py` |
| Fail-open floods Node 5 when Ollama is down | Report says "everything validated" | Accepted per R3 (bias against false negatives), but bounded and made visible: `issup_verdict=None` distinguishes fail-opened from model-validated, and the breaker emits `error_count:1` (R5) so the run is flagged degraded |
| LLM returns prose / malformed JSON instead of `{"verdict": …}` | Verdict unparseable | `format="json"` + strict parse; any parse failure → `None` → fail-open (spec §4.4); covered by `test_malformed_json_returns_none` |
| Dangerous clause left `clause_type=None` by Node 2, with empty evidence | Silent false negative (zero-LLM discard) | Accepted Phase-1 residual (spec §7.5); made observable via discard-reason (§9.2) and empty-evidence (§9.6) metrics; `SELF_RAG_HIGH_RISK_CLAUSE_TYPES` is a tunable widen-knob |
| Large clause count × per-call timeouts × 3 checks | Slow aggregate runtime | Short-circuit skips checks on early-discarded clauses; circuit breaker bounds the outage case; sequential processing keeps memory flat; per-call timeouts bound each call (constitution §9) |
| `clause_type` stored as enum vs string drift | High-risk gate silently misses | `_clause_type_value` normalizes enum/str/None; `test_clause_type_enum_or_str_gate` + `test_self_rag_high_risk_types_are_valid_clause_types` guard both ends |
| `error_count` increment misread as a hard pipeline error downstream | Spurious abort/retry | It is a single health-signal increment via `operator.add`, not a control flag; spec §2 states downstream behavior on `error_count` is unchanged; capped at one per run |
| Renaming `SELF_RAG_MAX_RETRIES` breaks a hidden reference | Import/AttributeError | Grep confirms no current references (Node 4 unimplemented); `test_self_rag_max_retries_renamed` locks the rename |

---

## 7. Out of Scope for This Plan

- **Nodes 5–7**: not wired or implemented. `builder.py` routes `self_rag_validation` → END until feature-007 (RiskScore).
- **Assigning a risk level (Low/Medium/High)**: RiskScoreAgent (Node 5), `specs/007-*`. Self-RAG decides only validated-vs-discarded (spec §5.1).
- **Drafting safer clause language (redlining)**: RedlineAgent (Node 6) (spec §5.2).
- **`evidence_trail` compilation**: ReportAgent (Node 7); Self-RAG writes only per-clause verdict fields (spec §5.3).
- **Gathering / scoring evidence, retrieval routing, embeddings**: CRAG (Node 3); Self-RAG consumes `evidence_snippets` as given (spec §5.4).
- **The `route_on_risk` conditional edge**: Node 6's edge; Self-RAG's edge is a plain linear `add_edge` (spec §5.5).
- **Persisting a candidate-finding statement / finding text**: ephemeral, not written to state; a future 001-schema change under constitution §10 if ever needed (spec §5.6 / §8b Q3).
- **Human-in-the-loop review of discarded findings**: no review/override UI (spec §5.7; PERMANENTLY CUT audit-log UI).
- **Bounded-parallelism over clauses**: sequential for Phase 1; a concurrency knob is deferred (spec §5.8 / §7 note).
- **Regenerate-and-recritique Self-RAG loop**: rejected (R1) — retry re-runs ISSUP only.
- **Prompt-wording finalization for Relevance vs ISREL semantics**: pinned provisionally (spec §8b Q1); tunable without control-flow change.
- **API endpoints, DB storage, MCP delivery, privacy/security**: per Phase 2 deferral / other specs.
