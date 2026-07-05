# RiskScore Technical Plan

## Git Branch

`feature/007-risk-score` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

This plan details how to implement the **RiskScore node (Node 5)** as specified in `specs/007-risk-score/spec.md`. The node is the **severity-assignment stage** between "these clauses are worth flagging" (Node 4, Self-RAG) and "draft a safer version of the risky ones" (Node 6, Redline). For **each validated finding** (`final_status == ValidationStatus.VALIDATED`) it makes **one** generative LLM call that returns a `RiskLevel` (`LOW`/`MEDIUM`/`HIGH`) plus a short `risk_rationale`, and writes both back into that clause record.

Only `VALIDATED` clauses are scored. `DISCARDED` clauses (Self-RAG suppressed them as noise) and any defensively-`None` `final_status` are **skipped with no LLM call and left untouched** — the node returns only the clause IDs it actually scored, and the `merge_nested_clause_dicts` reducer preserves the rest (constitution §5).

The node writes only `clauses` (via the reducer) plus `current_node` and `node_timings`, per the partial-update rule. The **one** exception is the circuit-open health signal: a single `error_count: 1` when the LLM backend is declared down for the run (spec §2 / §4.5 / §7.4).

All configurable thresholds live in `app/config.py` per constitution §3. The single LLM call uses the **generative** model `OLLAMA_MODEL_NAME` (Qwen3 via Ollama) — the same model Nodes 2 and 4 use. The node makes **no vector calls** and never references `OLLAMA_EMBED_MODEL_NAME` (constitution §8 model-separation; CRAG already produced the evidence, Self-RAG already validated).

**Resolved design decisions carried from the spec (§8a):**
- **R1 — Fail-safe default = `HIGH`.** A finding that passed Self-RAG's "worth flagging" gate but could not be scored surfaces at maximum severity rather than being silently downgraded — the risk-tool bias against false negatives, directly analogous to Self-RAG's fail-open to `VALIDATED`. It is a tunable config constant, and the circuit-breaker `error_count:1` keeps a wholesale-defaulted run distinguishable from a genuinely all-`HIGH` document.
- **R2 — `RiskLevel` stays `LOW`/`MEDIUM`/`HIGH`;** "clean" is not a Node-5 outcome (that is Self-RAG `DISCARDED`, handled at Node 6). No `001`-schema change.
- **R3 — Empty/whitespace text on a validated finding → fail-safe default** (skip the LLM), so no validated finding ever reaches Node 6 without a `risk_level`.
- **R4 — No document-level roll-up risk** (a Node-7 concern; out of scope here).
- **R5 — Scoring method: pure LLM, single call, `clause_type` as soft context.** No rule-based lookup, no hybrid.
- **R6 — No retry loop.** Constitution §2 scopes retries to Self-RAG's ISSUP check only; a single unparseable/failed call takes the fail-safe default (no `RISK_SCORE_MAX_ATTEMPTS`).
- **R7 — State-key name `"risk_score"`,** matching `builder.py` and the `crag_retrieval` / `self_rag_validation` naming pattern.

This node's outgoing graph edge is a **plain linear `add_edge`** (`risk_score → redline`, wired to `END` until feature-008). RiskScore is **not** one of the two conditional edges the constitution permits — those are CRAG's confidence routing (Node 3) and Node 6's `route_on_risk`, which *reads* the `risk_level` this node writes. RiskScore assigns severity; it does not route.

**One design tension recorded for Node 6 (`008`), not a Node-5 change (spec §8b):** because every validated finding gets `LOW`/`MEDIUM`/`HIGH` (all "risk found") and "clean" was already consumed by Self-RAG discard, `route_on_risk`'s "no risk → SkipRedline" branch may never fire for a validated finding unless `008` deliberately maps `LOW → SkipRedline`. Node 5 assigns the level regardless; the routing threshold is `008`'s call.

---

## 2. Files to Create / Modify

### Shared Config Module

#### [MODIFY] `backend/app/config.py`

Add a new `# ── RiskScore thresholds` block (no RiskScore constant exists yet — this is a pure addition, no rename). The default-level constant is stored as the `RiskLevel` enum, matching spec §6.

**Import note (verified acyclic):** this block requires `from app.graph.state import RiskLevel` at the top of `config.py`. `config.py` currently has **zero** imports; adding this one is safe because `app.graph.state` imports only stdlib (`typing`, `enum`, `operator`) and the `app` / `app.graph` package `__init__.py` files are empty stubs — so `app.config → app.graph.state` never cycles back to `app.config`. (Confirmed by reading all three `__init__.py` and `state.py`.)

```python
from app.graph.state import RiskLevel   # add near top of config.py (only import in the module)

# ── RiskScore thresholds ───────────────────────────────────────────────────────
# Source: specs/007-risk-score/spec.md §6

RISK_SCORE_TIMEOUT_SECONDS: int = 120
# Wall-clock timeout for a single RiskScore LLM call (one severity judgment) via
# Ollama. Mirrors SELF_RAG_TIMEOUT_SECONDS; headroom for local Qwen3 per
# constitution §9. On timeout the finding takes the fail-safe default (spec §4.4).

RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD: int = 5
# Number of CONSECUTIVE LLM failures after which the node declares the generative
# backend down for the rest of the run and applies the fail-safe default level to
# all remaining validated findings (skipping per-finding timeouts). Resets on any
# success. Opening emits the error_count health signal once (spec §4.5, AC-14/15).
# Mirrors SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD.

RISK_SCORE_PROMPT_MAX_CHARS: int = 6000
# Clause text + concatenated evidence snippets are truncated to this length before
# the scoring LLM call, to bound prompt size (spec §4.8). Mirrors
# SELF_RAG_PROMPT_MAX_CHARS.

RISK_RATIONALE_MAX_CHARS: int = 1000
# Generated risk_rationale is truncated to this length before being written to
# ContractState, to bound persisted state size (spec §4.9). Unlike Self-RAG's
# ephemeral candidate-finding text, risk_rationale IS persisted — 001 reserves it.

RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE: RiskLevel = RiskLevel.HIGH
# Fail-safe severity applied when a finding cannot be scored (LLM failure, timeout,
# unparseable output, empty text, or circuit open) — spec §4.4 / §7.2 / §8a R1.
# HIGH biases toward surfacing at maximum severity for human review, consistent with
# Self-RAG's fail-open to VALIDATED. Configurable because it directly shifts
# downstream Redline load; tune against real sample contracts.
```

The node also reuses the existing `OLLAMA_MODEL_NAME` — it introduces no new model constant. There is intentionally **no** `RISK_SCORE_MAX_ATTEMPTS` (spec §8a R6 — no retry loop).

---

### Scorers Package

New package `backend/app/graph/nodes/scorers/`, following the same structure precedent as `validators/` (Node 4) and `retrievers/` (Node 3): a package `__init__.py` plus one module for the severity judgment, independently testable with the LLM mocked at the boundary.

#### [NEW] `backend/app/graph/nodes/scorers/__init__.py`

A package marker with a module docstring. It does **not** redefine an evidence formatter: `risk_scorer.py` reuses the existing, dependency-free `format_evidence` from the validators package (see the import note below), so there is no shared helper to export here.

#### [NEW] `backend/app/graph/nodes/scorers/risk_scorer.py`

The single severity judgment. Returns `Optional[Tuple[RiskLevel, str]]` and **never raises** — the exception boundary is load-bearing (spec §4.4). Contract for the caller (the node):

- `(RiskLevel, rationale)` → a real score from the model
- `None` → the judgment **could not be run** (Ollama unreachable, timeout, or unparseable/invalid response) → the node treats this as an unrecoverable LLM failure, applies the fail-safe default, and counts it toward the circuit breaker (spec §4.4 / AC-12/13).

```python
from typing import List, Dict, Any, Optional, Tuple
from app.graph.state import RiskLevel
from app.graph.nodes.validators import format_evidence   # reuse — see note

def score_risk(
    clause_text: str,
    evidence_snippets: Optional[List[Dict[str, Any]]],
    clause_type: Optional[str],
    timeout_seconds: int,
    model_name: str,
    prompt_max_chars: int,
) -> Optional[Tuple[RiskLevel, str]]:
    """Single generative call assigning Low/Medium/High severity to a validated
    finding, plus a short rationale. evidence_snippets is used as scoring context
    when present (the 001 shape); may be []/None (Self-RAG's high-risk rescue path)
    in which case scoring is on clause text + clause_type alone. clause_type is a
    normalized string label (or None) used as a soft prior in the prompt.
    Returns (RiskLevel, rationale) or None on any LLM failure / unparseable output.
    Never raises."""
```

Implementation notes (mirror `reflectors.py` structurally):
- **Shared invocation core.** A private `_run_scoring(prompt, timeout_seconds, model_name) -> Optional[Tuple[RiskLevel, str]]` performs the Ollama call and parses the result, via `_call_ollama` + `_parse_score`. Same split as `reflectors.py:157-217`.
- **Ollama call + timeout — copy the Node 4 pattern exactly (spec §4.4, constitution §9).** `ollama.Client(timeout=timeout_seconds).chat(model=model_name, messages=[...], format="json", options={"num_predict": <small, e.g. 384>})` **inside** a `concurrent.futures.ThreadPoolExecutor(max_workers=1)` with `future.result(timeout=timeout_seconds)`. `Client(timeout=…)` is the **primary** bound (aborts the underlying `httpx` call so a hung socket cannot outlive the timeout and defeat the circuit breaker); the executor `future.result(timeout=…)` is the backstop. `num_predict` is a little larger than the reflectors' 256 because the response carries a short rationale, not just a bool.
  - **`num_predict` must comfortably exceed the token-equivalent of `RISK_RATIONALE_MAX_CHARS` + the JSON scaffolding.** Unlike the reflectors (which emit a tiny bool), this call emits prose: if `num_predict` cuts the model off mid-object, the body is invalid JSON → `_parse_score` returns `None` → the finding is treated as a scoring **failure** (fail-safe HIGH *and* a tick toward the circuit breaker), which is wrong for a finding the model was scoring fine. `RISK_RATIONALE_MAX_CHARS = 1000` chars ≈ ~250 tokens; the prompt asks for "one or two sentences" (~40 tokens), so `384` gives ~6× headroom and is safe. The invariant to preserve when tuning either value: `num_predict` stays well above `RISK_RATIONALE_MAX_CHARS`-in-tokens so a legitimately long rationale is never misread as a failed call. (Kept inline like the reflectors' `256`; promote to a named constant only if it later needs per-deployment tuning.)
- **JSON score contract.** Prompt the model to return `{"risk_level": "low"|"medium"|"high", "rationale": "<one or two sentences>"}`. Parse:
  - `risk_level` → `RiskLevel(value.strip().lower())` inside a `try`; a `ValueError` (value not one of the three) → treat as **unparseable** → return `None` (AC-13/22). Reject non-`str` `risk_level` too.
  - `rationale` → coerced to `str` (default `""`); returned **untruncated** (the node applies `RISK_RATIONALE_MAX_CHARS` before writing to state — single owner of state-bound size).
  - Non-JSON body, missing `risk_level` → `None`. Catch `concurrent.futures.TimeoutError`, `httpx.TimeoutException`, and any `Exception` → `None` with a rate-limited warning. Never raises.
- **Prompt truncation.** `clause_text` and (via `format_evidence`) the evidence block are truncated so their combined length is bounded by `prompt_max_chars` before the call (spec §4.8, AC-19), same arithmetic as the reflectors (`clause_trunc = clause_text[:prompt_max_chars]; remaining = max(0, prompt_max_chars - len(clause_trunc))`). Truncation logged at debug.
- **Prompt content.** One prompt template with an evidence-present and an evidence-absent variant (mirroring `_ISSUP_WITH_EVIDENCE_PROMPT` / `_ISSUP_TEXT_ONLY_PROMPT`). Both state the rubric: **Low** = minor/standard deviation, **Medium** = a materially one-sided or non-standard term, **High** = a severe, uncapped, or unilateral risk. `clause_type` is inserted as soft context ("This clause is categorized as: {clause_type_or_unspecified}"). The exact wording is tunable later without changing control flow.
- **Reuse of `format_evidence` (import note).** `risk_scorer.py` imports `format_evidence` from `app.graph.nodes.validators` rather than redefining it. It is a generic, dependency-free renderer of the 001 evidence shape (`validators/__init__.py:13-30`); duplicating it would invite drift. This is the single cross-node-package import in this feature and is deliberate; if a future refactor wants a neutral home for it, that move is out of scope here.

---

### RiskScore Node

#### [NEW] `backend/app/graph/nodes/risk_score_agent.py`

The LangGraph node — the only file that touches `ContractState`. Owns the per-clause loop, the `VALIDATED`-only gate, the fail-safe default, the circuit breaker, and the health signal. Structurally mirrors `self_rag_validation_agent.py`.

```python
import app.config as _config  # module import so tests can monkeypatch (Node 2/4 precedent)

logger = logging.getLogger("contractsentinel.risk_score")

# Re-exposed module-level names for monkeypatching (mirrors self_rag_validation_agent.py):
OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME
RISK_SCORE_TIMEOUT_SECONDS = _config.RISK_SCORE_TIMEOUT_SECONDS
RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD = _config.RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD
RISK_SCORE_PROMPT_MAX_CHARS = _config.RISK_SCORE_PROMPT_MAX_CHARS
RISK_RATIONALE_MAX_CHARS = _config.RISK_RATIONALE_MAX_CHARS
RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE = _config.RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE


def risk_score_agent(state: ContractState) -> dict:
    """LangGraph Node 5. Reads clauses/document_id/ingest_error; scores only
    VALIDATED findings; returns partial dict: clauses (per-finding risk_level +
    risk_rationale), current_node, node_timings, and error_count:1 ONLY when the
    circuit breaker opened."""
```

**Internal flow:**

```
1.  current_node = "risk_score"; record start_time.
2.  Defensive: if state.get("ingest_error") is not None → return empty update
    (clauses={}, current_node, node_timings). No LLM calls. (AC-8)
3.  clauses = state.get("clauses", {}).
    If not clauses → log warning, return empty update. No LLM calls. (AC-9)
4.  Circuit-breaker state — a SINGLE MUTABLE HOLDER (see "Circuit-state holder"
    note; do NOT use bare int/bool locals):
        cb = {"consecutive_failures": 0, "open": False, "tripped": False}
5.  clause_updates = {}.
6.  For each clause_id, record in document order (by position):
      a. final_status = record.get("final_status")
         if final_status != ValidationStatus.VALIDATED:
             continue        # skip DISCARDED / None — no update, no LLM call (AC-2, AC-3, AC-10)
      b. text = (record.get("text") or "").strip()
         if not text:        # Edge Case 6 — validated finding with empty text (defensive)
             clause_updates[clause_id] = _failsafe("clause text was empty; assigned default severity")
             log warning; continue        # CIRCUIT-NEUTRAL: no _account call (AC-14a)
      c. if cb["open"]:       # backend already declared down this run
             clause_updates[clause_id] = _failsafe("scoring backend unavailable; assigned default severity")
             continue                      # CIRCUIT-NEUTRAL bulk default: no _account, no LLM (AC-14a)
      d. evidence = record.get("evidence_snippets")     # may be []/None (rescue path) — fine (AC-20)
         ct_label = _clause_type_value(record.get("clause_type"))   # enum/str/None -> Optional[str]
         result = score_risk(text, evidence, ct_label,
                             RISK_SCORE_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME,
                             RISK_SCORE_PROMPT_MAX_CHARS)             # 1 LLM call
         _account(result, cb)              # None increments counter; a real score resets it
         if result is None:
             clause_updates[clause_id] = _failsafe("scoring failed; assigned default severity")   # (AC-12/13)
         else:
             level, rationale = result
             clause_updates[clause_id] = {
                 "risk_level": level,
                 "risk_rationale": rationale[:RISK_RATIONALE_MAX_CHARS],   # (AC-18)
             }
      e. Per-finding structured log via logger.info(..., extra={...}). (spec §9)
7.  elapsed = time.monotonic() - start_time
8.  Aggregate metrics log (level distribution, failure count, circuit_opened). (spec §9)
    This log MUST fire unconditionally — including when clause_updates == {} — so a
    non-empty-but-all-DISCARDED document still emits the AC-10 info line ("0 validated
    findings scored, N clauses skipped"). AC-10's info line lives here, distinct from
    the empty-clauses WARNING in step 3.
9.  out = {"clauses": clause_updates, "current_node": current_node,
           "node_timings": {current_node: elapsed}}
    if cb["tripped"]:  out["error_count"] = 1                # health signal (R1/§7.4)
    return out
```

**`_failsafe(reason)` helper:**
```
return {"risk_level": RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE,          # RiskLevel.HIGH (AC-12)
        "risk_rationale": f"[auto] {reason} (default={RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE.value})"}
```
The rationale explicitly records that the level was assigned automatically, so a fail-safe HIGH is distinguishable from a model-assigned HIGH both in state and in the report (spec §4.4). The `[auto]` marker is the tell.

**`_account(result, cb)` — circuit-breaker bookkeeping (spec §4.5 / AC-14/14a):**
```
if result is None:                      # a genuine LLM failure (call was issued)
    cb["consecutive_failures"] += 1
    if cb["consecutive_failures"] >= RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD and not cb["open"]:
        cb["open"] = True
        cb["tripped"] = True                # emit error_count:1 once at return
        logger.warning("RiskScore LLM circuit opened after %d consecutive failures ...")
else:                                   # a real (level, rationale) = a successful call
    cb["consecutive_failures"] = 0
```
**Circuit-neutrality (spec AC-14a — do not skip):** `_account` is called **only** for paths that actually issued an LLM call (step 6d). The empty-text fail-safe (6b) and the post-open bulk default (6c) reach the default **without** an LLM call and therefore **must not** call `_account` — they neither increment nor reset the counter. This is what prevents a document full of empty-text validated findings from spuriously opening the circuit and emitting a false `error_count:1`. Mirrors Self-RAG's zero-LLM Branch B exemption (`self_rag_validation_agent.py:167`).

**Circuit-state holder (implementation note — do not skip; per CLAUDE.md the implementer must not infer this):** `cb` is a **single mutable dict** threaded through `_account`, NOT three bare `int`/`bool` locals. Rebinding an outer `int`/`bool` from a nested helper requires `nonlocal`; omit it and Python raises `UnboundLocalError` or silently shadows, so the breaker would never open (defeating spec §4.5). Mutating a dict's **contents** (`cb["open"] = True`) needs no `nonlocal`. Pass `cb` explicitly into `_account`, or define `_account` as a closure over `cb` — but do **not** use standalone `consecutive_failures`/`circuit_open` locals. (Identical to the Node 4 holder; a small mutable `@dataclass` is an acceptable equivalent.)

**Helper — `_clause_type_value(raw) -> Optional[str]`:** identical to Node 4's (`self_rag_validation_agent.py:355-364`) — `raw.value if isinstance(raw, ClauseType) else (raw if isinstance(raw, str) else None)` — so the scorer receives a plain string label (or `None`) whether the record stored a `ClauseType` enum or its `.value` string.

**Key invariants (make these explicit so they are testable):**
- **Every VALIDATED finding gets a non-`None` `risk_level ∈ {LOW,MEDIUM,HIGH}` and a non-empty `risk_rationale`** — including the empty-text and circuit-open paths (via `_failsafe`). No validated finding reaches Node 6 unscored (spec §7.3, AC-1). (AC-3/R3)
- **Non-`VALIDATED` clauses are never in the return** — the reducer leaves their `risk_level`/`risk_rationale` absent; no LLM call is made for them (AC-2, AC-5).
- **`suggested_rewrite` is never written here** (Node 6 owns it, AC-21).
- **`error_count` increments at most once per run** — only when the breaker opens, never per-finding (AC-15).
- **Only LLM-issuing failures move the consecutive counter** — zero-LLM fail-safe paths are circuit-neutral (AC-14a).

**Return shape (success):**
```python
{"clauses": clause_updates, "current_node": "risk_score",
 "node_timings": {"risk_score": elapsed}}
# + "error_count": 1  IFF the circuit opened during the run
```

**Return shape (defensive — ingest_error set, or empty clauses):**
```python
{"clauses": {}, "current_node": "risk_score",
 "node_timings": {"risk_score": elapsed}}
```
Note: a run with **no validated findings** (all `DISCARDED`) also returns `clauses: {}` — the loop scores nothing, makes zero LLM calls, and logs an info line (AC-10). This is a normal outcome, not a defensive short-circuit.

---

### Graph Wiring

#### [MODIFY] `backend/app/graph/builder.py`

Register the RiskScore node and replace the temporary `self_rag_validation → END` edge with `self_rag_validation → risk_score → END`:

```python
from app.graph.nodes.risk_score_agent import risk_score_agent

# Inside build_graph():
graph.add_node("risk_score", risk_score_agent)
graph.add_edge("self_rag_validation", "risk_score")   # was END temporarily
graph.add_edge("risk_score", END)                     # → END until feature-008 (Redline)
```

Update the module docstring's "Current scope" note (builder.py:4-9) to include Node 5 and move the "→ END temporarily" comment to the RiskScore edge.

**Constitution §2 note:** RiskScore's outgoing edge is a **plain linear `add_edge`**. It is deliberately **not** an `add_conditional_edges` — the two conditional edges the constitution permits are CRAG's confidence routing (Node 3) and `route_on_risk` (Node 6). `route_on_risk` will *read* the `risk_level` this node writes; RiskScore itself does not branch. The node-name string `"risk_score"` matches the pinned `current_node` value (spec §2) so state-key identity never drifts from the graph node name (constitution §8).

---

### Unit Tests

#### [NEW] `backend/tests/unit/test_risk_scorer.py`

Tests for `score_risk` — mock `ollama.Client.chat`, no running Ollama:

| Test | Verifies |
|------|----------|
| `test_parses_high_medium_low` | `{"risk_level": "high"/"medium"/"low"}` → `RiskLevel.HIGH/MEDIUM/LOW` (parametrized) |
| `test_level_case_and_whitespace_insensitive` | `" HIGH "` → `RiskLevel.HIGH` |
| `test_returns_rationale` | `rationale` string is returned alongside the level |
| `test_timeout_returns_none` | Simulated timeout → `None`, warning logged |
| `test_connection_error_returns_none` | Ollama unreachable → `None` |
| `test_malformed_json_returns_none` | Non-JSON body → `None` |
| `test_missing_risk_level_returns_none` | JSON without `risk_level` → `None` |
| `test_invalid_level_string_returns_none` | `{"risk_level": "critical"}` → `None` (not a RiskLevel) (AC-13) |
| `test_non_string_level_returns_none` | `{"risk_level": 3}` → `None` |
| `test_uses_generative_model_only` | `chat` called with `OLLAMA_MODEL_NAME`; `OLLAMA_EMBED_MODEL_NAME` never referenced (AC-6) |
| `test_prompt_truncated_to_max_chars` | Oversized text+evidence truncated to `prompt_max_chars` before the call (AC-19) |
| `test_empty_evidence_scores_on_text` | `evidence_snippets` `[]`/`None` → uses text-only prompt variant, no crash (AC-20) |
| `test_clause_type_included_in_prompt` | A provided `clause_type` label appears in the prompt; `None` → "unspecified" wording |
| `test_scorer_never_raises` | Any injected exception → `None`, no propagation |
| `test_rationale_returned_untruncated` | Scorer returns full rationale (node, not scorer, applies `RISK_RATIONALE_MAX_CHARS`) |

#### [NEW] `backend/tests/unit/test_risk_score_agent.py`

Tests for the node — mock `score_risk` at the module level (Node 2/4 monkeypatch precedent) so results are deterministic fixtures and call counts are assertable:

| Test | Verifies |
|------|----------|
| `test_validated_findings_scored` | Every `VALIDATED` clause ends with a `risk_level ∈ {LOW,MEDIUM,HIGH}` and non-empty `risk_rationale` (AC-1) |
| `test_discarded_untouched_no_llm` | `DISCARDED` clause: `risk_level`/`risk_rationale` stay absent; **no** `score_risk` call (AC-2) |
| `test_final_status_none_skipped` | `final_status is None` clause skipped, no call (AC-3) |
| `test_level_echoes_judgment` | Mock returns HIGH/MEDIUM/LOW → clause gets that level (parametrized) (AC-4) |
| `test_only_validated_incur_llm_calls` | `score_risk` call count == number of `VALIDATED` clauses (AC-5) |
| `test_uses_generative_not_embedding_model` | Passed model is `OLLAMA_MODEL_NAME` ≠ `OLLAMA_EMBED_MODEL_NAME` (AC-6) |
| `test_ingest_error_returns_empty` | `ingest_error` set → empty update, no calls (AC-8) |
| `test_empty_clauses_returns_empty` | `clauses == {}` → empty update, warning, no calls (AC-9) |
| `test_no_validated_findings_zero_llm` | All-`DISCARDED` doc → empty `clauses` update, zero calls, info log (AC-10) |
| `test_partial_update_only_no_error_count` | Non-outage run → keys exactly `{clauses, current_node, node_timings}`; no `error_count` (AC-11) |
| `test_graceful_llm_failure_failsafe_high` | `score_risk` → None → clause gets default `HIGH`, `[auto]` rationale, no crash, others proceed; `error_count` NOT incremented for a single failure (AC-12) |
| `test_malformed_output_failsafe` | `score_risk` returns None on unparseable output → same fail-safe path (AC-13) |
| `test_circuit_breaker_opens` | After `THRESHOLD` consecutive None results, remaining validated findings get default `HIGH` with **no** further `score_risk` calls; one "circuit opened" warning (AC-14) |
| `test_empty_text_findings_are_circuit_neutral` | A run of only empty-text validated findings applies default to each but **never** opens the circuit and returns **no** `error_count` (AC-14a) |
| `test_circuit_resets_on_success` | An interleaved real score resets the consecutive counter (intermittent single failures never trip it) |
| `test_circuit_open_emits_error_count_once` | Breaker opens → return includes `error_count: 1` exactly once; never-open run has no `error_count` key (AC-15) |
| `test_current_node_pinned` | `current_node == "risk_score"` and same key in `node_timings` (AC-16) |
| `test_rerun_overwrites_risk_fields` | Pre-existing `risk_level`/`risk_rationale` overwritten; reducer preserves text/verdicts (AC-17) |
| `test_rationale_truncated` | Rationale longer than `RISK_RATIONALE_MAX_CHARS` truncated before write (AC-18) |
| `test_empty_evidence_validated_still_scored` | `VALIDATED` finding with `evidence_snippets` `[]`/`None` still scored, no crash (AC-20) |
| `test_empty_text_validated_failsafe` | Whitespace-only text on a `VALIDATED` finding → default level, `[auto]` rationale, **no** `score_risk` call, circuit-neutral (Edge Case 6 + AC-14a) |
| `test_suggested_rewrite_untouched` | Node never sets/modifies `suggested_rewrite` on any clause (AC-21) |
| `test_risk_level_is_valid_enum` | Every assigned `risk_level` is a `RiskLevel` member (serializes to `"low"/"medium"/"high"`) (AC-22) |
| `test_clause_type_enum_or_str_context` | `_clause_type_value` normalizes `ClauseType` enum, `str`, and `None` to the string label passed to `score_risk` |

> **AC-7 coverage note:** AC-7 ("all constants read from `app.config`, never hardcoded") has no dedicated row — it is covered *implicitly*: a hardcoded timeout, threshold, or default level would break `test_circuit_breaker_opens`, `test_graceful_llm_failure_failsafe_high`, and `test_rationale_truncated`, all of which monkeypatch the re-exposed module-level names. Accepted coverage, flagged so it isn't mistaken for a direct assertion (same stance as the Node 4 plan's AC-10 note).

#### [MODIFY] `backend/tests/unit/test_config.py`

| Test | Verifies |
|------|----------|
| `test_risk_score_constants_match_spec` | `RISK_SCORE_TIMEOUT_SECONDS`, `RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD`, `RISK_SCORE_PROMPT_MAX_CHARS`, `RISK_RATIONALE_MAX_CHARS` match spec §6 |
| `test_risk_score_constants_correct_types` | `int` for the numeric constants |
| `test_risk_score_default_level_is_high` | `RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE is RiskLevel.HIGH` (and is a `RiskLevel` member) |
| `test_risk_score_no_max_attempts_constant` | No `RISK_SCORE_MAX_ATTEMPTS` exists (spec §8a R6 — no retry loop) |
| `test_risk_score_uses_generative_model` | The node's generative model is `OLLAMA_MODEL_NAME`, and `OLLAMA_MODEL_NAME != OLLAMA_EMBED_MODEL_NAME` (constitution §8) |

---

### Integration Tests

#### [NEW] `backend/tests/integration/test_risk_score_graph.py`

RiskScore wired into the graph. `score_risk` (and the upstream Self-RAG reflectors / CRAG embed+web) are mocked — no live Ollama. Self-RAG's `final_status` is either produced by the real upstream nodes with their LLM boundaries mocked, or injected as a pre-built `clauses` fixture, depending on the case:

| Test | Verifies |
|------|----------|
| `test_graph_reaches_risk_score_and_ends` | Full path Node1→…→5 reaches END; every `VALIDATED` clause carries a `risk_level` |
| `test_graph_ingest_error_skips_risk_score` | Ingest error short-circuits to END without reaching RiskScore |
| `test_graph_only_validated_scored` | Mixed fixture: `VALIDATED` clauses get a `risk_level`; `DISCARDED` clauses keep `risk_level = None`, all still present in state (AC-2, AC-17) |
| `test_graph_no_validated_findings` | All-`DISCARDED` document → no clause has a `risk_level`; graph ends cleanly with no `error_count` (AC-10) |
| `test_graph_circuit_open_sets_error_count` | Forcing all scores to fail opens the breaker → final state `error_count == 1` and remaining validated findings default to `HIGH` (AC-14, AC-15) |
| `test_graph_checkpointing_after_risk_score` | State is checkpointed after RiskScore completes |

**Note:** a separate *manual* end-to-end test (not in the automated suite) can run with live Ollama (`qwen3:14b`) against a real contract to sanity-check severity quality and tune the prompt / rubric. (Per the Node 4 memory note, live Qwen3 smoke may OOM on the current box — the automated suite must pass fully mocked regardless.)

---

## 3. Dependency & Import Map

```
app/config.py
    └── app.graph.state (RiskLevel)   # NEW — only import in the module; verified acyclic
                                        # (state.py imports only stdlib; package __init__ are empty)

app/graph/nodes/scorers/__init__.py
    └── (package marker — no imports)

app/graph/nodes/scorers/risk_scorer.py
    ├── concurrent.futures, json, logging, typing (stdlib)
    ├── httpx (timeout type), ollama
    ├── app.graph.state (RiskLevel)
    └── app.graph.nodes.validators (format_evidence)   # reuse, dependency-free helper
        # model_name/timeout/limits passed in — no app.config import here

app/graph/nodes/risk_score_agent.py
    ├── time, logging, typing (stdlib)
    ├── app.graph.state (ContractState, ClauseType, ValidationStatus, RiskLevel)
    ├── app.graph.nodes.scorers.risk_scorer (score_risk)
    └── app.config — imported AS A MODULE (`import app.config as _config`) with the
                     RiskScore constants re-exposed as module-level names, read by bare
                     name so tests can monkeypatch them (Node 2/4 precedent).

app/graph/builder.py
    ├── langgraph.graph (StateGraph, END)
    ├── app.graph.state (ContractState)
    ├── app.graph.nodes.ingest_agent (ingest_agent)
    ├── app.graph.nodes.clause_splitter_agent (clause_splitter_agent)
    ├── app.graph.nodes.crag_retrieval_agent (crag_retrieval_agent)
    ├── app.graph.nodes.self_rag_validation_agent (self_rag_validation_agent)
    └── app.graph.nodes.risk_score_agent (risk_score_agent)   # NEW
```

No `numpy` / `faiss` / `duckduckgo_search` — RiskScore is purely generative-LLM, no vectors or retrieval (constitution §8; spec §5.5).

---

## 4. Implementation Order

Following TDD per constitution §7 — tests written and confirmed failing before implementation.

| Step | Action | Files |
|------|--------|-------|
| 1 | Write config tests for the new RiskScore constants (confirm failing) | `tests/unit/test_config.py` |
| 2 | Add the `# ── RiskScore thresholds` block + `RiskLevel` import to config | `app/config.py` |
| 3 | Run config tests (confirm passing) | — |
| 4 | Create the `scorers/` package marker | `app/graph/nodes/scorers/__init__.py` |
| 5 | Write unit tests for `score_risk` (confirm failing) | `tests/unit/test_risk_scorer.py` |
| 6 | Implement `risk_scorer.py` (shared `_run_scoring` + prompt variants + parse) | `app/graph/nodes/scorers/risk_scorer.py` |
| 7 | Run scorer tests (confirm passing) | — |
| 8 | Write unit tests for the node (confirm failing) | `tests/unit/test_risk_score_agent.py` |
| 9 | Implement `risk_score_agent.py` | `app/graph/nodes/risk_score_agent.py` |
| 10 | Run node tests (confirm passing) | — |
| 11 | Update graph builder (add node, rewire self_rag → risk_score → END) | `app/graph/builder.py` |
| 12 | Write and run integration tests (mocked scoring) | `tests/integration/test_risk_score_graph.py` |
| 13 | Full test suite pass (all existing + new) | all tests |

> **Note on Step 4**: the `scorers/__init__.py` is a package marker with no logic (unlike `validators/__init__.py`, which hosts `format_evidence`) — RiskScore reuses the validators' helper rather than defining its own, so there is nothing to test here.

---

## 5. Design Decisions & Rationale

### Scorer returns `Optional[Tuple[RiskLevel, str]]`, node interprets `None` as failure
A two-valued success (`(level, rationale)`) plus `None` for "could not run" is the smallest contract that lets the node distinguish a real score from an un-runnable one, exactly as the reflectors return `Optional[bool]` and `embed_query` returns `Optional[np.ndarray]`. It keeps the fail-safe policy (spec §8a R1) and the circuit-breaker bookkeeping entirely in the node, where all state lives — the scorer stays pure, stateless, and independently testable with the LLM mocked.

### Single LLM call, no retry (spec §8a R5/R6)
Constitution §2 assigns Low/Medium/High per validated finding and mandates retries only for Self-RAG's ISSUP check. So RiskScore makes exactly one call returning level + rationale together; an unparseable/failed call takes the fail-safe default rather than re-sampling. This keeps latency bounded (constitution §9) and the node simple. A self-consistency re-sample was rejected as trading latency for marginal determinism (spec §8b/R6). Because only *validated* findings are scored — typically a small fraction of all clauses — aggregate LLM load is materially lighter than Self-RAG's.

### Fail-safe = HIGH, with a circuit-open health signal (spec §8a R1)
For a risk detector, a *missed* risk is costlier than an over-flagged one, so a finding that already passed Self-RAG's gate but couldn't be scored surfaces at `HIGH` rather than being downgraded. But a *wholesale* outage that defaults everything to HIGH must not masquerade as a genuinely high-risk document — so the circuit breaker opening emits `error_count: 1` **once**. A single flaky call stays silent (matching Nodes 2-4); only the breaker speaks. And because a fail-safe HIGH carries an `[auto]`-prefixed rationale, downstream nodes and the report can tell it apart from a model-assigned HIGH.

### Circuit breaker as a runtime guarantee, with zero-LLM paths exempt (spec §4.5, AC-14a)
Without it, an unreachable Ollama makes every validated finding pay `RISK_SCORE_TIMEOUT_SECONDS` — pathological over a contract with many findings. After `RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD` **consecutive** failures the node stops calling the LLM and applies the fail-safe default to the rest. Crucially, only paths that *issued* an LLM call move the consecutive counter; the empty-text skip and the post-open bulk default are circuit-neutral, so a document full of empty-text findings can't spuriously trip the breaker or emit a false `error_count`. The counter resets on any success. Per-run only; not persisted. Directly mirrors Self-RAG's breaker and its Branch-B exemption.

### `VALIDATED`-only gate, discarded clauses left inert (spec §1, AC-2/3)
RiskScore scores exactly the findings Self-RAG kept. Discarded clauses stay in state untouched (the node never returns them, so the reducer preserves them) — consistent with Self-RAG not deleting clause IDs and downstream nodes filtering on status. This also means the "no risk → SkipRedline (clean)" branch at Node 6 corresponds to non-validated clauses, not to anything RiskScore relabels (the §8b tension, recorded for `008`).

### `RiskLevel` stored as the enum in config (spec §6)
`RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE` is the `RiskLevel` enum, not a string, giving type safety and letting the node use it directly (and satisfy AC-22 without conversion). This requires the module's single import (`from app.graph.state import RiskLevel`), which is verified acyclic. (Contrast `SELF_RAG_HIGH_RISK_CLAUSE_TYPES`, which stores plain strings — but that is for `frozenset` membership against a possibly-enum-or-string `clause_type`, a different concern; here a single canonical enum value is cleaner.)

### Reuse `format_evidence`, separate `scorers/` package
`risk_scorer.py` is independently testable (LLM mocked, no network, no vectors) and independently replaceable — same rationale as the `validators/` and `retrievers/` splits. It reuses the validators' `format_evidence` rather than duplicating the 001-evidence-shape renderer, keeping that assumption in one place.

### Logging strategy (spec §9)
Named logger `contractsentinel.risk_score`. `ContractState` carries only aggregate `node_timings["risk_score"]`; all eval metrics (risk-level distribution, level-by-`clause_type`, scoring-failure rate, circuit events, rationale length, per-finding latency) are emitted as `logger.info(..., extra={...})` structured records for the eval harness (`specs/002-tech-stack.md` §3i) — never added as extra per-clause state fields. Mirrors `self_rag_validation_agent.py` and `crag_retrieval_agent.py`.

---

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Ollama / `qwen3:14b` not running at pipeline time | Every score fails | Scorer uses `ollama.Client(timeout=…)` so each call aborts; circuit breaker collapses remaining cost to a constant and fail-safes the rest; `error_count:1` surfaces the degraded run |
| Hung Ollama socket outliving the executor timeout | Node blocks past timeout, defeating the breaker | `Client(timeout=…)` aborts the underlying call (primary bound); `future.result(timeout=…)` is the backstop — same pattern as `reflectors.py` / `llm_refiner.py` |
| Fail-safe HIGH inflates the level distribution when Ollama is flaky | Report skews high; Redline over-triggered | `[auto]`-prefixed rationale distinguishes fail-safe from model HIGH; breaker emits `error_count:1`; the scoring-failure-rate metric (spec §9.3) cross-checks metric §9.1 so an artificial skew is visible; default level is a tunable constant |
| LLM returns an out-of-enum level (e.g. `"critical"`) or prose | Score unparseable | `format="json"` + strict `RiskLevel(...)` parse; any invalid/missing value → `None` → fail-safe (spec §4.4); covered by `test_invalid_level_string_returns_none` |
| Empty-text validated findings spuriously open the circuit | False `error_count:1`, premature bulk-default | Empty-text and post-open paths are **circuit-neutral** — never call `_account` (AC-14a); `test_empty_text_findings_are_circuit_neutral` locks this |
| Validated finding reaches Node 6 without a `risk_level` | Ambiguous record at `route_on_risk` | Every VALIDATED finding is scored or fail-safed; the empty-text and circuit-open paths still assign a level (spec §7.3, AC-1) |
| `clause_type` stored as enum vs string drift | Prompt context malformed | `_clause_type_value` normalizes enum/str/None; `test_clause_type_enum_or_str_context` guards it |
| Unbounded rationale bloats checkpointed state | State size growth | Node truncates to `RISK_RATIONALE_MAX_CHARS` before writing (AC-18); `test_rationale_truncated` locks it |
| `config.py` importing `RiskLevel` introduces a cycle | ImportError at startup | Verified acyclic: `state.py` imports only stdlib, package `__init__` are empty; the config test suite importing `app.config` exercises this on every run |
| `error_count` increment misread as a hard pipeline error downstream | Spurious abort/retry | It is a single health-signal increment via `operator.add`, not a control flag (spec §2, mirrors Self-RAG); capped at one per run |

---

## 7. Out of Scope for This Plan

- **Nodes 6–7**: not wired or implemented. `builder.py` routes `risk_score` → END until feature-008 (Redline).
- **The `route_on_risk` conditional edge**: Node 6's edge (`specs/008-*`); RiskScore only *writes* `risk_level` (spec §5.2). The level→Redline routing threshold (incl. whether `LOW → SkipRedline`) is `008`'s decision — recorded as the §8b tension, not resolved here.
- **Drafting safer clause language (redlining)**: RedlineAgent (Node 6); RiskScore produces no `suggested_rewrite` (spec §5.3).
- **`evidence_trail` compilation**: ReportAgent (Node 7); RiskScore writes only `risk_level` / `risk_rationale` (spec §5.4).
- **Deciding validated vs discarded**: Self-RAG (Node 4); RiskScore consumes `final_status` as a gate (spec §5.1).
- **Gathering / scoring retrieval evidence, embeddings, web search**: CRAG (Node 3); RiskScore consumes `evidence_snippets` as given context (spec §5.5).
- **Document-level roll-up / overall-contract risk score**: a ReportAgent (Node 7) concern and a `001`-schema change; not added here (spec §5.6 / §8a R4).
- **Human-in-the-loop override of an assigned level**: no review/override UI (spec §5.7; PERMANENTLY CUT).
- **Bounded-parallelism over findings**: sequential for Phase 1; a concurrency knob is deferred (spec §5.8).
- **Retry / self-consistency re-sample of the score**: rejected (spec §8a R6) — single call, fail-safe on failure.
- **Prompt-rubric finalization**: pinned provisionally (Low/Medium/High rubric wording); tunable without control-flow change.
- **API endpoints, DB storage, MCP delivery, privacy/security**: per Phase 2 deferral / other specs.
