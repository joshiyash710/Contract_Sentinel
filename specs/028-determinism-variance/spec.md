# Feature 028 — Determinism and variance (make the tuning loop trustworthy)

## 1. Problem statement

Feature 026 gave ContractSentinel its first end-to-end accuracy numbers and 027 tuned Self-RAG
against them — but both rest on a shaky foundation the 027 measurement note called out explicitly:
**the pipeline is not reproducible run-to-run, so a single harness run is a point estimate with an
unmeasured noise band** ("recall is ±2-clause LLM-noisy at this corpus size"). Concretely, every
generative node calls Ollama with **default sampling** — no `temperature`, no `seed`:

| Call site | node | current call |
| --- | --- | --- |
| `splitters/llm_refiner.py:107` | ClauseSplitter (refine + `clause_type`) | `chat(..., think=False, options={"num_predict": 4096})` |
| `validators/reflectors.py:185` | Self-RAG (relevance / ISREL / ISSUP) | `chat(..., think=False, options={"num_predict": 256})` |
| `scorers/risk_scorer.py:145` | RiskScore (level + rationale) | `chat(..., think=False, options={"num_predict": 384})` |
| `drafters/redline_drafter.py:159` | Redline (suggested rewrite) | `chat(..., think=False, options={"num_predict": 1536})` |

Ollama's default decoding temperature (~0.8) means each of these **samples** a token stream, so the
same contract analyzed twice can land on different clause types, different relevance/ISSUP verdicts,
different risk levels, and different rewrites. That non-determinism is the direct cause of two real
problems this feature fixes:

1. **The tuning loop can't tell signal from noise.** 027 reported "recall 63.6% → 100%", but with an
   unmeasured run-to-run variance, a reviewer can't know whether a future ±3pp move is a real
   regression or the same clause flipping caught↔missed by chance. For a data-driven tuning loop
   (026 → 027 → …) that is a foundational gap.
2. **The product itself is non-reproducible.** For a legal-risk tool, "I analyzed the same contract
   twice and got two different risk reports" is a trust defect, not a feature.

This feature has two complementary halves, matching its name:

- **Determinism (reduce variance at the source):** pin Ollama sampling — `temperature` and `seed` —
  as named `§3` config constants applied to all four generative calls, so repeated runs on the same
  input produce (near-)identical outputs.
- **Variance (measure the residual):** extend the 026 harness with a **repeat-N-runs** mode that
  reports the *distribution* of each metric (mean ± std, min/max, coefficient of variation) plus a
  per-gold-clause caught↔missed **flip rate**, so 026/027-style before/after deltas can finally be
  read against a measured noise floor.

### Position relative to the constitution

**No amendment. No graph node/edge change. No `ContractState` field change. No migration. No
frontend.** Determinism is a §3 configurable-constants change threaded into the existing generative
nodes' `options` dicts — the 7-node graph and its 2 conditional edges are untouched (§2), and it is
reversible to today's behavior (§3, D6-style). The variance harness is **offline tooling** under
`backend/eval/`, exactly like 026 — not a runtime node, not in the pytest runtime suite, and it
consumes the already-defined 009 report + 026 verdict sidecar. Per §9 (local-model latency) the
repeat-N design accounts for multi-minute local runs. Per §7 the config wiring and the pure
variance-aggregation core are TDD-unit-tested; per §1/§11 it is developed on
`feature/028-determinism-variance`. Embeddings (BGE-M3, §8) are untouched — they do no sampling and
are already deterministic.

## 2. Inputs and outputs

### 2.1 Part A — Determinism: new config (§3, `app/config.py`)
Named constants near `OLLAMA_MODEL_NAME`:
- `OLLAMA_TEMPERATURE: float` — **default `0.0`** (greedy decode). Applied to every generative
  `chat()` call. `0.0` removes sampling variance; raise (e.g. `0.8`) to restore today's behavior
  (reversibility).
- `OLLAMA_SEED: Optional[int]` — **default a fixed int (e.g. `42`)**. Passed to Ollama so that any
  residual sampling (temperature > 0) is reproducible; at `temperature = 0.0` it is belt-and-braces.
  `None` ⇒ omit the key (Ollama picks a random seed) — the "let it vary" escape hatch the variance
  harness uses.

These are threaded into each generative node's existing `options` dict (merged with `num_predict`,
not replacing it): `options={"num_predict": N, "temperature": OLLAMA_TEMPERATURE, "seed": OLLAMA_SEED}`
(the `seed` key omitted when `OLLAMA_SEED is None`). The four call sites in the table above are the
complete set; `retrievers/embeddings.py` (BGE-M3) is **not** touched (embeddings are deterministic
and take no sampling options).

### 2.2 Part A — Observable output (against 001 state)
**No new `ContractState` field and no field-shape change.** The only observable change is
*stability*: for a fixed input document, repeated runs converge on the same values for the
generative-node-populated slice of `clauses[clause_id]` in
`001-contract-state-schema.md §3` — specifically `clause_type`, `relevance_verdict`,
`isrel_verdict`, `issup_verdict`, `final_status`, `risk_level`, `risk_rationale`, and
`suggested_rewrite`. (The embedding-derived `confidence_score` / `path_taken` were already
deterministic modulo the live web fallback — see EC-2/EC-4.) Downstream reducers, routing, and the
009 report are unchanged in shape.

### 2.3 Part B — Variance harness (offline, extends 026)
A repeat-runs driver under `backend/eval/harness/` (e.g. `variance.py` + a pure aggregation core in
`variance_stats.py`), reusing 026 verbatim:
- **Input:** the 026 `backend/eval/gold/` corpus and the existing 026 `run` + `score` phases
  (delivery disabled via `MCP_DELIVERY_ENABLED=False`, per 026 D8).
- **Driver (needs live Ollama):** execute the 026 `run`+`score` cycle **N times** over the same gold
  corpus (N = `EVAL_VARIANCE_RUNS`, §3 eval config), each into its own `runs/<timestamp-i>/`
  directory, producing N per-run `metrics.json` files. Idempotent/resumable like 026's run phase
  (skip completed run indices). The driver measures two distinct things via a documented flag:
  (a) **residual determinism** — run N times at the shipped `temperature = 0` + fixed seed to see how
  reproducible the *pinned* pipeline actually is (the residual is GPU-float/web-fallback, per D4);
  (b) **true model wobble** — set `OLLAMA_SEED = None` **and raise `OLLAMA_TEMPERATURE` above 0** so
  the model actually samples, to characterize the sampling variance the pinning removes. Note: a
  `seed=None` sweep left at `temperature = 0` measures near-nothing (greedy is still greedy), so mode
  (b) must raise temperature — the flag controls both together.
- **Aggregation (pure, offline, no Ollama — the §7 TDD core):** given the N `metrics.json` files,
  compute per-metric **mean, standard deviation, min, max, and coefficient of variation (std/mean)**
  for every 026 metric (precision, recall, F1, miss rate, false-flag rate, severity exact +
  within-one accuracy), plus:
  - **Per-gold-clause flip rate:** across the N runs, the fraction of runs in which each
    `should_flag:true` gold clause was caught; a clause caught in some runs and missed in others is
    an *unstable* clause. Summary: count of stable-caught / stable-missed / unstable clauses.
  - **Verdict stability:** for matched clauses, the fraction whose `final_status` (and `risk_level`)
    is identical across all N runs (uses the 026 verdict sidecar).
  - Emit `variance.json` + a printed human-readable summary reporting each headline metric as
    `mean ± std (min–max, CV=…)` and the stable/unstable clause counts.

## 3. Resolved decisions (inline)

- **D1 — Ship `temperature = 0.0` as the runtime default (product-wide), not eval-only.** Determinism
  is a *product* property for a legal tool ("same contract → same report"), and it is what makes the
  026/027 tuning loop trustworthy. Greedy decode is the standard, usually *better*, choice for the
  structured-JSON extraction/classification these calls already do (`format="json"`, `think=False`);
  no quality regression is expected, and 026 (re-run per D5) measures it directly. Reversible to
  today by setting `OLLAMA_TEMPERATURE = 0.8`. *(This is the D1 the user should confirm — see Open
  Question 1.)*
- **D2 — Single global sampling config, not per-node.** One `OLLAMA_TEMPERATURE` / `OLLAMA_SEED`
  pair governs all four generative calls. Per-node temperature tuning is a speculative complication
  with no evidence it's needed; if a future node wants divergence, that's a separate change. Keeps
  §3 to two constants.
- **D3 — `temperature` + `seed` only; not `top_p`/`top_k`/`repeat_penalty`.** At `temperature = 0.0`
  decoding is greedy and the sampling-shape knobs are moot; adding them is noise. If the runtime
  default is ever raised above 0, revisit.
- **D4 — Determinism is "near", not absolute — and we say so.** Even at `temperature = 0` + fixed
  seed, GPU floating-point non-associativity and llama.cpp/Ollama batching can flip a low-margin
  token, and the live web fallback (EC-2) is inherently non-reproducible. So Part A *reduces* variance
  sharply but does not promise bit-identity; **Part B exists precisely to measure the residual.** The
  honest framing is carried in the variance summary output.
- **D5 — Re-run the 026 harness before/after Part A.** The determinism change is a config tune whose
  accuracy effect must be measured, not assumed — same discipline as 027 (AC-7). Expectation: recall/
  precision land within the variance band of the pre-change numbers (determinism should not *move* the
  metric, only *stabilize* it), and CV drops toward ~0.
- **D6 — Part B reuses 026 verbatim; it is not a reimplementation.** The variance driver calls the
  existing 026 `run`/`score`; the only new code is the N-times orchestration and the pure
  cross-run aggregation. Config lives in the 026 eval config module (`backend/eval/harness/config.py`,
  026 D7), not the runtime `app/config.py`, for `EVAL_VARIANCE_RUNS`.
- **D7 — `OLLAMA_SEED` default is a fixed int, overridable to `None`.** A pinned seed maximizes
  reproducibility of the tuning loop (the common case); the variance driver flips it to `None` to
  sample the model's true wobble. Both are the same tool, different flag.
- **D8 — Both halves ship together (the feature name is "determinism AND variance").** Determinism
  without a variance measurement can't prove it worked; a variance harness without determinism just
  reports a large, unfixable noise floor. They are complementary and each is small (Part A: 2 config
  constants + 4 one-line `options` merges; Part B: an N-loop + a pure stats aggregator over 026's
  existing `metrics.json`).

## 4. Acceptance criteria

### Part A — Determinism (backend pytest, no Ollama)
- **AC-1:** `OLLAMA_TEMPERATURE` (float) and `OLLAMA_SEED` (`Optional[int]`) exist in `app/config.py`
  with the D1/D7 defaults; a `test_config` assertion checks their types and that
  `OLLAMA_TEMPERATURE == 0.0` by default.
- **AC-2:** Each of the four generative call sites passes `temperature = OLLAMA_TEMPERATURE` in its
  `options` dict while preserving its existing `num_predict` value (mock/spy the `ollama.Client.chat`
  call and assert the `options` argument). No fifth generative call site exists (grep guard); the
  embedding call in `retrievers/embeddings.py` is unchanged (takes no sampling options).
- **AC-3:** When `OLLAMA_SEED` is an int, `seed` is present in `options` with that value; when
  `OLLAMA_SEED is None`, the `seed` key is **absent** from `options` (not `seed: None`) — verified per
  call site via the spy.
- **AC-4 (reversibility):** With `OLLAMA_TEMPERATURE` monkeypatched to `0.8` and `OLLAMA_SEED` to
  `None`, the `options` dict passed to `chat` contains `temperature: 0.8` and no `seed` key —
  restoring today's default-sampling behavior (the only always-present addition being `num_predict`,
  which is unchanged from today).
- **AC-5:** No graph/edge/`ContractState`/migration change — `git diff` touches only `app/config.py`,
  the four generative node modules, and their tests (plus the Part B eval files). Whole `pytest`
  green.

### Part B — Variance harness (pytest, deterministic, no Ollama)
- **AC-6:** Given synthetic fixtures of N per-run `metrics.json` dicts, the aggregation core computes
  correct **mean, std, min, max, and coefficient of variation** for each metric (verified on a
  hand-worked example), and reports `CV` as N/A (no div-by-zero) when the mean is 0.
- **AC-7:** Given N synthetic per-run match results, the **per-gold-clause flip rate** and
  stable-caught / stable-missed / **unstable** clause counts are computed correctly, including a
  clause caught in some runs and missed in others (the unstable case).
- **AC-8:** `EVAL_VARIANCE_RUNS` is a named constant in the 026 eval config module (§3 / 026 D7); the
  aggregator handles `N = 1` (std = 0, CV = 0) and `N = 0` / empty inputs with well-defined output
  (reports "insufficient runs", no crash).
- **AC-9:** The variance aggregation runs with **no Ollama and no network** against cached fixture
  `metrics.json` files, emits a `variance.json`, and prints a non-empty summary formatted as
  `mean ± std (min–max, CV=…)` per headline metric.
- **AC-10:** The variance harness is **not** imported by the runtime app or the pytest runtime suite
  (grep guard: nothing under `app/` imports `eval/`).

### Live (real backend)
- **AC-11 (smoke, manual, D5):** Run the 026 harness on the seed corpus **before** the determinism
  change **twice** (two `run`+`score` cycles) and confirm the metrics differ across the two runs
  (demonstrating the problem). Apply Part A, run **twice more**, and confirm the two post-change runs
  produce **identical or near-identical** metrics (demonstrating the fix). Record both.
- **AC-12 (smoke, manual):** The Part B variance driver executes `EVAL_VARIANCE_RUNS` full harness
  cycles over the seed corpus (live Ollama, delivery stubbed) and its aggregator prints a coherent
  variance summary (per-metric mean ± std/CV + stable/unstable clause counts) with plausible numbers.

## 5. Edge cases
- **EC-1 — Residual non-determinism at `temperature = 0`.** GPU float non-associativity / batching can
  still flip a low-margin token → the two post-change runs in AC-11 may be *near*-identical, not
  bit-identical. This is expected (D4); AC-11 accepts "identical or near-identical" and Part B
  quantifies the residual.
- **EC-2 — Live web fallback (CRAG `web_fallback` path) is inherently non-reproducible.** DuckDuckGo
  results change over time/order, so clauses routed to the web path (score < 0.73) carry variance no
  LLM seed can remove. Documented limitation; a frozen-KB / recorded-web-response snapshot is a
  separate concern (§6). The local FAISS KB path is deterministic.
- **EC-3 — Concurrency ordering (Self-RAG `ThreadPoolExecutor` in `reflectors.py`).** Per-clause
  results are keyed by `clause_id` and merged by reducer, so completion *order* does not change final
  state *values*; concurrency affects timing, not determinism of results. No change needed; noted so
  it is not mistaken for a variance source.
- **EC-4 — Circuit-breaker / timeout fail-open paths.** These are triggered by wall-clock timeouts and
  consecutive-failure counts (§ CRAG/Self-RAG breakers), which are latency-dependent, not sampling-
  dependent; under load a run could fail-open where a faster run didn't. This is a *latency*-driven
  variance source, out of Part A's scope (temperature can't fix it) but *visible* in Part B's metric
  spread. Documented.
- **EC-5 — `OLLAMA_SEED = None` in the runtime default.** If a user sets seed to `None` at
  `temperature = 0`, decoding is still greedy so output stays stable; the `seed` key is simply omitted
  (AC-3). No error.
- **EC-6 — 025-gated large docs (regex-only, `clause_type = None`).** The LLM refinement is skipped
  (`CLAUSE_SPLITTER_LLM_MAX_CLAUSES`), so those clauses have fewer generative calls to stabilize; their
  determinism comes for free (regex is deterministic). Consistent with 027 D5. Tie-in:
  [[project_feature025_paused]].
- **EC-7 — Part B with `EVAL_VARIANCE_RUNS = 1`.** Degenerate: std = 0, CV = 0, every clause
  trivially "stable"; the summary notes a single run cannot measure variance (AC-8). N ≥ 3 recommended
  in the summary framing.

## 6. Out of scope
- **Eliminating GPU/float and web-fallback non-determinism** (EC-1, EC-2) — Part A targets LLM
  *sampling*; bit-exact reproducibility across hardware, and a frozen web-response snapshot for the
  CRAG fallback, are separate efforts (the latter would belong to a 005-CRAG follow-up).
- **Per-node temperature tuning** (D2) and **`top_p`/`top_k`/`repeat_penalty` config** (D3) — not until
  evidence demands them.
- **CI variance gating / statistical-significance tests / regression thresholds** — Part B *reports*
  the distribution; wiring it into an automated pass/fail gate is future work (mirrors 026 §6).
- **Growing the gold corpus / lawyer review** — belongs to 026's data effort; Part B's numbers are
  only as meaningful as that corpus (026 D5 honesty caveat carries).
- **Any runtime graph / `ContractState` / API / frontend / migration change** — none.

## 7. Evaluation (metrics this feature exists to log)
Because this feature measures the stability of the CRAG/Self-RAG/risk-scoring outputs, its Part B
harness logs, per corpus and across `EVAL_VARIANCE_RUNS` repeated runs, the **distribution** of every
026 metric — **precision, recall, F1, miss rate, false-flag rate, severity exact + within-one
accuracy** — as **mean, std, min, max, and coefficient of variation**, plus the **per-gold-clause
caught↔missed flip rate** (stable-caught / stable-missed / unstable counts) and the **Self-RAG
`final_status` / `risk_level` verdict-stability rate** over matched clauses. These are written to
`variance.json` per variance sweep so a before/after determinism comparison (AC-11, D5) can show the
**CV collapsing toward ~0** once `temperature = 0` + fixed seed is applied, and so future 026/027-style
tuning deltas can be judged against the measured noise floor (a change smaller than the residual band
is noise, not signal). **Honesty caveat (carried in the summary output):** the residual band and all
rates are only as meaningful as the seed corpus's size/quality (026 D5), and Part A reduces but does
not eliminate non-determinism (D4, EC-1/EC-2/EC-4).

## 8. Notes for plan.md / tasks.md (pointers)
- **Config (Part A):** add `OLLAMA_TEMPERATURE` (0.0) and `OLLAMA_SEED` (fixed int) near
  `OLLAMA_MODEL_NAME` in `app/config.py`; add a `test_config` type/default assertion. In each of the
  four node modules read them by bare module-level name (so tests can monkeypatch the node-module
  attr, mirroring the 027 alias pattern) and build the `options` dict as
  `{"num_predict": N, "temperature": OLLAMA_TEMPERATURE, **({"seed": OLLAMA_SEED} if OLLAMA_SEED is not None else {})}`.
- **Node call sites (Part A):** `splitters/llm_refiner.py:107`, `validators/reflectors.py:185`,
  `scorers/risk_scorer.py:145`, `drafters/redline_drafter.py:159`. Do **not** touch
  `retrievers/embeddings.py`.
- **Tests (Part A):** spy on `ollama.Client.chat` per node (or its module-level `_call_ollama`
  helper) and assert the `options` dict carries `temperature`/`seed` per AC-2/AC-3/AC-4; preserve
  existing `num_predict` assertions. TDD failing-first.
- **Harness (Part B):** `backend/eval/harness/variance.py` (N-loop driver over 026 `run`+`score`;
  optional `--vary-seed` flag setting `OLLAMA_SEED=None`) + `variance_stats.py` (pure aggregation).
  Add `EVAL_VARIANCE_RUNS` to `backend/eval/harness/config.py` (026 D7). `runs/` cache stays
  gitignored (026 §8). Unit test the aggregator: `backend/tests/unit/test_eval_variance_stats.py`
  (synthetic N `metrics.json` dicts — pure, deterministic; AC-6..9). The live driver is exercised by
  the AC-12 smoke, not the runtime suite.
- **Measurement (D5):** re-run the 026 harness before/after Part A (AC-11) and run the Part B sweep
  (AC-12); record CV before vs. after.

## 9. Open questions (all RESOLVED 2026-07-19)
- **OQ-1 (significant) — Ship `temperature = 0.0` as the *product-wide* runtime default, or apply
  deterministic settings only inside the eval harness?** **RESOLVED — product-wide** (per D1). Same
  contract → same report is a trust property for a legal tool, greedy decode is the standard choice
  for these structured-JSON calls (no quality loss expected; 026 re-run measures it), and it fixes the
  tuning-loop noise. `OLLAMA_TEMPERATURE = 0.0` is the shipped runtime default for all four generative
  calls; reversible to `0.8`.
- **OQ-2 — Both halves ship together (D8)?** **RESOLVED — yes**, both Part A (determinism) and Part B
  (variance harness) ship in this feature.
- **OQ-3 — Default `EVAL_VARIANCE_RUNS` (N)?** **RESOLVED — N = 5** (recommended default), a
  configurable eval constant, documented as indicative with the summary recommending N ≥ 3.
- **OQ-4 — Default `OLLAMA_SEED`?** **RESOLVED — a fixed int (`42`)** for reproducibility; the
  variance driver flips it to `None` (with raised temperature) to probe true model wobble (§2.3).
