# Feature 047 — Tolerant LLM clause-grouping — Tasks

Reference documents:
- Spec: `specs/047-tolerant-clause-grouping/spec.md` (APPROVED)
- Plan: `specs/047-tolerant-clause-grouping/plan.md` (APPROVED)
- Constitution: `specs/000-constitution.md` (**§2** no graph/edge/state; **§3** named config; **§7** TDD +
  never weaken; **§8** embeddings untouched; **§11** branch-gated)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **TDD (§7):** parser tests written FAILING first; they call `_parse_grouping_response` **directly**
  (pure — no network); the one budget test mocks the client.
- **Scope (AC-9):** `app/config.py`, `app/graph/nodes/splitters/llm_refiner.py`,
  `tests/unit/test_llm_refiner.py`, `tests/unit/test_config.py`, `specs/047-**`. **No
  `self_rag_validation_agent.py`, no `embeddings.py`, no graph/edge/state/migration.**
- **⚠ Revert local `OLLAMA_MODEL_NAME` qwen3:4b → qwen3:8b BEFORE committing** (breaks 4 config tests);
  re-apply after merge.
- **Do NOT stage** the unrelated uncommitted docs (`docs/ACCURACY.md`, `docs/DEPLOYMENT.md`,
  `specs/046-.../RESULTS.md`) in 047's commits.
- Default `CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING=True` ⇒ new behavior; `False` ⇒ byte-for-byte today.

---

## Task 0: Branch
- [ ] With spec + plan spec-reviewer-APPROVED, run `git-start` (checkout main, pull, `git checkout -b
  feature/047-tolerant-clause-grouping`). Commit spec/plan/tasks.

**Verify:** `git branch --show-current` → `feature/047-tolerant-clause-grouping`.

---

## Task 1: Config (§3)  [AC-5]
- [ ] **[MODIFY] `app/config.py`** — near the ClauseSplitter LLM constants (`CLAUSE_SPLITTER_LLM_EMIT_TEXT`
  ~:178 / `CLAUSE_SPLITTER_LLM_NUM_PREDICT` ~:187): add `CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING: bool = True`
  (with the plan §1 comment) and change `CLAUSE_SPLITTER_LLM_NUM_PREDICT: int = 1024` → `= 4096` (keep/
  update its comment). Both are plain module literals (like the siblings — no `_env_*` reader).

**Verify:** `python -c "import app.config as c; print(c.CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING, c.CLAUSE_SPLITTER_LLM_NUM_PREDICT)"` → `True 4096`.

---

## Task 2: Config test (red → green)  [AC-5]
- [ ] **[MODIFY] `tests/unit/test_config.py`** — add an assertion that
  `CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING` is a `bool`. **Update the EXISTING assertion at `:81`** from
  `CLAUSE_SPLITTER_LLM_NUM_PREDICT == 1024` to `== 4096` (a tracked default change — edit, do NOT add a
  second contradicting assertion). Leave the `:88-89` isinstance checks as-is.

**Verify:** `python -m pytest tests/unit/test_config.py -q` → PASS.

---

## Task 3: Parser tests (red)  [AC-1..AC-7]
- [ ] **[MODIFY] `tests/unit/test_llm_refiner.py`** (FAIL first). Add tests calling
  `llm_refiner._parse_grouping_response(raw_content, regex_clauses)` directly, building `regex_clauses`
  as real `ClauseBoundary` objects with `position=1..N` and **distinct single-line `text`**. Monkeypatch
  `llm_refiner.CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING` per case:
  - **AC-1 (partial → fill):** N=6, response `[{"indices":[1,2],"clause_type":"liability"},
    {"indices":[3],"clause_type":"confidentiality"}]` (4,5,6 omitted), flag True → **exactly 4** clauses
    in order: merged[1,2] type `liability`, [3] `confidentiality`, singletons 4,5,6 (each carrying its
    regex segment's own type/section).
  - **AC-2 (perfect partition):** `[1,2],[3],[4],[5],[6]` → same result under flag True and flag False.
  - **AC-3 (dup/out-of-range/non-int):** N=4, `[[1,2],[2,7],["x",3],[]]`, flag True → no raise; 2 kept
    only in first group, 7 & "x" ignored, empty skipped, unclaimed 4 → singleton; repeat = identical.
  - **AC-4 (type validated):** group typed `"liability"` → `clause_type=="liability"`; `"nonsense"` →
    `None`.
  - **AC-6 (index coverage):** for AC-1 & AC-3, `\n`-split each output `.text`, collect → equals input
    segment texts each exactly once.
  - **AC-7 (garbage falls back):** `{}`, `{"clauses":[]}`, invalid JSON → `ValueError` under BOTH flags.
  - **AC-5 (strict path):** flag False + non-partition → `ValueError`; flag False + perfect partition →
    identical to today.

**Verify:** the new tests FAIL (tolerant path absent) → confirms red.

---

## Task 4: Parser implementation (green)  [AC-1..AC-7]
- [ ] **[MODIFY] `app/graph/nodes/splitters/llm_refiner.py`**:
  - Add bare alias `CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING = _config.CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING`
    next to the existing aliases (~:26-27).
  - Refactor `_parse_grouping_response` (~:304): keep shared front matter (`json.loads` raise-on-invalid;
    require non-empty `data["clauses"]` list — AC-7). Then branch on the bare flag: `False` → **existing
    strict body verbatim** (partition check ~:342, assembly ~:347-373); `True` → tolerant body per plan §2
    (first-claim-wins, `isinstance(x, bool)` excluded, in-range ints only, empty groups skipped,
    passthrough singletons for unclaimed indices, sort by min claimed index, join within group ascending).
  - Factor per-group `ClauseBoundary` construction (section_number fallback, `_VALID_CLAUSE_TYPES` gate,
    `"\n".join`, sequential `position`/`clause_id`) into a shared local helper used by both paths so
    strict-path **output** stays byte-identical to today.

**Verify:** `python -m pytest tests/unit/test_llm_refiner.py -q` → the Task 3 tests PASS.

---

## Task 5: num_predict + pin surprised existing tests  [AC-8]
- [ ] **[CONFIRM]** `_call_ollama` grouping branch already passes `num_predict=CLAUSE_SPLITTER_LLM_NUM_PREDICT`
  (~:220) — the 4096 default flows through automatically; no `.chat(...)` edit.
- [ ] **[CONFIRM] `test_grouping_num_predict_uses_config` (`:500`)** stays green (reads the constant → now
  4096). **Do NOT touch `test_emit_text_mode_num_predict_is_4096` (`:511`)** (EMIT_TEXT hardcodes 4096).
- [ ] **[MODIFY — pin, never weaken] `test_grouping_bad_partition_falls_back_to_regex` (`:479-497`)** — its
  **missing-index** (`[1,2]`), **out-of-range** (`[1,2,4]`), **reordered** (`[1,3,2]`) cases now produce
  tolerant output under the `True` default. Pin those cases with `llm_refiner.CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING
  = False` to keep asserting the strict fallback, AND add a tolerant-path expectation for them. Its
  `[1,1,3]`/`{"clauses":[]}`/missing-`indices` cases still fall back/raise under both flags. Do NOT delete.
  Pin any other grouping test surprised by the default the same way.

**Verify:** `python -m pytest tests/unit/test_llm_refiner.py -q` → PASS.

---

## Task 6: Full suite + scope gate  [AC-9]
- [ ] Revert local `OLLAMA_MODEL_NAME` → `qwen3:8b`. `python -m pytest -q` → GREEN (pin any surprised test
  with justification, never weaken).
- [ ] `git diff --name-only main` = the allow-list only: `app/config.py`,
  `app/graph/nodes/splitters/llm_refiner.py`, `tests/unit/test_llm_refiner.py`, `tests/unit/test_config.py`,
  `specs/047-**`. **No `self_rag_validation_agent.py`, no `embeddings.py`, no graph/edge/state/migration**,
  and `OLLAMA_MODEL_NAME == "qwen3:8b"` in the diff. (Do not stage the unrelated `docs/**` /
  `specs/046-.../RESULTS.md` edits.)

**Verify:** suite green; diff scope confirmed.

---

## Task 7: Merge
- [ ] Whole `pytest` green; diff scope confirmed; qwen3:8b reverted. Rebase `main`, merge
  `feature/047-tolerant-clause-grouping`, delete branch (`git-finish`); re-apply qwen3:4b locally.

---

## Task 8: AC-10 live measurement (after merge; needs Groq key + local Ollama for bge-m3)
- [ ] Set `LLM_PROVIDER=groq`, `GROQ_MODEL=openai/gpt-oss-120b`, Ollama up with `bge-m3`, delivery OFF.
  On a **small (1–3 doc)** large-doc subset (Groq 200K-tokens/day cap — 046 RESULTS), run the harness with
  the flag ON vs OFF; `score` each; record clause_type coverage (0→>0 on large docs), 027 floor-rescue
  count (0→>0), recall, precision, false-flag, severity vs `eval/runs/BEFORE_042subset`.
- [ ] Apply the **042 merge gate** (recall rises; false-flag rise ≤ +5pp; recall-gain ≥ false-flag-gain).
  If it fails, flip `CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING` default to `False` (feature present,
  reversible) — never weaken the gate. Write `specs/047-tolerant-clause-grouping/RESULTS.md` (honest
  candidate-label framing, 026/041).

---

*Per §1/§11, implementation happens only on `feature/047-tolerant-clause-grouping`. Provider/parsing seam
only — no `ContractState`, no graph/edge, no migration, embeddings stay on Ollama (§8). Default
`CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING=True` is measurement-gated (AC-10); `False` ⇒ byte-for-byte today.*
