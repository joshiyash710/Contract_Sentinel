# Feature 055 — Technical plan: PDF clause source-locator capture (backend)

Branch: `feature/055-pdf-source-locator` (per constitution §11).

Derived from the approved `spec.md`. Backend-only. Capture a char→(page,bbox) map at ingest (PDF text layer),
thread each clause's character range through the splitter, stamp each clause record with a per-line
`source_locator`, and carry it as pass-through metadata into `ReportFinding`. **Amends `specs/001` FIRST
(§10).** No new node/edge; nodes 3–7 untouched. Reversible via `PDF_SOURCE_LOCATOR_ENABLED` (default False):
off ⇒ `extracted_text` byte-identical, no `page_spans`, no `source_locator`.

Owner decisions folded in: per-line bboxes + `pages` list (OQ-1); accept flag-on extraction diff + MEASURE
it before any flip (OQ-2); transient in-state `page_spans` cleared by the splitter (OQ-3).

## 0. Scope of change (files touched)
```
specs/001-contract-state-schema.md                         (AMEND FIRST — §10)
backend/app/config.py                                      (flag)
backend/app/graph/state.py                                 (source_locator doc + page_spans key)
backend/app/graph/nodes/parsers/__init__.py               (ParseResult.page_spans)
backend/app/graph/nodes/parsers/pdf_parser.py             (dict-based text+map when flag on)
backend/app/graph/nodes/ingest/text_cleaner.py            (offset-tracked strip variant + span remap)
backend/app/graph/nodes/ingest_agent.py                   (wire map + remap; write page_spans)
backend/app/graph/nodes/splitters/__init__.py             (ClauseBoundary.char_start/char_end)
backend/app/graph/nodes/splitters/regex_splitter.py       (set char ranges)
backend/app/graph/nodes/splitters/llm_refiner.py          (thread ranges through grouping; None on text-emit)
backend/app/graph/nodes/clause_splitter_agent.py          (_renumber copy; _build_return stamp; clear map)
backend/app/graph/nodes/renderers/report_assembler.py     (copy source_locator → ReportFinding)
backend/app/models/report.py                              (ReportFinding.source_locator)
backend/tests/...                                          (new/updated unit tests — §8)
frontend/src/lib/api/types.ts                             (ReportFinding mirror: optional source_locator)
specs/055-pdf-source-locator/{spec,plan,tasks}.md
```
**NOT touched:** any CRAG/Self-RAG/RiskScore/Redline node; the graph builder/edges; `routes.py`; the
Markdown/PDF/email renderers; `docx_parser.py` (degrades via ParseResult default); any Alembic migration.
**`report-fields.test.ts` drift-lock:** NOT changed — following the `is_failsafe` precedent, `source_locator`
is added to the Python model + TS interface but NOT to the base `reportFixture` findings, so the lock's
`REPORT_FINDING_FIELDS` stays as-is and green (reviewer note 1; AC-13).

## 1. `specs/001` amendment (DONE FIRST — §10)
Add, with rationale (copied from spec §1/§2), to `001`:
- **Clause record:** `source_locator: Optional[dict]` — `{"pages": List[int], "spans": List[{"page": int,
  "bbox": [float,float,float,float]}]}` or `None`. Written by ClauseSplitterAgent; read by no graph node;
  serialized into the report. Flows via the existing `merge_nested_clause_dicts` reducer.
- **Top-level transient key:** `page_spans: Optional[List[dict]]` — the ingest→splitter char→bbox map (each
  `{"start","end","page","bbox"}`, offsets into the *cleaned* `extracted_text`); written by IngestAgent, set
  to `None` by ClauseSplitterAgent after it stamps locators. No reducer (last-write-wins).
`state.py` is updated to match in Task order (001 edit precedes the `state.py` edit).

## 2. `config.py`
- `PDF_SOURCE_LOCATOR_ENABLED: bool = _env_bool("PDF_SOURCE_LOCATOR_ENABLED", False)` (§3, D1). Re-exposed
  module-level where read (pdf_parser, ingest_agent, clause_splitter_agent) per the monkeypatch pattern.

## 3. `parsers/__init__.py` + `pdf_parser.py` — dict-based text+map (AC-1/AC-2)
- `ParseResult` gains `page_spans: Optional[List[dict]] = None` (defaulted → `docx_parser`/OCR unaffected).
- `pdf_parser._parse_pdf_inner`: re-expose `PDF_SOURCE_LOCATOR_ENABLED`. **Flag off** → current
  `"\n".join(page.get_text() for page in doc)` path, `page_spans=None` (byte-identical, AC-2). **Flag on,
  direct (non-OCR) path** → one `page.get_text("dict")` pass per page: walk blocks→lines→spans, appending
  each span's `text` to a buffer while recording `{"start": len_before, "end": len_after, "page": pageno,
  "bbox": [x0,y0,x1,y1]}` (span bbox from the dict). Join pages/lines so the buffer is the `extracted_text`
  and every char offset has a span (newlines inserted between lines/pages are recorded as gaps — no span,
  acceptable; a clause offset landing on a gap simply finds the nearest covering spans). OCR branch
  unchanged → `page_spans=None` (D2/EC-2). The OCR *decision* (`needs_ocr`) is computed on the dict-built
  text length, same thresholds.
- Note (OQ-2): the dict-built text may differ slightly from plain `get_text()`; that is accepted under the
  flag. The plan's §9 measurement step quantifies it before any default flip.

## 4. `text_cleaner.py` — offset-tracked strip + span remap (AC-6)
- Add `strip_document_chrome_tracked(text) -> tuple[str, list[tuple[int,int]]]`: same two-pass logic, but
  also records every removed `[start,end)` range in **original (pre-strip) coords** — both the mid-line
  `_EDGAR_FOOTER.sub` excisions and the whole-line/bare-page-number drops (including the trailing `\n`
  consumed by the line drop). Returns `(cleaned_text, deletions)` with `deletions` ascending, non-overlapping.
- Keep `strip_document_chrome(text) -> str` as a thin wrapper returning `strip_document_chrome_tracked(text)[0]`
  (byte-identical for the existing ingest caller when the locator flag is off).
- Add a pure `remap_spans(page_spans, deletions) -> list[dict]`: translate each span from original→cleaned
  coords. For a span `[s,e)`: if it lies fully inside any deletion → drop it; else
  `shift = sum(d1-d0 for (d0,d1) in deletions if d1 <= s)`, new span `start=s-shift, end=e-shift` (bbox/page
  unchanged). **Worked example:** original `"ABCDEF\n{footer}\nGHIJ"`; the footer line (orig `[7,34)` incl.
  its newline) is dropped → `deletions=[(7,34)]`, cleaned `"ABCDEF\nGHIJ"`; the "GHIJ" span orig `[34,38)`
  has `shift=34-7=27` → cleaned `[7,11)`, and `cleaned[7:11]=="GHIJ"`. ✓ (A footer span itself lies inside
  `[7,34)` → dropped.)

## 5. `ingest_agent.py` — wire + remap; write `page_spans` (AC-1/AC-2)
- Re-expose `PDF_SOURCE_LOCATOR_ENABLED`. Current success path does `extracted_text =
  strip_document_chrome(result.text)` when `INGEST_STRIP_DOCUMENT_CHROME_ENABLED`.
- **Flag on:** obtain `result.page_spans` (None for DOCX/OCR). If `INGEST_STRIP_DOCUMENT_CHROME_ENABLED`:
  `extracted_text, deletions = strip_document_chrome_tracked(result.text)` else `extracted_text, deletions
  = result.text, []`. Then `page_spans = remap_spans(result.page_spans, deletions) if result.page_spans
  else None`. Return `page_spans` in the partial dict (only when non-None). **Flag off / DOCX / OCR:**
  behavior exactly as today, no `page_spans` key (AC-2/AC-11).
- This keeps all downstream offsets in **cleaned-text coords** (one translation, here), so the splitter just
  intersects clause ranges with `page_spans` directly.

## 6. Splitter — thread char ranges (AC-3/AC-4/AC-5/EC-9)
- `splitters/__init__.py`: `ClauseBoundary` gains `char_start: Optional[int] = None`,
  `char_end: Optional[int] = None` (defaulted → existing constructions compile; set explicitly below).
- `regex_splitter.py`: `_build_clauses_from_matches` already computes `start`/`end` per clause → set
  `char_start=start, char_end=end` (the raw marker span; `.strip()` only trims the stored `text`, the range
  still covers the clause region — AC-3). **Thread the offsets through `raw`:** today `raw` stores only
  `(clause_text, section_number)` and FILTERS empty clauses (`if clause_text:`), so the final
  `enumerate(raw, start=1)` index is decoupled from the match index — append `(clause_text, section_number,
  start, end)` to `raw` and read `start/end` from the tuple in the final `ClauseBoundary` build (do NOT zip
  the match index to the clause index). `_build_clauses_from_paragraph_splits` → set the chunk's
  `[positions[i], positions[i+1])`. The whole-text single-clause fallbacks → `char_start=0,
  char_end=len(text)`; the empty `[]` return is unchanged.
- `llm_refiner.py`: `_build_grouped_clause` — segments are `by_index[idx]`; set `char_start=min(s.char_start
  for s)`, `char_end=max(s.char_end for s)` over segments with non-None ranges (document order preserved by
  grouping), else None. Passthrough singleton keeps its segment's range. The text-re-emit `_parse_response`
  path → `char_start=char_end=None` (rewritten text, offsets unrecoverable — AC-5).
- `clause_splitter_agent.py::_renumber` — copy `char_start`/`char_end` into the rebuilt `ClauseBoundary`
  (EC-9; else locators are lost after a truncation re-clamp).

## 7. `clause_splitter_agent.py` — stamp `source_locator`, clear the map (AC-7/AC-8/AC-9/AC-11)
- `clause_splitter_agent(state)`: read `page_spans = state.get("page_spans")`. Pass it into `_build_return`.
- `_build_return`: for each clause, when the flag is on AND `page_spans` AND `c.char_start`/`c.char_end` are
  set, compute `source_locator` via a pure helper `locator_from_range(char_start, char_end, page_spans)`:
  collect every span whose `[start,end)` intersects `[char_start,char_end)`; build
  `spans=[{"page","bbox"} ...]` (in page/offset order), `pages=` sorted-unique of their pages; empty → None
  (EC-4/EC-5). Set `clauses_dict[clause_id]["source_locator"] = source_locator` (or None).
- The node's returned partial dict includes **`page_spans: None`** to clear the transient map (AC-9), but
  ONLY when the flag is on (off ⇒ don't add the key at all → byte-identical). This applies to the
  success + short-text paths (which call `_build_return`); the `ingest_error` and empty-`extracted_text`
  early returns never had `page_spans` set upstream, so they need no clear (AC-9 is only meaningful where a
  map was produced).
- Flag off / no page_spans (DOCX/OCR) ⇒ no `source_locator` written (stays absent → treated as None, AC-11).

## 8. Report model + frontend mirror (AC-10/AC-13)
- `report_assembler.assemble_report`: add `source_locator=record.get("source_locator")` to the
  `ReportFinding(...)` construction (pass-through; None-safe).
- `models/report.py`: `ReportFinding` gains `source_locator: Optional[dict] = None` (additive, back-compat).
- `frontend/src/lib/api/types.ts`: `ReportFinding` interface gains `source_locator?: { pages: number[];
  spans: { page: number; bbox: number[] }[] } | null;`. **Do not** add it to the base `reportFixture`
  findings or `REPORT_FINDING_FIELDS` (is_failsafe precedent) → drift-lock untouched/green.

## 9. Tests (TDD — write first, confirm failing, then implement) + measurement
### Backend (pytest; PyMuPDF local; LLM mocked; reportlab builds fixture PDFs)
- **parser** (new `test_pdf_source_locator.py`): AC-1 (flag on → page_spans cover text; a known word's
  offset → correct page + in-mediabox bbox), AC-2 (flag off → extracted_text == plain path, page_spans None).
- **text_cleaner** (extend): `strip_document_chrome_tracked` returns correct deletions; `remap_spans` matches
  the §4 worked example; `strip_document_chrome` wrapper byte-identical (AC-6).
- **regex_splitter** (extend): char_start/char_end recover the clause region; fallbacks correct (AC-3).
- **llm_refiner** (extend): grouping merge → min/max range; passthrough keeps range; text-emit → None (AC-4/5).
- **clause_splitter_agent** (extend): AC-7 (source_locator shape: pages ascending-unique, spans⊆pages), AC-8
  (cross-page clause → ≥2 pages), AC-9 (returned state page_spans is None), EC-9 (_renumber keeps ranges),
  AC-11 (DOCX/OCR path → all None, no error).
- **assembler/model** (extend): AC-10 (source_locator copied clause→ReportFinding; unread by nodes 3–7 — a
  mocked full run leaves it equal to what the splitter stamped), AC-13 (ReportFinding has the field).
- **state/001** — AC-12. NOTE: there is **no** automated "schema-transcription test" today — `state.py`'s
  "verbatim transcription of 001" is only a docstring convention (`state.py` module docstring), enforced
  manually. So AC-12 is satisfied by: (1) amending `001` FIRST (§10); (2) keeping `state.py` consistent with
  it — add the `page_spans` top-level key to the `ContractState` TypedDict and document `source_locator` in
  the clause-record comment block (the clause record is an untyped `Dict[str,Any]`, so `source_locator` is a
  comment, like the other per-clause fields, not an annotation); and (3) a **NEW** minimal test
  `tests/unit/test_state_source_locator.py` asserting `"page_spans" in ContractState.__annotations__` (the
  new top-level key is really present). Do NOT try to "extend" a transcription test — none exists.
- Full suite green (AC-14).
### Frontend
- `tsc --noEmit` green (types-only); `report-fields.test.ts` unchanged + green.
### Measurement (OQ-2, before any default flip — NOT a merge blocker)
- A small offline script/run over the real corpus comparing flag-on dict-built `extracted_text` vs the plain
  path, reporting the diff rate + whether clause counts change. Recorded for the eventual flip decision.

## 10. Verification gate (all offline)
- Backend `python -X utf8 -m pytest -q` full suite green; frontend `npm test` + `npx tsc --noEmit` + eslint +
  `npm run build` green. `git diff --name-only main` == §0 allow-list (no node3-7/builder/routes/renderers/
  migration change). Flag ships OFF → the whole pipeline is byte-identical by default; live/visual value
  arrives with 057.

## 11. Risks / limitations
- **Extraction diff (OQ-2):** flag-on text may differ from plain extraction; mitigated by default-off +
  the §9 measurement before flipping.
- **Chrome-strip remap** is the subtlest piece (two deletion kinds); covered by the §4 worked example + AC-6.
- **`page_spans` size** on a large doc rides one checkpoint (post-ingest) then cleared (§6/D5); comparable to
  `extracted_text` already in state.
- **OCR/DOCX/text-emit** have no locator by design (degrade to None) — this is expected, not a gap.
- Metadata-only; nothing downstream reads it → zero analysis/accuracy risk.

## 12. Merge
Full backend + frontend gate green; diff scope matches §0. Rebase `main`, merge
`feature/055-pdf-source-locator`, delete branch (`git-finish`). Flag ships OFF; 056 (serve-original) + 057
(viewer) follow. Live smoke + default flip come with 057.
