# Feature 055 — PDF clause source-locator capture — Implementation Tasks

Reference documents:
- Spec: `specs/055-pdf-source-locator/spec.md`
- Plan: `specs/055-pdf-source-locator/plan.md`
- Constitution: `specs/000-constitution.md` (**§1/§11** branch workflow; **§7** TDD / never weaken a test;
  **§10** spec-first change — amend 001 BEFORE code; **§2** no new node/edge; **§3** named config; **§5/§6**)

Backend paths relative to `backend/`; frontend relative to `frontend/`.

**Workflow reminders:**
- **Amend `specs/001` FIRST (§10)**, then `state.py` to match — before any other code.
- **No new node/edge; nodes 3–7 are pure pass-through** (they only write their own keys; the
  `merge_nested_clause_dicts` reducer `{**existing,**new}` preserves `source_locator`). Do NOT touch any
  CRAG/Self-RAG/RiskScore/Redline node, the graph builder, `routes.py`, the md/pdf/email renderers, or add a
  migration (`page_spans` is transient in-state; `source_locator` rides the already-JSON clauses dict).
- **Reversible flag `PDF_SOURCE_LOCATOR_ENABLED`, default `False`** — off ⇒ `extracted_text` byte-identical,
  no `page_spans`, no `source_locator`.
- **Scope allow-list (AC-14)** = the files in plan §0 + the new tests below. Nothing else.
- **TDD (§7):** write each layer's tests first, confirm FAIL, then implement. Never weaken a surprised test.
- **Owner decisions:** per-line bboxes + `pages` list; accept flag-on extraction diff (measured in Task 12);
  transient in-state `page_spans` cleared by the splitter.
- **Shapes:** `page_spans` entry `{"start","end","page","bbox":[x0,y0,x1,y1]}` (offsets into cleaned
  `extracted_text`). `source_locator` = `{"pages":[int...], "spans":[{"page":int,"bbox":[4 floats]}...]}` or None.

---

## Task 0: Branch
- [ ] From up-to-date `main` (`git checkout main && git pull`), create `feature/055-pdf-source-locator`
  (`git-start`). Commit the APPROVED spec/plan/tasks on the branch.

**Verify:** `git branch --show-current` → `feature/055-pdf-source-locator`.

---

## Task 1: Amend 001 + state.py (§10 FIRST)  [AC-12]
- [ ] **[MODIFY] `specs/001-contract-state-schema.md`** — add, with rationale (copy from spec §1/§2): the
  clause-record field `source_locator: Optional[dict]` (`{"pages":[int],"spans":[{"page","bbox"}]}` or None;
  written by ClauseSplitterAgent, read by no graph node, serialized into the report) and the transient
  top-level key `page_spans: Optional[List[dict]]` (ingest→splitter char→bbox map, cleaned-text coords;
  written by IngestAgent, set None by ClauseSplitterAgent; no reducer).
- [ ] **[MODIFY] `app/graph/state.py`** — add `page_spans: Optional[List[Dict[str, Any]]]` to the
  `ContractState` TypedDict (top-level annotation) and document `source_locator` in the clause-record
  comment block (the clause record is `Annotated[Dict[str, Dict[str, Any]], merge_nested_clause_dicts]`, so
  `source_locator` is a comment like the other per-clause fields, NOT an annotation).
- [ ] **[NEW] `tests/unit/test_state_source_locator.py`** — assert `"page_spans" in ContractState.__annotations__`.
  (There is NO pre-existing "schema-transcription test" to extend.)

**Verify:** the new test passes; 001 and state.py agree.

---

## Task 2: `config.py`  [AC-2, D1]
- [ ] Add `PDF_SOURCE_LOCATOR_ENABLED: bool = _env_bool("PDF_SOURCE_LOCATOR_ENABLED", False)`.

---

## Task 3: Write the failing backend tests first  [AC-1..AC-11]
Create/extend these (they FAIL until Tasks 4–9). Use `reportlab` to build tiny text PDFs with known text at
known coordinates; mock the splitter LLM as existing tests do; enable the flag per-test via
`monkeypatch.setattr(<module>, "PDF_SOURCE_LOCATOR_ENABLED", True)`.

- [ ] **[NEW] `tests/unit/test_pdf_source_locator.py`** — AC-1 (flag on: `parse_pdf` returns `page_spans`
  covering `extracted_text`; a known word's char offset → correct `page` + bbox within the page media box),
  AC-2 (flag off: `extracted_text` == current plain `"\n".join(page.get_text())` output; `page_spans` None).
- [ ] **[EXTEND] the text_cleaner test** — `strip_document_chrome_tracked` returns correct `(cleaned,
  deletions)` (both mid-line excision + whole-line/bare-page drops, original coords); `remap_spans` matches
  the plan §4 worked example (GHIJ orig `[34,38)` + `deletions=[(7,34)]` → cleaned `[7,11)`; footer span
  dropped); `strip_document_chrome(text)` wrapper is byte-identical (AC-6).
- [ ] **[EXTEND] regex_splitter test** — `char_start`/`char_end` recover the clause region
  (`cleaned_text[char_start:char_end]` ⊇ clause); paragraph + single-clause fallbacks set valid ranges
  (AC-3).
- [ ] **[EXTEND] llm_refiner test** — grouping merge → `char_start=min`, `char_end=max` of grouped segments;
  passthrough singleton keeps its range; text-re-emit path (`CLAUSE_SPLITTER_LLM_EMIT_TEXT=True`) →
  `char_start=char_end=None` (AC-4/AC-5).
- [ ] **[EXTEND] clause_splitter_agent test** — AC-7 (`source_locator` shape: `pages` ascending-unique,
  every span page ∈ pages), AC-8 (cross-page clause → `len(pages) >= 2`), AC-9 (returned state `page_spans`
  is None on the success/short-text paths), EC-9 (`_renumber` preserves char ranges), AC-11 (DOCX + OCR
  paths → all `source_locator` None, no error).
- [ ] **[EXTEND] report assembler/model test** — AC-10 (`source_locator` copied clause→`ReportFinding`; a
  mocked full run leaves it == what the splitter stamped), AC-13 (`ReportFinding` has the optional field).
- [ ] Run `python -X utf8 -m pytest -q` → CONFIRM the new assertions FAIL (symbols/fields/logic absent).

**Verify:** the new/extended tests fail for the expected reasons.

---

## Task 4: ParseResult + pdf_parser  [AC-1, AC-2]
- [ ] **[MODIFY] `app/graph/nodes/parsers/__init__.py`** — `ParseResult` gains
  `page_spans: Optional[List[dict]] = None` (defaulted → docx/OCR unaffected).
- [ ] **[MODIFY] `app/graph/nodes/parsers/pdf_parser.py`** — re-expose `PDF_SOURCE_LOCATOR_ENABLED`
  module-level. Flag OFF → current plain path, `page_spans=None` (AC-2). Flag ON + non-OCR → one
  `page.get_text("dict")` pass per page: append each span's `text` to a buffer, recording
  `{"start":len_before,"end":len_after,"page":pageno,"bbox":[x0,y0,x1,y1]}`; the buffer becomes
  `extracted_text` and `page_spans` is the span list. OCR branch unchanged → `page_spans=None`. `needs_ocr`
  computed on the built text length (same thresholds).

---

## Task 5: text_cleaner — tracked strip + remap  [AC-6]
- [ ] **[MODIFY] `app/graph/nodes/ingest/text_cleaner.py`** — add
  `strip_document_chrome_tracked(text) -> tuple[str, list[tuple[int,int]]]` (same two-pass logic; also record
  every removed `[start,end)` in ORIGINAL coords — mid-line excisions + whole-line/bare-page drops incl. the
  consumed `\n`; ascending, non-overlapping). Make `strip_document_chrome(text) -> str` a thin wrapper
  returning `[0]` (byte-identical for existing callers). Add pure
  `remap_spans(page_spans, deletions) -> list[dict]`: drop any span fully inside a deletion; else
  `shift = sum(d1-d0 for (d0,d1) in deletions if d1 <= s)`, new `start=s-shift,end=e-shift` (bbox/page kept).

---

## Task 6: ingest_agent — wire + remap  [AC-1, AC-2, AC-11]
- [ ] **[MODIFY] `app/graph/nodes/ingest_agent.py`** — re-expose `PDF_SOURCE_LOCATOR_ENABLED`. Flag ON: get
  `result.page_spans`; if `INGEST_STRIP_DOCUMENT_CHROME_ENABLED` use
  `extracted_text, deletions = strip_document_chrome_tracked(result.text)` else `(result.text, [])`; set
  `page_spans = remap_spans(result.page_spans, deletions) if result.page_spans else None`; include
  `page_spans` in the returned partial dict only when non-None. Flag OFF / DOCX / OCR → exactly today's
  path, no `page_spans` key.

---

## Task 7: Splitter — thread char ranges  [AC-3, AC-4, AC-5, EC-9]
- [ ] **[MODIFY] `app/graph/nodes/splitters/__init__.py`** — `ClauseBoundary` gains
  `char_start: Optional[int] = None`, `char_end: Optional[int] = None` (defaulted).
- [ ] **[MODIFY] `app/graph/nodes/splitters/regex_splitter.py`** — thread `(start,end)` through the `raw`
  tuple in `_build_clauses_from_matches` (today `raw` holds `(clause_text, section_number)` and filters empty
  clauses — append `(clause_text, section_number, start, end)` and read start/end in the final build; do NOT
  zip match index to clause index). Set ranges in `_build_clauses_from_paragraph_splits`
  (`[positions[i],positions[i+1])`) and the whole-text single-clause fallbacks (`0,len(text)`).
- [ ] **[MODIFY] `app/graph/nodes/splitters/llm_refiner.py`** — in `_build_grouped_clause` set
  `char_start=min(...)`, `char_end=max(...)` over grouped segments' non-None ranges (passthrough keeps its
  range); in the text-re-emit `_parse_response` set `char_start=char_end=None`.
- [ ] **[MODIFY] `app/graph/nodes/clause_splitter_agent.py` `_renumber`** — copy `char_start`/`char_end` into
  the rebuilt `ClauseBoundary` (EC-9).

---

## Task 8: clause_splitter_agent — stamp + clear  [AC-7, AC-8, AC-9, AC-11]
- [ ] **[MODIFY] `app/graph/nodes/clause_splitter_agent.py`** — re-expose `PDF_SOURCE_LOCATOR_ENABLED`. Read
  `page_spans = state.get("page_spans")`; pass it into `_build_return`. Add a pure helper
  `locator_from_range(char_start, char_end, page_spans)` → collect spans intersecting `[char_start,char_end)`
  into `{"pages":sorted-unique, "spans":[{"page","bbox"}...]}`; empty/None → None. In `_build_return`, when
  the flag is on AND `page_spans` AND the clause has `char_start`/`char_end`, set
  `clauses_dict[cid]["source_locator"]` (else None). On the success + short-text paths, include
  `page_spans: None` in the returned dict (clear the map, AC-9) ONLY when the flag is on. The `ingest_error`
  / empty-`extracted_text` early returns are unchanged (no map was set).

---

## Task 9: Report model + frontend mirror  [AC-10, AC-13]
- [ ] **[MODIFY] `app/graph/nodes/renderers/report_assembler.py`** — add
  `source_locator=record.get("source_locator")` to the `ReportFinding(...)` construction.
- [ ] **[MODIFY] `app/models/report.py`** — `ReportFinding` gains `source_locator: Optional[dict] = None`.
- [ ] **[MODIFY] `frontend/src/lib/api/types.ts`** — `ReportFinding` interface gains
  `source_locator?: { pages: number[]; spans: { page: number; bbox: number[] }[] } | null;`. Do NOT add it
  to the base `reportFixture` findings or `REPORT_FINDING_FIELDS` (is_failsafe precedent → drift-lock green).

---

## Task 10: Backend gate  [AC-1..AC-12, AC-14]
- [ ] `python -X utf8 -m pytest -q` → new/extended tests pass AND the full suite stays green (CRAG / self_rag
  / risk / redline / report / ingest / splitter tests unchanged except where they assert new behavior). Fix
  code, not tests, on any surprise (§7).

**Verify:** full backend suite green.

---

## Task 11: Frontend gate  [AC-13, AC-14]
- [ ] `npx tsc --noEmit` clean; `npm test` green (incl. the unchanged `report-fields.test.ts` drift-lock);
  eslint no new errors; `npm run build` compiles.
- [ ] `git diff --name-only main` matches plan §0 allow-list (no node3-7 / builder / routes / renderer /
  migration change).

---

## Task 12: Measurement (OQ-2 — NOT a merge blocker)
- [x] A small offline run over the real corpus comparing flag-on dict-built `extracted_text` vs the plain
  path (diff rate + whether clause counts change). Record it for the eventual default-flip decision. Does not
  gate the merge (flag ships OFF). **DONE (feature 060):** `backend/eval/measure_055_extraction_diff.py` over
  the 30-contract corpus → min 99.71% char similarity, 100% whitespace-collapsed, 0/30 clause-count change.
  Recorded in `backend/eval/RESULTS_055.md`; the measurement gated the 060 default-flip.

---

## Task 13: Merge
- [ ] Full backend + frontend gate green; diff scope confirmed. Rebase `main`, merge
  `feature/055-pdf-source-locator`, delete branch (`git-finish`). Flag ships OFF; 056 (serve-original) + 057
  (viewer) follow; live smoke + default flip come with 057.

---

*Per §1/§10/§11, implementation happens only on `feature/055-pdf-source-locator`, opened after spec + plan +
tasks are all spec-reviewer-APPROVED, with 001 amended FIRST. Backend metadata-capture only — no graph/edge
change, nodes 3–7 pure pass-through, no migration; flag ships OFF (byte-identical default).*
