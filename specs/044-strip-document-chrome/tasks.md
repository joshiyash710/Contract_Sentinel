# Feature 044 — Strip document-chrome artifacts — Implementation Tasks

Reference documents:
- Spec: `specs/044-strip-document-chrome/spec.md`
- Plan: `specs/044-strip-document-chrome/plan.md`
- Constitution: `specs/000-constitution.md` (**§2** no graph/edge/state change; **§3** config flag +
  inline fixed patterns; **§5** IngestAgent partial-update; **§7** TDD + never weaken a test;
  **§1/§11** branch-gated)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **TDD (§7):** cleaner + integration tests written FAILING first, then implementation makes them
  green. Pin any surprised existing ingest test (never weaken).
- **Scope = exactly 6 files (AC-6).** `git diff --name-only main` must show only `app/config.py`,
  `app/graph/nodes/ingest/text_cleaner.py` (NEW, + its package `__init__.py`),
  `app/graph/nodes/ingest_agent.py`, `tests/unit/test_text_cleaner.py` (NEW),
  `tests/unit/test_ingest_agent.py`, `tests/unit/test_config.py` (+ `specs/044-**`). No
  graph/edge/`ContractState`/migration/Self-RAG/frontend change.
- **Conservative / bias-to-under-strip (D2):** only remove lines/spans matching the full EDGAR footer
  shape (company + SEC form id + `M/D/YYYY`). **Never** touch `[***]` redactions or prose containing
  "Source" (AC-3 negative controls are load-bearing).
- **Reversible (D3):** `INGEST_STRIP_DOCUMENT_CHROME_ENABLED=False` ⇒ byte-identical `extracted_text`.
- **Monkeypatch:** `ingest_agent.py` reads the flag by bare module name (mirrors its `_config` alias
  convention) so the reversibility test can patch it.
- All tests are **offline** (pure cleaner; ingest integration mocks the parser — no Ollama/IO).

---

## Task 0: Branch (done — confirm)
- [x] On `feature/044-strip-document-chrome`. spec.md + plan.md spec-reviewer-APPROVED. Commit
  spec/plan/tasks on the branch.

**Verify:** `git branch --show-current` → `feature/044-strip-document-chrome`.

---

## Task 1: Config flag (§3)  [AC-5]
- [ ] **[MODIFY] `app/config.py`** — near the ingest constants add
  `INGEST_STRIP_DOCUMENT_CHROME_ENABLED: bool = True` with the plan §1 comment (reversible; when True,
  IngestAgent strips the EDGAR footer + immediately-adjacent bare page-number line before segmentation).

**Verify:** `python -c "import app.config as c; print(c.INGEST_STRIP_DOCUMENT_CHROME_ENABLED)"` → `True`.

---

## Task 2: Config validity test (red → green)  [AC-5]
- [ ] **[MODIFY] `tests/unit/test_config.py`** (FAIL first): assert
  `INGEST_STRIP_DOCUMENT_CHROME_ENABLED` is a `bool`. Task 1 makes it green.

**Verify:** `python -m pytest tests/unit/test_config.py -q` → PASS.

---

## Task 3: Cleaner — test (red) → implementation (green)  [AC-1..AC-4, AC-6, AC-7]
- [ ] **[NEW] `tests/unit/test_text_cleaner.py`** (FAIL first — module absent). Cases:
  - **AC-1/AC-2:** own-line footers for **`10-12B` (ARCONIC canonical — REQUIRED explicit case)**,
    `10-12G`, `8-K`, `10-Q`, `S-1`, `10-KA`, `EX-10.2`, `F-1`, `1-A` with assorted `M/D/YYYY` dates are
    removed; surrounding clause text intact.
  - **AC-3 negatives (load-bearing):** `"Source code shall be delivered to Buyer."` unchanged; a clause
    containing `[***]` unchanged; a bare `"12"` line **not** adjacent to a footer unchanged; prose
    `"…a Source of funds, Section 3, dated material."` unchanged.
  - **AC-4 / EC-2 mid-line:** `"9 Source: ARMSTRONG FLOORING, INC., 8-K, 1/7/2019 directors, officers"`
    → footer span excised, `"9  directors, officers"` remainder retained.
  - **EC-1 adjacency:** footer line + following lone `"12"` → both removed; same `"12"` with no adjacent
    footer → kept.
  - **AC-6 idempotence:** `strip(strip(t)) == strip(t)` for BOTH a whole-line case AND a mid-line case.
    **AC-7 determinism:** repeated calls identical. **EC-6:** empty/whitespace unchanged.
- [ ] **[NEW] `app/graph/nodes/ingest/__init__.py`** (empty package marker) + **`text_cleaner.py`** —
  implement `strip_document_chrome(text)` exactly per plan §2 (two passes: mid-line `_EDGAR_FOOTER.sub`
  excision recording `footer_line[i]`; then drop footer-emptied lines and bare page-number lines that
  are immediately adjacent to a footer-excised line). Use the plan's corrected `_SEC_FORM`
  (verified to match `10-12B`).

**Verify:** `python -m pytest tests/unit/test_text_cleaner.py -q` → PASS.

---

## Task 4: Wire-in to IngestAgent — test (red) → implementation (green)  [AC-5]
- [ ] **[MODIFY] `tests/unit/test_ingest_agent.py`** (new cases FAIL first): mock the parser so
  `result.text` contains an EDGAR footer line.
  - Flag ON → returned `extracted_text` has the footer stripped (and normal text preserved).
  - Monkeypatch `ingest_agent.INGEST_STRIP_DOCUMENT_CHROME_ENABLED = False` → `extracted_text ==
    result.text` (reversibility).
- [ ] **[MODIFY] `app/graph/nodes/ingest_agent.py`** per plan §3: import `strip_document_chrome` +
  alias `INGEST_STRIP_DOCUMENT_CHROME_ENABLED = _config.INGEST_STRIP_DOCUMENT_CHROME_ENABLED`; at the
  success return (~line 218) compute `extracted = strip_document_chrome(result.text)` when the flag is
  on, else `result.text`, and return it as `extracted_text`. Error paths (return `""`) untouched.

**Verify:** `python -m pytest tests/unit/test_ingest_agent.py -q` → PASS.

---

## Task 5: Full suite + scope gate  [AC-6]
- [ ] `python -m pytest -q` → GREEN. Pin any surprised existing ingest test with justification (never
  weaken).
- [ ] `git diff --name-only main` shows exactly the 6 allow-listed files (+ `specs/044-**`) — no
  graph/edge/`ContractState`/migration/Self-RAG/frontend change.

**Verify:** suite green; diff scope matches the plan §0 allow-list.

---

## Task 6: Merge
- [ ] Whole `pytest` green; diff scope confirmed. Rebase `main`, merge
  `feature/044-strip-document-chrome`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/044-strip-document-chrome`. Ingestion text-clean
only — no `ContractState`, no config threshold (a reversible bool flag + fixed inline patterns), no
graph/edge, no migration, no frontend. The cleaner is pure, deterministic, and idempotent; it only
removes recognized EDGAR chrome and never rewrites substantive text.*
