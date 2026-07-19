# Feature 028 — Tasks: Determinism and variance

TDD order (§7): write/adjust failing tests → implement → green → measure. Each task lists its
acceptance link. File scope limited to plan §0 (Part A: the five `app/` files + their tests; Part B:
`eval/harness/{config,variance,variance_stats}.py` + `test_eval_variance_stats.py`). No graph/edge/
`ContractState`/migration change.

Branch: `feature/028-determinism-variance` (constitution §11).

---

## Part A — Determinism (runtime)

## T1 — Config: add `OLLAMA_TEMPERATURE` + `OLLAMA_SEED` (plan §1, D1/D7)
- [ ] In `app/config.py`, right after `OLLAMA_MODEL_NAME` (`:28`), add
      `OLLAMA_TEMPERATURE: float = 0.0` and `OLLAMA_SEED: Optional[int] = 42` with the doc-comments
      from plan §1. (`Optional` already imported at `config.py:12`.)
- **AC:** AC-1.

## T2 — Config test (TDD-first) (AC-1)
- [ ] In `tests/unit/test_config.py` assert `OLLAMA_TEMPERATURE == 0.0` and `isinstance(..., float)`,
      and `OLLAMA_SEED == 42` and `isinstance(..., int)`.
- [ ] Run → passes once T1 is in (config-only, no node dependency).
- **AC:** AC-1.

## T3 — Part A failing tests first: per-node `options` spies (§7 TDD, AC-2/3/4)
For EACH of the four node test modules, following that file's existing Ollama-mock pattern, spy on
the `chat` call (patch `ollama.Client` / capture the `options` kwarg passed by `_call_ollama`):
- [ ] `tests/unit/test_llm_refiner.py` — options carry `temperature == OLLAMA_TEMPERATURE` **and**
      preserve `num_predict == 4096`.
- [ ] `tests/unit/test_self_rag_reflectors.py` — same, `num_predict == 256`.
- [ ] `tests/unit/test_risk_scorer.py` — same, `num_predict == 384`.
- [ ] `tests/unit/test_redline_drafter.py` — same, `num_predict == 1536`.
- [ ] **AC-3** in each: with node-module `OLLAMA_SEED` an int → `options["seed"] == OLLAMA_SEED`;
      monkeypatch node-module `OLLAMA_SEED = None` → `"seed" not in options` (key absent, not `None`).
- [ ] **AC-4** in each (reversibility): monkeypatch node-module `OLLAMA_TEMPERATURE = 0.8`,
      `OLLAMA_SEED = None` → `options["temperature"] == 0.8` and no `seed` key (`num_predict` still
      present).
- [ ] Run → these FAIL against current nodes (no temperature/seed yet). Confirm red.
- **AC:** AC-2, AC-3, AC-4.

## T4 — Part A implement: aliases + options merge in the four nodes (plan §2a/§2b)
For EACH of `splitters/llm_refiner.py`, `validators/reflectors.py`, `scorers/risk_scorer.py`,
`drafters/redline_drafter.py`:
- [ ] Add `import app.config as _config` + module-level aliases
      `OLLAMA_TEMPERATURE = _config.OLLAMA_TEMPERATURE` and `OLLAMA_SEED = _config.OLLAMA_SEED`
      (read by bare name — 027 pattern at `app/graph/nodes/self_rag_validation_agent.py:32,44-51`).
- [ ] Replace `options={"num_predict": N}` (llm_refiner `:109`/4096, reflectors `:187`/256,
      risk_scorer `:151`/384, redline_drafter `:161`/1536) with the merge:
      `{"num_predict": N, "temperature": OLLAMA_TEMPERATURE, **({"seed": OLLAMA_SEED} if OLLAMA_SEED is not None else {})}`.
      Leave `model`, `messages`, `format="json"`, `think=False` unchanged.
- [ ] Do NOT touch `retrievers/embeddings.py` (no sampling options; BGE-M3, §8).
- [ ] Run T3 → green.
- **AC:** AC-2, AC-3, AC-4.

## T5 — Part A grep guard (AC-2)
- [ ] Add/confirm a test or documented grep that exactly **four** `client.chat(` generative sites
      exist (the four nodes) and `retrievers/embeddings.py` uses `client.embeddings(` with no sampling
      options (unchanged).
- **AC:** AC-2.

---

## Part B — Variance harness (offline tooling)

## T6 — Part B config: add `EVAL_VARIANCE_RUNS` (plan §3a)
- [ ] In `eval/harness/config.py`, next to `EVAL_MATCH_MIN_OVERLAP` (`:8`), add
      `EVAL_VARIANCE_RUNS: int = 5` with the doc-comment (plan §3a).
- **AC:** AC-8.

## T7 — Part B failing tests first: pure aggregation core (§7 TDD, AC-6/7/8/9)
Create `tests/unit/test_eval_variance_stats.py` (pure, synthetic dicts — no Ollama/network/fs):
- [ ] **AC-6** `summarize` / `aggregate_metrics` on a hand-worked N-run fixture → correct
      mean/std/min/max; `cv` = N/A when mean 0; `None` leaves ignored.
- [ ] **AC-7** `flip_stats` on synthetic per-run caught maps incl. a clause caught in some runs &
      missed in others → correct caught-fraction + `stable_caught`/`stable_missed`/`unstable`/`total`.
- [ ] **AC-8** N=1 (std 0, cv 0, all stable) and N=0 / empty inputs → "insufficient runs", no
      div-by-zero. `verdict_stability` on synthetic maps → correct identical-across-N fraction.
- [ ] **AC-9** `aggregate_metrics` returns a `variance.json`-shaped dict and a summary string builder
      yields non-empty `mean ± std (min–max, CV=…)` text — from fixture `metrics.json` dicts only.
- [ ] Run → FAIL (module not yet implemented). Confirm red.
- **AC:** AC-6, AC-7, AC-8, AC-9.

## T8 — Part B implement: `eval/harness/variance_stats.py` (plan §3b)
- [ ] Implement pure `summarize`, `aggregate_metrics`, `flip_stats`, `verdict_stability` per plan §3b
      signatures (population std; `cv=None` when mean 0 or n<2; None-leaf handling; N∈{0,1}).
- [ ] Run T7 → green.
- **AC:** AC-6, AC-7, AC-8, AC-9.

## T9 — Part B driver: `eval/harness/variance.py` (plan §3c) — smoke-only, not in pytest suite
- [ ] N-loop over `run.run(gold, runs)` + `score.score_run(run_dir)` collecting N `metrics` dicts
      (resumable/skip like 026's run).
- [ ] Per run build the **flip map** from `matcher.match(report["findings"], gold_clauses)` and the
      **verdict map** by joining `risk_level`/`clause_id` from the report `findings` to `final_status`
      from `sidecar.json` **by `clause_id`** (NOT `risk_level` from the sidecar — it has no such key;
      plan §3c step 2 / reviewer fix). Reuse the same `MatchResult.matches` pairs.
- [ ] Call `variance_stats.*`; write `variance.json`; print the `mean ± std (min–max, CV=…)` +
      stable/unstable summary with the 026 honesty caveat and N<3 note.
- [ ] `--vary-seed` flag: patch the four node modules' bound `OLLAMA_SEED = None` **and**
      `OLLAMA_TEMPERATURE = 0.8` before running (import-bound patch, like `run.py`'s `_dstep`), so mode
      (b) measures true model wobble; default (no flag) = mode (a) residual at temp 0 + fixed seed.
- [ ] Exercised by the AC-12 live smoke only — NOT imported by the runtime pytest suite.
- **AC:** AC-12 (live).

---

## T10 — Full backend suite green + boundary/grep guard (AC-5, AC-10)
- [ ] `python -m pytest` (from `backend/`) — whole suite green.
- [ ] `git diff --name-only` shows only: `app/config.py`, the four node files
      (`splitters/llm_refiner.py`, `validators/reflectors.py`, `scorers/risk_scorer.py`,
      `drafters/redline_drafter.py`), `tests/unit/test_config.py` + the four per-node test files,
      and Part B: `eval/harness/config.py`, `eval/harness/variance.py`,
      `eval/harness/variance_stats.py`, `tests/unit/test_eval_variance_stats.py`.
- [ ] Grep guard: nothing under `app/` imports `eval/`; no graph/`ContractState` change
      (no `app/graph/**` state/edge diff).
- **AC:** AC-5, AC-10.

## T11 — Live measurement (manual, live Ollama, `python -X utf8`) (AC-11, AC-12)
Run from `backend/`, delivery off (inherited from `run.py`), UTF-8 mode (027 harness gotcha — the ✓
print crashes cp1252).
- [x] **AC-11 before/after:** demonstrated via the temp=0 (after) vs `--vary-seed` sampling (before)
      contrast — temp=0 halves precision/recall/F1 CV and cuts within-one CV ~10×. See table below.
      (Used the variance driver's two modes rather than a literal main-vs-branch checkout diff.)
- [x] **AC-12 sweep:** `python -X utf8 -m eval.harness.variance --runs 3` → coherent
      `mean ± std (min–max, CV)` + stable/unstable summary with plausible seed-set numbers. ✅
- [x] Recorded in the "Measured result" section below.
- **AC:** AC-12 ✅; AC-11 partial (after-only; before-contrast optional).

## T12 — Wrap up
- [x] Commit on `feature/028-determinism-variance` (Part A 679ace6c, Part B 368fca97).
- [x] Update memory (feature 028 status).

---

## Measured result (AC-12) — variance sweep, N=3, shipped config (temp=0, seed=42), qwen3:8b

Ran `python -X utf8 -m eval.harness.variance --runs 3` over the seed gold corpus (heavy_contract +
sample_balanced; 11 should_flag clauses). Report: `eval/runs/variance/20260720-000808/variance.json`.

| metric | mean ± std (min–max) | CV |
| --- | --- | --- |
| precision | 91.4% ± 0.4% (90.9–91.7%) | **0.4%** |
| recall | 97.0% ± 4.3% (90.9–100.0%) | 4.4% |
| F1 | 94.1% ± 2.2% (90.9–95.7%) | 2.4% |
| miss rate | 3.0% ± 4.3% (0.0–9.1%) | 141% (tiny mean → CV inflated) |
| false-flag | 33.3% ± 0.0% (33.3–33.3%) | **0.0%** |
| severity exact | 50.0% ± 3.7% (45.5–54.5%) | 7.4% |
| severity within-one | 90.6% ± 0.4% (90.0–90.9%) | 0.5% |

Stability: **10/11 risky gold clauses stable-caught, 0 stable-missed, 1 unstable** (`heavy_contract#4`,
caught 2/3 runs). Verdict-stability **83.3% (10/12)**.

**Read (honest):** at the shipped temp=0 + fixed seed the pipeline is *near*-deterministic, not
bit-exact — **precision and false-flag are flat (CV 0.4% / 0.0%)** and severity within-one barely
moves, but **one risky clause (`heavy_contract#4`) flips caught↔missed across runs**, driving all of
the recall/miss variance (recall CV 4.4%). That single clause routes through the CRAG **web-fallback**
(DDGS results shift run-to-run, EC-2) and/or sits at a GPU-float decision margin (EC-1) — residual no
seed can remove (D4). This **measures** 027's asserted "±2-clause noise" as a concrete CV and confirms
Part A collapses the *sampling* component (the stable-clause CVs are ~0) while Part B surfaces the
irreducible residual. `false_flag_rate` CV=0 is the governing-law/confidentiality FF from 027 (D3),
now shown deterministic.

### AC-11 before/after contrast — deterministic (temp=0) vs sampled (`--vary-seed`, temp=0.8), both N=3

| metric | temp=0 CV | sampled CV |
| --- | --- | --- |
| precision | **0.4%** | 0.9% |
| recall | **4.4%** | 9.8% |
| F1 | **2.4%** | 5.3% |
| severity within-one | **0.5%** | 5.2% |
| severity exact | 7.4% | 9.1% |
| false-flag | 0.0% | 0.0% (deterministic clause-typing FF, 027 D3) |

Stability: temp=0 → 10/11 stable-caught, 1 unstable, verdict-stability 83.3%. Sampled → 9/11, **2
unstable**, verdict-stability **75.0%**. **Read:** temp=0 roughly halves precision/recall/F1 CV and
cuts within-one CV ~10×, and holds one more clause stable — Part A's determinism materially reduces
variance vs sampling. Residual under temp=0 (recall CV 4.4%) is the web-fallback/GPU-margin floor no
seed removes (EC-1/EC-2). Tiny corpus (11 clauses, N=3): direction + rough magnitude, not a tight
bound. Sampled report: `eval/runs/variance_sampled/<ts>/variance.json`.

---

### Notes
- No graph/edge/`ContractState`/migration change (AC-5/AC-10). Delivery stays off for the harness
  (026 note; `run.py` patches `_dstep.MCP_DELIVERY_ENABLED=False`).
- Runtime generative model: qwen3 via Ollama (harness/live only; all Part-A unit tests mock the LLM
  call and assert the `options` kwarg — no Ollama needed for pytest).
- Determinism is *near*, not bit-exact (D4/EC-1): GPU-float/batching + the CRAG web-fallback (EC-2)
  leave residual variance Part B measures. AC-11 accepts "near-identical".
