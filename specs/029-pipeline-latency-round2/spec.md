# Feature 029 — Pipeline latency reduction round 2 (within-node levers C + F)

## 1. Problem statement

The 7-node pipeline is still slow. Re-measured on 2026-07-28 (post-025/027/028, qwen3:8b,
delivery off, n=1 each): **~3.0 min for a 6-clause contract and ~3.6 min for an 8-clause one**.
The root cause remains **generative LLM-call volume/size**, not model size. Two nodes dominate:

- **Self-RAG validation (Node 4) — ~42–47s.** Per evidence-bearing clause it makes **up to 3
  sequential** generative calls (Relevance → ISREL → ISSUP). For a document of N clauses this is up
  to ~3N sequential round-trips. This is *already* with feature 025's Lever B (`SELF_RAG_MAX_ATTEMPTS=1`)
  and 027's recall-floor short-circuit — the remaining cost is the **three separate calls**, not retries.
- **ClauseSplitter (Node 2) — ~58–70s.** A **single** LLM refinement call, but an expensive one: the
  prompt instructs the model to **re-emit the full text of every clause** (`num_predict: 4096`,
  "Preserve ALL original text"), so output-token generation dominates the wall time. Feature 025's
  Lever A size-gate (`CLAUSE_SPLITTER_LLM_MAX_CLAUSES=40`) does **not** help here because real
  contracts in the common case are far below 40 clauses — the gate never fires, and the full,
  text-re-emitting call runs every time.

This feature applies two **within-node, config-gated, reversible** speed levers that leave the fixed
architecture untouched:

- **Lever C — merge Self-RAG's three judgment calls into ONE combined prompt per clause.** Cuts the
  evidence-present path from up to 3 sequential generative calls to exactly 1, targeting the ~42–47s node.
- **Lever F — slim the ClauseSplitter refinement call** so the LLM no longer re-emits full clause
  text (it returns boundary/grouping + `clause_type` metadata; the node reassembles text locally),
  with a correspondingly reduced output-token cap, targeting the ~58–70s node.

### Position relative to the constitution

**No amendment. No new node/edge. No `ContractState` schema change (001).** The StateGraph keeps its
exactly 7 nodes and exactly 2 conditional edges (§2). Only the **internal behavior** of two existing
nodes changes; the per-clause fields they write (`relevance_verdict`, `isrel_verdict`,
`issup_verdict`, `retry_count`, `final_status`; and `text`, `section_number`, `clause_type`) are the
same names and semantics defined in 001. Both levers are exposed as **named, configurable constants in
the single shared config module** exactly as §3 requires, since they will be tuned against real sample
contracts. Per §9 (local-model latency) the merged call keeps a single wall-clock timeout and fail-open
semantics. Per §11 developed on `feature/029-pipeline-latency-round2`; per §7 TDD. This is the same
class of change as feature 025 (config-driven, reversible, no graph/state change).

Cross-node merges (e.g. folding Self-RAG into RiskScore, or RiskScore into Redline) are **explicitly
out of scope** — they would merge nodes and therefore require a §2 amendment (see §5 Out of scope).

## 2. Inputs and outputs

Neither lever adds or renames any `ContractState` field. Both read and write exactly the slice of
`clauses[clause_id]` that their node already owns per 001-contract-state-schema.md §3.

### 2.1 Lever C — Self-RAG combined judgment (Node 4)

**Reads** (unchanged, per clause record): `text`, `evidence_snippets`, `clause_type`.

**New config (§3):**
- `SELF_RAG_MERGE_JUDGMENTS: bool = True` — when `True`, the evidence-present validation path
  ("Branch C") issues **one** combined-judgment LLM call returning all three verdicts at once. When
  `False`, the node uses the pre-029 three-separate-call path **byte-for-byte** (full reversibility).

**Combined-call contract:** for an evidence-present clause, one LLM call returns a single JSON object:
```json
{"relevance": true|false, "isrel": true|false, "issup": true|false,
 "reason": "<one short sentence>"}
```
The node then applies the **existing, unchanged decision logic** to those three verdicts:
- `relevance == False` → `final_status = DISCARDED` (ISREL/ISSUP ignored).
- `relevance == True` AND `clause_type ∈ SELF_RAG_RECALL_FLOOR_TYPES` → `final_status = VALIDATED`
  (027 recall-floor short-circuit; ISREL/ISSUP ignored).
- `relevance == True`, non-floor, `isrel == False` → `DISCARDED`.
- `relevance == True`, non-floor, `isrel == True`, `issup == False` → `DISCARDED`.
- `relevance == True`, non-floor, `isrel == True`, `issup == True` → `VALIDATED`.

**Writes** (unchanged field names/semantics per 001): `relevance_verdict`, `isrel_verdict`,
`issup_verdict`, `retry_count`, `final_status`. When the merged call supplies a verdict, that field is
populated with the corresponding bool; a field the decision path does not consume is written `None`
(exactly as the three-call path leaves un-reached checks `None` today — e.g. a `relevance=False`
result still records `isrel_verdict=None, issup_verdict=None`). `retry_count` follows the current
rule (0 when a single ISSUP attempt succeeds; `None` on the short-circuit/discard-before-ISSUP paths).

### 2.2 Lever F — ClauseSplitter slim refinement (Node 2)

**Reads** (unchanged): the regex pre-pass output (`ClauseBoundary` list: `position`,
`section_number`, `text`).

**New config (§3):**
- `CLAUSE_SPLITTER_LLM_EMIT_TEXT: bool = False` — when `False` (new default), the refinement prompt
  asks the model for **grouping/boundary + `clause_type`** metadata only, and the node **reassembles
  each clause's text locally** from the regex segments. When `True`, the node uses the pre-029
  text-re-emitting prompt **byte-for-byte** (full reversibility).
- `CLAUSE_SPLITTER_LLM_NUM_PREDICT: int = 1024` — output-token cap for the refinement call. Replaces
  the hardcoded `num_predict: 4096`; the slim (metadata-only) response needs far fewer tokens. (When
  `CLAUSE_SPLITTER_LLM_EMIT_TEXT=True`, the cap reverts to the pre-029 `4096` so the reversible path
  is unchanged.)

**Writes** (unchanged field names/semantics per 001): each refined clause's `text`, `section_number`,
`clause_type`. The exact schema by which the LLM expresses merges/splits without re-emitting text is
an **Open Question** (§6 Q1) that the plan must resolve; the *output* into state is unchanged either way.

### 2.3 What is NOT changed

CRAG retrieval (Node 3), RiskScoreAgent (Node 5), route_on_risk, RedlineAgent (Node 6), and
ReportAgent (Node 7) are untouched. All timeouts, prompt-max-char budgets, circuit-breaker thresholds,
temperature/seed (028), and the recall-floor type set (027) keep their existing config values.

## 3. Acceptance criteria

### Lever C — Self-RAG combined judgment
- **AC-1** With `SELF_RAG_MERGE_JUDGMENTS=True`, an evidence-present, non-floor clause that would
  previously be VALIDATED via Relevance=T→ISREL=T→ISSUP=T is validated by **exactly one** LLM call.
- **AC-2** The number of generative calls for an evidence-present clause is **1** when merging is on
  (verifiable by counting mocked `client.chat`/reflector calls), vs 2–3 when off.
- **AC-3** Verdict-field outcomes are preserved for every combination of (relevance, isrel, issup) ∈
  {T,F}³ — a parametrized test asserts the same `final_status` and the same
  `relevance_verdict`/`isrel_verdict`/`issup_verdict`/`retry_count` the three-call path produces for
  that combination (per the §2.1 decision table).
- **AC-4** `relevance=False` from the merged call → `DISCARDED`, with `isrel_verdict=None` and
  `issup_verdict=None` (downstream verdicts not consumed), regardless of the isrel/issup values the
  model returned.
- **AC-5** A recall-floor `clause_type` (∈ `SELF_RAG_RECALL_FLOOR_TYPES`) with `relevance=True` →
  `VALIDATED` (027 behavior preserved) even if the merged call returned `isrel=False`/`issup=False`.
- **AC-6** Fail-open preserved: if the merged call fails entirely (timeout, non-JSON, missing/`non-bool`
  verdict object) → `final_status=VALIDATED` (fail-open), matching today's None-handling.
- **AC-7** Partial result: if the JSON parses but an individual verdict key is missing or non-bool,
  that verdict is treated as `None` and the **existing** per-verdict None-handling applies (fail-open
  at the point it would be consumed) — asserted for a missing `issup` and a missing `relevance`.
- **AC-8** Circuit-breaker accounting is **per LLM call**: with merging on, an evidence-present clause
  produces **one** accounting event (not up to three). A test asserts the breaker opens after
  `SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD` consecutive failed *clauses*, and that fail-open applies to
  the remaining clauses once open (post-trip behavior unchanged).
- **AC-9** Reversibility: with `SELF_RAG_MERGE_JUDGMENTS=False`, the node makes the pre-029 sequence of
  up to three separate calls and all existing Self-RAG tests pass unchanged.
- **AC-10** The empty-evidence paths are unchanged by Lever C: Branch A (empty evidence + floor type)
  still makes its single text-only ISSUP call; Branch B (empty evidence, non-floor) is still a
  zero-LLM discard. (Lever C only merges the evidence-present Branch C.)

### Lever F — ClauseSplitter slim refinement
- **AC-11** With `CLAUSE_SPLITTER_LLM_EMIT_TEXT=False`, the refinement LLM response contains **no full
  clause text** (metadata-only per the §6-Q1 schema), and every output clause's `text` is reassembled
  by the node from the regex segments.
- **AC-12** Text preservation: for a document whose regex segments the LLM merely regroups, the
  concatenation of all output clause `text` values equals the concatenation of the input regex-segment
  texts (no text dropped, added, reordered, or rewritten). The existing "dropped too much text" guard
  (`output_chars < input_chars * 0.5` → fall back to regex) is preserved or superseded by an exact
  reassembly check.
- **AC-13** `clause_type` classification still works: output clauses carry a valid `ClauseType` value
  or `None`, validated against the same `_VALID_CLAUSE_TYPES` set as today.
- **AC-14** The refinement call uses `num_predict = CLAUSE_SPLITTER_LLM_NUM_PREDICT` (default 1024)
  when emit-text is off, and `4096` when emit-text is on.
- **AC-15** Fail-safe preserved: any LLM failure (timeout, invalid JSON, schema violation, reassembly
  inconsistency) → the node falls back to the **regex-only** clause list, exactly as today; the node
  never raises.
- **AC-16** Reversibility: with `CLAUSE_SPLITTER_LLM_EMIT_TEXT=True`, the node uses the pre-029
  text-re-emitting prompt and `num_predict=4096`, and all existing ClauseSplitter tests pass unchanged.
- **AC-17** Lever A interaction unchanged: the size-gate (`CLAUSE_SPLITTER_LLM_MAX_CLAUSES`) still
  decides *whether* refinement runs at all; Lever F only changes *how* the refinement call is shaped
  when it does run.

### Cross-cutting
- **AC-18** Both levers are named constants in the shared config module (§3); no threshold, cap, or
  toggle is hardcoded inline in node logic.
- **AC-19** With both toggles set to their reversible (pre-029) values, the pipeline's per-clause
  outputs are identical to pre-029 for the corpus docs (regression guard).
- **AC-20** Measured effect (documented, not a unit assertion): re-running `backend/scripts/latency_measure.py` (path relative to the `backend/` run dir: `scripts/latency_measure.py`)
  with defaults shows a reduction in the `self_rag_validation` and `clause_splitter` node timings vs
  the 2026-07-28 baseline (self_rag ~42–47s, clause_splitter ~58–70s), recorded in the tasks.md
  measurement note. No accuracy regression beyond noise on the eval harness (026/027 metrics).
- **AC-21** No `ContractState` field is added, renamed, or removed; the graph still has 7 nodes and 2
  conditional edges.

## 4. Edge cases

- **Empty / whitespace clause text (Self-RAG):** unchanged — still a zero-LLM discard (Edge Case 6);
  the merged call is not issued for empty text.
- **Empty evidence (Self-RAG):** the merged (Branch C) call is only for evidence-present clauses.
  Empty-evidence clauses keep Branch A (floor → single text-only ISSUP) / Branch B (non-floor →
  zero-LLM discard). Lever C must not route an empty-evidence clause through the combined prompt.
- **Merged call returns malformed/partial JSON:** whole-object parse failure → fail-open VALIDATED
  (AC-6); object parses but a key is missing/non-bool → that verdict is `None`, existing None-handling
  applies (AC-7). No exception escapes the node.
- **Circuit breaker mid-document (Self-RAG):** once open, remaining clauses fail-open VALIDATED with
  all verdict fields `None` (unchanged). Accounting is now one event per clause (AC-8) — the breaker
  trips after fewer *events* than the three-call path for the same number of failing calls; this is an
  intended consequence of merging, called out for confirmation (§6 Q3).
- **ISSUP retry loop:** with a single merged call there is no separate ISSUP retry round-trip;
  `SELF_RAG_MAX_ATTEMPTS` is already 1 (025), so `retry_count` is 0 on a validated merged result and
  `None` on short-circuit/discard-before-ISSUP paths. If `SELF_RAG_MAX_ATTEMPTS>1` is ever restored,
  the plan must define whether a merged `issup=False` re-issues the whole combined prompt or is treated
  as terminal (see §6 Q4).
- **ClauseSplitter — LLM splits a run-on segment (Lever F):** if the chosen §6-Q1 schema cannot
  express an intra-segment split without re-emitting text, a split request must degrade safely (keep
  the regex boundary) rather than corrupt or drop text; any inconsistency triggers the regex fallback
  (AC-15). This is the crux of Q1.
- **ClauseSplitter — reassembly mismatch (Lever F):** if reassembled text fails the preservation check
  (AC-12), the node falls back to regex-only output; it never emits partially-reassembled clauses.
- **Timeouts:** both calls keep their existing per-call wall-clock timeout
  (`SELF_RAG_TIMEOUT_SECONDS`, `CLAUSE_SPLITTER_TIMEOUT_SECONDS`) and fail-open/fail-safe on expiry
  (§9). The merged Self-RAG call replaces up to three timeouts with one, so worst-case Self-RAG
  wall-time per clause *decreases*.

## 5. Out of scope

- **Cross-node merges** (Self-RAG⊕RiskScore, RiskScore⊕Redline, or any prompt spanning two nodes) —
  these change the fixed 7-node graph and require a §2 constitution amendment. Not this feature.
- **RiskScore / Redline prompt-slimming** — each is already one call per clause; investigation
  (2026-07-28) showed the volume win is in Self-RAG and the size win is in ClauseSplitter. Deferred; a
  future feature owns any RiskScore/Redline prompt tuning if warranted.
- **CRAG retrieval latency** — no generative call per clause (embeddings + KB + web fallback); out of
  scope here, owned by 005 if revisited.
- **Changing the accuracy contract** — Lever C/F must preserve verdict/text semantics; any deliberate
  precision/recall retuning is owned by 027 (recall floor) / a future eval-driven feature, not here.
- **Model or embedding-model changes, quantization, GPU/hardware tuning** — out of scope.
- **New `ContractState` fields for timing/telemetry** — node_timings already exists (001); no new field.

## 6. Open questions

1. **(Lever F — architecturally significant) How should the slim refinement response encode merges and
   splits without re-emitting clause text?** Candidate schemes: (a) **index-grouping only** — the LLM
   returns, per output clause, the list of input regex-segment indices it groups plus `clause_type`;
   the node concatenates those segments. Cheapest output, but **cannot split a run-on segment**
   (intra-segment splits are lost — accept regex boundaries within a segment). (b) **index-grouping +
   optional char-offset split points** — adds the ability to split a segment at a returned offset;
   more tokens and more failure surface. (c) keep re-emitting text but drastically cap `num_predict`
   and instruct terseness. My recommendation is **(a)** — the regex pre-pass already sets boundaries,
   real contracts rarely need the LLM to *split* a regex segment (its main value is merge + classify),
   and (a) gives the biggest, safest speed win with an exact text-preservation guarantee. **Confirm
   (a), or require split capability via (b)?**
2. **(Rollout defaults) Ship both levers ON by default** (`SELF_RAG_MERGE_JUDGMENTS=True`,
   `CLAUSE_SPLITTER_LLM_EMIT_TEXT=False`) as this spec proposes, mirroring 025 which shipped its levers
   on — **or** ship them OFF and flip on only after the eval harness (026/027) confirms no accuracy
   regression? Recommendation: **ON by default**, with AC-20 requiring the harness/latency check before
   merge.
3. **(Lever C — circuit-breaker semantics) Confirm the accounting change is acceptable:** one
   accounting event per clause instead of up to three, so the breaker trips after fewer sub-checks fail.
   Recommendation: **accept** — accounting is intrinsically per-LLM-call, and one call per clause is the
   point of the lever.
4. **(Lever C — future retry) If `SELF_RAG_MAX_ATTEMPTS` is ever raised above 1**, should a merged
   `issup=False` re-issue the entire combined prompt, or should retries be considered incompatible with
   merging (retries only meaningful on the un-merged path)? Recommendation: **treat merged `issup=False`
   as terminal**; document that retries require `SELF_RAG_MERGE_JUDGMENTS=False`. Low urgency (attempts
   is 1 today).

## 7. Evaluation

Self-RAG validation is a confidence/verdict node, so the following should be logged/observed for
later analysis (extending the 026 harness and the `scripts/latency_measure.py` timing script; no new
`ContractState` field):

- **Node timings** before/after, per node, via `node_timings` — specifically the reduction in
  `self_rag_validation` and `clause_splitter` seconds vs the 2026-07-28 baseline (AC-20).
- **Generative-call count per clause** for Self-RAG (should be 1 on the evidence-present path with
  merging on) — countable via mocked reflector/`client.chat` invocations in tests, and observable in
  the harness run.
- **Verdict-distribution parity:** the counts of VALIDATED vs DISCARDED (and the
  relevance/isrel/issup verdict mix) on the eval corpus with merging ON vs OFF should match within
  LLM noise — the merged prompt must not systematically shift the discard rate.
- **Accuracy metrics unchanged:** precision / recall / false-flag from the 026 harness (and 027's
  recall-floor behavior) must hold within the documented noise band; regressions block merge (AC-20).
- **Text-preservation rate (Lever F):** fraction of documents where slim-refinement reassembly passes
  the exact-preservation check vs falls back to regex — a high fallback rate would indicate the Q1
  schema is too lossy.
