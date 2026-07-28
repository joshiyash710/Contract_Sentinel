# Feature 030 — Professional report delivery (Phase 1: PDF report + SaaS HTML email)

## 1. Problem statement

Today a completed analysis is delivered as a **plain Markdown attachment** on a **plain-text email**
(`app/delivery/delivery_step.py::_compose_email` builds a `MIMEText(..., "plain")` body;
`app/delivery/mcp_servers/gmail_server.py` attaches the raw `.md`). For a product that wants to look
like a trustworthy SaaS, this undersells the analysis: the recipient gets a bare `.md` file and a
few lines of text.

This feature (Phase 1 of the delivery upgrade) makes the delivered artifacts look professional:

1. **A branded PDF report** — a polished, trustworthy-looking PDF generated from the existing report
   data, replacing the `.md` as the emailed attachment and uploaded to Drive.
2. **A branded SaaS-style HTML email** — a multipart HTML email (with a plain-text fallback) that
   presents the risk summary cleanly, instead of the current plain-text body.

### Position relative to the constitution

This work lives **entirely in the post-terminal delivery layer** (feature 010), which is **not a
graph node** (010 spec §8a D1: "deliver_report … NOT a graph node; the graph is untouched"). So:

- **No new LangGraph node/edge; the fixed 7-node / 2-conditional-edge graph (§2) is untouched.**
- **No `ContractState` change (001).** The PDF/email are rendered from the report artifacts Node 7
  (ReportAgent) already writes to disk (`report_path` → `<document_id>.md` + `.json`). Node 7 is
  **unchanged** and still writes `.md` + `.json`.
- **Stays within the permitted integrations** — Drive + Gmail only; nothing new is added to the
  PERMANENTLY-CUT "beyond Drive + Gmail" list. No compliance claims, no new modes.
- New tunables are **named configurable constants** in the shared config module (§3), reversible.
- Per §9 (local-model latency) the PDF render adds a small, bounded amount of time to the
  already-post-terminal delivery step; it must not block or crash the pipeline.
- Per §1 + the artifact review gate, developed spec → plan → tasks → implementation on branch
  `feature/030-professional-report-delivery`; per §7 TDD.

**Explicitly Phase 1 only.** Per-user Google Drive (each user's report to *their own* Drive) requires
per-user OAuth and a constitution amendment — that is **Phase 2**, owned by a future spec and **out of
scope here** (§5). Delivery stays on the single, server-managed Google account; the email recipient is
still the logged-in user's own email (feature 020, unchanged).

## 2. Inputs and outputs

### 2.1 Inputs (existing artifacts — no new state)

The renderer and email composer consume the **report artifacts already on disk**, not new state.
Source of truth is `app/models/report.py::ContractReport` (the JSON sibling of `report_path`), whose
shape is already produced by Node 7. These are **typed Pydantic models**, not loose dicts: `summary`
is a `ReportSummary` and `findings` is a `List[ReportFinding]`. Relevant fields (verified against
`report.py` and a real `data/reports/*.json`):

- `ContractReport`: `document_id: str`, `original_filename: str`, `uploaded_at: str`,
  `generated_at: str`, `ocr_used: bool`, `ingest_error: Optional[dict]`, `summary: ReportSummary`,
  `findings: List[ReportFinding]`.
- `ReportSummary`: `{ total_clauses, validated_findings, clean_clauses, high, medium, low }` (ints).
- `ReportFinding` (each finding): `clause_id`, `position`, `section_number`, `clause_type`,
  `risk_level` ("low"|"medium"|"high", may be None), `risk_rationale`, `clause_text`, `rewrite_state`,
  `suggested_rewrite` (Optional), `path_taken`, `confidence_score`, `evidence` (list).

From `ContractState` (001) the delivery step continues to read only `report_path` and
`original_filename` (as it does today) — **no `ContractState` field is added, renamed, or removed.**

### 2.2 Outputs

- **New artifact on disk:** `<document_id>.pdf`, generated at delivery time next to the existing
  `.md`/`.json` (same directory as `report_path`). It is NOT written by Node 7 and NOT referenced in
  `ContractState`.
- **Gmail:** a **multipart** message — `MIMEMultipart("mixed")` containing a
  `MIMEMultipart("alternative")` body (plain-text fallback + HTML part) plus the **PDF attachment**
  (replacing the `.md` attachment). Sent from the central app account to the existing recipient
  (feature 020 logic unchanged).
- **Drive:** the **PDF** is uploaded (see §6 Q2 for pdf-only vs pdf+md+json). Existing
  `mcp_delivery_status` shape (`{drive|gmail: {status, error_message, delivered_at}}`) is unchanged.
- **Drive CTA link source:** today `_deliver_drive` sets the aggregate `resource_ref` **only from the
  `md` upload** (`if ext == "md" and r.ok: md_ref = r.resource_ref`), and `_compose_email` uses that as
  the "View on Drive" link. Because Q2's recommendation drops `md` from Drive, this feature must
  **re-source the Drive `resource_ref` from the PDF upload** so the CTA points at the delivered PDF
  (see AC-10a). The email CTA must not silently disappear as a side effect of Q2.
- **`mcp_delivery_status`** semantics unchanged: `deliver_report` still returns only
  `{"mcp_delivery_status": {...}}` and never raises.

### 2.3 New/changed config (§3 — named, reversible)

- `MCP_GMAIL_ATTACH_FORMAT` (default `"pdf"`) — the email attachment format; revert to `"md"` for the
  pre-030 behavior.
- `MCP_DRIVE_UPLOAD_FORMATS` gains `"pdf"` (see §6 Q2 for whether it replaces or augments `md`/`json`).
- `MCP_REPORT_PDF_ENABLED` (default `True`) — master toggle for PDF rendering; `False` reverts to the
  pre-030 `.md`-attachment + plain-text path (AC-15).
- `MCP_REPORT_PDF_ENGINE` — selects the PDF engine (per §6 Q1), if more than one is supported.
- `REPORT_PDF_CLAUSE_MAX_CHARS` / `REPORT_PDF_RATIONALE_MAX_CHARS` / `REPORT_PDF_REWRITE_MAX_CHARS` —
  per-field truncation caps (AC-7), mirroring the report's existing char-cap discipline.
- Branding constants (product wordmark text, accent color, support/footer text) — no secrets.

(Exact final names may be refined in the plan, but each MUST be a named constant, never an inline
literal — AC-17.)

## 3. Acceptance criteria

### PDF renderer
- **AC-1** Given a valid report JSON with ≥1 finding, the renderer produces a non-empty PDF file whose
  first bytes are the `%PDF-` magic header.
- **AC-2** The PDF contains the branded header/wordmark text, the `original_filename`, and the
  `generated_at` (or upload) date (assert by extracting text from the produced PDF).
- **AC-3** The PDF contains a risk-summary section reflecting `summary` — the total clauses, validated
  findings, and the high/medium/low counts (assert the numbers appear).
- **AC-4** For each finding, the PDF renders its `clause_type`/`section_number`, `risk_level`,
  `risk_rationale`, `clause_text`, and — when `suggested_rewrite` is present — a before→after rewrite
  block. Severity is visually distinguished per level (e.g. a color/label per high/medium/low).
- **AC-5** A **zero-findings** report (all clean) still produces a valid PDF with a "no risks flagged"
  state and the clean-clause count (no crash, no empty file).
- **AC-6** The renderer is a **pure function of the report data** (same input → same document
  structure); it must not require network access and must not read `ContractState`.
- **AC-7** Long inputs are bounded: very long `clause_text`/`risk_rationale`/`suggested_rewrite` are
  truncated to a configured max so the PDF cannot balloon unbounded (mirrors the report's existing
  char caps); truncation never raises.

### HTML email
- **AC-8** The Gmail message is `multipart/mixed` whose body is a `multipart/alternative` with **both**
  a `text/plain` and a `text/html` part; the HTML part contains the product wordmark, the findings
  count, and the high/medium/low breakdown.
- **AC-9** The **plain-text fallback** part is present and conveys the same summary (accessibility /
  non-HTML clients), preserving today's plain-text content as the fallback.
- **AC-10** When a Drive link (`drive_ref`) is available, the HTML email includes it as a
  CTA/link; when absent, the email omits the CTA without error (unchanged behavior for the text part).
- **AC-10a** The Drive `resource_ref` that feeds the CTA is sourced from the **PDF** upload (not the
  `md` upload, which Q2 drops). A test asserts: after a successful Drive PDF upload, the composed email
  contains the PDF's Drive link; and Q2 dropping `md` does NOT null out the CTA.
- **AC-18 (HTML-injection safety)** A finding whose `clause_text`/`risk_rationale`/`suggested_rewrite`
  contains HTML metacharacters (e.g. `<script>`, `a & b`, `"quotes"`) is **escaped** in the emitted
  HTML email body — the raw markup does not appear unescaped and cannot alter the email structure
  (assert the escaped entities are present and the raw tag is absent).
- **AC-11** The **PDF** is attached with `Content-Type: application/pdf` and a `.pdf` filename;
  `Content-Disposition: attachment`. When `MCP_GMAIL_ATTACH_REPORT` is false, no attachment is added
  (parity with today).
- **AC-12** `gmail_server.py` accepts an HTML body + PDF attachment via its request schema and encodes
  a valid RFC-822 message (round-trip: the built message parses back to the expected parts).

### Delivery wiring & safety
- **AC-13** `deliver_report` generates the PDF (when enabled) and attaches/uploads it. On **PDF render
  failure** the precedence is: (1) **fall back to the pre-030 `.md` attachment** if the `.md` exists;
  (2) only if that fallback is also unavailable, mark the channel FAILED via the existing
  `_failed_info` pattern. In all cases `deliver_report` **never raises** — a bad render must not break
  delivery or the pipeline (assert: render exception → email still sent with `.md` attached; render
  exception + no `.md` → channel FAILED, no raise).
- **AC-14** Drive uploads the PDF (§6 Q2); `mcp_delivery_status` still reports per-channel
  success/failure with the same shape.
- **AC-15** With PDF rendering disabled via config, behavior reverts to the pre-030 path
  (plain-text email + `.md` attachment) — full reversibility.
- **AC-16** No `ContractState` field is added/renamed/removed; the graph still has 7 nodes / 2
  conditional edges; Node 7 (`report_agent`) is unchanged.
- **AC-17** All new tunables are named constants in the shared config module (no inline literals for
  formats, caps, branding, or engine selection).

## 4. Edge cases

- **Missing/'.json' sibling unreadable:** `_load_summary` already returns `None` on error today; the
  PDF/email must degrade gracefully — render a minimal PDF/email from whatever is available (at least
  the filename) rather than crash (mirrors AC-13).
- **Report file missing / `report_path is None`:** unchanged — delivery already returns
  `_all_enabled_failed(...)`; no PDF is attempted.
- **Zero findings (all clean):** valid "no risks" PDF + a positive-toned email (AC-5).
- **PDF engine unavailable / import error / render exception:** caught; fall back to `.md` attachment
  and mark/deliver without raising (AC-13). Never let a rendering dependency take down delivery.
- **Very large report (hundreds of findings) or very long text fields:** bounded via caps (AC-7);
  render must complete within the existing `MCP_DELIVERY_TIMEOUT_SECONDS` budget or fall back.
- **HTML-injection safety:** finding text (clause text, rationale, rewrite) is contract-derived and
  goes into the HTML email + PDF — it must be **escaped** so stray `<`, `&`, or markup cannot break
  the HTML email or inject content.
- **Non-ASCII / unicode text in clauses:** the PDF and email must render UTF-8 content (fonts that
  cover common characters) without raising; unsupported glyphs degrade gracefully.
- **Gmail size limits:** an oversized PDF (many findings) could approach attachment limits; the char
  caps (AC-7) keep it bounded, and an attach failure is reported via the existing failure path, not a
  crash.

## 5. Out of scope

- **Per-user Google Drive / per-user OAuth (Phase 2)** — each user's report to *their own* Drive. That
  needs per-user OAuth (connect flow, callback endpoint, per-user token storage + refresh, a DB
  migration) and a **constitution amendment** reversing the single-account server-managed model
  (feature 024). A **future spec (Phase 2)** owns it. This spec keeps the single central account.
- **Sending Gmail *from* the user's own account** — the email is still sent from the central app
  account **to** the user (that is the SaaS-correct model). Out of scope to change the sender.
- **In-app "Download PDF" button / a report-PDF API endpoint / any frontend change** — a candidate
  fast-follow. Phase 1 is **backend/delivery only**; no `frontend/src` file is touched. A future spec
  owns exposing the PDF in the web UI.
- **Changing what the report *contains*** (findings, risk scoring, evidence) — owned by Node 7
  (feature 009) and the pipeline; this feature only re-renders the existing report data.
- **New delivery channels** (Slack/Notion/etc.) — PERMANENTLY CUT.
- **Encryption at rest / retention / audit of the generated PDF** — Phase 2 DEFERRED items; not here.
- **Email deliverability infra** (SPF/DKIM/custom domain, unsubscribe management) — out of scope; we
  send via the existing Gmail MCP path.

## 6. Open questions

### Resolutions (decided 2026-07-28 — carried into the plan)
- **Q1 PDF engine → `reportlab`** (pure-Python, robust on Windows, full layout control; no browser/GTK).
- **Q2 Drive formats → PDF + json** (drop the raw `md` from Drive; the PDF supersedes it for humans,
  json stays as the machine record). The Drive CTA `resource_ref` is sourced from the PDF upload (AC-10a).
- **Q3 branding → text/CSS wordmark** ("ContractSentinel"); no binary logo asset in Phase 1.
- **Q4 product identity → "ContractSentinel"**, professional **navy** accent palette; a neutral
  trustworthy footer line. No logo file required.

The original options are retained below for context.


1. **(PDF engine — architecturally significant; needs your decision)** No PDF library is installed on
   this Windows box (only `pillow`). Options:
   - **(a) reportlab** — pure-Python, no system/browser deps, very robust on Windows, full
     programmatic layout control (colored bands, tables, severity chips). More layout code, but a
     clean corporate look is very achievable. **Recommended lead** — best reliability-to-effort for a
     professional PDF with zero fragile dependencies.
   - **(b) xhtml2pdf** — pure-Python HTML/CSS → PDF (uses reportlab under the hood). Faster templating
     via an HTML string, but **dated CSS support** (no flexbox/grid); "impressive" is harder to push.
   - **(c) Playwright + headless Chromium** — renders a modern HTML/CSS template with the **highest
     design fidelity** (can match the frontend's look), but adds a heavy dependency **plus a ~150 MB
     Chromium binary and an install step (`playwright install chromium`)**, and spawns a browser in
     the delivery path. Best-looking, heaviest/most fragile.
   **Recommendation: (a) reportlab.** Confirm (a), or choose (b)/(c) if you want the HTML-template
   route / maximum fidelity and accept the trade-offs.
2. **(Drive upload formats)** Should Drive upload the **PDF only**, or **PDF + keep the existing
   `md` + `json`**? Recommendation: **PDF + json** (drop the raw `md` from Drive — the PDF supersedes
   it for humans; keep `json` as the machine-readable record). Or keep all three if you prefer.
3. **(Branding assets)** **Text/CSS wordmark only** (no binary asset — simplest, no asset pipeline),
   or an **embedded logo image** (needs a committed logo file + asset handling)? Recommendation:
   **text/CSS wordmark** for Phase 1; add a real logo later. Confirm, or provide a logo to embed.
4. **(Product identity in the email/PDF)** Confirm the display name/wordmark is **"ContractSentinel"**
   and provide any footer/support line and accent color you want (else I'll use a sensible default
   navy/professional palette consistent with the app).
