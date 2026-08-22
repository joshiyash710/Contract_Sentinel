# Feature 047 — Technical plan: tolerant LLM clause-grouping

Branch: `feature/047-tolerant-clause-grouping` (per constitution §11).

Derived from `spec.md`. Makes `_parse_grouping_response` apply the model's **valid partial** grouping
(merges + `clause_type`) instead of the current all-or-nothing exact-partition fallback, and raises the
grouping output-token budget. Reviving the model's `clause_type` on large docs re-arms the existing 027
recall floor. **No graph/edge/`ContractState`/migration/Self-RAG/embeddings change.**

## 0. Scope of change (files touched)

Per **AC-9** the `git diff --name-only main` must show **exactly**:
```
backend/app/config.py
backend/app/graph/nodes/splitters/llm_refiner.py
backend/tests/unit/test_llm_refiner.py
backend/tests/unit/test_config.py
specs/047-tolerant-clause-grouping/{spec,plan,tasks}.md
```
No other file — **no `self_rag_validation_agent.py`, no `embeddings.py`, no graph/edge/state/migration.**
**⚠ The local uncommitted `OLLAMA_MODEL_NAME = "qwen3:4b"` in `app/config.py` must be reverted to
`"qwen3:8b"` before committing** (it breaks 4 `test_config` model-name assertions); re-apply after merge.
The uncommitted docs edits (`docs/ACCURACY.md`, `docs/DEPLOYMENT.md`, `specs/046-.../RESULTS.md`) are NOT
part of this feature — do not stage them in 047's commits.

## 1. Config change (`app/config.py`)

Near the ClauseSplitter LLM constants (`CLAUSE_SPLITTER_LLM_EMIT_TEXT` / `_NUM_PREDICT`, ~lines 178/187):

```python
CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING: bool = True
# Feature 047. When True (default), the grouping-mode parser applies the model's VALID partial output —
# its merges + clause_type — and fills any un-referenced/out-of-range/duplicate index with a passthrough
# regex singleton, instead of discarding the whole response on a non-exact partition. Reviving the
# model's clause_type on large docs re-arms the 027 recall floor. False ⇒ byte-for-byte today's strict
# exact-partition behavior (non-partition → ValueError → regex fallback).
```
And raise the existing grouping budget:
```python
CLAUSE_SPLITTER_LLM_NUM_PREDICT: int = 4096   # was 1024 (feature 029). 047: raised so large-doc
# index-only grouping output (and, on Groq reasoning models, shared reasoning tokens) is not truncated.
```
Both are **plain module-literal constants** exactly like their siblings `CLAUSE_SPLITTER_LLM_EMIT_TEXT`
(`= False`) and the old `CLAUSE_SPLITTER_LLM_NUM_PREDICT` (`= 1024`) — those do **not** use an
`_env_bool`/`_env_int` reader today (config.py:178/187). Do NOT invent an env-reader pattern here;
overrides come via the call-time monkeypatch of the bare `llm_refiner` aliases, which is what the node
already relies on. (Correcting the spec §2.1 "env-overridable" aside: monkeypatch-overridable, not
env-read — no behavior change intended.)

## 2. Parser change (`llm_refiner.py`)

- **Flag plumbing (reviewer suggestion 2):** add ONE bare module alias next to the existing ones
  (`llm_refiner.py:26-27`) so tests monkeypatch it and it is read at call time:
  ```python
  CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING = _config.CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING
  ```
  `CLAUSE_SPLITTER_LLM_NUM_PREDICT` is **already** aliased (`:27`) — no change needed there beyond the
  raised default flowing through. **Do not add a parameter** to `_parse_grouping_response`; it reads the
  bare module flag internally (keeps the signature `(raw_content, regex_clauses)` and the monkeypatch
  pattern consistent with `CLAUSE_SPLITTER_LLM_EMIT_TEXT`).

- **Refactor `_parse_grouping_response(raw_content, regex_clauses)`** (currently `:304`):
  1. Keep the shared front matter unchanged: `json.loads` (raise→fallback on invalid JSON), require
     `data["clauses"]` is a non-empty list (raise otherwise). This preserves AC-7 for both flag values.
  2. Branch on the bare flag:
     - `if not CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING:` run the **existing strict body verbatim** (the
       `flat`/partition check at `:342` and the current assembly at `:347-373`) — AC-5/EC-4 byte-identical.
     - else run the **tolerant body** (below).
  3. Factor the per-group `ClauseBoundary` construction (section_number fallback to `segments[0]`,
     `clause_type` validated against `_VALID_CLAUSE_TYPES` → else `None`, `"\n".join` of segment text,
     sequential `position`/`clause_id`) into a small local helper reused by both paths so validation
     (AC-4) stays identical. **AC-5 byte-identity is about the strict path's *output*, not its source
     layout:** the shared helper must reproduce today's section_number fallback, `_VALID_CLAUSE_TYPES`
     gate, `"\n".join`, and sequential `clause_id`/`position` **exactly**, so the refactored strict path
     yields the same `ClauseBoundary` list as today for any given response.

- **Tolerant body algorithm** (pure; deterministic; implements spec §2.2):
  ```
  n = len(regex_clauses); by_index = {c.position: c for c in regex_clauses}
  claimed = set(); groups = []          # each: (sorted_indices, item)
  for item in data["clauses"]:
      idxs = item.get("indices")
      if not isinstance(idxs, list): continue          # skip non-list (e.g. concatenated int)
      keep = []
      for x in idxs:
          if isinstance(x, bool): continue             # bool is an int subclass — exclude
          if isinstance(x, int) and 1 <= x <= n and x not in claimed:
              claimed.add(x); keep.append(x)
      if keep: groups.append((sorted(keep), item))     # ascending within group
  # passthrough singletons for every unclaimed index
  for x in range(1, n + 1):
      if x not in claimed: groups.append(([x], None))  # None item ⇒ carry regex segment's own fields
  # document order = ascending minimum claimed index
  groups.sort(key=lambda g: g[0][0])
  # build ClauseBoundary list via the shared helper, renumbering position/clause_id 1..len
  ```
  - `item is None` (passthrough) ⇒ `section_number`/`clause_type` taken from the single regex segment
    (`by_index[x]`), exactly today's regex clause.
  - If, after filtering, `groups` is empty (can only happen when `n == 0`) fall back by raising — but
    `n == 0` never reaches here (regex always yields ≥1 clause). No fabricated clauses (AC-7 intact).
  - **Text preservation (spec §2.2):** every index `1..N` is in exactly one group (claimed-once or
    passthrough) → index coverage holds by construction.

- **`_call_ollama`** (`:192`) is unchanged except that the grouping branch already passes
  `num_predict=CLAUSE_SPLITTER_LLM_NUM_PREDICT` (`:220`) — the raised default flows through automatically
  (AC-8). No edit to the `.chat(...)` call.

## 3. Test plan (TDD, `tests/unit/test_llm_refiner.py`)
Failing-first per §7. Parser tests call `_parse_grouping_response` **directly** (pure — no client); the
one budget test mocks the client. Monkeypatch `llm_refiner.CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING` per case.
Build `regex_clauses` as real `ClauseBoundary` objects with `position=1..N` and **distinct single-line
`text`** (so AC-6's `\n`-split round-trip is exact).

- **AC-1 (partial → fill gaps):** N=6; response groups `[1,2]`(liability) + `[3]`(confidentiality),
  omits 4/5/6. Flag True → **exactly 4** clauses in order: merged[1,2] (type `liability`), [3]
  (`confidentiality`), singleton 4, 5, 6 (each carrying its regex segment's own type/section). Hard count.
- **AC-2 (perfect partition):** `[1,2],[3],[4],[5],[6]` → same result under True and under the strict path
  (merges+types applied; no singleton filling).
- **AC-3 (duplicate / out-of-range / non-int):** e.g. `[[1,2],[2,7],["x",3],[]]`, N=4 → no raise;
  index 2 kept only in first group, 7 & "x" ignored, empty group skipped; unclaimed 4 → singleton;
  deterministic on repeat.
- **AC-4 (type flows / validated):** group typed `"liability"` → `clause_type=="liability"`; group typed
  `"nonsense"` → `None` (unchanged `_VALID_CLAUSE_TYPES` gate).
- **AC-5 (reversibility):** flag False + non-partition response → `ValueError` (as today); flag False +
  perfect partition → identical to today. `test_config.py`: add `CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING`
  is `bool`. **Existing-test edit (required, not optional):** `test_config.py:81` currently asserts
  `CLAUSE_SPLITTER_LLM_NUM_PREDICT == 1024` — **update it to `== 4096`** (a legitimate tracked default
  change, NOT a weakening; do not merely add a second assertion, or the file self-contradicts). The
  `test_config.py:88-89` `isinstance` checks stay green unchanged. `test_config.py` is already in the
  AC-9 diff allow-list, so no scope change — only this edit.
- **AC-6 (index-coverage / text preservation):** for the AC-1, AC-3 cases, `\n`-split each output
  `.text`, collect pieces → equals the input segment texts, each exactly once.
- **AC-7 (garbage still falls back):** `{}`, `{"clauses":[]}`, invalid JSON → `ValueError` under BOTH
  flag values.
- **AC-8 (num_predict):** existing `test_grouping_num_predict_uses_config` (`:500`) still green (reads the
  constant); add/confirm it observes 4096. **Do NOT touch `test_emit_text_mode_num_predict_is_4096`
  (`:511`)** (EMIT_TEXT path hardcodes 4096, independent — D7).
- **Pin (never weaken) the specific existing test the new default breaks:**
  `test_grouping_bad_partition_falls_back_to_regex` (`tests/unit/test_llm_refiner.py:479-497`,
  parametrized, runs under the `_grouping_mode` fixture). Under the new `True` default its **missing-index**
  (`[1,2]`), **out-of-range** (`[1,2,4]`), and **reordered** (`[1,3,2]`) cases now produce tolerant output
  instead of regex fallback. Fix: **pin those cases with the flag `False`** (monkeypatch
  `llm_refiner.CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING = False`) to keep asserting the strict fallback, AND
  add a tolerant-path expectation for them — do NOT delete. Its `[1,1,3]` (duplicate → AC-3),
  `{"clauses":[]}` and missing-`indices` (→ AC-7) cases still fall back / raise under both flags. Apply the
  same pin-don't-delete rule to any other grouping test surprised by the default.

## 4. Measurement (AC-10, live — governs the shipped default)
Needs `LLM_PROVIDER=groq` (`GROQ_MODEL=openai/gpt-oss-120b`) + local `bge-m3`, delivery off. Keep the
subset **small (1–3 docs)** — Groq free tier caps 200K tokens/day (046 RESULTS). Run flag ON vs OFF on
the same doc(s); record clause_type coverage (0→>0 on large docs), 027 floor-rescue count (0→>0), recall,
precision, false-flag, severity. Compare vs `eval/runs/BEFORE_042subset`. **Merge gate (the 042 gate):**
ship default `True` only if (i) recall rises, (ii) false-flag rise ≤ +5pp, (iii) recall-gain(pp) ≥
false-flag-gain(pp). If it fails, flip the default to `False` (feature present, reversible) — never weaken
the gate. Record a `RESULTS.md` with honest candidate-label framing.

## 5. Risks / limitations
- **Precision cost from the revived floor:** the 027 floor validates on-topic floor-type clauses without
  the ISSUP gate; more filled types ⇒ more floor rescues ⇒ potential false-flag rise (the 042 finding).
  Mitigant vs 042: typing here is the model's own (measured accurate on gpt-oss), not a phrase tagger —
  AC-10 + the gate decide the default.
- **On the OLLAMA (qwen3:8b) path** the flag also changes behavior (qwen grouping partials now applied).
  qwen types less accurately than gpt-oss → could reintroduce 042-style precision cost on the local
  default. The gate/measurement covers this; reversibility (`False`) is the safety valve.
- **Budget still finite:** a doc large enough to truncate even 4096 tokens to invalid JSON still falls
  back to regex (AC-7) — strictly no worse than today.

## 6. Merge
Whole `pytest` green; `git diff --name-only main` = the four code files (+ `specs/047-**`); qwen3:8b
reverted. Rebase `main`, merge `feature/047-tolerant-clause-grouping`, delete branch (`git-finish`);
re-apply qwen3:4b locally after. The AC-10 live measurement + `RESULTS.md` can follow the merge (like
046 Task 8) since the feature ships reversible and default-decidable; if AC-10 is run before merge and
fails the gate, set the default `False` in the same branch.
