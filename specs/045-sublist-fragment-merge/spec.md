# Feature 045 — Keep enumerated sub-list items with their governing clause

Branch: `feature/045-sublist-fragment-merge` (per constitution §11).

## 1. Problem statement

The ClauseSplitter regex pre-pass (`regex_splitter.py`) splits on `(a)` / `(ii)` and `a.` / `b.`
**sub-list markers**, treating each enumerated sub-item as its own clause. In real contracts these
markers are almost always **sub-items of a governing clause**, not top-level clauses — so splitting on
them **severs the material obligation (in a sub-item) from its governing stem** and leaves a tiny,
contextless fragment that Self-RAG cannot judge (a `B_never_scored` miss in the accuracy diagnostic).

**Measured on the cached 6-document run (offline, no assumptions):**
- **225 / 981 clauses (22.9%) start with a `(a)`/`(ii)` sub-list marker**; **83 (8.5%) are short
  (<120 chars) contextless list fragments**. (The `a.`/`b.` marker adds only 0.3% — negligible.)
- **Confirmed root cause on a real document** (FuseMedical Distributor Agreement): the high-severity
  **non-compete** obligation is sub-item `(f)` of a `"2.4 The Distributor shall not: (a)… (h)…"` list.
  The splitter cuts it into the fragment `"(f) act as the agent … competitive with the Product; or"`
  with **no governing stem** → Self-RAG never scores it → a real recall miss.

**A/B validated on that document** (splitter run with vs without the sub-list split):

| | Clauses | Median len | Short (<80) | Non-compete clause |
|---|---|---|---|---|
| Current (splits sub-lists) | 187 | 135 | 59 | 113-char fragment, **no stem** |
| Without sub-list split | 117 | 169 | 31 | 915 chars, **with `"2.4 The Distributor shall not:"` stem** |

Not splitting sub-list markers **reattaches the enumerated items to their governing stem** (the
non-compete regains full context) and makes segmentation *healthier* — fewer clauses, larger median,
~half the short fragments, **no collapse** (the higher-level `1.2`/`2.4`/`Article N` numbering still
provides the real clause boundaries).

### Position relative to the constitution
Changes only which regex markers `regex_splitter.py` (step 1 of ClauseSplitter, Node 2) splits on —
the 7-node graph, edges, and `ContractState` are untouched (§2). Gated by a **named §3 config flag**,
reversible to today's exact segmentation. Per §7 the splitter is pure and TDD-unit-tested (no Ollama).
Developed on `feature/045-sublist-fragment-merge` (§1/§11).

## 2. Inputs and outputs

### 2.1 New config (§3)
- `CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS: bool` — **Default `False`** (the new, better behavior:
  enumerated `(a)`/`(ii)`/`a.` sub-items stay attached to their governing clause). **`True` ⇒
  byte-for-byte today's segmentation** (sub-list markers split as before), for reversibility.

### 2.2 Behavior change (`regex_splitter.py`)
The two **sub-list-marker** patterns — `(?m)^[ \t]*(\([a-z]+\)|\([ivxlcdm]+\))\s` (the `(a)`/`(ii)`
pattern) and `(?m)^[ \t]*([a-z])\.[ \t]` (the `a.`/`b.` pattern) — are applied **only when
`CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS` is `True`**. When `False` (default), they are omitted from the
active pattern set, so enumerated sub-items are absorbed into the clause opened by the nearest
higher-level marker (`1.` / `Article N` / `Section N` / `§N` / `Clause N` / recital keyword) or the
paragraph fallback. All other patterns are unchanged.

### 2.3 Output
Same `list[ClauseBoundary]` shape; no new state field, no schema/report change. Clauses on documents
that use `(a)`/`(ii)` enumerations are fewer and larger (each governing clause now includes its
sub-list), so material obligations buried in sub-items retain context and reach Self-RAG intact.

## 3. Resolved decisions (inline)
- **D1 — Default OFF = do not split sub-lists.** The measured evidence (segmentation healthier, a real
  recall miss recovered, no collapse) makes not-splitting the better default. `(a)`/`(i)` in contracts
  are sub-items, not top-level clauses.
- **D2 — Reversible §3 flag, not a hard removal.** Segmentation ripples downstream, so keep an exact
  rollback (`True` ⇒ today's behavior) and a clean A/B knob for AC-7 measurement.
- **D3 — Scope only the two sub-list-marker patterns.** The `\d+.` numeric pattern is **not** touched
  — the numeric-schedule noise it produces (patent tables, bare section numbers) is a separate,
  lower-value precision concern, out of scope (§6), and that pattern is load-bearing for real numbered
  clauses.
- **D4 — Higher-level markers still bound clauses.** Because `1.`/`Article`/`Section`/`§`/`Clause`/
  recital patterns remain, dropping the sub-list split does not under-segment; the A/B test confirms
  clause count stays healthy (187→117, not →a few blobs).
- **D5 — Pure, deterministic.** No RNG/I/O/Ollama; flag read at call time so tests can toggle it.

## 4. Acceptance criteria (pytest — all offline, no Ollama)
- **AC-1 (sub-list items merge, default):** given a `"X. The Distributor shall not:\n(a) …; or\n(b) …;
  or\n(f) act as the agent … competitive with the Product; or"` block, with the flag at its default
  (`False`) `split_by_regex` returns **one** clause containing the stem **and** all sub-items (the
  `(f)` non-compete text is in the same clause as `"shall not"`), not one clause per `(a)`.
- **AC-2 (higher-level boundaries preserved):** a document with `1.`, `2.4`, `Article N` headings plus
  `(a)`/`(b)` sub-items still splits at the numbered/heading boundaries; sub-items attach to the
  correct parent (clause count is materially reduced but > 1; no giant single blob).
- **AC-3 (reversibility):** with `CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS=True`, `split_by_regex` output
  is **identical** to today (each `(a)`/`(ii)`/`a.` opens its own clause). A `test_config` assertion
  checks the flag is a bool.
- **AC-4 (no regression on non-sub-list docs):** a document with only `1.`/`Article`/`§`/`WHEREAS`
  markers (no `(a)`/`a.`) segments identically regardless of the flag (the removed patterns never
  matched it anyway) — the existing `test_regex_splitter` suite stays green.
- **AC-5 (a./b. also covered):** an `a. … b. …` enumerated block is likewise kept with its stem when
  the flag is False, split when True.
- **AC-6 (no architecture change):** `git diff` touches only `app/config.py`, `regex_splitter.py`, and
  their tests (+ `specs/045-**`) — no graph/edge/`ContractState`/migration/Self-RAG change. Whole
  `pytest` green.
- **AC-7 (determinism):** pure function of text + flag; repeated calls identical.

### Live measurement (harness — AC-8, deferred/optional)
- **AC-8:** on the large-doc subset, re-segment (flag default off) and confirm (i) the short-fragment
  clause rate drops (measured baseline: 8.5% list fragments, 28.6% <30-char clauses), and (ii) the
  previously-`B_never_scored` non-compete now reaches Self-RAG with its stem (fn→tp candidate). A full
  re-run needs live Ollama; the offline splitter A/B (already demonstrated) is the primary evidence.

## 5. Edge cases
- **EC-1 — Sub-list with no higher-level marker above it** (rare: a doc that starts straight into
  `(a)/(b)`): with the flag off those items fall to the paragraph/whole-text fallback rather than one
  clause each — acceptable (still keeps them together; no worse than a fragment).
- **EC-2 — `(a)` mid-sentence / inline** (not at line start): unaffected — the pattern was already
  line-anchored (`^`), so only line-leading markers were ever split.
- **EC-3 — Flag on** → today's exact behavior (D2).
- **EC-4 — Very long merged clause** (a stem with many sub-items): may exceed prior per-clause sizes
  but stays within `MAX_CLAUSES_LIMIT`/`MIN_CLAUSE_LENGTH` handling, which is unchanged; the A/B test
  showed a healthy 915-char clause, well under the 4561-char max already present.

## 6. Out of scope
- The `\d+.` numeric-schedule noise (patent tables, bare section numbers — 19.7%/9.5% measured): a
  separate precision concern; the `\d+.` pattern is load-bearing and not touched here.
- Merging fragments *after* splitting (a post-processor) — this feature prevents the over-split at the
  source instead; simpler and measured-sufficient.
- Any Self-RAG / scoring / retrieval change — 045 only supplies better-segmented input.

## 7. Evaluation (metrics to log)
Deterministic unit tests (AC-1…AC-7) are the primary gate. The offline splitter A/B on the FuseMedical
doc (187→117 clauses, non-compete 113-char-fragment → 915-char-with-stem, short<80 59→31) is the
recorded measured evidence. Optional live confirmation is AC-8.

## 8. Notes for plan.md / tasks.md (pointers)
- **Config:** add `CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS: bool = False` to `app/config.py`.
- **Splitter:** in `regex_splitter.py`, move the two sub-list-marker `re.compile(...)` entries into a
  separate `_SUBLIST_PATTERNS` tuple; `_COMPILED_PATTERNS` (base) excludes them. `split_by_regex`
  assembles the active pattern list at call time: base + (sub-list iff the flag is True). Import
  `app.config` and re-expose `CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS` as a bare module name for
  monkeypatch (regex_splitter currently imports no config — this adds the first, minimal read).
- **Tests:** extend `tests/unit/test_regex_splitter.py` (AC-1..AC-5, AC-7); add the `test_config` bool
  assertion (AC-3). TDD failing-first. **⚠ Revert the local `OLLAMA_MODEL_NAME` qwen3:4b→qwen3:8b
  before committing (it breaks 4 config tests).**
