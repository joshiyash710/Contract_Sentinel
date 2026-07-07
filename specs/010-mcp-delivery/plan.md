
# MCP Delivery Technical Plan

## Git Branch

`feature/010-mcp-delivery` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

This plan details how to implement the **MCP delivery step** specified in
`specs/010-mcp-delivery/spec.md`. It is the pipeline's **post-terminal transport
layer**: it takes the report artifact ReportAgent (Node 7, feature 009) wrote to disk
(`report_path` + its JSON sibling) and delivers it over the two — and only two — MCP
channels the constitution permits (§2 PERMANENTLY CUT): **Google Drive** and **Gmail**.

**It is NOT an 8th graph node (spec D1).** Constitution §2 fixes the StateGraph at
exactly 7 sequential nodes + 2 conditional edges, terminating at `report → END`
(`builder.py:133`). `001` §3 labels `mcp_delivery_status` "**Added by MCP delivery
step**". This feature therefore makes **zero** changes to `builder.py` — no
`add_node`, no `add_edge`, no `add_conditional_edges` — and instead adds a standalone
callable that a future runner/API layer invokes *after* the compiled graph returns.
To make the "not a node" boundary **structural and obvious**, all new application code
lives under a new top-level package `backend/app/delivery/`, deliberately **outside**
`app/graph/nodes/` (which is reserved for the 7 nodes).

**Transport = MCP (spec D10).** Per `002` §g — which lists the `mcp` Python SDK
*alongside* `google-api-python-client` and pins integration "via the Model Context
Protocol" — delivery is realized as an **MCP client → local MCP server** flow, not raw
Google API calls. This feature builds:

1. **Two thin local MCP servers** (`app/delivery/mcp_servers/`) that wrap
   `google-api-python-client` + Google OAuth and expose one tool each — a Drive
   `upload_file` tool and a Gmail `send_message` tool. The Google OAuth credentials
   are read **here**, at the server boundary, never in the delivery step.
2. **Two MCP client wrappers** (`app/delivery/mcp_clients/`) that open an MCP
   `ClientSession` to the respective server over **stdio transport**, call its tool
   with a per-attempt timeout + bounded backoff retry, and return a structured result.
   These never raise (boundary discipline mirroring `web_search` / `draft_rewrite`).
3. **One orchestrator** (`app/delivery/delivery_step.py`, `deliver_report`) — the
   public entrypoint the future runner calls. It resolves config, reads the artifact,
   drives the two channels **best-effort and independently** (spec D3), and returns a
   partial state dict containing **only** `mcp_delivery_status` (spec §2.2).

**Resolved spec decisions carried into this plan (§8a D1–D13):**
- **D1** — post-terminal step, not a node; no `builder.py` change. Code under
  `app/delivery/`.
- **D2** — Drive upload + Gmail email; Gmail links to the Drive copy when available and
  always attaches the Markdown.
- **D3** — per-channel, best-effort, independent, non-fatal: each service writes its own
  `mcp_delivery_status[service]` entry; one failing never blocks/reverts the other and
  the step never raises.
- **D4** — recipient from `MCP_DELIVERY_RECIPIENT` (env-overridable), runner may override
  per call.
- **D5** — transport only: reads `report_path` + the JSON sibling; never reads `clauses`.
- **D6** — deterministic Drive filename on `document_id`; re-delivery overwrites in place.
- **D7** — explicit **per-attempt** timeout + bounded **backoff** retry on every MCP tool
  call.
- **D8** — delivery failures recorded in `mcp_delivery_status`, **never** `error_count`.
- **D9** — OAuth consent/setup out of scope; the server only *reads* a provisioned
  credential and fails gracefully if it is missing/expired.
- **D10** — transport is MCP client → local Drive/Gmail MCP servers wrapping
  `google-api-python-client`.
- **D11** — no `current_node` / no `node_timings` entry written; timing to logs only.
  **D11a** — writes only `SUCCESS`/`FAILED`, never `PENDING`.
- **D12** — Drive URL/Gmail message id **not** persisted in state (`MCPDeliveryInfo`
  unchanged; no `001` §10 change).
- **D13** — config-disabled channel → **no** `mcp_delivery_status` entry;
  enabled-but-cannot-run → **`FAILED`** entry.

**Boundary Pydantic (constitution §4).** Every MCP tool-call request/response payload is
modeled with **Pydantic** (`app/delivery/models.py`) — the transport types are validated
before the call and never stored in graph state (the state key is the `001`-defined
`MCPDeliveryInfo` TypedDict, built as a plain dict by the orchestrator).

**Async bridge.** The `mcp` SDK's `ClientSession` is asyncio-based, and the future
runner is FastAPI (async, `002` §e). The orchestrator's real entrypoint is therefore
`async def deliver_report(...)`; a thin sync convenience wrapper
`deliver_report_sync(...)` (`asyncio.run(...)`) is provided for non-async callers and
simple tests. Channels run **sequentially** inside one event loop — Drive first so
Gmail can embed the returned Drive link (spec §2.3) — but their *outcomes* are
independent (a Drive failure still lets Gmail send with the attachment, spec AC-12).

---

## 2. Files to Create / Modify

### Shared Config Module

#### [MODIFY] `backend/app/config.py`

Add a new `# ── MCP delivery` block (pure addition, no rename). This block needs two
new imports at the top of `config.py` (which currently imports only
`from app.graph.state import RiskLevel`): **`import os`** (to read the recipient env
var — AC-15) and **`from typing import Optional`** (for `MCP_DRIVE_FOLDER_ID`).

```python
# ── MCP delivery ───────────────────────────────────────────────────────────────
# Source: specs/010-mcp-delivery/spec.md §6

MCP_DELIVERY_ENABLED: bool = True
# Master switch. False → deliver_report is a no-op (Edge Case 10).

MCP_DRIVE_ENABLED: bool = True
MCP_GMAIL_ENABLED: bool = True
# Per-channel toggles. A config-disabled channel is never attempted and contributes
# NO mcp_delivery_status entry (D13, AC-9). Both off ≡ MCP_DELIVERY_ENABLED False.

MCP_DELIVERY_RECIPIENT: str = os.getenv("CONTRACTSENTINEL_DELIVERY_RECIPIENT", "")
# Default Gmail recipient, read from the CONTRACTSENTINEL_DELIVERY_RECIPIENT env var
# (concrete name — AC-15) with "" fallback; a future runner may also override per
# request (D4). Empty → Gmail records a FAILED entry ("no recipient configured") while
# Drive proceeds (D13). NOTE: os.getenv is evaluated at import; tests assert AC-15 by
# monkeypatching the re-exposed MCP_DELIVERY_RECIPIENT on the delivery-step module (the
# established config-monkeypatch pattern), not by mutating the environment post-import.

MCP_DRIVE_FOLDER_ID: Optional[str] = None
# Target Drive folder id. None → the account's Drive root.

MCP_DRIVE_UPLOAD_FORMATS: tuple = ("md", "json")
# Which of Node 7's report files to upload. Default both; ("md",) uploads only the
# human-readable Markdown (AC-2).

MCP_GMAIL_ATTACH_REPORT: bool = True
# Attach the Markdown report so the recipient always has it even without a shareable
# Drive link (D3 robustness, AC-4).

MCP_DELIVERY_TIMEOUT_SECONDS: int = 60
# Per-ATTEMPT wall-clock timeout for one MCP tool call (client→server→Google→back),
# constitution §9. Worst case per channel ≈ (1 + MCP_DELIVERY_MAX_RETRIES) × this (AC-16).

MCP_DELIVERY_MAX_RETRIES: int = 2
# Bounded retries WITH EXPONENTIAL BACKOFF for TRANSIENT errors the server surfaces
# (Google 5xx / rate-limit) before a channel is marked FAILED. Non-retryable errors
# (auth/permission/malformed) fail immediately (AC-17, Edge Case 8).

GOOGLE_OAUTH_CREDENTIALS_PATH: str = "data/secrets/google_credentials.json"
GOOGLE_OAUTH_TOKEN_PATH: str = "data/secrets/google_token.json"
# backend/-relative OAuth client-secrets + cached-token paths. Consumed by the MCP
# SERVER layer (wraps google-api-python-client), NOT the client step (D10). Setup/
# consent that produces the token is out of scope (§5.4). git-ignored; never committed.
```

There is intentionally **no** LLM / model constant — the step makes zero LLM calls.

**[MODIFY] `.gitignore`** (repo root) — add `backend/data/secrets/` next to the
existing `backend/data/reports/` line so OAuth credentials/token are never committed.

#### [MODIFY] `backend/pyproject.toml` — enable pytest-asyncio (**gating**)

This feature introduces the **first** async code in the repo — there are currently
**zero** `async def test_*` and **no** `[tool.pytest.ini_options]` section anywhere
(`conftest.py` sets nothing). `pytest-asyncio` defaults to **strict** mode, which
errors/skips any bare `async def` test lacking `@pytest.mark.asyncio`. The plan's entire
client / orchestrator / integration suite is written as bare `async def test_...`, so
without this the async suite **does not execute**. Add:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
# Auto-collect bare `async def test_*` (first async tests in the repo — feature 010).
# Without this, pytest-asyncio's default strict mode skips/errors them silently.
```

This is a **blocking prerequisite** and is Step 0 of the TDD order (§4) — every async
test after it depends on it.

---

### Transport Pydantic Models

#### [NEW] `backend/app/delivery/models.py`

Boundary transport types (constitution §4). Never stored in graph state; the state key
`mcp_delivery_status` is the `001` `MCPDeliveryInfo` TypedDict, built as a plain dict by
the orchestrator from these results.

```python
from typing import Optional
from pydantic import BaseModel   # no Field — none of these models use it (ruff F401)

class DriveUploadRequest(BaseModel):
    """Validated arguments for the Drive server's upload_file tool."""
    file_path: str            # absolute/backend-relative path to the report file
    file_name: str            # deterministic {document_id}.{ext} (D6)
    mime_type: str            # "text/markdown" | "application/json"
    folder_id: Optional[str] = None

class GmailSendRequest(BaseModel):
    """Validated arguments for the Gmail server's send_message tool."""
    to: str
    subject: str
    body: str
    attachment_path: Optional[str] = None     # the Markdown, when MCP_GMAIL_ATTACH_REPORT
    attachment_name: Optional[str] = None

class ToolOutcome(BaseModel):
    """Structured result an MCP server tool returns (never a raw exception across the
    boundary). retryable classifies the failure for the client's retry logic (D7)."""
    ok: bool
    resource_ref: Optional[str] = None        # Drive webViewLink / Gmail message id (D12: NOT persisted)
    error_message: Optional[str] = None
    retryable: bool = False

class DeliveryResult(BaseModel):
    """What a client wrapper returns to the orchestrator (post-retry, terminal)."""
    service: str                              # "drive" | "gmail"
    ok: bool
    resource_ref: Optional[str] = None
    error_message: Optional[str] = None
```

---

### MCP Servers (wrap google-api-python-client)

New package `backend/app/delivery/mcp_servers/`. Each server is a **thin** MCP server
(built with the `mcp` SDK's server API) exposing exactly one tool, launched by the
client over **stdio** (`python -m app.delivery.mcp_servers.drive_server`). The servers
are the only place Google OAuth + `google-api-python-client` are touched (D10).

#### [NEW] `backend/app/delivery/mcp_servers/__init__.py`
Package marker + docstring stating these are the Drive/Gmail MCP servers (constitution
§2 permits Drive+Gmail MCP only).

#### [NEW] `backend/app/delivery/mcp_servers/google_auth.py`
```python
def load_credentials(credentials_path: str, token_path: str) -> Credentials:
    """Load the cached OAuth token; refresh it via google.auth.transport.requests.Request
    if expired and a refresh token exists. Raises CredentialsError if the token is
    missing or unrefreshable (no interactive consent at runtime — D9)."""

def build_drive_service(creds) -> Resource:   # googleapiclient.discovery.build("drive","v3")
def build_gmail_service(creds) -> Resource:   # build("gmail","v1")
```
Pure Google-side; imports `google.oauth2.credentials`, `google.auth.transport.requests`,
`googleapiclient.discovery`. **No** MCP, no ContractState.

#### [NEW] `backend/app/delivery/mcp_servers/drive_server.py`
An MCP server exposing tool **`upload_file`** (args validated against `DriveUploadRequest`
shape). Handler logic:
- `load_credentials(...)` → `build_drive_service(...)`.
- **Overwrite-in-place (D6):** query `files().list(q="name='{file_name}' and '{folder}' in parents and trashed=false")`;
  if a match exists → `files().update(fileId=..., media_body=MediaFileUpload(path))`,
  else `files().create(body={name, parents:[folder] if folder else []}, media_body=..., fields="id,webViewLink")`.
- On success → `ToolOutcome(ok=True, resource_ref=webViewLink)`.
- On `googleapiclient.errors.HttpError` → classify: 5xx / 429 → `retryable=True`;
  401/403/400/404 → `retryable=False`; return `ToolOutcome(ok=False, ...)` — **never
  raise across the tool boundary** (Edge Case 8). On `CredentialsError` →
  `ToolOutcome(ok=False, retryable=False, error_message="auth: ...")` (Edge Case 9).

#### [NEW] `backend/app/delivery/mcp_servers/gmail_server.py`
An MCP server exposing tool **`send_message`** (args validated against `GmailSendRequest`).
Handler logic:
- `load_credentials(...)` → `build_gmail_service(...)`.
- Build a MIME message (`email.mime.multipart.MIMEMultipart` + `MIMEText` body +
  optional `MIMEApplication` attachment from `attachment_path`), base64url-encode, then
  `users().messages().send(userId="me", body={"raw": ...})`.
- Success → `ToolOutcome(ok=True, resource_ref=message_id)`; `HttpError` classified as
  above; oversized attachment (413 / size error) → `retryable=False` with a size message
  (Edge Case 11). Never raises across the boundary.

> **Server construction altitude.** Exact `mcp` server-API surface (tool registration
> decorator, `stdio_server()` run loop) is followed from the installed `mcp` SDK version
> at implement time; the contract this plan pins is: **one tool per server, args per the
> Pydantic request shapes, results as `ToolOutcome`, errors never cross the boundary as
> exceptions.**
>
> **Blocking-call discipline.** `google-api-python-client`'s `.execute()` (and the auth
> file/network I/O in `load_credentials`/`build_*_service`) are **synchronous, blocking**.
> The `async def _handle_*` tool bodies wrap them in `await asyncio.to_thread(...)` so a
> real stdio server never blocks its event loop. Tests still `await` the handlers, so the
> test matrix is unchanged — but the servers must be written this way to be correct.

---

### MCP Clients (open a session, call the tool, retry)

New package `backend/app/delivery/mcp_clients/`.

#### [NEW] `backend/app/delivery/mcp_clients/__init__.py`
Re-exports `upload_report_to_drive`, `send_report_via_gmail`.

#### [NEW] `backend/app/delivery/mcp_clients/session.py`
Shared async helper that spawns a server over stdio and calls one tool with the
timeout + retry policy (single source of truth for D7):
```python
async def call_tool_with_retry(server_module: str, tool_name: str, arguments: dict,
                               *, timeout_seconds: int, max_retries: int) -> ToolOutcome:
    """Open a stdio ClientSession to `python -m <server_module>`, call `tool_name` once
    per attempt under asyncio.wait_for(timeout_seconds). Retry on a retryable ToolOutcome
    OR on TimeoutError / connection error, up to max_retries with exponential backoff
    (e.g. 0.5·2^n s). Return the terminal ToolOutcome. NEVER raises — a hard failure
    becomes ToolOutcome(ok=False, retryable=False, error_message=...)."""
```
Uses `mcp.client.stdio.stdio_client` + `mcp.ClientSession`; parses the tool result back
into `ToolOutcome`. Mirrors the timeout-bounding discipline of `web_retriever.py`
(there via `concurrent.futures`; here via `asyncio.wait_for`, since MCP is async).

#### [NEW] `backend/app/delivery/mcp_clients/drive_client.py`
```python
async def upload_report_to_drive(file_path, file_name, mime_type, folder_id,
                                 *, timeout_seconds, max_retries) -> DeliveryResult:
    """Validate a DriveUploadRequest, call the drive server's upload_file tool via
    call_tool_with_retry, map ToolOutcome → DeliveryResult(service='drive'). Never raises."""
```

#### [NEW] `backend/app/delivery/mcp_clients/gmail_client.py`
```python
async def send_report_via_gmail(to, subject, body, attachment_path, attachment_name,
                                *, timeout_seconds, max_retries) -> DeliveryResult:
    """Validate a GmailSendRequest, call the gmail server's send_message tool, map to
    DeliveryResult(service='gmail'). Never raises."""
```

---

### Delivery Step (orchestrator — the public entrypoint)

#### [NEW] `backend/app/delivery/__init__.py`
Re-exports `deliver_report`, `deliver_report_sync`.

#### [NEW] `backend/app/delivery/delivery_step.py`

Reads config (re-exposed as module-level names for monkeypatching, per the Node
2/4/5/6/7 precedent), orchestrates the two channels, builds `mcp_delivery_status`.

```python
import app.config as _config  # module import so tests can monkeypatch

logger = logging.getLogger("contractsentinel.delivery")

# Re-exposed for monkeypatching (bare-name reads in logic):
MCP_DELIVERY_ENABLED   = _config.MCP_DELIVERY_ENABLED
MCP_DRIVE_ENABLED      = _config.MCP_DRIVE_ENABLED
MCP_GMAIL_ENABLED      = _config.MCP_GMAIL_ENABLED
MCP_DELIVERY_RECIPIENT = _config.MCP_DELIVERY_RECIPIENT
MCP_DRIVE_FOLDER_ID    = _config.MCP_DRIVE_FOLDER_ID
MCP_DRIVE_UPLOAD_FORMATS = _config.MCP_DRIVE_UPLOAD_FORMATS
MCP_GMAIL_ATTACH_REPORT  = _config.MCP_GMAIL_ATTACH_REPORT
MCP_DELIVERY_TIMEOUT_SECONDS = _config.MCP_DELIVERY_TIMEOUT_SECONDS
MCP_DELIVERY_MAX_RETRIES     = _config.MCP_DELIVERY_MAX_RETRIES
```

**Async flow (`async def deliver_report(state, *, recipient: Optional[str] = None) -> dict`):**
```
1.  if not MCP_DELIVERY_ENABLED (or both channels disabled):
        log info; return {"mcp_delivery_status": {}}       # no-op, no entries (Edge Case 10, D13)
2.  report_path = state.get("report_path"); document_id = state.get("document_id","unknown")
    md_path = Path(report_path) if report_path else None
    json_path = md_path.with_suffix(".json") if md_path else None
3.  # Guard: nothing to deliver (D13 → FAILED for each ENABLED channel, no network call)
    if report_path is None or not md_path.exists():
        reason = "no report_path (Node 7 write failed)" if report_path is None else "report file not found"
        return {"mcp_delivery_status": _all_enabled_failed(reason)}   # AC-18/19, Edge Case 1/2
4.  summary = _load_summary(json_path)     # parse JSON sibling → ContractReport.summary; None on miss (Edge Case 4)
5.  status = {}
    # ── Drive first (so Gmail can embed the link) ──
    drive_ref = None
    if MCP_DRIVE_ENABLED:
        result = await _deliver_drive(md_path, json_path, document_id)   # uploads MCP_DRIVE_UPLOAD_FORMATS
        status["drive"] = _to_info(result)
        if result.ok: drive_ref = result.resource_ref
    # ── Gmail ──
    if MCP_GMAIL_ENABLED:
        to = recipient or MCP_DELIVERY_RECIPIENT
        if not to:
            status["gmail"] = _failed_info("no recipient configured")    # D13, Edge Case 3 — Drive still ran
        else:
            subject, body = _compose_email(document_id, state, summary, drive_ref)  # counts from summary; link iff drive_ref
            attach = str(md_path) if MCP_GMAIL_ATTACH_REPORT else None
            result = await send_report_via_gmail(to, subject, body, attach, md_path.name,
                        timeout_seconds=MCP_DELIVERY_TIMEOUT_SECONDS, max_retries=MCP_DELIVERY_MAX_RETRIES)
            status["gmail"] = _to_info(result)
6.  logger.info("MCP delivery completed", extra={... per-channel ok flags, elapsed ...})   # D11 — logs only
7.  return {"mcp_delivery_status": status}      # the ONLY state key written (spec §2.2, AC-10)
```

**Helpers:**
- `_to_info(result: DeliveryResult) -> dict` → `{"status": MCPDeliveryStatus.SUCCESS if
  result.ok else MCPDeliveryStatus.FAILED, "error_message": result.error_message,
  "delivered_at": _now_iso() if result.ok else None}`. **Only SUCCESS/FAILED — never
  PENDING** (D11a).
- `_failed_info(msg)` → `{"status": MCPDeliveryStatus.FAILED, "error_message": msg,
  "delivered_at": None}`.
- `_all_enabled_failed(reason)` → a `_failed_info(reason)` entry for **each enabled**
  channel only (config-disabled → no entry, D13).
- `_load_summary(json_path)` → `ContractReport.model_validate_json(json_path.read_text())
  .summary`; on `FileNotFoundError`/`ValidationError`/`OSError` → `None` + warning
  (Edge Case 4). **Reuses feature-009's `app/models/report.py` model** — no re-derivation
  from `clauses` (D5).
- `_deliver_drive(md_path, json_path, document_id)` → for each ext in
  `MCP_DRIVE_UPLOAD_FORMATS`, resolve the file + mime, call `upload_report_to_drive`.
  A channel is `ok` iff every requested-format upload succeeded; returns the Markdown's
  `resource_ref` for the email link. (Uploading the `.md` is what `drive_ref` links to.)
- `_compose_email(...)` → subject
  `"ContractSentinel report — {original_filename}: N findings (H high / M med / L low)"`
  when `summary` present, else a generic subject (Edge Case 4); body = short summary +
  the Drive link **iff** `drive_ref` (spec AC-5), always noting the attachment.
- `deliver_report_sync(state, *, recipient=None) -> dict` → `asyncio.run(deliver_report(...))`.

**Key invariants (testable):**
- Returns **only** `{"mcp_delivery_status": ...}` — no `current_node`, no
  `node_timings`, no `processing_completed_at`, no `error_count`, no Node 1–7 key
  (D8/D11, AC-10/11).
- Keys ⊆ `{"drive","gmail"}`; each value has exactly `{status, error_message,
  delivered_at}` (AC-7); `status` ∈ `{SUCCESS, FAILED}` only (AC-8, D11a).
- Config-disabled channel → **no** key; enabled-but-cannot-run → `FAILED` key (D13,
  AC-9/20).
- Never raises: a channel exception is contained by the client wrapper → `FAILED`
  (AC-12/13/14).

**Graph builder is untouched — literally.** `builder.py` is **not modified at all**: no
`deliver_report` import, no wiring, and no comment either (D1's "zero changes" is taken
literally so `test_delivery_does_not_touch_graph` can assert it byte-for-byte). Where
delivery fits relative to `report → END` is documented here in the spec/plan, not in the
builder source.

---

### Unit Tests

All Google network + all MCP sessions are **mocked**; no live OAuth. Async tests use
`pytest-asyncio` (`002` §3h).

#### [NEW] `backend/tests/unit/test_delivery_models.py`
| Test | Verifies |
|------|----------|
| `test_tool_outcome_defaults` | `ToolOutcome` defaults `ok`/`retryable`; `resource_ref`/`error_message` default `None` |
| `test_requests_validate_required_fields` | `DriveUploadRequest`/`GmailSendRequest` require their mandatory fields → `ValidationError` when missing |
| `test_delivery_result_service_literal` | `DeliveryResult.service` carries `"drive"`/`"gmail"` |

#### [NEW] `backend/tests/unit/test_delivery_step.py`
Orchestrator tests — `mcp_clients.upload_report_to_drive` / `send_report_via_gmail`
patched with async stubs returning canned `DeliveryResult`s; `_load_summary` fed a real
fixture JSON in `tmp_path`.
| Test | Verifies |
|------|----------|
| `test_happy_path_both_channels` | Both stubs called; `mcp_delivery_status` has `drive`+`gmail`, both `SUCCESS`, `delivered_at` set (AC-1/7) |
| `test_status_keys_and_info_shape` | Keys ⊆ {drive,gmail}; each value exactly {status,error_message,delivered_at} (AC-7) |
| `test_never_writes_pending` | No path yields `PENDING` in the returned status (AC-8, D11a) |
| `test_partial_update_only` | Return is exactly `{"mcp_delivery_status": ...}` — no current_node/node_timings/error_count/processing_completed_at/Node1–7 key (AC-10/11, D8/D11) |
| `test_drive_disabled_no_entry` | `MCP_DRIVE_ENABLED=False` → no drive call, no `drive` key; gmail present (AC-9, D13) |
| `test_gmail_disabled_no_entry` | symmetric (AC-9) |
| `test_both_disabled_noop` | `MCP_DELIVERY_ENABLED=False` → `{}`, no calls (Edge Case 10) |
| `test_drive_failure_does_not_block_gmail` | Drive stub returns `ok=False` → `drive` FAILED, `gmail` SUCCESS; no raise (AC-12) |
| `test_gmail_failure_keeps_drive_success` | Gmail stub fails after Drive ok → drive SUCCESS, gmail FAILED; no Drive rollback (AC-13) |
| `test_total_failure_non_fatal` | Both stubs fail → both FAILED, no raise (AC-14) |
| `test_no_report_path_fails_enabled_channels` | `report_path=None` → enabled channels FAILED, no client call (AC-18, Edge Case 1) |
| `test_missing_file_fails` | `report_path` set but file absent → FAILED, no client call (AC-19, Edge Case 2) |
| `test_missing_recipient_fails_gmail_drive_ok` | empty recipient → gmail FAILED "no recipient configured", drive uploaded (AC-20, Edge Case 3, D13) |
| `test_recipient_override_used` | `recipient=` arg overrides `MCP_DELIVERY_RECIPIENT` (D4) |
| `test_email_counts_from_json_sibling` | Subject/body counts equal the fixture JSON `summary`; never reads `clauses` (AC-6, D5) |
| `test_missing_json_sibling_generic_email` | JSON absent/corrupt → gmail still SUCCESS with generic subject (AC-21, Edge Case 4) |
| `test_gmail_body_links_drive_only_when_ok` | Drive ok → body has the link; drive failed/disabled → no link, still sent (AC-5) |
| `test_drive_uploads_configured_formats` | default → 2 uploads (.md,.json); `("md",)` → 1 (AC-2) |
| `test_drive_filename_matches_report_basename` | upload names = `Path(report_path).name` (`.md`) and its `.json` sibling — i.e. the basenames Node 7 already wrote (`{document_id}.md/.json`); the step does **not** re-import the Node-7 filename templates (AC-3, D6) |
| `test_config_values_read_not_hardcoded` | recipient/folder/formats/timeout/retry read from monkeypatched module names (AC-15) |
| `test_sync_wrapper_runs` | `deliver_report_sync` returns the same result via `asyncio.run` |
| `test_redelivery_idempotent_state_shape` | Running the step twice → keys stay `{"drive","gmail"}`; `merge_dicts` over the two returns replaces per-service entries, no duplicates (AC-22, orchestrator-level) |

#### [NEW] `backend/tests/unit/test_mcp_clients.py`
Client wrappers — `call_tool_with_retry` patched (or the stdio session mocked) to return
scripted `ToolOutcome`s.
| Test | Verifies |
|------|----------|
| `test_drive_client_maps_outcome` | ok `ToolOutcome` → `DeliveryResult(service='drive', ok=True, resource_ref=...)` |
| `test_gmail_client_maps_outcome` | symmetric for gmail |
| `test_client_never_raises` | An exception inside the session → `DeliveryResult(ok=False, error_message=...)`, no raise |
| `test_timeout_becomes_failed` | `asyncio.wait_for` TimeoutError on every attempt → FAILED with a timeout message (AC-16) |
| `test_retryable_is_retried_with_backoff` | retryable ToolOutcome retried up to `max_retries` then FAILED; attempt count asserted (AC-17) |
| `test_non_retryable_fails_immediately` | `retryable=False` (auth/permission) → 1 attempt, immediate FAILED (AC-17, Edge Case 8) |
| `test_worst_case_attempts_bounded` | attempts ≤ `1 + max_retries` (AC-16 bound) |

#### [NEW] `backend/tests/unit/test_mcp_servers.py`
Server tool handlers — `google_auth.build_*_service` patched with a `MagicMock` Google
service; no network.
| Test | Verifies |
|------|----------|
| `test_drive_upload_creates_when_absent` | no existing file → `files().create` called; `ToolOutcome(ok=True, resource_ref=webViewLink)` |
| `test_drive_upload_updates_when_present` | existing same-name file → `files().update` (overwrite-in-place, D6) |
| `test_drive_httperror_5xx_retryable` | `HttpError` 503 → `ToolOutcome(ok=False, retryable=True)` |
| `test_drive_httperror_403_not_retryable` | 403 → `retryable=False` |
| `test_drive_creds_error_not_retryable` | `CredentialsError` → `ok=False, retryable=False, "auth: ..."` (Edge Case 9) |
| `test_gmail_send_builds_mime_and_sends` | `messages().send(userId="me", ...)` called; success → message id |
| `test_gmail_attaches_when_path_given` | attachment path → MIME has the attachment part |
| `test_gmail_oversized_not_retryable` | size error → `retryable=False` (Edge Case 11) |
| `test_server_never_raises_across_boundary` | any Google error → `ToolOutcome`, never a raised exception |

#### [NEW] `backend/tests/unit/test_google_auth.py`
| Test | Verifies |
|------|----------|
| `test_missing_token_raises_credentials_error` | absent token file → `CredentialsError` (no interactive flow, D9) |
| `test_expired_token_refreshed` | expired creds with refresh token → `Request`-based refresh invoked |
| `test_build_services` | `build("drive","v3")` / `build("gmail","v1")` called with creds |

#### [MODIFY] `backend/tests/unit/test_config.py`
| Test | Verifies |
|------|----------|
| `test_mcp_delivery_constants_match_spec` | all `MCP_*` + `GOOGLE_OAUTH_*` constants match spec §6 values/types |
| `test_mcp_delivery_no_llm_constant` | no `MCP_*_MODEL` / LLM / circuit-breaker constant exists |
| `test_mcp_upload_formats_are_report_extensions` | `MCP_DRIVE_UPLOAD_FORMATS` ⊆ {"md","json"} (matches Node-7 outputs) |

---

### Integration Tests

#### [NEW] `backend/tests/integration/test_delivery_integration.py`
End-to-end **without the graph** (delivery is post-terminal) and **without live
Google** — the MCP session is driven against **in-memory / stubbed servers** so the
real client→tool→result contract is exercised.
| Test | Verifies |
|------|----------|
| `test_deliver_after_report_terminal_state` | Given a terminal `ContractState` (real `report_path` from a Node-7 run in `tmp_path`) + stubbed servers, `deliver_report` returns `mcp_delivery_status` with SUCCESS entries and the report is "uploaded"/"sent" (arg capture) |
| `test_deliver_reads_real_report_json_summary` | The email subject counts equal a real Node-7-produced JSON sibling's `summary` (AC-6 end-to-end) |
| `test_delivery_does_not_touch_graph` | Importing/using delivery does not import or modify `builder.py`; the compiled graph still ends at `report → END` (D1) |
| `test_delivery_step_state_key_only` | Applying the returned partial dict via `001`'s `merge_dicts` reducer yields a valid `mcp_delivery_status`; no other state key touched |

> **Whole-pipeline note.** A future runner test (`report → deliver_report`) belongs to
> the runner/API feature (spec §5.5), not here — no runner exists yet. This suite proves
> the step consumes a genuine Node-7 terminal state correctly, which is the seam that
> matters for Phase 1.

---

## 3. Dependency & Import Map

```
app/config.py
    ├── typing (Optional)                 # NEW import for MCP_DRIVE_FOLDER_ID
    └── app.graph.state (RiskLevel)       # existing

app/delivery/models.py
    └── pydantic (BaseModel, Field)       # boundary transport types (constitution §4)

app/delivery/mcp_servers/google_auth.py
    ├── google.oauth2.credentials, google.auth.transport.requests   # 002 §g
    └── googleapiclient.discovery (build)                           # 002 §g
        # NO mcp, NO ContractState

app/delivery/mcp_servers/drive_server.py
app/delivery/mcp_servers/gmail_server.py
    ├── mcp (server API + stdio run loop)                           # 002 §g
    ├── googleapiclient.http (MediaFileUpload), googleapiclient.errors (HttpError)
    ├── email.mime.* + base64 (gmail only)
    ├── app.delivery.mcp_servers.google_auth (load_credentials, build_*_service)
    └── app.delivery.models (ToolOutcome, request shapes)
        # server-side ONLY — reads OAuth creds; NO ContractState

app/delivery/mcp_clients/session.py
    ├── asyncio
    ├── mcp (ClientSession), mcp.client.stdio (stdio_client, StdioServerParameters)
    └── app.delivery.models (ToolOutcome)

app/delivery/mcp_clients/drive_client.py
app/delivery/mcp_clients/gmail_client.py
    ├── app.delivery.mcp_clients.session (call_tool_with_retry)
    └── app.delivery.models (DriveUploadRequest/GmailSendRequest, DeliveryResult)

app/delivery/delivery_step.py
    ├── asyncio, logging, datetime, pathlib (stdlib)
    ├── app.config  (imported AS A MODULE; MCP constants re-exposed for monkeypatch)
    ├── app.graph.state (MCPDeliveryStatus)          # enum for status values
    ├── app.models.report (ContractReport)           # REUSE Node-7 model to read JSON summary (D5)
    └── app.delivery.mcp_clients (upload_report_to_drive, send_report_via_gmail)

app/graph/builder.py
    └── UNCHANGED (no delivery import; delivery is post-terminal — D1)
```

**New runtime imports vs. the stack:** `mcp`, `google-auth`, `google-auth-oauthlib`,
`google-auth-httplib2`, `google-api-python-client` — **all already in `002` §g / §4**
(deps lines 143–148). **No** `002` change, **no** new dependency (spec §5.9).

---

## 4. Implementation Order

TDD per constitution §7 — tests written and confirmed failing before implementation.

| Step | Action | Files |
|------|--------|-------|
| 0 | **Enable `asyncio_mode = "auto"`** (gates every async test below) | `pyproject.toml` |
| 1 | Config tests for MCP constants (confirm failing) | `tests/unit/test_config.py` |
| 2 | Add `# ── MCP delivery` block + `import os` / `Optional` imports; add `.gitignore` secrets line | `app/config.py`, `.gitignore` |
| 3 | Run config tests (pass) | — |
| 4 | Transport-model tests (failing) | `tests/unit/test_delivery_models.py` |
| 5 | Implement transport models | `app/delivery/models.py` |
| 6 | Run model tests (pass) | — |
| 7 | google_auth tests (failing) | `tests/unit/test_google_auth.py` |
| 8 | Implement `google_auth.py` | `app/delivery/mcp_servers/google_auth.py` |
| 9 | Server-handler tests (failing) | `tests/unit/test_mcp_servers.py` |
| 10 | Implement Drive + Gmail MCP servers | `app/delivery/mcp_servers/*.py` |
| 11 | Run server + auth tests (pass) | — |
| 12 | Client-wrapper tests (failing) | `tests/unit/test_mcp_clients.py` |
| 13 | Implement `session.py` + drive/gmail clients | `app/delivery/mcp_clients/*.py` |
| 14 | Run client tests (pass) | — |
| 15 | Orchestrator tests (failing) | `tests/unit/test_delivery_step.py` |
| 16 | Implement `delivery_step.py` (+ package `__init__`s) | `app/delivery/*.py` |
| 17 | Run orchestrator tests (pass) | — |
| 18 | Integration tests (stubbed servers, real Node-7 artifact) | `tests/integration/test_delivery_integration.py` |
| 19 | Full suite pass (all existing 365 + new) | all tests |

---

## 5. Design Decisions & Rationale

### Post-terminal step under `app/delivery/`, not a node (spec D1)
Placing the code in a new top-level package — not `app/graph/nodes/` — makes the "not
the 8th node" boundary *structural*: nothing here is registered with `StateGraph`, and
`builder.py` is untouched, so constitution §2's "exactly 7 nodes / 2 conditional edges"
invariant is preserved by construction, not just by convention.

### MCP client → local servers wrapping google-api-python-client (spec D10)
Honors `002` §g's "via the Model Context Protocol" and keeps the `mcp` dependency
load-bearing. The client/server split also puts **all** Google OAuth + API surface
behind the server boundary, so the delivery step (and its tests) never touch Google
directly — the step only knows MCP tools and `ToolOutcome`s. This is the same
"thin boundary helper that never raises" discipline the pipeline already uses for the
web retriever and the redline drafter, adapted to MCP's async session model.

### Per-channel, best-effort, non-fatal; no cross-channel circuit breaker (spec D3)
With only two channels and a post-graph position, the failure model is simpler than the
generative nodes': each channel is attempted independently, its outcome recorded in its
own `mcp_delivery_status` entry, and one failing never blocks/reverts the other. There
is no circuit breaker (that pattern amortizes many per-clause LLM calls; here there are
at most two calls). The on-disk report remains the source of truth (spec §1).

### Delivery failures → `mcp_delivery_status`, not `error_count` (spec D8)
`error_count` is the in-graph health counter (Nodes 4–7); this step runs after the graph
returns, so folding transport failures into it would conflate two lifecycles. All
delivery health is captured, per channel, in `mcp_delivery_status`.

### Per-attempt timeout + bounded backoff retry (spec D7, constitution §9)
`asyncio.wait_for(call_tool, MCP_DELIVERY_TIMEOUT_SECONDS)` bounds each attempt;
transient (server-classified `retryable=True`, or timeout/connection) errors retry with
exponential backoff up to `MCP_DELIVERY_MAX_RETRIES`; permanent (auth/permission/
malformed) fail immediately. Worst-case latency per channel is explicit:
`≈ (1 + MCP_DELIVERY_MAX_RETRIES) × MCP_DELIVERY_TIMEOUT_SECONDS`.

### Reuse the Node-7 Pydantic report model to read the summary (spec D5)
The email counts come from `ContractReport.model_validate_json(<sibling>).summary` —
reusing `app/models/report.py` rather than re-deriving from `clauses`, which the step
never reads. This keeps the Node-7/delivery boundary clean and the two features'
serialization contract in one place.

### Never write `PENDING`; state write is `mcp_delivery_status` only (spec D11/D11a)
The step is synchronous end-to-end per channel — an attempt either succeeds or fails
before the entry is written — so `PENDING` (an optimistic-then-flipped state) never
occurs; it is reserved for a future async/queued runner. No `current_node` /
`node_timings` is written because this is a step, not a node (timing → logs).

### Do not persist the Drive URL (spec D12)
`MCPDeliveryInfo` stays `{status, error_message, delivered_at}`; the Drive
`webViewLink`/Gmail message id live in `ToolOutcome.resource_ref` in-memory (used for the
email link, logged) but are dropped before the state write — no constitution §10 change
to `001`.

### Async primary entrypoint + sync wrapper
The `mcp` SDK and the future FastAPI runner are async, so `deliver_report` is `async`;
`deliver_report_sync` (`asyncio.run`) serves scripts/tests. Channels run sequentially in
one loop (Drive→Gmail for the link) but with independent outcomes.

### Logging strategy (spec §9-style)
Named logger `contractsentinel.delivery`. One `logger.info("MCP delivery completed",
extra={per-channel ok, resource kinds, elapsed})` roll-up per run; per-channel warnings
on failure. All observability is in logs — never added to `ContractState` (D11).

---

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OAuth token missing/expired at runtime | Channel can't authenticate | Server `load_credentials` refreshes if possible, else returns a non-retryable auth `ToolOutcome`; step records `FAILED`, never launches interactive consent (D9, Edge Case 9) |
| A Google API / MCP session error escapes as an exception | Step crashes after the graph already succeeded | Every layer is a never-raises boundary: server returns `ToolOutcome`, client returns `DeliveryResult`, orchestrator contains both; `test_*_never_raises` lock it (AC-12/13/14) |
| Hung upload/send (stuck socket) | Step blocks indefinitely | `asyncio.wait_for` per-attempt timeout; worst case bounded by retries (AC-16) |
| Drive link not shareable (permissions) | Email link dead | Attachment (`MCP_GMAIL_ATTACH_REPORT`) guarantees delivery; Drive still `SUCCESS` (the file uploaded); body omits link when no `resource_ref` (Edge Case 5) |
| Gmail attachment oversized | Send fails | Server returns non-retryable size error → gmail `FAILED`; Drive unaffected; link-only fallback deferred (spec §5.6, Edge Case 11) |
| Re-delivery proliferates Drive copies | Clutter | Overwrite-in-place by deterministic `{document_id}` name (list→update-or-create, D6); `merge_dicts` updates the per-service entry (Edge Case 7) |
| OAuth secrets committed to git | Credential leak | `data/secrets/` git-ignored (§2); paths point there; setup docs only |
| `mcp` SDK v2 breaking change | Build breaks on upgrade | `002` pins `mcp>=1.27,<2.0.0`; server-API surface followed from the installed version at implement time (§2 note) |
| Delivery accidentally wired as a graph node | Violates constitution §2 | Code lives outside `app/graph/nodes/`; `builder.py` untouched; `test_delivery_does_not_touch_graph` locks it (D1) |
| Reading `clauses` to build the email (scope creep) | Blurs Node-7/delivery boundary | Summary read from the JSON sibling via the Node-7 model; `test_email_counts_from_json_sibling` asserts `clauses` is not the source (D5) |

---

## 7. Out of Scope for This Plan

- **The trigger / runner / API layer that invokes `deliver_report`** — *when* delivery
  runs is the future runner/API feature's job (spec §5.5); this plan ships the callable
  + its integration contract.
- **One-time OAuth consent/setup** — obtaining the token file is a deployment step
  documented separately; the runtime only *reads* it (spec §5.4, D9).
- **Any MCP integration beyond Drive + Gmail** — PERMANENTLY CUT (spec §5.3).
- **Persisting the Drive URL / Gmail id in state** — deferred; no `001` change (spec
  §5.8, D12).
- **Attachment-size fallback, Drive versioning/retention, delivery history/audit** —
  Phase-2 (spec §5.6).
- **Per-user / multi-tenant recipients, RBAC** — PERMANENTLY CUT; single configured
  recipient (spec §5.7, D4).
- **Any change to `builder.py` or the 7-node graph** — delivery is post-terminal (D1).
- **Any `002-tech-stack.md` change** — the MCP + OAuth stack is already listed (spec
  §5.9).
- **Re-rendering / re-scoring / re-validating the report** — Node 7 / 5 / 4 / 3 own
  those; delivery is transport only (spec §5.2, D5).

---

## 8. Reference: Constitution & Spec Traceability

- **Constitution §2** — Drive+Gmail is the one permitted MCP carve-out; delivery is the
  reserved "MCP delivery step", not an 8th node → code under `app/delivery/`, no
  `builder.py` change (this plan §1, §2, §5; D1/D10).
- **Constitution §3** — all toggles/paths/recipient/timeout/retry in `app/config.py`
  (§2 config block; AC-15).
- **Constitution §4** — Pydantic at the MCP/HTTP boundary (`app/delivery/models.py`),
  never in graph state; state key is the `001` `MCPDeliveryInfo` TypedDict (§2, §5).
- **Constitution §5** — partial-update rule: `deliver_report` returns only
  `mcp_delivery_status` (§2 orchestrator; AC-10).
- **Constitution §6** — state minimality: the report body stays on disk (Node 7's
  files); delivery adds only the bounded per-service status (no body, no Drive URL — D12).
- **Constitution §7** — TDD order (§4).
- **Constitution §8** — model-separation: N/A (zero LLM/embedding calls); the step is
  pure transport.
- **Constitution §9** — local/network latency: explicit per-attempt timeout + bounded
  backoff retry on every MCP tool call (§2 session helper, §5; AC-16/17).
- **Constitution §10** — **no** `001` schema change: `mcp_delivery_status` /
  `MCPDeliveryInfo` are pre-reserved and used as-is; `PENDING` left unwritten, no
  `resource_ref` added (D11a/D12).
- **Constitution §11** — branch `feature/010-mcp-delivery` (top of this file).
- **Spec §8a D1–D13** — resolved decisions carried into this plan §1.
