# Feature 047 — Tolerant LLM clause-grouping (use partial model output instead of all-or-nothing regex fallback)

Branch: `feature/047-tolerant-clause-grouping` (per constitution §11).

## 1. Problem statement

The ClauseSplitter LLM refinement runs in **grouping mode** (`CLAUSE_SPLITTER_LLM_EMIT_TEXT=False`,
the shipped default): the model receives the regex segments as a numbered list and returns, per logical
clause, the **indices** it merges plus a `clause_type`. `_parse_grouping_response` then requires the
flattened indices to be an **exact ordered partition of `1..N`** (`llm_refiner.py:342`). If the model's
answer is not a perfect partition, the parser raises `ValueError` and `refine_with_llm` **falls back to
the raw regex clauses — discarding everything the model got right** (both its merges and, critically,
its `clause_type` labels).

This all-or-nothing behavior is the reason the strongest model (feature 046 / Groq `gpt-oss-120b`) did
**not** improve accuracy: its grouping output is thrown away on exactly the documents where it matters.

**Measured directly against Groq `gpt-oss-120b` (2026-08-22, `specs/046-.../RESULTS.md`):**
- **Small input (6 segments):** the model returned a **flawless** partition and correct types —
  `{"indices":[1,2],"clause_type":"liability"}`, then `confidentiality`, `term`, `termination`,
  `intellectual_property`. Parser accepts it.
- **Large input (80 segments):** the model returned **valid JSON covering only 57 of 80 indices** — an
  incomplete partition → `ValueError: grouping indices are not an exact ordered partition of 1..80` →
  **full regex fallback, all types dropped.** Real contracts routinely exceed 40 segments (025 Lever A
  skips the whole LLM typing above `CLAUSE_SPLITTER_LLM_MAX_CLAUSES=40`), so the large-doc regime — the
  one where clause typing is most needed — is precisely where grouping fails today.
- Contributing factor: the grouping output token budget `CLAUSE_SPLITTER_LLM_NUM_PREDICT=1024` is too
  small for large docs (57 singleton groups already ≈ 3.4 KB), and on Groq reasoning models the hidden
  reasoning tokens share that budget — so large-doc grouping is additionally prone to truncation.

### Why fixing this lifts recall (the mechanism)
The **027 recall floor** (`self_rag_validation_agent.py`) validates an on-topic clause **without** the
ISREL/ISSUP discard gates when its `clause_type ∈ SELF_RAG_RECALL_FLOOR_TYPES = {liability, termination,
intellectual_property, confidentiality}` (`config.py:305`). Those four types are a **subset of the 12
types the grouping prompt already assigns**. Today, because grouping fails on large docs → `clause_type`
is `None` → the floor is inert (the 041 root cause). Letting the model's **valid, per-clause** typing
flow through revives the floor on the highest-value clause types, using the **model's own judgment**
(the 046 probe showed gpt-oss types these accurately) — unlike feature 042's deterministic phrase tagger,
whose imprecision caused a ~1:1 recall/precision trade (042 shipped OFF).

### Position relative to the constitution
Changes only `_parse_grouping_response` / `_call_ollama` in `llm_refiner.py` (step 2–3 of ClauseSplitter,
Node 2) and adds §3 config. The 7-node graph, edges, and `ContractState` are untouched (§2); embeddings
untouched (§8). Gated by a **named §3 config flag**, reversible to today's exact strict-partition
behavior. The new parsing logic is a **pure function** → TDD-unit-tested with no Ollama (§7).

## 2. Inputs and outputs

### 2.1 New / changed config (§3)
- `CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING: bool` — **Default `True`** (new behavior: apply the model's
  valid groups + types, fill any gaps with passthrough singletons). **`False` ⇒ byte-for-byte today's
  strict all-or-nothing partition check**, for reversibility.
- `CLAUSE_SPLITTER_LLM_NUM_PREDICT` — **raise default `1024 → 4096`** so large-doc index-only grouping
  output (and, on Groq, shared reasoning tokens) is not truncated. Index-only JSON is compact, so the
  higher cap is bounded in cost. (Env-overridable; still read at call time.)

### 2.2 Behavior change (`llm_refiner.py::_parse_grouping_response`)
When `CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING` is `True`, the parser **no longer requires an exact
partition**. It builds the refined clause list so that **every input segment appears exactly once**
(text-preservation guarantee retained), as follows:

1. Parse JSON; require `data["clauses"]` is a non-empty list (unchanged — a completely unusable response
   still raises → regex fallback).
2. Walk the model's clauses **in order**; for each, keep only indices that are **in range `1..N`**, are
   **ints**, and are **not already claimed** by an earlier group (first claim wins; later duplicates
   dropped). A group that has ≥1 surviving index becomes an output clause carrying the model's
   `section_number`/`clause_type`; a group left empty is skipped.
3. Any input index **not claimed** by any valid group becomes its **own passthrough singleton clause**,
   preserving that regex segment's original `section_number`/`clause_type` (i.e. today's regex clause).
4. Assemble all output clauses (groups + passthrough singletons) **sorted by their minimum claimed
   index** (document order); within each clause, join its segments' text in **ascending index order**
   with the existing `"\n".join(...)` logic (`llm_refiner.py:350`); renumber `position`/`clause_id`
   sequentially. Note a first-claim-wins group may hold **non-contiguous** indices, so two output
   clauses' index ranges can interleave — ordering is by each clause's *minimum* claimed index.

**Text-preservation invariant (checkable form).** Because a merged group concatenates its segments into
a single `.text` via `"\n".join`, the invariant is stated on **index coverage**, not on a "multiset of
`.text` values": **every input index `1..N` is claimed by exactly one output clause (a group or a
singleton) — none dropped, none duplicated.** The **authoritative** invariant is that index coverage; the
`"\n"`-split-equals-input-texts form is the **test-fixture** check AC-6 uses (fixtures use single-line,
distinct per-segment texts so the round-trip is exact — real multi-line segment text would make a naive
`\n`-split lossy, but the parser algorithm is defined purely on indices, so this is a fixture concern,
not a correctness one). Segment order across non-contiguous merges may differ; nothing is lost or
duplicated.

When `CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING` is `False`, the exact current strict-partition logic runs
unchanged (raises on non-partition → regex fallback).

### 2.3 Output
Same `list[ClauseBoundary]` shape; no new state field, no schema/report change. On large docs the model's
partial merges + types are now applied (previously all discarded), so `clause_type` is populated on the
clauses the model could confidently classify — reviving the 027 floor on liability/IP/confidentiality/
termination clauses without any graph change.

## 3. Resolved decisions (inline)
- **D1 — Partial model output beats all-or-nothing discard.** A valid, in-range subset of the model's
  grouping is strictly more information than falling back to raw regex; unreferenced segments degrade
  gracefully to today's regex singletons. Text preservation is *maintained* structurally (every input
  index appears exactly once — in a group or as a singleton).
- **D2 — Reversible §3 flag (`False` ⇒ today exactly).** Segmentation ripples downstream, so keep an
  exact rollback and a clean A/B knob for AC-8 measurement (mirrors 042/044/045).
- **D3 — First-claim-wins for duplicate indices; ignore out-of-range/non-int.** Deterministic,
  order-preserving conflict resolution; guarantees each segment is used exactly once.
- **D4 — Raise the grouping token budget (1024→4096).** Truncation is a co-cause of large-doc failure;
  index-only output is compact so the cap rise is cheap. Env-overridable (§3).
- **D5 — Default `True`, but the ship decision is measurement-gated (like 042).** Tolerant grouping
  revives the 027 floor, which trades recall for precision. Unlike 042's deterministic tagger, typing
  here is the model's own (measured accurate on gpt-oss). AC-8 + the plan's merge gate decide whether it
  ships `True`; if precision fails the gate, ship `False` (feature present, reversible) — never weaken
  the gate to pass.
- **D6 — Pure parser, deterministic.** `_parse_grouping_response` remains a pure function of
  `(raw_content, regex_clauses, flag)`; flag read at call time so tests toggle it. No RNG/I/O in parsing.
- **D7 — `EMIT_TEXT=True` (legacy re-emit) path is untouched.** This feature only affects the grouping
  (`EMIT_TEXT=False`) path, which is the shipped default.

## 4. Acceptance criteria (pytest — parser tests are offline; client mocked where needed)
- **AC-1 (partial coverage → fill gaps):** given `N=6` regex clauses and a model response grouping only
  `{"indices":[1,2],type:liability}` and `{"indices":[3],type:confidentiality}` (indices 4,5,6 omitted),
  with the flag `True` the parser returns **4 clauses**: the merged [1,2] (type liability), [3]
  (confidentiality), and passthrough singletons for 4, 5, 6 — in document order, every segment's text
  present exactly once.
- **AC-2 (perfect partition unchanged):** a full valid partition (e.g. `[1,2],[3],[4],[5],[6]`) yields
  the same result under `True` and under the legacy strict path — merges + types applied, no singleton
  filling needed.
- **AC-3 (duplicate / out-of-range / non-int indices):** a response with a duplicate index, an
  out-of-range index (`> N` or `< 1`), and a non-int index is handled without raising: duplicate's later
  occurrence dropped, out-of-range/non-int ignored; any now-unclaimed segment becomes a singleton; text
  preserved exactly once each. Result is deterministic.
- **AC-4 (clause_type flows to enable the floor):** for a model group typed `"liability"` (∈
  `SELF_RAG_RECALL_FLOOR_TYPES`), the returned `ClauseBoundary.clause_type == "liability"` (validated
  against `_VALID_CLAUSE_TYPES`); an invalid/unknown type string falls to `None` (unchanged validation).
- **AC-5 (reversibility):** with `CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING=False`, a non-partition response
  **raises `ValueError`** exactly as today (→ regex fallback in `refine_with_llm`); a perfect partition
  parses identically to today. `test_config` asserts the flag is a bool and `CLAUSE_SPLITTER_LLM_NUM_PREDICT`
  is an int.
- **AC-6 (text-preservation invariant, index-coverage form):** for any accepted response, splitting
  every output clause's `.text` on `"\n"` and collecting the pieces yields **exactly** the input
  segments' texts — each present **exactly once** (none dropped, none duplicated). (Fixture uses
  distinct per-segment texts so the pieces are identifiable.) Asserted on the partial, duplicate, and
  out-of-range cases. This is the concrete, output-checkable form of §2.2's index-coverage invariant;
  segment order across non-contiguous merges may differ.
- **AC-7 (empty/garbage response still falls back):** `{}`, `{"clauses":[]}`, and invalid JSON still
  raise `ValueError` under both flag values (→ regex fallback) — tolerance never fabricates clauses.
- **AC-8 (num_predict raised):** `_call_ollama` submits the grouping call with `num_predict` =
  `CLAUSE_SPLITTER_LLM_NUM_PREDICT` (now 4096 default); assert via a mocked client capturing `options`.
  The existing `test_grouping_num_predict_uses_config` (`test_llm_refiner.py:500`) reads the constant so
  it stays correct after the default rise. **Do NOT touch `test_emit_text_mode_num_predict_is_4096`
  (`:511`)** — the EMIT_TEXT path hardcodes 4096 independently (D7) and is unaffected.
- **AC-9 (no architecture change):** `git diff` touches only `app/config.py`, `llm_refiner.py`, and
  their tests (+ `specs/047-**`) — no graph/edge/`ContractState`/migration/Self-RAG/embeddings change.
  Whole `pytest` green.

### Live measurement (harness — AC-10)
- **AC-10:** on a small (token-cap-safe) large-doc subset via Groq `gpt-oss-120b`, re-run with the flag
  ON vs OFF and record: `clause_type` coverage (0 → >0 on large docs), 027 floor-rescue count (0 → >0),
  recall, precision, false-flag rate, severity. Apply the plan's merge gate (recall rises; false-flag
  rise ≤ +5pp; recall-gain ≥ false-flag-gain — the 042 gate) to decide the shipped default. Honest
  candidate-label framing (026/041). Groq free-tier 200K-tokens/day cap ⇒ keep the subset small (1–3
  docs); a full run is optional.

## 5. Edge cases
- **EC-1 — Model returns ALL singletons (no merges), full partition:** identical to regex clauses but
  with model types applied → types flow, boundaries unchanged. Fine.
- **EC-2 — Model omits most indices (covers few):** the many unclaimed segments become singletons →
  result ≈ regex clauses plus the few merges/types the model did provide. Strictly ≥ today's info.
- **EC-3 — A group references only out-of-range/duplicate indices (empties out):** skipped; its intended
  segments (if unclaimed) still appear as singletons. No text lost, no crash.
- **EC-4 — Flag OFF:** today's exact behavior (D2/AC-5).
- **EC-5 — Very large doc still exceeds raised budget:** if the response truncates to invalid JSON it
  still raises → regex fallback (AC-7); if it truncates to *valid* JSON with partial coverage, tolerance
  applies the partial result (AC-1) — strictly better than today.

## 6. Out of scope
- Changing the grouping **prompt** wording / few-shot examples (a separate, optional tuning lever; the
  probe shows the schema is understood — the failure is parser strictness + budget, not prompt).
- The `EMIT_TEXT=True` legacy re-emit path (D7) and the regex patterns themselves (040/044/045 own those).
- Any Self-RAG / scoring / retrieval / floor-set change — 047 only lets existing clause_type reach the
  existing 027 floor. Re-tuning `SELF_RAG_RECALL_FLOOR_TYPES` is separate.
- The direct whole-contract extraction redesign (the larger "utilize the model" path) — deferred; 047 is
  the measure-first step that precedes it.

## 7. Evaluation (metrics to log)
Deterministic parser unit tests (AC-1…AC-9) are the primary gate. AC-10 is the live floor-rescue /
recall / precision measurement that governs the shipped default via the 042 merge gate.

## 8. Notes for plan.md / tasks.md (pointers)
- **Config:** add `CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING: bool = True`; raise
  `CLAUSE_SPLITTER_LLM_NUM_PREDICT` default `1024 → 4096`. `CLAUSE_SPLITTER_LLM_NUM_PREDICT` is **already**
  aliased as a bare module name in `llm_refiner.py:27`, so **only the new `TOLERANT_GROUPING` flag** needs
  adding as a bare alias (mirroring the existing `CLAUSE_SPLITTER_LLM_EMIT_TEXT`/`_NUM_PREDICT` pattern)
  for monkeypatch.
- **Parser:** split `_parse_grouping_response` into the strict path (today) and a tolerant path selected
  by the flag; factor the shared JSON-load + `clauses`-list validation. Tolerant path implements the
  claim/gap/sort algorithm in §2.2 with the text-preservation invariant.
- **Tests:** extend `tests/unit/test_llm_refiner.py` (AC-1..AC-8) calling `_parse_grouping_response`
  directly (pure) + one mocked-client `_call_ollama` test for AC-8; add `test_config` assertions (AC-5).
  TDD failing-first. **⚠ Revert local `OLLAMA_MODEL_NAME` qwen3:4b→qwen3:8b before committing** (breaks
  4 config tests); re-apply after merge.
- **Measurement:** AC-10 needs live Groq (`LLM_PROVIDER=groq`) + local `bge-m3`; keep the subset small
  (200K-tokens/day cap). Compare vs `eval/runs/BEFORE_042subset`.
