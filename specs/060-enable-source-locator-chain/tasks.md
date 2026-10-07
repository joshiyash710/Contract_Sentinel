# Feature 060 — Enable the source-locator traceability chain by default — Implementation Tasks

Reference documents:
- Spec: `specs/060-enable-source-locator-chain/spec.md`
- Plan: `specs/060-enable-source-locator-chain/plan.md`
- Constitution: `specs/000-constitution.md` (**§2/§10** no node/edge/state/migration; **§3** named config;
  **§7** TDD / never weaken a test; **§11** branch workflow)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **Config-default flip only.** Flip two `_env_bool(..., False)` defaults to `True` in `app/config.py`. No
  node/edge/`ContractState`/`specs/001`/migration/dependency/frontend change. Both flags stay env-overridable.
- **Scope allow-list (AC-6)** = `app/config.py`, `backend/eval/RESULTS_055.md` (NEW), the new default test,
  the pinned off-path tests, `specs/055-pdf-source-locator/tasks.md` (Task 12 tick + pointer), and the 060
  specs. Nothing else.
- **TDD (§7):** write the default-resolution test first, confirm FAIL (defaults are False today), then flip.
  Off-path tests are made hermetic (flag pinned to the value they assert) — never weakened or deleted.
- **Measurement already run:** `backend/eval/measure_055_extraction_diff.py` over `backend/eval/corpus` (n=30)
  → raw char similarity min 99.71%, whitespace-collapsed 100%, 0/30 clause-count change. Task 3 records it.

---

## Task 0: Branch
- [ ] From up-to-date `main` (`git checkout main && git pull`), create `feature/060-enable-source-locator-chain`
  (`git-start`). Commit the APPROVED spec/plan/tasks on the branch. (The measurement script
  `backend/eval/measure_055_extraction_diff.py` is already present on `main` from the gating run.)

**Verify:** `git branch --show-current` → `feature/060-enable-source-locator-chain`.

---

## Task 1: Write the failing default-resolution tests first  [AC-1, AC-2, AC-3]
- [ ] **[NEW] `tests/unit/test_config_chain_defaults.py`.** `app.config` resolves `_env_bool` at import, so
  assert defaults by reloading under a controlled environment. Pattern per test: `monkeypatch.delenv(<VAR>,
  raising=False)` (AC-1/AC-2) or `monkeypatch.setenv(<VAR>, "False")` (AC-3), then `importlib.reload(app.config)`,
  assert the constant, and **restore** `app.config` by reloading once more under the original environment in a
  `finally`/fixture so no mutated module leaks into the rest of the suite.
  - AC-1: `PDF_SOURCE_LOCATOR_ENABLED` unset → reloaded constant `is True`.
  - AC-2: `UPLOAD_SOURCE_RETENTION_ENABLED` unset → reloaded constant `is True`.
  - AC-3: each var set to `"False"` → reloaded constant `is False` (override still wins).
- [ ] Run `python -X utf8 -m pytest -q tests/unit/test_config_chain_defaults.py` → CONFIRM AC-1/AC-2 FAIL
  (defaults resolve False today); AC-3 passes already.

---

## Task 2: Flip the config defaults  [AC-1, AC-2, AC-3]
- [ ] `app/config.py` ~line 297: `PDF_SOURCE_LOCATOR_ENABLED: bool = _env_bool("PDF_SOURCE_LOCATOR_ENABLED",
  True)`.
- [ ] `app/config.py` ~line 304: `UPLOAD_SOURCE_RETENTION_ENABLED: bool = _env_bool(
  "UPLOAD_SOURCE_RETENTION_ENABLED", True)`.
- [ ] Update the inline comments that say "default … False / flipped on when 057 ships" to state the now-on
  default + the 060 rationale (chain on by default; override to opt out). Only the `_env_bool` default arg
  changes — the env-override path is untouched (AC-3).

**Verify:** `test_config_chain_defaults.py` now fully green.

---

## Task 3: Record the 055 Task 12 measurement  [AC-5]
- [ ] **[NEW] `backend/eval/RESULTS_055.md`** (mirrors the `eval/RESULTS_041.md` precedent): the command
  (`.venv/Scripts/python.exe eval/measure_055_extraction_diff.py`), corpus (`backend/eval/corpus`, n=30), the
  aggregate (raw char similarity mean 99.97% / median 99.98% / **min 99.71%**; whitespace-collapsed 100.00% on
  every doc; **0/30** regex clause-count change), and the conclusion: the dict path is content-identical to the
  plain path and does not change segmentation → flipping `PDF_SOURCE_LOCATOR_ENABLED` on by default is safe.
- [ ] `specs/055-pdf-source-locator/tasks.md` Task 12 → check it off with a one-line pointer to
  `backend/eval/RESULTS_055.md` (bookkeeping only; does not change 055's requirements).

---

## Task 4: Make flip-exposed off-path tests hermetic  [AC-4]  (§7 — pin, never weaken)
- [ ] **`tests/unit/test_registry_writethrough.py`:** add
  `monkeypatch.setattr(registry_mod._config, "UPLOAD_SOURCE_RETENTION_ENABLED", False)` (match the test
  file's existing `registry_mod._config` alias) in
  `test_mark_terminal_deletes_upload_blob_on_turso` (it asserts the upload blob IS deleted — flag-OFF behavior)
  and in `test_mark_terminal_delete_failure_does_not_change_status` (it exercises the delete path). This
  restores the exact flag-OFF precondition each test asserts; ON-retention is covered by `test_source_retention.py`.
- [ ] Run the full suite; for every OTHER failure caused by the flip, pin the flag to its old value in that
  specific test (preserving intent) — suspects: `tests/unit/test_ingest_agent.py` (the `== _fake_parse_with_footer
  ().text` "byte-identical to today" assertion) and `tests/unit/test_clause_splitter_agent.py` (the splitter now
  adds `page_spans: None` to its returned partial when the flag is on), via
  `monkeypatch.setattr(<module>, "PDF_SOURCE_LOCATOR_ENABLED", False)`. Only pin tests whose INTENT is the
  off/plain behavior; never alter an on-path assertion, weaken, or delete a test.
- [ ] Record (in the commit message / here) which tests actually needed pinning, so the final diff is
  self-documenting against the AC-6 allow-list.

---

## Task 5: Backend gate  [AC-4, AC-6]
- [ ] `python -X utf8 -m pytest -q` → full suite green with the new defaults, including
  `test_config_chain_defaults.py` and the pinned off-path tests; no on-path (055/056) test regresses. Fix code,
  not tests, on any surprise (§7).
- [ ] `git diff --name-only main` matches the §0 allow-list — only `app/config.py`, the new/updated tests, the
  measurement note, the 055 Task 12 tick, and the 060 specs. No node/edge/`ContractState`/`specs/001`/migration/
  dependency/frontend change (AC-6).

---

## Task 6: Merge
- [ ] Backend gate green; diff scope matches §0. Rebase `main`, merge `feature/060-enable-source-locator-chain`,
  delete branch (`git-finish`). The chain is now ON by default; a deployment opts out via
  `PDF_SOURCE_LOCATOR_ENABLED=False` / `UPLOAD_SOURCE_RETENTION_ENABLED=False`.

---

*Per §1/§11, implementation happens only on `feature/060-enable-source-locator-chain`, opened after spec +
plan + tasks are all spec-reviewer-APPROVED. Config-default flip only — no node/edge/`ContractState`/migration/
dependency/frontend change; both flags stay env-overridable.*
