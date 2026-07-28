# Professional report delivery (Phase 1: PDF + SaaS HTML email) — Implementation Tasks

Implements `specs/030-professional-report-delivery/plan.md`. TDD per constitution §7 (write/observe the
test failing first, then implement; never weaken an assertion to force a pass). All work on branch
`feature/030-professional-report-delivery` (§11). Run all `pytest` and scripts from `backend/`.
Delivery-layer only — no graph/edge/`ContractState` change; Node 7 (`report_agent.py`) and `builder.py`
are untouched. Monkeypatch the delivery **module-level config aliases** (mirrors the existing
`delivery_step.py` / `gmail_server.py` re-exposure), never `app.config` directly.

Legend: each task lists file(s), the change, and the acceptance criteria (AC-n) it satisfies.

---

## Task 0 — Branch (prerequisite)
Only after spec.md + plan.md are approved and this tasks.md exists: `git checkout main` → `git pull
origin main` → `git checkout -b feature/030-professional-report-delivery` (git-start workflow). No
`app/` file written before the branch exists.

---

## Task 1 — Dependency + config constants (AC-17)
**Files:** `pyproject.toml`, `app/config.py`, `tests/unit/test_config.py`
1. Add `reportlab` to the project dependencies in `pyproject.toml`; install into the venv:
   `.venv/Scripts/python.exe -m pip install reportlab`. Verify `import reportlab` works.
2. In `app/config.py` add (with §3 rationale comments):
   ```python
   MCP_GMAIL_ATTACH_FORMAT: str = "pdf"          # "md" restores pre-030 attachment
   MCP_REPORT_PDF_ENABLED: bool = True           # False → pre-030 plain email + .md attachment
   REPORT_PDF_CLAUSE_MAX_CHARS: int = 2000
   REPORT_PDF_RATIONALE_MAX_CHARS: int = 1500
   REPORT_PDF_REWRITE_MAX_CHARS: int = 4000
   REPORT_BRAND_NAME: str = "ContractSentinel"
   REPORT_BRAND_ACCENT_HEX: str = "#1e293b"
   REPORT_BRAND_FOOTER: str = "Automated contract-risk analysis — review with qualified counsel."
   ```
   and CHANGE `MCP_DRIVE_UPLOAD_FORMATS` from `("md","json")` to `("pdf","json")`.
3. **Test first** in `tests/unit/test_config.py`:
   - Add asserts for each new constant + `MCP_DRIVE_UPLOAD_FORMATS == ("pdf","json")` and types.
   - UPDATE `test_mcp_upload_formats_are_report_extensions` (currently
     `set(MCP_DRIVE_UPLOAD_FORMATS) <= {"md","json"}`) → `<= {"md","json","pdf"}`. Do NOT delete it —
     it still guards against arbitrary/typo extensions; `pdf` is now a legitimate delivery format.
   - UPDATE `test_mcp_delivery_constants_match_spec` (line ~420) which hard-asserts
     `config.MCP_DRIVE_UPLOAD_FORMATS == ("md","json")` → change to `== ("pdf","json")`. This is a
     second breaking assertion for the same config change — update it (not weaken), same TDD intent.
   Run `pytest tests/unit/test_config.py` → red before the config edits, green after.
4. Run `pytest -q` — note that `test_drive_uploads_configured_formats` (test_delivery_step.py) and the
   integration `md_path in uploaded_paths` will now be red; they're fixed in Task 5 (record them).

---

## Task 2 — PDF renderer (AC-1..AC-7, escaping)
**Files:** `app/delivery/report_pdf.py` (CREATE), `tests/unit/test_report_pdf.py` (CREATE)
**Test first** — `test_report_pdf.py` (build a `ContractReport` fixture from `app/models/report.py`
with a couple `ReportFinding`s incl. one with `suggested_rewrite` and one high/med/low each):
- **AC-1**: `render_report_pdf(report, tmp_path/"r.pdf")` → file exists, non-empty, first bytes `b"%PDF-"`.
- **AC-2/3/4** (via the `_build_flowables(report)` seam — a pure list of text/flowables, NOT by parsing
  the PDF): asserts the seam's text content includes `REPORT_BRAND_NAME`, `original_filename`, the date,
  the summary numbers (total/validated/clean + high/med/low), and per-finding clause_type/section,
  risk_level, risk_rationale, clause_text, and a before→after block when `suggested_rewrite` is set.
- **AC-5**: a zero-findings report → valid PDF, seam contains a "no risks flagged" + clean-count state.
- **AC-7**: clause_text/rationale/rewrite longer than the caps → truncated (len ≤ cap, ellipsis), no raise.
- **escaping**: a finding with `clause_text="<script>x</script> a & b"` → renders without raising; the
  seam's escaped text contains `&lt;script&gt;`/`&amp;` (reportlab Paragraph mini-markup safety).
**Then implement** `report_pdf.py`:
- Module config aliases: `REPORT_PDF_CLAUSE_MAX_CHARS`, `REPORT_PDF_RATIONALE_MAX_CHARS`,
  `REPORT_PDF_REWRITE_MAX_CHARS`, `REPORT_BRAND_NAME`, `REPORT_BRAND_ACCENT_HEX`, `REPORT_BRAND_FOOTER`.
- `_esc(s)` = `xml.sax.saxutils.escape(str(s or ""))`; `_trunc(s, n)` = cap + ellipsis.
- `_build_flowables(report: ContractReport) -> list` (pure): branded header band (wordmark on accent),
  metadata line, risk-summary band (colored chips for total/validated/clean + high/med/low), then per
  finding: severity chip (high=red `#dc2626`, medium=amber `#d97706`, low=slate accent), clause_type +
  section_number, escaped+truncated clause_text, risk_rationale, and a before→after rewrite block when
  present; evidence source count. Footer paragraph = `REPORT_BRAND_FOOTER`.
- `render_report_pdf(report, out_path) -> Path`: `SimpleDocTemplate(str(out_path), ...).build(
  _build_flowables(report), onFirstPage=..., onLaterPages=...)` for the header/footer + page numbers;
  return `out_path`. Pure, no network, does not read `ContractState`. Content-driven issues never raise
  (truncation/escaping handle them); genuinely unexpected exceptions propagate to the delivery caller
  (which falls back — Task 5).
Run `pytest tests/unit/test_report_pdf.py` → green.

---

## Task 3 — HTML + plain email bodies (AC-8, AC-9, AC-10, AC-18)
**Files:** `app/delivery/email_html.py` (CREATE), `tests/unit/test_email_html.py` (CREATE)
**Test first** — `test_email_html.py`:
- **AC-8**: `build_email_bodies(document_id, summary, original_filename, drive_ref="http://x")` returns
  `(subject, plain, html)`; `html` contains `REPORT_BRAND_NAME`, the findings count, and high/med/low.
- **AC-9**: `plain` is non-empty and conveys the same summary (matches the pre-030 text content).
- **AC-10**: with `drive_ref` set → `html` contains the link as a CTA; with `drive_ref=None` → no CTA,
  no error, `plain` still fine.
- **AC-18**: a `summary`/filename or (when findings are passed) finding field containing
  `<script>`/`&`/`"` → the `html` shows escaped entities (`&lt;`,`&amp;`,`&quot;`), raw `<script>` absent.
**Then implement** `email_html.py`:
- Module aliases for `REPORT_BRAND_NAME`, `REPORT_BRAND_ACCENT_HEX`, `REPORT_BRAND_FOOTER`.
- `build_email_bodies(document_id, summary, original_filename, drive_ref) -> tuple[str,str,str]`:
  - `subject` = the current `_compose_email` subject logic (findings + high/med/low; fallback form when
    `summary is None`).
  - `plain` = the current `_compose_email` body text verbatim (the accessible fallback).
  - `html` = a branded, INLINE-CSS, table-based (email-client-safe) template: wordmark header on
    `REPORT_BRAND_ACCENT_HEX`, a summary block (validated findings + high/med/low), a short trustworthy
    blurb, a CTA `<a>` button to `drive_ref` when present, footer = `REPORT_BRAND_FOOTER`.
  - EVERY interpolated value passes through `html.escape(...)` (AC-18), including subject/filename.
Run `pytest tests/unit/test_email_html.py` → green.

---

## Task 4 — Gmail MCP: HTML alternative + PDF attachment (AC-8, AC-11, AC-12)
**Files:** `app/delivery/models.py`, `app/delivery/mcp_servers/gmail_server.py`,
`app/delivery/mcp_clients/gmail_client.py`, `tests/unit/test_mcp_servers.py`,
`tests/unit/test_mcp_clients.py`
**Test first**:
- `test_mcp_servers.py`: build a `GmailSendRequest` with `html_body` set + a PDF `attachment_path`; call
  `_build_mime`, base64-decode, `email.message_from_bytes` → assert (AC-8/AC-12) it is `multipart/mixed`
  containing a `multipart/alternative` with BOTH a `text/plain` and a `text/html` part; (AC-11) an
  `application/pdf` part with `Content-Disposition: attachment; filename="*.pdf"`. With `html_body=None`
  → plain-only structure (pre-030 parity). Keep the EXISTING gmail tests
  (`test_gmail_attaches_when_path_given`, `test_gmail_send_builds_mime_and_sends`) passing.
- `test_mcp_clients.py`: `send_report_via_gmail(..., html_body="<b>x</b>")` threads `html_body` into the
  built `GmailSendRequest`; existing positional-arg behavior (to/subject/body) unchanged.
**Then implement**:
- `models.py`: `GmailSendRequest` gains `html_body: Optional[str] = None`.
- `gmail_server._build_mime`: `outer = MIMEMultipart("mixed")`; `alt = MIMEMultipart("alternative")`;
  `alt.attach(MIMEText(req.body, "plain"))`; if `req.html_body`: `alt.attach(MIMEText(req.html_body,
  "html"))`; `outer.attach(alt)`; then the attachment. Generalize the CURRENT generic attachment path
  (today `MIMEApplication(data, Name=name)` + a manual `Content-Disposition`) to set the subtype from
  the file extension — `application/pdf` for `.pdf`, but keep a sensible type for the `.md` fallback
  attachment (AC-13/AC-15) rather than hardcoding pdf. Keep `Content-Disposition: attachment;
  filename="..."`. Set `outer["to"]/["subject"]`. Return base64.
- `gmail_server` `send_message` inputSchema: add `"html_body": {"type": ["string","null"]}`.
- `gmail_client.send_report_via_gmail`: add `html_body: Optional[str] = None` as a **trailing keyword**
  (after the existing params, before/with the `*` keyword-only barrier so positional
  to/subject/body/attachment_path/attachment_name are unchanged); pass into `GmailSendRequest`.
Run `pytest tests/unit/test_mcp_servers.py tests/unit/test_mcp_clients.py` → green.

---

## Task 5 — Delivery wiring + reconcile breaking tests (AC-13, AC-14, AC-15, AC-10a, AC-16)
**Files:** `app/delivery/delivery_step.py`, `tests/unit/test_delivery_step.py`,
`tests/integration/test_delivery_integration.py`
**Test first** — `test_delivery_step.py`:
- **AC-13**: monkeypatch the delivery module's `render_report_pdf` to raise → `deliver_report` returns
  normally (no raise) and the attachment passed to the gmail client is the `.md` path (fallback). Render
  raises AND `.md` missing → gmail channel FAILED, still no raise.
- **AC-10a**: successful PDF Drive upload → the aggregate Drive `resource_ref` (and thus the email CTA)
  is the PDF upload's ref; assert dropping `md` from `MCP_DRIVE_UPLOAD_FORMATS` does not null the CTA.
- **AC-14**: Drive uploads pdf + json; `mcp_delivery_status` shape `{drive|gmail:{status,error_message,
  delivered_at}}` unchanged.
- **AC-15**: `MCP_REPORT_PDF_ENABLED=False` → no PDF render; email is plain-text + `.md` attachment
  (pre-030); gmail called with `html_body=None` (or the plain path).
- **UPDATE** `test_drive_uploads_configured_formats` → assert the default set now yields `.pdf`/`.json`
  names (not `.md`). Confirm `test_gmail_body_links_drive_only_when_ok` still passes (positional
  subject/body unchanged; `html_body` trailing keyword).
**Then implement** `delivery_step.py`:
- Add module aliases for `MCP_GMAIL_ATTACH_FORMAT`, `MCP_REPORT_PDF_ENABLED` (+ the branding/cap ones as
  needed); import `render_report_pdf` and `build_email_bodies`.
- Add `_load_report(json_path) -> Optional[ContractReport]` (full report; None on error).
- In `deliver_report` after the existing report-file guards:
  1. `pdf_path = md_path.with_suffix(".pdf")`; if `MCP_REPORT_PDF_ENABLED` and the report json loaded:
     `try: render_report_pdf(report, pdf_path); pdf_ok = True` `except Exception: log; pdf_ok = False`.
  2. Drive (`_deliver_drive`): extend `ext_to_path` with `"pdf": pdf_path` (only when `pdf_ok`) and
     `ext_to_mime` with `"pdf": "application/pdf"`; iterate `MCP_DRIVE_UPLOAD_FORMATS`; source the
     aggregate `resource_ref` from the **pdf** upload (replace the `if ext=="md"` logic). If `not
     pdf_ok`, fall back to uploading/refing `md`.
  3. Gmail: `subject, plain, html = build_email_bodies(document_id, summary, original_filename,
     drive_ref)`; pick attachment by `MCP_GMAIL_ATTACH_FORMAT`: `pdf_path` when `pdf_ok` and
     format=="pdf", else `md_path` if it exists, else no attachment (channel may FAIL per existing
     path). Call `send_report_via_gmail(to, subject, plain, attachment_path, attachment_name,
     html_body=html)`.
  - Never raise; keep `_all_enabled_failed` / `_failed_info` behavior for the missing-report guards.
- **UPDATE** `test_delivery_integration.py` (~L106-107): the happy path now uploads the PDF (+ json), not
  `md` — assert the PDF/json paths in `uploaded_paths` and that the gmail attachment is the PDF.
Run `pytest tests/unit/test_delivery_step.py tests/integration/test_delivery_integration.py` → green.

---

## Task 6 — Full regression + no-scope-creep gate (AC-16)
- `pytest -q` → ALL green (unit + integration).
- `git diff --name-only main` shows ONLY: `pyproject.toml`, `app/config.py`,
  `app/delivery/report_pdf.py`, `app/delivery/email_html.py`, `app/delivery/models.py`,
  `app/delivery/mcp_servers/gmail_server.py`, `app/delivery/mcp_clients/gmail_client.py`,
  `app/delivery/delivery_step.py`, and the test files. NO graph/edge/`ContractState`/migration/frontend/
  endpoint change; `report_agent.py`/`builder.py` untouched; 7 nodes / 2 conditional edges intact.

---

## Task 7 — Live smoke (real Google account)
From `backend/`, with the venv on PATH and a valid `google_token.json` (now long-lived after the
Production publish): `.venv/Scripts/python.exe scripts/delivery_smoke.py <your-email>`. Confirm:
1. `SMOKE: PASS` (drive + gmail both success).
2. The inbox email is a **branded HTML** email (not plain text) with an **`application/pdf`**
   attachment; open the PDF and confirm the branded professional layout.
3. Google Drive shows the **PDF + json** (not the raw md).
Record the result (append a short note to this tasks.md). A failure here blocks merge — investigate.

---

## Acceptance-criteria coverage map
AC-1..7 → Task 2 · AC-8 → Task 3 & Task 4 · AC-9,10 → Task 3 · AC-10a → Task 5 · AC-11,12 → Task 4 ·
AC-13,14,15 → Task 5 · AC-16 → Task 6 · AC-17 → Task 1 · AC-18 → Task 3. Live verification → Task 7.
