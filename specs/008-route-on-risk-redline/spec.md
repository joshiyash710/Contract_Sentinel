# route_on_risk + Redline Specification

> Feature 008 — **Node 6** of the fixed 7-node pipeline. This feature owns
> BOTH the `route_on_risk` conditional edge AND the RedlineAgent node it
> routes to, plus its sibling SkipRedline node. Per constitution §2 these are
> a single architectural unit ("6. Conditional edge route_on_risk"), so they
> are specced together here.

## 1. Problem Statement

Node 6 is the point in the pipeline where a **severity-ranked set of validated
findings** (produced by RiskScore, Node 5) is turned into **actionable safer
clause language**. It has three graph elements, all owned by this feature:

Per constitution §2:

> 6. Conditional edge route_on_risk:
>    - risk found -> RedlineAgent (drafts safer clause language)
>    - no risk -> SkipRedline (clause marked clean)

1. **`route_on_risk`** — the conditional edge. It sits immediately after
   `risk_score` (Node 5) and decides whether the document has any finding worth
   redlining. This is **one of exactly two domain-logic conditional edges the
   constitution permits** (the other is CRAG's confidence routing, Node 3). It
   is the **first and only** such edge realized as a genuine graph-level
   `add_conditional_edges` (see §7.1 for why, and how it differs from CRAG).

2. **RedlineAgent** (`redline` node) — the "risk found" branch. For each
   redline-eligible clause it drafts a **safer rewrite** of the clause language
   and writes it to `suggested_rewrite`. It uses the generative model
   (`OLLAMA_MODEL_NAME`), one call per redlined clause, mirroring RiskScore's
   per-finding LLM pattern.

3. **SkipRedline** (`skip_redline` node) — the "no risk" branch. A lightweight
   node that records that the document needed no redlining and passes state
   through unchanged (see §7.4 — "clause marked clean" is emergent, not a new
   field).

Both branches re-converge downstream: they each flow to ReportAgent (Node 7,
future feature 009). Until Node 7 exists, both flow to `END` (§7.5).

**Why this node exists where it does.** RiskScore (Node 5) deliberately stops at
*severity assignment* — it writes `risk_level`/`risk_rationale` but explicitly
produces **no** `suggested_rewrite` (RiskScore spec §5.3, AC-21: "`suggested_rewrite`
is owned by Node 6"). Node 6 is the stage that consumes that severity ranking and
either (a) drafts remediation for the risky clauses (RedlineAgent), or (b) records
that there was nothing to remediate (SkipRedline). It is the **remediation stage**
between "these findings are ranked by severity" (Node 5) and "compile the final
report + evidence trail" (Node 7).

**Model note (constitution §8).** RedlineAgent uses the **generative** model
(`OLLAMA_MODEL_NAME`, Qwen3 via Ollama) — the same model ClauseSplitter, Self-RAG,
and RiskScore use. It MUST NOT use the embedding model
(`OLLAMA_EMBED_MODEL_NAME`); Redline makes no vector calls (retrieval and
validation are already done). Per constitution §9 it makes one generative call per
**redlined** finding, so per-call timeout, per-call abort, and a circuit breaker
to bound aggregate runtime when Ollama is unreachable are load-bearing, not
optional (mirrors CRAG Edge Case 13, Self-RAG Edge Case 8, RiskScore Edge Case 5).
Because only redline-eligible findings are rewritten — a subset of validated
findings, itself a small fraction of all clauses — Redline's LLM load is the
**lightest generative load** of any node in the pipeline. `route_on_risk` and
SkipRedline make **no** LLM calls at all.

## 2. Inputs and Outputs

All fields reference `ContractState` as defined in
`specs/001-contract-state-schema.md`. This spec introduces **no new
clause-record field names** — `suggested_rewrite` is already reserved for exactly
this purpose in `001` §3 (clause-record comment block:
`suggested_rewrite: Optional[str]`).

### 2.1 `route_on_risk` (conditional edge / routing function)

**Reads** from `ContractState`:
- `clauses`: `Dict[str, Dict[str, Any]]` — for each clause record it reads:
  - `final_status`: `Optional[ValidationStatus]` — only `VALIDATED` records are
    considered; `DISCARDED` / `None` are ignored (they carry no `risk_level`).
  - `risk_level`: `Optional[RiskLevel]` — the severity Node 5 assigned. The
    routing decision is: does at least one clause satisfy the redline threshold
    (§6, `REDLINE_RISK_THRESHOLD`)?
- `ingest_error`: `Optional[Dict[str, str]]` — checked defensively; if set, route
  to `skip_redline` (nothing was ever scored — Edge Case 1).

**Returns** (a routing string, NOT a state update — a routing function returns the
name of the next node; it never mutates state):
- `"redline"` — at least one clause is redline-eligible.
- `"skip_redline"` — no clause is redline-eligible (all validated findings fall
  below the threshold, or there are zero validated findings, or `ingest_error` is
  set).

### 2.2 RedlineAgent (`redline` node)

**Reads** from `ContractState`:
- `clauses` — for each clause record:
  - `final_status` — the gate; only `VALIDATED` records are candidates.
  - `risk_level` — must satisfy `REDLINE_RISK_THRESHOLD` to be redlined.
  - `text`: `str` — the clause language being rewritten.
  - `risk_rationale`: `Optional[str]` — the Node-5 explanation of *why* the clause
    is risky; fed to the rewrite prompt as the remediation target.
  - `evidence_snippets`: `Optional[List[Dict[str, Any]]]` — merged CRAG evidence
    (may be `[]`/`None`); used as drafting context when present.
  - `clause_type`: `Optional[ClauseType]` — drafting context.
  - `position`, `section_number` — read for logging / ordering only.
- `document_id`: `str` — logging only.
- `ingest_error`: `Optional[Dict[str, str]]` — checked defensively; if set, return
  immediately with no rewrites (same pattern as Nodes 2–5).

**Writes** back into the existing `clauses` dict via the `merge_nested_clause_dicts`
reducer. For **each redlined clause** it adds:

| Field | Type | Description |
|-------|------|-------------|
| `suggested_rewrite` | `Optional[str]` | Safer rewritten clause language for a redline-eligible finding, bounded to `REDLINE_REWRITE_MAX_CHARS`. On an unrecoverable drafting failure it is emitted as an explicit `None` (§7.3 — Redline does NOT fabricate legal text on failure; the finding stays surfaced via `risk_level`). See the three-state definition immediately below. |

**Three-state definition of `suggested_rewrite`** — this field has three distinct
states, disambiguated by reading it **together with `risk_level`**, never in
isolation:

| State | Meaning | How the node produces it |
|-------|---------|--------------------------|
| **key absent** | Clause was **never attempted** — it is not redline-eligible (SkipRedline path, or an ineligible/below-threshold/discarded clause). | Node **omits** the key (partial-update rule). |
| **`None`** | Clause **was** redline-eligible and the node **attempted it but produced no rewrite** — LLM failure, empty/whitespace output, empty clause text, or circuit-open bulk skip (§7.3; Edge Cases 4/5/6/10). | Node **emits** `suggested_rewrite: None` (explicitly, to clear any stale re-run value — §8a R3). |
| **non-empty `str`** | **Successful rewrite**, bounded to `REDLINE_REWRITE_MAX_CHARS`. | Node emits the string. |

**"Clean" is `risk_level is None`, NOT `suggested_rewrite is None`.** A clause is
*clean* precisely when it never validated (`final_status != VALIDATED`, hence no
`risk_level`); a `None` rewrite on a clause that *does* carry a `risk_level` means
"risky, remediation unavailable" — the opposite of clean. This refines the imprecise
inline comment in `001` §3 (`suggested_rewrite: Optional[str]  # ... None if clean`),
which was pre-Node-6 shorthand: cleanliness is recoverable only from the
`(final_status, risk_level, suggested_rewrite)` triple, not from `suggested_rewrite`
alone. This is a **documentation-only** refinement of `001` — the field's type and
reducer are unchanged — flagged here as a light constitution §10 touch (§8a R2).

It does **not** create new clause IDs and does **not** modify `text`, `position`,
`section_number`, `clause_type`, `confidence_score`, `path_taken`,
`evidence_snippets`, any Self-RAG verdict field, or `risk_level` / `risk_rationale`
(all owned by earlier nodes).

**Partial-update rule (constitution §5).** In the normal case RedlineAgent returns
ONLY `clauses` (per-clause `suggested_rewrite` for redlined findings),
`current_node`, and `node_timings`. The **sole** exception is the circuit-breaker
health signal (§7.6): when the LLM backend is declared down for the run it
additionally returns `error_count: 1` (exactly once, via the `operator.add`
reducer). It does NOT return or modify any key owned by Nodes 1–5, the top-level
`evidence_trail` / `report_path` (ReportAgent, Node 7), or `mcp_delivery_status`.

**Pinned state-key value.** `current_node` is set to the string `"redline"`, and
that same string is the key used in the `node_timings` update — matching the graph
node name registered in `builder.py` (constitution §8; mirrors how Nodes 2–5 pin
`"clause_splitter"` / `"crag_retrieval"` / `"self_rag_validation"` / `"risk_score"`).

**Error accounting.** A **single-clause** rewrite failure does NOT increment
`error_count` — it is graceful degradation with a defined outcome (§7.3), matching
Nodes 2–5. The **one** case that increments is the **circuit breaker opening**
(§7.6): a wholesale backend outage is a genuine pipeline-health event and must be
distinguishable from a clean run, so the node returns `error_count: 1` **once**
when the circuit opens. This is a health signal, not a hard abort. Directly mirrors
RiskScore §2 / Self-RAG §8a R5.

### 2.3 SkipRedline (`skip_redline` node)

**Reads**: nothing beyond what it needs for metadata (`document_id` for logging).

**Writes**: ONLY `current_node` (pinned string `"skip_redline"`) and `node_timings`
(`{"skip_redline": elapsed}`). It writes **no** clause fields — "clause marked
clean" is emergent from `suggested_rewrite` being absent (§7.4); `001` reserves no
"clean"/"reviewed" flag and adding one would be a constitution §10 schema change
(out of scope — §5.5). Makes **no** LLM calls.

### 2.4 Enums used (already defined in `001`; no new members)

```python
class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class ValidationStatus(str, Enum):
    DISCARDED = "discarded"
    VALIDATED = "validated"
```

## 3. Acceptance Criteria

Each criterion is written to become a test case directly. The rewrite generation is
mocked at the LLM boundary (no live Ollama) so outputs are deterministic fixtures.
Throughout, "redline-eligible" means `final_status == VALIDATED` **and**
`risk_level ∈ REDLINE_RISK_THRESHOLD`.

### route_on_risk (routing function)

1. **Routes to `redline` when a redline-eligible clause exists**: Given a `clauses`
   dict with at least one `VALIDATED` clause whose `risk_level` satisfies
   `REDLINE_RISK_THRESHOLD`, `route_on_risk(state)` returns the string `"redline"`.

2. **Routes to `skip_redline` when none exists**: Given a `clauses` dict with zero
   redline-eligible clauses (all `DISCARDED`/`None`, or all validated findings below
   the threshold), `route_on_risk(state)` returns `"skip_redline"`.

3. **Empty clauses → `skip_redline`**: For `clauses == {}`, `route_on_risk` returns
   `"skip_redline"`.

4. **`ingest_error` set → `skip_redline`**: If `ingest_error` is non-`None`,
   `route_on_risk` returns `"skip_redline"` regardless of `clauses` contents.

5. **Ignores discarded clauses**: A `DISCARDED` clause is never counted as
   redline-eligible even if (defensively) it carries a `risk_level`; only
   `VALIDATED` findings can route to `redline`.

6. **Threshold is read from config**: The set of levels that count as
   redline-eligible is read from `REDLINE_RISK_THRESHOLD` (`app.config`), never
   hardcoded inline (constitution §3). A test that monkeypatches the threshold to
   exclude `LOW` makes an all-`LOW` document route to `skip_redline`.

7. **Pure function, no mutation**: `route_on_risk` returns only a routing string and
   does not add, remove, or mutate any key in the state it is passed (assert the
   state dict is unchanged after the call).

### RedlineAgent (`redline` node)

8. **Redline-eligible clauses get a rewrite**: Given N redline-eligible clauses,
   after the node runs every one of them has a non-`None`, non-empty
   `suggested_rewrite`.

9. **Non-eligible validated clauses are untouched**: A `VALIDATED` clause whose
   `risk_level` is **below** `REDLINE_RISK_THRESHOLD` receives no
   `suggested_rewrite` (the node omits the key entirely — it stays **absent**, the
   "never attempted" state of §2.2) and incurs **no** LLM call.

10. **Discarded / `None` clauses are untouched**: A `DISCARDED` or `final_status
    is None` clause receives no `suggested_rewrite` and incurs no LLM call.

11. **Exactly one LLM call per redlined clause**: The number of drafting LLM calls
    equals the number of redline-eligible clauses (assert by counting calls). No
    calls for skipped clauses.

12. **Uses the generative model, not the embedding model**: Every LLM call uses
    `OLLAMA_MODEL_NAME`; the node never references `OLLAMA_EMBED_MODEL_NAME`. A test
    asserts the two constants are distinct and the embedding model name is never
    passed to the node's LLM call.

13. **Uses configured constants**: The per-call timeout, circuit-breaker threshold,
    prompt-truncation limit, rewrite-truncation limit, and redline threshold set are
    all read from `app.config` (constitution §3), never hardcoded inline.

14. **Defensive `ingest_error` check**: If `ingest_error` is set, the node returns
    immediately with an empty `clauses` update and makes no LLM calls.

15. **Empty clauses input**: For `clauses == {}`, the node returns an empty `clauses`
    update, makes no LLM calls, and logs a warning.

16. **No redline-eligible findings**: If `clauses` is non-empty but contains zero
    redline-eligible clauses (should not normally reach `redline` given
    `route_on_risk`, but defensively), the node returns an empty `clauses` update,
    makes zero LLM calls, and logs an info line. This is a valid outcome, not an
    error.

17. **Partial update only**: In the normal (no-outage) case the returned dict
    contains ONLY the keys `clauses`, `current_node`, and `node_timings`, with NO
    `error_count` and no keys owned by other nodes. The single permitted addition is
    `error_count: 1` when — and only when — the circuit breaker opened (AC-23).

18. **Graceful drafting failure (fail-safe)**: If an LLM call raises or times out
    for a redlined clause, the node emits that clause's `suggested_rewrite` as an
    explicit `None` (Redline does not fabricate legal text — §7.3; emitting `None`
    rather than omitting the key clears any stale re-run value — §2.2), a warning is
    logged, the pipeline does NOT crash, and other clauses still process. A
    single-clause failure alone does NOT increment `error_count`. The finding
    remains surfaced downstream via its unchanged `risk_level`.

19. **Malformed / empty LLM output**: If the LLM returns empty/whitespace-only text
    (no usable rewrite), the node treats it as a drafting failure (AC-18 path): emits
    `suggested_rewrite: None`, warning logged, no crash. This counts toward the
    consecutive-failure counter (AC-20).

20. **LLM circuit breaker**: When LLM calls fail for
    `REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD` clauses **consecutively**, the node marks
    the backend down for the rest of the run and emits `suggested_rewrite: None`
    for all **remaining** redline-eligible clauses without issuing further LLM calls
    (no per-clause timeout wait). A single "circuit opened" warning is logged; the
    consecutive-failure counter resets on any successful call. (Ineligible/skipped
    clauses remain omitted regardless — they never depended on the LLM.)

20a. **Only LLM-issuing failures move the consecutive-failure counter**: Exactly the
    paths that issued an LLM call and got an unrecoverable result (raise, timeout, or
    empty output — AC-18/19) increment the consecutive-failure counter, and any
    successful call resets it. The post-circuit-open bulk skip issues no LLM call and
    is **circuit-neutral** (neither increments nor resets). Mirrors RiskScore AC-14a.

21. **Rewrite truncation**: A generated `suggested_rewrite` longer than
    `REDLINE_REWRITE_MAX_CHARS` is truncated to that limit before being written to
    state; truncation is logged at debug level.

22. **Prompt truncation**: The clause text, `risk_rationale`, and concatenated
    evidence snippets fed into the drafting prompt are truncated to
    `REDLINE_PROMPT_MAX_CHARS` before the LLM call; truncation logged at debug level.

23. **Circuit-open health signal**: On a run where the breaker opens, the returned
    partial dict includes `error_count: 1` (exactly one, regardless of how many
    clauses were skipped afterward). On a run where the breaker never opens, the
    returned dict includes no `error_count` key. (Assert both directions.)

24. **`current_node` pinned**: After the node runs, `current_node == "redline"` and
    the same string is the key in the returned `node_timings` dict.

25. **Re-run overwrite (defensive)**: If a redlined clause already carries a
    `suggested_rewrite` (e.g. a re-run), a successful drafting call overwrites it;
    the `merge_nested_clause_dicts` reducer preserves all non-rewrite fields
    (`text`, `risk_level`, `evidence_snippets`, Self-RAG verdicts, etc.).

26. **Redlined finding with empty evidence still drafts**: For a redline-eligible
    clause whose `evidence_snippets` is `[]`/`None`, the node still drafts a rewrite
    from clause text + `risk_rationale` + `clause_type` alone, without crashing.

27. **Does not modify upstream fields**: The node never sets or modifies
    `risk_level`, `risk_rationale`, or any Self-RAG / CRAG / Ingest field on any
    clause (assert those fields are byte-for-byte unchanged after the run).

### SkipRedline (`skip_redline` node)

28. **Passthrough update only**: `skip_redline` returns ONLY `current_node ==
    "skip_redline"` and `node_timings == {"skip_redline": <float>}`; it makes no LLM
    calls and writes no `clauses`, `suggested_rewrite`, `error_count`, or any other
    key.

29. **No clause mutation**: After `skip_redline` runs, the `clauses` dict is
    unchanged (no `suggested_rewrite` added to any clause).

### Graph wiring

30. **`route_on_risk` is a genuine graph-level conditional edge**: `builder.py`
    registers `route_on_risk` via `add_conditional_edges` on the `risk_score` node
    with a path map `{"redline": "redline", "skip_redline": "skip_redline"}`. This
    replaces the temporary `risk_score → END` edge (feature-007 placeholder).

31. **Both branches converge downstream**: Both `redline` and `skip_redline` have an
    outgoing edge to the same successor (ReportAgent when feature-009 exists; `END`
    until then — §7.5).

32. **Only two domain conditional edges exist**: A test/inspection asserts the graph
    contains exactly the two permitted domain conditional edges — CRAG's confidence
    routing (internal, Node 3) and `route_on_risk` (graph-level, Node 6) — plus the
    non-domain ingest error-guard edge. No other `add_conditional_edges` is
    introduced by this feature.

## 4. Edge Cases

1. **`ingest_error` set**: `route_on_risk` returns `"skip_redline"`; if `redline`
   is nonetheless reached it returns immediately with no rewrites (AC-14). Same
   defensive pattern as Nodes 2–5.

2. **Empty `clauses` dict**: `route_on_risk` → `"skip_redline"` (AC-3); `redline`,
   if reached, returns an empty update and logs a warning (AC-15).

3. **No redline-eligible findings** (`clauses` non-empty, all below threshold or all
   discarded): `route_on_risk` → `"skip_redline"` (AC-2). This is the normal "no
   risk → SkipRedline (clause marked clean)" path of constitution §2. With the
   resolved threshold `{LOW, MEDIUM, HIGH}` (§8a R1) this branch fires **only** for
   documents with zero `VALIDATED` findings — a conscious, accepted consequence
   (RiskScore §8b): the "no risk" branch is driven by Self-RAG discards, not by risk
   level. (Were the threshold later tightened to exclude `LOW`, this branch would
   also fire for documents whose only findings are `LOW`.)

4. **LLM call fails / times out / returns empty output for a clause**: On any
   unrecoverable failure (Ollama unreachable, timeout > `REDLINE_TIMEOUT_SECONDS`,
   empty/whitespace response) emit `suggested_rewrite: None` (explicit, per §2.2), log
   a rate-limited warning, and continue with the next clause. Never crash. Unlike
   RiskScore's fail-safe (which defaults to `HIGH`), Redline's fail-safe is **no
   rewrite**, not a fabricated one — see §7.3 for why a risk tool must not invent legal
   text on failure. The finding is still surfaced via its `risk_level`.

5. **LLM backend down mid-run (circuit breaker)**: After
   `REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD` **consecutive** LLM failures, the node
   stops attempting calls for the rest of the run and emits `suggested_rewrite: None`
   for every remaining redline-eligible clause, without paying the per-clause
   timeout. A single "circuit opened" warning is logged **and** the node emits
   `error_count: 1` once (§2.2 / AC-23). The counter resets on any success; the
   post-open bulk skip is circuit-neutral (AC-20a). Per-run only; not persisted
   across pipeline invocations. Mirrors RiskScore Edge Case 5.

6. **Empty / whitespace-only clause text on a redline-eligible finding** (defensive —
   Self-RAG/RiskScore would normally not have produced one): skip the LLM call, emit
   `suggested_rewrite: None` (explicit, per §2.2), log a warning. Circuit-neutral (no
   LLM call issued). Other clauses still process.

7. **Redline-eligible finding with empty / absent evidence** (`evidence_snippets`
   `[]`/`None`): draft on clause text + `risk_rationale` + `clause_type` alone. Never
   crash (AC-26).

8. **Very long clause text / rationale / evidence**: The concatenated prompt inputs
   are truncated to `REDLINE_PROMPT_MAX_CHARS` before the LLM call (AC-22). Logged at
   debug level.

9. **Very long generated rewrite**: `suggested_rewrite` is truncated to
   `REDLINE_REWRITE_MAX_CHARS` before being written to state (AC-21). Logged at debug
   level.

10. **Clause already carries `suggested_rewrite` (re-run)**: A successful call
    overwrites it; the reducer preserves all non-rewrite fields (AC-25). On a *failed*
    re-run call the node emits `suggested_rewrite: None`, explicitly clearing any stale
    rewrite so a now-failing clause never keeps a previous run's stale text (§2.2 / §8a
    R3). Because the node attempted the clause, emitting the key is correct under the
    partial-update rule (constitution §5) — the field genuinely changed to a definitive
    `None` outcome.

11. **Large redline-eligible count**: The node processes eligible clauses strictly
    sequentially (mirrors CRAG §7.6 / Self-RAG / RiskScore Edge Case 11). Per-clause
    runtime is bounded by `REDLINE_TIMEOUT_SECONDS`; the aggregate worst case (backend
    down → every clause pays the timeout) is bounded by the circuit breaker (Edge
    Case 5).

12. **`route_on_risk` disagreement with RedlineAgent** (defensive consistency): both
    the edge and the node compute "redline-eligible" from the **same**
    `REDLINE_RISK_THRESHOLD` constant and the same `final_status == VALIDATED` gate,
    so they cannot disagree. A test asserts a document routed to `skip_redline` would
    also have produced zero rewrites had `redline` been run on it (single source of
    truth for the eligibility predicate — see §7.2).

## 5. Out of Scope

Node 6 does NOT handle:

1. **Assigning severity** — that is **RiskScore (Node 5)**, `specs/007-risk-score`.
   Node 6 consumes `risk_level` as a gate and never re-derives or overrides it.

2. **Deciding validated vs discarded** — that is **Self-RAG (Node 4)**,
   `specs/006-self-rag-validation`. Node 6 reads `final_status` as a gate only.

3. **Gathering or scoring retrieval evidence** — **CRAG (Node 3)**,
   `specs/005-crag-retrieval`. Redline consumes `evidence_snippets` as given drafting
   context and performs no retrieval, embedding, or web search.

4. **Compiling the final report and the top-level `evidence_trail`** — **ReportAgent
   (Node 7)**, future `specs/009-*`. Redline writes only per-clause
   `suggested_rewrite`; it does not assemble `report_path` or `evidence_trail`.

5. **Any document-level "clean" / "reviewed" flag or roll-up remediation status** —
   `001` reserves no such field. "Clause marked clean" is emergent from a clause never
   validating (`risk_level is None`), not from `suggested_rewrite` (§2.2 / §7.4);
   introducing an explicit marker field would be a constitution §10 schema change and
   is out of scope here (§8a R4).

6. **Human-in-the-loop acceptance / editing of a suggested rewrite** — no review or
   accept/reject UI (consistent with the PERMANENTLY CUT "no audit log UI / dashboard"
   items). Redline produces the suggestion; downstream presentation and any user
   action on it are not this node's concern.

7. **Legal correctness / enforceability guarantees of the rewrite** — the rewrite is
   an LLM-generated *suggestion* surfaced for human review, not vetted legal advice.
   This spec makes no claim that a `suggested_rewrite` is legally sound; it only
   guarantees the mechanics of generating, bounding, and persisting it.

8. **Bounded-parallelism over clauses** — sequential for Phase 1, matching CRAG §7.6,
   Self-RAG §5.8, and RiskScore §5.8. A concurrency knob is deferred.

9. **Delivering the report via MCP (Drive/Gmail)** — that is a later step writing
   `mcp_delivery_status`, not Node 6.

## 6. Configurable Constants

Per constitution §3, all thresholds live in `backend/app/config.py`. This spec adds
a new `# ── Redline thresholds` section; no Redline constant exists there yet. The
node reuses the existing shared `OLLAMA_MODEL_NAME` for its generative calls and
introduces no new model constant.

```python
# ── Redline thresholds ─────────────────────────────────────────────────────────
# Source: specs/008-route-on-risk-redline/spec.md §6

REDLINE_RISK_THRESHOLD: frozenset[RiskLevel] = frozenset(
    {RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH}
)
# The set of risk levels that route a VALIDATED finding to RedlineAgent (vs
# SkipRedline). Read by BOTH route_on_risk (the edge) and RedlineAgent (the node)
# so the eligibility predicate has a single source of truth (spec §7.2). RESOLVED to
# Option A — all three levels (§8a R1): every validated finding is redlined, and the
# accepted consequence is that SkipRedline fires only for documents with zero
# validated findings. Kept permissive on purpose so the spec §9 / RiskScore §9.6
# redline-routing metrics can inform a later tightening to {MEDIUM, HIGH} if LOW
# rewrites prove noisy — a one-line change plus an eval monkeypatch. Tune against real
# sample contracts.

REDLINE_TIMEOUT_SECONDS: int = 120
# Wall-clock timeout for a single Redline LLM call (one clause rewrite) via Ollama.
# Mirrors RISK_SCORE_TIMEOUT_SECONDS / SELF_RAG_TIMEOUT_SECONDS; headroom for local
# Qwen3 per constitution §9. On timeout the clause takes the fail-safe (spec §4.4):
# the node emits suggested_rewrite: None.

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

(All defaults are starting points to be tuned against real sample contracts after
implementation. Note there is intentionally **no** `REDLINE_MAX_ATTEMPTS` retry
constant — constitution §2 scopes retries to Self-RAG's ISSUP check only; a failed
rewrite takes the fail-safe (no rewrite) rather than re-sampling, mirroring RiskScore
§6.)

## 7. Pinned Design

The pins below are safe to plan and implement against. All design decisions they touch
are resolved (§8a); this spec has no remaining open questions.

### 7.1 `route_on_risk` is a genuine graph-level conditional edge
Unlike CRAG's confidence routing — which the constitution counts as a conditional
edge but which is realized as **internal per-clause branching** because it routes
*each clause* down a different retrieval path while all clauses share one state object
(`builder.py:69-80`) — `route_on_risk` is a **document-level** decision: "does this
document contain anything worth redlining?" That routes the **whole** `ContractState`
to exactly one successor node, which is precisely what LangGraph's
`add_conditional_edges` expresses. So this feature registers `route_on_risk` as a
real graph-level conditional edge on the `risk_score` node, with path map
`{"redline": "redline", "skip_redline": "skip_redline"}`. RedlineAgent then does the
**per-clause** filtering internally (loop over eligible clauses), exactly as RiskScore
loops over validated findings. This makes `route_on_risk` the pipeline's first and
only domain conditional edge realized at the graph level; CRAG's stays internal. Both
are legitimate under constitution §2's "exactly 2 conditional edges" (§2 constrains
the *count and semantics*, not the realization mechanism — the same reading already
applied to CRAG in `005` §7.2).

### 7.2 Single source of truth for "redline-eligible"
Both `route_on_risk` (the edge) and RedlineAgent (the node) decide eligibility from
the **same** predicate: `final_status == VALIDATED and risk_level in
REDLINE_RISK_THRESHOLD`. This predicate is defined once (a shared helper) and read
from the one config constant, so the edge and the node can never disagree about which
clauses are eligible (AC-32, Edge Case 12). The node's internal filter is defensive
belt-and-suspenders: even though `route_on_risk` only sends the state to `redline`
when ≥1 eligible clause exists, `redline` still re-checks per clause so it never
rewrites an ineligible one.

### 7.3 Redline fail-safe = NO rewrite (not a fabricated one)
This is the deliberate **inverse** of RiskScore's fail-safe. RiskScore fails *safe*
toward `HIGH` because an unscored-but-validated finding should surface at maximum
severity — failing toward *more* visibility is the risk-appropriate bias. Redline is
different: the artifact it produces is **substantive legal text**. Fabricating or
guessing clause language on an LLM failure would be actively harmful (a plausible-
looking but unfounded rewrite is worse than none). So on any unrecoverable drafting
failure the fail-safe is to leave `suggested_rewrite == None` and log the reason. The
finding is **not** lost — it remains fully surfaced downstream by its unchanged
`risk_level` / `risk_rationale`; only the *optional* remediation text is absent.
Resolved (§8a R2/R3): on failure the node emits an explicit `suggested_rewrite: None`
(never omits the key) so a stale re-run value is cleared and "attempted but failed" is
uniform — see the three-state definition in §2.2.

### 7.4 "Clause marked clean" is emergent, not a new field
Constitution §2's "no risk -> SkipRedline (clause marked clean)" is satisfied by a
clause **never having validated** (`risk_level is None`): a clause with a `risk_level`
but no rewrite is a flagged-but-not-redlined finding (risky, remediation absent — not
clean), whereas a clause that was never validated is clean by virtue of never having a
`risk_level`. `001` reserves no boolean "clean"
flag, and SkipRedline therefore writes no clause fields (§2.3). Introducing an explicit
marker would be a constitution §10 schema change — resolved to keep it emergent (§8a R4).

### 7.5 Wiring supersedes the feature-007 placeholder
`builder.py` currently ends the pipeline at `risk_score → END` (feature-007 placeholder,
`builder.py:103`). This feature **replaces** that single edge with:
`risk_score → route_on_risk (conditional) → {redline, skip_redline}`, and both `redline`
and `skip_redline` → `END` **until** feature-009 (ReportAgent, Node 7) exists, at which
point both branches will instead point to `report`. This mirrors how every prior node's
`→ END` placeholder was rewired when its successor arrived. (Note: RiskScore spec §2's
prose describing "`builder.py` wires `risk_score → redline` as a plain linear add_edge"
was an imprecise forward-reference written before this spec; the actual Node-6 wiring is
the conditional edge described here, which is fully consistent with constitution §2.)

### 7.6 Circuit-open health signal
As with RiskScore §7.4 and Self-RAG §7.6: a per-clause fail-safe (§7.3) is silent by
design — one flaky call must not raise a pipeline error — but a **circuit-breaker open**
means the backend is down and the rest of the run is being skipped wholesale, which must
not look identical to a clean run. So when (and only when) the breaker opens, RedlineAgent
returns `error_count: 1` **once** (the `operator.add` reducer accumulates it). Exactly one
increment per run; the breaker opens at most once. A health signal for observability, not
a hard abort.

## 8. Design Decisions and Open Questions

### 8a. Resolved / pinned (safe for plan.md)

Structural invariants (follow directly from the constitution / shared conventions):

- **Eligibility gate** — a clause is redlined iff `final_status == VALIDATED and
  risk_level in REDLINE_RISK_THRESHOLD`; discarded/`None`/below-threshold clauses are
  skipped with no LLM call (§7.2, AC-9/10). Single source of truth shared by edge and
  node.
- **Model** — generative `OLLAMA_MODEL_NAME` only; never the embedding model (§1, AC-12).
  Constitution §8.
- **Partial update + error accounting** — RedlineAgent returns only
  `clauses`/`current_node`/`node_timings` normally, `+ error_count:1` iff the circuit
  opened (§2.2, AC-17/23). SkipRedline returns only `current_node`/`node_timings` (§2.3,
  AC-28). Mirrors RiskScore.
- **Circuit breaker** — mirror RiskScore/Self-RAG/CRAG: consecutive-failure threshold,
  bulk fail-safe, single health signal, per-run reset; only LLM-issuing failures move the
  counter (§4.5, AC-20/20a/23).
- **Constants in config** — all thresholds in `app.config` (§6); no inline literals
  (constitution §3, AC-6/13).
- **`route_on_risk` realized as graph-level `add_conditional_edges`** — §7.1. Follows from
  its document-level routing semantics.
- **State-key names `"redline"` / `"skip_redline"`** — snake-case, no `_agent` suffix,
  matching `crag_retrieval` / `self_rag_validation` / `risk_score` (§2.2/§2.3).

Design decisions resolved with the reviewer on 2026-07-05 (were open in a prior draft;
now pinned):

- **R1 — `REDLINE_RISK_THRESHOLD` = `{LOW, MEDIUM, HIGH}` (Option A)** (was Q1). Every
  validated finding is redlined. "Clean" is already Self-RAG `DISCARDED`, so a `LOW`
  finding is a genuine minor finding worth a suggested improvement, not a clean clause
  — this keeps one mental model: *validated finding ⟺ rewrite attempted; clean ⟺
  discarded*. **Accepted consequence:** SkipRedline fires only for documents with zero
  validated findings, so `route_on_risk`'s "no risk" branch is driven by Self-RAG
  discards rather than by risk level (the tension RiskScore §8b flagged, adopted
  consciously). Chosen over `{MEDIUM, HIGH}` — the one defensible fallback — because the
  permissive default loses no information and the spec §9 / RiskScore §9.6
  redline-routing metrics make a later tightening a one-line config change; starting
  strict and loosening would be the harder direction. Confirms §6 / Edge Case 3.

- **R2 — `suggested_rewrite` is three-state, disambiguated by `risk_level`** (was the
  `None`-collision in Q2). key **absent** = never attempted (ineligible / SkipRedline);
  **`None`** = attempted, no rewrite produced; **non-empty str** = successful rewrite.
  "Clean" is `risk_level is None`, never `suggested_rewrite is None`. This refines
  `001` §3's imprecise inline comment "`None if clean`" — a documentation-only
  refinement (field type and reducer unchanged; a light constitution §10 touch,
  flagged). Confirms §2.2.

- **R3 — On failure/circuit-open the node emits an explicit `suggested_rewrite: None`;
  it omits the key only for clauses it never attempted** (was Q3). Emitting `None`
  clears a stale re-run value and makes "attempted but failed" uniform; this is correct
  under the partial-update rule (constitution §5) because the field genuinely changed to
  a definitive `None` outcome. Confirms §7.3 and unifies all fail-safe language in §3 /
  §4 (AC-18/19/20, Edge Cases 4/5/6/10).

- **R4 — "Clause marked clean" stays emergent; no new state field** (was Q2). A
  `reviewed_clean` / `redline_status` field would be a `001` schema change for zero
  Phase-1 benefit — cleanliness is fully recoverable from the `(final_status,
  risk_level, suggested_rewrite)` triple. Confirms §7.4 / §5.5.

- **R5 — Phase 1 always attempts a rewrite for an eligible clause; no distinct "no
  change needed" outcome** (was Q4). Modeling deliberate-`None` vs failure-`None` would
  need a new field for a case not yet observed; `None` means exactly "no rewrite
  available." **Eval-watch caveat:** a model told to improve an already-fine clause may
  echo the input verbatim — a non-empty "success" that is actually a no-op the
  empty-output fail-safe won't catch. Logged as a §9 eval-watch metric (optionally treat
  `rewrite.strip() == text.strip()` → `None` in a later iteration); NOT a required
  Phase-1 mechanic. Confirms §7.1's "attempt every eligible clause".

### 8b. Open questions

No remaining open questions. This spec is considered final and ready for plan.md
(constitution §1 / §8).

## 9. Evaluation

Node 6 generates a remediation artifact per redlined finding and makes a routing
decision, so the following metrics MUST be logged per run for later tuning (per
`specs/002-tech-stack.md` §3i eval tooling), following the `logger.info(...,
extra={...})` structured-log pattern established in `crag_retrieval_agent.py`,
`self_rag_validation_agent.py`, and `risk_score_agent.py`. These live in **log
records, NOT in `ContractState`**, which carries only aggregate
`node_timings["redline"]` / `node_timings["skip_redline"]`. Metric 4 is the direct
counterpart RiskScore §9.6 ("redline-routing preview") promised to cross-reference
once `008` exists.

1. **Route decision** — for each run, whether `route_on_risk` returned `redline` or
   `skip_redline`, plus the count of redline-eligible clauses. The headline signal of
   how often any redlining happens at all.

2. **Redline rate** — of redline-eligible clauses, the fraction that received a
   non-empty `suggested_rewrite` vs. an emitted `None` (failure/skip). In a healthy
   deployment this should be ~1.0; a low rate points at LLM instability, not at product
   behavior.

3. **Rewrite-failure & circuit-breaker events** — fraction of eligible clauses that
   took the fail-safe `None` (LLM failure / timeout / empty output / empty text), and
   count of runs where the circuit opened (each emits `error_count: 1`, §7.6). Should be
   ~0 in a healthy deployment; a spike means findings are being surfaced without
   remediation text.

4. **Level → route breakdown** — of scored findings, the `LOW`/`MEDIUM`/`HIGH` split
   among those redlined vs. skipped. The direct input for tuning `REDLINE_RISK_THRESHOLD`
   (§8a R1) and the counterpart to RiskScore §9.6. Under the resolved all-levels
   threshold every validated finding is in the "redlined" column, so a later tightening
   to `{MEDIUM, HIGH}` would be justified from this metric (e.g. if `LOW` rewrites prove
   low-value against the no-op rate in metric 6).

5. **Rewrite length & truncation rate** — distribution of `suggested_rewrite` length and
   how often it hit `REDLINE_REWRITE_MAX_CHARS`, to calibrate that cap; plus the
   prompt-truncation rate against `REDLINE_PROMPT_MAX_CHARS`.

6. **No-op / echo rate (eval-watch, §8a R5)** — fraction of "successful" (non-empty)
   rewrites where `suggested_rewrite.strip() == text.strip()` (the model echoed the
   clause unchanged). Not acted on in Phase 1, but logged so we can decide whether to
   treat echoes as `None` in a later iteration.

7. **Latency** — per-clause drafting-call latency and total node wall-clock time (the
   value that also feeds `node_timings`). Supports constitution §9 tuning; expected the
   lightest generative load of any node since only redline-eligible findings are drafted.

8. **Rewrite quality (requires ground truth)** — when labeled sample contracts are
   available, compare `suggested_rewrite` against human-authored redlines to estimate
   usefulness. Cannot be computed from logs alone; the per-clause rewrite + `risk_level`
   / `risk_rationale` logs above are the raw material for that offline analysis.

These metrics directly support tuning `REDLINE_RISK_THRESHOLD`, the drafting prompt, and
`REDLINE_REWRITE_MAX_CHARS` against real sample contracts once implementation is complete.
