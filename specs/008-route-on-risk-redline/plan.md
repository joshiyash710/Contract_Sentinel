# route_on_risk + Redline Technical Plan

## Git Branch

`feature/008-route-on-risk-redline` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

This plan details how to implement **Node 6** as specified in `specs/008-route-on-risk-redline/spec.md`. Node 6 is a single architectural unit made of **three graph elements**, all owned by this feature:

1. **`route_on_risk`** — a genuine graph-level `add_conditional_edges` on the `risk_score` node. It reads the whole `ContractState` and returns `"redline"` if the document has **any** redline-eligible clause, else `"skip_redline"`. This is the pipeline's **first and only** domain conditional edge realized at the graph level (CRAG's confidence routing stays internal per-clause branching — spec §7.1).
2. **RedlineAgent** (`redline` node) — the "risk found" branch. For each redline-eligible clause it makes **one** generative LLM call that returns a safer rewrite, and writes it to `suggested_rewrite`. Structurally mirrors `risk_score_agent.py`.
3. **SkipRedline** (`skip_redline` node) — the "no risk" branch. A lightweight passthrough that records `current_node` + `node_timings` and writes **no** clause fields.

Both branches re-converge downstream: `redline` and `skip_redline` each get a plain `add_edge` to the same successor — `END` until feature-009 (ReportAgent, Node 7) exists, at which point both point to `report` (spec §7.5).

**Redline-eligible** is the single predicate shared by the edge and the node (spec §7.2): `final_status == ValidationStatus.VALIDATED and risk_level in REDLINE_RISK_THRESHOLD`. It is defined **once** as a module-level helper reading the **one** config constant, so the edge and the node can never disagree (spec AC-32, Edge Case 12).

The node writes only `clauses` (via the `merge_nested_clause_dicts` reducer) plus `current_node` and `node_timings`, per the partial-update rule. The **one** exception is the circuit-open health signal: a single `error_count: 1` when the LLM backend is declared down for the run (spec §2.2 / §7.6). All configurable thresholds live in `app/config.py` per constitution §3. The single LLM call uses the **generative** model `OLLAMA_MODEL_NAME` (Qwen3 via Ollama) — the same model Nodes 2, 4, 5 use. The node makes **no vector calls** and never references `OLLAMA_EMBED_MODEL_NAME` (constitution §8; retrieval and validation are already done).

**Resolved design decisions carried from the spec (§8a R1–R5):**
- **R1 — `REDLINE_RISK_THRESHOLD` = `{LOW, MEDIUM, HIGH}` (Option A).** Every validated finding is redlined; SkipRedline fires only for documents with zero validated findings. Kept permissive on purpose so the §9 metrics can inform a later tightening to `{MEDIUM, HIGH}` — a one-line config change. Accepted consequence: `route_on_risk`'s "no risk" branch is driven by Self-RAG discards, not by risk level.
- **R2 — `suggested_rewrite` is three-state, disambiguated by `risk_level`:** key **absent** = never attempted (ineligible / SkipRedline); **`None`** = attempted but no rewrite produced; **non-empty str** = successful rewrite. "Clean" is `risk_level is None`, never `suggested_rewrite is None`.
- **R3 — On failure / circuit-open the node emits an explicit `suggested_rewrite: None`;** it omits the key only for clauses it never attempted. Emitting `None` clears a stale re-run value and is correct under the partial-update rule (the field genuinely changed to a definitive `None` outcome).
- **R4 — "Clause marked clean" stays emergent;** no new state field (no `001` schema change).
- **R5 — Phase 1 always attempts a rewrite for an eligible clause;** no distinct "no change needed" outcome. `None` means exactly "no rewrite available." A no-op/echo eval-watch metric is logged (spec §9.6) but not acted on.

**Fail-safe is the deliberate inverse of RiskScore's (spec §7.3).** RiskScore fails *safe* toward `HIGH` (more visibility). Redline's artifact is **substantive legal text**, so fabricating a rewrite on failure would be actively harmful — the fail-safe is **no rewrite** (`suggested_rewrite: None`). The finding is not lost: it remains fully surfaced by its unchanged `risk_level` / `risk_rationale`; only the *optional* remediation text is absent.

---

## 2. Files to Create / Modify

### Shared Config Module

#### [MODIFY] `backend/app/config.py`

Add a new `# ── Redline thresholds` block (no Redline constant exists yet — pure addition, no rename). `config.py` **already imports `RiskLevel`** (`config.py:11`, added by feature-007), so `REDLINE_RISK_THRESHOLD` needs **no new import** — the acyclic-import concern is already resolved.

```python
# ── Redline thresholds ─────────────────────────────────────────────────────────
# Source: specs/008-route-on-risk-redline/spec.md §6

REDLINE_RISK_THRESHOLD: frozenset = frozenset(
    {RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH}
)
# The set of risk levels that route a VALIDATED finding to RedlineAgent (vs
# SkipRedline). Read by BOTH route_on_risk (the edge) and RedlineAgent (the node)
# via one shared predicate so eligibility has a single source of truth (spec §7.2).
# RESOLVED to Option A — all three levels (spec §8a R1): every validated finding is
# redlined; SkipRedline fires only for documents with zero validated findings. Kept
# permissive so the spec §9 / RiskScore §9.6 redline-routing metrics can justify a
# later tightening to {MEDIUM, HIGH}. Stored as RiskLevel members; membership is
# robust to a str value too because RiskLevel is a str-Enum (RiskLevel.LOW == "low",
# hash-equal). Tune against real sample contracts.

REDLINE_TIMEOUT_SECONDS: int = 120
# Wall-clock timeout for a single Redline LLM call (one clause rewrite) via Ollama.
# Mirrors RISK_SCORE_TIMEOUT_SECONDS; headroom for local Qwen3 per constitution §9.
# On timeout the clause takes the fail-safe: the node emits suggested_rewrite: None.

REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD: int = 5
# Number of CONSECUTIVE LLM failures after which the node declares the generative
# backend down for the rest of the run and emits suggested_rewrite: None for all
# remaining eligible clauses (skipping per-clause timeouts). Resets on any success.
# Opening emits the error_count health signal once (spec §7.6, AC-20/23). Mirrors
# RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD.

REDLINE_PROMPT_MAX_CHARS: int = 6000
# Clause text + risk_rationale + concatenated evidence snippets are truncated to this
# combined length before the drafting LLM call, to bound prompt size (spec §4.8).
# Mirrors RISK_SCORE_PROMPT_MAX_CHARS.

REDLINE_PROMPT_RATIONALE_RESERVE_CHARS: int = 1000
# Portion of REDLINE_PROMPT_MAX_CHARS reserved for risk_rationale BEFORE the clause
# text is truncated, so a clause longer than the prompt budget cannot starve the
# rationale (the remediation target — the model needs it to know WHY to rewrite) to a
# zero budget (spec §4.8; plan §2 drafter notes). Matches RISK_RATIONALE_MAX_CHARS
# (the max a Node-5 rationale can be), so a present rationale is never dropped
# (budget 6000 >> 1000). A budget-partitioning threshold, so it lives in config per
# constitution §3 (not inline). Tune against real sample contracts.

REDLINE_REWRITE_MAX_CHARS: int = 4000
# Generated suggested_rewrite is truncated to this length before being written to
# ContractState, to bound persisted state size (spec §4.9). Larger than
# RISK_RATIONALE_MAX_CHARS (1000) because a rewritten clause is full replacement
# language, not a one-line explanation.
```

The node reuses the existing `OLLAMA_MODEL_NAME` — no new model constant. There is intentionally **no** `REDLINE_MAX_ATTEMPTS` (spec §6 / §8a — no retry loop; constitution §2 scopes retries to Self-RAG only).

---

### Drafters Package

New package `backend/app/graph/nodes/drafters/`, following the same structure precedent as `scorers/` (Node 5), `validators/` (Node 4), and `retrievers/` (Node 3): a package `__init__.py` plus one module for the rewrite generation, independently testable with the LLM mocked at the boundary.

#### [NEW] `backend/app/graph/nodes/drafters/__init__.py`

A package marker with a module docstring. It does **not** redefine an evidence formatter: `redline_drafter.py` reuses the existing, dependency-free `format_evidence` from the validators package (as `risk_scorer.py` does — `risk_scorer.py:19`). Nothing to export here.

#### [NEW] `backend/app/graph/nodes/drafters/redline_drafter.py`

The single rewrite generation. Returns `Optional[str]` and **never raises** — the exception boundary is load-bearing (spec §7.3). Contract for the caller (the node):

- non-empty `str` → a real rewrite from the model
- `None` → the rewrite **could not be produced** (Ollama unreachable, timeout, non-JSON, missing field, or **empty/whitespace output** — spec AC-19) → the node emits `suggested_rewrite: None` and counts it toward the circuit breaker (spec §4.4 / AC-18/19).

```python
from typing import Any, Dict, List, Optional
from app.graph.nodes.validators import format_evidence   # reuse — see note

def draft_rewrite(
    clause_text: str,
    risk_rationale: Optional[str],
    evidence_snippets: Optional[List[Dict[str, Any]]],
    clause_type: Optional[str],
    timeout_seconds: int,
    model_name: str,
    prompt_max_chars: int,
    rationale_reserve: int,
) -> Optional[str]:
    """Single generative call producing safer replacement language for a
    redline-eligible clause. risk_rationale (the Node-5 explanation of WHY the clause
    is risky) is the remediation target fed to the prompt. evidence_snippets (001
    shape) is drafting context when present; may be []/None (Self-RAG rescue path) →
    draft on clause text + risk_rationale + clause_type alone. clause_type is a
    normalized string label (or None). Returns the rewrite string (untruncated — the
    node applies REDLINE_REWRITE_MAX_CHARS) or None on any failure / empty output.
    Never raises."""
```

Implementation notes (mirror `risk_scorer.py` structurally — it is the closest template):
- **Shared invocation core.** A private `_run_drafting(prompt, timeout_seconds, model_name) -> Optional[str]` performs the Ollama call and parses the result, via `_call_ollama` + `_parse_rewrite`. Same split as `risk_scorer.py:118-152`.
- **Ollama call + timeout — copy the Node 5 pattern exactly (spec §4.4, constitution §9).** `ollama.Client(timeout=timeout_seconds).chat(model=model_name, messages=[...], format="json", options={"num_predict": 1536})` **inside** a `concurrent.futures.ThreadPoolExecutor(max_workers=1)` with `future.result(timeout=timeout_seconds)`. `Client(timeout=…)` is the **primary** bound (aborts the underlying `httpx` call so a hung socket cannot outlive the timeout and defeat the circuit breaker); the executor `future.result(timeout=…)` is the backstop. Catch `concurrent.futures.TimeoutError`, `httpx.TimeoutException`, and any `Exception` → `None` with a rate-limited warning.
  - **`num_predict` must comfortably exceed the token-equivalent of `REDLINE_REWRITE_MAX_CHARS` + JSON scaffolding.** A rewrite is full clause language, not a one-line rationale. `REDLINE_REWRITE_MAX_CHARS = 4000` chars ≈ ~1000 tokens; `num_predict = 1536` gives ~50% headroom (~6000 chars) so a legitimately long rewrite is never truncated mid-JSON. **Invariant to preserve when tuning either value:** `num_predict` stays well above `REDLINE_REWRITE_MAX_CHARS`-in-tokens, so a valid long rewrite is never cut off into invalid JSON and misread as a failed call (which would waste a fail-safe `None` and tick the breaker). Kept inline like `risk_scorer.py:149`'s `384`; promote to a named constant only if it needs per-deployment tuning.
- **JSON rewrite contract.** Prompt the model to return `{"suggested_rewrite": "<rewritten clause text>"}`. Parse in `_parse_rewrite`:
  - `suggested_rewrite` → coerced to `str`, `.strip()`. **Empty/whitespace-only → `None`** (spec AC-19: empty output is a drafting failure, not a valid "" rewrite). Reject non-`str` (`None`, number) → `None`.
  - Non-JSON body, missing `suggested_rewrite` → `None`. Never raises.
  - Returned **untruncated** (the node applies `REDLINE_REWRITE_MAX_CHARS` before writing to state — single owner of state-bound size, mirroring the rationale handling in `risk_scorer.py`).
- **Prompt truncation.** Budget the combined prompt inputs to `prompt_max_chars` (spec §4.8, AC-22). **Unlike `risk_scorer.py`, do NOT truncate the clause first with the full budget** — Redline's `risk_rationale` is the remediation target (it tells the model *why* to rewrite), so a clause longer than `prompt_max_chars` must not starve it to a zero budget (which would make the model rewrite a risky clause without knowing what is risky about it). **Reserve a rationale floor before truncating the clause,** then give evidence the remainder:
  ```
  rationale_full = (risk_rationale or "").strip()
  # rationale_reserve (config REDLINE_PROMPT_RATIONALE_RESERVE_CHARS = 1000) matches
  # RISK_RATIONALE_MAX_CHARS, the maximum a Node-5 rationale can be, so a present
  # rationale is never dropped (budget 6000 >> 1000).
  reserve       = min(len(rationale_full), rationale_reserve)
  clause_budget = max(0, prompt_max_chars - reserve)
  clause_trunc  = clause_text[:clause_budget]
  remaining     = max(0, prompt_max_chars - len(clause_trunc))
  rationale_trunc = rationale_full[:remaining]
  remaining     = max(0, remaining - len(rationale_trunc))
  evidence_str  = format_evidence(evidence_snippets, remaining)
  ```
  `rationale_reserve` is passed in (config `REDLINE_PROMPT_RATIONALE_RESERVE_CHARS`), not inline — it partitions the config-backed `prompt_max_chars`, so it belongs in config per constitution §3. Log truncation at debug (same style as `risk_scorer.py:86-100`).
- **Prompt content.** One template with an evidence-present and an evidence-absent variant (mirroring `_SCORING_WITH_EVIDENCE_PROMPT` / `_SCORING_TEXT_ONLY_PROMPT`). Both instruct: *rewrite the clause to neutralize the risk described in the rationale while preserving the clause's legitimate commercial intent; return only the replacement clause text.* `risk_rationale` and `clause_type` are inserted as context ("This clause was flagged as risky because: {rationale}"; "categorized as: {clause_type_or_unspecified}"). Exact wording is tunable later without changing control flow.
- **Reuse of `format_evidence` (import note).** Import from `app.graph.nodes.validators` rather than redefining — the same deliberate single cross-node-package reuse `risk_scorer.py` makes (`risk_scorer.py:19`), keeping the 001-evidence-shape renderer in one place.

---

### Redline Node + Routing Edge + Skip Node

#### [NEW] `backend/app/graph/nodes/redline_agent.py`

The module that touches `ContractState` for Node 6. It owns **all three** graph elements plus the shared eligibility predicate, so the single-source-of-truth guarantee (spec §7.2) is enforced by construction — the edge and the node call the *same* function.

```python
import app.config as _config  # module import so tests can monkeypatch (Node 2/4/5 precedent)

logger = logging.getLogger("contractsentinel.redline")

# Re-exposed module-level names for monkeypatching (mirrors risk_score_agent.py:42-49):
OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME
REDLINE_RISK_THRESHOLD = _config.REDLINE_RISK_THRESHOLD
REDLINE_TIMEOUT_SECONDS = _config.REDLINE_TIMEOUT_SECONDS
REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD = _config.REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD
REDLINE_PROMPT_MAX_CHARS = _config.REDLINE_PROMPT_MAX_CHARS
REDLINE_PROMPT_RATIONALE_RESERVE_CHARS = _config.REDLINE_PROMPT_RATIONALE_RESERVE_CHARS
REDLINE_REWRITE_MAX_CHARS = _config.REDLINE_REWRITE_MAX_CHARS
```

**Shared eligibility predicate — the single source of truth (spec §7.2):**
```python
def is_redline_eligible(record: dict) -> bool:
    """True iff this clause record should be redlined: it validated AND its risk
    level is in the configured threshold. Read by BOTH route_on_risk and
    redline_agent so they can never disagree (spec AC-32). Reads the module-level
    REDLINE_RISK_THRESHOLD (monkeypatchable). Robust to risk_level being a RiskLevel
    enum or its str value (RiskLevel is a str-Enum → hash-equal); None → False."""
    if record.get("final_status") != ValidationStatus.VALIDATED:
        return False
    return record.get("risk_level") in REDLINE_RISK_THRESHOLD
```

**`route_on_risk` — the conditional edge (spec §2.1, AC-1..7):**
```python
def route_on_risk(state: ContractState) -> str:
    """Graph-level conditional edge after risk_score. Returns "redline" if the
    document has >=1 redline-eligible clause, else "skip_redline". Pure — never
    mutates state (AC-7)."""
    if state.get("ingest_error") is not None:
        return "skip_redline"                      # AC-4
    clauses = state.get("clauses", {})
    if any(is_redline_eligible(rec) for rec in clauses.values()):
        return "redline"                           # AC-1
    return "skip_redline"                          # AC-2/3
```

**`redline_agent` — the node (spec §2.2). Internal flow (mirrors `risk_score_agent.py`):**
```
1.  current_node = "redline"; record start_time.
2.  Defensive: if state.get("ingest_error") is not None → return empty update
    (clauses={}, current_node, node_timings). No LLM calls. (AC-14)
3.  clauses = state.get("clauses", {}).
    If not clauses → log warning, return empty update. No LLM calls. (AC-15)
4.  cb = {"consecutive_failures": 0, "open": False, "tripped": False}   # single mutable holder
5.  clause_updates = {}.
    counts = {"eligible": 0, "rewritten": 0, "failed": 0, "noop": 0,
              "empty_text": 0, "bulk_skipped": 0}     # the SOURCE for spec §9 metrics;
                                                       # mirrors Node 5's level_counts
                                                       # (risk_score_agent.py:96)
6.  For each clause_id, record in document order (by position):
      a. if not is_redline_eligible(record):
             continue        # OMIT the key — never attempted (AC-9/10). Ineligible/
                             # discarded/below-threshold clauses left untouched.
         counts["eligible"] += 1     # every clause that passes the gate is "eligible"
      b. text = (record.get("text") or "").strip()
         if not text:        # Edge Case 6 — eligible finding with empty text (defensive)
             clause_updates[clause_id] = {"suggested_rewrite": None}   # emit explicit None (R3)
             counts["empty_text"] += 1
             log warning; continue        # CIRCUIT-NEUTRAL: no _account call (AC-20a)
      c. if cb["open"]:       # backend already declared down this run
             clause_updates[clause_id] = {"suggested_rewrite": None}   # bulk skip (AC-20)
             counts["bulk_skipped"] += 1
             continue                      # CIRCUIT-NEUTRAL: no _account, no LLM (AC-20a)
      d. rationale = record.get("risk_rationale")
         evidence  = record.get("evidence_snippets")     # may be []/None (rescue path) (AC-26)
         ct_label  = _clause_type_value(record.get("clause_type"))
         result = draft_rewrite(text, rationale, evidence, ct_label,
                                REDLINE_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME,
                                REDLINE_PROMPT_MAX_CHARS,
                                REDLINE_PROMPT_RATIONALE_RESERVE_CHARS)  # 1 LLM call
         _account(result, cb)              # None increments counter; a real rewrite resets it
         if result is None:
             clause_updates[clause_id] = {"suggested_rewrite": None}   # failure (AC-18/19)
             counts["failed"] += 1
             rewrite_len, is_noop = 0, False
             log warning
         else:
             rewrite = result[:REDLINE_REWRITE_MAX_CHARS]              # truncate (AC-21)
             if len(result) > REDLINE_REWRITE_MAX_CHARS: log debug
             clause_updates[clause_id] = {"suggested_rewrite": rewrite}
             counts["rewritten"] += 1
             rewrite_len = len(rewrite)
             is_noop = (rewrite.strip() == text.strip())     # spec §9 metric 6 (echo/no-op)
             if is_noop: counts["noop"] += 1
      e. Per-clause structured log — reached ONLY via 6d (6a/6b/6c continue first).
         DO NOT log the rewrite text (up to 4000 chars). Log only: clause_id,
         risk_level (the finding's level `.value` — feeds spec §9 metric 4, the
         level→route breakdown that pairs with RiskScore §9.6), rewrite_len,
         success=(result is not None), is_noop, circuit_open=cb["open"]. Mirrors Node 5
         logging .value + is_failsafe rather than prose (risk_score_agent.py:168-177).
         (spec §9)
7.  elapsed = time.monotonic() - start_time
8.  Aggregate metrics log (spec §9) via logger.info("RedlineAgent completed",
    extra={**counts, "circuit_opened": cb["tripped"], "elapsed_seconds": round(elapsed,4)}).
    Fires UNCONDITIONALLY — including clause_updates == {} — so a document whose eligible
    clauses were all skipped (AC-16), or a defensively-reached run with no eligible
    clauses, still emits the info line. Downstream the harness derives: redline rate =
    rewritten / eligible; fail-safe-None rate = (failed + empty_text + bulk_skipped) /
    eligible (spec §9 metric 3 covers LLM failure AND empty output AND empty text — all
    three fail-safe-None components are logged separately); no-op rate = noop / rewritten
    (spec §9 metrics 2 / 3 / 6).
9.  out = {"clauses": clause_updates, "current_node": current_node,
           "node_timings": {current_node: elapsed}}
    if cb["tripped"]:  out["error_count"] = 1                # health signal (spec §7.6)
    return out
```

**`skip_redline` — the passthrough node (spec §2.3, AC-28/29):**
```python
def skip_redline(state: ContractState) -> dict:
    """LangGraph "no risk" branch. Records that no redlining was needed; writes NO
    clause fields ("clause marked clean" is emergent — spec §7.4). No LLM calls."""
    start_time = time.monotonic()
    logger.info("SkipRedline: no redline-eligible findings for document_id=%s",
                state.get("document_id", "unknown"))
    return {"current_node": "skip_redline",
            "node_timings": {"skip_redline": time.monotonic() - start_time}}
```

**`_account(result, cb)` — circuit-breaker bookkeeping (spec §4.5 / AC-20/20a):** identical shape to `risk_score_agent.py:219-243`. `result is None` → increment `consecutive_failures`; on reaching `REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD` (and not already open) set `open=True`, `tripped=True`, log one "circuit opened" warning. A real (non-`None`) rewrite resets the counter. **Circuit-neutrality (spec AC-20a — do not skip):** `_account` is called **only** from the drafting path (step 6d). The empty-text skip (6b) and the post-open bulk skip (6c) reach `suggested_rewrite: None` **without** an LLM call and therefore **must not** call `_account` — so a document full of empty-text eligible findings can't spuriously open the breaker or emit a false `error_count: 1`. Mirrors RiskScore's zero-LLM exemption (`risk_score_agent.py` `_account` note).

**Circuit-state holder (implementation note — do not skip; per CLAUDE.md the implementer must not infer this):** `cb` is a **single mutable dict** threaded through `_account`, NOT three bare `int`/`bool` locals. Rebinding an outer `int`/`bool` from a nested helper needs `nonlocal`; omit it and Python raises `UnboundLocalError` or silently shadows, so the breaker never opens. Mutating a dict's contents (`cb["open"] = True`) needs no `nonlocal`. Identical to the Node 4/5 holder.

**Helper — `_clause_type_value(raw) -> Optional[str]`:** identical to Node 4/5's (`risk_score_agent.py:246-256`) — normalizes `ClauseType` enum / `str` / `None` to the string label passed to `draft_rewrite`.

**Key invariants (make these explicit so they are testable):**
- **Eligible + attempted clauses always get the `suggested_rewrite` key** — a non-empty string on success, an explicit `None` on any failure/skip (spec §2.2 states 2/3). The reducer therefore clears any stale re-run value (AC-25 / R3).
- **Ineligible / below-threshold / discarded clauses are never in the return** — the key stays absent (state "key absent" per §2.2), no LLM call (AC-9/10).
- **`risk_level`, `risk_rationale`, and all Self-RAG/CRAG/Ingest fields are never modified** (AC-27) — the node writes only `suggested_rewrite`.
- **`error_count` increments at most once per run** — only when the breaker opens (AC-23).
- **Only LLM-issuing failures move the consecutive counter** — zero-LLM skip paths are circuit-neutral (AC-20a).

**Return shape (success):**
```python
{"clauses": clause_updates, "current_node": "redline",
 "node_timings": {"redline": elapsed}}
# + "error_count": 1  IFF the circuit opened during the run
```
**Return shape (defensive — ingest_error set, or empty clauses):**
```python
{"clauses": {}, "current_node": "redline", "node_timings": {"redline": elapsed}}
```

---

### Graph Wiring

#### [MODIFY] `backend/app/graph/builder.py`

Register the two new nodes and **replace** the temporary `risk_score → END` edge (`builder.py:103`) with the `route_on_risk` conditional edge (spec §7.5, AC-30/31):

```python
from app.graph.nodes.redline_agent import route_on_risk, redline_agent, skip_redline

# Inside build_graph(), replacing `graph.add_edge("risk_score", END)`:

# ── Node 6: route_on_risk (conditional edge) → RedlineAgent / SkipRedline ──────
# Constitution §2: this is the SECOND of the two permitted domain conditional edges
# (the first is CRAG's confidence routing, Node 3, realized as internal per-clause
# branching). Unlike CRAG, route_on_risk is a DOCUMENT-LEVEL decision that routes the
# whole ContractState to one successor, so it IS a genuine graph-level
# add_conditional_edges (spec §7.1). RedlineAgent does per-clause filtering internally
# via the same is_redline_eligible predicate route_on_risk uses (spec §7.2).
graph.add_node("redline", redline_agent)
graph.add_node("skip_redline", skip_redline)
graph.add_conditional_edges(
    "risk_score",
    route_on_risk,
    {"redline": "redline", "skip_redline": "skip_redline"},
)
graph.add_edge("redline", END)        # → "report" once feature-009 (Node 7) exists
graph.add_edge("skip_redline", END)   # → "report" once feature-009 (Node 7) exists
```

Update the module docstring's "Current scope" note (`builder.py:4-10`) to include Node 6 and move the "→ END temporarily" placeholder to the two Node-6 branches. The node-name strings `"redline"` / `"skip_redline"` match the pinned `current_node` values (spec §2.2/§2.3) so state-key identity never drifts from the graph node name (constitution §8).

**Note on the ingest error-guard edge:** `route_after_ingest` (`builder.py:44`) remains a non-domain error guard, not one of the two domain conditional edges — its own comment already says so. After this change the graph has exactly: one non-domain conditional edge (ingest guard), CRAG's internal per-clause routing (Node 3), and one domain graph-level conditional edge (`route_on_risk`, Node 6) — satisfying spec AC-32.

---

### Unit Tests

#### [NEW] `backend/tests/unit/test_redline_drafter.py`

Tests for `draft_rewrite` — mock `ollama.Client.chat`, no running Ollama:

| Test | Verifies |
|------|----------|
| `test_returns_rewrite_string` | `{"suggested_rewrite": "safer text"}` → `"safer text"` |
| `test_timeout_returns_none` | Simulated timeout → `None`, warning logged |
| `test_connection_error_returns_none` | Ollama unreachable → `None` |
| `test_malformed_json_returns_none` | Non-JSON body → `None` |
| `test_missing_field_returns_none` | JSON without `suggested_rewrite` → `None` |
| `test_empty_rewrite_returns_none` | `{"suggested_rewrite": "   "}` → `None` (empty output = failure, AC-19) |
| `test_non_string_rewrite_returns_none` | `{"suggested_rewrite": 5}` / `null` → `None` |
| `test_uses_generative_model_only` | `chat` called with `OLLAMA_MODEL_NAME`; `OLLAMA_EMBED_MODEL_NAME` never referenced (AC-12) |
| `test_prompt_truncated_to_max_chars` | Oversized clause+rationale+evidence truncated to `prompt_max_chars` before the call (AC-22) |
| `test_long_clause_preserves_rationale` | A clause **longer than** `prompt_max_chars` still includes the (reserved) `risk_rationale` in the prompt — the rationale floor is not starved to zero. Locks the §2 reserve logic (the one piece of new logic vs. Node 5) under TDD (constitution §7) |
| `test_empty_evidence_drafts_on_text` | `evidence_snippets` `[]`/`None` → text-only prompt variant, no crash (AC-26) |
| `test_rationale_included_in_prompt` | The provided `risk_rationale` appears in the prompt |
| `test_clause_type_included_in_prompt` | A provided `clause_type` label appears; `None` → "unspecified" wording |
| `test_drafter_never_raises` | Any injected exception → `None`, no propagation |
| `test_rewrite_returned_untruncated` | Drafter returns the full rewrite (node, not drafter, applies `REDLINE_REWRITE_MAX_CHARS`) |

#### [NEW] `backend/tests/unit/test_redline_agent.py`

Tests for the three graph elements — mock `draft_rewrite` at the module level (`app.graph.nodes.redline_agent.draft_rewrite`, Node 2/4/5 monkeypatch precedent) so results are deterministic and call counts are assertable. `REDLINE_RISK_THRESHOLD` is monkeypatched where a test needs a tightened threshold.

**`route_on_risk`:**

| Test | Verifies |
|------|----------|
| `test_route_redline_when_eligible_exists` | ≥1 VALIDATED clause with in-threshold `risk_level` → `"redline"` (AC-1) |
| `test_route_skip_when_none_eligible` | All discarded / below-threshold → `"skip_redline"` (AC-2) |
| `test_route_skip_empty_clauses` | `clauses == {}` → `"skip_redline"` (AC-3) |
| `test_route_skip_on_ingest_error` | `ingest_error` set → `"skip_redline"` regardless of clauses (AC-4) |
| `test_route_ignores_discarded_with_risk_level` | A DISCARDED clause carrying a (defensive) `risk_level` is not counted (AC-5) |
| `test_route_threshold_from_config` | Monkeypatch threshold to exclude LOW → all-LOW doc routes `"skip_redline"` (AC-6) |
| `test_route_does_not_mutate_state` | State dict unchanged after the call (AC-7) |

**`redline_agent`:**

| Test | Verifies |
|------|----------|
| `test_eligible_clauses_get_rewrite` | Every eligible clause ends with a non-empty `suggested_rewrite` (AC-8) |
| `test_below_threshold_untouched_no_llm` | VALIDATED-but-below-threshold clause: key absent, **no** `draft_rewrite` call (AC-9) |
| `test_discarded_and_none_untouched_no_llm` | DISCARDED / `final_status is None` clause: key absent, no call (AC-10) |
| `test_one_llm_call_per_eligible_clause` | `draft_rewrite` call count == number of eligible clauses (AC-11) |
| `test_uses_generative_not_embedding_model` | Passed model is `OLLAMA_MODEL_NAME` ≠ `OLLAMA_EMBED_MODEL_NAME` (AC-12) |
| `test_ingest_error_returns_empty` | `ingest_error` set → empty update, no calls (AC-14) |
| `test_empty_clauses_returns_empty` | `clauses == {}` → empty update, warning, no calls (AC-15) |
| `test_no_eligible_findings_zero_llm` | Non-empty but zero-eligible → empty `clauses` update, zero calls, info log (AC-16) |
| `test_partial_update_only_no_error_count` | Non-outage run → keys exactly `{clauses, current_node, node_timings}`; no `error_count` (AC-17) |
| `test_graceful_failure_emits_none` | `draft_rewrite` → None → clause gets `suggested_rewrite: None`, no crash, others proceed; `error_count` NOT incremented for a single failure (AC-18) |
| `test_empty_output_emits_none` | `draft_rewrite` returns None on empty output → same fail-safe path, counts toward breaker (AC-19) |
| `test_circuit_breaker_opens` | After `THRESHOLD` consecutive None results, remaining eligible clauses get `suggested_rewrite: None` with **no** further `draft_rewrite` calls; one "circuit opened" warning (AC-20) |
| `test_empty_text_findings_are_circuit_neutral` | A run of only empty-text eligible findings emits `None` for each but **never** opens the circuit and returns **no** `error_count` (AC-20a) |
| `test_circuit_resets_on_success` | An interleaved real rewrite resets the consecutive counter (intermittent failures never trip it) |
| `test_circuit_open_emits_error_count_once` | Breaker opens → return includes `error_count: 1` exactly once; never-open run has no `error_count` key (AC-23) |
| `test_rewrite_truncated` | Rewrite longer than `REDLINE_REWRITE_MAX_CHARS` truncated before write (AC-21) |
| `test_current_node_pinned` | `current_node == "redline"` and same key in `node_timings` (AC-24) |
| `test_rerun_overwrites_rewrite` | Pre-existing `suggested_rewrite` overwritten on success; a now-failing re-run emits `None`, clearing it; reducer preserves non-rewrite fields (AC-25 / R3) |
| `test_empty_evidence_eligible_still_drafts` | Eligible clause with `evidence_snippets` `[]`/`None` still drafts, no crash (AC-26) |
| `test_empty_text_eligible_emits_none` | Whitespace-only text on an eligible finding → `suggested_rewrite: None`, **no** `draft_rewrite` call, circuit-neutral (Edge Case 6 + AC-20a) |
| `test_upstream_fields_untouched` | Node never modifies `risk_level` / `risk_rationale` / Self-RAG / CRAG / Ingest fields (AC-27) |

**`skip_redline`:**

| Test | Verifies |
|------|----------|
| `test_skip_passthrough_only` | Returns exactly `{current_node: "skip_redline", node_timings: {...}}`; no `clauses`, no `error_count`, no LLM call (AC-28) |
| `test_skip_no_clause_mutation` | `clauses` dict unchanged after run (AC-29) |

> **AC-13 coverage note:** AC-13 ("all constants read from `app.config`, never hardcoded") has no dedicated row — it is covered *implicitly*: a hardcoded timeout, threshold, or limit would break `test_circuit_breaker_opens`, `test_route_threshold_from_config`, and `test_rewrite_truncated`, all of which monkeypatch the re-exposed module-level names. Accepted coverage, flagged so it isn't mistaken for a direct assertion (same stance as the Node 5 plan's AC-7 note).

#### [MODIFY] `backend/tests/unit/test_config.py`

| Test | Verifies |
|------|----------|
| `test_redline_constants_match_spec` | `REDLINE_TIMEOUT_SECONDS`, `REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD`, `REDLINE_PROMPT_MAX_CHARS`, `REDLINE_PROMPT_RATIONALE_RESERVE_CHARS`, `REDLINE_REWRITE_MAX_CHARS` match spec §6 |
| `test_redline_constants_correct_types` | `int` for the numeric constants; `frozenset` for the threshold |
| `test_redline_rationale_reserve_within_prompt_budget` | `REDLINE_PROMPT_RATIONALE_RESERVE_CHARS < REDLINE_PROMPT_MAX_CHARS` (the reserve is a partition of the budget, never larger than it) |
| `test_redline_threshold_is_all_levels` | `REDLINE_RISK_THRESHOLD == frozenset({LOW, MEDIUM, HIGH})` and every member is a `RiskLevel` (spec §8a R1) |
| `test_redline_no_max_attempts_constant` | No `REDLINE_MAX_ATTEMPTS` exists (spec §6 — no retry loop) |
| `test_redline_uses_generative_model` | The node's generative model is `OLLAMA_MODEL_NAME`, and `OLLAMA_MODEL_NAME != OLLAMA_EMBED_MODEL_NAME` (constitution §8) |

---

### Integration Tests

#### [NEW] `backend/tests/integration/test_redline_graph.py`

Node 6 wired into the graph. `draft_rewrite` is patched at the node module level (`app.graph.nodes.redline_agent.draft_rewrite` — the same "patch where it's bound" note as `test_risk_score_graph.py:4-7`), and the upstream Self-RAG / RiskScore / CRAG LLM+embed+web boundaries are mocked — no live Ollama. `final_status` / `risk_level` are either produced by the real upstream nodes with their boundaries mocked, or injected as a pre-built `clauses` fixture.

| Test | Verifies |
|------|----------|
| `test_graph_routes_to_redline_and_ends` | A doc with an eligible finding routes through `redline` to END; that clause carries a non-empty `suggested_rewrite` (AC-30/31) |
| `test_graph_routes_to_skip_redline_and_ends` | An all-discarded doc routes through `skip_redline` to END; no clause has a `suggested_rewrite` (AC-2/28) |
| `test_graph_ingest_error_skips_to_end` | Ingest error short-circuits to END without reaching Node 6 |
| `test_graph_mixed_only_eligible_rewritten` | Mixed fixture: eligible clauses get `suggested_rewrite`; ineligible/discarded keep it absent; `risk_level` unchanged everywhere (AC-9/10/27) |
| `test_graph_circuit_open_sets_error_count` | Forcing all rewrites to fail opens the breaker → final `error_count == 1`, remaining eligible clauses have `suggested_rewrite is None` (AC-20/23) |
| `test_graph_has_only_expected_conditional_edges` | Inspect `build_graph().get_graph()`: `risk_score` branches to exactly `{redline, skip_redline}`; no `add_conditional_edges` exists for `crag_retrieval` (it stays internal); ingest guard is the only other conditional source (AC-32) |
| `test_graph_checkpointing_after_redline` | State checkpointed after Node 6. The test builds its **own** graph with a checkpointer (`SqliteSaver.from_conn_string(":memory:")`, wrapped in `try/except ImportError → pytest.skip`) because `build_graph()` compiles with no checkpointer (`builder.py:106`); asserts `compiled.get_state(thread_cfg)` is retrievable. Mirrors `test_risk_score_graph.py:247-312` |

**Note:** a separate *manual* end-to-end test (not in the automated suite) can run with live Ollama (`qwen3:14b`) against a real contract to sanity-check rewrite quality and tune the prompt. (Per the Node 4/5 memory note, live Qwen3 smoke may OOM on the current box — the automated suite must pass fully mocked regardless.)

---

## 3. Dependency & Import Map

```
app/config.py
    └── app.graph.state (RiskLevel)   # ALREADY imported (feature-007) — no change

app/graph/nodes/drafters/__init__.py
    └── (package marker — no imports)

app/graph/nodes/drafters/redline_drafter.py
    ├── concurrent.futures, json, logging, typing (stdlib)
    ├── httpx (timeout type), ollama
    └── app.graph.nodes.validators (format_evidence)   # reuse, dependency-free helper
        # model_name/timeout/limits passed in — no app.config or app.graph.state import
        # (draft_rewrite takes/returns plain str — unlike score_risk it needs no RiskLevel)

app/graph/nodes/redline_agent.py
    ├── time, logging, typing (stdlib)
    ├── app.graph.state (ContractState, ClauseType, ValidationStatus, RiskLevel)
    ├── app.graph.nodes.drafters.redline_drafter (draft_rewrite)
    └── app.config — imported AS A MODULE (`import app.config as _config`) with the
                     Redline constants re-exposed as module-level names, read by bare
                     name so tests can monkeypatch them (Node 2/4/5 precedent).

app/graph/builder.py
    ├── langgraph.graph (StateGraph, END)
    ├── app.graph.state (ContractState)
    ├── app.graph.nodes.ingest_agent (ingest_agent)
    ├── app.graph.nodes.clause_splitter_agent (clause_splitter_agent)
    ├── app.graph.nodes.crag_retrieval_agent (crag_retrieval_agent)
    ├── app.graph.nodes.self_rag_validation_agent (self_rag_validation_agent)
    ├── app.graph.nodes.risk_score_agent (risk_score_agent)
    └── app.graph.nodes.redline_agent (route_on_risk, redline_agent, skip_redline)  # NEW
```

No `numpy` / `faiss` / `duckduckgo_search` — Redline is purely generative-LLM, no vectors or retrieval (constitution §8; spec §5.3/§5.5).

---

## 4. Implementation Order

Following TDD per constitution §7 — tests written and confirmed failing before implementation.

| Step | Action | Files |
|------|--------|-------|
| 1 | Write config tests for the new Redline constants (confirm failing) | `tests/unit/test_config.py` |
| 2 | Add the `# ── Redline thresholds` block to config (no new import) | `app/config.py` |
| 3 | Run config tests (confirm passing) | — |
| 4 | Create the `drafters/` package marker | `app/graph/nodes/drafters/__init__.py` |
| 5 | Write unit tests for `draft_rewrite` (confirm failing) | `tests/unit/test_redline_drafter.py` |
| 6 | Implement `redline_drafter.py` (shared `_run_drafting` + prompt variants + parse) | `app/graph/nodes/drafters/redline_drafter.py` |
| 7 | Run drafter tests (confirm passing) | — |
| 8 | Write unit tests for route_on_risk + redline_agent + skip_redline (confirm failing) | `tests/unit/test_redline_agent.py` |
| 9 | Implement `redline_agent.py` (predicate, edge, node, skip node, `_account`) | `app/graph/nodes/redline_agent.py` |
| 10 | Run node tests (confirm passing) | — |
| 11 | Update graph builder (add 2 nodes, replace `risk_score → END` with `route_on_risk`) | `app/graph/builder.py` |
| 12 | Write and run integration tests (mocked drafting) | `tests/integration/test_redline_graph.py` |
| 13 | Full test suite pass (all existing + new) | all tests |

> **Note on Step 4**: `drafters/__init__.py` is a package marker with no logic — Redline reuses the validators' `format_evidence` rather than defining its own, so there is nothing to test here (same as `scorers/__init__.py`).

---

## 5. Design Decisions & Rationale

### `route_on_risk` as a genuine graph-level conditional edge (spec §7.1)
CRAG's confidence routing is internal per-clause branching because it routes *each clause* down a different retrieval path while all clauses share one state object. `route_on_risk` is different: it is a **document-level** decision ("does anything here need redlining?") that routes the **whole** `ContractState` to one successor — exactly what `add_conditional_edges` expresses. So it is the pipeline's one domain conditional edge realized at the graph level; RedlineAgent does the per-clause filtering internally. Both are legitimate under constitution §2's "exactly 2 conditional edges" (§2 constrains count and semantics, not realization mechanism — the same reading `005` applied to CRAG).

### Single source of truth for eligibility (spec §7.2)
`is_redline_eligible` is defined once in `redline_agent.py` and called by **both** `route_on_risk` and `redline_agent`, reading the one `REDLINE_RISK_THRESHOLD` constant. This makes the edge and the node structurally incapable of disagreeing (AC-32) — the node's per-clause re-check is defensive belt-and-suspenders, never a second policy. Colocating the edge and the node in one module (rather than putting `route_on_risk` inline in `builder.py` like the ingest guard) is deliberate: it keeps the predicate, the edge, and the node that must agree in one file and makes the edge unit-testable in isolation.

### Drafter returns `Optional[str]`, node interprets `None` as failure/skip
The smallest contract that lets the node distinguish a real rewrite from an un-producible one — exactly as `score_risk` returns `Optional[Tuple[...]]` and the reflectors return `Optional[bool]`. **Empty/whitespace output collapses to `None`** at the drafter boundary (spec AC-19) so the node has one uniform "no rewrite" signal. The fail-safe policy and circuit-breaker bookkeeping stay entirely in the node where all state lives; the drafter stays pure, stateless, and mockable.

### Fail-safe = no rewrite (`None`), the inverse of RiskScore (spec §7.3)
RiskScore fails toward `HIGH` (more visibility) because an unscored finding should still surface. Redline produces **legal text**, so on failure it emits `None` rather than a fabricated rewrite — a plausible-but-unfounded rewrite is worse than none. The finding is not lost: `risk_level` / `risk_rationale` still surface it. This is why there is **no** "default rewrite" constant analogous to `RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE`.

### Explicit `None` on attempted-but-failed clauses (spec §8a R3)
The node emits `suggested_rewrite: None` (not key-omission) for every eligible clause it attempted but couldn't rewrite. Omitting would let the reducer keep a stale rewrite from a prior run; emitting `None` clears it. This is correct under the partial-update rule because the field genuinely changed to a definitive `None` outcome — the node returns a key it modified. Ineligible clauses (never attempted) are omitted, preserving the three-state distinction of spec §2.2.

### Circuit breaker with zero-LLM paths exempt (spec §4.5, AC-20a)
Without it, an unreachable Ollama makes every eligible clause pay `REDLINE_TIMEOUT_SECONDS`. After `THRESHOLD` **consecutive** failures the node stops calling the LLM and emits `None` for the rest. Only paths that *issued* a call move the counter; the empty-text skip and post-open bulk skip are circuit-neutral, so a document full of empty-text findings can't trip the breaker or emit a false `error_count`. Per-run only; not persisted. Directly mirrors RiskScore's breaker.

### SkipRedline writes no clause fields (spec §7.4)
"Clause marked clean" is emergent from `risk_level is None` (never validated), not from `suggested_rewrite`. `001` reserves no "clean" flag, so `skip_redline` only records `current_node` + `node_timings`. Making cleanliness explicit would be a constitution §10 schema change for zero Phase-1 benefit.

### Logging strategy (spec §9)
Named logger `contractsentinel.redline`. `ContractState` carries only aggregate `node_timings["redline"]` / `node_timings["skip_redline"]`; all eval metrics (route decision, redline rate, failure/circuit rate, level→route breakdown, rewrite length/truncation, no-op/echo rate, per-clause latency) are emitted as `logger.info(..., extra={...})` structured records for the eval harness (`specs/002-tech-stack.md` §3i) — never added as extra per-clause state fields. Mirrors `risk_score_agent.py`.

---

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Ollama / `qwen3:14b` not running at pipeline time | Every rewrite fails | Drafter uses `ollama.Client(timeout=…)` so each call aborts; circuit breaker collapses remaining cost to a constant and emits `None` for the rest; `error_count:1` surfaces the degraded run |
| Hung Ollama socket outliving the executor timeout | Node blocks past timeout, defeating the breaker | `Client(timeout=…)` aborts the underlying call (primary bound); `future.result(timeout=…)` is the backstop — same pattern as `risk_scorer.py` / `reflectors.py` |
| `num_predict` too small truncates a long rewrite into invalid JSON | Valid rewrite misread as a failure (wasted `None` + breaker tick) | `num_predict = 1536` (~6000 chars) comfortably exceeds `REDLINE_REWRITE_MAX_CHARS = 4000`; invariant documented in the drafter notes |
| Edge and node disagree on eligibility | An ineligible clause redlined, or an eligible one skipped | One `is_redline_eligible` predicate + one config constant shared by both (spec §7.2); `test_graph_has_only_expected_conditional_edges` + the routing tests lock it |
| Stale `suggested_rewrite` survives a re-run whose new attempt failed | Report shows an outdated rewrite | Node emits explicit `None` on failure (R3); `test_rerun_overwrites_rewrite` locks it |
| Empty-text eligible findings spuriously open the circuit | False `error_count:1`, premature bulk skip | Empty-text and post-open paths are **circuit-neutral** — never call `_account` (AC-20a); `test_empty_text_findings_are_circuit_neutral` locks it |
| Model echoes the clause verbatim as a "successful" rewrite | No-op rewrite counted as success | Logged as the no-op/echo eval-watch metric (spec §9.6 / §8a R5); not acted on in Phase 1, flagged for a later `rewrite.strip()==text.strip()→None` iteration |
| `risk_level` deserialized as a str after checkpoint round-trip | Membership check misses | `RiskLevel` is a str-Enum (`RiskLevel.LOW == "low"`, hash-equal), so `in REDLINE_RISK_THRESHOLD` works for enum or str; `None → False` |
| Unbounded rewrite bloats checkpointed state | State size growth | Node truncates to `REDLINE_REWRITE_MAX_CHARS` before writing (AC-21); `test_rewrite_truncated` locks it |
| `error_count` increment misread as a hard pipeline error downstream | Spurious abort/retry | It is a single health-signal increment via `operator.add`, not a control flag; capped at one per run (mirrors RiskScore/Self-RAG) |
| A new `add_conditional_edges` sneaks in and violates constitution §2's edge count | Architecture drift | `test_graph_has_only_expected_conditional_edges` asserts the exact conditional-edge set (AC-32) |

---

## 7. Out of Scope for This Plan

- **Node 7 (ReportAgent)**: not wired or implemented. `builder.py` routes both `redline` and `skip_redline` → END until feature-009; the plan notes where those edges will re-point to `report`.
- **Assigning severity / `risk_level`**: RiskScore (Node 5); Node 6 consumes it as a gate (spec §5.1).
- **Deciding validated vs discarded**: Self-RAG (Node 4); Node 6 reads `final_status` as a gate (spec §5.2).
- **Gathering / scoring retrieval evidence, embeddings, web search**: CRAG (Node 3); Redline consumes `evidence_snippets` as given drafting context (spec §5.3).
- **`evidence_trail` / `report_path` compilation**: ReportAgent (Node 7); Redline writes only per-clause `suggested_rewrite` (spec §5.4).
- **Any document-level "clean" / "reviewed" flag or roll-up remediation status**: emergent, no new field; a `001` change (spec §5.5 / §8a R4).
- **Human-in-the-loop acceptance / editing of a rewrite**: no review/accept UI (spec §5.6; PERMANENTLY CUT).
- **Legal correctness / enforceability guarantees of the rewrite**: the rewrite is an LLM suggestion for human review, not vetted advice (spec §5.7).
- **Bounded-parallelism over clauses**: sequential for Phase 1; a concurrency knob is deferred (spec §5.8).
- **A distinct "no change needed" outcome / retry / self-consistency re-sample**: rejected (spec §8a R5 / §6) — single call, fail-safe `None` on failure.
- **Tightening `REDLINE_RISK_THRESHOLD` to `{MEDIUM, HIGH}`**: a future one-line config change justified by the §9 metrics; not done here (spec §8a R1).
- **Prompt finalization**: pinned provisionally (rewrite instruction + rubric context); tunable without control-flow change.
- **MCP delivery of the report, API endpoints, DB storage, privacy/security**: per Phase 2 deferral / other specs.

---

## 8. Reference: Constitution & Spec Traceability

- **Constitution §2** — Node 6 is item 6 (`route_on_risk` + RedlineAgent + SkipRedline); `route_on_risk` is one of the two permitted conditional edges. Realization: spec §7.1, this plan §2 (builder) / §5.
- **Constitution §3** — all thresholds in `app/config.py`; this plan §2 (config block), AC-13 note.
- **Constitution §5** — partial-update rule; node returns only `clauses`/`current_node`/`node_timings` (+ `error_count:1` on circuit open). This plan §2 (node flow), §5 (explicit-`None` rationale).
- **Constitution §7** — TDD order; this plan §4.
- **Constitution §8** — generative model only, never embedding; this plan §2, §3, config test.
- **Constitution §9** — local-model latency: per-call timeout + circuit breaker; this plan §2 (drafter), §6.
- **Constitution §10** — no `001` schema change (three-state `suggested_rewrite` is a doc-only refinement of the existing field); spec §2.2 / §8a R2.
- **Constitution §11** — branch `feature/008-route-on-risk-redline` (top of this file).
- **Spec §8a R1–R5** — resolved decisions carried into this plan §1.
