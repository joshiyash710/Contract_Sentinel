# Professional report delivery (Phase 1: PDF report + SaaS HTML email) — Technical Plan

## Git Branch

`feature/030-professional-report-delivery` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

Implements `specs/030-professional-report-delivery/spec.md` — a **delivery-layer** upgrade (feature
010, post-terminal, **NOT a graph node**), with **no graph/edge/`ContractState` change** and **no
constitution amendment**. Two deliverables, rendered from the report artifacts Node 7 already writes:

- **Professional PDF report** — a new `reportlab` renderer turns the `ContractReport` (the `.json`
  sibling of `report_path`) into a branded `<document_id>.pdf`, which replaces the `.md` as the email
  attachment and is uploaded to Drive.
- **SaaS-style HTML email** — a branded `multipart/alternative` (plain-text fallback + HTML) body
  replacing the current plain-text email.

Resolved spec decisions (§6): **reportlab** engine; Drive uploads **PDF + json** (drop `md`); Drive CTA
`resource_ref` re-sourced from the **PDF** upload; **text/CSS wordmark "ContractSentinel"**, navy
accent. All new tunables are named config constants (§3), reversible (`MCP_REPORT_PDF_ENABLED=False`
+ `MCP_GMAIL_ATTACH_FORMAT="md"` restores pre-030 behavior). Node 7 still writes `.md` + `.json`
unchanged (so the `.md` remains available as the render-failure fallback — AC-13).

---

## 2. Files to Create / Modify

### Backend (`backend/`)
```
pyproject.toml                                     [MODIFY] add dependency: reportlab
app/config.py                                      [MODIFY] add delivery/branding constants (§3); MCP_DRIVE_UPLOAD_FORMATS ("md","json")→("pdf","json")
app/delivery/report_pdf.py                         [CREATE] reportlab renderer: render_report_pdf(report: ContractReport, out_path: Path) -> Path (pure, never network)
app/delivery/email_html.py                         [CREATE] build_email_bodies(document_id, report_or_summary, drive_ref) -> (subject, plain, html); HTML-escapes all finding text
app/delivery/models.py                             [MODIFY] GmailSendRequest gains html_body: Optional[str] = None
app/delivery/mcp_servers/gmail_server.py           [MODIFY] _build_mime → multipart/alternative (plain+html) + PDF attachment; send_message inputSchema gains html_body
app/delivery/mcp_clients/gmail_client.py           [MODIFY] send_report_via_gmail gains html_body param → GmailSendRequest
app/delivery/delivery_step.py                      [MODIFY] load full ContractReport; render PDF (gated); attach PDF / upload PDF+json; CTA ref from PDF; HTML bodies; .md fallback on render failure; never raise
tests/unit/test_report_pdf.py                      [CREATE] renderer tests (%PDF- header, brand/meta/summary/findings text, zero-findings, truncation, escaping)
tests/unit/test_email_html.py                      [CREATE] HTML/plain body tests (structure, summary numbers, CTA present/absent, HTML-escaping)
tests/unit/test_mcp_servers.py                     [MODIFY] gmail _build_mime now multipart/alternative + PDF attachment round-trip; html_body schema (existing gmail-attach/send tests here must still pass on the plain path)
tests/unit/test_mcp_clients.py                     [MODIFY] send_report_via_gmail gains html_body (KEYWORD/trailing param — positional subject/body positions unchanged)
tests/unit/test_delivery_step.py                   [MODIFY] PDF gen + attach/upload wiring, CTA-from-PDF, render-failure→.md fallback, reversibility, never-raise; UPDATE test_drive_uploads_configured_formats (default now uploads .pdf/.json not .md) and the positional-arg gmail-body assertions
tests/integration/test_delivery_integration.py     [MODIFY] happy-path assertion `md_path in uploaded_paths` (L106-107) → PDF/json path (Drive drops md); gmail attaches the PDF
tests/unit/test_config.py                          [MODIFY] assert the new constants; change MCP_DRIVE_UPLOAD_FORMATS `("md","json")`→`("pdf","json")`; UPDATE test_mcp_upload_formats_are_report_extensions (invariant now ⊆ {md, json, pdf} — pdf is a legitimate delivery-time format; do NOT delete the assertion)
```
No graph/edge/`ContractState`/migration/frontend/endpoint change. `report_agent.py` (Node 7) untouched.

---

## 3. Backend design

### 3.1 `pyproject.toml` + install
Add `reportlab` to the project dependencies (pure-Python wheel; no system/GTK/browser deps). Install
into the venv (`.venv/Scripts/python.exe -m pip install reportlab`). No other runtime dep.

### 3.2 `app/config.py` (§3 — named constants, reversible)
```python
MCP_DRIVE_UPLOAD_FORMATS: tuple = ("pdf", "json")   # was ("md","json") — PDF supersedes md for humans (Q2)
MCP_GMAIL_ATTACH_FORMAT: str = "pdf"                 # email attachment format; "md" restores pre-030
MCP_REPORT_PDF_ENABLED: bool = True                  # master toggle; False → pre-030 .md attachment + plain email
REPORT_PDF_CLAUSE_MAX_CHARS: int = 2000              # per-field caps (AC-7), mirror report char-cap discipline
REPORT_PDF_RATIONALE_MAX_CHARS: int = 1500
REPORT_PDF_REWRITE_MAX_CHARS: int = 4000
REPORT_BRAND_NAME: str = "ContractSentinel"
REPORT_BRAND_ACCENT_HEX: str = "#1e293b"             # professional navy (slate-800)
REPORT_BRAND_FOOTER: str = "Automated contract-risk analysis — review with qualified counsel."
```
`MCP_GMAIL_ATTACH_REPORT` (existing) stays the on/off attach toggle; the new `MCP_GMAIL_ATTACH_FORMAT`
only selects which file. No engine-selector constant — only reportlab is implemented (spec §6-Q1's
`MCP_REPORT_PDF_ENGINE` is unnecessary with a single engine; note this in the plan, not a silent drop).

### 3.3 `app/delivery/report_pdf.py` (CREATE — reportlab renderer)
- `render_report_pdf(report: ContractReport, out_path: Path) -> Path` — pure; no network; no
  `ContractState`. Uses `reportlab.platypus` (`SimpleDocTemplate`, `Paragraph`, `Table`, `Spacer`,
  colored `TableStyle`/severity chips) + `reportlab.lib` styles/colors.
- Layout: (1) **branded header** band — `REPORT_BRAND_NAME` wordmark on the accent color, tagline;
  (2) **document metadata** — `original_filename`, `generated_at`/`uploaded_at`, ocr flag; (3)
  **risk-summary band** — total clauses, validated findings, clean clauses, and high/medium/low counts
  as colored chips; (4) **per-finding sections** — for each `ReportFinding`: severity chip (color per
  `risk_level`: high=red, medium=amber, low=slate), `clause_type` + `section_number`, `clause_text`,
  `risk_rationale`, and when `suggested_rewrite` present a **before→after** block; evidence reference
  count/source. (5) footer with `REPORT_BRAND_FOOTER` + page numbers.
- **Truncation** (AC-7): clause/rationale/rewrite text truncated to the `REPORT_PDF_*_MAX_CHARS` caps
  (ellipsis) before layout — never raises on long input.
- **Escaping** (safety): all report-derived strings pass through `xml.sax.saxutils.escape` before
  going into reportlab `Paragraph` markup (reportlab treats `<...>` as its mini-HTML), so stray `<`/`&`
  can't break layout — the PDF analogue of the HTML-escaping requirement.
- **Zero findings** (AC-5): renders a positive "No risks flagged — N clauses reviewed" state.
- Never raises for content reasons; a genuinely unexpected failure propagates to the caller's
  try/except in delivery (which falls back — §3.6).

### 3.4 `app/delivery/email_html.py` (CREATE — HTML + plain bodies)
- `build_email_bodies(document_id, summary, original_filename, drive_ref) -> tuple[str, str, str]`
  returning `(subject, plain_text, html)`.
- **plain_text** = today's `_compose_email` content verbatim (preserved as the fallback — AC-9).
- **html** = a branded, inline-CSS (email-client-safe, table-based) template: wordmark header on the
  accent color, a summary block (validated findings + high/medium/low), a short trustworthy blurb, a
  **CTA button** linking `drive_ref` when present (omitted when absent — AC-10), professional footer.
- **All interpolated report text is HTML-escaped** via `html.escape` (AC-18) — subject/filename too.
- The existing `_compose_email` in `delivery_step.py` is replaced by a thin call into this module
  (keeps subject logic; adds the html part).

### 3.5 `app/delivery/models.py` + `gmail_server.py` + `gmail_client.py` (HTML + PDF over MCP)
- **`GmailSendRequest`**: add `html_body: Optional[str] = None`.
- **`gmail_server._build_mime`**: build `MIMEMultipart("mixed")`; inside it a
  `MIMEMultipart("alternative")` with `MIMEText(req.body, "plain")` **and**, when `req.html_body`,
  `MIMEText(req.html_body, "html")`; then attach the file (PDF) via `MIMEApplication` with an explicit
  `application/pdf` subtype + `.pdf` filename (AC-11/AC-12). When `html_body` is None → plain-only
  (pre-030 parity). `send_message` inputSchema gains `"html_body": {"type": ["string","null"]}`.
- **`gmail_client.send_report_via_gmail`**: add `html_body: Optional[str] = None` as a **trailing
  keyword** param, thread it into `GmailSendRequest`. **The existing positional order of `to`,
  `subject`, `body` (and `attachment_path`, `attachment_name`) is unchanged** — existing tests assert
  on positional args (e.g. `call_args[0][1]`=subject, `[0][2]`=body); `html_body` must be added after
  them / passed as a keyword so those positions are preserved (AC-8/AC-10a wiring; §7).

### 3.6 `app/delivery/delivery_step.py` (wiring)
- Add module aliases for the new config constants (mirror the existing re-exposure pattern).
- Add `_load_report(json_path) -> Optional[ContractReport]` (full report, not just summary; reuse the
  existing `ContractReport.model_validate_json`; None on error).
- In `deliver_report`, after the existing report-file guards:
  1. **PDF generation** (gated on `MCP_REPORT_PDF_ENABLED` and a successfully loaded report):
     `pdf_path = md_path.with_suffix(".pdf")`; `try: render_report_pdf(report, pdf_path)` — on success
     `pdf_ok=True`; on exception log + `pdf_ok=False` (fall back). If the report json won't load,
     `pdf_ok=False`.
  2. **Drive** (`_deliver_drive`): extend `ext_to_path`/`ext_to_mime` with `"pdf" → pdf_path`,
     `application/pdf`; iterate `MCP_DRIVE_UPLOAD_FORMATS` = `("pdf","json")`; set the aggregate
     `resource_ref` from the **pdf** upload (AC-10a) — replacing the `if ext=="md"` md-sourced ref in
     the current `_deliver_drive`. **Symmetric fallback** with Gmail (AC-13): if `pdf_ok` is False,
     fall back to uploading `md` (so Drive still gets a human-readable doc) and source the ref from the
     md upload — i.e. both channels prefer PDF, else the `.md`, else the channel reports FAILED.
  3. **Gmail**: `subject, plain, html = build_email_bodies(...)`; choose attachment by
     `MCP_GMAIL_ATTACH_FORMAT` — `pdf_path` when `pdf_ok` and format=="pdf", else `md_path` (AC-13
     precedence: PDF → else `.md` if it exists → else mark FAILED). Call `send_report_via_gmail(to,
     subject, plain, html_body=html, attachment_path=attach, attachment_name=...)`.
- **Never raises**; `mcp_delivery_status` shape unchanged; disabled-PDF path reverts to pre-030 exactly.

---

## 4. Tests mapped to acceptance criteria (pytest, TDD §7)

### `test_report_pdf.py` (renderer)
- **AC-1** rendered file starts with `b"%PDF-"` and is non-empty.
- **AC-2/3/4** assert via a `_build_flowables(report)` seam that returns the ordered text-content list
  (pure, unit-testable without parsing the PDF; no new PDF-parsing dependency): brand wordmark,
  `original_filename`, date; summary numbers; per-finding clause_type/risk_level/rationale/clause_text
  and a before→after block when `suggested_rewrite` set. The emitted PDF itself is checked only by the
  `%PDF-` header (AC-1).
- **AC-5** zero-findings report → valid PDF, "no risks" state, no crash.
- **AC-7** oversized clause/rationale/rewrite → truncated to caps, no raise.
- **AC-6** pure/no-network: monkeypatch nothing; same input → same flowable structure.
- **escaping**: a finding with `<script>`/`&` renders without breaking (escaped in flowables).

### `test_email_html.py`
- **AC-8** result has non-empty html containing wordmark + findings count + high/med/low.
- **AC-9** plain-text fallback present, conveys the summary (matches pre-030 text).
- **AC-10** CTA link present when `drive_ref` given; absent (no error) when None.
- **AC-18** `<script>`/`&`/`"` in a finding field appear **escaped** in the html; raw tag absent.

### `test_mcp_servers.py` (extend — gmail server) + `test_mcp_clients.py` (extend — gmail client)
- **AC-8/AC-12** `_build_mime` with `html_body` set → parse the built message: it is `multipart/mixed`
  containing a `multipart/alternative` with a `text/plain` AND a `text/html` part.
- **AC-11** with a PDF `attachment_path` → an `application/pdf` part with `Content-Disposition:
  attachment; filename="*.pdf"`. With `MCP_GMAIL_ATTACH_REPORT` false / no attachment → no attachment part.
- **parity** `html_body=None` → plain-only message (pre-030 shape) still valid; the EXISTING gmail tests
  in `test_mcp_servers.py` (e.g. `test_gmail_attaches_when_path_given`, `test_gmail_sends_message`) and
  the client-signature test in `test_mcp_clients.py` must still pass (extend, don't weaken).

### `test_delivery_step.py` (extend)
- **AC-13** monkeypatch `render_report_pdf` to raise → email still sent with the `.md` attached (assert
  the attachment passed to the gmail client is the md path); render raises **and** md missing → gmail
  channel FAILED, `deliver_report` returns normally (no raise).
- **AC-10a** successful PDF Drive upload → the composed email's CTA/`drive_ref` is the PDF's ref; assert
  dropping `md` from formats does not null the CTA.
- **AC-14** Drive uploads pdf+json; `mcp_delivery_status` shape unchanged.
- **AC-15** `MCP_REPORT_PDF_ENABLED=False` → no PDF; email plain-text + `.md` attachment (pre-030).
- **never-raise**: a raised renderer/loader error never propagates out of `deliver_report`.
- **UPDATE existing breaking tests (not weaken):** `test_drive_uploads_configured_formats` (asserts the
  default upload set includes a `.md` name) → now assert `.pdf`/`.json`; the `test_gmail_body_links_
  drive_only_when_ok` positional-arg assertions (`call_args[0][1]`=subject, `[0][2]`=plain body) stay
  valid because `html_body` is a trailing keyword (§3.5) — re-run to confirm.

### `test_config.py`
- **AC-17** assert each new constant + `MCP_DRIVE_UPLOAD_FORMATS == ("pdf","json")` and types.
- **UPDATE `test_mcp_upload_formats_are_report_extensions`** (currently asserts
  `set(MCP_DRIVE_UPLOAD_FORMATS) <= {"md","json"}`): pdf is now a legitimate delivery-time format, so
  restate the invariant as `<= {"md","json","pdf"}` (do NOT delete it — it still guards against typos /
  arbitrary extensions). Note the intent (§7): the set is "renderable delivery formats," `pdf` added.

### `test_delivery_integration.py` (extend)
- **UPDATE** the happy-path `assert md_path in uploaded_paths` (≈L106-107): under the new default Drive
  drops `md`, so assert the **PDF** (and json) paths are uploaded instead, and that the Gmail attachment
  is the PDF. This is a real integration test the config change breaks — reconcile it, don't skip it.

### Cross-cutting
- **AC-16** `git diff --name-only main` shows no graph/state/migration/frontend/endpoint file; only the
  §2 files (incl. `tests/integration/test_delivery_integration.py`). `report_agent.py` and `builder.py`
  unchanged; 7 nodes / 2 edges + `ContractState` intact.

---

## 5. Implementation order (TDD — §7)

1. **Dep + config (red-enabling):** add reportlab to pyproject + install; add the config constants;
   write `test_config.py` asserts (red → green). Whole suite still green (nothing reads them yet).
2. **PDF renderer:** write `test_report_pdf.py` (red) → implement `report_pdf.py` with a
   `_build_flowables` seam + `render_report_pdf` (green). Include truncation + escaping + zero-findings.
3. **HTML email:** write `test_email_html.py` (red) → implement `email_html.py` (green).
4. **Gmail MCP (model+server+client):** write `test_mcp_servers.py` + `test_mcp_clients.py` extensions
   (red) → add `html_body` to `GmailSendRequest`, rebuild `_build_mime` as multipart/alternative + PDF
   attachment, extend the inputSchema and `send_report_via_gmail` (trailing kwarg) (green). Confirm the
   existing gmail tests in those files still pass (plain parity).
5. **Delivery wiring:** write `test_delivery_step.py` extensions (red) → wire PDF gen + Drive pdf/json +
   CTA-from-PDF + attachment selection + `.md` fallback + reversibility into `delivery_step.py` (green).
   Then reconcile the breaking existing tests (`test_config.py` upload-formats invariant,
   `test_drive_uploads_configured_formats`, `test_delivery_integration.py` md assertion) — update to the
   new pdf/json reality, not weaken.
6. **Full regression:** `pytest -q` all green (unit + integration); `git diff --name-only main` shows
   only §2 files.
7. **Live smoke (real Google account):** run `scripts/delivery_smoke.py <your-email>` → confirm a
   branded PDF lands in the inbox as an `application/pdf` attachment on a proper HTML email, and the PDF
   + json appear in Drive. (Requires a valid `google_token.json` — now long-lived after the Production
   publish.) Record PASS.

Tests are written/observed failing first (§7). No existing assertion is weakened — existing gmail/
delivery tests keep passing on the plain/`.md` reversible path where they assert pre-030 behavior; only
extend or add.

---

## 6. Notes / risks

- **Delivery-layer only (feature 010 D1):** the graph, `ContractState`, and Node 7 are untouched; the
  PDF is a delivery artifact rendered from the report `.json`. This keeps the constitution's fixed
  architecture intact and makes the whole feature reversible via config.
- **Fallback safety (AC-13):** Node 7 still writes `.md`, so a reportlab failure degrades to the exact
  pre-030 attachment; `deliver_report` never raises — a rendering bug can never break the pipeline.
- **Escaping in two places:** reportlab `Paragraph` uses an HTML-ish mini-markup, and the email HTML is
  real HTML — both must escape contract-derived text (`xml.sax.saxutils.escape` / `html.escape`). This
  is both a correctness (layout) and a safety (injection) requirement.
- **Latency (§9):** reportlab renders a small report in well under a second; it runs once, post-terminal,
  inside the existing `MCP_DELIVERY_TIMEOUT_SECONDS` envelope — negligible added time.
- **PDF text-extraction in tests:** to avoid a new test-only PDF-parsing dependency, assert content via
  the pure `_build_flowables` seam (list of text/flowables) rather than parsing the emitted PDF; keep
  one `%PDF-` header check on the real output (AC-1).
- **reportlab is the only engine** — `MCP_REPORT_PDF_ENGINE` from spec §2.3/§6-Q1 is intentionally not
  added (single engine); `MCP_REPORT_PDF_ENABLED` provides the reversibility toggle instead.
- **Phase 2 boundary:** per-user Drive / per-user OAuth is explicitly a separate future feature; nothing
  here touches the single-account model, auth, or the `/integrations` page.

---

*Per §1/§11, the `feature/030-professional-report-delivery` branch opens only after this plan.md +
spec.md are approved and `tasks.md` exists. No migration, no frontend, no graph/state change. No
`tasks.md`/implementation in this pass — plan only.*
