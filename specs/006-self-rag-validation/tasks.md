# Self-RAG Validation Implementation Tasks

Reference documents:
- Spec: `specs/006-self-rag-validation/spec.md`
- Plan: `specs/006-self-rag-validation/plan.md`
- State schema: `specs/001-contract-state-schema.md`
- Tech stack: `specs/002-tech-stack.md`
- Constitution: `specs/000-constitution.md`

All file paths below are relative to `backend/` unless stated otherwise.

**Workflow reminders:**
- Follow TDD per constitution §7 — write tests, confirm they FAIL, then implement to make them PASS.
- Node returns ONLY the state keys it updates per constitution §5 (Partial-Update Rule): `clauses`, `current_node`, `node_timings` — **plus `error_count: 1` in the one case the circuit breaker opens** (spec §8a R5 / AC-20). Never any other key.
- All thresholds live in `app/config.py` per constitution §3 — never hardcode inline.
- Model separation (constitution §8): every Self-RAG LLM call uses the **generative** `OLLAMA_MODEL_NAME` (Qwen3). Self-RAG makes NO vector calls and MUST NEVER reference `OLLAMA_EMBED_MODEL_NAME`.
- The four locked design decisions (spec §8a): **R1** retry re-runs ISSUP only (no finding regeneration); **R2** three sequential short-circuit calls (Relevance → ISREL → ISSUP); **R3** fail-open (`VALIDATED`) on unrecoverable LLM failure; **R4** empty-evidence is `clause_type`-gated (high-risk → rescue on clause text; else zero-LLM discard); **R5** circuit-open emits `error_count: 1` once.
- Branch: `feature/006-self-rag-validation` per constitution §11.

---

## Task 0: Create feature branch

- [ ] From an up-to-date `main`, create and check out `feature/006-self-rag-validation`

**Why**: Per constitution §11, every feature is developed on its own branch. CRAG retrieval (005) is already merged to `main`.

**Verify**: `git branch --show-current` prints `feature/006-self-rag-validation`.

**Note**: The working tree currently has `specs/006-self-rag-validation/` (spec.md, plan.md, tasks.md) and a modified `specs/001-contract-state-schema.md` (the validation-example fix). Confirm with the user whether those spec docs should be committed before branching, so 006 starts from a clean tree.

---

## Task 1: Write config tests for the Self-RAG constants (confirm FAILING)

- [ ] Open `tests/unit/test_config.py`
- [ ] Add 5 new test functions for the Self-RAG constants, the rename, and model separation:

```python
def test_self_rag_constants_match_spec():
    """Verify Self-RAG constants match specs/006 §6."""
    from app.config import (
        SELF_RAG_MAX_ATTEMPTS,
        SELF_RAG_TIMEOUT_SECONDS,
        SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD,
        SELF_RAG_PROMPT_MAX_CHARS,
    )
    assert SELF_RAG_MAX_ATTEMPTS == 3
    assert SELF_RAG_TIMEOUT_SECONDS == 120
    assert SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD == 5
    assert SELF_RAG_PROMPT_MAX_CHARS == 6000


def test_self_rag_constants_correct_types():
    """int for the numeric constants; frozenset of str for the high-risk set."""
    from app import config
    assert isinstance(config.SELF_RAG_MAX_ATTEMPTS, int)
    assert isinstance(config.SELF_RAG_TIMEOUT_SECONDS, int)
    assert isinstance(config.SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD, int)
    assert isinstance(config.SELF_RAG_PROMPT_MAX_CHARS, int)
    assert isinstance(config.SELF_RAG_HIGH_RISK_CLAUSE_TYPES, frozenset)
    assert all(isinstance(t, str) for t in config.SELF_RAG_HIGH_RISK_CLAUSE_TYPES)


def test_self_rag_high_risk_types_are_valid_clause_types():
    """Every high-risk entry must be a real ClauseType.value (guards typos / enum drift)."""
    from app.config import SELF_RAG_HIGH_RISK_CLAUSE_TYPES
    from app.graph.state import ClauseType
    valid = {ct.value for ct in ClauseType}
    assert SELF_RAG_HIGH_RISK_CLAUSE_TYPES <= valid


def test_self_rag_max_retries_renamed():
    """The old placeholder is gone; the renamed constant exists (spec §8b Q2)."""
    from app import config
    assert not hasattr(config, "SELF_RAG_MAX_RETRIES")
    assert hasattr(config, "SELF_RAG_MAX_ATTEMPTS")


def test_self_rag_uses_generative_model():
    """Constitution §8: the generative model is distinct from the embedding model."""
    from app.config import OLLAMA_MODEL_NAME, OLLAMA_EMBED_MODEL_NAME
    assert OLLAMA_MODEL_NAME != OLLAMA_EMBED_MODEL_NAME
    assert OLLAMA_MODEL_NAME == "qwen3:14b"
```

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — `test_self_rag_constants_match_spec` must FAIL (`ImportError` — the new constants don't exist yet) and `test_self_rag_max_retries_renamed` must FAIL (old `SELF_RAG_MAX_RETRIES` still present). `test_self_rag_uses_generative_model` may already PASS. Existing config tests must still PASS.

---

## Task 2: Replace the Self-RAG placeholder with the spec §6 constants

- [ ] Open `app/config.py`
- [ ] In the `# ── Self-RAG validation thresholds ──` block, **delete** the placeholder lines (the `# Placeholder …` comment and `SELF_RAG_MAX_RETRIES: int = 3`) and replace them with the constants below. This executes the §8b Q2 rename (`SELF_RAG_MAX_RETRIES` → `SELF_RAG_MAX_ATTEMPTS`).
- [ ] **First confirm the rename is safe**: `grep -rn SELF_RAG_MAX_RETRIES app/ tests/` must return nothing outside `config.py` (Node 4 is not yet implemented — expected clean).

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
# all remaining clauses that would otherwise call the LLM (skipping per-clause
# timeouts). Resets on any success. Opening emits the error_count health signal once
# (spec §4.8, §8a R5, AC-15/20). Mirrors CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD.

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

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — all config tests (Ingest + ClauseSplitter + CRAG + Self-RAG) must now PASS.

---

## Task 3: Implement the validators package shared helper (no dedicated TDD cycle)

- [ ] Create directory `app/graph/nodes/validators/`
- [ ] Create file `app/graph/nodes/validators/__init__.py`
- [ ] Contents:

```python
"""
Shared helpers for the Self-RAG validator modules.

format_evidence renders 001-shape evidence snippets into a single prompt-ready
block, truncated to a char budget. Placing it in the package __init__ (like
make_snippet in retrievers/__init__.py) keeps the "001 evidence shape" assumption
in one place for both reflectors.py and the node.
"""
from typing import List, Dict, Any, Optional


def format_evidence(snippets: Optional[List[Dict[str, Any]]], max_chars: int) -> str:
    """Render evidence snippets into a single prompt block, truncated to max_chars.

    Each snippet is the 001 shape {"snippet_text": str, "source_reference": str}.
    Returns "" when snippets is None or empty (the empty-evidence path formats its
    own "no evidence" wording in the reflector). Truncation is applied to the
    concatenated block so total prompt input is bounded (spec §4.9).
    """
    if not snippets:
        return ""
    parts = []
    for i, s in enumerate(snippets, start=1):
        text = (s.get("snippet_text") or "").strip()
        src = (s.get("source_reference") or "").strip()
        if text:
            parts.append(f"[{i}] ({src}) {text}")
    block = "\n".join(parts)
    return block[:max_chars]
```

**Why**: `format_evidence` is a shared, dependency-free helper — like `make_snippet` in `retrievers/__init__.py`, it needs no TDD cycle and is implemented before the reflector tests that import it (plan §4 Step 4 note). It IS still asserted, in `test_format_evidence_shape_and_empty` (Task 4).

**Verify**: Run from `backend/`:
```
python -c "from app.graph.nodes.validators import format_evidence; print(repr(format_evidence(None, 100)), repr(format_evidence([{'snippet_text':'t','source_reference':'r'}], 100)))"
```

---

## Task 4: Write unit tests for the reflectors (confirm FAILING)

- [ ] Create file `tests/unit/test_self_rag_reflectors.py`
- [ ] The import `from app.graph.nodes.validators.reflectors import check_relevance, check_isrel, check_issup` will fail until Task 5 — expected for TDD.
- [ ] **Mocking strategy (name the target)**: patch `ollama.Client` at `app.graph.nodes.validators.reflectors.ollama.Client` (equivalently `patch("ollama.Client")` since `reflectors.py` does `import ollama`). Configure `mock_client.return_value.chat.return_value = {"message": {"content": '{"verdict": true, "reason": "x"}'}}`. Assert on `mock_client.call_args` that it was constructed with `timeout=<passed timeout_seconds>` (the correctness hinge from Task 5) and on `.chat.call_args` for `model=OLLAMA_MODEL_NAME` and `format="json"`. **No real Ollama.**
- [ ] Write these 13 test functions (plan §2 test matrix):

| Test function | Verifies |
|---------------|----------|
| `test_verdict_true_parsed` | `{"verdict": true}` → `True` |
| `test_verdict_false_parsed` | `{"verdict": false}` → `False` |
| `test_timeout_returns_none` | Simulated timeout (`concurrent.futures.TimeoutError` / `httpx.TimeoutException`) → `None`, warning logged |
| `test_connection_error_returns_none` | Ollama unreachable (`ConnectionError`/`httpx.ConnectError`) → `None` |
| `test_malformed_json_returns_none` | Non-JSON `content` → `None` (fail-open trigger) |
| `test_missing_verdict_key_returns_none` | JSON without a `verdict` key → `None` |
| `test_non_bool_verdict_returns_none` | `{"verdict": "maybe"}` (or `1`) → `None` |
| `test_uses_generative_model_only` | `chat` called with `model=OLLAMA_MODEL_NAME`; `OLLAMA_EMBED_MODEL_NAME` never referenced (AC-9) |
| `test_relevance_prompt_excludes_evidence` | The Relevance prompt is a function of clause text only (evidence text does not appear in the built prompt) |
| `test_issup_empty_evidence_uses_text_only_prompt` | With `evidence_snippets=None`/`[]`, the ISSUP prompt instructs judging on the clause text alone (spec §7.5) |
| `test_prompt_truncated_to_max_chars` | Oversized clause text + evidence is truncated so the prompt input is bounded by `prompt_max_chars` (spec §4.9) |
| `test_format_evidence_shape_and_empty` | `format_evidence` renders `[i] (src) text` lines; returns `""` for `None`/`[]` |
| `test_reflector_never_raises` | Any injected exception inside the call → `None`, nothing propagates |

- [ ] For the "uses generative model" test, call all three reflectors and assert none pass `OLLAMA_EMBED_MODEL_NAME`.
- [ ] For `test_prompt_truncated_to_max_chars`: capture the prompt actually sent (from `.chat.call_args` → `messages[0]["content"]`) and assert the **combined** clause+evidence variable portion is bounded by `prompt_max_chars` (per the pinned combined-budget rule in Task 5 — `len(clause_trunc) + len(evidence_str) <= prompt_max_chars`), i.e. the total prompt length ≤ fixed scaffold + `prompt_max_chars`. Use an ISSUP or ISREL call (which include evidence) with oversized clause text AND oversized evidence so independent truncation would exceed the budget but the combined rule does not.
- [ ] Warning assertions use pytest's `caplog` at `WARNING`.

**Verify**: Run `python -m pytest tests/unit/test_self_rag_reflectors.py -v` — all 13 tests must FAIL (ImportError). Confirms the TDD cycle.

---

## Task 5: Implement the reflectors

- [ ] Create file `app/graph/nodes/validators/reflectors.py`
- [ ] **Imports**: `concurrent.futures`, `json`, `logging` (stdlib); `httpx` (timeout type); `ollama`; `from app.graph.nodes.validators import format_evidence`. No `app.config` import (all limits passed in).
- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.self_rag_validation.reflectors")`
- [ ] Public interface — each returns `Optional[bool]`, **never raises** (`None` = un-runnable → the node fail-opens):

```python
def check_relevance(clause_text: str, timeout_seconds: int, model_name: str,
                    prompt_max_chars: int) -> "Optional[bool]":
    """Relevance: is this clause a substantive, analyzable provision worth
    evaluating at all? A property of the CLAUSE — does NOT read evidence."""

def check_isrel(clause_text: str, evidence_snippets: list, timeout_seconds: int,
                model_name: str, prompt_max_chars: int) -> "Optional[bool]":
    """ISREL: is the retrieved evidence relevant to this clause? A property of the
    EVIDENCE. Only called when evidence is present."""

def check_issup(clause_text: str, evidence_snippets, timeout_seconds: int,
                model_name: str, prompt_max_chars: int) -> "Optional[bool]":
    """ISSUP ('worth flagging'): does the evidence support surfacing this clause as a
    concern? If evidence_snippets is empty/None (the high-risk rescue path, spec
    §7.5) the prompt judges on the CLAUSE TEXT ALONE."""
```

- [ ] **Shared invocation core** — a private `_run_judgment(prompt, timeout_seconds, model_name) -> Optional[bool]` that all three public functions call with their own prompt. Mirrors `llm_refiner.py`'s `_call_ollama` + `_parse_response` split.
- [ ] **CRITICAL — client-level timeout is the primary bound (plan §5)**: the call MUST go through `ollama.Client(timeout=timeout_seconds).chat(model=model_name, messages=[{"role":"user","content":prompt}], format="json", options={"num_predict": 256})`, run inside a `concurrent.futures.ThreadPoolExecutor(max_workers=1)` with `future.result(timeout=timeout_seconds)` — exactly the `llm_refiner.refine_with_llm` pattern (llm_refiner.py:67–80, 102–108). Do NOT use a bare `ollama.chat` bounded only by the executor: on a hung Ollama socket the worker thread would stay blocked in the HTTP read and `shutdown(wait=True)` at `with` exit would hang, defeating both `SELF_RAG_TIMEOUT_SECONDS` and the circuit breaker. `num_predict` is small — each judgment returns a tiny JSON object, not prose.
- [ ] **Verdict parsing** — parse `response["message"]["content"]` as JSON; read `verdict`. Return it ONLY if it is a genuine `bool` (`isinstance(v, bool)` — note `isinstance(True, int)` is True, so check `bool` explicitly and reject ints/strings). If the content is not valid JSON, is missing `verdict`, or `verdict` is not a `bool` → treat as an **unrecoverable failure** and return `None` (fail-open). `reason`, if present, is logged at DEBUG only — **never stored in state** (spec §5.6).
- [ ] **Failure handling** — catch `concurrent.futures.TimeoutError`, `httpx.TimeoutException`, and any `Exception` → log a rate-limited WARNING and return `None`. Never raise.
- [ ] **Prompt construction & truncation — COMBINED budget (spec §4.9, reviewer note 1)** — clause text + evidence together must be bounded by `prompt_max_chars`, NOT each independently (independent truncation could let the variable input reach ~2× the budget). Pinned rule: truncate the clause text first, then give the **remainder** of the budget to the evidence block:
  ```python
  clause_trunc = clause_text[:prompt_max_chars]
  remaining = max(0, prompt_max_chars - len(clause_trunc))
  evidence_str = format_evidence(evidence, remaining)   # ISREL / ISSUP only
  # → len(clause_trunc) + len(evidence_str) <= prompt_max_chars, guaranteed
  ```
  (Relevance has no evidence, so it just uses `clause_text[:prompt_max_chars]`.) Instruct the model to reply with ONLY `{"verdict": true|false, "reason": "<short>"}` — no markdown — mirroring `llm_refiner.py`'s JSON-only instruction. Three distinct, focused prompts:
  - **Relevance**: given only the clause text, is it a substantive/analyzable provision? (evidence NOT included — this is what `test_relevance_prompt_excludes_evidence` asserts)
  - **ISREL**: given the clause text and the evidence block, is the evidence on-topic/relevant to this clause?
  - **ISSUP**: given the clause text and (if present) the evidence block, does it support flagging this clause as a concern worth surfacing? When evidence is empty/None, the prompt explicitly says to judge on the clause text alone.

**Verify**: Run `python -m pytest tests/unit/test_self_rag_reflectors.py -v` — all 13 tests must PASS.

---

## Task 6: Write unit tests for the `self_rag_validation_agent` node (confirm FAILING)

- [ ] Create file `tests/unit/test_self_rag_validation_agent.py`
- [ ] **Mocking strategy**: patch `check_relevance`, `check_isrel`, `check_issup` **at the node module level** (`app.graph.nodes.self_rag_validation_agent`), because the node does `from ...reflectors import check_relevance, ...` — binding those names into the node module. Patching `validators.reflectors.check_relevance` would NOT affect the node. Give each mock a `side_effect` list (or `return_value`) so verdicts are deterministic per attempt, and assert call counts.
- [ ] Helper: `make_state(clauses, ingest_error=None, document_id="doc-1")` returning a minimal state dict. Clause records carry at least `{text, position, evidence_snippets, clause_type}`. Provide small builders for the common shapes (evidence-present, empty-evidence-high-risk, empty-evidence-non-high-risk, empty-text).
- [ ] Write these 28 test functions (plan §2 node matrix):

| Test function | Verifies |
|---------------|----------|
| `test_all_clauses_get_final_status` | Every clause ends with non-None `final_status` (AC-1) |
| `test_relevance_fail_discards_short_circuit` | Relevance False → relevance=False, isrel=None, issup=None, retry=None, DISCARDED; **no** ISREL/ISSUP call (AC-2, AC-8) |
| `test_isrel_fail_discards_short_circuit` | Relevance True, ISREL False → isrel=False, issup=None, retry=None, DISCARDED; **no** ISSUP call (AC-3, AC-8) |
| `test_issup_pass_first_attempt_validated` | ISSUP True first try → issup=True, retry_count=0, VALIDATED (AC-4) |
| `test_issup_retry_then_pass_validated` | ISSUP [False, True] → issup=True, retry_count=1, VALIDATED (AC-5) |
| `test_issup_exhaustion_discarded` | ISSUP False every attempt → issup=False, retry_count=MAX-1, DISCARDED (AC-6) |
| `test_attempt_cap_enforced` | ≤ `SELF_RAG_MAX_ATTEMPTS` ISSUP calls (constant monkeypatched small) (AC-7) |
| `test_only_issup_retries` | Exactly one Relevance call, and (when reached) one ISREL call — never retried (AC-8) |
| `test_uses_generative_not_embedding_model` | Reflectors invoked with `OLLAMA_MODEL_NAME`; `OLLAMA_EMBED_MODEL_NAME` never referenced by the node (AC-9) |
| `test_ingest_error_returns_empty` | `ingest_error` set → empty update; no reflector calls (AC-11) |
| `test_empty_clauses_returns_empty` | `clauses == {}` → empty update, warning, no reflector calls (AC-12) |
| `test_partial_update_only_no_error_count` | Non-outage run → keys exactly `{clauses, current_node, node_timings}`; NO `error_count` (AC-13) |
| `test_graceful_llm_failure_fail_open` | A reflector returns None → clause VALIDATED, affected verdict None, no crash, other clauses proceed; `error_count` NOT incremented for a single failure (AC-14) |
| `test_circuit_breaker_opens` | After `THRESHOLD` consecutive None-returns, remaining LLM-path clauses take the default outcome with NO further reflector calls; one "circuit opened" warning (AC-15) |
| `test_circuit_resets_on_success` | An interleaved real verdict resets the consecutive counter (breaker not tripped by intermittent single failures) |
| `test_empty_evidence_high_risk_validates_on_text` | Empty evidence + high-risk type + Relevance True + text-ISSUP True → relevance=True, isrel=None, issup=True, VALIDATED (AC-16, AC-16a) |
| `test_empty_evidence_high_risk_relevance_false_discards` | Empty evidence + high-risk type + Relevance **False** → relevance=False, isrel=None, issup=None, retry=None, DISCARDED; NO ISSUP call (spec §7.5) |
| `test_empty_evidence_high_risk_issup_false_discards` | Same but text-ISSUP False to exhaustion → DISCARDED, isrel=None |
| `test_empty_evidence_non_high_risk_zero_llm_discard` | Empty evidence + non-high-risk type → all verdicts None, DISCARDED, **zero** reflector calls (AC-16b) |
| `test_empty_evidence_clause_type_none_discards` | Empty evidence + `clause_type=None` → zero-LLM DISCARD (residual-gap case, spec §7.5) |
| `test_no_isrel_false_with_validated` | Invariant: no clause ends `isrel_verdict=False` + `VALIDATED` (AC-16a) |
| `test_current_node_pinned` | `current_node == "self_rag_validation"` and same key in `node_timings` (AC-17) |
| `test_rerun_overwrites_verdicts` | Pre-existing verdict fields overwritten; reducer preserves text/evidence (AC-18) |
| `test_discarded_clause_still_present` | DISCARDED clause remains in the update; no clause IDs removed (AC-19) |
| `test_circuit_open_emits_error_count_once` | Breaker opens → return includes `error_count: 1` exactly once; never-open run has no `error_count` key (AC-20) |
| `test_empty_clause_text_skipped` | Whitespace-only text → all verdicts None, DISCARDED, no reflector call (Edge Case 6) |
| `test_clause_type_enum_or_str_gate` | High-risk gate matches whether `clause_type` is a `ClauseType` enum or its `.value` string |
| `test_zero_llm_branches_exempt_from_fail_open_after_trip` | After the circuit opens, a subsequent Branch-B (non-high-risk empty-evidence) clause and an empty-text clause still reach **DISCARDED**, not fail-open VALIDATED (spec §4.8 / AC-15 carve-out) |

- [ ] For `test_ingest_error_returns_empty` / `test_empty_clauses_returns_empty`: assert all three reflector mocks `assert_not_called()`.
- [ ] For `test_attempt_cap_enforced`: monkeypatch `SELF_RAG_MAX_ATTEMPTS` on the **node module** to a small value (e.g. 2), make ISSUP always False, assert `check_issup.call_count == 2` for that clause.
- [ ] For `test_circuit_breaker_opens`: monkeypatch `SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD` small (e.g. 3), make the first reflector called always return None, feed more clauses than the threshold, and assert reflector calls STOP after the trip (later clauses VALIDATED via fail-open, with zero further calls).
- [ ] For `test_partial_update_only_no_error_count`: assert forbidden keys absent — `document_id`, `extracted_text`, `ingest_error`, `report_path`, `evidence_trail`, `mcp_delivery_status`, `retry_budgets`, and specifically `error_count` (on a non-outage run).
- [ ] For `test_clause_type_enum_or_str_gate`: run the same empty-evidence high-risk clause twice — once with `clause_type=ClauseType.LIABILITY`, once with `clause_type="liability"` — and assert both take the rescue path (Relevance called).

**Verify**: Run `python -m pytest tests/unit/test_self_rag_validation_agent.py -v` — all 28 tests must FAIL (ImportError). Confirms the TDD cycle.

---

## Task 7: Implement the `self_rag_validation_agent` node function

- [ ] Create file `app/graph/nodes/self_rag_validation_agent.py`
- [ ] **Imports**: `time`, `logging` (stdlib); `from app.graph.state import ContractState, ClauseType, ValidationStatus`; `from app.graph.nodes.validators.reflectors import check_relevance, check_isrel, check_issup`.
- [ ] **CRITICAL — config import pattern (mirror `clause_splitter_agent.py`)**: `import app.config as _config` and re-expose each tunable as a monkeypatchable module-level name read by **bare name** (never `_config.NAME`):

```python
import app.config as _config

OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME
SELF_RAG_MAX_ATTEMPTS = _config.SELF_RAG_MAX_ATTEMPTS
SELF_RAG_TIMEOUT_SECONDS = _config.SELF_RAG_TIMEOUT_SECONDS
SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD = _config.SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD
SELF_RAG_PROMPT_MAX_CHARS = _config.SELF_RAG_PROMPT_MAX_CHARS
SELF_RAG_HIGH_RISK_CLAUSE_TYPES = _config.SELF_RAG_HIGH_RISK_CLAUSE_TYPES
```

- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.self_rag_validation")`
- [ ] Public interface:

```python
def self_rag_validation_agent(state: ContractState) -> dict:
    """LangGraph Node 4. Reads clauses/document_id/ingest_error; returns partial
    dict: clauses (per-clause verdict updates), current_node, node_timings, and
    error_count:1 ONLY when the circuit breaker opened."""
```

- [ ] **CRITICAL — circuit state is a SINGLE MUTABLE HOLDER, not bare locals (plan §2 "Circuit-state holder")**: use `cb = {"consecutive_failures": 0, "open": False, "tripped": False}` and thread it into the helpers. Rebinding an outer `int`/`bool` from a nested function needs `nonlocal`; omit it and Python raises `UnboundLocalError` or silently shadows, so the breaker never opens. Mutating a dict's contents (`cb["open"] = True`) needs no `nonlocal`. Do NOT introduce standalone `consecutive_failures`/`circuit_open`/`circuit_tripped_this_run` locals.
- [ ] **Internal flow** (plan §2 — follow exactly):
  1. `start_time = time.monotonic()`; `current_node = "self_rag_validation"`; `document_id = state.get("document_id", "unknown")`.
  2. **Defensive `ingest_error` check** — if `state.get("ingest_error") is not None` → return empty update (`clauses={}`, `current_node`, `node_timings`); NO reflector calls (AC-11).
  3. `clauses = state.get("clauses", {})`. If falsy → log warning, return empty update (AC-12).
  4. `cb = {"consecutive_failures": 0, "open": False, "tripped": False}`; `clause_updates = {}`.
  5. Iterate clauses **in document order** (sort by `position`). For each `clause_id`, `record`, compute the 5 verdict fields via the branch logic below, then stage `clause_updates[clause_id] = {relevance_verdict, isrel_verdict, issup_verdict, retry_count, final_status}` and emit a per-clause structured log (`logger.info(..., extra={...})`, spec §9).
  6. `elapsed = time.monotonic() - start_time`.
  7. `out = {"clauses": clause_updates, "current_node": current_node, "node_timings": {current_node: elapsed}}`; if `cb["tripped"]`: `out["error_count"] = 1`; return `out`.
- [ ] **Per-clause branch logic** (plan §2 flow, step 6):
  - **Empty/whitespace text** (`(record.get("text") or "").strip() == ""`): all 5 verdicts `None` except `final_status = ValidationStatus.DISCARDED`; log a warning; NO reflector call (Edge Case 6). This is exempt from the circuit's fail-open bulk outcome.
  - `evidence = record.get("evidence_snippets")`; `empty_evidence = evidence is None or len(evidence) == 0`.
  - `ct = _clause_type_value(record.get("clause_type"))`.
  - **BRANCH A** — `empty_evidence and ct in SELF_RAG_HIGH_RISK_CLAUSE_TYPES`: `isrel_verdict = None`. If `cb["open"]` → fail-open (relevance=None, issup=None, retry=None, VALIDATED). Else `relevance = check_relevance(text, SELF_RAG_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME, SELF_RAG_PROMPT_MAX_CHARS)`; `_account(relevance, cb)`; `None` → fail-open; `False` → DISCARD (relevance=False, issup=None, retry=None); `True` → `_issup_loop(text, None, cb)`.
  - **BRANCH B** — `empty_evidence and ct not in ...` (incl. `ct is None`): DISCARD with **zero** reflector calls (all verdicts None, `final_status=DISCARDED`). **Exempt from the fail-open bulk outcome** even when `cb["open"]` (AC-16b; counter untouched).
  - **BRANCH C** — evidence present: if `cb["open"]` → fail-open (all verdicts None, VALIDATED). Else `relevance = check_relevance(...)`; `_account`; `None`→fail-open, `False`→DISCARD (relevance=False, isrel=None, issup=None, retry=None). Else `isrel = check_isrel(text, evidence, ...)`; `_account`; `None`→fail-open (relevance=True, isrel=None, VALIDATED), `False`→DISCARD (relevance=True, isrel=False, issup=None, retry=None). Else `_issup_loop(text, evidence, cb)`.
- [ ] **`_issup_loop(text, evidence, cb)`** (shared by Branch A rescue and Branch C):
  - For `attempt` in `1..SELF_RAG_MAX_ATTEMPTS`: `issup = check_issup(text, evidence, SELF_RAG_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME, SELF_RAG_PROMPT_MAX_CHARS)`; `_account(issup, cb)`. `None` → return `(issup_verdict=None, retry_count=None, VALIDATED)` (fail-open). `True` → return `(True, attempt-1, VALIDATED)` (AC-4/5). `False` → retry.
  - After the loop (all False): return `(False, SELF_RAG_MAX_ATTEMPTS-1, DISCARDED)` (AC-6).
  - NB: only ISSUP `False` retries; an LLM failure (`None`) short-circuits to fail-open — it does NOT spin the loop.
- [ ] **`_account(verdict, cb)`** — circuit bookkeeping: if `verdict is None`: `cb["consecutive_failures"] += 1`; if `cb["consecutive_failures"] >= SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD and not cb["open"]` → `cb["open"] = True`, `cb["tripped"] = True`, log ONE "circuit opened" warning. Else (real verdict): `cb["consecutive_failures"] = 0`.
- [ ] **`_clause_type_value(raw) -> Optional[str]`**: `raw.value if isinstance(raw, ClauseType) else (raw if isinstance(raw, str) else None)` — so the high-risk membership test works whether the record holds the enum or its string value.
- [ ] **Key invariants** (make them hold by construction):
  - Absent evidence → `isrel_verdict = None`, never `False` (so no `isrel=False + VALIDATED` state — AC-16a). `False` is reserved for present-but-off-topic evidence (Branch C ISREL).
  - Fail-open sets the *affected* verdict field to `None` and `final_status = VALIDATED` (a fail-opened VALIDATED carries `issup_verdict=None`, distinguishable from a model-validated `issup_verdict=True` — AC-14, spec §7.4).
  - `error_count` increments **at most once per run**, only when the breaker opens (AC-20).
- [ ] **`final_status`** stores the `ValidationStatus` enum member (`ValidationStatus.VALIDATED` / `ValidationStatus.DISCARDED`), matching the 001 clause-record type.
- [ ] **Pinned `current_node`**: the literal `"self_rag_validation"` (spec §2) — also the `node_timings` key and the graph node name in Task 8. Do NOT derive it.

**Verify**: Run `python -m pytest tests/unit/test_self_rag_validation_agent.py -v` — all 28 tests must PASS.

---

## Task 8: Wire the node into the graph builder

- [ ] Open `app/graph/builder.py`
- [ ] Add the import: `from app.graph.nodes.self_rag_validation_agent import self_rag_validation_agent`
- [ ] Register the node and rewire the tail so `crag_retrieval → self_rag_validation → END`:

```python
graph.add_node("self_rag_validation", self_rag_validation_agent)
graph.add_edge("crag_retrieval", "self_rag_validation")   # was END temporarily
graph.add_edge("self_rag_validation", END)                # → END until feature-007 (RiskScore)
```

- [ ] Remove the old `graph.add_edge("crag_retrieval", END)` line (replaced by the edge into `self_rag_validation`).
- [ ] Update the module docstring "Current scope" note (builder.py:4–8) to include Node 4 and move the "→ END temporarily" comment to the Self-RAG edge.
- [ ] **Add a comment near the node** noting that Self-RAG's outgoing edge is a **plain linear `add_edge`**, deliberately NOT an `add_conditional_edges` — the two permitted conditional edges are CRAG's confidence routing (Node 3) and `route_on_risk` (Node 6). Discarded findings stay in state marked `DISCARDED` and flow along the linear edge; downstream nodes filter on `final_status`. Mirror the existing comment style on `route_after_ingest` / the CRAG node.

**Verify**: Run from `backend/`:
```
python -c "from app.graph.builder import build_graph; g = build_graph(); print(type(g))"
```
Should print the compiled graph type without errors.

---

## Task 9: Write and run integration tests

- [ ] Create file `tests/integration/test_self_rag_validation_graph.py`
- [ ] Tests exercise the compiled graph through Node 4. The three reflective judgments are **mocked** (no live Ollama); CRAG evidence is either produced by the real upstream nodes with embed/web mocked, or injected as a pre-built `clauses` fixture.
- [ ] **CRITICAL — patch targets**: patch `app.graph.nodes.self_rag_validation_agent.check_relevance` / `.check_isrel` / `.check_issup` — i.e. **on the node module** (the node did `from ...reflectors import ...`, binding those names locally). Patching `validators.reflectors.*` would NOT affect the node and could silently hit real Ollama.
- [ ] Also mock the upstream LLM calls (`ollama.chat` for ClauseSplitter and `embed_query`/`web_search` on the CRAG node module) as in the 004/005 integration tests, so no live Ollama/network is needed. Or, for the pure-Node-4 cases, inject a hand-built `clauses` dict as initial state and invoke a graph/subgraph starting at Self-RAG.
- [ ] Write these 6 test functions (plan §2 matrix):

| Test function | Verifies |
|---------------|----------|
| `test_graph_reaches_self_rag_and_ends` | Node1→2→3→4 reaches END; every clause carries a non-None `final_status` |
| `test_graph_ingest_error_skips_self_rag` | Ingest error short-circuits to END; Self-RAG not reached; assert `assert not final_state.get("clauses")` (KeyError caution below) |
| `test_graph_validated_and_discarded_coexist` | A mixed fixture yields both VALIDATED and DISCARDED clauses, all still present in state (AC-19, Edge Case 12) |
| `test_graph_empty_evidence_gate_end_to_end` | In one run: a high-risk empty-evidence clause validates on text; a non-high-risk empty-evidence clause is discarded |
| `test_graph_circuit_open_sets_error_count` | Forcing all judgments to return None opens the breaker → final state `error_count == 1` and remaining LLM-path clauses VALIDATED (fail-open) (AC-15, AC-20) |
| `test_graph_checkpointing_after_self_rag` | State is checkpointed after Self-RAG completes (SqliteSaver; `pytest.skip` if the import path is unavailable, mirroring `test_ingest_graph.py`) |

- [ ] **KeyError caution** (`test_graph_ingest_error_skips_self_rag`): `clauses` is an `Annotated[dict, merge_nested_clause_dicts]` channel with no default; on the error short-circuit it is never written, so `final_state["clauses"]` raises `KeyError`. Assert `assert not final_state.get("clauses")` instead (same subtlety noted in 004/005).
- [ ] For `test_graph_validated_and_discarded_coexist`: drive the mocked reflectors with `side_effect` sequences so one clause validates (Relevance/ISREL/ISSUP all True) and another discards (e.g. Relevance False) in the same run; assert both clause IDs are present with the expected `final_status`.
- [ ] For the checkpointing test, attach the checkpointer the same way `test_ingest_graph.py` / `test_crag_retrieval_graph.py` do.

**Verify**: Run `python -m pytest tests/integration/test_self_rag_validation_graph.py -v` — all 6 tests must PASS (checkpointing may skip if the SQLite saver import path is unavailable — acceptable).

---

## Task 10: Full test suite pass

- [ ] Run the complete suite:
```
python -m pytest tests/ -v --tb=short
```
- [ ] All existing IngestAgent (003), ClauseSplitterAgent (004), and CRAG (005) tests must still pass — Node 4 must not regress them. In particular, the previously-terminal `crag_retrieval → END` edge is now `crag_retrieval → self_rag_validation`; any 005 integration test asserting the graph ends right after CRAG must be updated to expect the Self-RAG node (it should still reach END, now via Node 4).
- [ ] Expected NEW test count for feature 006: 5 (config) + 13 (reflectors) + 28 (node) + 6 (integration) = **52 new tests**.
- [ ] OCR-gated IngestAgent tests may skip if Tesseract is absent — acceptable. No Self-RAG test requires Tesseract, a live Ollama, or network.

---

## Task 11: Linting and type checking

- [ ] Run `black app/ tests/` — auto-format.
- [ ] Run `ruff check app/ tests/` — no lint errors.
- [ ] Run `mypy app/` — no type errors (if mypy is installed). `ollama`/`httpx` are already used elsewhere; add narrow `# type: ignore[...]` only if genuinely needed — do NOT broaden.
- [ ] Do NOT weaken tests to satisfy lint/type checks — fix the implementation instead (constitution §7).

---

## Task 12: Manual live smoke test (optional, not in automated suite)

- [ ] Ensure Ollama is running with `qwen3:14b` (`ollama pull qwen3:14b`).
- [ ] Run the full graph (Node 1→4) on a real multi-clause contract with live Ollama (embedding + web can stay mocked, or run fully live if `bge-m3` + network are available).
- [ ] Confirm: every clause carries a `final_status`; some VALIDATED and some DISCARDED; a fail-opened clause (if any) shows `final_status=VALIDATED` with `issup_verdict=None`; per-clause latency is well under `SELF_RAG_TIMEOUT_SECONDS`; and `error_count` is absent unless the breaker actually opened.
- [ ] Record the validation rate, discard-reason breakdown, and retry distribution (spec §9) — use them to consider tuning `SELF_RAG_MAX_ATTEMPTS` and the prompts / `SELF_RAG_HIGH_RISK_CLAUSE_TYPES` in a follow-up.

**Why**: The automated suite mocks the judgments, so this is the only step that validates real Qwen3 judgment quality, prompt wording (spec §8b Q1), and the true latency envelope (plan §6 risks).

---

## Summary of all files created/modified

| # | File | Action |
|---|------|--------|
| 1 | `app/config.py` | MODIFIED (replace `SELF_RAG_MAX_RETRIES` placeholder with 5 Self-RAG constants; rename) |
| 2 | `app/graph/nodes/validators/__init__.py` | NEW (`format_evidence`) |
| 3 | `app/graph/nodes/validators/reflectors.py` | NEW (`check_relevance`, `check_isrel`, `check_issup`) |
| 4 | `app/graph/nodes/self_rag_validation_agent.py` | NEW (node function) |
| 5 | `app/graph/builder.py` | MODIFIED (add node + rewire crag → self_rag → END) |
| 6 | `tests/unit/test_config.py` | MODIFIED (+5 tests) |
| 7 | `tests/unit/test_self_rag_reflectors.py` | NEW (13 tests) |
| 8 | `tests/unit/test_self_rag_validation_agent.py` | NEW (28 tests) |
| 9 | `tests/integration/test_self_rag_validation_graph.py` | NEW (6 tests) |

---

## Acceptance-criteria traceability (spec §3 → tasks)

| Spec §3 criterion | Covered by |
|-------------------|-----------|
| 1. Per-clause coverage | Task 6/7 (`test_all_clauses_get_final_status`) |
| 2. Relevance fail → discard (short-circuit) | Task 6/7 (`test_relevance_fail_discards_short_circuit`) |
| 3. ISREL fail → discard (short-circuit) | Task 6/7 (`test_isrel_fail_discards_short_circuit`) |
| 4. ISSUP pass first attempt → validated | Task 6/7 (`test_issup_pass_first_attempt_validated`) |
| 5. ISSUP retry then pass → validated | Task 6/7 (`test_issup_retry_then_pass_validated`) |
| 6. ISSUP exhaustion → discard | Task 6/7 (`test_issup_exhaustion_discarded`) |
| 7. Attempt cap enforced | Task 6/7 (`test_attempt_cap_enforced`) |
| 8. Only ISSUP retries | Task 6/7 (`test_only_issup_retries`, `test_relevance_fail_discards_short_circuit`, `test_isrel_fail_discards_short_circuit`) |
| 9. Generative model, not embedding model | Task 1 (`test_self_rag_uses_generative_model`), Task 4/5 (`test_uses_generative_model_only`), Task 6/7 (`test_uses_generative_not_embedding_model`) |
| 10. Uses configured constants | Implicit — a hardcoded value breaks `test_attempt_cap_enforced` / `test_circuit_breaker_opens` / the empty-evidence gate tests (all monkeypatch the re-exposed names) |
| 11. Defensive ingest_error check | Task 6/7 (`test_ingest_error_returns_empty`) |
| 12. Empty clauses input | Task 6/7 (`test_empty_clauses_returns_empty`) |
| 13. Partial update only | Task 6/7 (`test_partial_update_only_no_error_count`) |
| 14. Graceful LLM failure (fail-open) | Task 6/7 (`test_graceful_llm_failure_fail_open`) |
| 15. LLM circuit breaker | Task 6/7 (`test_circuit_breaker_opens`, `test_circuit_resets_on_success`, `test_zero_llm_branches_exempt_from_fail_open_after_trip`), Task 9 (`test_graph_circuit_open_sets_error_count`) |
| 16. Empty/absent evidence — clause-type gated | Task 6/7 (`test_empty_evidence_high_risk_validates_on_text`, `test_empty_evidence_high_risk_relevance_false_discards`, `test_empty_evidence_high_risk_issup_false_discards`, `test_empty_evidence_non_high_risk_zero_llm_discard`, `test_empty_evidence_clause_type_none_discards`), Task 9 (`test_graph_empty_evidence_gate_end_to_end`) |
| 16a. High-risk empty-evidence validates on text | Task 6/7 (`test_empty_evidence_high_risk_validates_on_text`, `test_no_isrel_false_with_validated`) |
| 16b. Non-high-risk empty-evidence zero-LLM discard | Task 6/7 (`test_empty_evidence_non_high_risk_zero_llm_discard`) |
| 17. `current_node` pinned | Task 6/7 (`test_current_node_pinned`) |
| 18. Re-run overwrite | Task 6/7 (`test_rerun_overwrites_verdicts`) |
| 19. Discarded findings inert, not removed | Task 6/7 (`test_discarded_clause_still_present`), Task 9 (`test_graph_validated_and_discarded_coexist`) |
| 20. Circuit-open health signal | Task 6/7 (`test_circuit_open_emits_error_count_once`), Task 9 (`test_graph_circuit_open_sets_error_count`) |
