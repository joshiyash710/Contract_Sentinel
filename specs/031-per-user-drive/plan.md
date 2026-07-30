# Per-user Google Drive delivery (Phase 2: per-user OAuth) — Technical Plan

## Git Branch

`feature/031-per-user-drive` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

Implements `specs/031-per-user-drive/spec.md`, authorized by the §2 amendment (2026-07-28, feature
031). A vertical slice across **auth/integration + post-terminal delivery + frontend**, with **no
LangGraph node/edge change and no `ContractState` change**:

- **Per-user token store** — `users` gains a Google OAuth token column (Alembic **0006**);
  `UserStore` gains scoped get/set/clear.
- **Per-user OAuth web connect flow** — `/api/integrations/google/{status,authorize,callback,disconnect}`,
  all `require_auth` + current-user-scoped, using `google-auth-oauthlib` `Flow` with a CSRF-safe,
  single-use `state`. Redirect URI = **`http://localhost:8000/api/integrations/google/callback`**
  (backend, per spec §6 resolution; owner registers it on a **Web** OAuth client in GCP).
- **Per-user delivery routing** — the runner resolves the uploading user's token and threads it to
  delivery; the Drive upload authenticates as **that user** (their Drive) or is **skipped** (email
  still sent). Gmail stays central (feature 020 recipient + feature 030 PDF/HTML email).
- **Frontend** — `IntegrationsView` gets a real Connect / Connected / Disconnect for Drive.

Resolved decisions (spec §6): not-connected → `MCPDeliveryStatus.FAILED` + message; disconnect →
best-effort revoke + local delete; per-user `invalid_grant` → auto-mark disconnected; token stored
unencrypted (amendment-authorized interim). Reversible: a feature flag disables the per-user path and
falls back to the central token (see §3.9).

---

## 2. Files to Create / Modify

### Backend
```
alembic/versions/0006_add_user_google_token.py     [CREATE] add users.google_oauth_token TEXT NULL + users.google_email TEXT NULL
app/runner/user_store.py                           [MODIFY] UserRow + _row_to_user gain the 2 cols; add set/get/clear google-credentials (user_id-scoped)
app/config.py                                      [MODIFY] GOOGLE_OAUTH_REDIRECT_URI, GOOGLE_DRIVE_OAUTH_SCOPES, GOOGLE_OAUTH_WEB_CREDENTIALS_PATH, FRONTEND_INTEGRATIONS_URL, PER_USER_DRIVE_ENABLED
app/api/integrations.py                            [CREATE] integrations_router (/api/integrations/google/*): status/authorize/callback/disconnect + Pydantic models + single-use state store + Flow helpers
app/api/main.py                                    [MODIFY] include integrations_router (require_auth); give the worker a UserStore handle
app/delivery/oauth_credentials.py                  [CREATE] pure helper: credentials_json_to_tempfile()/Credentials.from_authorized_user_info; revoke_token() best-effort
app/delivery/models.py                             [MODIFY] DriveUploadRequest gains token_path: Optional[str] = None
app/delivery/mcp_servers/drive_server.py           [MODIFY] use req.token_path when present, else central; ADD token_path to the upload_file tool inputSchema
app/delivery/mcp_clients/drive_client.py           [MODIFY] upload_report_to_drive gains token_path (trailing keyword) → DriveUploadRequest
app/delivery/delivery_step.py                      [MODIFY] deliver_report/deliver_report_sync gain drive_token_json; materialize temp token (delete=False), unlink in finally; per-user Drive or skip(FAILED+msg); gmail unchanged
app/runner/core.py                                 [MODIFY] run_pipeline gains drive_token_json → deliver_report_sync
app/runner/worker.py                               [MODIFY] PipelineWorker.__init__ gains user_store=None (self._user_store); _run_one resolves token via user_store.get_google_credentials(rec.user_id); pass drive_token_json; on invalid_grant auto-clear
tests/unit/test_user_store.py                      [MODIFY] google-credentials methods + isolation
tests/unit/test_migrations.py (or 012 harness)     [MODIFY/ADD] 0006 upgrade/downgrade round-trip
tests/unit/test_integrations_api.py                [CREATE] status/authorize/callback (mock Flow)/disconnect + CSRF/replay + auth + cross-user isolation
tests/unit/test_delivery_step.py                   [MODIFY] per-user token routing, not-connected skip, invalid_grant graceful, gmail-unchanged, two-user isolation
tests/unit/test_mcp_servers.py                     [MODIFY] drive_server uses token_path when given
tests/unit/test_mcp_clients.py                     [MODIFY] upload_report_to_drive threads token_path
tests/unit/test_config.py                          [MODIFY] new constants
```

### Frontend
```
frontend/src/lib/api/client.ts                     [MODIFY] IntegrationsApi seam: getGoogleDriveStatus(), googleDriveAuthorizeUrl(), disconnectGoogleDrive()
frontend/src/lib/api/realProvider.ts               [MODIFY] implement against /api/integrations/google/*
frontend/src/lib/api/mockProvider.ts               [MODIFY] mock the seam
frontend/src/components/integrations/IntegrationsView.tsx [MODIFY] real Connect/Connected(as email)/Disconnect for Drive; Gmail stays "server-managed"
frontend/src/__tests__/integrations.test.tsx       [MODIFY] connected/not-connected/disconnect states
frontend/src/__tests__/integrations-boundary.test.ts [MODIFY] per-user Drive reality (not weakened)
```
No graph/`ContractState`/Node-7 change. `alembic upgrade head` required after pull.

---

## 3. Backend design

### 3.1 Migration 0006 + UserStore
- `0006_add_user_google_token.py`: `op.add_column('users', Column('google_oauth_token', Text, nullable=True))`
  and `google_email` (Text, nullable). `downgrade` drops both. Existing rows → NULL (not connected).
- `UserRow` + `_row_to_user`: add `google_oauth_token: Optional[str]`, `google_email: Optional[str]`
  (SELECT column lists updated). New methods (all `WHERE id=?`):
  `set_google_credentials(user_id, token_json, google_email)`, `get_google_credentials(user_id) ->
  Optional[str]`, `get_google_email(user_id) -> Optional[str]`, `clear_google_credentials(user_id)`.

### 3.2 Config (§3 — named constants)
```python
PER_USER_DRIVE_ENABLED: bool = True                     # master toggle (reversibility §3.9)
GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/integrations/google/callback"
GOOGLE_DRIVE_OAUTH_SCOPES: tuple = ("https://www.googleapis.com/auth/drive.file",)
GOOGLE_OAUTH_WEB_CREDENTIALS_PATH: str = "data/secrets/google_web_credentials.json"  # Web client (Q1)
FRONTEND_INTEGRATIONS_URL: str = "http://localhost:3000/integrations"                 # callback 302 target
```
`GOOGLE_OAUTH_WEB_CREDENTIALS_PATH` is the **Web** OAuth client secrets (owner adds it in GCP; §6 Q1).
It may equal `GOOGLE_OAUTH_CREDENTIALS_PATH` if that client is converted to Web; kept separate so the
central desktop client (used for the central Gmail token) is untouched.

### 3.3 `app/api/integrations.py` (the connect flow)
- `integrations_router = APIRouter(prefix="/api/integrations")`, mounted in main with
  `dependencies=[Depends(require_auth)]` (same as the app router) so every endpoint is authenticated;
  each handler takes `current_user` and scopes to it.
- **Single-use CSRF state:** a module-level `_PENDING: dict[user_id -> (state, created_at)]` guarded by
  a `threading.Lock`, TTL-bounded. `authorize` generates a random `state`, stores it for the user;
  `callback` looks up by `current_user`, compares, and **pops** it (single-use → replay rejected, AC-7a).
  (Single uvicorn worker; in-memory is fine — a restart mid-handshake just fails safe.)
- **Flow helper:** `_build_flow()` = `google_auth_oauthlib.flow.Flow.from_client_secrets_file(
  GOOGLE_OAUTH_WEB_CREDENTIALS_PATH, scopes=list(GOOGLE_DRIVE_OAUTH_SCOPES),
  redirect_uri=GOOGLE_OAUTH_REDIRECT_URI)`.
- Endpoints:
  - `GET /google/status` → `GoogleStatus(connected: bool, google_email: Optional[str])` from
    `UserStore.get_google_credentials/get_google_email(current_user.id)`.
  - `GET /google/authorize` → `flow.authorization_url(access_type="offline", prompt="consent",
    include_granted_scopes="true")`; store state; **302 redirect** to Google (browser navigates).
  - `GET /google/callback` (params `code`, `state`, optional `error`): if `error` (e.g. access_denied)
    → 302 to `FRONTEND_INTEGRATIONS_URL?google=denied`. Verify+pop the stored state for `current_user`
    (mismatch/absent/replay → 400). `flow.fetch_token(code=...)`; `creds = flow.credentials`;
    `UserStore.set_google_credentials(current_user.id, creds.to_json(), _email_of(creds))`; 302 to
    `FRONTEND_INTEGRATIONS_URL?google=connected`. Wrap in try/except → 302 `...?google=error` (no 500).
  - `POST /google/disconnect` → best-effort `revoke_token(token)` (oauth_credentials helper),
    then `UserStore.clear_google_credentials(current_user.id)`; return `{connected: false}`.
- `_email_of(creds)`: derive the Google account email — **prefer the `id_token` claim** if present;
  else a **strictly best-effort, bounded-timeout** userinfo/Drive `about.get(fields="user")` call; on
  any failure/timeout store `None` (display falls back to "Connected"). Never blocks or fails the
  callback.
- **Cookie note:** the callback relies on the `SameSite=Lax` session cookie being sent on Google's
  top-level GET redirect to `:8000` (Lax allows top-level GET; cookie host `localhost` is port-agnostic,
  so it is sent to :8000). Verified against `_set_session_cookie`.

### 3.4 `app/delivery/oauth_credentials.py` (pure helpers)
- `write_token_tempfile(token_json: str) -> str`: create with `NamedTemporaryFile(delete=False)`
  (Windows can't have the subprocess re-open a `delete=True` handle), write the JSON, close it, return
  the path. The **caller owns deletion** and must `os.unlink` it in a `finally` **after
  `upload_report_to_drive` returns** (subprocess exited), so the child can read it during the upload.
- `revoke_token(token_json: str) -> bool`: POST the refresh/access token to Google's revoke endpoint
  (bounded timeout, §9); return success; never raises.

### 3.5 Drive MCP: per-user token (`models.py`, `drive_server.py`, `drive_client.py`)
- `DriveUploadRequest` gains `token_path: Optional[str] = None`.
- `drive_server._handle_upload`: `token_path = req.token_path or _config.GOOGLE_OAUTH_TOKEN_PATH`;
  `load_credentials(_config.GOOGLE_OAUTH_CREDENTIALS_PATH, token_path)` (works with either the central
  desktop token or a per-user web token — both are authorized-user JSON that `load_credentials`
  refreshes).
- **`upload_file` tool `inputSchema` MUST also gain `"token_path": {"type": ["string","null"]}`**
  (in `drive_server._build_server()`). This is the credential-threading hinge: `token_path` crosses the
  stdio subprocess boundary as an argument (`req.model_dump()` → `call_tool("upload_file", arguments)`
  → `DriveUploadRequest(**arguments)`), and MCP validates arguments against the tool's `inputSchema` —
  an undeclared property can be stripped/rejected. The path is a **local filesystem path** the
  same-machine subprocess reads; `test_mcp_servers` asserts the schema includes `token_path` and that a
  given `token_path` is used over the central default.
- `upload_report_to_drive(...)` gains `token_path: Optional[str] = None` as a **trailing keyword**
  (positional args unchanged) → `DriveUploadRequest(token_path=...)`.

### 3.6 `delivery_step.py` — per-user Drive selection
- `deliver_report(state, *, recipient=None, drive_token_json: Optional[str] = None)` and
  `deliver_report_sync(..., drive_token_json=None)` (trailing keyword; existing `recipient` positions
  unchanged).
- In `deliver_report`, before the Drive block:
  - If `PER_USER_DRIVE_ENABLED` and `drive_token_json`: `user_token_path =
    write_token_tempfile(drive_token_json)`; in a **`try/finally`** call `_deliver_drive(..., token_path=
    user_token_path)` and **`os.unlink(user_token_path)` in the `finally`** (after the await returns, so
    the subprocess has exited). The aggregate `resource_ref`/CTA come from the PDF upload (feature 030,
    unchanged). A test asserts the temp file does not exist after `deliver_report` returns.
  - Else (not connected): **skip Drive** — `status["drive"] = _failed_info("user has not connected
    Google Drive")` (resolved Q5), and **do NOT call the drive client**. Gmail still runs.
  - `invalid_grant`/refresh failure during the per-user upload → the drive `DeliveryResult` is `ok=False`
    with the Google message; surface as `status["drive"]` FAILED; **email still sent**. The worker
    (§3.7) auto-clears the user's token on `invalid_grant`.
- `_deliver_drive` gains a `token_path` param it passes through to `upload_report_to_drive`.
- Gmail block unchanged (central token, feature-030 PDF/HTML email, feature-020 recipient).

### 3.7 Runner threading (`worker.py`, `core.py`)
- **`PipelineWorker.__init__`** today is `(registry, saver, concurrency)`; add a trailing
  `user_store=None` param stored as `self._user_store`. The token is resolved in the worker's per-job
  method (`_run_one`, which is what calls `run_pipeline`) — NOT in `RunnerContext` (that lives in
  `routes.py` and does not call the pipeline). This resolves the earlier "registry.py (or context)"
  ambiguity: the handle lives on the worker.
- In `_run_one`, before `run_pipeline`: `drive_token = None`; if `self._user_store and rec.user_id`:
  `drive_token = self._user_store.get_google_credentials(rec.user_id)`. Pass `run_pipeline(...,
  drive_token_json=drive_token)`.
- `run_pipeline(..., drive_token_json=None)` → `deliver_report_sync(final_state, recipient=recipient,
  drive_token_json=drive_token_json)`.
- **Auto-clear on invalid_grant (Q4):** the delivery layer surfaces the marker substring
  **`"invalid_grant"`** in `mcp_delivery_status["drive"].error_message` when a per-user token refresh
  fails (Google's own error text contains it; the drive client passes it through). After delivery, if a
  per-user token was used AND `status["drive"]` is FAILED with `"invalid_grant"` in the message, the
  worker calls `self._user_store.clear_google_credentials(rec.user_id)` so `/status` shows
  reconnect-needed. (The token never enters the persisted `JobRow`/jobs table; it lives only as a local
  variable + short-lived temp file for the delivery call.)

### 3.8 `main.py`
- `application.include_router(integrations_router, dependencies=[Depends(require_auth)])`.
- In the lifespan, construct the worker with `PipelineWorker(..., user_store=user_store)` (the same
  `user_store` already built + placed on `app.state`).

### 3.9 Reversibility
`PER_USER_DRIVE_ENABLED=False` → delivery ignores `drive_token_json` and uses the central token (pre-031
behavior); the connect endpoints can stay (harmless) or be feature-gated. Fully restores feature-030
delivery.

---

## 4. Frontend design
- **API seam** (`client.ts`): `getGoogleDriveStatus(): Promise<{connected, googleEmail?}>`,
  `googleDriveAuthorizeUrl(): string` (returns the **absolute** URL
  `getConfig().apiBaseUrl + "/api/integrations/google/authorize"` — NOT a bare path — so the top-level
  browser navigation lands on `:8000` and carries the session cookie),
  `disconnectGoogleDrive(): Promise<void>`. `realProvider` calls the endpoints (authorize is a full
  navigation: `window.location.href = googleDriveAuthorizeUrl()`); `mockProvider` returns canned states.
- **`IntegrationsView`**: on mount, fetch status. Drive card: **Not connected** → enabled "Connect
  Google Drive" (navigates to authorize); **Connected** → "Connected as {googleEmail}" + "Disconnect"
  (POST → refetch). On return from callback, read `?google=connected|denied|error` and show a toast/
  banner. Gmail card copy stays "server-managed (sent from the app account)".
- Honest model: only Drive is per-user; no fake Gmail connect.

---

## 5. Tests mapped to acceptance criteria (TDD §7)

- **AC-1** `test_migrations`: 0006 upgrade adds columns, downgrade drops them; existing row survives NULL.
- **AC-2/AC-3** `test_user_store`: set/get/clear google creds; new user → None; user A cannot read B
  (scoped queries).
- **AC-4** `test_integrations_api`: `/status` 401 without session; `{connected:false}` new; `{connected:
  true, google_email}` after a seeded token.
- **AC-5** `authorize` (mock `_build_flow`) → redirect URL contains `drive.file`, `access_type=offline`,
  `prompt=consent`, and a `state`; state stored for the user.
- **AC-6** `callback` with valid state+code (mock `flow.fetch_token`/`credentials`) → token stored for
  current user, 302 to `FRONTEND_INTEGRATIONS_URL`.
- **AC-7 / AC-7a** callback with missing/mismatched state → 4xx, nothing stored; **replayed** (already-
  popped) state → 4xx; `error=access_denied` → 302 with `google=denied`, nothing stored, no 500.
- **AC-8** `disconnect` clears token (`/status`→false); revoke failure (mock `revoke_token` raising/False)
  still disconnects locally.
- **AC-9** `/status` response body never contains the token/refresh_token.
- **AC-10** `test_delivery_step`: connected user (drive_token_json set) → `_deliver_drive` called with a
  `token_path` (a temp file whose contents == the user's token JSON), NOT the central path; drive status
  SUCCESS. **Also assert the temp file no longer exists after `deliver_report` returns** (cleanup).
- **AC-11** not-connected (drive_token_json None) → drive client **not** called; `status["drive"]` ==
  FAILED with `error_message=="user has not connected Google Drive"`; gmail still called (PDF attached).
- **AC-12** per-user upload returns invalid_grant → drive FAILED, email still sent, worker clears the
  user's token (assert `clear_google_credentials` called); no raise.
- **AC-13** gmail path/central token unaffected by connection state (assert gmail called identically in
  connected/not-connected cases).
- **AC-14** two users A/B: A's job uses A's token_path, B's uses B's (distinct temp contents) — no
  cross-use.
- **AC-15** `git diff` shows no graph/state/Node-7/builder change; `MCPDeliveryStatus` enum unchanged.
- **AC-16** endpoints read redirect URI + scopes from config constants (assert via monkeypatch that
  changing the constant changes the built URL).
- **AC-17** every integrations endpoint is current-user-scoped (a second user cannot see/alter the
  first's connection).
- **AC-18/AC-19** frontend: `integrations.test.tsx` renders Connect when not connected, Connected+
  Disconnect when connected, Disconnect calls the seam; boundary test updated to per-user Drive; Gmail
  stays server-managed.
- **drive MCP** `test_mcp_servers`/`test_mcp_clients`: the `upload_file` tool `inputSchema` includes
  `token_path`; `token_path` honored (per-user) / defaulted to central when None; client threads
  `token_path` as trailing keyword (existing positional calls unchanged, existing drive tests still pass).
- **config** `test_config`: the new constants + types.
- **Live (Task 7-style, real Google):** after the owner registers the Web client + redirect URI, connect
  a test account via the UI, upload, and confirm the PDF lands in **that account's** Drive; a
  not-connected account still gets the email with Drive skipped.

---

## 6. Implementation order (TDD — §7)
1. **Migration + UserStore** (0006, get/set/clear) — tests red→green; `alembic upgrade head`.
2. **Config constants** — test_config red→green.
3. **Drive MCP token_path** (models → drive_server → drive_client) — tests; central path still default.
4. **oauth_credentials helpers** (tempfile, revoke) — unit tests.
5. **delivery_step per-user routing** (drive_token_json, skip-when-none, temp-file, gmail unchanged) —
   tests incl. two-user isolation + not-connected + invalid_grant.
6. **Runner threading** (core.run_pipeline, worker resolve+clear, context user_store) — tests.
7. **integrations API** (status/authorize/callback/disconnect + state store) — tests incl. CSRF/replay/
   isolation; mount router.
8. **Frontend** seam + IntegrationsView + tests.
9. **Full regression** (`pytest -q` + frontend `vitest`); `git diff --name-only main` = only §2 files.
10. **Live smoke** once the owner completes the GCP Web-client + redirect-URI setup.

Tests are written/observed failing first (§7); existing tests are updated (not weakened) where the new
`token_path`/`drive_token_json` keyword or per-user Drive changes their expectations.

---

## 7. Notes / risks
- **GCP setup is a hard external dependency** (spec §6 Q1): the Web OAuth client + registered redirect
  URI must exist before the live connect works. Build + all mocked tests proceed without it; only the
  live smoke (step 10) needs it. This mirrors the OAuth-publish step from feature 030's fix.
- **Token security:** per-user refresh tokens are stored **unencrypted** (amendment-authorized interim)
  and materialized to a short-lived temp file (deleted in `finally`) for the subprocess Drive upload;
  the token **never** enters the persisted `JobRow`/jobs table or graph state, and is never returned on
  the wire. Encryption-at-rest is the future item.
- **SameSite=Lax callback:** verified the session cookie is sent on Google's top-level GET redirect to
  `:8000`; if the cookie were ever `SameSite=Strict`, the callback would need an alternative (state-only
  identity). Not the case today.
- **Single-process state store:** the CSRF `state` map is in-memory (one uvicorn worker). Fine for local
  dev; a multi-worker prod deployment would move it to a signed cookie/DB (future).
- **No graph/state change:** the whole feature is auth + delivery-layer + frontend; the 7-node graph,
  `ContractState`, and Node 7 are untouched.
- **Reversible:** `PER_USER_DRIVE_ENABLED=False` restores central-token delivery (feature 030).

---

*Per §1/§11, the `feature/031-per-user-drive` branch opens only after this plan.md + spec.md are
approved and `tasks.md` exists. Requires `alembic upgrade head` after pull; requires the owner's GCP
Web-client + redirect-URI setup before the live smoke. No graph/state change. No `tasks.md`/
implementation in this pass — plan only.*
