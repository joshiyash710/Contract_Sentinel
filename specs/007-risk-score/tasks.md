# RiskScore Implementation Tasks

Reference documents:
- Spec: `specs/007-risk-score/spec.md`
- Plan: `specs/007-risk-score/plan.md`
- State schema: `specs/001-contract-state-schema.md`
- Tech stack: `specs/002-tech-stack.md`
- Constitution: `specs/000-constitution.md`

All file paths below are relative to `backend/` unless stated otherwise.

**Workflow reminders:**
- Follow TDD per constitution §7 — write tests, confirm they FAIL, then implement to make them PASS.
- Node returns ONLY the state keys it updates per constitution §5 (Partial-Update Rule): `clauses`, `current_node`, `node_timings` — **plus `error_count: 1` in the one case the circuit breaker opens** (spec §4.5 / §7.4 / AC-15). Never any other key.
- All thresholds live in `app/config.py` per constitution §3 — never hardcode inline.
- Model separation (constitution §8): every RiskScore LLM call uses the **generative** `OLLAMA_MODEL_NAME` (Qwen3). RiskScore makes NO vector calls and MUST NEVER reference `OLLAMA_EMBED_MODEL_NAME`.
- The seven locked design decisions (spec §8a): **R1** fail-safe default = `HIGH` on any unrecoverable failure; **R2** `RiskLevel` stays `LOW`/`MEDIUM`/`HIGH` (no "clean" outcome); **R3** empty/whitespace text → fail-safe default (skip LLM); **R4** no document-level roll-up; **R5** pure-LLM single call, `clause_type` as soft context; **R6** no retry loop (no `RISK_SCORE_MAX_ATTEMPTS`); **R7** state-key name `"risk_score"`.
- Scope gate: **only** clauses with `final_status == ValidationStatus.VALIDATED` are scored. `DISCARDED` / `None` are skipped — no LLM call, not returned, left untouched by the reducer.
- **Circuit-neutrality (AC-14a)**: only paths that actually issued a `score_risk` LLM call and got `None` back move the consecutive-failure counter. The empty-text skip and the post-open bulk default reach the fail-safe level **without** an LLM call and must NOT touch the counter.
- Branch: `feature/007-risk-score` per constitution §11.

---

## Task 0: Create feature branch

- [ ] From an up-to-date `main`, create and check out `feature/007-risk-score`

**Why**: Per constitution §11, every feature is developed on its own branch. Self-RAG validation (006) is already merged to `main`.

**Verify**: `git branch --show-current` prints `feature/007-risk-score`.

**Note**: The working tree currently has an untracked `specs/007-risk-score/` (spec.md, plan.md, tasks.md) and an untracked `eval/` directory at the repo root. Confirm with the user whether the spec docs should be committed before branching, so 007 starts from a clean tree.

---

## Task 1: Write config tests for the RiskScore constants (confirm FAILING)

- [ ] Open `tests/unit/test_config.py`
- [ ] Add 5 new test functions for the RiskScore constants, the default level, the no-retry guarantee, and model separation:

```python
def test_risk_score_constants_match_spec():
    """Verify RiskScore numeric constants match specs/007 §6."""
    from app.config import (
        RISK_SCORE_TIMEOUT_SECONDS,
        RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD,
        RISK_SCORE_PROMPT_MAX_CHARS,
        RISK_RATIONALE_MAX_CHARS,
    )
    assert RISK_SCORE_TIMEOUT_SECONDS == 120
    assert RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD == 5
    assert RISK_SCORE_PROMPT_MAX_CHARS == 6000
    assert RISK_RATIONALE_MAX_CHARS == 1000


def test_risk_score_constants_correct_types():
    """int for the numeric constants."""
    from app import config
    assert isinstance(config.RISK_SCORE_TIMEOUT_SECONDS, int)
    assert isinstance(config.RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD, int)
    assert isinstance(config.RISK_SCORE_PROMPT_MAX_CHARS, int)
    assert isinstance(config.RISK_RATIONALE_MAX_CHARS, int)


def test_risk_score_default_level_is_high():
    """Fail-safe default is RiskLevel.HIGH (spec §8a R1)."""
    from app.config import RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE
    from app.graph.state import RiskLevel
    assert RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE is RiskLevel.HIGH
    assert isinstance(RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE, RiskLevel)


def test_risk_score_no_max_attempts_constant():
    """No retry loop for RiskScore (spec §8a R6) — the constant must not exist."""
    from app import config
    assert not hasattr(config, "RISK_SCORE_MAX_ATTEMPTS")


def test_risk_score_uses_generative_model():
    """Constitution §8: the generative model is distinct from the embedding model."""
    from app.config import OLLAMA_MODEL_NAME, OLLAMA_EMBED_MODEL_NAME
    assert OLLAMA_MODEL_NAME != OLLAMA_EMBED_MODEL_NAME
    assert OLLAMA_MODEL_NAME == "qwen3:14b"
```

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — `test_risk_score_constants_match_spec`, `test_risk_score_constants_correct_types`, and `test_risk_score_default_level_is_high` must FAIL (`ImportError` — the new constants don't exist yet). `test_risk_score_no_max_attempts_constant` and `test_risk_score_uses_generative_model` may already PASS. Existing config tests (Ingest + ClauseSplitter + CRAG + Self-RAG) must still PASS.

---

## Task 2: Add the RiskScore constants to config

- [ ] Open `app/config.py`
- [ ] **Add the import** `from app.graph.state import RiskLevel` near the top of the module. This is the module's **first and only** import — verified acyclic: `app.graph.state` imports only stdlib (`typing`, `enum`, `operator`) and the `app` / `app.graph` package `__init__.py` are empty stubs, so `app.config → app.graph.state` never cycles back to `app.config`.
- [ ] Append a new `# ── RiskScore thresholds` block at the end of the file (pure addition — no rename, no placeholder to replace):

```python
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

- [ ] The node reuses the existing `OLLAMA_MODEL_NAME` — introduce no new model constant. Do NOT add `RISK_SCORE_MAX_ATTEMPTS` (spec §8a R6).

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — all config tests (Ingest + ClauseSplitter + CRAG + Self-RAG + RiskScore) must now PASS.

---

## Task 3: Create the scorers package marker (no dedicated TDD cycle)

- [ ] Create directory `app/graph/nodes/scorers/`
- [ ] Create file `app/graph/nodes/scorers/__init__.py` — a package marker with a module docstring only (no logic, nothing to export):

```python
"""
Scorer modules for the RiskScore node (Node 5).

risk_scorer.py assigns Low/Medium/High severity to a validated finding via a
single generative LLM call. Unlike validators/__init__.py, this package init
hosts no shared helper — risk_scorer.py reuses format_evidence from the
validators package (a dependency-free renderer of the 001 evidence shape) rather
than redefining it.
"""
```

**Why**: mirrors the `validators/` / `retrievers/` package layout. The evidence formatter is reused, not duplicated, so there is no helper here and no test for this file.

**Verify**: Run from `backend/`:
```
python -c "import app.graph.nodes.scorers; print('ok')"
```

---

## Task 4: Write unit tests for `score_risk` (confirm FAILING)

- [ ] Create file `tests/unit/test_risk_scorer.py`
- [ ] The import `from app.graph.nodes.scorers.risk_scorer import score_risk` will fail until Task 5 — expected for TDD.
- [ ] **Mocking strategy (name the target)**: patch `ollama.Client` at `app.graph.nodes.scorers.risk_scorer.ollama.Client` (equivalently `patch("ollama.Client")` since `risk_scorer.py` does `import ollama`). Configure `mock_client.return_value.chat.return_value = {"message": {"content": '{"risk_level": "high", "rationale": "x"}'}}`. Assert on `mock_client.call_args` that it was constructed with `timeout=<passed timeout_seconds>` (the correctness hinge from Task 5) and on `.chat.call_args` for `model=OLLAMA_MODEL_NAME` and `format="json"`. **No real Ollama.**
- [ ] Write these 15 test functions (plan §2 scorer matrix):

| Test function | Verifies |
|---------------|----------|
| `test_parses_high_medium_low` | `{"risk_level": "high"/"medium"/"low"}` → `RiskLevel.HIGH/MEDIUM/LOW` (parametrized) |
| `test_level_case_and_whitespace_insensitive` | `{"risk_level": " HIGH "}` → `RiskLevel.HIGH` |
| `test_returns_rationale` | The `rationale` string is returned alongside the level (as a `(level, rationale)` tuple) |
| `test_timeout_returns_none` | Simulated timeout (`concurrent.futures.TimeoutError` / `httpx.TimeoutException`) → `None`, warning logged |
| `test_connection_error_returns_none` | Ollama unreachable (`ConnectionError`/`httpx.ConnectError`) → `None` |
| `test_malformed_json_returns_none` | Non-JSON `content` → `None` |
| `test_missing_risk_level_returns_none` | JSON without a `risk_level` key → `None` |
| `test_invalid_level_string_returns_none` | `{"risk_level": "critical"}` → `None` (not a `RiskLevel`) (AC-13) |
| `test_non_string_level_returns_none` | `{"risk_level": 3}` → `None` |
| `test_uses_generative_model_only` | `chat` called with `model=OLLAMA_MODEL_NAME`; `OLLAMA_EMBED_MODEL_NAME` never referenced (AC-6) |
| `test_prompt_truncated_to_max_chars` | Oversized clause text + evidence is truncated so the prompt input is bounded by `prompt_max_chars` (AC-19) |
| `test_empty_evidence_scores_on_text` | `evidence_snippets=None`/`[]` → uses the text-only prompt variant; still returns a `(level, rationale)` on a valid response; no crash (AC-20) |
| `test_clause_type_included_in_prompt` | A provided `clause_type` label appears in the built prompt; `None` → "unspecified" wording |
| `test_scorer_never_raises` | Any injected exception inside the call → `None`, nothing propagates |
| `test_rationale_returned_untruncated` | The scorer returns the full rationale (the NODE applies `RISK_RATIONALE_MAX_CHARS`, not the scorer) |

- [ ] For `test_prompt_truncated_to_max_chars`: capture the prompt actually sent (from `.chat.call_args` → `messages[0]["content"]`) and assert the **combined** clause+evidence variable portion is bounded by `prompt_max_chars` (the combined-budget rule from Task 5: `len(clause_trunc) + len(evidence_str) <= prompt_max_chars`). Use oversized clause text AND oversized evidence so independent truncation would exceed the budget but the combined rule does not.
- [ ] Warning assertions use pytest's `caplog` at `WARNING`.

**Verify**: Run `python -m pytest tests/unit/test_risk_scorer.py -v` — all 15 tests must FAIL (ImportError). Confirms the TDD cycle.

---

## Task 5: Implement `score_risk`

- [ ] Create file `app/graph/nodes/scorers/risk_scorer.py`
- [ ] **Imports**: `concurrent.futures`, `json`, `logging` (stdlib); `from typing import List, Dict, Any, Optional, Tuple`; `httpx` (timeout type); `ollama`; `from app.graph.state import RiskLevel`; `from app.graph.nodes.validators import format_evidence`. No `app.config` import (all limits passed in).
- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.risk_score.scorer")`
- [ ] Public interface — returns `Optional[Tuple[RiskLevel, str]]`, **never raises** (`None` = un-runnable → the node fail-safes and counts it toward the circuit breaker):

```python
def score_risk(clause_text: str,
               evidence_snippets: "Optional[List[Dict[str, Any]]]",
               clause_type: "Optional[str]",
               timeout_seconds: int, model_name: str,
               prompt_max_chars: int) -> "Optional[Tuple[RiskLevel, str]]":
    """Single generative call assigning Low/Medium/High severity to a validated
    finding, plus a short rationale. evidence_snippets (001 shape) is scoring
    context when present; may be []/None (Self-RAG rescue path) → judge on clause
    text + clause_type alone. clause_type is a normalized string label (or None).
    Returns (RiskLevel, rationale) or None on any failure. Never raises."""
```

- [ ] **Shared invocation core** — a private `_run_scoring(prompt, timeout_seconds, model_name) -> Optional[Tuple[RiskLevel, str]]` via `_call_ollama` + `_parse_score`. Mirrors `reflectors.py:157-217`.
- [ ] **CRITICAL — client-level timeout is the primary bound (plan §5)**: the call MUST go through `ollama.Client(timeout=timeout_seconds).chat(model=model_name, messages=[{"role":"user","content":prompt}], format="json", options={"num_predict": 384})`, run inside a `concurrent.futures.ThreadPoolExecutor(max_workers=1)` with `future.result(timeout=timeout_seconds)` — exactly the `reflectors._run_judgment` / `llm_refiner.refine_with_llm` pattern. Do NOT use a bare `ollama.chat` bounded only by the executor: on a hung Ollama socket the worker thread would stay blocked and `shutdown(wait=True)` at `with` exit would hang, defeating both `RISK_SCORE_TIMEOUT_SECONDS` and the circuit breaker. `num_predict` is 384 (a little larger than the reflectors' 256) because the response carries a short rationale, not just a bool.
- [ ] **Score parsing** (`_parse_score`) — parse `response["message"]["content"]` as JSON, then:
  - `level_raw = data.get("risk_level")`. If not a `str` → return `None`. Else `try: level = RiskLevel(level_raw.strip().lower())` — on `ValueError` (value not one of `low`/`medium`/`high`) → return `None` (AC-13/22).
  - `rationale = str(data.get("rationale") or "")` — returned **untruncated** (the node applies `RISK_RATIONALE_MAX_CHARS`).
  - Return `(level, rationale)`.
  - Non-JSON body, or missing `risk_level` → `None`.
- [ ] **Failure handling** — catch `concurrent.futures.TimeoutError`, `httpx.TimeoutException`, and any `Exception` → log a rate-limited WARNING and return `None`. Never raise.
- [ ] **Prompt construction & truncation — COMBINED budget (spec §4.8, same rule as the reflectors)** — clause text + evidence together bounded by `prompt_max_chars`, NOT each independently:
  ```python
  clause_trunc = clause_text[:prompt_max_chars]
  remaining = max(0, prompt_max_chars - len(clause_trunc))
  evidence_str = format_evidence(evidence_snippets, remaining)   # "" when empty/None
  # → len(clause_trunc) + len(evidence_str) <= prompt_max_chars, guaranteed
  ```
- [ ] **Prompt content** — one template with an evidence-present and an evidence-absent variant (mirroring `_ISSUP_WITH_EVIDENCE_PROMPT` / `_ISSUP_TEXT_ONLY_PROMPT` in `reflectors.py`). Both:
  - State the rubric: **low** = minor / standard deviation; **medium** = a materially one-sided or non-standard term; **high** = a severe, uncapped, or unilateral risk.
  - Insert `clause_type` as soft context: `This clause is categorized as: {clause_type or "unspecified"}`.
  - Instruct the model to reply with ONLY `{"risk_level": "low"|"medium"|"high", "rationale": "<one or two sentences>"}` — no markdown.
  - The evidence-absent variant states no retrieved evidence is available and to judge on the clause text alone.
  The exact wording is tunable later without changing control flow.

**Verify**: Run `python -m pytest tests/unit/test_risk_scorer.py -v` — all 15 tests must PASS.

---

## Task 6: Write unit tests for the `risk_score_agent` node (confirm FAILING)

- [ ] Create file `tests/unit/test_risk_score_agent.py`
- [ ] **Mocking strategy**: patch `score_risk` **at the node module level** (`app.graph.nodes.risk_score_agent.score_risk`), because the node does `from ...risk_scorer import score_risk` — binding the name into the node module. Patching `scorers.risk_scorer.score_risk` would NOT affect the node. Give the mock a `side_effect` list (or `return_value`) so results are deterministic per call, and assert call counts.
- [ ] Helper: `make_state(clauses, ingest_error=None, document_id="doc-1")` returning a minimal state dict. Clause records carry at least `{text, position, final_status, evidence_snippets, clause_type}`. Provide builders for the common shapes: a VALIDATED finding (with evidence), a VALIDATED finding with empty evidence, a DISCARDED clause, a `final_status=None` clause, and a VALIDATED finding with empty text.
- [ ] Use `RiskLevel` and `ValidationStatus` from `app.graph.state` in fixtures; `score_risk` mock returns `(RiskLevel.X, "rationale")` tuples or `None`.
- [ ] Write these 24 test functions (plan §2 node matrix):

| Test function | Verifies |
|---------------|----------|
| `test_validated_findings_scored` | Every `VALIDATED` clause ends with `risk_level ∈ {LOW,MEDIUM,HIGH}` and non-empty `risk_rationale` (AC-1) |
| `test_discarded_untouched_no_llm` | `DISCARDED` clause: `risk_level`/`risk_rationale` stay absent; **no** `score_risk` call (AC-2) |
| `test_final_status_none_skipped` | `final_status is None` clause skipped, no call (AC-3) |
| `test_level_echoes_judgment` | Mock returns HIGH/MEDIUM/LOW → clause gets that level (parametrized) (AC-4) |
| `test_only_validated_incur_llm_calls` | `score_risk` call count == number of `VALIDATED` clauses (AC-5) |
| `test_uses_generative_not_embedding_model` | `score_risk` invoked with `OLLAMA_MODEL_NAME`; `OLLAMA_EMBED_MODEL_NAME` never referenced by the node (AC-6) |
| `test_ingest_error_returns_empty` | `ingest_error` set → empty update; no `score_risk` calls (AC-8) |
| `test_empty_clauses_returns_empty` | `clauses == {}` → empty update, warning, no calls (AC-9) |
| `test_no_validated_findings_zero_llm` | All-`DISCARDED` doc → empty `clauses` update, zero calls, info log (AC-10) |
| `test_partial_update_only_no_error_count` | Non-outage run → keys exactly `{clauses, current_node, node_timings}`; NO `error_count` (AC-11) |
| `test_graceful_llm_failure_failsafe_high` | `score_risk` → None → clause gets default `HIGH`, `[auto]` rationale, no crash, other clauses proceed; `error_count` NOT incremented for a single failure (AC-12) |
| `test_malformed_output_failsafe` | `score_risk` returns None on unparseable output → same fail-safe path (AC-13) |
| `test_circuit_breaker_opens` | After `THRESHOLD` consecutive None-returns, remaining validated findings get default `HIGH` with NO further `score_risk` calls; one "circuit opened" warning (AC-14) |
| `test_empty_text_findings_are_circuit_neutral` | A run of only empty-text validated findings applies default to each but **never** opens the circuit and returns **no** `error_count` (AC-14a) |
| `test_circuit_resets_on_success` | An interleaved real score resets the consecutive counter (intermittent single failures never trip it) |
| `test_circuit_open_emits_error_count_once` | Breaker opens → return includes `error_count: 1` exactly once; never-open run has no `error_count` key (AC-15) |
| `test_current_node_pinned` | `current_node == "risk_score"` and same key in `node_timings` (AC-16) |
| `test_rerun_overwrites_risk_fields` | Pre-existing `risk_level`/`risk_rationale` overwritten; reducer preserves text/verdicts (AC-17) |
| `test_rationale_truncated` | Rationale longer than `RISK_RATIONALE_MAX_CHARS` truncated before write (AC-18) |
| `test_empty_evidence_validated_still_scored` | `VALIDATED` finding with `evidence_snippets` `[]`/`None` still scored (one `score_risk` call), no crash (AC-20) |
| `test_empty_text_validated_failsafe` | Whitespace-only text on a `VALIDATED` finding → default level, `[auto]` rationale, **no** `score_risk` call (Edge Case 6 + AC-14a) |
| `test_suggested_rewrite_untouched` | Node never sets/modifies `suggested_rewrite` on any clause (AC-21) |
| `test_risk_level_is_valid_enum` | Every assigned `risk_level` is a `RiskLevel` member (serializes to `"low"/"medium"/"high"`) (AC-22) |
| `test_clause_type_enum_or_str_context` | `_clause_type_value` normalizes `ClauseType` enum, `str`, and `None` to the string label passed to `score_risk` |

- [ ] For `test_ingest_error_returns_empty` / `test_empty_clauses_returns_empty` / `test_no_validated_findings_zero_llm`: assert the `score_risk` mock `assert_not_called()`.
- [ ] For `test_circuit_breaker_opens`: monkeypatch `RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD` small (e.g. 3) on the **node module**, make `score_risk` always return `None`, feed more VALIDATED findings than the threshold, and assert `score_risk` calls STOP after the trip (later findings get default `HIGH` via the bulk path, with zero further calls).
- [ ] For `test_empty_text_findings_are_circuit_neutral`: feed more than `THRESHOLD` VALIDATED findings **all with whitespace-only text**; assert `score_risk` is never called, every finding gets the default level, and the return has **no** `error_count` key (the counter was never touched).
- [ ] For `test_partial_update_only_no_error_count`: assert forbidden keys absent — `document_id`, `extracted_text`, `ingest_error`, `report_path`, `evidence_trail`, `mcp_delivery_status`, `retry_budgets`, and specifically `error_count` (on a non-outage run).
- [ ] For `test_clause_type_enum_or_str_context`: score the same VALIDATED finding twice — once with `clause_type=ClauseType.LIABILITY`, once with `clause_type="liability"` — and assert `score_risk` received the string label `"liability"` in both cases (inspect the mock's `call_args`).
- [ ] For `test_suggested_rewrite_untouched`: include a clause that already has `suggested_rewrite` set and assert the node's returned update does not carry that key for any clause.

**Verify**: Run `python -m pytest tests/unit/test_risk_score_agent.py -v` — all 24 tests must FAIL (ImportError). Confirms the TDD cycle.

---

## Task 7: Implement the `risk_score_agent` node function

- [ ] Create file `app/graph/nodes/risk_score_agent.py`
- [ ] **Imports**: `time`, `logging` (stdlib); `from typing import Optional`; `from app.graph.state import ContractState, ClauseType, ValidationStatus, RiskLevel`; `from app.graph.nodes.scorers.risk_scorer import score_risk`.
- [ ] **CRITICAL — config import pattern (mirror `self_rag_validation_agent.py`)**: `import app.config as _config` and re-expose each tunable as a monkeypatchable module-level name read by **bare name** (never `_config.NAME`):

```python
import app.config as _config

OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME
RISK_SCORE_TIMEOUT_SECONDS = _config.RISK_SCORE_TIMEOUT_SECONDS
RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD = _config.RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD
RISK_SCORE_PROMPT_MAX_CHARS = _config.RISK_SCORE_PROMPT_MAX_CHARS
RISK_RATIONALE_MAX_CHARS = _config.RISK_RATIONALE_MAX_CHARS
RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE = _config.RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE
```

- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.risk_score")`
- [ ] Public interface:

```python
def risk_score_agent(state: ContractState) -> dict:
    """LangGraph Node 5. Reads clauses/document_id/ingest_error; scores only
    VALIDATED findings; returns partial dict: clauses (per-finding risk_level +
    risk_rationale), current_node, node_timings, and error_count:1 ONLY when the
    circuit breaker opened."""
```

- [ ] **CRITICAL — circuit state is a SINGLE MUTABLE HOLDER, not bare locals (plan §2 "Circuit-state holder")**: use `cb = {"consecutive_failures": 0, "open": False, "tripped": False}` and thread it into `_account`. Rebinding an outer `int`/`bool` from a nested function needs `nonlocal`; omit it and Python raises `UnboundLocalError` or silently shadows, so the breaker never opens. Mutating a dict's contents (`cb["open"] = True`) needs no `nonlocal`. Do NOT introduce standalone `consecutive_failures`/`circuit_open` locals.
- [ ] **Internal flow** (plan §2 — follow exactly):
  1. `start_time = time.monotonic()`; `current_node = "risk_score"`; `document_id = state.get("document_id", "unknown")`.
  2. **Defensive `ingest_error` check** — if `state.get("ingest_error") is not None` → return empty update (`clauses={}`, `current_node`, `node_timings`); NO `score_risk` calls (AC-8).
  3. `clauses = state.get("clauses", {})`. If falsy → log warning, return empty update (AC-9).
  4. `cb = {"consecutive_failures": 0, "open": False, "tripped": False}`; `clause_updates = {}`.
  5. Iterate clauses **in document order** (sort by `position`). For each `clause_id`, `record`:
     - `final_status = record.get("final_status")`. If `final_status != ValidationStatus.VALIDATED` → `continue` (skip DISCARDED / None — no update, no call: AC-2/3/10).
     - `text = (record.get("text") or "").strip()`. If `not text` → `clause_updates[clause_id] = _failsafe("clause text was empty; assigned default severity")`; log warning; `continue`. **CIRCUIT-NEUTRAL: do NOT call `_account`** (Edge Case 6 / AC-14a).
     - If `cb["open"]` → `clause_updates[clause_id] = _failsafe("scoring backend unavailable; assigned default severity")`; `continue`. **CIRCUIT-NEUTRAL bulk default: no `_account`, no `score_risk` call** (AC-14a).
     - `evidence = record.get("evidence_snippets")` (may be `[]`/`None` — fine, AC-20); `ct = _clause_type_value(record.get("clause_type"))`.
     - `result = score_risk(text, evidence, ct, RISK_SCORE_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME, RISK_SCORE_PROMPT_MAX_CHARS)` — **the one LLM call**.
     - `_account(result, cb)`.
     - If `result is None` → `clause_updates[clause_id] = _failsafe("scoring failed; assigned default severity")` (AC-12/13). Else `level, rationale = result`; `clause_updates[clause_id] = {"risk_level": level, "risk_rationale": rationale[:RISK_RATIONALE_MAX_CHARS]}` (AC-18).
     - Emit a per-finding structured log (`logger.info(..., extra={...})`, spec §9).
  6. `elapsed = time.monotonic() - start_time`. Emit an aggregate metrics log (level distribution, failure count, `circuit_opened`, elapsed — spec §9).
  7. `out = {"clauses": clause_updates, "current_node": current_node, "node_timings": {current_node: elapsed}}`; if `cb["tripped"]`: `out["error_count"] = 1`; return `out`.
- [ ] **`_failsafe(reason)`** helper: `return {"risk_level": RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE, "risk_rationale": f"[auto] {reason} (default={RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE.value})"}`. The `[auto]` marker distinguishes a fail-safe HIGH from a model-assigned HIGH in state and the report (spec §4.4).
- [ ] **`_account(result, cb)`** — circuit bookkeeping: if `result is None`: `cb["consecutive_failures"] += 1`; if `cb["consecutive_failures"] >= RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD and not cb["open"]` → `cb["open"] = True`, `cb["tripped"] = True`, log ONE "circuit opened" warning. Else (a real `(level, rationale)`): `cb["consecutive_failures"] = 0`. **`_account` is called ONLY from the `score_risk` path (step 5) — never from the empty-text or bulk-default paths** (AC-14a).
- [ ] **`_clause_type_value(raw) -> Optional[str]`**: `raw.value if isinstance(raw, ClauseType) else (raw if isinstance(raw, str) else None)` — identical to Node 4's helper — so `score_risk` receives a plain string label (or `None`).
- [ ] **Key invariants** (make them hold by construction):
  - Every VALIDATED finding gets a non-None `risk_level ∈ {LOW,MEDIUM,HIGH}` and non-empty `risk_rationale` — including the empty-text and circuit-open paths via `_failsafe` (AC-1).
  - Non-VALIDATED clauses are never added to `clause_updates` (so the reducer leaves them untouched — AC-2/3).
  - `suggested_rewrite` is never written (Node 6 owns it — AC-21).
  - `error_count` increments **at most once per run**, only when the breaker opens (AC-15).
  - Only `score_risk`-issuing failures move the consecutive counter; zero-LLM paths are circuit-neutral (AC-14a).
- [ ] **`risk_level`** stores the `RiskLevel` enum member (from `score_risk` or `RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE`), matching the 001 clause-record type (AC-22).
- [ ] **Pinned `current_node`**: the literal `"risk_score"` (spec §2) — also the `node_timings` key and the graph node name in Task 8. Do NOT derive it.

**Verify**: Run `python -m pytest tests/unit/test_risk_score_agent.py -v` — all 24 tests must PASS.

---

## Task 8: Wire the node into the graph builder

- [ ] Open `app/graph/builder.py`
- [ ] Add the import: `from app.graph.nodes.risk_score_agent import risk_score_agent`
- [ ] Register the node and rewire the tail so `self_rag_validation → risk_score → END`:

```python
graph.add_node("risk_score", risk_score_agent)
graph.add_edge("self_rag_validation", "risk_score")   # was END temporarily
graph.add_edge("risk_score", END)                     # → END until feature-008 (Redline)
```

- [ ] Remove the old `graph.add_edge("self_rag_validation", END)` line (replaced by the edge into `risk_score`).
- [ ] Update the module docstring "Current scope" note (builder.py:4-9) to include Node 5 and move the "→ END temporarily" comment to the RiskScore edge.
- [ ] **Add a comment near the node** noting that RiskScore's outgoing edge is a **plain linear `add_edge`**, deliberately NOT an `add_conditional_edges` — the two permitted conditional edges are CRAG's confidence routing (Node 3) and `route_on_risk` (Node 6, which will *read* the `risk_level` this node writes). Mirror the existing comment style on the Self-RAG node.

**Verify**: Run from `backend/`:
```
python -c "from app.graph.builder import build_graph; g = build_graph(); print(type(g))"
```
Should print the compiled graph type without errors.

---

## Task 9: Write and run integration tests

- [ ] Create file `tests/integration/test_risk_score_graph.py`
- [ ] Tests exercise the compiled graph through Node 5. `score_risk` is **mocked** (no live Ollama); Self-RAG's `final_status` is either produced by the real upstream nodes with their LLM boundaries mocked, or injected as a pre-built `clauses` fixture.
- [ ] **CRITICAL — patch targets**: patch `app.graph.nodes.risk_score_agent.score_risk` — i.e. **on the node module** (the node did `from ...risk_scorer import score_risk`, binding the name locally). Patching `scorers.risk_scorer.score_risk` would NOT affect the node and could silently hit real Ollama. Also mock the upstream LLM boundaries (`self_rag_validation_agent.check_relevance/.check_isrel/.check_issup`, ClauseSplitter's `ollama.chat`, CRAG's `embed_query`/`web_search`) as in the 004/005/006 integration tests, OR inject a hand-built `clauses` dict (with `final_status` set) as initial state and invoke starting at RiskScore.
- [ ] Write these 6 test functions (plan §2 matrix):

| Test function | Verifies |
|---------------|----------|
| `test_graph_reaches_risk_score_and_ends` | Full path Node1→…→5 reaches END; every `VALIDATED` clause carries a `risk_level` |
| `test_graph_ingest_error_skips_risk_score` | Ingest error short-circuits to END; RiskScore not reached; assert `assert not final_state.get("clauses")` (KeyError caution below) |
| `test_graph_only_validated_scored` | Mixed fixture: `VALIDATED` clauses get a `risk_level`; `DISCARDED` clauses keep `risk_level` absent/None, all still present in state (AC-2) |
| `test_graph_no_validated_findings` | All-`DISCARDED` document → no clause has a `risk_level`; graph ends cleanly with no `error_count` (AC-10) |
| `test_graph_circuit_open_sets_error_count` | Forcing all `score_risk` calls to return None opens the breaker → final state `error_count == 1` and remaining validated findings default to `HIGH` (AC-14, AC-15) |
| `test_graph_checkpointing_after_risk_score` | State is checkpointed after RiskScore completes (SqliteSaver; `pytest.skip` if the import path is unavailable, mirroring `test_ingest_graph.py`) |

- [ ] **KeyError caution** (`test_graph_ingest_error_skips_risk_score`): `clauses` is an `Annotated[dict, merge_nested_clause_dicts]` channel with no default; on the error short-circuit it is never written, so `final_state["clauses"]` raises `KeyError`. Assert `assert not final_state.get("clauses")` instead (same subtlety noted in 004/005/006).
- [ ] For `test_graph_only_validated_scored`: build the initial `clauses` with a mix of `final_status=VALIDATED` and `=DISCARDED`; drive the mocked `score_risk` to return `(RiskLevel.MEDIUM, "...")`; assert the validated IDs gained `risk_level` and the discarded IDs did not, and all IDs remain present.
- [ ] For the checkpointing test, attach the checkpointer the same way `test_ingest_graph.py` / `test_self_rag_validation_graph.py` do.

**Verify**: Run `python -m pytest tests/integration/test_risk_score_graph.py -v` — all 6 tests must PASS (checkpointing may skip if the SQLite saver import path is unavailable — acceptable).

---

## Task 10: Full test suite pass

- [ ] Run the complete suite:
```
python -m pytest tests/ -v --tb=short
```
- [ ] All existing IngestAgent (003), ClauseSplitterAgent (004), CRAG (005), and Self-RAG (006) tests must still pass — Node 5 must not regress them.
- [ ] **Regression caution — the tail edge moved (BROADER than one suite — read fully).** The previously-terminal `self_rag_validation → END` edge is now `self_rag_validation → risk_score → END`. Every integration test that invokes the real `build_graph()` and runs to END asserts `final_state["current_node"] == "self_rag_validation"` on the assumption that Self-RAG is terminal. That assumption is now false for **four** files across **three upstream feature suites (003/004/005) plus 006** — not just 006. These failures are **EXPECTED and benign**: the graph still reaches END, and because `ollama.Client` is globally patched in these tests, the new `score_risk` calls simply fail-safe (they do not hit real Ollama). Do **NOT** treat the red as a bug and do **NOT** weaken these assertions (constitution §7) — **update** each to the new terminal node. Exact edits — change `"self_rag_validation"` → `"risk_score"` at:
  - `tests/integration/test_ingest_graph.py:59` (and fix the comment at :58 — "Node 4 is the terminal node after feature-006" → Node 5 / risk_score after feature-007)
  - `tests/integration/test_clause_splitter_graph.py:69` (and comment :68) and `:115` (and comment :114)
  - `tests/integration/test_crag_retrieval_graph.py:93`
  - `tests/integration/test_self_rag_validation_graph.py:103` (in `test_graph_reaches_self_rag_and_ends`)
- [ ] **Do NOT change `tests/integration/test_self_rag_validation_graph.py:299`.** That test (the 006 checkpointing case) builds its **own** self-contained subgraph wiring `self_rag_validation → END` directly (line 279), so Self-RAG genuinely *is* terminal there — its `current_node == "self_rag_validation"` assertion stays correct. Touching it would be wrong.
- [ ] After these updates, re-run the full suite; the only remaining diffs from these files should be the terminal-node string. Verify line numbers before editing (they may drift as 006 evolves) by grepping `current_node.*self_rag_validation` across `tests/integration/`.
- [ ] Expected NEW test count for feature 007: 5 (config) + 15 (scorer) + 24 (node) + 6 (integration) = **50 new tests**.
- [ ] OCR-gated IngestAgent tests may skip if Tesseract is absent — acceptable. No RiskScore test requires Tesseract, a live Ollama, or network.

---

## Task 11: Linting and type checking

- [ ] Run `black app/ tests/` — auto-format.
- [ ] Run `ruff check app/ tests/` — no lint errors.
- [ ] Run `mypy app/` — no type errors (if mypy is installed). `ollama`/`httpx` are already used elsewhere; add narrow `# type: ignore[...]` only if genuinely needed — do NOT broaden.
- [ ] Do NOT weaken tests to satisfy lint/type checks — fix the implementation instead (constitution §7).

---

## Task 12: Manual live smoke test (optional, not in automated suite)

- [ ] Ensure Ollama is running with `qwen3:14b` (`ollama pull qwen3:14b`). NOTE (per project memory): the current dev box OOMs on live `qwen3:14b` — this step may not be runnable here; the automated suite (Task 10) is fully mocked and must pass regardless.
- [ ] Run the full graph (Node 1→5) on a real multi-clause contract with live Ollama (embedding + web can stay mocked, or run fully live if `bge-m3` + network are available).
- [ ] Confirm: every VALIDATED finding carries a `risk_level` and a `risk_rationale`; a fail-safed finding (if any) shows the `[auto]` rationale prefix and `HIGH`; discarded clauses have no `risk_level`; per-finding latency is well under `RISK_SCORE_TIMEOUT_SECONDS`; and `error_count` is absent unless the breaker actually opened.
- [ ] Record the risk-level distribution, level-by-`clause_type`, and scoring-failure rate (spec §9) — use them to consider tuning `RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE`, the rubric wording, and (for Node 6) the level→Redline routing threshold.

**Why**: The automated suite mocks the scorer, so this is the only step that validates real Qwen3 severity quality, prompt/rubric wording, and the true latency envelope (plan §6 risks).

---

## Summary of all files created/modified

| # | File | Action |
|---|------|--------|
| 1 | `app/config.py` | MODIFIED (add `RiskLevel` import + 5 RiskScore constants) |
| 2 | `app/graph/nodes/scorers/__init__.py` | NEW (package marker, no logic) |
| 3 | `app/graph/nodes/scorers/risk_scorer.py` | NEW (`score_risk`) |
| 4 | `app/graph/nodes/risk_score_agent.py` | NEW (node function) |
| 5 | `app/graph/builder.py` | MODIFIED (add node + rewire self_rag → risk_score → END) |
| 6 | `tests/unit/test_config.py` | MODIFIED (+5 tests) |
| 7 | `tests/unit/test_risk_scorer.py` | NEW (15 tests) |
| 8 | `tests/unit/test_risk_score_agent.py` | NEW (24 tests) |
| 9 | `tests/integration/test_risk_score_graph.py` | NEW (6 tests) |
| 10 | `tests/integration/test_ingest_graph.py` | MODIFIED (Task 10 regression: terminal-node assertion `:59` + comment `:58`) |
| 11 | `tests/integration/test_clause_splitter_graph.py` | MODIFIED (Task 10 regression: terminal-node assertions `:69`, `:115` + comments) |
| 12 | `tests/integration/test_crag_retrieval_graph.py` | MODIFIED (Task 10 regression: terminal-node assertion `:93`) |
| 13 | `tests/integration/test_self_rag_validation_graph.py` | MODIFIED (Task 10 regression: terminal-node assertion `:103` only — NOT `:299`) |

> Files 10–13 are **expected regression fix-ups**, not new feature code — the tail edge moving from `self_rag_validation → END` to `self_rag_validation → risk_score → END` invalidates their "Self-RAG is terminal" assertion (see Task 10).

---

## Acceptance-criteria traceability (spec §3 → tasks)

| Spec §3 criterion | Covered by |
|-------------------|-----------|
| 1. Validated findings are scored | Task 6/7 (`test_validated_findings_scored`), Task 9 (`test_graph_reaches_risk_score_and_ends`) |
| 2. Discarded clauses untouched (no LLM) | Task 6/7 (`test_discarded_untouched_no_llm`), Task 9 (`test_graph_only_validated_scored`) |
| 3. `final_status is None` skipped | Task 6/7 (`test_final_status_none_skipped`) |
| 4. Level echoes the judgment | Task 6/7 (`test_level_echoes_judgment`) |
| 5. Only validated findings incur LLM calls | Task 6/7 (`test_only_validated_incur_llm_calls`) |
| 6. Generative model, not embedding model | Task 1 (`test_risk_score_uses_generative_model`), Task 4/5 (`test_uses_generative_model_only`), Task 6/7 (`test_uses_generative_not_embedding_model`) |
| 7. Uses configured constants | Implicit — a hardcoded value breaks `test_circuit_breaker_opens` / `test_graceful_llm_failure_failsafe_high` / `test_rationale_truncated` (all monkeypatch the re-exposed names) |
| 8. Defensive `ingest_error` check | Task 6/7 (`test_ingest_error_returns_empty`), Task 9 (`test_graph_ingest_error_skips_risk_score`) |
| 9. Empty clauses input | Task 6/7 (`test_empty_clauses_returns_empty`) |
| 10. No validated findings | Task 6/7 (`test_no_validated_findings_zero_llm`), Task 9 (`test_graph_no_validated_findings`) |
| 11. Partial update only | Task 6/7 (`test_partial_update_only_no_error_count`) |
| 12. Graceful LLM failure (fail-safe) | Task 6/7 (`test_graceful_llm_failure_failsafe_high`) |
| 13. Malformed / unparseable output | Task 4/5 (`test_invalid_level_string_returns_none`, `test_malformed_json_returns_none`), Task 6/7 (`test_malformed_output_failsafe`) |
| 14. LLM circuit breaker | Task 6/7 (`test_circuit_breaker_opens`, `test_circuit_resets_on_success`), Task 9 (`test_graph_circuit_open_sets_error_count`) |
| 14a. Only LLM-issuing failures move the counter | Task 6/7 (`test_empty_text_findings_are_circuit_neutral`, `test_empty_text_validated_failsafe`) |
| 15. Circuit-open health signal | Task 6/7 (`test_circuit_open_emits_error_count_once`), Task 9 (`test_graph_circuit_open_sets_error_count`) |
| 16. `current_node` pinned | Task 6/7 (`test_current_node_pinned`) |
| 17. Re-run overwrite | Task 6/7 (`test_rerun_overwrites_risk_fields`) |
| 18. Rationale truncation | Task 6/7 (`test_rationale_truncated`) |
| 19. Prompt truncation | Task 4/5 (`test_prompt_truncated_to_max_chars`) |
| 20. Validated finding with empty evidence still scores | Task 4/5 (`test_empty_evidence_scores_on_text`), Task 6/7 (`test_empty_evidence_validated_still_scored`) |
| 21. `suggested_rewrite` untouched | Task 6/7 (`test_suggested_rewrite_untouched`) |
| 22. `risk_level` is a valid enum member | Task 4/5 (`test_invalid_level_string_returns_none`), Task 6/7 (`test_risk_level_is_valid_enum`) |
