# MCP Delivery Implementation Tasks

Reference documents:
- Spec: `specs/010-mcp-delivery/spec.md`
- Plan: `specs/010-mcp-delivery/plan.md`
- State schema: `specs/001-contract-state-schema.md`
- Tech stack: `specs/002-tech-stack.md`
- Constitution: `specs/000-constitution.md`

All file paths below are relative to `backend/` unless stated otherwise.

**Workflow reminders:**
- Follow TDD per constitution §7 — write tests, confirm they FAIL, then implement to make them PASS.
- This feature is the **MCP delivery step** — the pipeline's **post-terminal transport layer**. It takes the report ReportAgent (Node 7) wrote to disk (`report_path` + its JSON sibling) and delivers it over **Google Drive** and **Gmail** — the only two MCP integrations the constitution permits (§2 PERMANENTLY CUT).
- **It is NOT a graph node.** Constitution §2 fixes the graph at exactly 7 nodes / 2 conditional edges ending at `report → END`. `001` §3 labels `mcp_delivery_status` "Added by MCP delivery **step**". This feature makes **ZERO** changes to `builder.py` — no `add_node`, no `add_edge`, no `add_conditional_edges`, and no comment either (D1). All new code lives under a **new top-level package `app/delivery/`**, deliberately **outside** `app/graph/nodes/`.
- **No existing test should change.** Because the graph is untouched, the current 365 tests (features 003–009) must remain **byte-for-byte unmodified** and still pass. Unlike feature 009, there are **NO regression fix-ups** — if an existing test breaks, something is wrong; do not "fix" it by editing the graph.
- **The step writes ONLY `mcp_delivery_status`** to state (constitution §5, spec §2.2, AC-10). It writes NO `current_node`, NO `node_timings`, NO `processing_completed_at`, NO `error_count`, and no Node 1–7 key.
- **Zero LLM / embedding calls** — pure transport. No `ollama`, no model/timeout/circuit-breaker LLM constant.
- All toggles/paths/recipient/timeout/retry live in `app/config.py` per constitution §3 — never hardcode inline.
- **Boundary Pydantic (constitution §4):** MCP tool request/response payloads are Pydantic types in `app/delivery/models.py`, validated before the call, never stored in graph state. The state key `mcp_delivery_status` is the `001` `MCPDeliveryInfo` TypedDict, built as a plain dict by the orchestrator.
- **Never-raises boundaries:** server tool → `ToolOutcome`; client wrapper → `DeliveryResult`; orchestrator contains both. A Google/MCP error never crosses a layer as an exception. This mirrors the existing `web_retriever.py` / `redline_drafter.py` discipline.
- **First async code in the repo** — the `mcp` SDK is asyncio-based. `deliver_report` is `async`; a sync wrapper `deliver_report_sync` is provided. `asyncio_mode = "auto"` MUST be enabled first (Task 1) or the async suite silently won't run.

**The thirteen locked design decisions (spec §8a D1–D13):**
- **D1** — post-terminal step, NOT a node; no `builder.py` change; code under `app/delivery/`.
- **D2** — Drive upload + Gmail email; Gmail links to the Drive copy when available and always attaches the Markdown.
- **D3** — per-channel, best-effort, independent, non-fatal: each service writes its own `mcp_delivery_status[service]` entry; one failing never blocks/reverts the other; the step never raises.
- **D4** — recipient from `MCP_DELIVERY_RECIPIENT` (env-overridable via `CONTRACTSENTINEL_DELIVERY_RECIPIENT`), runner may override per call.
- **D5** — transport only: reads `report_path` + the JSON sibling; NEVER reads `clauses`. Email summary comes from parsing the JSON sibling with the reused Node-7 `ContractReport` model.
- **D6** — deterministic Drive filename = the on-disk basename Node 7 wrote (`Path(report_path).name`); re-delivery overwrites in place.
- **D7** — explicit **per-attempt** timeout + bounded **exponential-backoff** retry on every MCP tool call.
- **D8** — delivery failures recorded in `mcp_delivery_status`, NEVER `error_count`.
- **D9** — OAuth consent/setup out of scope; the server only *reads* a provisioned credential and fails gracefully (never launches interactive consent at runtime).
- **D10** — transport is MCP client → local Drive/Gmail MCP servers wrapping `google-api-python-client`; OAuth lives at the server boundary.
- **D11** — no `current_node` / no `node_timings` written; timing to logs only. **D11a** — writes only `SUCCESS`/`FAILED`, never `PENDING`.
- **D12** — Drive URL / Gmail message id NOT persisted in state (`MCPDeliveryInfo` unchanged; no `001` §10 change).
- **D13** — config-disabled channel → **no** `mcp_delivery_status` entry; enabled-but-cannot-run → **`FAILED`** entry.
- Branch: `feature/010-mcp-delivery` per constitution §11.

---

## Task 0: Create feature branch

- [ ] Confirm `specs/010-mcp-delivery/spec.md`, `plan.md`, and `tasks.md` all exist and are approved (constitution §1 / §11 gate).
- [ ] From an up-to-date `main`, create and check out `feature/010-mcp-delivery` (the `git-start` skill does this mechanically).

**Why**: Per constitution §11, every feature is developed on its own branch. ReportAgent (009) is already merged to `main`.

**Verify**: `git branch --show-current` prints `feature/010-mcp-delivery`.

**Note**: The working tree has an untracked `specs/010-mcp-delivery/`. Confirm with the user whether the spec docs should be committed before branching, so 010 starts from a clean tree (same as prior features).

---

## Task 1: Enable pytest-asyncio auto mode (GATING — do first)

- [ ] Open `pyproject.toml` (in `backend/`). Confirm there is currently **no** `[tool.pytest.ini_options]` section (this is the repo's first async code).
- [ ] Add:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
# Auto-collect bare `async def test_*` (first async tests in the repo — feature 010).
# Without this, pytest-asyncio's default strict mode skips/errors them silently.
```

**Why**: `pytest-asyncio` (a declared dev dep, `002` §3h) defaults to **strict** mode, which skips/errors any `async def test_*` lacking `@pytest.mark.asyncio`. Every client/orchestrator/integration test below is a bare `async def`. This gates them all.

**Verify**: Add a throwaway `async def test__asyncio_smoke(): assert True` to any test file, run `python -m pytest -k _asyncio_smoke -v`, confirm it **runs and passes** (not "skipped"/"errored"), then delete it. The existing 365 tests must still pass.

---

## Task 2: Write config tests for the MCP delivery constants (confirm FAILING)

- [ ] Open `tests/unit/test_config.py`
- [ ] Add 3 new test functions:

```python
def test_mcp_delivery_constants_match_spec():
    """Verify MCP delivery constants match specs/010 §6."""
    from app import config
    assert config.MCP_DELIVERY_ENABLED is True
    assert config.MCP_DRIVE_ENABLED is True
    assert config.MCP_GMAIL_ENABLED is True
    assert isinstance(config.MCP_DELIVERY_RECIPIENT, str)      # env-derived, "" default
    assert config.MCP_DRIVE_FOLDER_ID is None
    assert config.MCP_DRIVE_UPLOAD_FORMATS == ("md", "json")
    assert config.MCP_GMAIL_ATTACH_REPORT is True
    assert config.MCP_DELIVERY_TIMEOUT_SECONDS == 60
    assert config.MCP_DELIVERY_MAX_RETRIES == 2
    assert config.GOOGLE_OAUTH_CREDENTIALS_PATH == "data/secrets/google_credentials.json"
    assert config.GOOGLE_OAUTH_TOKEN_PATH == "data/secrets/google_token.json"


def test_mcp_delivery_no_llm_constant():
    """Delivery makes no LLM call — no model/timeout-LLM/circuit-breaker constant."""
    from app import config
    assert not hasattr(config, "MCP_DELIVERY_MODEL_NAME")
    assert not hasattr(config, "MCP_DELIVERY_LLM_CIRCUIT_BREAKER_THRESHOLD")


def test_mcp_upload_formats_are_report_extensions():
    """Uploaded formats must be a subset of Node-7's output extensions {md, json}."""
    from app import config
    assert set(config.MCP_DRIVE_UPLOAD_FORMATS) <= {"md", "json"}
```

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — the first and third must FAIL (`AttributeError`/`ImportError` — constants don't exist yet); the second may already PASS. All existing config tests (Ingest → Report) must still PASS.

---

## Task 3: Add the MCP delivery constants to config + .gitignore

- [ ] Open `app/config.py`
- [ ] Add two imports at the top (config currently imports only `from app.graph.state import RiskLevel`): `import os` (for the recipient env var) and `from typing import Optional` (for `MCP_DRIVE_FOLDER_ID`).
- [ ] Append a new `# ── MCP delivery` block at the end of the file (pure addition — no rename):

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
# Drive proceeds (D13). os.getenv is evaluated at import; AC-15 is tested by
# monkeypatching the re-exposed name on the delivery-step module, not the environment.

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

- [ ] Do NOT add any LLM/model/circuit-breaker constant.
- [ ] Open the repo-root `.gitignore` and add `backend/data/secrets/` beside the existing `backend/data/reports/` line (`.gitignore:33`) so OAuth credentials/token are never committed.

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — all config tests (through MCP delivery) must PASS. Run `git status --porcelain` and confirm nothing under `data/secrets/` would be tracked.

---

## Task 4: Write unit tests for the transport Pydantic models (confirm FAILING)

- [ ] Create file `tests/unit/test_delivery_models.py`
- [ ] The import `from app.delivery.models import DriveUploadRequest, GmailSendRequest, ToolOutcome, DeliveryResult` will fail until Task 5 — expected for TDD.
- [ ] Write these 3 test functions (plan §2 model matrix):

| Test function | Verifies |
|---------------|----------|
| `test_tool_outcome_defaults` | `ToolOutcome(ok=True)` defaults `retryable is False`, `resource_ref is None`, `error_message is None` |
| `test_requests_validate_required_fields` | `DriveUploadRequest()` / `GmailSendRequest()` without their required fields raise `pydantic.ValidationError`; a fully-specified one constructs |
| `test_delivery_result_service_literal` | `DeliveryResult(service="drive", ok=True)` carries `service == "drive"`; `service` accepts `"gmail"` too |

**Verify**: Run `python -m pytest tests/unit/test_delivery_models.py -v` — all 3 must FAIL (ImportError).

---

## Task 5: Implement the transport Pydantic models

- [ ] Create the package: `app/delivery/__init__.py` (docstring only for now — the re-exports of `deliver_report` / `deliver_report_sync` are added in Task 13; a bare docstring keeps imports clean meanwhile).
- [ ] Create file `app/delivery/models.py`.
- [ ] **Imports**: `from typing import Optional`; `from pydantic import BaseModel` (**no `Field`** — none of the four models use it; importing it would trip `ruff` F401 in Task 16). **No `app.graph.state` import**, no MCP, no Google — these are pure transport types.
- [ ] Define exactly as plan §2 specifies:

```python
class DriveUploadRequest(BaseModel):
    file_path: str
    file_name: str
    mime_type: str
    folder_id: Optional[str] = None

class GmailSendRequest(BaseModel):
    to: str
    subject: str
    body: str
    attachment_path: Optional[str] = None
    attachment_name: Optional[str] = None

class ToolOutcome(BaseModel):
    ok: bool
    resource_ref: Optional[str] = None        # Drive webViewLink / Gmail message id (D12: NOT persisted)
    error_message: Optional[str] = None
    retryable: bool = False

class DeliveryResult(BaseModel):
    service: str                              # "drive" | "gmail"
    ok: bool
    resource_ref: Optional[str] = None
    error_message: Optional[str] = None
```

- [ ] Module docstring: these are **boundary transport models** (constitution §4), validated before/after the MCP tool call, never stored in graph state.

**Verify**: Run `python -m pytest tests/unit/test_delivery_models.py -v` — all 3 must PASS.

---

## Task 6: Write unit tests for `google_auth` (confirm FAILING)

- [ ] Create file `tests/unit/test_google_auth.py`
- [ ] The import `from app.delivery.mcp_servers.google_auth import load_credentials, build_drive_service, build_gmail_service, CredentialsError` will fail until Task 7.
- [ ] Patch the Google libs (`google.oauth2.credentials.Credentials`, `google.auth.transport.requests.Request`, `googleapiclient.discovery.build`) with `unittest.mock`. No network, no real token files (use `tmp_path` for fake paths).
- [ ] Write these 3 test functions (plan §2 auth matrix):

| Test function | Verifies |
|---------------|----------|
| `test_missing_token_raises_credentials_error` | A non-existent token path → `load_credentials` raises `CredentialsError` (no interactive consent — D9, Edge Case 9) |
| `test_expired_token_refreshed` | A creds object with `expired=True` + a `refresh_token` → `creds.refresh(Request())` is invoked and the refreshed creds returned |
| `test_build_services` | `build_drive_service(creds)` calls `build("drive", "v3", credentials=creds)`; `build_gmail_service(creds)` calls `build("gmail", "v1", credentials=creds)` |

**Verify**: Run `python -m pytest tests/unit/test_google_auth.py -v` — all 3 must FAIL (ImportError).

---

## Task 7: Implement `google_auth.py`

- [ ] Create package marker `app/delivery/mcp_servers/__init__.py` with a docstring stating these are the Drive/Gmail MCP servers (constitution §2 permits Drive+Gmail MCP only).
- [ ] Create file `app/delivery/mcp_servers/google_auth.py`.
- [ ] **Imports**: `import os`; `from google.oauth2.credentials import Credentials`; `from google.auth.transport.requests import Request`; `from googleapiclient.discovery import build`. **No MCP, no ContractState.**
- [ ] Define `class CredentialsError(Exception): ...`.
- [ ] `load_credentials(credentials_path: str, token_path: str) -> Credentials`:
  - If `token_path` does not exist → raise `CredentialsError("token not found; run one-time OAuth setup")` (D9 — never launch interactive consent).
  - Load `Credentials.from_authorized_user_file(token_path, SCOPES)` (SCOPES = Drive file + Gmail send scopes as module constants).
  - If `creds.expired and creds.refresh_token` → `creds.refresh(Request())`; if refresh fails / no refresh token and creds invalid → raise `CredentialsError`.
  - Return `creds`.
- [ ] `build_drive_service(creds)` → `build("drive", "v3", credentials=creds)`; `build_gmail_service(creds)` → `build("gmail", "v1", credentials=creds)`.

**Verify**: Run `python -m pytest tests/unit/test_google_auth.py -v` — all 3 must PASS.

---

## Task 8: Write unit tests for the MCP server tool handlers (confirm FAILING)

- [ ] Create file `tests/unit/test_mcp_servers.py`
- [ ] Test the **tool handler functions** directly (factor each server's tool body into a testable `async def _handle_upload(req)` / `_handle_send(req)` so it can be called without spinning up a stdio server). Patch `google_auth.build_drive_service` / `build_gmail_service` to return a `MagicMock` Google service; assert on the mocked call chain. No network.
- [ ] Write these 9 test functions (plan §2 server matrix):

| Test function | Verifies |
|---------------|----------|
| `test_drive_upload_creates_when_absent` | `files().list(...)` returns no match → `files().create(...)` called; result `ToolOutcome(ok=True, resource_ref=<webViewLink>)` |
| `test_drive_upload_updates_when_present` | `files().list(...)` returns an existing same-name file → `files().update(fileId=..., media_body=...)` called (overwrite-in-place, D6, AC-22) |
| `test_drive_httperror_5xx_retryable` | A `googleapiclient.errors.HttpError` with status 503 → `ToolOutcome(ok=False, retryable=True)`, no raise |
| `test_drive_httperror_403_not_retryable` | status 403 → `ToolOutcome(ok=False, retryable=False)` |
| `test_drive_creds_error_not_retryable` | `CredentialsError` from `load_credentials` → `ToolOutcome(ok=False, retryable=False, error_message startswith "auth")` (Edge Case 9) |
| `test_gmail_send_builds_mime_and_sends` | `users().messages().send(userId="me", body={"raw": ...})` called; success → `ToolOutcome(ok=True, resource_ref=<message id>)` |
| `test_gmail_attaches_when_path_given` | With an `attachment_path`, the built MIME contains an attachment part named `attachment_name` |
| `test_gmail_oversized_not_retryable` | A size/413 error → `ToolOutcome(ok=False, retryable=False)` (Edge Case 11) |
| `test_server_never_raises_across_boundary` | Any Google exception inside the handler → a `ToolOutcome`, never a raised exception |

**Verify**: Run `python -m pytest tests/unit/test_mcp_servers.py -v` — all 9 must FAIL (ImportError).

---

## Task 9: Implement the Drive + Gmail MCP servers

- [ ] Create `app/delivery/mcp_servers/drive_server.py` and `app/delivery/mcp_servers/gmail_server.py`.
- [ ] Each server: registers exactly **one** tool with the `mcp` SDK server API (Drive: `upload_file`; Gmail: `send_message`) and runs a `stdio` loop under `if __name__ == "__main__":` (so the client can launch it via `python -m app.delivery.mcp_servers.drive_server`). Factor the tool body into a standalone `async def _handle_upload(req: DriveUploadRequest) -> ToolOutcome` / `_handle_send(req: GmailSendRequest) -> ToolOutcome` (imported by the tests).
- [ ] **Drive `_handle_upload`** (plan §2):
  - `creds = load_credentials(GOOGLE_OAUTH_CREDENTIALS_PATH, GOOGLE_OAUTH_TOKEN_PATH)` (read config here, server-side); `svc = build_drive_service(creds)`.
  - Query existing file by name in folder (`files().list(q=..., fields="files(id)")`); if found → `files().update(fileId=..., media_body=MediaFileUpload(req.file_path, mimetype=req.mime_type), fields="id,webViewLink")`; else `files().create(body={"name": req.file_name, "parents": [req.folder_id] if req.folder_id else []}, media_body=..., fields="id,webViewLink")`.
  - Success → `ToolOutcome(ok=True, resource_ref=result["webViewLink"])`.
  - `except HttpError as e:` classify status (5xx/429 → `retryable=True`; else `False`) → `ToolOutcome(ok=False, retryable=..., error_message=str(e))`. `except CredentialsError as e:` → `ToolOutcome(ok=False, retryable=False, error_message=f"auth: {e}")`. **Never raise.**
- [ ] **Gmail `_handle_send`** (plan §2):
  - `creds` → `svc = build_gmail_service(creds)`.
  - Build a MIME message (`email.mime.multipart.MIMEMultipart`, `MIMEText(req.body)`, optional `MIMEApplication` from `req.attachment_path` named `req.attachment_name`), base64url-encode → `raw`; `users().messages().send(userId="me", body={"raw": raw})`.
  - Success → `ToolOutcome(ok=True, resource_ref=sent["id"])`; `HttpError` classified as above (413/size → `retryable=False`); `CredentialsError` → auth outcome. **Never raise.**
- [ ] **Imports**: `asyncio`; `mcp` server API + stdio; `googleapiclient.http.MediaFileUpload`; `googleapiclient.errors.HttpError`; `email.mime.*` + `base64` (gmail); `app.delivery.mcp_servers.google_auth`; `app.delivery.models`; `import app.config as _config` for the OAuth paths.
- [ ] **Blocking-call discipline (correctness, not just test-passing):** `google-api-python-client`'s `.execute()` (and `load_credentials`/`build_*_service`, which do file/network I/O) are **synchronous, blocking** calls. Inside the `async def _handle_*` handlers, wrap them with `await asyncio.to_thread(...)` so a real stdio server never blocks its event loop. The tests still just `await` the handlers, so this doesn't change the test matrix — but the servers must be written this way to be correct under the real stdio run loop.

> **`mcp` server-API altitude:** follow the tool-registration + `stdio_server()` run-loop surface of the installed `mcp` SDK version (`002` pins `mcp>=1.27,<2.0.0`). The stable contract this feature depends on is: **one tool per server, args per the Pydantic request shapes, returns a `ToolOutcome`, errors never cross the boundary as exceptions.** The unit tests exercise the `_handle_*` bodies, not the stdio loop.

**Verify**: Run `python -m pytest tests/unit/test_mcp_servers.py tests/unit/test_google_auth.py -v` — all 12 must PASS.

---

## Task 10: Write unit tests for the MCP client wrappers (confirm FAILING)

- [ ] Create file `tests/unit/test_mcp_clients.py`
- [ ] The import `from app.delivery.mcp_clients import upload_report_to_drive, send_report_via_gmail` (and `from app.delivery.mcp_clients.session import call_tool_with_retry`) will fail until Task 11.
- [ ] Patch `call_tool_with_retry` (an `async` function) with an async stub returning scripted `ToolOutcome`s to test the wrapper mapping; separately test `call_tool_with_retry`'s own retry/timeout logic by patching the stdio session it opens (or by injecting a fake tool-call coroutine). Async tests — rely on Task 1's `asyncio_mode = "auto"`.
- [ ] Write these 7 test functions (plan §2 client matrix):

| Test function | Verifies |
|---------------|----------|
| `test_drive_client_maps_outcome` | An ok `ToolOutcome(resource_ref="url")` → `DeliveryResult(service="drive", ok=True, resource_ref="url")` |
| `test_gmail_client_maps_outcome` | Symmetric → `DeliveryResult(service="gmail", ok=True, resource_ref="msgid")` |
| `test_client_never_raises` | `call_tool_with_retry` raising internally is contained → `DeliveryResult(ok=False, error_message=...)`, no raise |
| `test_timeout_becomes_failed` | Every attempt hits `asyncio.TimeoutError` → terminal `ToolOutcome(ok=False)` with a timeout message (AC-16) |
| `test_retryable_is_retried_with_backoff` | A `retryable=True` outcome is retried up to `max_retries` then FAILED; assert the tool-call was attempted `1 + max_retries` times (AC-17) |
| `test_non_retryable_fails_immediately` | A `retryable=False` outcome → exactly 1 attempt, immediate FAILED (AC-17, Edge Case 8) |
| `test_worst_case_attempts_bounded` | Total attempts never exceed `1 + max_retries` (AC-16 bound) |

- [ ] For backoff tests, patch `asyncio.sleep` so the test doesn't actually wait; assert it was called with increasing delays.

**Verify**: Run `python -m pytest tests/unit/test_mcp_clients.py -v` — all 7 must FAIL (ImportError).

---

## Task 11: Implement `session.py` + the Drive/Gmail client wrappers

- [ ] Create package marker `app/delivery/mcp_clients/__init__.py` re-exporting `upload_report_to_drive`, `send_report_via_gmail`.
- [ ] Create `app/delivery/mcp_clients/session.py`:
  - **Imports**: `asyncio`; `mcp.ClientSession`; `mcp.client.stdio` (`stdio_client`, `StdioServerParameters`); `app.delivery.models.ToolOutcome`.
  - `async def call_tool_with_retry(server_module, tool_name, arguments, *, timeout_seconds, max_retries) -> ToolOutcome`:
    - Loop `attempt` in `range(1 + max_retries)`:
      - Open a stdio `ClientSession` to `python -m <server_module>`, `await session.initialize()`, then `await asyncio.wait_for(session.call_tool(tool_name, arguments), timeout=timeout_seconds)`.
      - Parse the tool result back into a `ToolOutcome`.
      - If `outcome.ok` → return it. If `not outcome.retryable` → return it (permanent). Else fall through to retry.
    - On `asyncio.TimeoutError` / connection error → treat as a **retryable** attempt failure.
    - Between attempts: `await asyncio.sleep(base * 2**attempt)` (exponential backoff; `base` a small module constant, e.g. 0.5).
    - After the last attempt → return the terminal `ToolOutcome(ok=False, retryable=<last>, error_message=...)`. **NEVER raise.**
- [ ] Create `app/delivery/mcp_clients/drive_client.py`:
  - `async def upload_report_to_drive(file_path, file_name, mime_type, folder_id, *, timeout_seconds, max_retries) -> DeliveryResult`: build+validate a `DriveUploadRequest`, `outcome = await call_tool_with_retry("app.delivery.mcp_servers.drive_server", "upload_file", req.model_dump(), timeout_seconds=..., max_retries=...)`, map → `DeliveryResult(service="drive", ok=outcome.ok, resource_ref=outcome.resource_ref, error_message=outcome.error_message)`. Wrap in `try/except` → never raises.
- [ ] Create `app/delivery/mcp_clients/gmail_client.py`: symmetric, tool `send_message` on `app.delivery.mcp_servers.gmail_server`, `DeliveryResult(service="gmail", ...)`.

**Verify**: Run `python -m pytest tests/unit/test_mcp_clients.py -v` — all 7 must PASS.

---

## Task 12: Write unit tests for the orchestrator `deliver_report` (confirm FAILING)

- [ ] Create file `tests/unit/test_delivery_step.py`
- [ ] The import `from app.delivery.delivery_step import deliver_report, deliver_report_sync` will fail until Task 13.
- [ ] Patch `app.delivery.delivery_step.upload_report_to_drive` and `.send_report_via_gmail` (the names as re-exposed/imported in the module) with **async stubs** returning canned `DeliveryResult`s. Provide a real fixture report pair in `tmp_path`: a `{doc}.md` and a `{doc}.json` (the JSON = a valid `ContractReport.model_dump_json()` with a known `summary`). Build `state` with `report_path=str(tmp_md)`, `document_id`, `original_filename`. Monkeypatch the re-exposed config names (`MCP_*`) on the module.
- [ ] Async tests — rely on Task 1. Write these 22 test functions (plan §2 orchestrator matrix + the AC-22 idempotency test):

| Test function | Verifies |
|---------------|----------|
| `test_happy_path_both_channels` | Both stubs called; status has `drive`+`gmail`, both `SUCCESS`, `delivered_at` set (AC-1/7) |
| `test_status_keys_and_info_shape` | Keys ⊆ {drive,gmail}; each value exactly `{status, error_message, delivered_at}` (AC-7) |
| `test_never_writes_pending` | No returned entry has `status == MCPDeliveryStatus.PENDING` (AC-8, D11a) |
| `test_partial_update_only` | Return is exactly `{"mcp_delivery_status": ...}` — assert **no** `current_node`, `node_timings`, `error_count`, `processing_completed_at`, or any Node 1–7 key (AC-10/11, D8/D11) |
| `test_drive_disabled_no_entry` | `MCP_DRIVE_ENABLED=False` → drive stub NOT called; no `drive` key; `gmail` present (AC-9, D13) |
| `test_gmail_disabled_no_entry` | `MCP_GMAIL_ENABLED=False` → symmetric (AC-9) |
| `test_both_disabled_noop` | `MCP_DELIVERY_ENABLED=False` → `{"mcp_delivery_status": {}}`, no stub calls (Edge Case 10) |
| `test_drive_failure_does_not_block_gmail` | Drive stub `ok=False` → `drive` FAILED, `gmail` SUCCESS; no raise (AC-12) |
| `test_gmail_failure_keeps_drive_success` | Gmail stub fails after Drive ok → `drive` SUCCESS, `gmail` FAILED; no Drive rollback attempted (AC-13) |
| `test_total_failure_non_fatal` | Both stubs fail → both FAILED, no raise (AC-14) |
| `test_no_report_path_fails_enabled_channels` | `report_path=None` → enabled channels FAILED, **no** stub call (AC-18, Edge Case 1) |
| `test_missing_file_fails` | `report_path` set but file absent → FAILED, no stub call (AC-19, Edge Case 2) |
| `test_missing_recipient_fails_gmail_drive_ok` | `MCP_DELIVERY_RECIPIENT=""` + no override → `gmail` FAILED "no recipient configured"; drive uploaded (AC-20, Edge Case 3, D13) |
| `test_recipient_override_used` | `deliver_report(state, recipient="x@y.z")` overrides the empty config default (D4) |
| `test_email_counts_from_json_sibling` | Gmail stub receives a subject/body whose counts equal the fixture JSON `summary`; `clauses` is never read (AC-6, D5) |
| `test_missing_json_sibling_generic_email` | JSON absent/corrupt → gmail still SUCCESS, generic subject (no counts) (AC-21, Edge Case 4) |
| `test_gmail_body_links_drive_only_when_ok` | Drive stub returns a `resource_ref` → gmail body contains it; drive **failed/disabled** → no link, gmail still sent; **drive `ok=True` but `resource_ref is None`** (upload succeeded, no shareable URL) → no body link **and** `drive` stays `SUCCESS` (AC-5, Edge Case 5) |
| `test_drive_uploads_configured_formats` | default → drive stub called for `.md` and `.json`; `MCP_DRIVE_UPLOAD_FORMATS=("md",)` → only `.md` (AC-2) |
| `test_drive_filename_matches_report_basename` | file names passed = `Path(report_path).name` (`.md`) and its `.json` sibling — the basenames Node 7 wrote; the step does NOT import Node-7 filename templates (AC-3, D6) |
| `test_config_values_read_not_hardcoded` | recipient/folder/formats/timeout/retry all read from the monkeypatched module names (AC-15) |
| `test_sync_wrapper_runs` | `deliver_report_sync(state)` returns the same result as awaiting `deliver_report(state)` (via `asyncio.run`) |
| `test_redelivery_idempotent_state_shape` | Run `deliver_report` **twice** on the same terminal state → both returns have `mcp_delivery_status` keys exactly `{"drive","gmail"}`; feeding the two returns through `001`'s `merge_dicts` reducer **replaces** the per-service entries (no duplicate keys, second wins), not appends (AC-22, orchestrator-level idempotency) |

**Verify**: Run `python -m pytest tests/unit/test_delivery_step.py -v` — all 22 must FAIL (ImportError).

---

## Task 13: Implement `delivery_step.py` (the orchestrator)

- [ ] Create file `app/delivery/delivery_step.py`.
- [ ] **Imports**: `asyncio`, `logging`, `from datetime import datetime, timezone`, `from pathlib import Path`, `from typing import Optional` (stdlib); `import app.config as _config`; `from app.graph.state import MCPDeliveryStatus`; `from app.models.report import ContractReport` (REUSE Node-7's model to read the JSON summary — D5); `from app.delivery.mcp_clients import upload_report_to_drive, send_report_via_gmail`. **No `ollama`, no Google, no MCP-server import.**
- [ ] **Config re-exposure (mirror `report_agent.py:29-32`)** — re-expose every `MCP_*` constant as a module-level name read by bare name so tests can monkeypatch:

```python
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

- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.delivery")`.
- [ ] `async def deliver_report(state, *, recipient: Optional[str] = None) -> dict` — flow per plan §2:
  1. If `not MCP_DELIVERY_ENABLED` **or** (`not MCP_DRIVE_ENABLED and not MCP_GMAIL_ENABLED`) → log info; `return {"mcp_delivery_status": {}}` (Edge Case 10, D13).
  2. `report_path = state.get("report_path")`; `document_id = state.get("document_id", "unknown")`; `md_path = Path(report_path) if report_path else None`; `json_path = md_path.with_suffix(".json") if md_path else None`.
  3. **Guard:** if `report_path is None` → reason `"no report_path (Node 7 write failed)"`; elif `not md_path.exists()` → reason `"report file not found"`. Return `{"mcp_delivery_status": _all_enabled_failed(reason)}` — **no** network call (AC-18/19, Edge Case 1/2).
  4. `summary = _load_summary(json_path)` — `None` on miss (Edge Case 4).
  5. `status = {}`; `drive_ref = None`.
     - If `MCP_DRIVE_ENABLED`: `result = await _deliver_drive(md_path, json_path, document_id)`; `status["drive"] = _to_info(result)`; if `result.ok`: `drive_ref = result.resource_ref`.
     - If `MCP_GMAIL_ENABLED`: `to = recipient or MCP_DELIVERY_RECIPIENT`; if `not to` → `status["gmail"] = _failed_info("no recipient configured")` (D13, Edge Case 3); else compose `subject, body = _compose_email(document_id, state, summary, drive_ref)`, `attach = str(md_path) if MCP_GMAIL_ATTACH_REPORT else None`, `result = await send_report_via_gmail(to, subject, body, attach, md_path.name, timeout_seconds=MCP_DELIVERY_TIMEOUT_SECONDS, max_retries=MCP_DELIVERY_MAX_RETRIES)`, `status["gmail"] = _to_info(result)`.
  6. `logger.info("MCP delivery completed", extra={...per-channel ok flags, elapsed...})` — logs only (D11).
  7. `return {"mcp_delivery_status": status}` — the ONLY state key (AC-10).
- [ ] **Helpers:**
  - `_now_iso()` → `datetime.now(timezone.utc).isoformat()`.
  - `_to_info(result)` → `{"status": MCPDeliveryStatus.SUCCESS if result.ok else MCPDeliveryStatus.FAILED, "error_message": result.error_message, "delivered_at": _now_iso() if result.ok else None}`. **SUCCESS/FAILED only — never PENDING (D11a).**
  - `_failed_info(msg)` → `{"status": MCPDeliveryStatus.FAILED, "error_message": msg, "delivered_at": None}`.
  - `_all_enabled_failed(reason)` → a `_failed_info(reason)` entry for **each enabled** channel only (config-disabled → no entry, D13).
  - `_load_summary(json_path)` → `try: return ContractReport.model_validate_json(json_path.read_text(encoding="utf-8")).summary; except (FileNotFoundError, OSError, ValidationError): log warning; return None` (Edge Case 4). Never reads `clauses` (D5).
  - `_deliver_drive(md_path, json_path, document_id)` → for each `ext in MCP_DRIVE_UPLOAD_FORMATS`: pick path (`md_path` for `"md"`, `json_path` for `"json"`) + mime (`text/markdown` / `application/json`); `await upload_report_to_drive(str(path), path.name, mime, MCP_DRIVE_FOLDER_ID, timeout_seconds=..., max_retries=...)`. Channel `ok` iff every requested-format upload succeeded; return the **Markdown** upload's `resource_ref` as the email link. Build a `DeliveryResult(service="drive", ...)` aggregating.
  - `_compose_email(document_id, state, summary, drive_ref)` → subject `"ContractSentinel report — {original_filename}: N findings (H high / M med / L low)"` when `summary` present, else a generic subject (Edge Case 4); body = short summary + the Drive link **iff** `drive_ref`, always noting the attachment (AC-5).
- [ ] `def deliver_report_sync(state, *, recipient=None) -> dict:` → `return asyncio.run(deliver_report(state, recipient=recipient))`.
- [ ] Update `app/delivery/__init__.py` to re-export `deliver_report`, `deliver_report_sync`.
- [ ] **Key invariants** (hold by construction): returns only `mcp_delivery_status`; keys ⊆ {drive,gmail}; each value exactly `{status, error_message, delivered_at}`; status ∈ {SUCCESS, FAILED}; config-disabled → no key; enabled-but-can't-run → FAILED; never raises.
- [ ] **`builder.py` stays untouched** — do NOT import `deliver_report` there, do NOT wire anything, do NOT add a comment (D1; `test_delivery_does_not_touch_graph` asserts it).

**Verify**: Run `python -m pytest tests/unit/test_delivery_step.py -v` — all 22 must PASS.

---

## Task 14: Write and run integration tests

- [ ] Create file `tests/integration/test_delivery_integration.py`
- [ ] End-to-end **without the graph** and **without live Google**: drive the client→tool→result contract against **stubbed servers** — either patch `call_tool_with_retry` to route to the real `_handle_upload`/`_handle_send` with a mocked Google service, or patch the two client wrappers with async stubs that record their arguments. Produce a **real** report pair by running the actual Node-7 `report_agent(state)` into `tmp_path` (monkeypatch `report_agent.REPORT_OUTPUT_DIR`), then feed that terminal state to `deliver_report`.
- [ ] Write these 4 test functions (plan §2 integration matrix):

| Test function | Verifies |
|---------------|----------|
| `test_deliver_after_report_terminal_state` | Given a terminal `ContractState` with a real `report_path` from a Node-7 run + stubbed servers, `deliver_report` returns `mcp_delivery_status` with SUCCESS `drive`+`gmail`; the stubs received the real report file path (upload) and a subject (send) |
| `test_deliver_reads_real_report_json_summary` | The composed email subject counts equal the real Node-7-produced JSON sibling's `summary` (AC-6 end-to-end) |
| `test_delivery_does_not_touch_graph` | `import app.delivery.delivery_step` does not import `app.graph.builder`; and `build_graph().get_graph()` still ends at `report → END` (report's only successor is END) — the graph is unchanged (D1) |
| `test_delivery_step_state_key_only` | Applying the returned partial dict through `001`'s `merge_dicts` reducer onto a prior `mcp_delivery_status` yields a valid merged dict; no other state key is present in the return |

- [ ] For `test_delivery_does_not_touch_graph`: the **primary** assertion is that `delivery_step` does not itself import the builder — scan the module's own imports/source (e.g. `inspect.getsource(delivery_step)` contains no `app.graph.builder`, or walk its module-level names). **Do NOT rely on a `sys.modules` before/after diff** — under a shared pytest session `app.graph.builder` is almost certainly already imported by earlier tests, so a global diff is unreliable. Then, as a second assertion, inspect `build_graph().get_graph()` edges to confirm `report`'s only successor is `END` (graph unchanged).

> **Whole-pipeline note (do NOT build here):** a `report → deliver_report` end-to-end through a *runner* belongs to the future runner/API feature (spec §5.5) — no runner exists yet. This suite proves the step consumes a genuine Node-7 terminal state correctly, which is the Phase-1 seam.

**Verify**: Run `python -m pytest tests/integration/test_delivery_integration.py -v` — all 4 must PASS.

---

## Task 15: Full test suite pass (NO regressions expected)

- [ ] Run the complete suite:
```
python -m pytest tests/ -v --tb=short
```
- [ ] **All existing 365 tests (features 003–009) must still pass, UNMODIFIED.** This feature adds a post-terminal step and changes **nothing** in the graph, so — unlike feature 009 — there are **no** terminal-node regression fix-ups. If any existing integration/unit test changes behavior, STOP: the delivery code has leaked into the graph or config in a way it must not. Do not edit existing tests to make them pass.
- [ ] Expected NEW test count for feature 010: 3 (config) + 3 (models) + 3 (auth) + 9 (servers) + 7 (clients) + 22 (orchestrator) + 4 (integration) = **51 new tests**. Total suite: 365 + 51 = **416**.
- [ ] OCR-gated IngestAgent tests may skip if Tesseract is absent — acceptable. **No delivery test requires a live Google account, real OAuth, or the network** — all Google/MCP boundaries are mocked/stubbed.

---

## Task 16: Linting and type checking

- [ ] Run `black app/ tests/` — auto-format.
- [ ] Run `ruff check app/ tests/` — no lint errors. (Async funcs, the new `app/delivery/` tree.)
- [ ] Run `mypy app/` — no type errors (if installed). The transport Pydantic models are fully typed; add narrow `# type: ignore[...]` only if genuinely needed for the `mcp`/`googleapiclient` untyped imports — do NOT broaden.
- [ ] Do NOT weaken tests to satisfy lint/type checks — fix the implementation instead (constitution §7).

---

## Task 17: One-time OAuth setup + manual smoke test (optional, not in automated suite)

- [ ] **Out of automated scope (D9).** A real delivery needs a Google OAuth token at `GOOGLE_OAUTH_TOKEN_PATH`. Document (not implement as pipeline logic) the one-time consent: create OAuth client credentials in Google Cloud, place the client-secrets JSON at `GOOGLE_OAUTH_CREDENTIALS_PATH`, run a small one-off `InstalledAppFlow` consent script to produce the cached token. This is a deployment step, not runtime code (spec §5.4).
- [ ] If running the real smoke: set `CONTRACTSENTINEL_DELIVERY_RECIPIENT`, run `deliver_report_sync(terminal_state)` on a real Node-7 report, and confirm:
  - A `{document_id}.md` (and `.json`) appears in Drive (root or `MCP_DRIVE_FOLDER_ID`); a re-run updates the same file, not a duplicate (D6).
  - The recipient receives an email whose subject/counts match the report and that links to the Drive file and carries the Markdown attachment.
  - `mcp_delivery_status` has `drive` + `gmail` both `SUCCESS` with `delivered_at` set.
- [ ] Kill-switch check: set `MCP_DELIVERY_ENABLED=False` (or a channel off) and confirm the corresponding no-op / no-entry behavior (Edge Case 10, AC-9).

**Why**: The automated suite exercises the mechanics against mocks; this is the only step that touches real Google APIs and eyeballs the delivered artifact.

---

## Summary of all files created/modified

| # | File | Action |
|---|------|--------|
| 1 | `pyproject.toml` | MODIFIED (add `[tool.pytest.ini_options] asyncio_mode = "auto"`) |
| 2 | `app/config.py` | MODIFIED (add `import os` / `Optional`; MCP delivery + OAuth constants) |
| 3 | `.gitignore` (repo root) | MODIFIED (add `backend/data/secrets/`) |
| 4 | `app/delivery/__init__.py` | NEW (package marker; re-exports `deliver_report`, `deliver_report_sync`) |
| 5 | `app/delivery/models.py` | NEW (Pydantic transport: `DriveUploadRequest`, `GmailSendRequest`, `ToolOutcome`, `DeliveryResult`) |
| 6 | `app/delivery/mcp_servers/__init__.py` | NEW (package marker) |
| 7 | `app/delivery/mcp_servers/google_auth.py` | NEW (`load_credentials`, `build_drive_service`, `build_gmail_service`, `CredentialsError`) |
| 8 | `app/delivery/mcp_servers/drive_server.py` | NEW (Drive MCP server + `_handle_upload`) |
| 9 | `app/delivery/mcp_servers/gmail_server.py` | NEW (Gmail MCP server + `_handle_send`) |
| 10 | `app/delivery/mcp_clients/__init__.py` | NEW (re-exports client wrappers) |
| 11 | `app/delivery/mcp_clients/session.py` | NEW (`call_tool_with_retry`) |
| 12 | `app/delivery/mcp_clients/drive_client.py` | NEW (`upload_report_to_drive`) |
| 13 | `app/delivery/mcp_clients/gmail_client.py` | NEW (`send_report_via_gmail`) |
| 14 | `app/delivery/delivery_step.py` | NEW (`deliver_report`, `deliver_report_sync`, helpers) |
| 15 | `tests/unit/test_config.py` | MODIFIED (+3 tests) |
| 16 | `tests/unit/test_delivery_models.py` | NEW (3 tests) |
| 17 | `tests/unit/test_google_auth.py` | NEW (3 tests) |
| 18 | `tests/unit/test_mcp_servers.py` | NEW (9 tests) |
| 19 | `tests/unit/test_mcp_clients.py` | NEW (7 tests) |
| 20 | `tests/unit/test_delivery_step.py` | NEW (22 tests) |
| 21 | `tests/integration/test_delivery_integration.py` | NEW (4 tests) |

> **`app/graph/builder.py` is NOT in this list — by design (D1).** The graph is untouched; no existing test file is modified (contrast feature 009's terminal-node fix-ups).

---

## Acceptance-criteria traceability (spec §3 → tasks)

| Spec §3 criterion | Covered by |
|-------------------|-----------|
| **Delivery behavior** | |
| 1. Both channels attempted on happy path | Task 12/13 (`test_happy_path_both_channels`) |
| 2. Drive uploads the configured formats | Task 12/13 (`test_drive_uploads_configured_formats`) |
| 3. Drive filename = report basename (deterministic) | Task 12/13 (`test_drive_filename_matches_report_basename`) |
| 4. Gmail addressed, subjected, attached | Task 12/13 (`test_email_counts_from_json_sibling`), Task 8/9 (`test_gmail_send_builds_mime_and_sends`, `test_gmail_attaches_when_path_given`) |
| 5. Gmail body links Drive only when Drive ok (+ EC5: ok but no URL) | Task 12/13 (`test_gmail_body_links_drive_only_when_ok`) |
| 6. Summary counts from the JSON sibling | Task 12/13 (`test_email_counts_from_json_sibling`), Task 14 (`test_deliver_reads_real_report_json_summary`) |
| **State outputs** | |
| 7. `mcp_delivery_status` keyed by service, shape | Task 12/13 (`test_status_keys_and_info_shape`) |
| 8. `MCPDeliveryStatus` enum; never PENDING | Task 12/13 (`test_never_writes_pending`) |
| 9. Disabled channel → no entry | Task 12/13 (`test_drive_disabled_no_entry`, `test_gmail_disabled_no_entry`) |
| 10. Partial update only | Task 12/13 (`test_partial_update_only`) |
| 11. `error_count` untouched on failure | Task 12/13 (`test_partial_update_only`, `test_drive_failure_does_not_block_gmail`) |
| **Independence & failure isolation** | |
| 12. Drive failure doesn't block Gmail | Task 12/13 (`test_drive_failure_does_not_block_gmail`) |
| 13. Gmail failure doesn't revert Drive | Task 12/13 (`test_gmail_failure_keeps_drive_success`) |
| 14. Total failure is non-fatal | Task 12/13 (`test_total_failure_non_fatal`) |
| **Config, timeout, retry** | |
| 15. Toggles/paths/recipient from config | Task 2/3 (`test_mcp_delivery_constants_match_spec`), Task 12/13 (`test_config_values_read_not_hardcoded`, `test_recipient_override_used`) |
| 16. Per-attempt timeout enforced | Task 10/11 (`test_timeout_becomes_failed`, `test_worst_case_attempts_bounded`) |
| 17. Bounded, backed-off retry | Task 10/11 (`test_retryable_is_retried_with_backoff`, `test_non_retryable_fails_immediately`) |
| **Degenerate & guard paths** | |
| 18. No `report_path` → nothing delivered, recorded | Task 12/13 (`test_no_report_path_fails_enabled_channels`) |
| 19. Missing report file on disk | Task 12/13 (`test_missing_file_fails`) |
| 20. Missing recipient → Gmail skipped/FAILED, Drive proceeds | Task 12/13 (`test_missing_recipient_fails_gmail_drive_ok`) |
| 21. Missing/unreadable JSON sibling → generic email | Task 12/13 (`test_missing_json_sibling_generic_email`) |
| 22. Re-delivery idempotent — state shape (keys stable, merge replaces) | Task 12/13 (`test_redelivery_idempotent_state_shape`) |
| 22 (Drive-file half, D6/EC7 — overwrite in place) | Task 8/9 (`test_drive_upload_updates_when_present`) |
| **Design invariants (spec §8a / plan)** | |
| D1 — not a node, no builder.py change | Task 14 (`test_delivery_does_not_touch_graph`) |
| D5 — transport only, never reads `clauses` | Task 12/13 (`test_email_counts_from_json_sibling`) |
| D9 — no interactive OAuth at runtime | Task 6/7 (`test_missing_token_raises_credentials_error`) |
| D11a — never writes PENDING | Task 12/13 (`test_never_writes_pending`) |
| Async suite actually runs (Task 1 gate) | Task 1 (`asyncio_mode = "auto"` smoke) |
