# Self-RAG Validation Specification

## 1. Problem Statement

The Self-RAG validation node is **Node 4** of the fixed 7-node pipeline defined in `specs/000-constitution.md`. Its responsibility is to decide, **per clause**, whether the clause represents a **finding worth surfacing to the user** — using the merged evidence gathered by CRAG retrieval (Node 3) as the ground it reasons against.

Per constitution §2, this node runs three reflective checks against each clause's merged evidence and produces a binary outcome:

- **Relevance check** — is this clause a substantive provision that could plausibly carry a contractual concern (i.e. is there a candidate finding to evaluate at all)?
- **ISREL check** — is the retrieved evidence actually **relevant** to this clause (does it give the node usable material to judge against)?
- **ISSUP check ("worth flagging")** — does the evidence **support** flagging this clause as a concern worth surfacing?

The constitution also fixes the retry behavior: **retry on ISSUP fail, max 3 attempts**, with a final outcome of either **"Discard finding"** (never shown to the user) or **"Validated finding"** (flows on to RiskScoreAgent, Node 5).

**Why this node exists where it does:** Evidence must already be gathered per clause (Node 3) before it can be judged (Node 4), and findings must be validated (Node 4) before they can be risk-scored (Node 5) and redlined (Node 6). Self-RAG is the **quality gate** between "we have evidence for each clause" and "we have a set of findings worth acting on." Its job is to suppress noise: clauses that are benign, un-analyzable, or unsupported by their evidence are discarded here so downstream nodes and the final report only ever deal with validated findings.

**Model note (constitution §8):** This node uses the **generative** model (`OLLAMA_MODEL_NAME`, Qwen3 via Ollama) for its reflective judgments — the same generative model ClauseSplitterAgent uses. It MUST NOT use the embedding model (`OLLAMA_EMBED_MODEL_NAME`); Self-RAG makes no vector calls of its own (CRAG already produced the evidence). Per constitution §9, this node is LLM-heavy (up to several generative calls per clause over potentially 100–200 clauses), so timeouts, a per-call abort, and a circuit breaker to bound aggregate runtime when Ollama is unreachable are load-bearing, not optional (mirrors CRAG's Edge Case 13).

**Not a conditional edge:** The two conditional edges the constitution permits are CRAG's confidence routing (Node 3) and `route_on_risk` (Node 6). Self-RAG is **not** one of them. Discarded findings are **not** routed away at the graph level — they remain in `ContractState`, marked `DISCARDED`, and `builder.py` wires `self_rag_validation → risk_score` (future) as a plain linear `add_edge`. Downstream nodes filter on `final_status`; Self-RAG never removes clauses from state.

## 2. Inputs and Outputs

### Inputs

Self-RAG reads the following from `ContractState` (as defined in `specs/001-contract-state-schema.md`):

- `clauses`: `Dict[str, Dict[str, Any]]` — the per-clause dict, already carrying Node 2 and Node 3 output. For each clause record this node reads:
  - `text`: `str` — the clause text being judged
  - `evidence_snippets`: `Optional[List[Dict[str, Any]]]` — the merged evidence from CRAG (Node 3); each entry is `{snippet_text: str, source_reference: str}`. May be `[]` (path ran, found nothing) or `None` (no path executed, e.g. empty clause).
  - `path_taken`: `Optional[RetrievalPath]` — read for logging only
  - `confidence_score`: `Optional[float]` — read for logging only; Self-RAG does NOT re-use CRAG's confidence as a gate
  - `position`, `section_number`, `clause_type` — read for logging/ordering only
- `document_id`: `str` — for logging only
- `ingest_error`: `Optional[Dict[str, str]]` — checked defensively; if set, the node returns without processing (same defensive pattern as Nodes 2 and 3)

### Outputs

Self-RAG writes back into the **existing `clauses` dict** using the `merge_nested_clause_dicts` reducer defined in `specs/001-contract-state-schema.md`. It adds the following fields to **each** clause record (it does NOT create new clause IDs and does NOT modify `text`, `position`, `section_number`, `clause_type`, `confidence_score`, `path_taken`, or `evidence_snippets`):

| Field | Type | Description |
|-------|------|-------------|
| `relevance_verdict` | `Optional[bool]` | Result of the Relevance check. `True` = clause is a substantive, analyzable provision; `False` = not worth analyzing. `None` only if the check could not be run (LLM failure at this stage, or clause skipped). |
| `isrel_verdict` | `Optional[bool]` | Result of the ISREL check. `True` = evidence is present **and** relevant to this clause; `False` = evidence is present but off-topic. `None` if ISREL was not assessable — either **no evidence existed** to judge relevance against (the empty-evidence path, §4.3), or the check was not reached (Relevance failed) / could not be run. Note the deliberate split: absent evidence → `None` (not-assessable), NOT `False` (which is reserved for present-but-off-topic evidence). |
| `issup_verdict` | `Optional[bool]` | Result of the ISSUP ("worth flagging") check — its **final** value across all attempts. `True` = evidence supports flagging; `False` = not supported after all attempts. `None` if the check was not reached (Relevance or ISREL failed) or could not be run. |
| `retry_count` | `Optional[int]` | Number of **retries** of the ISSUP check (0 = passed or failed on the first attempt; see §7.2 for the attempt/retry semantics). `None` if ISSUP was never reached. |
| `final_status` | `Optional[ValidationStatus]` | `ValidationStatus.VALIDATED` (`"validated"`) or `ValidationStatus.DISCARDED` (`"discarded"`). Present for **every** processed clause. |

These field names are already reserved for exactly this purpose in `specs/001-contract-state-schema.md` §3 (the clause-record comment block). This spec introduces no new clause-record field names.

**Partial-update rule (constitution §5):** In the normal case the node returns ONLY `clauses` (carrying the per-clause verdict updates), plus `current_node` and `node_timings` for pipeline metadata. The **sole** exception is the circuit-breaker health signal (§8a R5): when the LLM backend is declared down for the run, the node additionally returns `error_count: 1` (exactly once — see §2 Error accounting). It does NOT return or modify any IngestAgent-, ClauseSplitter-, or CRAG-owned keys, any RiskScore/Redline/Report keys, or the top-level `evidence_trail` (compiled later by ReportAgent, Node 7).

**Pinned state-key value:** `current_node` is set to the string `"self_rag_validation"`, and that same string is the key used in the `node_timings` update. This is the node's *state-key identity*, fixed here so it does not drift from the graph node name registered in `builder.py` (constitution §8). Mirrors how Nodes 2 and 3 pin `"clause_splitter"` / `"crag_retrieval"`.

**Error accounting:** A **single-clause** LLM failure does NOT increment `error_count` — it is a graceful degradation with a defined fail-open outcome (§4.4), matching Nodes 2 and 3. The **one** case that does increment is the **circuit breaker opening** (§8a R5): a wholesale backend outage that fail-opens the rest of the run is a genuine pipeline-health event and must not be indistinguishable from a clean run, so the node returns `error_count: 1` **once** when the circuit opens (via the `operator.add` reducer). It is capped at one increment per run — the breaker opens at most once — so a degraded run reads as exactly one Self-RAG error, never one-per-clause. This is a health signal, not a hard abort; downstream behavior on `error_count` is unchanged.

### `ValidationStatus` enum

Already defined in `specs/001-contract-state-schema.md`; this spec introduces no new enum values:

```python
class ValidationStatus(str, Enum):
    DISCARDED = "discarded"
    VALIDATED = "validated"
```

## 3. Acceptance Criteria

Each criterion is written to become a test case directly. Throughout, the three checks are mocked at the LLM boundary (no live Ollama) so verdicts are deterministic fixtures.

1. **Per-clause coverage**: Given a state whose `clauses` dict has N clauses (N ≥ 1), after the node runs, every one of the N clause records has a non-`None` `final_status` (`VALIDATED` or `DISCARDED`) — no clause is skipped.

2. **Relevance fail → discard**: For a clause whose Relevance check returns `False`, the result is `relevance_verdict = False`, `isrel_verdict = None`, `issup_verdict = None`, `retry_count = None`, `final_status = DISCARDED`. No ISREL or ISSUP LLM call is made for that clause (short-circuit, §7.3).

3. **ISREL fail → discard**: For a clause that passes Relevance but whose ISREL check returns `False`, the result is `relevance_verdict = True`, `isrel_verdict = False`, `issup_verdict = None`, `retry_count = None`, `final_status = DISCARDED`. No ISSUP LLM call is made.

4. **ISSUP pass first attempt → validated**: For a clause that passes Relevance and ISREL and whose ISSUP check returns `True` on the first attempt, the result is `relevance_verdict = True`, `isrel_verdict = True`, `issup_verdict = True`, `retry_count = 0`, `final_status = VALIDATED`.

5. **ISSUP retry then pass → validated**: For a clause whose ISSUP check returns `False` then `True` on a later attempt (within the cap), `issup_verdict = True`, `final_status = VALIDATED`, and `retry_count` equals the number of retries taken before the passing attempt (e.g. one prior `False` → `retry_count = 1`).

6. **ISSUP exhaustion → discard**: For a clause whose ISSUP check returns `False` on every attempt up to `SELF_RAG_MAX_ATTEMPTS`, the result is `issup_verdict = False`, `final_status = DISCARDED`, and `retry_count = SELF_RAG_MAX_ATTEMPTS - 1`.

7. **Attempt cap enforced**: No clause makes more than `SELF_RAG_MAX_ATTEMPTS` ISSUP LLM calls (test by counting calls with the constant monkeypatched to a small value).

8. **Only ISSUP retries**: A Relevance or ISREL `False` never triggers a retry — those checks are attempted exactly once. (Assert exactly one Relevance call and, when reached, exactly one ISREL call.)

9. **Uses the generative model, not the embedding model**: Every LLM call uses `OLLAMA_MODEL_NAME`; the node never references `OLLAMA_EMBED_MODEL_NAME`. A test asserts these two constants are distinct and that the embedding model name is never passed to the node's LLM call.

10. **Uses configured constants**: The max attempts, per-call timeout, circuit-breaker threshold, and any prompt-truncation limit are all read from `app.config` (constitution §3), never hardcoded inline in node logic.

11. **Defensive `ingest_error` check**: If `ingest_error` is set (non-`None`) in the input state, the node returns immediately with an empty `clauses` update and makes no LLM calls.

12. **Empty clauses input**: If the input `clauses` dict is empty (`{}`), the node returns an empty `clauses` update without any LLM calls, and logs a warning.

13. **Partial update only**: In the normal (no-outage) case the returned dict contains ONLY the keys `clauses`, `current_node`, and `node_timings`, with NO `error_count` and no keys owned by other nodes. The single permitted addition is `error_count: 1` when — and only when — the circuit breaker opened during the run (AC-20).

14. **Graceful LLM failure**: If an LLM call raises or times out for a clause, that clause receives the **default outcome** (§4.4 / §8a R3 — fail-open `VALIDATED`), the affected verdict field is `None`, the pipeline does NOT crash, and other clauses still process. A single-clause failure alone does NOT increment `error_count`.

15. **LLM circuit breaker**: When LLM calls fail for `SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD` clauses **consecutively**, the node marks the LLM backend as down for the remainder of the run and applies the fail-open default outcome to all remaining clauses **that would otherwise consult the LLM**, without issuing further LLM calls (no per-clause timeout wait). A single "circuit opened" warning is logged; the consecutive-failure counter resets on any successful LLM call. **Zero-LLM branches are exempt from the fail-open bulk outcome:** an empty/whitespace-text clause (Edge Case 6) and a non-high-risk empty-evidence clause (AC-16b, Branch B) reach `DISCARDED` deterministically without any LLM call, so they stay `DISCARDED` even after the circuit opens — the fail-open default only applies where an LLM call was actually going to be made.

16. **Empty / absent evidence — clause-type gated (§8a R4)**: A clause whose `evidence_snippets` is `[]` or `None` is handled per §4.3: if its `clause_type` is in `SELF_RAG_HIGH_RISK_CLAUSE_TYPES`, the node runs Relevance then an ISSUP judgment **on clause text alone** (skipping ISREL, which is left `None`), and may `VALIDATE` it; otherwise (any other type, or `clause_type is None`) the clause is `DISCARDED` with **no LLM call**. Never crashes either way.

16a. **High-risk empty-evidence clause can validate on text**: For an empty-evidence clause whose `clause_type ∈ SELF_RAG_HIGH_RISK_CLAUSE_TYPES` that passes Relevance and whose clause-text ISSUP returns `True`, the result is `relevance_verdict = True`, `isrel_verdict = None`, `issup_verdict = True`, `final_status = VALIDATED`. (No `isrel_verdict = False` + `VALIDATED` contradiction ever occurs, because absent evidence yields `isrel_verdict = None`.)

16b. **Non-high-risk empty-evidence clause is discarded without an LLM call**: For an empty-evidence clause whose `clause_type` is not in the high-risk set (including `None`), the result is `relevance_verdict = None`, `isrel_verdict = None`, `issup_verdict = None`, `retry_count = None`, `final_status = DISCARDED`, and the node makes **zero** LLM calls for that clause (assert by counting calls).

20. **Circuit-open health signal**: On a run where the circuit breaker opens, the returned partial dict includes `error_count: 1` (exactly one, regardless of how many clauses were fail-opened afterward). On a run where the breaker never opens, the returned dict includes no `error_count` key. (Assert both directions.)

17. **`current_node` pinned**: After the node runs, `current_node == "self_rag_validation"` and the same string is the key in the returned `node_timings` dict.

18. **Re-run overwrite (defensive)**: If a clause already carries verdict fields (e.g. a re-run), the node overwrites `relevance_verdict`, `isrel_verdict`, `issup_verdict`, `retry_count`, and `final_status`; the `merge_nested_clause_dicts` reducer preserves the non-verdict fields (`text`, `evidence_snippets`, etc.).

19. **Discarded findings are inert, not removed**: A `DISCARDED` clause remains present in the returned `clauses` update (marked discarded) — the node does not delete clause IDs. (Confirms Self-RAG is not a graph-level conditional edge.)

## 4. Edge Cases

1. **`ingest_error` set**: Return immediately with no validation work (AC-11). Same defensive pattern as Nodes 2 and 3.

2. **Empty `clauses` dict**: Return an empty `clauses` update, log a warning, make no LLM calls (AC-12).

3. **Empty / absent evidence for a clause** (`evidence_snippets` is `[]` or `None`): **Decided (§8a R4 — clause-type-gated fallback).** ISREL cannot be assessed (there is no evidence to judge relevance against), so `isrel_verdict = None` (not `False`, which is reserved for present-but-off-topic evidence). The clause is then routed by its `clause_type`:

   - **High-risk type** (`clause_type ∈ SELF_RAG_HIGH_RISK_CLAUSE_TYPES`, §6): the false-negative cost of silently dropping these is too high, so the node **rescues** the clause with an evidence-free judgment — it runs **Relevance** on the clause text, and if that passes, runs **ISSUP on the clause text alone** (with the normal retry cap; ISREL is skipped, staying `None`). `ISSUP True → VALIDATED`; `ISSUP False after the cap → DISCARDED`. This targets exactly the "self-evidently risky clause CRAG happened to find no evidence for" case (e.g. an uncapped-liability clause) without leaning on the LLM for every unsupported clause.
   - **Any other type, or `clause_type is None`**: no evidence + not a high-stakes category ⇒ treat as noise and **DISCARD with zero LLM calls** (`relevance_verdict = None`, `isrel_verdict = None`, `issup_verdict = None`, `retry_count = None`, `final_status = DISCARDED`). This keeps the false-positive floodgate shut and bounds LLM load.

   **Rationale for the gate:** blanket-discard (the original R4) risks dropping genuinely dangerous unretrieved clauses; blanket-validate-on-text risks a false-positive flood and heavy LLM load. Gating on `clause_type` — which Node 2 already assigns — spends the unaided-LLM judgment only where a miss is most costly. **Known residual gap:** a dangerous clause that Node 2 left `clause_type = None` (unclassified) is discarded here; the discard-reason breakdown (§9.2) and empty-evidence metric (§9.6) are the tripwires for whether unclassified clauses are a material false-negative source, and `SELF_RAG_HIGH_RISK_CLAUSE_TYPES` is a tunable knob if so.

4. **LLM call fails / times out / returns malformed output for a clause**: On any unrecoverable LLM failure (Ollama unreachable, timeout > `SELF_RAG_TIMEOUT_SECONDS`, unparseable response) at any check, apply the **default outcome** (§8a R3 — **fail-open: `final_status = VALIDATED`**, so a potential risk is surfaced for human review rather than silently hidden), set the affected verdict field to `None`, log a rate-limited warning, and continue with the next clause. Never crash. **Consecutive-failure protection:** if the backend is down entirely, paying `SELF_RAG_TIMEOUT_SECONDS` per clause is pathological over a large contract — the circuit breaker in Edge Case 8 bounds this.

5. **ISSUP retry exhaustion**: If ISSUP returns `False` on every attempt up to `SELF_RAG_MAX_ATTEMPTS`, the finding is `DISCARDED` with `issup_verdict = False` and `retry_count = SELF_RAG_MAX_ATTEMPTS - 1` (AC-6). This is the normal "not worth flagging after repeated checks" outcome, not an error.

6. **Empty / whitespace-only clause text**: If a clause's `text` is empty or whitespace (a defensive case — CRAG would have set `evidence_snippets = None` for it), skip all LLM checks: set `relevance_verdict = None`, `isrel_verdict = None`, `issup_verdict = None`, `retry_count = None`, `final_status = DISCARDED`, and log a warning. Other clauses still process.

7. **Very large clause count**: The node processes clauses strictly sequentially (mirrors CRAG §7.6). Per-clause runtime is bounded by `SELF_RAG_TIMEOUT_SECONDS` × the (short-circuited) number of checks. The aggregate worst case (backend down → every clause pays the timeout on every attempt) is bounded by the circuit breaker (Edge Case 8).

8. **LLM backend down mid-run (circuit breaker)**: After `SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD` **consecutive** LLM failures, the node stops attempting LLM calls for the rest of this run and applies the default outcome (Edge Case 4) to every remaining clause **that would otherwise have made an LLM call**. Clauses on a zero-LLM path — empty/whitespace text (Edge Case 6) and non-high-risk empty-evidence (Branch B, §7.5) — still reach their deterministic `DISCARDED` outcome; the fail-open bulk default does not override them (they never depended on the LLM). A single "circuit opened" warning is logged **and the node emits the `error_count: 1` health signal** (§8a R5 / AC-20) — so a wholesale fail-open run is distinguishable downstream from a clean run where everything genuinely validated. The counter resets on any successful LLM call, so intermittent single failures never trip it (and never emit the health signal). This is a **routing/runtime guarantee** bounding aggregate node time when Ollama is unreachable; it is per-run only and not persisted across pipeline invocations. Directly mirrors CRAG's Edge Case 13 / AC-16.

9. **Very long clause text or evidence**: The clause text and the concatenated evidence snippets fed into each prompt are truncated to `SELF_RAG_PROMPT_MAX_CHARS` before the LLM call, to bound prompt size. Truncation is logged at debug level.

10. **Clause already carries verdict fields (re-run)**: The node overwrites all five verdict fields for each clause it processes; the reducer preserves the non-verdict fields (AC-18).

11. **`confidence_score = None` from CRAG** (CRAG could not embed the clause): Self-RAG still runs its checks on whatever `evidence_snippets` exist; it does not require a CRAG confidence score. If evidence is also absent, Edge Case 3 applies.

12. **All clauses discarded** / **all clauses validated**: Both are valid outcomes. The node must not assume any particular mix; an all-discarded document simply means nothing flows as a finding to Node 5, and an all-validated document means every clause is risk-scored downstream.

## 5. Out of Scope

Self-RAG validation does NOT handle:

1. **Assigning a risk level (Low/Medium/High)** — that belongs to **RiskScoreAgent (Node 5)**, `specs/007-*` (future). Self-RAG only decides *validated vs discarded*, not *how risky*.

2. **Drafting safer clause language (redlining)** — **RedlineAgent (Node 6)**. Self-RAG produces no `suggested_rewrite`.

3. **Compiling the final report and the top-level `evidence_trail`** — **ReportAgent (Node 7)**. Self-RAG writes only per-clause verdict fields.

4. **Gathering or scoring evidence / retrieval-path routing** — **CRAG retrieval (Node 3)**, `specs/005-crag-retrieval`. Self-RAG consumes `evidence_snippets` as given and does not perform its own retrieval, embedding, or web search.

5. **The `route_on_risk` conditional edge** — that is Node 6's edge (constitution §2). Self-RAG's outgoing graph edge is a plain linear `add_edge` to Node 5; discarded findings are marked, not routed away (§1, AC-19).

6. **Persisting an intermediate "candidate finding" statement** — 001-contract-state-schema.md reserves no field for a generated finding text, so any candidate concern the node reasons about internally is ephemeral and NOT written to state. Persisting it would be a 001-schema change under constitution §10 (§8b Q4 — deferred).

7. **Human-in-the-loop review of discarded findings** — discarded findings are "never shown to the user" per constitution §2; there is no review/override UI (also consistent with the PERMANENTLY CUT "no audit log UI" item).

8. **Bounded-parallelism over clauses** — sequential for Phase 1, matching CRAG §7.6; a concurrency knob is deferred.

## 6. Configurable Constants

Per constitution §3, all thresholds live in `backend/app/config.py`. A `SELF_RAG_MAX_RETRIES = 3` placeholder already exists there; this spec **supersedes and clarifies** it (see §8b Q2 on the retry-vs-attempt naming) and adds the remaining constants:

```python
# ── Self-RAG validation thresholds ─────────────────────────────────────────────
# Source: specs/006-self-rag-validation/spec.md §6

SELF_RAG_MAX_ATTEMPTS: int = 3
# Maximum number of ISSUP ("worth flagging") judgment attempts per clause,
# per constitution §2 ("retry on ISSUP fail, max 3 attempts"). The FIRST
# attempt plus retries together may not exceed this. retry_count = attempts - 1,
# so retry_count ∈ {0, 1, 2} at this default. NOTE: this replaces/renames the
# existing SELF_RAG_MAX_RETRIES placeholder — see §8b Q2.

SELF_RAG_TIMEOUT_SECONDS: int = 120
# Wall-clock timeout for a single Self-RAG LLM call (Relevance / ISREL / one
# ISSUP attempt) via Ollama. Mirrors CLAUSE_SPLITTER_TIMEOUT_SECONDS; generous
# headroom for local Qwen3 per constitution §9. On timeout the clause takes the
# default outcome (spec §4.4).

SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD: int = 5
# Number of CONSECUTIVE LLM failures after which the node declares the backend
# down for the rest of the run and applies the default outcome to all remaining
# clauses (skipping per-clause timeouts). Resets on any success. Bounds aggregate
# runtime when Ollama is unreachable (spec §4.8, AC-15). Mirrors CRAG's
# CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD.

SELF_RAG_PROMPT_MAX_CHARS: int = 6000
# Clause text + concatenated evidence snippets are truncated to this length
# before each LLM call, to bound prompt size (spec §4.9).

SELF_RAG_HIGH_RISK_CLAUSE_TYPES: frozenset[str] = frozenset({
    "liability",
    "termination",
    "intellectual_property",
    "dispute_resolution",
})
# Clause types (ClauseType.value strings, specs/001 §3) for which an
# empty-evidence clause is RESCUED via an evidence-free clause-text judgment
# instead of being discarded (spec §4.3 / §8a R4). These are the categories
# where a single clause most materially shifts risk allocation and a silent
# false negative is costliest: uncapped/one-sided liability, unilateral or
# for-convenience termination, IP assignment/ownership, and forced-forum /
# arbitration dispute-resolution terms. Kept deliberately narrow to avoid a
# false-positive flood and unbounded LLM load on unsupported clauses; widen
# only if the empty-evidence discard metric (§9.6) shows real misses. Types
# NOT listed (and clause_type=None) fall through to zero-LLM-call discard.
```

(All defaults are starting points to be tuned against real sample contracts after implementation. The node also uses the existing shared `OLLAMA_MODEL_NAME` for its generative calls — it introduces no new model constant.)

## 7. Provisionally Pinned Design (pending Open Questions)

The four architecturally significant decisions are now locked (§8a); the pins below that touch the still-open, plan-safe items (§8b) may still be tuned after implementation.

### 7.1 Three checks as a sequential short-circuit gate
The three checks run in order — **Relevance → ISREL → ISSUP** — and short-circuit: a `False` at Relevance skips ISREL and ISSUP; a `False` at ISREL skips ISSUP. Only if both pass is ISSUP attempted (with retries). Short-circuiting is the natural reading of the constitution's ordered list and minimizes LLM calls on clauses destined to be discarded (important under constitution §9). The alternative — one combined LLM call returning all three verdicts — was considered and rejected (§8a R2: three sequential calls with short-circuit).

### 7.2 Attempt vs retry counting
`SELF_RAG_MAX_ATTEMPTS` bounds **total ISSUP attempts** (constitution: "max 3 attempts"). `retry_count` records **retries** = `attempts_taken - 1`. A first-attempt pass or a first-attempt-and-only failure both yield `retry_count = 0`; exhausting 3 attempts yields `retry_count = 2`. The existing `SELF_RAG_MAX_RETRIES = 3` placeholder is ambiguous against this (3 retries would be 4 attempts) — see §8b Q2.

### 7.3 What "Relevance" vs "ISREL" mean
Provisionally: **Relevance** = a property of the **clause** (is it a substantive, analyzable provision worth evaluating at all?); **ISREL** = a property of the **evidence** (is the retrieved evidence relevant to this clause?). This split gives the two checks distinct jobs, since classic Self-RAG's ISREL alone already means "is-relevant." Confirmation needed — §8b Q1.

### 7.4 Default outcome on unrecoverable LLM failure
**Decided (§8a R3): fail-open** (`VALIDATED`) so potential risks are surfaced for human review rather than silently hidden — appropriate for a risk tool where a false negative is the costlier error. This also governs the circuit-breaker's bulk outcome (Edge Case 8) and could flood downstream nodes if Ollama is down; that health-signal tension is resolved by §8a R5 (a single `error_count` increment when the breaker opens, §7.6).

### 7.5 Empty-evidence handling: clause-type-gated fallback (§8a R4)
When a clause reaches Self-RAG with no evidence (`evidence_snippets` `[]`/`None`), ISREL is not assessable and is set to `None`. The clause is then gated on `clause_type`:

```
if evidence is empty:
    isrel_verdict = None                      # not-assessable (NOT False)
    if clause_type in SELF_RAG_HIGH_RISK_CLAUSE_TYPES:
        run Relevance(clause_text)            # cheap analyzability guard
        if Relevance is False → DISCARD (relevance_verdict=False, issup=None, retry=None)
        else run ISSUP(clause_text alone) with retries   # ISREL skipped
             → VALIDATED if ISSUP True, else DISCARD
    else:                                     # other type, or clause_type is None
        DISCARD with zero LLM calls           # all verdicts None
```

This is the operational form of §4.3. The key invariant: absent evidence yields `isrel_verdict = None`, never `False`, so no clause is ever left in the contradictory `isrel_verdict = False` + `final_status = VALIDATED` state (the same class of inconsistency corrected in the 001 schema example). The high-risk set is small by design (§6) so the unaided-LLM judgment is spent only where a silent miss is costliest; everything else short-circuits to a no-LLM discard, bounding both false positives and Ollama load. Note this is the **only** path where ISSUP runs without ISREL having passed — it is a deliberate, gated exception, not the general flow (§7.1).

### 7.6 Circuit-open health signal (§8a R5)
Per-clause fail-open (§7.4) is silent by design — one flaky LLM call should not raise a pipeline error. But a **circuit-breaker open** means the backend is down and the rest of the run is being fail-opened wholesale, which must not look identical to a clean run. So when (and only when) the breaker opens, the node returns `error_count: 1` **once** (the `operator.add` reducer accumulates it into the pipeline total). It is exactly one increment per run — the breaker opens at most once — never one-per-clause. This is a health signal for observability, not a hard abort; it does not alter Self-RAG's own control flow.

## 8. Design Decisions and Open Questions

### 8a. Resolved (locked before plan.md)

The architecturally significant questions — the ones that shape the plan's control flow, not just a constant — were resolved with the user on 2026-07-04. They are now the pinned design of this spec (reflected in §4/§7 and the ACs); they are recorded here, not left open.

- **R1 — What a retry does (was §8.3):** Each retry **re-runs the same ISSUP judgment** to guard against LLM non-determinism / transient errors. Self-RAG does **not** regenerate a candidate finding statement. Rationale: Node 4 is a **gate/validator**, not a generator — finding/risk text is authored downstream at Nodes 5–6. Regenerating findings here would hand Node 4 a generation role it does not own (duplicating Nodes 5–6), violate state minimality (§6), and force a 001-schema change to persist finding text. Keeping the retry a re-sample of ISSUP directly targets the realistic failure (a genuinely flag-worthy clause getting a spurious "no"). Confirms §7 and keeps §5.6 (no finding-text persistence) intact.

- **R2 — Call structure (was §8.6):** **Three sequential LLM calls with short-circuit** — Relevance → ISREL → ISSUP, stopping early (discard) as soon as one fails. Not a single combined call. This keeps "retry only ISSUP" clean and avoids LLM calls on clauses destined to be discarded (matters under constitution §9). Confirms §7.1.

- **R3 — Failure mode (was §8.4):** **Fail-open** — an unrecoverable LLM failure (timeout, unreachable Ollama, circuit-breaker open) defaults the clause to `final_status = VALIDATED` so a potential risk is surfaced for human review rather than silently dropped, consistent with a risk-detector's bias against false negatives. This also governs the circuit breaker's bulk outcome (Edge Case 8). The health-signal tension it creates (silently validating everything when Ollama is down) is resolved by R5. Confirms §4.4/§7.4.

- **R4 — Empty-evidence handling (was §8.5): clause-type-gated fallback.** A clause CRAG found no evidence for (`evidence_snippets` `[]`/`None`) sets `isrel_verdict = None` (not-assessable), then routes on `clause_type`: if it is in `SELF_RAG_HIGH_RISK_CLAUSE_TYPES` (§6), the node runs Relevance + an ISSUP judgment **on clause text alone** and may validate it; otherwise (any other type, or `None`) it is **discarded with no LLM call**. This supersedes the original blanket-discard: it rescues exactly the high-stakes "risky clause CRAG missed" case (uncapped liability, unilateral termination, IP assignment, forced-forum dispute terms) while keeping the false-positive/LLM-load floodgate shut for everything else. Residual gap: unclassified (`clause_type = None`) dangerous clauses are still discarded — tracked via §9.2/§9.6, tunable via the high-risk set. Detailed flow in §7.5. Confirms §4.3.

- **R5 — Circuit-open health signal (companion to R3):** Because R3 fail-opens, a Self-RAG that silently validates everything when Ollama is down would be indistinguishable from a clean run. So when the **circuit breaker opens**, the node emits `error_count: 1` **once** per run (via `operator.add`) — a health signal, not a hard abort. A single-clause fail-open does NOT increment; only a wholesale outage does. Detail in §7.6. (This resolves what was formerly the open §8b `error_count` question.)

### 8b. Remaining open questions (plan-safe — provisional pins are fine for plan.md)

These do not change the plan's architecture — each is a constant, a naming choice, or a prompt-wording matter. The pinned defaults are safe to plan and implement against; revisit during/after implementation if eval warrants.

1. **Relevance vs ISREL semantics.** Is the §7.3 split correct — Relevance = clause-is-analyzable, ISREL = evidence-is-relevant? Or should both concern the evidence (closer to literal Self-RAG, in which case one becomes near-redundant)? Affects prompt wording, not control flow. Pinned per §7.3.

2. **Attempt vs retry count, and the `SELF_RAG_MAX_RETRIES` placeholder.** Pinned choice (§6): treat 3 as total attempts and rename the constant `SELF_RAG_MAX_RETRIES` → `SELF_RAG_MAX_ATTEMPTS`. A rename to execute in the plan; sound as pinned.

3. **Persisting the candidate-finding statement.** 001 reserves no field for finding text, so it stays ephemeral (§5.6). Default: defer. (R1 removed the main pressure to add it; only revisit if the report must later quote *why* a clause was flagged beyond the raw evidence — a 001-schema change under constitution §10.)

4. **Circuit breaker inclusion.** §6 adds `SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD` mirroring CRAG; its bulk outcome follows R3 (fail-open) and its opening emits the R5 health signal. Default: keep it (mirrors CRAG Edge Case 13). Confirmed as sound.

*(The former `error_count` open question is now resolved — see §8a R5.)*

## 9. Evaluation

Because this node performs retry-validated findings, the following metrics MUST be logged per run for later tuning (per `specs/002-tech-stack.md` §3i eval tooling), following the `logger.info(..., extra={...})` structured-log pattern established in `crag_retrieval_agent.py` — these live in **log records, NOT in `ContractState`**, which carries only aggregate `node_timings["self_rag_validation"]`.

1. **Validation rate** — fraction of clauses ending `VALIDATED` vs `DISCARDED` (per document and aggregate). The headline signal of how much noise the gate suppresses.
2. **Discard-reason breakdown** — of discarded clauses, the fraction discarded at **Relevance**, at **ISREL** (present-but-off-topic evidence), at **ISSUP exhaustion**, at the **empty-evidence non-high-risk short-circuit** (zero-LLM discard, §7.5), at the **empty-evidence high-risk ISSUP-on-text** path, and via the **default outcome** (LLM failure). Tells us which gate does the filtering — and specifically how many clauses the empty-evidence gate drops without an LLM call.
3. **Verdict distribution** — pass/fail counts for each of the three checks independently.
4. **Retry success rate** — of clauses that failed ISSUP at least once, the fraction that eventually validated within the attempt cap; plus the distribution of `retry_count`.
5. **Retry-exhaustion rate** — fraction of ISSUP-reaching clauses that hit `SELF_RAG_MAX_ATTEMPTS` and were discarded (calibrates whether the cap is too low/high).
6. **Empty-evidence rate & gated-fallback outcomes** — fraction of clauses reaching Self-RAG with `evidence_snippets` `[]`/`None` (a coverage-gap signal, cross-referenced with CRAG's empty-evidence metric), split by whether they hit the **high-risk rescue** path (and its validate/discard split) or the **zero-LLM discard** path — and, of the zero-LLM discards, how many had `clause_type = None`. This is the direct tripwire for the §7.5 residual gap: if unclassified or non-listed clauses are being discarded and later prove risky, this metric shows it and motivates widening `SELF_RAG_HIGH_RISK_CLAUSE_TYPES`.
7. **LLM failure rate & circuit-breaker events** — fraction of clauses that took the default outcome due to LLM failure, and count of runs where the circuit opened (each of which emits `error_count: 1`, §7.6) — should be ~0 in a healthy deployment.
8. **Latency** — per-check LLM latency and per-clause total (log records only), plus total node wall-clock time (the value that also feeds `node_timings`). Supports constitution §9 tuning.
9. **False-flag / false-negative rates (requires ground truth)** — when labeled sample contracts are available, compare `final_status` against human labels to estimate false-positive (validated-but-benign) and false-negative (discarded-but-risky) rates. These cannot be computed from logs alone; the per-clause verdict logs above are the raw material for that offline analysis.

These metrics directly support tuning `SELF_RAG_MAX_ATTEMPTS`, `SELF_RAG_TIMEOUT_SECONDS`, and the empty-evidence / fail-open policies against real sample contracts once implementation is complete.
