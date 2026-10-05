# Feature 055 — Spec: PDF clause source-locator capture (backend)

Status: DRAFT (pre spec-reviewer gate)
Branch: `feature/055-pdf-source-locator` (constitution §11).

> First of the "Suggestion 1 — clause traceability" chain (**055 capture → 056 serve-original endpoint →
> 057 in-workspace pdf.js viewer with click-to-highlight**). 055 is backend-only: it captures *where in the
> original PDF each clause physically sits* (page + bounding boxes) and carries it as pure metadata into the
> report. It renders nothing and serves nothing — 056/057 own the endpoint and the viewer. This is the
> longest pole of the chain.

## 1. Problem statement

ContractSentinel can tell a user *what* is risky in a clause, but not *where that clause lives in the
original contract*. The pipeline never retains physical position: `pdf_parser` extracts text with
`"\n".join(page.get_text() for page in doc)` (plain text — page/coordinate geometry discarded), the
`regex_splitter`/`llm_refiner` produce `ClauseBoundary(clause_id, text, position, section_number,
clause_type)` with no character offsets, and the `clauses[...]` record (`specs/001`) has no positional
field. So there is no way to point a reader from a finding back to the exact spot on the exact page of the
uploaded PDF — the prerequisite for the click-to-highlight viewer (057).

This feature captures, at ingest time, a **char-offset → (page, bounding-box)** map for the PDF, threads
each clause's character span through the splitter, and stamps each clause record with a **`source_locator`**
(the page(s) + bbox(es) the clause occupies). The data rides untouched through CRAG / Self-RAG / RiskScore
/ Redline into the report's `ReportFinding`, ready for 057 to draw highlights. PDF only; DOCX, scanned/OCR
PDFs, and the text-re-emit splitter path degrade cleanly to `source_locator = None` (no locator, no error).

### Position relative to the constitution
- **No new node or edge (§2 intact).** All work is inside the existing IngestAgent (node 1) and
  ClauseSplitterAgent (node 2); CRAG/Self-RAG/Risk/Redline/Report are untouched and pass the metadata
  through unread.
- **§10 Spec-First Change — this feature REQUIRES amending `specs/001-contract-state-schema.md` FIRST**
  (before any code), adding: (a) a new per-clause field `source_locator`, and (b) a new **transient**
  top-level state key `page_spans` (the char→bbox map, written by IngestAgent, consumed and then CLEARED by
  ClauseSplitterAgent — see §6/D5). Rationale is given in §2 and must be copied into the 001 amendment.
- **§5 Partial-update / §6 State minimality:** IngestAgent and ClauseSplitterAgent each still return only
  their own keys. `page_spans` is compact numeric metadata (not the PDF bytes), is comparable in magnitude
  to the `extracted_text` already carried in state, and is **cleared by the splitter** so it rides only the
  single ingest→splitter hop rather than the whole run. `source_locator` is small per-clause numeric data.
- Fully reversible via a config flag (§3): off ⇒ no `page_spans`, no `source_locator`, and `extracted_text`
  is byte-identical to today (plain `get_text()` extraction) — see D1.

## 2. Inputs and outputs

### IngestAgent (node 1) — capture the map
- **Input:** the PDF file (as today, after decrypt-to-temp).
- **New output (when `PDF_SOURCE_LOCATOR_ENABLED` and the doc is a text PDF):** a top-level state key
  **`page_spans`** — a compact list of span records over `extracted_text`, each
  `{"start": int, "end": int, "page": int, "bbox": [x0, y0, x1, y1]}` (0-based `start`/`end` char offsets
  into `extracted_text`; `page` 1-based; `bbox` in PDF points). When the flag is off, the doc is DOCX, or
  OCR was used, `page_spans` is absent/None (degrade).
- **Extraction change (flag on only):** `pdf_parser` builds `extracted_text` and `page_spans` **together
  from one `page.get_text("dict")` pass** so offsets and bboxes are exact by construction. When the flag is
  off it uses the current plain `"\n".join(page.get_text())` path — **byte-identical** (D1). The OCR branch
  is unchanged and never produces `page_spans` (image text has no reliable char geometry).
- **Chrome-strip offset-awareness (044):** `strip_document_chrome` runs on `extracted_text` and deletes
  EDGAR-footer spans/lines, shifting offsets. When the flag is on, the cleaner ALSO returns the ordered
  list of deleted `[start, end)` ranges (in pre-strip coords) so a cleaned-text offset can be translated
  back to the original span-map coords. Off ⇒ the cleaner's current single-string return is unchanged.

### ClauseSplitterAgent (node 2) — thread spans, stamp locators, clear the map
- **`ClauseBoundary` gains `char_start: Optional[int]` / `char_end: Optional[int]`** (the clause's half-open
  range in the cleaned `extracted_text`). `regex_splitter` sets them from the marker/paragraph span offsets
  it already computes (`text[start:end]`); the single-clause/paragraph fallbacks set the whole-range or
  None. `llm_refiner` **grouping mode** (default) sets a merged clause's range to `[min(seg.char_start),
  max(seg.char_end)]` of its grouped segments (document order is preserved); the **text-re-emit path**
  (`CLAUSE_SPLITTER_LLM_EMIT_TEXT=True`, non-default) sets them `None` (the LLM rewrote the text — offsets
  are unrecoverable → that path degrades to no locator). The 025 large-doc LLM-skip path keeps the regex
  ranges unchanged.
- **`_build_return` stamps `source_locator`** per clause: translate the clause's cleaned-text
  `[char_start, char_end)` back through the chrome-strip deletions to original-text coords, intersect with
  `page_spans`, and collect the covered pages + bboxes into
  `source_locator = {"pages": [int,...], "spans": [{"page": int, "bbox": [x0,y0,x1,y1]}, ...]}`
  (a clause may cross lines/pages → multiple spans). When `page_spans` is absent, or the clause has no
  `char_start/char_end`, `source_locator = None`.
- **The splitter clears the map:** its return includes `page_spans: None` so the transient map does not ride
  the rest of the graph (§6/D5).

### Downstream (nodes 3–7) — pass-through, unread
- `source_locator` lives on each `clauses[...]` record and flows via the existing `merge_nested_clause_dicts`
  reducer; CRAG/Self-RAG/RiskScore/Redline never read or write it. `assemble_report` copies it onto
  `ReportFinding.source_locator` (new optional field), and it appears in the report JSON. The Markdown/PDF
  renderers are unchanged (no visual use here — 057 consumes the JSON).

### 001 state-schema amendment (the exact additions)
- `clauses[clause_id].source_locator: Optional[dict]` — `{"pages": List[int], "spans": List[{"page": int,
  "bbox": [float,float,float,float]}]}`, or `None`. Populated by ClauseSplitterAgent; read by nobody in the
  graph; serialized into the report.
- Top-level `page_spans: Optional[List[dict]]` — the transient ingest→splitter char→bbox map; written by
  IngestAgent, set to `None` by ClauseSplitterAgent. (No reducer — last-write-wins.)

### Resolved decisions (inline)
- **D1 — Reversible master flag `PDF_SOURCE_LOCATOR_ENABLED` (§3), default `False`.** Off ⇒ plain
  extraction (byte-identical `extracted_text`), no `page_spans`, no `source_locator`, chrome-strip returns
  its current string. Shipped OFF per the project pattern; flip after a live smoke with 057.
- **D2 — PDF text layer only.** DOCX (no fixed geometry) and OCR/scanned PDFs (no reliable char geometry)
  produce `source_locator = None`. DOCX→PDF conversion is explicitly out of scope (owner decision: PDF-only;
  LibreOffice/docx2pdf infeasible on the Render free tier).
- **D3 — One extraction pass drives both text and map** (`get_text("dict")`) so offsets are exact; no
  fragile post-hoc substring matching. Accept that flag-on `extracted_text` MAY differ subtly from the
  plain path (measured in the plan); the flag keeps the default byte-identical.
- **D4 — Grouping-mode locator only.** The default index-grouping refiner preserves segment→offset linkage,
  so locators survive merges; the non-default text-re-emit path and any LLM failure → regex ranges or None.
- **D5 — `page_spans` is transient and cleared by the splitter** (bounds state growth to one hop, §6).
- **D6 — Metadata only; no graph/edge/renderer behavior change.** Nothing downstream reads `source_locator`;
  the report JSON merely carries it for 057.

## 3. Acceptance criteria

All backend, offline (pytest; PyMuPDF runs locally, no Ollama needed — the splitter LLM is mocked as in
existing tests). Fixtures use a tiny generated text PDF (reportlab, already a dependency) with known text
at known positions.

- **AC-1 (map captured):** with the flag on, parsing a 2-page text PDF yields `page_spans` whose records
  cover `extracted_text`; a char offset inside a known word maps to the correct `page` and a `bbox` whose
  coordinates fall within that page's media box.
- **AC-2 (flag off ⇒ byte-identical):** with `PDF_SOURCE_LOCATOR_ENABLED=False`, `extracted_text` equals the
  current plain-extraction output exactly, `page_spans` is absent/None, and no `source_locator` is set; all
  existing ingest/parser tests pass unchanged.
- **AC-3 (regex clause ranges):** `split_by_regex` output carries `char_start`/`char_end` matching the
  marker spans (`text[char_start:char_end]` recovers the pre-strip clause region); the single-clause and
  paragraph fallbacks set a valid whole-range (or None for the no-op fallback), never a wrong offset.
- **AC-4 (grouping merges ranges):** when the grouping refiner merges segments 2+3 into one clause, that
  clause's `char_start`/`char_end` span from segment 2's start to segment 3's end; a passthrough singleton
  keeps its segment's range.
- **AC-5 (text-re-emit degrades):** with `CLAUSE_SPLITTER_LLM_EMIT_TEXT=True`, clauses get
  `char_start/char_end = None` and `source_locator = None` (no wrong offsets from rewritten text).
- **AC-6 (chrome-strip offset remap):** for a PDF whose text contains an EDGAR footer that
  `strip_document_chrome` removes, a clause AFTER the removed footer still maps to the correct bbox (the
  deletion offsets are accounted for) — i.e. the locator points at the right page region, not one shifted by
  the removed bytes.
- **AC-7 (source_locator stamped + shape):** with the flag on, a validated clause's record has
  `source_locator = {"pages": [...], "spans": [{"page": int, "bbox": [4 floats]}, ...]}`, pages ascending
  and unique, every span page ∈ pages.
- **AC-8 (cross-page clause):** a clause spanning a page break has `len(pages) >= 2` and spans on each page.
- **AC-9 (map cleared after splitter):** ClauseSplitterAgent's returned state has `page_spans = None` (the
  transient map does not persist past node 2).
- **AC-10 (pass-through intact):** CRAG/Self-RAG/RiskScore/Redline neither read nor modify `source_locator`;
  after a full (mocked-LLM) run, each validated clause's `source_locator` is unchanged from what the
  splitter stamped, and `ReportFinding.source_locator` equals it in the assembled report JSON.
- **AC-11 (DOCX / OCR degrade):** a DOCX upload and an OCR-triggered PDF both complete with every clause
  `source_locator = None` and no error.
- **AC-12 (001 amended first):** `specs/001-contract-state-schema.md` documents `source_locator` and the
  transient `page_spans` with rationale; `state.py` matches 001; the state-schema transcription test passes.
- **AC-13 (report model + TS mirror):** `ReportFinding` (Pydantic) gains optional `source_locator`; the
  frontend `types.ts` mirror + the report-fields drift-lock are updated in lockstep and stay green. (No UI
  rendering — that's 057.)
- **AC-14 (full suite green):** the whole backend `pytest` suite passes on Windows; the frontend
  `tsc`/drift-lock pass (types-only change). Diff within the plan allow-list.

## 4. Edge cases
- **EC-1 — Flag off:** no `page_spans`/`source_locator`; byte-identical to today (AC-2).
- **EC-2 — OCR PDF / scanned:** OCR branch sets no `page_spans`; all `source_locator = None` (AC-11).
- **EC-3 — DOCX:** `docx_parser` unchanged; no `page_spans`; `source_locator = None` (AC-11).
- **EC-4 — Clause whose range falls entirely inside a removed chrome footer** (degenerate): after remap the
  translated range is empty → `source_locator = None` (never a crash, never a wrong bbox).
- **EC-5 — Empty / whitespace-only clause** (CRAG already guards): `char_start==char_end` or None →
  `source_locator = None`.
- **EC-6 — Large doc (025 LLM-skip, up to `MAX_CLAUSES_LIMIT`):** regex ranges are used directly; locators
  stamped from them; `page_spans` size is bounded by the document and cleared after node 2 (EC bound noted
  in §8 risks).
- **EC-7 — LLM refine fails / times out:** refiner returns regex clauses (which carry ranges) → locators
  still stamped from the regex ranges.
- **EC-8 — `get_text("dict")` returns a block with no spans / empty page:** that page contributes no span
  records; offsets stay consistent; clauses there get `source_locator = None`.
- **EC-9 — Re-clamp/renumber after truncation (`_renumber`):** must carry `char_start`/`char_end` through
  (today `_renumber` rebuilds `ClauseBoundary` — it must copy the new fields, else locators are lost).

## 5. Out of scope
- **Serving the original PDF to the browser** and **stopping the terminal-delete of uploads** — feature
  **056** (needs the owner's upload-retention decision).
- **The pdf.js viewer + click-to-highlight UI** — feature **057**.
- **DOCX locators / DOCX→PDF conversion** — permanently out of this chain (D2).
- **Rendering `source_locator` in the Markdown/PDF/email report** — not here (057 uses the JSON; a static
  PDF can't in-place-highlight the original anyway).
- **Any change to CRAG routing, Self-RAG, scoring, or redlining** — pass-through only (D6).
- **Re-OCR with coordinates** (e.g. Tesseract word boxes) — a possible future enhancement; OCR degrades to
  None here.

## 6. Evaluation (metrics to log)
No probabilistic/accuracy change — this feature captures positional metadata and performs no scoring or
retrieval. For operability and to measure D3's extraction-diff risk, log (debug/info): per-document
`page_spans` count, the count of clauses that got a non-None `source_locator` vs total (locator coverage),
and — in the plan's measurement step — whether flag-on `extracted_text` differs from the plain path on the
real corpus (so any segmentation impact is quantified before the default is ever flipped). No
recall/precision/false-flag metric is affected (nothing downstream reads the locator).

## 7. Open questions

All resolved by the owner (2026-10-05); they confirm the spec's primary design (already reflected in §2 /
the decisions / the ACs), so no scope change — recorded here for traceability:

- **OQ-1 — Locator granularity → RESOLVED: per-line bboxes + `pages` list** (the `source_locator =
  {"pages": [...], "spans": [{"page","bbox"}, ...]}` shape in §2; 057 draws tight per-span highlights).
- **OQ-2 — Extraction trade-off → RESOLVED: accept flag-on `extracted_text` may differ (D3); default
  (flag off) stays byte-identical; the plan MEASURES the flag-on vs plain-extraction diff on the real
  corpus before any default flip.**
- **OQ-3 — Map storage → RESOLVED: transient in-state `page_spans`, cleared by the splitter** (D5); the
  sidecar-blob alternative is not taken.

No open questions remain.
