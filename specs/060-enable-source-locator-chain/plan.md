# Feature 060 — Technical plan: enable the source-locator traceability chain by default

Branch: `feature/060-enable-source-locator-chain` (per constitution §11).

Derived from the approved `spec.md`. A **config-default flip only**: `PDF_SOURCE_LOCATOR_ENABLED` and
`UPLOAD_SOURCE_RETENTION_ENABLED` from `False`→`True` in `app/config.py`, activating the already-merged
055→056→057 chain now that the 055 Task 12 extraction-diff measurement is clean (raw min 99.71%,
whitespace-collapsed 100%, 0/30 clause-count change). **No node/edge/`ContractState` change, no migration,
no dependency, no frontend production code.** Both flags stay env-overridable and reversible (§3).

## 0. Scope of change (files touched)
```
backend/app/config.py                              (flip the two defaults False→True)
backend/eval/RESULTS_055.md                        (NEW — record the Task 12 measurement, AC-5)
backend/eval/measure_055_extraction_diff.py        (already added — the measurement tool; no change)
backend/tests/unit/test_config_chain_defaults.py   (NEW — AC-1/AC-2/AC-3 default-resolution tests)
backend/tests/unit/test_registry_writethrough.py   (pin the flag False in the 2 delete-path tests, §7)
backend/tests/...                                   (pin the flag in any other flip-exposed off-path test)
specs/055-pdf-source-locator/tasks.md              (tick Task 12 + one-line pointer to RESULTS_055.md)
specs/060-enable-source-locator-chain/{spec,plan,tasks}.md
```
**NOT touched:** any pipeline node / graph / builder / routes / renderer; the 055 `pdf_parser` /
`ingest_agent` / `clause_splitter_agent` logic; the 056 `registry.mark_terminal` / `/source` route logic;
`specs/001` / `ContractState`; any Alembic migration; `package.json` / any frontend source.

## 1. `config.py` — the flip (AC-1, AC-2, AC-3)
- Line ~297: `PDF_SOURCE_LOCATOR_ENABLED: bool = _env_bool("PDF_SOURCE_LOCATOR_ENABLED", True)`.
- Line ~304: `UPLOAD_SOURCE_RETENTION_ENABLED: bool = _env_bool("UPLOAD_SOURCE_RETENTION_ENABLED", True)`.
- Only the `_env_bool` default argument changes (`False`→`True`). The env-override path is untouched, so a
  deployment setting either var to a falsey string still resolves `False` (AC-3). Update the inline comments
  that currently say "default … False / flipped on when 057 ships" to reflect the now-on default + the
  060 rationale (the live value is on by default; override to opt out).

## 2. Record the measurement (AC-5)
- **NEW `backend/eval/RESULTS_055.md`** — a short note: the command run
  (`.venv/Scripts/python.exe eval/measure_055_extraction_diff.py`), corpus (`backend/eval/corpus`, n=30),
  and the aggregate result (raw char similarity mean 99.97% / median 99.98% / **min 99.71%**;
  whitespace-collapsed similarity 100.00% on every doc; **0/30** regex clause-count change), plus the
  conclusion: the dict path is content-identical to the plain path and does not change segmentation →
  flipping `PDF_SOURCE_LOCATOR_ENABLED` on by default is safe. Mirrors the existing `eval/RESULTS_041.md`
  precedent.
- `specs/055-pdf-source-locator/tasks.md` Task 12 → checked, with a one-line pointer to
  `backend/eval/RESULTS_055.md` (bookkeeping only; does not change 055's requirements).

## 3. New default-resolution tests (AC-1, AC-2, AC-3) — TDD, write first
**NEW `backend/tests/unit/test_config_chain_defaults.py`.** `app.config` resolves `_env_bool` at import, so
assert the default by reloading the module with the env var controlled (pattern: `monkeypatch.delenv(...,
raising=False)` / `monkeypatch.setenv(...)` then `importlib.reload(app.config)`; reload once more in a
`finally`/fixture so later tests see the real module):
- **AC-1:** env var `PDF_SOURCE_LOCATOR_ENABLED` unset → reloaded `app.config.PDF_SOURCE_LOCATOR_ENABLED is
  True`.
- **AC-2:** env var `UPLOAD_SOURCE_RETENTION_ENABLED` unset → reloaded constant `is True`.
- **AC-3:** with each env var set to `"False"` → reloaded constant `is False` (override still wins).
These FAIL before §1 (default resolves False) and pass after. Guard the reload so it cannot leak a mutated
`app.config` into the rest of the suite (restore by reloading with the original `os.environ`).

## 4. Make flip-exposed off-path tests hermetic (AC-4) — §7: pin, never weaken
Flipping the defaults changes which branch runs for tests that exercised the flagged paths **without**
setting the flag. The dedicated 055/056 suites already monkeypatch the flag for BOTH states
(`test_pdf_source_locator.py` sets it True/False per case; `test_source_retention.py` sets it True/False per
case) and are unaffected. The confirmed and suspected off-path dependents:
- **CONFIRMED — `backend/tests/unit/test_registry_writethrough.py`:**
  `test_mark_terminal_deletes_upload_blob_on_turso` asserts the upload blob IS deleted on terminal
  (`calls == [("/tmp/contract.pdf", "upload_blobs")]`) and relied on the old default-False retention; with
  retention now on by default the delete is skipped and it fails. Add
  `monkeypatch.setattr(reg_mod._config, "UPLOAD_SOURCE_RETENTION_ENABLED", False)` so the test exercises the
  delete (flag-off) behavior it is asserting. Same pin in
  `test_mark_terminal_delete_failure_does_not_change_status` (it exercises the delete path). This is making
  the test hermetic to the behavior it targets — not weakening it (§7).
- **SUSPECTS to verify by running the suite — `test_ingest_agent.py` (e.g. the `== _fake_parse_with_footer()
  .text` "byte-identical to today" assertion) and `test_clause_splitter_agent.py` (return-dict shape — the
  splitter now adds `page_spans: None` to its returned partial when the flag is on).** If either relies on
  the default-False path, pin `PDF_SOURCE_LOCATOR_ENABLED=False` in that specific test (via its module's
  re-exposed constant, the same `monkeypatch.setattr(<mod>, "PDF_SOURCE_LOCATOR_ENABLED", False)` seam the
  existing locator tests use). Only pin tests whose INTENT is the off/plain behavior; do not alter any
  on-path assertion.
- **Procedure:** run the full suite after §1; for every failure caused by the flip, pin the flag to its old
  value in that test (preserving intent). Fix tests, never the measured production behavior (§7).

## 5. Verification gate (all offline)
- `python -X utf8 -m pytest -q` → full backend suite green with the new defaults, including the new
  `test_config_chain_defaults.py` and the pinned off-path tests; no on-path (055/056) test regresses (AC-4).
- `git diff --name-only main` == the §0 allow-list — only `app/config.py`, the new/updated tests, the
  measurement note, the 055 Task 12 tick, and the 060 specs. No node/edge/`ContractState`/migration/
  dependency/frontend change (AC-6).
- No Ollama / network needed (the measurement is a one-off already run; its result is recorded, not re-run
  in CI).

## 6. Correctness / constitution
- **§2/§10:** no node/edge/`ContractState` change, no migration — only two default literals flip; the
  flagged code paths are byte-unchanged.
- **§3:** both remain named, env-overridable config constants; the default-value flip is the sanctioned
  tuning seam, justified by the §6/RESULTS_055 measurement.
- **§036:** retained uploads stay Fernet-encrypted at rest (unchanged); nothing new stored in plaintext.
- **§019:** `/source` stays `require_auth` + owner-scoped; retention does not widen access.
- **§7:** off-path tests are pinned to the behavior they assert, never weakened or deleted.

## 7. Risks / limitations
- **Storage growth (retention now on by default):** keep-forever (056 D1); Turso free tier 5 GB, contracts
  small, no GC. Reversible via `UPLOAD_SOURCE_RETENTION_ENABLED=False`.
- **Whitespace drift from the dict path:** measured, content-identical, 0 clause-count change (§6); accepted.
- **Not retroactive:** pre-flip jobs have no locators and (on Turso) may have no retained source → the 057
  viewer shows "original no longer available" for them (EC-3). Expected.
- **Config reload in tests:** the default-resolution tests must restore `app.config` so they don't leak a
  mutated module into the rest of the suite (§3 of this plan addresses it).

## 8. Merge
Full backend gate green; diff scope matches §0. Rebase `main`, merge
`feature/060-enable-source-locator-chain`, delete branch (`git-finish`). The chain is now ON by default; a
deployment opts out via the two env vars.
