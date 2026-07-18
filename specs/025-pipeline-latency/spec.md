# Feature 025 — Pipeline latency reduction (config levers A + B)

## 1. Problem statement

The 7-node pipeline is slow (~2–5 min on the local 6 GB-VRAM box), which "ruins UX" — the user
watches the live steps and is auto-redirected to the report (017), so **shorter runtime = better
UX**. The root cause is **LLM-call volume**, not model size: on qwen3:8b the two hottest nodes are
**Self-RAG validation (~97s)** and **ClauseSplitter (~67s)** — together the majority of runtime.

This feature applies the two **low-risk, reversible, config-driven** speed levers the user selected
(A + B), leaving analysis correctness intact for the common case and fully revertible via config:
- **A — gate the ClauseSplitter LLM refinement** (fall back to the regex splitter that already
  exists), and
- **B — cut the Self-RAG ISSUP retry loop** from up to 3 attempts to 1.

### Position relative to the constitution

**No amendment. No new node/edge. No `ContractState` schema change.** Both levers are **named,
configurable constants** in the single shared config module, exactly as §3 (Configurable Thresholds)
requires — "since these will be tuned against real sample contracts after implementation." The 7-node
graph, its 2 conditional edges, and the state shape are untouched; only two node *behaviors* are
tuned via config. Per §11 developed on `feature/025-pipeline-latency`; per §7 TDD.

## 2. Inputs and outputs

### 2.1 Lever A — size-gate ClauseSplitter LLM refinement (Node 2)
- **New config:** `CLAUSE_SPLITTER_LLM_MAX_CLAUSES: int = 40` — the regex-clause-count ceiling at or
  below which the LLM refinement still runs. Above it, the refinement is skipped.
- **Behavior:** `clause_splitter_agent` currently always calls `refine_with_llm(regex_clauses, …)`.
  In the **normal path**, after `split_by_regex`, if `len(regex_clauses) > CLAUSE_SPLITTER_LLM_MAX_CLAUSES`
  the node **skips** `refine_with_llm` and uses the regex output directly (`refined = regex_clauses`,
  `llm_used = False`); otherwise it refines **exactly as today**. The **short-text path** (a single
  clause, `< MIN_CLAUSE_LENGTH`) is always ≤ the threshold, so it keeps the LLM (1 clause = cheap).
- **Rationale for the metric + default:** the real corpus splits cleanly into **~8-clause** contracts
  (normal) and **~185-clause** documents (the slow, expensive-to-refine outliers). A default of **40**
  sits well above a normal contract and well below the large-doc cluster, so normal contracts keep
  full LLM quality while only genuinely large documents fall back to regex. `40` is a **tunable §3
  constant** — calibrate against real `node_timings` (AC-8).
- **Output shape unchanged:** the node still returns `clauses` (same `ClauseBoundary` fields); above
  the threshold the clauses come from the regex splitter — see D1.

### 2.2 Lever B — cut Self-RAG ISSUP retries (Node 4)
- **Config change:** `SELF_RAG_MAX_ATTEMPTS: int = 3` → **`1`** (default). No code change — the node
  already reads this constant; `_issup_loop`'s `range(1, SELF_RAG_MAX_ATTEMPTS + 1)` yields exactly
  one attempt at `1`, with `retry_count = 0` (no off-by-one).
- **Behavior:** ISSUP is judged **once** per clause instead of retried up to 3×. All verdict
  semantics (relevance / ISREL / ISSUP, discard-vs-validate) are unchanged; only the *retry count* on
  an ISSUP-False result drops.

### 2.3 What is NOT changed
CRAG retrieval, RiskScore, route_on_risk, and Redline are untouched (lever C — merging the 3 Self-RAG
checks into one prompt — is explicitly out of scope, §6). Evidence, risk scoring, and redline output
are preserved.

## 3. Resolved decisions (inline)

- **D1 — Size-gated (accuracy preserved for normal contracts).** The LLM refinement is skipped
  **only** for documents whose regex-clause count exceeds `CLAUSE_SPLITTER_LLM_MAX_CLAUSES` (default
  40) — i.e. the large-document outliers. For those, clauses come from `split_by_regex`, which
  (a) splits run-on clauses less cleanly and (b) does **not infer `clause_type`** (`None`), so their
  finding titles fall back to "Clause {n}" (017 handles this) and the Self-RAG **high-risk
  clause-type rescue** (`SELF_RAG_HIGH_RISK_CLAUSE_TYPES`) fires less often. **Normal contracts
  (≤ threshold) are unaffected — full LLM typing and boundary refinement.** Consequence to be explicit
  about: small documents (e.g. the ~8-clause `heavy_contract.docx`) keep the LLM refinement, so
  **Lever A gives them no speedup — only Lever B does**; the clause-splitter win lands on large
  (100+ clause) documents. Fully tunable/reversible via the threshold (raise it to always refine,
  lower it to gate more aggressively).
- **D2 — Self-RAG max attempts → 1 (not 0).** One ISSUP judgment still happens (validation still
  runs); only the *retries* are removed. Discard/validate semantics are unchanged. Reversible by
  raising `SELF_RAG_MAX_ATTEMPTS`.
- **D3 — Config constants, not inline (§3).** Both levers are named constants in `app/config.py`; no
  behavior is hardcoded in node logic. They can be tuned per deployment without code changes.
- **D4 — No model change, no re-download.** These are model-independent call-volume reductions; the
  configured model (`qwen3:8b`) is unchanged. (A faster/larger model remains an orthogonal, separate
  concern.)
- **D5 — Lever C deferred.** Merging Self-RAG's relevance/ISREL/ISSUP into a single prompt is the
  larger Self-RAG win but rewrites the reflectors and changes verdict granularity — higher risk,
  deferred to a possible later feature (§6).
- **D6 — Backwards-safe tests.** Existing tests that pin the OLD defaults (LLM refinement on;
  3 attempts) are updated to set the constant **explicitly** for the behavior they intend to exercise
  — the assertions are not weakened; they are made independent of the new defaults (§7).

## 4. Acceptance criteria

### Backend (pytest)
- **AC-1:** When `split_by_regex` yields **more than** `CLAUSE_SPLITTER_LLM_MAX_CLAUSES` clauses,
  `clause_splitter_agent` does **not** call `refine_with_llm` (spy `assert_not_called()`) and the
  returned `clauses` are the regex boundaries verbatim (same ids / text / positions; `clause_type`
  is `None`, since regex infers no type). NOTE: `llm_used` is **not** a return field — it appears
  only in the completion log's `extra`; a test may additionally assert the `llm_used=False` log
  record via `caplog`, but the primary assertions are the spy call-count and the returned clauses.
  The test sets a low threshold so the gate triggers deterministically.
- **AC-2:** When the regex clause count is **≤** the threshold, `refine_with_llm` **is** called and
  the node behaves exactly as before (existing clause-splitter tests, which run below the default
  threshold, still pass unchanged).
- **AC-3:** The **short-text path** (single clause) is always ≤ the threshold, so it **keeps** the
  LLM refinement (no regression to clause-type inference for short docs).
- **AC-4:** With `SELF_RAG_MAX_ATTEMPTS = 1`, a clause whose ISSUP returns False is judged **once**
  (`check_issup` invoked ≤ 1× in `_issup_loop`) and yields `retry_count = 0`; the discard/validate
  outcome matches a single-attempt run.
- **AC-5:** With `SELF_RAG_MAX_ATTEMPTS = 3` (explicitly set), the retry behavior is unchanged
  (existing Self-RAG retry tests, pinned to 3, still pass).
- **AC-6:** The constants exist in `app/config.py` with the intended defaults
  (`CLAUSE_SPLITTER_LLM_MAX_CLAUSES = 40`, `SELF_RAG_MAX_ATTEMPTS = 1`); no node hardcodes either
  value (§3).
- **AC-7:** No graph/edge/`ContractState` change; `pytest` (whole suite) is green after the test
  updates in D6.

### Live (real backend)
- **AC-8 (smoke, manual):** Run the full pipeline on a **large (100+ clause) contract** (e.g. one of
  the ~185-clause PDFs — NOT the ~8-clause `heavy_contract.docx`, which stays below the threshold and
  keeps the LLM) before and after; record `node_timings`. On the large doc `clause_splitter` drops to
  near-0 (no LLM call) and Self-RAG's time does not grow; **total wall-clock is materially lower**
  than the pre-change baseline, with a coherent report still produced (findings, risk bands, redlines
  present). Also spot-check a normal ~8-clause doc to confirm it is unchanged (LLM still runs; Lever B
  is its only speedup).

## 5. Edge cases
- **EC-1 — Short text (< `MIN_CLAUSE_LENGTH`)** → single clause, ≤ threshold → LLM refinement still
  runs (clause-type inference preserved for short docs — AC-3).
- **EC-2 — Gated (large) doc above the threshold** → the existing `MAX_CLAUSES_LIMIT` pre-LLM clamp
  still applies; no post-LLM re-clamp is needed since no LLM runs. Clauses are the regex output.
- **EC-3 — `clause_type = None` on gated large docs** → finding titles use "Clause {n}" (017), and
  the high-risk-type rescue simply doesn't fire for those clauses; no crash, no fabricated type.
  Normal (≤ threshold) docs are unaffected.
- **EC-4 — `SELF_RAG_MAX_ATTEMPTS = 1` with ISSUP returning None (LLM failure)** → same
  not-assessable handling as today on the single attempt (no retry to mask a transient failure);
  behavior is deterministic and never raises.
- **EC-5 — Constants restored** (`CLAUSE_SPLITTER_LLM_MAX_CLAUSES` raised very high, `MAX_ATTEMPTS=3`)
  → byte-for-byte today's behavior (full reversibility, D1/D2).

## 6. Out of scope
- **Lever C** — merging Self-RAG's 3 checks into one prompt (D5) — a separate future feature.
- **Making Redline on-demand / off the critical path** — Redline is the most valuable output; not
  touched here.
- **CRAG / RiskScore tuning**, model swaps, GPU/hardware changes, batching, or streaming-format
  changes — none.
- **Any new node/edge, `ContractState` field, endpoint, or migration** — none.

## 7. Notes for plan.md / tasks.md (pointers)
- **Config:** add `CLAUSE_SPLITTER_LLM_MAX_CLAUSES = 40`; change `SELF_RAG_MAX_ATTEMPTS` default
  3 → 1 (both in `app/config.py`, near their existing node sections, with a one-line §3 rationale
  comment).
- **Node A:** in `app/graph/nodes/clause_splitter_agent.py` **normal path** (~L94–107), after
  `split_by_regex` + the existing `MAX_CLAUSES_LIMIT` clamp, gate the `refine_with_llm` call: if
  `len(regex_clauses) > CLAUSE_SPLITTER_LLM_MAX_CLAUSES` → `refined = regex_clauses` (`llm_used =
  False`), else refine as today. The short-text path (~L88) is left refining (single clause ≤
  threshold). Add a module-level alias (`CLAUSE_SPLITTER_LLM_MAX_CLAUSES = _config.…`) like the
  others so tests can monkeypatch.
- **Node B:** no logic change — `self_rag_validation_agent` already reads `SELF_RAG_MAX_ATTEMPTS`;
  only the default flips. Confirm `_issup_loop` at `range(1, MAX+1)` handles 1 (it does).
- **Tests (§7 / D6):** new clause-splitter test for the gated path (set a low
  `CLAUSE_SPLITTER_LLM_MAX_CLAUSES` so a multi-clause doc exceeds it → spy `refine_with_llm` not
  called; regex output; `llm_used False`); existing LLM-path tests keep running below the default
  threshold (unchanged), plus one asserting refinement still runs at/under the threshold; add a
  Self-RAG single-attempt test; pin existing Self-RAG retry tests to `SELF_RAG_MAX_ATTEMPTS=3`. A
  config test asserting the intended defaults. Then whole-suite green.
- **Live before/after** `node_timings` for AC-8 (real Ollama).
