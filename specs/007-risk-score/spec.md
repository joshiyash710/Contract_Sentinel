# RiskScore Specification

## 1. Problem Statement

The RiskScore node is **Node 5** of the fixed 7-node pipeline defined in `specs/000-constitution.md`. Its responsibility is to assign a **risk level — Low, Medium, or High — to each validated finding** produced by Self-RAG validation (Node 4), together with a short **rationale** explaining the assignment.

Per constitution §2, the node sits between Self-RAG validation (Node 4) and the `route_on_risk` conditional edge (Node 6):

> 5. RiskScoreAgent — assigns Low/Medium/High risk to each validated finding
> 6. Conditional edge route_on_risk:
>    - risk found -> RedlineAgent (drafts safer clause language)
>    - no risk -> SkipRedline (clause marked clean)

**Why this node exists where it does:** Self-RAG (Node 4) decides *whether* a clause is a finding worth surfacing (`VALIDATED` vs `DISCARDED`); it deliberately does **not** decide *how risky* the finding is (that is explicitly Node 5's job, per Self-RAG spec §5.1). RiskScore turns the flat set of validated findings into a **severity-ranked** set, which is exactly the input the downstream `route_on_risk` edge (Node 6) needs to decide whether a clause is worth drafting a safer rewrite for, and which the final report (Node 7) needs to present findings by severity. RiskScore is the **severity-assignment stage** between "these clauses are worth flagging" (Node 4) and "draft a safer version of the risky ones" (Node 6).

**Scope of what it scores:** RiskScore processes **only** clauses whose Self-RAG outcome is `final_status == ValidationStatus.VALIDATED`. `DISCARDED` clauses (Self-RAG suppressed them as noise, "never shown to the user" per constitution §2) are **skipped**: no LLM call, no `risk_level` assigned — they remain inert in state exactly as Self-RAG left them. This mirrors how Self-RAG itself does not remove discarded clauses from state but marks them and lets downstream nodes filter on `final_status`.

**Model note (constitution §8):** This node uses the **generative** model (`OLLAMA_MODEL_NAME`, Qwen3 via Ollama) — the same generative model ClauseSplitter and Self-RAG use — for its severity judgment. It MUST NOT use the embedding model (`OLLAMA_EMBED_MODEL_NAME`); RiskScore makes no vector calls (CRAG already produced the evidence, Self-RAG already validated). Per constitution §9, this node makes one generative call per **validated** finding, so timeouts, per-call abort, and a circuit breaker to bound aggregate runtime when Ollama is unreachable are load-bearing, not optional (mirrors CRAG Edge Case 13 and Self-RAG Edge Case 8). Because only validated findings are scored — typically a small fraction of all clauses — RiskScore's LLM load is materially lighter than Self-RAG's.

**Not a conditional edge:** The two conditional edges the constitution permits are CRAG's confidence routing (Node 3) and `route_on_risk` (Node 6). RiskScore is **not** one of them. `builder.py` wires `risk_score → redline` (future Node 6) as a plain linear `add_edge`; the risk-based branching is `route_on_risk`, which is **Node 6's** edge and reads the `risk_level` this node writes. RiskScore assigns severity; it does not route.

## 2. Inputs and Outputs

### Inputs

RiskScore reads the following from `ContractState` (as defined in `specs/001-contract-state-schema.md`):

- `clauses`: `Dict[str, Dict[str, Any]]` — the per-clause dict carrying Node 1–4 output. For each clause record this node reads:
  - `final_status`: `Optional[ValidationStatus]` — **the gate.** Only records with `final_status == ValidationStatus.VALIDATED` are scored; everything else is skipped.
  - `text`: `str` — the clause text being scored
  - `evidence_snippets`: `Optional[List[Dict[str, Any]]]` — the merged CRAG evidence (Node 3); each entry is `{snippet_text: str, source_reference: str}`. May be `[]`/`None` for a validated finding that Self-RAG rescued on clause text alone (its high-risk empty-evidence path). Used as scoring context when present.
  - `clause_type`: `Optional[ClauseType]` — read as a severity prior / scoring context (e.g. a liability clause skews the model toward higher severity)
  - `relevance_verdict`, `isrel_verdict`, `issup_verdict`, `retry_count` — read for logging/context only; RiskScore does not re-derive them
  - `position`, `section_number` — read for logging/ordering only
- `document_id`: `str` — for logging only
- `ingest_error`: `Optional[Dict[str, str]]` — checked defensively; if set, the node returns without processing (same defensive pattern as Nodes 2, 3, and 4)

### Outputs

RiskScore writes back into the **existing `clauses` dict** using the `merge_nested_clause_dicts` reducer defined in `specs/001-contract-state-schema.md`. For **each validated finding** it adds the following fields to that clause record (it does NOT create new clause IDs and does NOT modify `text`, `position`, `section_number`, `clause_type`, `confidence_score`, `path_taken`, `evidence_snippets`, or any Self-RAG verdict field):

| Field | Type | Description |
|-------|------|-------------|
| `risk_level` | `RiskLevel` | `RiskLevel.LOW` / `MEDIUM` / `HIGH` — the severity assigned to this validated finding. Always one of the three values for a scored clause (there is no "none"; a validated finding is by definition worth flagging — see §8a R2). |
| `risk_rationale` | `Optional[str]` | A short generated explanation for the assigned level, bounded to `RISK_RATIONALE_MAX_CHARS`. Set on a scored clause. Records automatic assignment when the level came from the fail-safe default (§4.4). |

These field names are already reserved for exactly this purpose in `specs/001-contract-state-schema.md` §3 (the clause-record comment block: `risk_level: Optional[RiskLevel]`, `risk_rationale: Optional[str]`). This spec introduces no new clause-record field names. `suggested_rewrite` is **owned by Node 6** and is never set here.

**Clauses NOT scored** (`DISCARDED`, or defensively `final_status is None`): the node does **not** include them in its return, so the reducer leaves them untouched — their `risk_level` / `risk_rationale` stay absent/`None`. Per the partial-update rule (constitution §5), a node returns only the keys it actually modifies.

**Partial-update rule (constitution §5):** In the normal case the node returns ONLY `clauses` (carrying the per-clause risk updates for validated findings), plus `current_node` and `node_timings` for pipeline metadata. The **sole** exception is the circuit-breaker health signal (§4.5): when the LLM backend is declared down for the run, the node additionally returns `error_count: 1` (exactly once). It does NOT return or modify any IngestAgent-, ClauseSplitter-, CRAG-, or Self-RAG-owned keys, any Redline/Report keys, or the top-level `evidence_trail` (compiled later by ReportAgent, Node 7).

**Pinned state-key value:** `current_node` is set to the string `"risk_score"`, and that same string is the key used in the `node_timings` update. This is the node's *state-key identity*, fixed here so it does not drift from the graph node name registered in `builder.py` (constitution §8; `builder.py` already refers to "feature-007 (RiskScore)"). Mirrors how Nodes 2–4 pin `"clause_splitter"` / `"crag_retrieval"` / `"self_rag_validation"`. (Resolved — §8a.)

**Error accounting:** A **single-finding** LLM failure does NOT increment `error_count` — it is a graceful degradation with a defined fail-safe outcome (§4.4), matching Nodes 2–4. The **one** case that increments is the **circuit breaker opening** (§4.5): a wholesale backend outage that fail-safes the rest of the run is a genuine pipeline-health event and must be distinguishable from a clean run, so the node returns `error_count: 1` **once** when the circuit opens (via the `operator.add` reducer), capped at one increment per run. This is a health signal, not a hard abort. Directly mirrors Self-RAG §8a R5.

### `RiskLevel` enum

Already defined in `specs/001-contract-state-schema.md`; this spec introduces no new enum values:

```python
class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
```

## 3. Acceptance Criteria

Each criterion is written to become a test case directly. Throughout, the severity judgment is mocked at the LLM boundary (no live Ollama) so verdicts are deterministic fixtures.

1. **Validated findings are scored**: Given a state whose `clauses` dict contains M clauses with `final_status == VALIDATED`, after the node runs, every one of those M records has a non-`None` `risk_level ∈ {LOW, MEDIUM, HIGH}` and a non-empty `risk_rationale`.

2. **Discarded clauses are untouched**: For a clause with `final_status == DISCARDED`, after the node runs its `risk_level` and `risk_rationale` remain absent/`None`, and **no** LLM call is made for it (assert by counting calls).

3. **`final_status is None` is skipped (defensive)**: A clause whose `final_status` is `None` (should not occur post-Node-4, but defensively) is not scored and incurs no LLM call.

4. **Level echoes the judgment**: When the mocked scorer returns `HIGH` for a validated finding, that clause's `risk_level == RiskLevel.HIGH`; likewise `MEDIUM → MEDIUM` and `LOW → LOW`.

5. **Only validated findings incur LLM calls**: The number of scoring LLM calls equals the number of `VALIDATED` clauses in the input (no calls for discarded / `None` clauses).

6. **Uses the generative model, not the embedding model**: Every LLM call uses `OLLAMA_MODEL_NAME`; the node never references `OLLAMA_EMBED_MODEL_NAME`. A test asserts these two constants are distinct and that the embedding model name is never passed to the node's LLM call.

7. **Uses configured constants**: The per-call timeout, circuit-breaker threshold, prompt-truncation limit, rationale-truncation limit, and fail-safe default level are all read from `app.config` (constitution §3), never hardcoded inline in node logic.

8. **Defensive `ingest_error` check**: If `ingest_error` is set (non-`None`) in the input state, the node returns immediately with an empty `clauses` update and makes no LLM calls.

9. **Empty clauses input**: If the input `clauses` dict is empty (`{}`), the node returns an empty `clauses` update without any LLM calls, and logs a warning.

10. **No validated findings**: If `clauses` is non-empty but contains zero `VALIDATED` records (e.g. an all-discarded document), the node returns an empty `clauses` update, makes zero LLM calls, and logs an info line. This is a valid outcome, not an error.

11. **Partial update only**: In the normal (no-outage) case the returned dict contains ONLY the keys `clauses`, `current_node`, and `node_timings`, with NO `error_count` and no keys owned by other nodes. The single permitted addition is `error_count: 1` when — and only when — the circuit breaker opened during the run (AC-15).

12. **Graceful LLM failure (fail-safe)**: If an LLM call raises or times out for a validated finding, that finding receives the **fail-safe default level** (`RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE`, pinned `HIGH` — §4.4), its `risk_rationale` records that the level was assigned automatically due to a scoring failure, the pipeline does NOT crash, and other findings still process. A single-finding failure alone does NOT increment `error_count`.

13. **Malformed / unparseable LLM output**: If the LLM returns text that does not map to a valid `RiskLevel`, the node treats it as a scoring failure (AC-12 path): fail-safe default level, rationale notes the failure, no crash. This counts toward the consecutive-failure counter (AC-14).

14. **LLM circuit breaker**: When LLM calls fail for `RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD` findings **consecutively**, the node marks the LLM backend as down for the remainder of the run and applies the fail-safe default level to all **remaining validated findings** without issuing further LLM calls (no per-finding timeout wait). A single "circuit opened" warning is logged; the consecutive-failure counter resets on any successful LLM call. (Discarded / `None` clauses remain skipped regardless — they never depended on the LLM.)

14a. **Only LLM-issuing failures move the consecutive-failure counter**: Exactly the paths that actually **issued an LLM call and got an unrecoverable result** (raise, timeout, or unparseable output — AC-12/13) increment the consecutive-failure counter, and any successful scoring call resets it. Paths that reach the fail-safe default **without issuing an LLM call** — the empty/whitespace-text skip (Edge Case 6) and the post-circuit-open bulk default (Edge Case 5) — are **circuit-neutral**: they neither increment nor reset the counter. Test: a run of only empty-text validated findings applies the fail-safe default to each but never opens the circuit and returns **no** `error_count` key. (Mirrors Self-RAG's zero-LLM Branch B being exempt from circuit accounting, `self_rag_validation_agent.py:167`.)

15. **Circuit-open health signal**: On a run where the circuit breaker opens, the returned partial dict includes `error_count: 1` (exactly one, regardless of how many findings were fail-safed afterward). On a run where the breaker never opens, the returned dict includes no `error_count` key. (Assert both directions.)

16. **`current_node` pinned**: After the node runs, `current_node == "risk_score"` and the same string is the key in the returned `node_timings` dict.

17. **Re-run overwrite (defensive)**: If a validated finding already carries `risk_level` / `risk_rationale` (e.g. a re-run), the node overwrites both; the `merge_nested_clause_dicts` reducer preserves the non-risk fields (`text`, `evidence_snippets`, Self-RAG verdicts, etc.).

18. **Rationale truncation**: A generated `risk_rationale` longer than `RISK_RATIONALE_MAX_CHARS` is truncated to that limit before being written to state; truncation is logged at debug level.

19. **Prompt truncation**: The clause text and concatenated evidence snippets fed into the scoring prompt are truncated to `RISK_SCORE_PROMPT_MAX_CHARS` before the LLM call; truncation is logged at debug level.

20. **Validated finding with empty evidence still scores**: For a `VALIDATED` finding whose `evidence_snippets` is `[]`/`None` (Self-RAG's high-risk rescue path), the node still assigns a `risk_level` using the clause text (and `clause_type`) alone, without crashing.

21. **`suggested_rewrite` untouched**: The node never sets or modifies `suggested_rewrite` on any clause (that field is owned by Node 6).

22. **`risk_level` is a valid enum member**: Every assigned `risk_level` is a member of `RiskLevel` (serializes to `"low"`/`"medium"`/`"high"`), never a raw free-text string.

## 4. Edge Cases

1. **`ingest_error` set**: Return immediately with no scoring work (AC-8). Same defensive pattern as Nodes 2–4.

2. **Empty `clauses` dict**: Return an empty `clauses` update, log a warning, make no LLM calls (AC-9).

3. **No validated findings** (`clauses` non-empty, all `DISCARDED` / `None`): Return an empty `clauses` update, make no LLM calls, log an info line (AC-10). Nothing flows to Node 6 as a risk-scored finding — a legitimate outcome for a benign document.

4. **LLM call fails / times out / returns malformed output for a finding**: On any unrecoverable LLM failure (Ollama unreachable, timeout > `RISK_SCORE_TIMEOUT_SECONDS`, unparseable response) apply the **fail-safe default level** (`RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE`, pinned `HIGH` — §7.2), set a `risk_rationale` noting the automatic assignment, log a rate-limited warning, and continue with the next finding. Never crash. Rationale for **HIGH** as the default: consistent with a risk detector's bias against false negatives (mirrors Self-RAG's fail-open to `VALIDATED`) — a finding we could not score is surfaced at maximum severity for human attention rather than silently downgraded. Resolved as `HIGH` (§8a R1); it remains a tunable config constant because it is the one genuinely load-affecting default (HIGH maximizes downstream Redline load).

5. **LLM backend down mid-run (circuit breaker)**: After `RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD` **consecutive** LLM failures, the node stops attempting LLM calls for the rest of this run and applies the fail-safe default level (Edge Case 4) to every remaining **validated** finding, without paying the per-finding timeout. A single "circuit opened" warning is logged **and the node emits `error_count: 1` once** (§2 Error accounting / AC-15) so a wholesale fail-safe run is distinguishable downstream from a clean run where every finding was genuinely scored. The counter resets on any successful LLM call, so intermittent single failures never trip it. Only LLM-issuing failures move the counter (AC-14a); the post-open bulk default applied to remaining findings issues no LLM call and is itself circuit-neutral. This is a per-run routing/runtime guarantee bounding aggregate node time when Ollama is unreachable; not persisted across pipeline invocations. Directly mirrors Self-RAG Edge Case 8 / CRAG Edge Case 13.

6. **Empty / whitespace-only clause text on a validated finding** (defensive — Self-RAG would normally have discarded such a clause): if a `VALIDATED` finding's `text` is empty/whitespace, skip the LLM call and apply the fail-safe default level with a rationale noting missing text (so a validated finding is never silently left unscored), log a warning. Other findings still process. Because no LLM call is issued, this skip is **circuit-neutral** — it does not touch the consecutive-failure counter (Edge Case 5 / AC-14a); a document full of empty-text findings must not spuriously open the circuit or emit a false `error_count: 1`.

7. **Validated finding with empty / absent evidence** (`evidence_snippets` `[]`/`None`, from Self-RAG's high-risk rescue path): score on clause text + `clause_type` alone. Never crash (AC-20).

8. **Very long clause text or evidence**: The clause text and concatenated evidence snippets fed into the prompt are truncated to `RISK_SCORE_PROMPT_MAX_CHARS` before the LLM call (AC-19). Truncation logged at debug level.

9. **Very long generated rationale**: `risk_rationale` is truncated to `RISK_RATIONALE_MAX_CHARS` before being written to state (AC-18). Truncation logged at debug level.

10. **Finding already carries risk fields (re-run)**: The node overwrites `risk_level` and `risk_rationale`; the reducer preserves all non-risk fields (AC-17).

11. **Large validated-finding count**: The node processes validated findings strictly sequentially (mirrors CRAG §7.6 / Self-RAG Edge Case 7). Per-finding runtime is bounded by `RISK_SCORE_TIMEOUT_SECONDS`; the aggregate worst case (backend down → every finding pays the timeout) is bounded by the circuit breaker (Edge Case 5).

12. **All findings scored the same level** (e.g. every validated finding is `HIGH`): a valid outcome; the node makes no assumption about level distribution.

## 5. Out of Scope

RiskScore does NOT handle:

1. **Deciding validated vs discarded** — that is **Self-RAG validation (Node 4)**, `specs/006-self-rag-validation`. RiskScore consumes `final_status` as a gate and never re-opens the validation decision.

2. **The `route_on_risk` conditional edge itself** — that is **Node 6's** edge (constitution §2), specced in `specs/008-*` (future). RiskScore only *writes* `risk_level`; it does not branch on it. In particular, the policy of **which** levels route to RedlineAgent vs SkipRedline (e.g. whether `LOW` warrants a rewrite) is Node 6's decision, not Node 5's (see §8b).

3. **Drafting safer clause language (redlining)** — **RedlineAgent (Node 6)**. RiskScore produces no `suggested_rewrite`.

4. **Compiling the final report and the top-level `evidence_trail`** — **ReportAgent (Node 7)**. RiskScore writes only the per-clause `risk_level` / `risk_rationale`.

5. **Gathering or scoring retrieval evidence / confidence** — **CRAG retrieval (Node 3)**, `specs/005-crag-retrieval`. RiskScore consumes `evidence_snippets` and `confidence_score` as given (as context) and performs no retrieval, embedding, or web search. Note the distinction: CRAG's `confidence_score` is *retrieval* confidence, unrelated to this node's *risk* level.

6. **Re-scoring or aggregating a document-level risk score** — this spec assigns risk **per validated finding** only. A single roll-up "overall contract risk" summary, if ever wanted, belongs to ReportAgent (Node 7) and is out of scope here; `001` reserves no document-level risk field and adding one would be a constitution §10 schema change (resolved out of scope — §8a R4).

7. **Human-in-the-loop override of an assigned risk level** — no review/override UI (consistent with the PERMANENTLY CUT "no audit log UI / dashboard" items).

8. **Bounded-parallelism over findings** — sequential for Phase 1, matching CRAG §7.6 and Self-RAG §5.8; a concurrency knob is deferred.

## 6. Configurable Constants

Per constitution §3, all thresholds live in `backend/app/config.py`. This spec adds a new `# ── RiskScore thresholds` section; no RiskScore constant exists there yet. The node also uses the existing shared `OLLAMA_MODEL_NAME` for its generative calls — it introduces no new model constant.

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
# unparseable output, empty text, or circuit open) — spec §4.4 / §7.2. HIGH biases
# toward surfacing at maximum severity for human review, consistent with Self-RAG's
# fail-open to VALIDATED. Configurable because it directly shifts downstream Redline
# load (spec §8a R1); tune against real sample contracts.
```

(All defaults are starting points to be tuned against real sample contracts after implementation. Note there is intentionally **no** `RISK_SCORE_MAX_ATTEMPTS` retry constant — constitution §2 mandates retries only for Self-RAG's ISSUP check, not for RiskScore; see §8a R6.)

## 7. Pinned Design

The pins below are safe to plan and implement against. All the design decisions they touch are now resolved (§8a); only the Node-6 routing-threshold question (§8b) remains open, and it does not change anything Node 5 does.

### 7.1 One LLM call per validated finding
RiskScore makes a **single** generative call per validated finding, returning a `{risk_level, rationale}` judgment from the clause text + merged evidence + `clause_type`. No retry loop (contrast Self-RAG's ISSUP retries — constitution §2 scopes retries to Self-RAG only). A single unparseable/failed call takes the fail-safe default (§7.2) rather than re-sampling. Rejected alternatives: (a) a **rule-based** `clause_type → level` lookup (too coarse — severity depends on the specific terms, not just the category); (b) a **hybrid** clause_type-prior + LLM. Both are resolved-rejected in §8a R5. Sequential processing over findings, matching CRAG §7.6 / Self-RAG.

### 7.2 Fail-safe default = HIGH
On any unrecoverable scoring failure the finding defaults to `RiskLevel.HIGH` (`RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE`), so an un-scorable but *validated* finding surfaces at maximum severity for human review rather than being silently downgraded. This is the risk-tool-appropriate bias against false negatives and is the direct analogue of Self-RAG's fail-open to `VALIDATED`. Its cost — inflating downstream Redline load when Ollama is flaky — is the reason it is a **configurable constant** (tunable, §8a). The circuit-breaker bulk outcome (Edge Case 5) uses this same default, and the breaker opening emits the `error_count` health signal so a wholesale-defaulted run is not mistaken for a genuinely all-HIGH document.

### 7.3 Every validated finding gets a level; "clean" is not a Node-5 outcome
`RiskLevel` has only `LOW`/`MEDIUM`/`HIGH` — there is no "none/clean" member, and this spec adds none. A finding reaching Node 5 has already passed Self-RAG's ISSUP gate ("worth flagging"), so assigning it a positive severity is coherent; the "no risk → SkipRedline (clause marked clean)" branch in constitution §2 corresponds to clauses that never validated (Self-RAG `DISCARDED`), which `route_on_risk` (Node 6) handles — **not** to a validated finding being re-labelled clean here. Making "clean" representable at Node 5 would require a new `RiskLevel` member (or a nullable outcome) and thus a `001`-schema change under constitution §10; ruled out (§8a — enum stays LOW/MEDIUM/HIGH).

### 7.4 Circuit-open health signal
As with Self-RAG §7.6, per-finding fail-safe (§7.2) is silent by design — one flaky call should not raise a pipeline error — but a **circuit-breaker open** means the backend is down and the rest of the run is being defaulted wholesale, which must not look identical to a clean run. So when (and only when) the breaker opens, the node returns `error_count: 1` **once** (the `operator.add` reducer accumulates it). Exactly one increment per run; the breaker opens at most once. A health signal for observability, not a hard abort; it does not alter RiskScore's control flow.

## 8. Design Decisions and Open Questions

### 8a. Resolved / pinned (safe for plan.md)

Structural invariants (follow directly from the constitution / shared conventions):

- **Scope gate** — RiskScore scores **only** `final_status == VALIDATED` clauses; `DISCARDED` / `None` are skipped with no LLM call and left untouched (§2, AC-2/3). Follows directly from the constitution's node ordering.
- **Model** — generative `OLLAMA_MODEL_NAME` only; never the embedding model (§1, AC-6). Constitution §8.
- **Partial update + error accounting** — returns only `clauses`/`current_node`/`node_timings` normally, `+ error_count:1` iff the circuit opened (§2, AC-11/15). Mirrors Self-RAG §8a R5.
- **Circuit breaker** — mirror Self-RAG/CRAG: consecutive-failure threshold, bulk fail-safe, single health signal, per-run reset (§4.5, AC-14/15). **Only LLM-issuing failures move the consecutive counter**; zero-LLM fail-safe paths (empty-text skip, post-open bulk default) are circuit-neutral (AC-14a) — mirrors Self-RAG's exempt zero-LLM Branch B.
- **Constants in config** — all thresholds in `app.config` (§6); no inline literals (constitution §3, AC-7).

Design decisions resolved with the user on 2026-07-05 (were open in a prior draft; now pinned):

- **R1 — Fail-safe default = `HIGH`** (was Q1). A finding that already passed Self-RAG's "worth flagging" gate but could not be scored surfaces at maximum severity rather than being silently downgraded — the risk-tool bias against false negatives, directly consistent with Self-RAG's fail-open to `VALIDATED`. The two objections are neutralized: it is a **config constant** (`RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE`, tunable) and the circuit-breaker `error_count: 1` keeps a wholesale-defaulted run distinguishable from a genuinely all-`HIGH` document. Confirms §7.2 / §4.4.

- **R2 — `RiskLevel` stays `LOW`/`MEDIUM`/`HIGH`; "clean" is not a Node-5 outcome** (was Q2). "Clean" = Self-RAG `DISCARDED`, handled at Node 6. Adding a member would be a `001`-schema change for no benefit. Confirms §7.3.

- **R3 — Empty/whitespace text on a validated finding → fail-safe default** (was Q3). Skip the LLM, apply the default level (circuit-neutral, §4.6). Leaving it `None` would break the invariant "every validated finding has a `risk_level`" and let an ambiguous record reach `route_on_risk`. Confirms §4.6.

- **R4 — Out of scope: document-level roll-up risk** (was Q5). A single overall-contract risk score is a ReportAgent/Node-7 concern and would need a `001` field; not added here. Confirms §5.6.

- **R5 — Scoring method: pure LLM, single call, `clause_type` as soft context** (was Q6). Rule-based `clause_type → level` is too coarse (severity depends on the specific terms); a hybrid is unnecessary Phase-1 complexity. Confirms §7.1.

- **R6 — No retry loop** (was Q7). Constitution §2 scopes retries to Self-RAG's ISSUP check only; a self-consistency re-sample trades latency (§9) for marginal determinism. No `RISK_SCORE_MAX_ATTEMPTS`. Confirms §7.1 / §6.

- **R7 — State-key name `"risk_score"`** (was Q8). Matches `builder.py`'s "feature-007 (RiskScore)" comment and the `crag_retrieval` / `self_rag_validation` snake-case, no-`_agent`-suffix pattern. Confirms §2.

### 8b. Remaining open question

1. **Which risk levels should `route_on_risk` (Node 6) send to Redline vs SkipRedline?** This is **Node 6's** decision (`specs/008-*`, future), not a Node-5 change — recorded here so the level semantics are settled before `008` is specced. **Recommendation: keep `LOW` assignable** (`LOW` is a genuine low-severity finding, not "clean"; "clean" is already Self-RAG `DISCARDED`).

   **Design tension to inherit into Node 6 (`008`):** Constitution §2 defines `route_on_risk` as *risk found → Redline / no risk → SkipRedline (clause marked clean)*. But §7.3/R2 pin that **every** validated finding is `LOW`/`MEDIUM`/`HIGH` (all "risk found"), and "clean" was already consumed by Self-RAG discard. Taken literally, this means **SkipRedline may never fire for a validated finding** — every scored clause routes to Redline. That is coherent, but it must be a *conscious* choice in `008`, not a surprise. This is the real substance of the question: if Node 6 decides `LOW → SkipRedline`, then `LOW` becomes the effective "clean-ish" branch for validated findings. Node 5 assigns the level regardless; only the routing threshold is deferred.

## 9. Evaluation

RiskScore assigns a scored judgment per validated finding, so the following metrics MUST be logged per run for later tuning (per `specs/002-tech-stack.md` §3i eval tooling), following the `logger.info(..., extra={...})` structured-log pattern established in `crag_retrieval_agent.py` and `self_rag_validation_agent.py`. These live in **log records, NOT in `ContractState`**, which carries only aggregate `node_timings["risk_score"]`.

1. **Risk-level distribution** — counts/fractions of `LOW` / `MEDIUM` / `HIGH` across scored findings (per document and aggregate). The headline signal of how severity is spread and whether the model skews to one level.
2. **Risk-level by `clause_type`** — the cross-tab of assigned level against clause type (do `liability` / `termination` / `intellectual_property` / `dispute_resolution` clauses skew `HIGH` as expected?). Validates that the severity judgment tracks the categories Self-RAG treats as high-risk.
3. **Scoring-failure rate & circuit-breaker events** — fraction of validated findings that took the fail-safe default due to LLM failure/timeout/unparseable output, and count of runs where the circuit opened (each emits `error_count: 1`, §7.4). Should be ~0 in a healthy deployment; a spike here means the `HIGH`-default is inflating the level distribution artificially (cross-check with metric 1).
4. **Rationale length & truncation rate** — distribution of `risk_rationale` length and how often it hit `RISK_RATIONALE_MAX_CHARS`, to calibrate that cap.
5. **Latency** — per-finding scoring-call latency and total node wall-clock time (the value that also feeds `node_timings`). Supports constitution §9 tuning; expected lighter than Self-RAG since only validated findings are scored.
6. **Redline-routing preview** — of scored findings, the fraction at each level that will route to Redline vs SkipRedline under Node 6's (future) policy. Cross-referenced with Node 6's own metrics once `008` exists; the direct input for tuning the level→route threshold (§8b).
7. **Risk-level accuracy (requires ground truth)** — when labeled sample contracts are available, compare assigned `risk_level` against human severity labels to estimate over-scoring (benign flagged `HIGH`) and under-scoring (serious flagged `LOW`) rates. Cannot be computed from logs alone; the per-finding level + rationale logs above are the raw material for that offline analysis.

These metrics directly support tuning `RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE`, the level→Redline routing policy (Node 6), and the scoring prompt against real sample contracts once implementation is complete.
