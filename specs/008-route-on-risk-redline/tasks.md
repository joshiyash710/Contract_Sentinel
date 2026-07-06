# route_on_risk + Redline Implementation Tasks

Reference documents:
- Spec: `specs/008-route-on-risk-redline/spec.md`
- Plan: `specs/008-route-on-risk-redline/plan.md`
- State schema: `specs/001-contract-state-schema.md`
- Tech stack: `specs/002-tech-stack.md`
- Constitution: `specs/000-constitution.md`

All file paths below are relative to `backend/` unless stated otherwise.

**Workflow reminders:**
- Follow TDD per constitution §7 — write tests, confirm they FAIL, then implement to make them PASS.
- This feature is **Node 6**, a single unit of THREE graph elements owned together: the `route_on_risk` conditional edge, the `redline` node (RedlineAgent), and the `skip_redline` node — plus the shared `is_redline_eligible` predicate they both use.
- RedlineAgent returns ONLY the state keys it updates per constitution §5 (Partial-Update Rule): `clauses`, `current_node`, `node_timings` — **plus `error_count: 1` in the one case the circuit breaker opens** (spec §7.6 / AC-23). SkipRedline returns ONLY `current_node`, `node_timings`. Never any other key.
- All thresholds live in `app/config.py` per constitution §3 — never hardcode inline.
- Model separation (constitution §8): every Redline LLM call uses the **generative** `OLLAMA_MODEL_NAME` (Qwen3). Redline makes NO vector calls and MUST NEVER reference `OLLAMA_EMBED_MODEL_NAME`.
- The five locked design decisions (spec §8a): **R1** `REDLINE_RISK_THRESHOLD = {LOW, MEDIUM, HIGH}` (every validated finding redlined; SkipRedline fires only for zero-validated-finding docs); **R2** `suggested_rewrite` is three-state — key absent = never attempted, `None` = attempted-but-failed, str = success; "clean" is `risk_level is None`, not `suggested_rewrite is None`; **R3** on failure/circuit-open emit explicit `suggested_rewrite: None` (omit the key only for never-attempted clauses); **R4** "clean" stays emergent, no new `001` field; **R5** always attempt a rewrite for an eligible clause, no distinct "no change needed" outcome (a no-op/echo eval-watch metric is logged, not acted on).
- **Fail-safe is the INVERSE of RiskScore's:** RiskScore fails to `HIGH`; Redline fails to **no rewrite** (`suggested_rewrite: None`) — a risk tool must not fabricate legal text. There is intentionally NO "default rewrite" constant.
- Eligibility gate: a clause is redlined iff `final_status == ValidationStatus.VALIDATED` **and** `risk_level in REDLINE_RISK_THRESHOLD`. The edge and the node compute this from the **same** `is_redline_eligible` helper reading the **one** config constant (spec §7.2) — they can never disagree.
- **Circuit-neutrality (AC-20a)**: only paths that actually issued a `draft_rewrite` LLM call and got `None` back move the consecutive-failure counter. The empty-text skip and the post-open bulk skip reach `suggested_rewrite: None` **without** an LLM call and must NOT touch the counter.
- Branch: `feature/008-route-on-risk-redline` per constitution §11.

---

## Task 0: Create feature branch

- [ ] From an up-to-date `main`, create and check out `feature/008-route-on-risk-redline`

**Why**: Per constitution §11, every feature is developed on its own branch. RiskScore (007) is already merged to `main`.

**Verify**: `git branch --show-current` prints `feature/008-route-on-risk-redline`.

**Note**: The working tree has an untracked `specs/008-route-on-risk-redline/` (spec.md, plan.md, tasks.md). Confirm with the user whether the spec docs should be committed before branching, so 008 starts from a clean tree (same as the 007 start).

---

## Task 1: Write config tests for the Redline constants (confirm FAILING)

- [ ] Open `tests/unit/test_config.py`
- [ ] Add 6 new test functions for the Redline constants, the threshold value, the reserve/budget invariant, the no-retry guarantee, and model separation:

```python
def test_redline_constants_match_spec():
    """Verify Redline numeric constants match specs/008 §6."""
    from app.config import (
        REDLINE_TIMEOUT_SECONDS,
        REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD,
        REDLINE_PROMPT_MAX_CHARS,
        REDLINE_PROMPT_RATIONALE_RESERVE_CHARS,
        REDLINE_REWRITE_MAX_CHARS,
    )
    assert REDLINE_TIMEOUT_SECONDS == 120
    assert REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD == 5
    assert REDLINE_PROMPT_MAX_CHARS == 6000
    assert REDLINE_PROMPT_RATIONALE_RESERVE_CHARS == 1000
    assert REDLINE_REWRITE_MAX_CHARS == 4000


def test_redline_constants_correct_types():
    """int for the numeric constants; frozenset for the threshold."""
    from app import config
    assert isinstance(config.REDLINE_TIMEOUT_SECONDS, int)
    assert isinstance(config.REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD, int)
    assert isinstance(config.REDLINE_PROMPT_MAX_CHARS, int)
    assert isinstance(config.REDLINE_PROMPT_RATIONALE_RESERVE_CHARS, int)
    assert isinstance(config.REDLINE_REWRITE_MAX_CHARS, int)
    assert isinstance(config.REDLINE_RISK_THRESHOLD, frozenset)


def test_redline_threshold_is_all_levels():
    """Resolved Option A (spec §8a R1): all three levels are redline-eligible."""
    from app.config import REDLINE_RISK_THRESHOLD
    from app.graph.state import RiskLevel
    assert REDLINE_RISK_THRESHOLD == frozenset(
        {RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH}
    )
    assert all(isinstance(x, RiskLevel) for x in REDLINE_RISK_THRESHOLD)


def test_redline_rationale_reserve_within_prompt_budget():
    """The reserve is a partition of the prompt budget, never larger than it."""
    from app.config import (
        REDLINE_PROMPT_RATIONALE_RESERVE_CHARS,
        REDLINE_PROMPT_MAX_CHARS,
    )
    assert REDLINE_PROMPT_RATIONALE_RESERVE_CHARS < REDLINE_PROMPT_MAX_CHARS


def test_redline_no_max_attempts_constant():
    """No retry loop for Redline (spec §6) — the constant must not exist."""
    from app import config
    assert not hasattr(config, "REDLINE_MAX_ATTEMPTS")


def test_redline_uses_generative_model():
    """Constitution §8: the generative model is distinct from the embedding model."""
    from app.config import OLLAMA_MODEL_NAME, OLLAMA_EMBED_MODEL_NAME
    assert OLLAMA_MODEL_NAME != OLLAMA_EMBED_MODEL_NAME
    assert OLLAMA_MODEL_NAME == "qwen3:14b"
```

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — `test_redline_constants_match_spec`, `test_redline_constants_correct_types`, `test_redline_threshold_is_all_levels`, and `test_redline_rationale_reserve_within_prompt_budget` must FAIL (`ImportError`/`AttributeError` — the new constants don't exist yet). `test_redline_no_max_attempts_constant` and `test_redline_uses_generative_model` may already PASS. Existing config tests (Ingest + ClauseSplitter + CRAG + Self-RAG + RiskScore) must still PASS.

---

## Task 2: Add the Redline constants to config

- [ ] Open `app/config.py`
- [ ] **No new import needed** — `RiskLevel` is ALREADY imported at `config.py:11` (added by feature-007). `REDLINE_RISK_THRESHOLD` reuses it directly. (This differs from the 007 task, which had to add the import.)
- [ ] Append a new `# ── Redline thresholds` block at the end of the file (pure addition — no rename, no placeholder to replace):

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
# later tightening to {MEDIUM, HIGH}. Membership is robust to a str value too because
# RiskLevel is a str-Enum (RiskLevel.LOW == "low", hash-equal). Tune against real
# sample contracts.

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
# rationale (the model's remediation target — it says WHY to rewrite) to a zero
# budget. Matches RISK_RATIONALE_MAX_CHARS (the max a Node-5 rationale can be), so a
# present rationale is never dropped. A budget-partitioning threshold, so it lives in
# config per constitution §3 rather than inline. Must stay < REDLINE_PROMPT_MAX_CHARS.

REDLINE_REWRITE_MAX_CHARS: int = 4000
# Generated suggested_rewrite is truncated to this length before being written to
# ContractState, to bound persisted state size (spec §4.9). Larger than
# RISK_RATIONALE_MAX_CHARS (1000) because a rewritten clause is full replacement
# language, not a one-line explanation.
```

- [ ] The node reuses the existing `OLLAMA_MODEL_NAME` — introduce no new model constant. Do NOT add `REDLINE_MAX_ATTEMPTS` (spec §6 — no retry loop).

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — all config tests (Ingest + ClauseSplitter + CRAG + Self-RAG + RiskScore + Redline) must now PASS.

---

## Task 3: Create the drafters package marker (no dedicated TDD cycle)

- [ ] Create directory `app/graph/nodes/drafters/`
- [ ] Create file `app/graph/nodes/drafters/__init__.py` — a package marker with a module docstring only (no logic, nothing to export):

```python
"""
Drafter modules for the Redline node (Node 6).

redline_drafter.py generates safer replacement language for a redline-eligible
clause via a single generative LLM call. Like scorers/__init__.py, this package
init hosts no shared helper — redline_drafter.py reuses format_evidence from the
validators package (a dependency-free renderer of the 001 evidence shape) rather
than redefining it.
"""
```

**Why**: mirrors the `scorers/` / `validators/` / `retrievers/` package layout. The evidence formatter is reused, not duplicated, so there is no helper here and no test for this file.

**Verify**: Run from `backend/`:
```
python -c "import app.graph.nodes.drafters; print('ok')"
```

---

## Task 4: Write unit tests for `draft_rewrite` (confirm FAILING)

- [ ] Create file `tests/unit/test_redline_drafter.py`
- [ ] The import `from app.graph.nodes.drafters.redline_drafter import draft_rewrite` will fail until Task 5 — expected for TDD.
- [ ] **Mocking strategy (name the target)**: patch `ollama.Client` at `app.graph.nodes.drafters.redline_drafter.ollama.Client` (equivalently `patch("ollama.Client")` since `redline_drafter.py` does `import ollama`). Configure `mock_client.return_value.chat.return_value = {"message": {"content": '{"suggested_rewrite": "safer clause text"}'}}`. Assert on `mock_client.call_args` that it was constructed with `timeout=<passed timeout_seconds>` (the correctness hinge from Task 5) and on `.chat.call_args` for `model=OLLAMA_MODEL_NAME` and `format="json"`. **No real Ollama.**
- [ ] Write these 15 test functions (plan §2 drafter matrix):

| Test function | Verifies |
|---------------|----------|
| `test_returns_rewrite_string` | `{"suggested_rewrite": "safer text"}` → `"safer text"` |
| `test_timeout_returns_none` | Simulated timeout (`concurrent.futures.TimeoutError` / `httpx.TimeoutException`) → `None`, warning logged |
| `test_connection_error_returns_none` | Ollama unreachable (`ConnectionError`/`httpx.ConnectError`) → `None` |
| `test_malformed_json_returns_none` | Non-JSON `content` → `None` |
| `test_missing_field_returns_none` | JSON without a `suggested_rewrite` key → `None` |
| `test_empty_rewrite_returns_none` | `{"suggested_rewrite": "   "}` → `None` (empty/whitespace output is a drafting failure — AC-19) |
| `test_non_string_rewrite_returns_none` | `{"suggested_rewrite": 5}` / `null` → `None` |
| `test_uses_generative_model_only` | `chat` called with `model=OLLAMA_MODEL_NAME`; `OLLAMA_EMBED_MODEL_NAME` never referenced (AC-12) |
| `test_prompt_truncated_to_max_chars` | Oversized clause+rationale+evidence truncated so the prompt input is bounded by `prompt_max_chars` (AC-22) |
| `test_long_clause_preserves_rationale` | A clause **longer than** `prompt_max_chars` still includes the (reserved) `risk_rationale` in the built prompt — the rationale floor is not starved to zero. Locks the reserve logic (the one piece of new logic vs. Node 5) |
| `test_empty_evidence_drafts_on_text` | `evidence_snippets=None`/`[]` → uses the text-only prompt variant; still returns a rewrite on a valid response; no crash (AC-26) |
| `test_rationale_included_in_prompt` | The provided `risk_rationale` text appears in the built prompt |
| `test_clause_type_included_in_prompt` | A provided `clause_type` label appears in the built prompt; `None` → "unspecified" wording |
| `test_drafter_never_raises` | Any injected exception inside the call → `None`, nothing propagates |
| `test_rewrite_returned_untruncated` | The drafter returns the full rewrite (the NODE applies `REDLINE_REWRITE_MAX_CHARS`, not the drafter) |

- [ ] For `test_prompt_truncated_to_max_chars`: capture the prompt actually sent (from `.chat.call_args` → `messages[0]["content"]`) and assert the combined variable portion (clause + rationale + evidence) is bounded by `prompt_max_chars`. Use oversized inputs so independent truncation would exceed the budget but the reserve+combined rule does not.
- [ ] For `test_long_clause_preserves_rationale`: pass a `clause_text` longer than `prompt_max_chars`, a short distinctive `risk_rationale` (e.g. `"UNCAPPED_LIABILITY_MARKER"`), a small `prompt_max_chars` (e.g. 200) and `rationale_reserve` (e.g. 50), and assert the marker still appears in the built prompt (the clause budget is `prompt_max_chars - reserve`, so the rationale is never dropped).
- [ ] Warning assertions use pytest's `caplog` at `WARNING`.

**Verify**: Run `python -m pytest tests/unit/test_redline_drafter.py -v` — all 15 tests must FAIL (ImportError). Confirms the TDD cycle.

---

## Task 5: Implement `draft_rewrite`

- [ ] Create file `app/graph/nodes/drafters/redline_drafter.py`
- [ ] **Imports**: `concurrent.futures`, `json`, `logging` (stdlib); `from typing import Any, Dict, List, Optional`; `httpx` (timeout type); `ollama`; `from app.graph.nodes.validators import format_evidence`. **No `app.config` import** (all limits passed in) and **no `app.graph.state` import** — `draft_rewrite` takes/returns plain `str`, so (unlike `score_risk`) it needs no `RiskLevel`.
- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.redline.drafter")`
- [ ] Public interface — returns `Optional[str]`, **never raises** (`None` = un-producible → the node emits `suggested_rewrite: None` and counts it toward the circuit breaker):

```python
def draft_rewrite(clause_text: str,
                  risk_rationale: "Optional[str]",
                  evidence_snippets: "Optional[List[Dict[str, Any]]]",
                  clause_type: "Optional[str]",
                  timeout_seconds: int, model_name: str,
                  prompt_max_chars: int, rationale_reserve: int) -> "Optional[str]":
    """Single generative call producing safer replacement language for a
    redline-eligible clause. risk_rationale (the Node-5 explanation of WHY the clause
    is risky) is the remediation target fed to the prompt. evidence_snippets (001
    shape) is drafting context when present; may be []/None (Self-RAG rescue path) →
    draft on clause text + risk_rationale + clause_type alone. clause_type is a
    normalized string label (or None). Returns the rewrite string (untruncated — the
    node applies REDLINE_REWRITE_MAX_CHARS) or None on any failure / empty output.
    Never raises."""
```

- [ ] **Shared invocation core** — a private `_run_drafting(prompt, timeout_seconds, model_name) -> Optional[str]` via `_call_ollama` + `_parse_rewrite`. Mirrors `risk_scorer.py:118-152` structurally.
- [ ] **CRITICAL — client-level timeout is the primary bound (plan §5)**: the call MUST go through `ollama.Client(timeout=timeout_seconds).chat(model=model_name, messages=[{"role":"user","content":prompt}], format="json", options={"num_predict": 1536})`, run inside a `concurrent.futures.ThreadPoolExecutor(max_workers=1)` with `future.result(timeout=timeout_seconds)` — exactly the `risk_scorer._run_scoring` / `reflectors._run_judgment` pattern. Do NOT use a bare `ollama.chat` bounded only by the executor: on a hung Ollama socket the worker thread would stay blocked and `shutdown(wait=True)` at `with` exit would hang, defeating both `REDLINE_TIMEOUT_SECONDS` and the circuit breaker.
- [ ] **CRITICAL — `num_predict = 1536` (larger than Node 5's 384)** because a rewrite is full clause language, not a one-line rationale. **Invariant**: `num_predict` must stay well above `REDLINE_REWRITE_MAX_CHARS`-in-tokens (~1000 tokens for 4000 chars) so a legitimately long rewrite is never cut off into invalid JSON and misread as a failure. `1536` gives ~50% headroom (~6000 chars). If either value is tuned, preserve `num_predict >> REDLINE_REWRITE_MAX_CHARS/4`.
- [ ] **Rewrite parsing** (`_parse_rewrite`) — parse `response["message"]["content"]` as JSON, then:
  - `rewrite_raw = data.get("suggested_rewrite")`. If not a `str` → return `None`. Else `rewrite = rewrite_raw.strip()`; if `not rewrite` (empty/whitespace) → return `None` (AC-19 — empty output is a failure, not a valid `""` rewrite).
  - Return the stripped `rewrite` **untruncated** (the node applies `REDLINE_REWRITE_MAX_CHARS`).
  - Non-JSON body, or missing `suggested_rewrite` → `None`.
- [ ] **Failure handling** — catch `concurrent.futures.TimeoutError`, `httpx.TimeoutException`, and any `Exception` → log a rate-limited WARNING and return `None`. Never raise.
- [ ] **CRITICAL — prompt truncation reserves a rationale floor (plan §2; the ONE new-logic difference vs. Node 5)**. Do NOT copy `risk_scorer`'s clause-first order: reserve the rationale budget BEFORE truncating the clause, so a clause longer than `prompt_max_chars` cannot starve the rationale to zero:
  ```python
  rationale_full = (risk_rationale or "").strip()
  reserve       = min(len(rationale_full), rationale_reserve)
  clause_budget = max(0, prompt_max_chars - reserve)
  clause_trunc  = clause_text[:clause_budget]
  remaining     = max(0, prompt_max_chars - len(clause_trunc))
  rationale_trunc = rationale_full[:remaining]
  remaining     = max(0, remaining - len(rationale_trunc))
  evidence_str  = format_evidence(evidence_snippets, remaining)   # "" when empty/None
  ```
  Log truncation at debug (same style as `risk_scorer.py:86-100`).
- [ ] **Prompt content** — one template with an evidence-present and an evidence-absent variant (mirroring `_SCORING_WITH_EVIDENCE_PROMPT` / `_SCORING_TEXT_ONLY_PROMPT` in `risk_scorer.py`). Both:
  - Instruct: *rewrite the clause to neutralize the risk described in the rationale while preserving the clause's legitimate commercial intent; return ONLY the replacement clause text.*
  - Insert `risk_rationale` as the remediation target: `This clause was flagged as risky because: {rationale_trunc}`.
  - Insert `clause_type` as context: `This clause is categorized as: {clause_type or "unspecified"}`.
  - Instruct the model to reply with ONLY `{"suggested_rewrite": "<rewritten clause text>"}` — no markdown.
  - The evidence-absent variant states no retrieved evidence is available.
  The exact wording is tunable later without changing control flow.

**Verify**: Run `python -m pytest tests/unit/test_redline_drafter.py -v` — all 15 tests must PASS.

---

## Task 6: Write unit tests for `redline_agent` (route_on_risk + redline + skip_redline) (confirm FAILING)

- [ ] Create file `tests/unit/test_redline_agent.py`
- [ ] The imports `from app.graph.nodes.redline_agent import route_on_risk, redline_agent, skip_redline, is_redline_eligible` will fail until Task 7 — expected for TDD.
- [ ] **Mocking strategy**: patch `draft_rewrite` **at the node module level** (`app.graph.nodes.redline_agent.draft_rewrite`), because the node does `from ...redline_drafter import draft_rewrite` — binding the name into the node module. Patching `drafters.redline_drafter.draft_rewrite` would NOT affect the node. Give the mock a `side_effect` list (or `return_value`) so results are deterministic per call, and assert call counts.
- [ ] Helper: `make_state(clauses, ingest_error=None, document_id="doc-1")` returning a minimal state dict. Clause records carry at least `{text, position, final_status, risk_level, risk_rationale, evidence_snippets, clause_type}`. Provide builders for the common shapes: an eligible finding (`VALIDATED` + `risk_level=RiskLevel.HIGH`), an eligible finding with empty evidence, an eligible finding with empty text, a below-threshold `VALIDATED` finding (only relevant when the threshold is monkeypatched to exclude a level), a `DISCARDED` clause, and a `final_status=None` clause.
- [ ] Use `RiskLevel` and `ValidationStatus` from `app.graph.state` in fixtures; the `draft_rewrite` mock returns `"safer text"` strings or `None`.

**route_on_risk (7 tests):**

| Test function | Verifies |
|---------------|----------|
| `test_route_redline_when_eligible_exists` | ≥1 VALIDATED clause with in-threshold `risk_level` → returns `"redline"` (AC-1) |
| `test_route_skip_when_none_eligible` | All discarded / below-threshold → returns `"skip_redline"` (AC-2) |
| `test_route_skip_empty_clauses` | `clauses == {}` → `"skip_redline"` (AC-3) |
| `test_route_skip_on_ingest_error` | `ingest_error` set → `"skip_redline"` regardless of clauses (AC-4) |
| `test_route_ignores_discarded_with_risk_level` | A DISCARDED clause carrying a (defensive) `risk_level` is not counted → `"skip_redline"` (AC-5) |
| `test_route_threshold_from_config` | Monkeypatch `REDLINE_RISK_THRESHOLD` (node module) to exclude LOW → an all-LOW doc returns `"skip_redline"` (AC-6) |
| `test_route_does_not_mutate_state` | Deep-copy the state, call `route_on_risk`, assert the state dict is unchanged (AC-7) |

**redline_agent (22 tests):**

| Test function | Verifies |
|---------------|----------|
| `test_eligible_clauses_get_rewrite` | Every eligible clause ends with a non-empty string `suggested_rewrite` (AC-8) |
| `test_below_threshold_untouched_no_llm` | VALIDATED-but-below-threshold clause (threshold monkeypatched): key **absent** in the return, **no** `draft_rewrite` call (AC-9) |
| `test_discarded_and_none_untouched_no_llm` | `DISCARDED` / `final_status is None` clause: key absent, no call (AC-10) |
| `test_one_llm_call_per_eligible_clause` | `draft_rewrite` call count == number of eligible clauses (AC-11) |
| `test_uses_generative_not_embedding_model` | `draft_rewrite` invoked with `OLLAMA_MODEL_NAME`; `OLLAMA_EMBED_MODEL_NAME` never referenced by the node (AC-12) |
| `test_ingest_error_returns_empty` | `ingest_error` set → empty update; no `draft_rewrite` calls (AC-14) |
| `test_empty_clauses_returns_empty` | `clauses == {}` → empty update, warning, no calls (AC-15) |
| `test_no_eligible_findings_zero_llm` | Non-empty but zero-eligible → empty `clauses` update, zero calls, info log (AC-16) |
| `test_partial_update_only_no_error_count` | Non-outage run → keys exactly `{clauses, current_node, node_timings}`; NO `error_count` (AC-17) |
| `test_graceful_failure_emits_none` | `draft_rewrite` → None → clause gets **explicit** `suggested_rewrite: None` in the return, no crash, other clauses proceed; `error_count` NOT incremented for a single failure (AC-18) |
| `test_empty_output_emits_none` | `draft_rewrite` returns None on empty output → same fail-safe path, counts toward breaker (AC-19) |
| `test_circuit_breaker_opens` | After `THRESHOLD` consecutive None-returns, remaining eligible clauses get `suggested_rewrite: None` with NO further `draft_rewrite` calls; one "circuit opened" warning (AC-20) |
| `test_empty_text_findings_are_circuit_neutral` | A run of only empty-text eligible findings emits `None` for each but **never** opens the circuit and returns **no** `error_count` (AC-20a) |
| `test_circuit_resets_on_success` | An interleaved real rewrite resets the consecutive counter (intermittent single failures never trip it) |
| `test_circuit_open_emits_error_count_once` | Breaker opens → return includes `error_count: 1` exactly once; never-open run has no `error_count` key (AC-23) |
| `test_rewrite_truncated` | Rewrite longer than `REDLINE_REWRITE_MAX_CHARS` truncated before write (AC-21) |
| `test_current_node_pinned` | `current_node == "redline"` and same key in `node_timings` (AC-24) |
| `test_rerun_overwrites_rewrite` | Pre-existing `suggested_rewrite` overwritten on success; a now-failing re-run emits `None`, clearing it; reducer preserves non-rewrite fields (AC-25 / R3) |
| `test_empty_evidence_eligible_still_drafts` | Eligible clause with `evidence_snippets` `[]`/`None` still drafts (one `draft_rewrite` call), no crash (AC-26) |
| `test_empty_text_eligible_emits_none` | Whitespace-only text on an eligible finding → `suggested_rewrite: None`, **no** `draft_rewrite` call, circuit-neutral (Edge Case 6 + AC-20a) |
| `test_upstream_fields_untouched` | Node never sets/modifies `risk_level`, `risk_rationale`, or any Self-RAG/CRAG/Ingest field on any clause (AC-27) |
| `test_noop_rewrite_counted` | Mock `draft_rewrite` to return the clause `text` verbatim → the aggregate `RedlineAgent completed` log's `extra` has `noop == 1` and `rewritten == 1` (locks the no-op/echo metric — spec §9 metric 6 / §8a R5 — and that the aggregate log fires at all). Use `caplog` |

**skip_redline (2 tests):**

| Test function | Verifies |
|---------------|----------|
| `test_skip_passthrough_only` | Returns exactly `{current_node: "skip_redline", node_timings: {"skip_redline": <float>}}`; no `clauses`, no `error_count`, no `draft_rewrite` call (AC-28) |
| `test_skip_no_clause_mutation` | Given a state with clauses, `skip_redline`'s return contains no `clauses` key; the input `clauses` dict is unchanged (AC-29) |

- [ ] For `test_ingest_error_returns_empty` / `test_empty_clauses_returns_empty` / `test_no_eligible_findings_zero_llm`: assert the `draft_rewrite` mock `assert_not_called()`.
- [ ] For `test_circuit_breaker_opens`: monkeypatch `REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD` small (e.g. 3) on the **node module**, make `draft_rewrite` always return `None`, feed more eligible findings than the threshold, and assert `draft_rewrite` calls STOP after the trip (later findings get `suggested_rewrite: None` via the bulk path, with zero further calls).
- [ ] For `test_empty_text_findings_are_circuit_neutral`: feed more than `THRESHOLD` eligible findings **all with whitespace-only text**; assert `draft_rewrite` is never called, every finding gets `suggested_rewrite: None`, and the return has **no** `error_count` key (the counter was never touched).
- [ ] For `test_partial_update_only_no_error_count`: assert forbidden keys absent — `document_id`, `extracted_text`, `ingest_error`, `report_path`, `evidence_trail`, `mcp_delivery_status`, `retry_budgets`, and specifically `error_count` (on a non-outage run).
- [ ] For `test_upstream_fields_untouched`: give an eligible clause a `risk_level` / `risk_rationale` / a Self-RAG verdict field, and assert the node's returned per-clause update for that clause contains ONLY `suggested_rewrite` (no other key).
- [ ] For `test_below_threshold_untouched_no_llm`: monkeypatch `REDLINE_RISK_THRESHOLD` on the node module to `frozenset({RiskLevel.HIGH})`, feed a `VALIDATED` clause with `risk_level=RiskLevel.LOW`, and assert its `suggested_rewrite` key is absent from the return and `draft_rewrite` was not called for it.
- [ ] For `test_noop_rewrite_counted`: set the `draft_rewrite` mock to return the SAME string as the eligible clause's `text`; capture the `RedlineAgent completed` record via `caplog` and assert `record.noop == 1` and `record.rewritten == 1`. This is the ONLY test that locks the `is_noop` counting (spec §9 metric 6 / §8a R5); without it an implementer could silently drop the `is_noop` line.

**Verify**: Run `python -m pytest tests/unit/test_redline_agent.py -v` — all 31 tests must FAIL (ImportError). Confirms the TDD cycle.

---

## Task 7: Implement `redline_agent.py` (predicate + edge + node + skip node)

- [ ] Create file `app/graph/nodes/redline_agent.py`
- [ ] **Imports**: `time`, `logging` (stdlib); `from typing import Optional`; `from app.graph.state import ContractState, ClauseType, ValidationStatus, RiskLevel`; `from app.graph.nodes.drafters.redline_drafter import draft_rewrite`.
- [ ] **CRITICAL — config import pattern (mirror `risk_score_agent.py:42-49`)**: `import app.config as _config` and re-expose each tunable as a monkeypatchable module-level name read by **bare name** (never `_config.NAME`):

```python
import app.config as _config

OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME
REDLINE_RISK_THRESHOLD = _config.REDLINE_RISK_THRESHOLD
REDLINE_TIMEOUT_SECONDS = _config.REDLINE_TIMEOUT_SECONDS
REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD = _config.REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD
REDLINE_PROMPT_MAX_CHARS = _config.REDLINE_PROMPT_MAX_CHARS
REDLINE_PROMPT_RATIONALE_RESERVE_CHARS = _config.REDLINE_PROMPT_RATIONALE_RESERVE_CHARS
REDLINE_REWRITE_MAX_CHARS = _config.REDLINE_REWRITE_MAX_CHARS
```

- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.redline")`
- [ ] **Shared eligibility predicate — the single source of truth (spec §7.2)**. Reads the module-level `REDLINE_RISK_THRESHOLD` (monkeypatchable) so BOTH `route_on_risk` and `redline_agent` compute eligibility identically (AC-32):

```python
def is_redline_eligible(record: dict) -> bool:
    """True iff this clause should be redlined: VALIDATED AND risk_level in the
    configured threshold. Robust to risk_level being a RiskLevel enum or its str
    value (RiskLevel is a str-Enum → hash-equal); None → False."""
    if record.get("final_status") != ValidationStatus.VALIDATED:
        return False
    return record.get("risk_level") in REDLINE_RISK_THRESHOLD
```

- [ ] **`route_on_risk` — the conditional edge (pure; never mutates state, AC-7)**:

```python
def route_on_risk(state: ContractState) -> str:
    """Graph-level conditional edge after risk_score. Returns "redline" if the
    document has >=1 redline-eligible clause, else "skip_redline"."""
    if state.get("ingest_error") is not None:
        return "skip_redline"
    clauses = state.get("clauses", {})
    if any(is_redline_eligible(rec) for rec in clauses.values()):
        return "redline"
    return "skip_redline"
```

- [ ] **`skip_redline` — passthrough node (writes NO clause fields, AC-28/29)**:

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

- [ ] **`redline_agent` — the node**. Public interface:

```python
def redline_agent(state: ContractState) -> dict:
    """LangGraph Node 6 (RedlineAgent). Reads clauses/document_id/ingest_error; drafts
    a safer suggested_rewrite for each redline-eligible clause; returns partial dict:
    clauses (per-clause suggested_rewrite), current_node, node_timings, and
    error_count:1 ONLY when the circuit breaker opened."""
```

- [ ] **CRITICAL — circuit state is a SINGLE MUTABLE HOLDER, not bare locals (plan §2)**: `cb = {"consecutive_failures": 0, "open": False, "tripped": False}`, threaded into `_account`. Rebinding an outer `int`/`bool` from a nested function needs `nonlocal`; omit it and Python raises `UnboundLocalError` or silently shadows, so the breaker never opens. Mutating a dict's contents (`cb["open"] = True`) needs no `nonlocal`. Do NOT introduce standalone `consecutive_failures`/`circuit_open` locals.
- [ ] **Internal flow** (plan §2 — follow exactly):
  1. `start_time = time.monotonic()`; `current_node = "redline"`; `document_id = state.get("document_id", "unknown")`.
  2. **Defensive `ingest_error` check** — if `state.get("ingest_error") is not None` → return empty update (`clauses={}`, `current_node`, `node_timings`); NO `draft_rewrite` calls (AC-14).
  3. `clauses = state.get("clauses", {})`. If falsy → log warning, return empty update (AC-15).
  4. `cb = {...}`; `clause_updates = {}`; `counts = {"eligible": 0, "rewritten": 0, "failed": 0, "noop": 0, "empty_text": 0, "bulk_skipped": 0}` (spec §9 metric source; mirrors Node 5's `level_counts`).
  5. Iterate clauses **in document order** (sort by `position`). For each `clause_id`, `record`:
     - If `not is_redline_eligible(record)` → `continue` (OMIT the key — never attempted: AC-9/10).
     - `counts["eligible"] += 1`.
     - `text = (record.get("text") or "").strip()`. If `not text` → `clause_updates[clause_id] = {"suggested_rewrite": None}`; `counts["empty_text"] += 1`; log warning; `continue`. **CIRCUIT-NEUTRAL: do NOT call `_account`** (Edge Case 6 / AC-20a).
     - If `cb["open"]` → `clause_updates[clause_id] = {"suggested_rewrite": None}`; `counts["bulk_skipped"] += 1`; `continue`. **CIRCUIT-NEUTRAL bulk skip: no `_account`, no `draft_rewrite` call** (AC-20a).
     - `rationale = record.get("risk_rationale")`; `evidence = record.get("evidence_snippets")` (may be `[]`/`None` — fine, AC-26); `ct = _clause_type_value(record.get("clause_type"))`.
     - `result = draft_rewrite(text, rationale, evidence, ct, REDLINE_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME, REDLINE_PROMPT_MAX_CHARS, REDLINE_PROMPT_RATIONALE_RESERVE_CHARS)` — **the one LLM call**.
     - `_account(result, cb)`.
     - If `result is None` → `clause_updates[clause_id] = {"suggested_rewrite": None}` (explicit None — AC-18/19); `counts["failed"] += 1`; `rewrite_len, is_noop = 0, False`; log warning. Else → `rewrite = result[:REDLINE_REWRITE_MAX_CHARS]` (log debug if truncated — AC-21); `clause_updates[clause_id] = {"suggested_rewrite": rewrite}`; `counts["rewritten"] += 1`; `rewrite_len = len(rewrite)`; `is_noop = (rewrite.strip() == text.strip())`; if `is_noop`: `counts["noop"] += 1`.
     - Per-clause structured log — reached ONLY via the `draft_rewrite` path. **DO NOT log the rewrite text** (up to 4000 chars). Log only: `clause_id`, `risk_level` (the finding's `.value` — feeds spec §9 metric 4), `rewrite_len`, `success=(result is not None)`, `is_noop`, `circuit_open=cb["open"]` (spec §9).
  6. `elapsed = time.monotonic() - start_time`. Emit an aggregate metrics log via `logger.info("RedlineAgent completed", extra={**counts, "circuit_opened": cb["tripped"], "elapsed_seconds": round(elapsed, 4)})` — fires UNCONDITIONALLY, including `clause_updates == {}` (spec §9; AC-16 info line).
  7. `out = {"clauses": clause_updates, "current_node": current_node, "node_timings": {current_node: elapsed}}`; if `cb["tripped"]`: `out["error_count"] = 1`; return `out`.
- [ ] **`_account(result, cb)`** — circuit bookkeeping (identical shape to `risk_score_agent.py:219-243`): if `result is None`: `cb["consecutive_failures"] += 1`; if `cb["consecutive_failures"] >= REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD and not cb["open"]` → `cb["open"] = True`, `cb["tripped"] = True`, log ONE "circuit opened" warning. Else (a real rewrite string): `cb["consecutive_failures"] = 0`. **`_account` is called ONLY from the `draft_rewrite` path (step 5) — never from the empty-text or bulk-skip paths** (AC-20a).
- [ ] **`_clause_type_value(raw) -> Optional[str]`**: `raw.value if isinstance(raw, ClauseType) else (raw if isinstance(raw, str) else None)` — identical to Node 4/5's helper — so `draft_rewrite` receives a plain string label (or `None`).
- [ ] **Key invariants** (make them hold by construction):
  - Eligible + attempted clauses always get the `suggested_rewrite` key — a non-empty string on success, an explicit `None` on any failure/skip (spec §2.2 states 2/3), so the reducer clears any stale re-run value (AC-25 / R3).
  - Ineligible / below-threshold / discarded clauses are NEVER added to `clause_updates` (key stays absent), no LLM call (AC-9/10).
  - `risk_level`, `risk_rationale`, and all Self-RAG/CRAG/Ingest fields are never modified (AC-27) — the node writes only `suggested_rewrite`.
  - `error_count` increments **at most once per run**, only when the breaker opens (AC-23).
  - Only `draft_rewrite`-issuing failures move the consecutive counter; zero-LLM skip paths are circuit-neutral (AC-20a).
- [ ] **Pinned `current_node`**: the literal `"redline"` (spec §2.2) — also the `node_timings` key and the graph node name in Task 8. `skip_redline` pins `"skip_redline"`. Do NOT derive them.

**Verify**: Run `python -m pytest tests/unit/test_redline_agent.py -v` — all 31 tests must PASS.

---

## Task 8: Wire the two nodes + conditional edge into the graph builder

- [ ] Open `app/graph/builder.py`
- [ ] Add the import: `from app.graph.nodes.redline_agent import route_on_risk, redline_agent, skip_redline`
- [ ] **Replace** the temporary `graph.add_edge("risk_score", END)` line (`builder.py:103`) with the two new nodes and the `route_on_risk` conditional edge:

```python
# ── Node 6: route_on_risk (conditional edge) → RedlineAgent / SkipRedline ──────
# Constitution §2: the SECOND of the two permitted domain conditional edges (the
# first is CRAG's confidence routing, Node 3, realized as internal per-clause
# branching). Unlike CRAG, route_on_risk is a DOCUMENT-LEVEL decision that routes the
# whole ContractState to one successor, so it IS a genuine graph-level
# add_conditional_edges (spec §7.1). RedlineAgent does per-clause filtering internally
# via the same is_redline_eligible predicate route_on_risk uses (spec §7.2). The node
# names "redline" / "skip_redline" match the pinned current_node values (spec §2) so
# state-key identity never drifts from the graph node name (constitution §8).
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

- [ ] Update the module docstring "Current scope" note (`builder.py:4-10`) to include Node 6 and move the "→ END temporarily" placeholder to the two Node-6 branches (the Node-5 comment on the risk_score edge no longer applies — that edge is now the conditional edge).
- [ ] Leave `route_after_ingest` (the ingest error-guard `add_conditional_edges`, `builder.py:44`) unchanged — it is a non-domain guard, not one of the two domain conditional edges (its own comment already says so).

**Verify**: Run from `backend/`:
```
python -c "from app.graph.builder import build_graph; g = build_graph(); print(type(g))"
```
Should print the compiled graph type without errors.

---

## Task 9: Write and run integration tests

- [ ] Create file `tests/integration/test_redline_graph.py`
- [ ] Tests exercise the compiled graph through Node 6. `draft_rewrite` is **mocked** (no live Ollama); upstream `final_status` / `risk_level` are either produced by the real upstream nodes with their LLM boundaries mocked, or injected as a pre-built `clauses` fixture invoked starting at RiskScore/Redline.
- [ ] **CRITICAL — patch targets**: patch `app.graph.nodes.redline_agent.draft_rewrite` — i.e. **on the node module** (the node did `from ...redline_drafter import draft_rewrite`, binding the name locally). Also mock the upstream LLM/embed/web boundaries (`self_rag_validation_agent.check_relevance/.check_isrel/.check_issup`, ClauseSplitter's `ollama.chat`, CRAG's `embed_query`/`web_search`, and `risk_score_agent.score_risk`) as in the 005/006/007 integration tests (see `test_risk_score_graph.py:4-27` for the patch-where-bound note), OR inject a hand-built `clauses` dict (with `final_status` + `risk_level` set).
- [ ] Write these 7 test functions (plan §2 matrix):

| Test function | Verifies |
|---------------|----------|
| `test_graph_routes_to_redline_and_ends` | A doc with an eligible finding routes through `redline` to END; `current_node == "redline"`; that clause carries a non-empty `suggested_rewrite` (AC-30/31) |
| `test_graph_routes_to_skip_redline_and_ends` | An all-`DISCARDED` doc routes through `skip_redline` to END; `current_node == "skip_redline"`; no clause has a `suggested_rewrite` (AC-2/28) |
| `test_graph_ingest_error_skips_to_end` | Ingest error short-circuits to END without reaching Node 6; assert `assert not final_state.get("clauses")` (KeyError caution below) |
| `test_graph_mixed_only_eligible_rewritten` | Mixed fixture: eligible clauses get `suggested_rewrite`; ineligible/discarded keep it absent; `risk_level` unchanged everywhere (AC-9/10/27) |
| `test_graph_circuit_open_sets_error_count` | Forcing all `draft_rewrite` calls to return None opens the breaker → final state `error_count == 1`, remaining eligible clauses have `suggested_rewrite is None` (AC-20/23) |
| `test_graph_has_only_expected_conditional_edges` | Inspect `build_graph().get_graph()`: `risk_score` branches to exactly `{redline, skip_redline}`; no `add_conditional_edges` exists for `crag_retrieval` (it stays internal); the ingest guard is the only other conditional source (AC-32) |
| `test_graph_checkpointing_after_redline` | State checkpointed after Node 6. Build the test's **own** graph with a checkpointer (`SqliteSaver.from_conn_string(":memory:")`, wrapped in `try/except ImportError → pytest.skip`) because `build_graph()` compiles with no checkpointer (`builder.py:106`). The own subgraph MUST wire Node 6 end-to-end (`risk_score → route_on_risk → {redline, skip_redline} → END`), **NOT** copy 007's `risk_score → END` verbatim (which would checkpoint after RiskScore, not Redline); assert `compiled.get_state(thread_cfg)` is retrievable and its `current_node` is `redline`/`skip_redline`. Mirrors `test_risk_score_graph.py:247-312` |

- [ ] **KeyError caution** (`test_graph_ingest_error_skips_to_end`): `clauses` is an `Annotated[dict, merge_nested_clause_dicts]` channel with no default; on the error short-circuit it is never written, so `final_state["clauses"]` raises `KeyError`. Assert `assert not final_state.get("clauses")` instead (same subtlety noted in 004/005/006/007).
- [ ] For `test_graph_routes_to_redline_and_ends`: mock `score_risk` to return `(RiskLevel.HIGH, "...")` (so the finding is eligible) and `draft_rewrite` to return `"safer text"`; assert the eligible clause's `suggested_rewrite == "safer text"`.
- [ ] For `test_graph_routes_to_skip_redline_and_ends`: drive Self-RAG to `DISCARDED` for all clauses (`check_issup` → False, or inject `final_status=DISCARDED`); assert `draft_rewrite` `assert_not_called()` and no clause has `suggested_rewrite`.
- [ ] For `test_graph_has_only_expected_conditional_edges`: use `build_graph().get_graph()` and assert the conditional branch source set is `{"ingest_agent", "risk_score"}` (guard + route_on_risk) and that `risk_score`'s successors are exactly `{"redline", "skip_redline"}`. `crag_retrieval` and `self_rag_validation` must have plain linear successors only.

**Verify**: Run `python -m pytest tests/integration/test_redline_graph.py -v` — all 7 tests must PASS (checkpointing may skip if the SQLite saver import path is unavailable — acceptable).

---

## Task 10: Full test suite pass + terminal-node regression fix-ups

- [ ] Run the complete suite:
```
python -m pytest tests/ -v --tb=short
```
- [ ] All existing IngestAgent (003), ClauseSplitterAgent (004), CRAG (005), Self-RAG (006), and RiskScore (007) unit tests must still pass — Node 6 must not regress them.
- [ ] **Regression caution — the tail edge moved AGAIN (read fully).** The previously-terminal `risk_score → END` edge is now `risk_score → route_on_risk → {redline, skip_redline} → END`. Every integration test that invokes the real `build_graph()` and runs to END currently asserts `current_node == "risk_score"` on the assumption that RiskScore is terminal. That assumption is now false. These failures are **EXPECTED and benign**: the graph still reaches END, and because `ollama.Client` is globally patched, the new `draft_rewrite` calls simply fail-safe (they do not hit real Ollama). Do **NOT** treat the red as a bug and do **NOT** weaken these assertions (constitution §7) — **update** each to the new terminal node.
- [ ] **New terminal is `"redline"` for all six affected assertions (across five files — `test_clause_splitter_graph.py` has two, `:69` and `:115`)** — each affected test validates every clause (`check_issup=True` / `_all_true`), so under the resolved threshold `{LOW, MEDIUM, HIGH}` every finding is eligible and routes to `redline`. (Even where `score_risk` fail-safes to `HIGH` under the global mock, `HIGH` is eligible.) Change `"risk_score"` → `"redline"` at:
  - `tests/integration/test_ingest_graph.py:59` (and fix the comment at `:58` — "Node 5 is the terminal node after feature-007" → Node 6 / redline after feature-008)
  - `tests/integration/test_clause_splitter_graph.py:69` (and comment `:68`) and `:115` (and comment `:114`)
  - `tests/integration/test_crag_retrieval_graph.py:93`
  - `tests/integration/test_self_rag_validation_graph.py:103` (in `test_graph_reaches_self_rag_and_ends`)
  - `tests/integration/test_risk_score_graph.py:98` (in `test_graph_reaches_risk_score_and_ends` — this 007 test mocks `score_risk` → `(RiskLevel.HIGH, ...)`, so the finding is eligible → `redline`)
- [ ] **Do NOT change the two self-contained subgraph tests** — they wire their own terminal edge and are genuinely correct as-is:
  - `tests/integration/test_self_rag_validation_graph.py:299` (006 checkpointing case builds `self_rag_validation → END` at line 279 → `current_node == "self_rag_validation"` stays correct).
  - `tests/integration/test_risk_score_graph.py:309` (007 checkpointing case builds its own subgraph `risk_score → END` → `current_node == "risk_score"` stays correct).
- [ ] Verify line numbers before editing (they may have drifted) by grepping `current_node.*risk_score` across `tests/integration/`. After the updates, the only diffs from these files should be the terminal-node string (`risk_score` → `redline`) and the two comments.
- [ ] Expected NEW test count for feature 008: 6 (config) + 15 (drafter) + 31 (node: 7 route + 22 redline + 2 skip) + 7 (integration) = **59 new tests**.
- [ ] OCR-gated IngestAgent tests may skip if Tesseract is absent — acceptable. No Redline test requires Tesseract, a live Ollama, or network.

---

## Task 11: Linting and type checking

- [ ] Run `black app/ tests/` — auto-format.
- [ ] Run `ruff check app/ tests/` — no lint errors.
- [ ] Run `mypy app/` — no type errors (if mypy is installed). `ollama`/`httpx` are already used elsewhere; add narrow `# type: ignore[...]` only if genuinely needed — do NOT broaden.
- [ ] Do NOT weaken tests to satisfy lint/type checks — fix the implementation instead (constitution §7).

---

## Task 12: Manual live smoke test (optional, not in automated suite)

- [ ] Ensure Ollama is running with `qwen3:14b` (`ollama pull qwen3:14b`). NOTE (per project memory): the current dev box OOMs on live `qwen3:14b` — this step may not be runnable here; the automated suite (Task 10) is fully mocked and must pass regardless.
- [ ] Run the full graph (Node 1→6) on a real multi-clause contract with live Ollama.
- [ ] Confirm: a doc with risky findings routes to `redline` and each eligible finding carries a non-empty `suggested_rewrite`; a benign (all-discarded) doc routes to `skip_redline` with no rewrites; a fail-safed clause (if any) shows `suggested_rewrite is None` while keeping its `risk_level`; per-clause latency is well under `REDLINE_TIMEOUT_SECONDS`; `error_count` is absent unless the breaker opened.
- [ ] Record the route decision, redline rate, no-op/echo rate, and level→route breakdown (spec §9) — use them to consider tuning `REDLINE_RISK_THRESHOLD` (toward `{MEDIUM, HIGH}`?), the rewrite prompt, and `REDLINE_REWRITE_MAX_CHARS`.

**Why**: The automated suite mocks the drafter, so this is the only step that validates real Qwen3 rewrite quality, prompt wording, and the true latency envelope (plan §6 risks).

---

## Summary of all files created/modified

| # | File | Action |
|---|------|--------|
| 1 | `app/config.py` | MODIFIED (add 6 Redline constants — no new import; `RiskLevel` already imported) |
| 2 | `app/graph/nodes/drafters/__init__.py` | NEW (package marker, no logic) |
| 3 | `app/graph/nodes/drafters/redline_drafter.py` | NEW (`draft_rewrite`) |
| 4 | `app/graph/nodes/redline_agent.py` | NEW (`is_redline_eligible`, `route_on_risk`, `redline_agent`, `skip_redline`, `_account`, `_clause_type_value`) |
| 5 | `app/graph/builder.py` | MODIFIED (add 2 nodes + `route_on_risk` conditional edge; replace `risk_score → END`) |
| 6 | `tests/unit/test_config.py` | MODIFIED (+6 tests) |
| 7 | `tests/unit/test_redline_drafter.py` | NEW (15 tests) |
| 8 | `tests/unit/test_redline_agent.py` | NEW (31 tests: 7 route + 22 redline + 2 skip) |
| 9 | `tests/integration/test_redline_graph.py` | NEW (7 tests) |
| 10 | `tests/integration/test_ingest_graph.py` | MODIFIED (Task 10 regression: terminal-node assertion `:59` + comment `:58`) |
| 11 | `tests/integration/test_clause_splitter_graph.py` | MODIFIED (Task 10 regression: terminal-node assertions `:69`, `:115` + comments) |
| 12 | `tests/integration/test_crag_retrieval_graph.py` | MODIFIED (Task 10 regression: terminal-node assertion `:93`) |
| 13 | `tests/integration/test_self_rag_validation_graph.py` | MODIFIED (Task 10 regression: terminal-node assertion `:103` only — NOT `:299`) |
| 14 | `tests/integration/test_risk_score_graph.py` | MODIFIED (Task 10 regression: terminal-node assertion `:98` only — NOT `:309`) |

> Files 10–14 are **expected regression fix-ups**, not new feature code — the tail edge moving from `risk_score → END` to `risk_score → route_on_risk → {redline, skip_redline} → END` invalidates their "RiskScore is terminal" assertion (see Task 10). All six assertions (across these five files — `test_clause_splitter_graph.py` has two) swap `"risk_score"` → `"redline"` because every affected test validates all clauses.

---

## Acceptance-criteria traceability (spec §3 → tasks)

| Spec §3 criterion | Covered by |
|-------------------|-----------|
| **route_on_risk** | |
| 1. Routes to `redline` when eligible exists | Task 6/7 (`test_route_redline_when_eligible_exists`), Task 9 (`test_graph_routes_to_redline_and_ends`) |
| 2. Routes to `skip_redline` when none | Task 6/7 (`test_route_skip_when_none_eligible`), Task 9 (`test_graph_routes_to_skip_redline_and_ends`) |
| 3. Empty clauses → `skip_redline` | Task 6/7 (`test_route_skip_empty_clauses`) |
| 4. `ingest_error` → `skip_redline` | Task 6/7 (`test_route_skip_on_ingest_error`) |
| 5. Ignores discarded clauses | Task 6/7 (`test_route_ignores_discarded_with_risk_level`) |
| 6. Threshold read from config | Task 1 (`test_redline_threshold_is_all_levels`), Task 6/7 (`test_route_threshold_from_config`) |
| 7. Pure function, no mutation | Task 6/7 (`test_route_does_not_mutate_state`) |
| **RedlineAgent** | |
| 8. Eligible clauses get a rewrite | Task 6/7 (`test_eligible_clauses_get_rewrite`), Task 9 (`test_graph_routes_to_redline_and_ends`) |
| 9. Non-eligible validated untouched | Task 6/7 (`test_below_threshold_untouched_no_llm`), Task 9 (`test_graph_mixed_only_eligible_rewritten`) |
| 10. Discarded / None untouched | Task 6/7 (`test_discarded_and_none_untouched_no_llm`), Task 9 (`test_graph_mixed_only_eligible_rewritten`) |
| 11. One LLM call per eligible clause | Task 6/7 (`test_one_llm_call_per_eligible_clause`) |
| 12. Generative model, not embedding | Task 1 (`test_redline_uses_generative_model`), Task 4/5 (`test_uses_generative_model_only`), Task 6/7 (`test_uses_generative_not_embedding_model`) |
| 13. Uses configured constants | Implicit — a hardcoded value breaks `test_circuit_breaker_opens` / `test_route_threshold_from_config` / `test_rewrite_truncated` (all monkeypatch the re-exposed names) |
| 14. Defensive `ingest_error` check | Task 6/7 (`test_ingest_error_returns_empty`), Task 9 (`test_graph_ingest_error_skips_to_end`) |
| 15. Empty clauses input | Task 6/7 (`test_empty_clauses_returns_empty`) |
| 16. No redline-eligible findings | Task 6/7 (`test_no_eligible_findings_zero_llm`) |
| 17. Partial update only | Task 6/7 (`test_partial_update_only_no_error_count`) |
| 18. Graceful drafting failure (fail-safe None) | Task 6/7 (`test_graceful_failure_emits_none`) |
| 19. Malformed / empty output | Task 4/5 (`test_empty_rewrite_returns_none`, `test_malformed_json_returns_none`), Task 6/7 (`test_empty_output_emits_none`) |
| 20. LLM circuit breaker | Task 6/7 (`test_circuit_breaker_opens`, `test_circuit_resets_on_success`), Task 9 (`test_graph_circuit_open_sets_error_count`) |
| 20a. Only LLM-issuing failures move counter | Task 6/7 (`test_empty_text_findings_are_circuit_neutral`, `test_empty_text_eligible_emits_none`) |
| 21. Rewrite truncation | Task 6/7 (`test_rewrite_truncated`) |
| 22. Prompt truncation | Task 4/5 (`test_prompt_truncated_to_max_chars`, `test_long_clause_preserves_rationale`) |
| 23. Circuit-open health signal | Task 6/7 (`test_circuit_open_emits_error_count_once`), Task 9 (`test_graph_circuit_open_sets_error_count`) |
| 24. `current_node` pinned | Task 6/7 (`test_current_node_pinned`) |
| 25. Re-run overwrite | Task 6/7 (`test_rerun_overwrites_rewrite`) |
| 26. Empty evidence still drafts | Task 4/5 (`test_empty_evidence_drafts_on_text`), Task 6/7 (`test_empty_evidence_eligible_still_drafts`) |
| 27. Does not modify upstream fields | Task 6/7 (`test_upstream_fields_untouched`), Task 9 (`test_graph_mixed_only_eligible_rewritten`) |
| **SkipRedline** | |
| 28. Passthrough update only | Task 6/7 (`test_skip_passthrough_only`), Task 9 (`test_graph_routes_to_skip_redline_and_ends`) |
| 29. No clause mutation | Task 6/7 (`test_skip_no_clause_mutation`) |
| **Graph wiring** | |
| 30. `route_on_risk` is a graph-level conditional edge | Task 8, Task 9 (`test_graph_routes_to_redline_and_ends`, `test_graph_has_only_expected_conditional_edges`) |
| 31. Both branches converge downstream | Task 8, Task 9 (`test_graph_routes_to_redline_and_ends`, `test_graph_routes_to_skip_redline_and_ends`) |
| 32. Only two domain conditional edges exist | Task 9 (`test_graph_has_only_expected_conditional_edges`) |
