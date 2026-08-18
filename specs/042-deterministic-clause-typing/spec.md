# Feature 042 — Deterministic clause-type fallback (revive the recall floor on large docs)

## 1. Problem statement

The feature-041 miss-triage (offline analysis of the cached 32-contract run, all review-agent-gated)
localized the low measured recall to a specific, unintended interaction between two shipped features:

- The Self-RAG **recall floor** (027) rescues on-topic high-risk clauses from discard — **but it keys on
  the pipeline's assigned `clause_type`** (`self_rag_validation_agent.py`, `ct in
  SELF_RAG_RECALL_FLOOR_TYPES`).
- **`clause_type` is `None` for ~95% of clauses** on the eval corpus (265/279 surfaced findings). It is
  inferred **only** by the ClauseSplitter LLM refinement, which **feature 025 Lever A skips whenever
  regex yields > `CLAUSE_SPLITTER_LLM_MAX_CLAUSES` (=40) clauses** — i.e. every large real-world
  (CUAD) contract. With `clause_type = None`, the recall floor **never fires**, so material clauses
  (e.g. a limitation-of-liability clause that should classify as `liability`, a type already in the
  floor) are discarded at the Self-RAG gate.

A **measure-first live experiment** (`scripts/exp_clausetype_floor.py`, review-gated) **falsified the
naive fix** of simply raising the size gate: forced on large docs, the LLM grouping call goes
**off-schema** (a 117-clause doc emitted a document-summary tree that truncated at
`num_predict=1024`; a 45-clause doc returned a valid-but-wrong-shaped object), falls back to
regex-only, and `clause_type` stays `None`. So restoring typing via the LLM is fragile and slow
(~450 s/doc), and "raise the gate" does not work.

This feature restores clause typing **deterministically**: a cheap, offline keyword/pattern tagger
assigns `clause_type` from the clause **text** whenever the LLM path left it `None` (gated off by 025,
or failed). This **revives the existing 027 recall floor on large documents with no dependence on the
LLM** — the whole point being that the tagger is deterministic and therefore robust and
**unit-testable without Ollama**. The recall gain and its precision cost are then **measured by the
041/026 harness**.

### Position relative to the constitution

**No graph/edge change, no `ContractState` change, no migration.** This adds a deterministic typing
**fallback inside the existing ClauseSplitterAgent (Node 2)** — the 7-node graph and 2 conditional
edges are untouched (§2). The keyword→type mapping and an enable flag are **named config constants**
(§3), reversible to today's behavior (flag off ⇒ `clause_type` unchanged). Per §7 the tagger is
TDD-unit-tested (pure, no Ollama); per §1/§11 it is developed on
`feature/042-deterministic-clause-typing` and its effect re-measured with the 041 harness.

## 2. Inputs and outputs

### 2.1 New config (§3)
- `DETERMINISTIC_CLAUSE_TYPING_ENABLED: bool` — master switch. **Default `True`.** `False` ⇒
  byte-for-byte today's behavior (no fallback typing), for reversibility (§7 / D5).
- `DETERMINISTIC_CLAUSE_TYPE_PATTERNS` — an **ordered** mapping of `ClauseType.value` → compiled
  keyword/phrase patterns used to type a clause from its text. **Scope of the default map: the
  recall-floor-relevant types only** — `liability`, `termination`, `intellectual_property`,
  `confidentiality` (the current `SELF_RAG_RECALL_FLOOR_TYPES`) — because only those change floor
  behavior, and a conservative, high-precision map limits the precision cost (see D2/D3). The map is a
  single tuning knob; empty map ⇒ no fallback typing (equivalent to the flag off).

### 2.2 Behavior change in ClauseSplitter (`clause_splitter_agent.py`)
After the existing regex split and optional LLM refinement, in `_build_return` (or a dedicated
post-step it calls), for each clause whose `clause_type` **is `None`**:
- Run the deterministic tagger over the clause `text`. If the text matches a pattern, assign the
  corresponding `ClauseType`; ambiguous matches resolve by the map's fixed order (deterministic).
- **Precedence:** the tagger **only fills `None`** — a `clause_type` already assigned by the LLM
  refinement is **never overwritten** (so small/typed docs are unaffected except where they had `None`).
- Gated by `DETERMINISTIC_CLAUSE_TYPING_ENABLED`; when `False`, the loop is skipped entirely.
- Conservative by design: no match ⇒ leave `None` (a `None` clause simply gets no floor, exactly as
  today — the tagger never *removes* signal, only adds it).

### 2.3 Output
No new state field, no boundary-model field, no report/schema change. The only observable effect is
that clauses on large docs now carry a non-`None` `clause_type` for the floor-relevant types, which
makes the **existing** 027 recall floor fire for them → more material clauses reach
`final_status = VALIDATED` and appear as findings. Downstream consumers are unchanged (RiskScore keys
off `final_status`, not `clause_type`; the recall-floor validations already carry the
`relevance=True, isrel=None, issup=None` record shape from 027). **No Self-RAG-node change is needed** —
this feature only supplies the input the 027 floor already consumes.

## 3. Resolved decisions (inline)

- **D1 — Deterministic (not LLM) typing.** The measure-first experiment proved LLM typing on large
  docs is fragile (off-schema) and slow. A keyword/pattern tagger is deterministic, ~free, and
  unit-testable offline — the right robustness/latency/deadline trade. Fixing the LLM refiner's
  schema-adherence is **separate future work** (§6), attempted only if this ships with margin.
- **D2 — Default map covers only the recall-floor types.** Typing a non-floor type has **no** effect on
  floor behavior, so the default map is limited to `{liability, termination, intellectual_property,
  confidentiality}` to keep the change minimal and the precision cost bounded. Widening the map (or the
  floor set) is a documented option, measured by the harness.
- **D3 — Accept + MEASURE the precision cost; don't pretend it's free.** Because the 027 floor
  **VALIDATES** a floor-type clause even when ISSUP would discard, an **over-broad** tagger causes
  false flags. The tagger is therefore deliberately **conservative/high-precision** (specific legal
  phrases, not single common words), and the 041 harness quantifies the false-flag rate before/after.
  The 041 triage already found `anti_assignment`/`audit_rights` over-flagging pressure; the tagger must
  not worsen precision materially — this is an explicit measured constraint, not an afterthought.
- **D4 — Only fills `None`; never overrides the LLM.** Where LLM typing ran (small docs), its labels
  win; the tagger is a *fallback*, so small-doc behavior is unchanged except for previously-`None`
  clauses. This keeps the blast radius on the large-doc regime the experiment identified.
- **D5 — Config §3, reversible.** `DETERMINISTIC_CLAUSE_TYPING_ENABLED = False` (or empty map) ⇒
  byte-for-byte today's `clause_type` behavior and therefore today's recall floor (inert on large docs).
- **D6 — Does not touch 025 or the LLM refiner.** The size gate stays (its latency win is real); the
  refiner is unchanged. This feature adds typing *alongside* them, so no latency regression and no
  re-litigating 025.

## 4. Acceptance criteria

### Backend (pytest — all offline, no Ollama)
- **AC-1 (tagger correctness):** Given representative clause texts, the tagger returns the expected
  `ClauseType` for each floor type — a limitation-of-liability / indemnification clause → `liability`;
  a termination/survival clause → `termination`; an IP assignment/ownership clause →
  `intellectual_property`; a confidentiality/non-disclosure clause → `confidentiality`. Non-matching
  boilerplate → `None`.
- **AC-2 (precedence / fill-None-only):** A clause already carrying an LLM-assigned `clause_type` is
  **not** overwritten by the tagger; a clause with `clause_type=None` **is** filled when it matches.
- **AC-3 (integration in ClauseSplitter):** For a regex-only (LLM-skipped, all-`None`) clause set
  containing a clear liability clause, `_build_return` output has that clause typed `liability`
  (so the 027 floor would fire); a set with no floor-type language stays all-`None`.
- **AC-4 (reversibility):** With `DETERMINISTIC_CLAUSE_TYPING_ENABLED=False`, ClauseSplitter output is
  **identical** to today (all previously-`None` clauses stay `None`). A `test_config` assertion checks
  the flag is a bool and every `DETERMINISTIC_CLAUSE_TYPE_PATTERNS` key is a valid `ClauseType.value`.
- **AC-5 (no architecture change):** `git diff` touches only `app/config.py`, `clause_splitter_agent.py`
  (+ any new `app/…/clause_typer.py` helper), and their tests — **no** graph/edge/`ContractState`/
  migration/Self-RAG-node change. Whole `pytest` suite green.
- **AC-6 (determinism):** The tagger is a pure function of the clause text + config (no RNG, no I/O,
  no Ollama); repeated calls give identical results (supports the offline test guarantee).

### Live measurement (harness — AC-7)
- **AC-7:** Re-run the 041/026 harness (`run` + `score`) on the corpus before vs after (or on a
  representative large-doc subset if a full run doesn't fit the deadline). Report: **clause_type
  non-None coverage** (expected: jumps from ~5% toward a meaningful fraction on large docs),
  **recall / miss rate** (expected: rises as floor-type material misses are rescued), and the
  **precision / false-flag rate** (the measured cost of D3). The deliverable is a *measured* trade,
  not an assumed one — this also supplies the positive-half control the 041 experiment lacked
  (confirm a populated floor-type `clause_type` actually flips a miss fn→tp).

## 5. Edge cases
- **EC-1 — Clause matches multiple floor types** → the map's fixed order decides (deterministic);
  documented in the plan.
- **EC-2 — Empty/whitespace clause text** → no match → `None` (unchanged; the tagger never invents a
  type for empty text).
- **EC-3 — LLM refinement ran and assigned a type** → tagger does not touch it (D4).
- **EC-4 — Flag off** → no fallback typing; today's behavior (D5).
- **EC-5 — Over-match risk** → a clause with incidental risk vocabulary but no substantive risk clause
  may be mistyped and then floor-validated (a false flag). Mitigated by conservative patterns and
  **measured** by AC-7; the plan documents the precision/recall trade and the option to tighten
  patterns or narrow the map/floor.
- **EC-6 — Huge doc truncated at `MAX_CLAUSES_LIMIT` (500)** → tagger runs on the retained clauses
  only (unchanged truncation behavior; out of scope to fix).

## 6. Out of scope
- **Fixing the ClauseSplitter LLM refiner's schema-adherence** on large inputs (batching, grammar-/
  structured-output enforcement, `num_predict` scaling) — the falsified-naive-fix follow-up; **future
  work**, only if 042 ships with deadline margin.
- **Changing feature 025's size gate** or its latency behavior (D6) — untouched.
- **Changing `SELF_RAG_RECALL_FLOOR_TYPES` or any Self-RAG-node logic** — 042 only supplies typing
  input; the floor is reused as-is.
- **Confirming the 041 candidate gold labels** (the `anti_assignment`/`audit_rights` over-flag
  question) — a separate offline data effort, human-gated, not this feature.
- **A general/high-accuracy clause classifier** — the constitution PERMANENTLY CUTs a separate
  classification node; this is a within-node deterministic fallback, not a new agent.

## 7. Evaluation (metrics to log)
Validated by the 041/026 harness before/after: **clause_type coverage, recall, miss rate, precision,
false-flag rate, severity accuracy**, plus the Self-RAG **seen-but-discarded** diagnostic (expected to
drop for floor types once they are typed). Honest framing (026/041): the candidate-labeled corpus is
indicative, not authoritative — the harness shows the **direction and rough magnitude** of the
recall/precision trade, to be re-confirmed on a larger expert-labeled corpus.

## 8. Notes for plan.md / tasks.md (pointers)
- **Config:** add `DETERMINISTIC_CLAUSE_TYPING_ENABLED` (bool, default True) and
  `DETERMINISTIC_CLAUSE_TYPE_PATTERNS` (ordered map, floor types only) to `app/config.py`, near the
  Self-RAG/clause-splitter constants. Mirror the module-alias pattern so tests can monkeypatch.
- **Tagger:** a pure helper (e.g. `app/graph/nodes/splitters/clause_typer.py` or alongside the regex
  splitter): `infer_clause_type(text) -> Optional[ClauseType]` compiling patterns once at import.
  Conservative, ordered, deterministic. No Ollama, no I/O.
- **Wire-in:** in `clause_splitter_agent.py::_build_return`, after `_to_clause_type`, if the resulting
  type is `None` and the flag is on, call `infer_clause_type(text)`; keep an existing non-`None`.
  Ensure both the LLM-skipped (regex-only) and LLM-failed (regex-fallback) paths reach this.
- **Tests:** new `tests/unit/test_clause_typer.py` (AC-1/2/6, pure); extend
  `test_clause_splitter_agent.py` for AC-3/4 (integration + reversibility); add the `test_config`
  validity assertion (AC-4). TDD failing-first.
- **Measurement:** re-run the 041 harness (`run` + `score`) for AC-7 before/after; report coverage,
  recall, and false-flag deltas. If a full 32-doc live run doesn't fit the deadline, measure a
  representative large-doc subset (document the reduced scope).
