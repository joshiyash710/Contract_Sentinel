# Feature 028 — Technical plan: Determinism and variance

Derived from `spec.md`. Two halves: **Part A** pins Ollama sampling (`temperature`/`seed`) as §3
config threaded into the four existing generative `chat()` calls — **no graph/edge/`ContractState`/
migration change** (constitution §2). **Part B** extends the 026 harness with an offline repeat-N
variance driver + a pure aggregation core under `backend/eval/` — offline tooling, not a runtime node,
not in the pytest runtime suite.

Branch (constitution §11): `feature/028-determinism-variance`.

## 0. Scope of change (files touched)

**Part A — runtime (AC-5 grep guard: the ONLY files under `app/` are these five):**
1. `backend/app/config.py` — add `OLLAMA_TEMPERATURE` (0.0) and `OLLAMA_SEED` (42).
2. `backend/app/graph/nodes/splitters/llm_refiner.py` — config aliases + options-dict merge.
3. `backend/app/graph/nodes/validators/reflectors.py` — same.
4. `backend/app/graph/nodes/scorers/risk_scorer.py` — same.
5. `backend/app/graph/nodes/drafters/redline_drafter.py` — same.

**Part A — tests:**
6. `backend/tests/unit/test_config.py` — `OLLAMA_TEMPERATURE`/`OLLAMA_SEED` type + default asserts.
7. Per-node unit tests (spy the `chat` `options` arg): the existing test module for each of the four
   nodes (e.g. `tests/unit/test_self_rag_reflectors.py`, `test_risk_scorer.py`, `test_llm_refiner.py`
   / `test_clause_splitter*`, `test_redline_drafter.py` — confirm exact filenames in tasks.md).

**Part B — offline tooling (under `backend/eval/`; nothing under `app/`, not in runtime suite):**
8. `backend/eval/harness/config.py` — add `EVAL_VARIANCE_RUNS` (5).
9. `backend/eval/harness/variance.py` — NEW: repeat-N driver (live) reusing 026 `run`/`score`.
10. `backend/eval/harness/variance_stats.py` — NEW: pure cross-run aggregation (the §7 TDD core).
11. `backend/tests/unit/test_eval_variance_stats.py` — NEW: pure fixture-driven tests (AC-6..9).

The 026 harness files (`run.py`, `score.py`, `matcher.py`, `scorer.py`, `schema.py`) are **imported/
reused, not modified** (spec D6). In particular `schema.py`/`build_sidecar` is NOT extended: the
verdict-stability metric sources `risk_level` from the report `findings`, not the sidecar (§3c step 2),
precisely so the sidecar schema stays untouched.

---

## 1. Part A — Config change (`app/config.py`)

Immediately after `OLLAMA_MODEL_NAME` (currently `config.py:28`) add:

```python
OLLAMA_TEMPERATURE: float = 0.0
# Sampling temperature for ALL generative Ollama chat() calls (the 4 nodes: clause-splitter
# refine, Self-RAG reflectors, risk scorer, redline drafter). 0.0 = greedy decode → repeated
# runs on the same input converge on the same output, which (a) makes the same contract yield
# the same report — a trust property for a legal tool — and (b) removes the run-to-run noise
# that made the 026/027 tuning loop hard to read (spec 028 §1, D1). Standard choice for the
# structured-JSON (format="json") calls these already are. Raise to 0.8 to restore pre-028
# default-sampling behavior (reversible). Does NOT eliminate GPU-float / web-fallback residual
# non-determinism — spec 028 Part B measures that (D4).

OLLAMA_SEED: Optional[int] = 42
# Fixed RNG seed passed to every generative chat() call, for reproducibility of any residual
# sampling (belt-and-braces at temperature 0). None ⇒ the "seed" key is OMITTED (Ollama picks a
# random seed) — the escape hatch the 028 variance driver uses (with a raised temperature) to
# probe true model wobble (spec 028 §2.3). Type is Optional[int]; `Optional` is already imported
# in config.py.
```

`Optional` is already imported (`config.py:12`). These sit in the "ClauseSplitter thresholds" block
next to `OLLAMA_MODEL_NAME`, which all four generative nodes already share.

## 2. Part A — Node changes (the four `chat()` call sites)

Each of the four files holds a `client.chat(model=…, messages=…, format="json", think=False,
options={"num_predict": N})`. The current confirmed forms:

| File | call fn | line (options) | `num_predict` |
| --- | --- | --- | --- |
| `splitters/llm_refiner.py` | `_call_ollama` (`:83`) | `:109` | 4096 |
| `validators/reflectors.py` | `_call_ollama` (`:178`) | `:187` | 256 |
| `scorers/risk_scorer.py` | `_call_ollama` (`:140`) | `:151` | 384 |
| `drafters/redline_drafter.py` | `_call_ollama` (`:150`) | `:161` | 1536 |

None of these four files currently imports config (the `model_name`/`timeout_seconds` are threaded
in as params). For each file apply the **same two edits** (mirrors the 027 monkeypatchable-alias
pattern, `app/graph/nodes/self_rag_validation_agent.py:32,44-51`):

### 2a. Add config import + module-level aliases (top of file, after existing imports)
```python
import app.config as _config

# Read by bare name below — never via _config.NAME — so tests monkeypatch the node-module attr.
OLLAMA_TEMPERATURE = _config.OLLAMA_TEMPERATURE
OLLAMA_SEED = _config.OLLAMA_SEED
```

### 2b. Merge temperature/seed into the existing `options` dict
Replace `options={"num_predict": N}` with (N = that file's existing value, unchanged):
```python
options={
    "num_predict": N,
    "temperature": OLLAMA_TEMPERATURE,
    **({"seed": OLLAMA_SEED} if OLLAMA_SEED is not None else {}),
},
```
This is the exact construction the spec §8 pointer prescribes: `num_predict` preserved, `temperature`
always present, `seed` key present only when `OLLAMA_SEED is not None` (AC-3). `think=False`,
`format="json"`, `model`, `messages` all unchanged. **`retrievers/embeddings.py` is NOT touched** —
`client.embeddings(...)` takes no sampling options and BGE-M3 is already deterministic (§8, AC-2).

The 4× repetition of the one-line merge (each with a different `num_predict`) is deliberate: it
matches the codebase's existing "each node owns its own `_call_ollama`" idiom and the spec's §8
per-node prescription, and keeps the diff to the five files AC-5 names (no new shared module).

## 3. Part B — Variance harness

### 3a. Config (`eval/harness/config.py`)
Append (next to `EVAL_MATCH_MIN_OVERLAP`):
```python
EVAL_VARIANCE_RUNS: int = 5
# Number of full harness (run+score) cycles the 028 variance driver executes over the gold corpus
# to measure metric variance. N≥3 recommended in the summary; each cycle is multiple minutes on the
# local 8B/6GB box (spec 028 OQ-3). Indicative, not authoritative (026 corpus caveat).
```

### 3b. Pure aggregation core (`eval/harness/variance_stats.py`) — the §7 TDD unit
Pure, deterministic, no Ollama/network/filesystem. Functions:

- `summarize(values: list[float | None]) -> dict` → `{"mean","std","min","max","cv","n"}`. Ignores
  `None` leaves (026 reports N/A as `None`); population std; `cv = std/mean` or `None` when mean == 0
  or n < 2 (AC-6, AC-8). Returns an "insufficient" marker when no non-None values.
- `aggregate_metrics(metrics_list: list[dict]) -> dict` → for each headline leaf in the 026 metrics
  dict — `detection.{precision,recall,f1,miss_rate,false_flag_rate}`,
  `severity.{exact_accuracy,within_one_accuracy}` — call `summarize` over the N runs. Shape mirrors
  the input so the summary can print `metric: mean ± std (min–max, CV=…)` (AC-6, AC-9).
- `flip_stats(per_run_caught: list[dict[str, bool]]) -> dict` → input is N maps of
  `gold_clause_key → caught?` (only `should_flag:true` clauses). Output: per-clause caught-fraction,
  and counts `{"stable_caught","stable_missed","unstable","total"}` (unstable = caught in ≥1 run and
  missed in ≥1 run) (AC-7).
- `verdict_stability(per_run_verdicts: list[dict[str, tuple]]) -> dict` → input is N maps of
  `clause_key → (final_status, risk_level)` (the map is **pre-built by the driver** — see §3c step 2
  for the two sources, since `final_status` and `risk_level` do NOT live in the same artifact); output
  = fraction of clauses whose tuple is identical across all N runs (§2.3 verdict stability). Handles
  N∈{0,1} (AC-8: N=1 → all trivially stable, std 0; N=0 → "insufficient runs", no crash). This
  function is pure and source-agnostic; unit tests feed it synthetic maps.

All of the above are unit-tested with **synthetic** dicts (no live run) in
`test_eval_variance_stats.py` — this is the pytest-runtime, no-Ollama core (AC-6..9, AC-10).

### 3c. Live driver (`eval/harness/variance.py`)
Mirrors `run.py`'s structure (delivery already disabled by importing `run`, which patches
`_dstep.MCP_DELIVERY_ENABLED=False`). Behaviour:
1. `for i in range(EVAL_VARIANCE_RUNS)`: `run_dir = run.run(gold_dir, runs_root)` (fresh timestamped
   dir per iteration — resumable/skip if an index dir already scored, like 026's run); then
   `metrics = score.score_run(run_dir)`. Collect the N `metrics` dicts.
2. Per run, build the two per-clause maps the aggregators need, **without modifying 026**: reload each
   manifest entry's cached `report.json` + `sidecar.json` + `gold` (as `score_run` does) and call
   `matcher.match(report["findings"], gold_clauses)` → `MatchResult`.
   - **flip map** (`gold_clause_key → caught?`): from `MatchResult` — a `should_flag:true` gold clause
     is `caught` iff it appears in the matched pairs.
   - **verdict map** (`clause_key → (final_status, risk_level)`): scoped to **matched (caught)**
     clauses. Source the two fields from **different** artifacts (this is the reviewer-caught fix):
     `risk_level` and `clause_id` come from the matched **report `finding`** (`ReportFinding.risk_level`
     / `.clause_id`, `app/models/report.py:38,42`); `final_status` comes from the **sidecar** keyed by
     that `clause_id` (`schema.py` `SIDECAR_KEYS` has `final_status` but **NOT** `risk_level` — reading
     `risk_level` from the sidecar would yield `None` for every clause and make verdict-stability a
     degenerate always-"stable" number). Join the two by `clause_id`. Reuse the same
     `MatchResult.matches` pairs from the flip map — no second overlap pass. This keeps all 026 files
     (incl. `schema.py`/`build_sidecar`) **unmodified** (D6/AC-10).
3. Call `variance_stats.aggregate_metrics / flip_stats / verdict_stability`; write
   `variance.json` at the variance-run root and print a summary formatted as
   `mean ± std (min–max, CV=…)` per headline metric + stable/unstable clause counts, carrying the 026
   honesty caveat and a note that N<3 can't characterize variance (AC-12).
4. **`--vary-seed` flag (spec §2.3 mode b):** to measure *true model wobble* (not residual), the
   driver flips sampling ON before running by patching the four node modules' bound aliases (the same
   import-bound-patch technique `run.py` uses for `_dstep`): set
   `<node_mod>.OLLAMA_SEED = None` and `<node_mod>.OLLAMA_TEMPERATURE = <sample-temp, e.g. 0.8>` on
   each of the four node modules. Default (flag absent) = mode (a): measure residual determinism at
   the shipped `temperature = 0` + fixed seed. Documented: a `seed=None` sweep left at temperature 0
   measures near-nothing (greedy stays greedy), so mode (b) raises temperature too — the flag does
   both together.

`variance.py` is exercised only by the AC-12 live smoke, never the runtime pytest suite (AC-10).

## 4. Test plan (TDD, §7 failing-first)

### Part A (pytest, no Ollama)
- **AC-1** `test_config.py`: `OLLAMA_TEMPERATURE == 0.0` and is `float`; `OLLAMA_SEED == 42` and is
  `int` (and the type is `Optional[int]`-compatible).
- **AC-2** per node (spy `ollama.Client.chat` or the module `_call_ollama`): assert the `options`
  dict passed to `chat` contains `temperature == OLLAMA_TEMPERATURE` **and** preserves the node's
  existing `num_predict` (256/384/1536/4096 respectively). One test per node → all four sites covered.
  A grep-guard test/assert that exactly four `client.chat(` generative sites exist and
  `embeddings.py` is untouched.
- **AC-3** per node: with `OLLAMA_SEED` an int → `options["seed"] == OLLAMA_SEED`; monkeypatch the
  node-module `OLLAMA_SEED = None` → `"seed" not in options` (key absent, not `None`).
- **AC-4** per node (reversibility): monkeypatch node-module `OLLAMA_TEMPERATURE = 0.8`,
  `OLLAMA_SEED = None` → `options` has `temperature == 0.8` and no `seed` key (today's behavior,
  `num_predict` still present).

### Part B (pytest, deterministic, no Ollama) — `test_eval_variance_stats.py`
- **AC-6** `summarize`/`aggregate_metrics` on a hand-worked N-run fixture → correct mean/std/min/max;
  `cv` = N/A when mean 0; `None` leaves ignored.
- **AC-7** `flip_stats` on synthetic per-run caught maps incl. a clause caught in some runs & missed
  in others → correct caught-fraction + stable_caught/stable_missed/unstable counts.
- **AC-8** N=1 (std 0, cv 0, all stable) and N=0 / empty inputs → "insufficient runs", no div-by-zero.
- **AC-9** aggregator emits a `variance.json`-shaped dict + a non-empty summary string, computed
  purely from fixture `metrics.json` dicts (no Ollama, no network).
- **AC-10** grep guard: nothing under `app/` imports `eval/`; `variance.py`/`variance_stats.py`/
  `config.py` are the only Part-B additions; graph/`ContractState` unchanged (`git diff`).

## 5. Measurement (live, manual — AC-11, AC-12)

Run from `backend/` with live Ollama (qwen3), delivery off (inherited from `run.py`), UTF-8 mode
(`python -X utf8`, per 027 harness gotcha — the ✓ summary print crashes cp1252):
- **AC-11 (before/after determinism):** on `main` (pre-028), run 026 `run`+`score` **twice** and show
  the two `metrics.json` differ (the problem). On the branch (temp=0+seed), run **twice** and show the
  two are identical/near-identical (the fix). Record both; expect the metric *values* to land within
  the pre-028 variance band (determinism stabilizes, does not move, the numbers — D5) and CV → ~0.
- **AC-12 (variance sweep):** `python -X utf8 -m eval.harness.variance` (default N=5) → coherent
  `mean ± std (min–max, CV)` summary + stable/unstable clause counts with plausible seed-set numbers.

## 6. Risks / limitations
- **D4 / EC-1 residual non-determinism:** temp=0+seed is *near*, not bit-exact, reproducibility (GPU
  float / llama.cpp batching). AC-11 accepts "near-identical"; Part B quantifies the residual.
- **EC-2 web fallback:** clauses on the CRAG `web_fallback` path (DuckDuckGo) carry variance no seed
  removes — inherent, documented, out of scope (a frozen-web snapshot is a separate CRAG concern).
- **EC-4 latency-driven fail-opens:** timeout/circuit-breaker paths are wall-clock-driven, not
  sampling-driven — Part A can't fix them; they surface as spread in Part B. Documented.
- **Greedy-quality:** temp=0 could in theory shift a borderline verdict vs. sampled; AC-11's 026
  re-run measures accuracy so any regression is caught, not assumed.
- **Live harness needs Ollama up** (qwen3) — same constraint as 026/027; Part B multiplies runtime by
  N (OQ-3 budget).
