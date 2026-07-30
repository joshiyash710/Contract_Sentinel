# Per-user Google Drive delivery (Phase 2) — Implementation Tasks

Implements `specs/031-per-user-drive/plan.md` (authorized by the constitution §2 feature-031
amendment). TDD per §7 (test first, red→green; never weaken an assertion — update breaking existing
tests to the new reality). Branch `feature/031-per-user-drive` (§11). Run backend `pytest` from
`backend/`, frontend `vitest` from `frontend/`. No graph/edge/`ContractState`/Node-7 change. Monkeypatch
module-level config aliases, never `app.config` directly.

Legend: each task lists file(s), the change, and the AC(s) it satisfies.

---

## Task 0 — Branch (prerequisite)
Only after spec.md + plan.md are approved and this tasks.md exists: `git checkout main` → `git pull
origin main` → `git checkout -b feature/031-per-user-drive` (git-start). The constitution amendment
(already in the working tree) rides along and commits with this feature. No `app/`/`frontend/src` file
before the branch exists.

---

## Task 1 — Migration 0006 + UserStore per-user token (AC-1, AC-2, AC-3)
**Files:** `alembic/versions/0006_add_user_google_token.py` (CREATE), `app/runner/user_store.py`,
`tests/unit/test_user_store.py`, `tests/integration/test_alembic_head.py` (the migration round-trip
lives HERE — there is no `test_migrations.py`; that file's existing `users`-cols assertion uses `<=`, so
adding columns won't break it — add the 0006 upgrade→downgrade + "existing row survives NULL" AC-1
assertions to it).
1. **Migration 0006** (down_revision = `0005`): `add_column('users', 'google_oauth_token' TEXT NULL)`
   and `'google_email' TEXT NULL`; `downgrade` drops both. Match the existing migration style.
2. **UserStore**: `UserRow` + `_row_to_user` gain `google_oauth_token: Optional[str]`,
   `google_email: Optional[str]`; update the SELECT column lists. Add (all `WHERE id=?`):
   `set_google_credentials(user_id, token_json, google_email)`, `get_google_credentials(user_id) ->
   Optional[str]`, `get_google_email(user_id) -> Optional[str]`, `clear_google_credentials(user_id)`.
**Test first:** migration upgrade adds cols / downgrade drops them / existing row survives NULL (AC-1);
set→get round-trip, clear→None, new user None, user A cannot read/clear user B (AC-2, AC-3). Run
`alembic upgrade head`. Green.

---

## Task 2 — Config constants (AC-16)
**Files:** `app/config.py`, `tests/unit/test_config.py`
Add (with §3 comments): `PER_USER_DRIVE_ENABLED: bool = True`; `GOOGLE_OAUTH_REDIRECT_URI: str =
"http://localhost:8000/api/integrations/google/callback"`; `GOOGLE_DRIVE_OAUTH_SCOPES: tuple =
("https://www.googleapis.com/auth/drive.file",)`; `GOOGLE_OAUTH_WEB_CREDENTIALS_PATH: str =
"data/secrets/google_web_credentials.json"`; `FRONTEND_INTEGRATIONS_URL: str =
"http://localhost:3000/integrations"`. **Test first** in `test_config.py`: assert each + types. Green.

---

## Task 3 — Drive MCP per-user token_path (AC-10, AC-11 support)
**Files:** `app/delivery/models.py`, `app/delivery/mcp_servers/drive_server.py`,
`app/delivery/mcp_clients/drive_client.py`, `tests/unit/test_mcp_servers.py`, `tests/unit/test_mcp_clients.py`
**Test first:** (a) `_build_server()` `upload_file` `inputSchema` includes `token_path`
(`["string","null"]`); (b) `_handle_upload` uses `req.token_path` when given (mock `load_credentials`,
assert the token_path arg), else the central `GOOGLE_OAUTH_TOKEN_PATH`; (c) `upload_report_to_drive(...,
token_path=...)` threads it into `DriveUploadRequest`; existing drive tests still pass with positional
args + None token_path.
**Then implement:** `DriveUploadRequest.token_path: Optional[str] = None`; drive_server `token_path =
req.token_path or GOOGLE_OAUTH_TOKEN_PATH` + add it to the tool inputSchema; `upload_report_to_drive`
gains `token_path` as a **trailing keyword** (positional `file_path/file_name/mime_type/folder_id`
unchanged). Green.

---

## Task 4 — oauth_credentials helpers (supports AC-8, AC-10, AC-12)
**Files:** `app/delivery/oauth_credentials.py` (CREATE), `tests/unit/test_oauth_credentials.py` (CREATE)
**Test first:** `write_token_tempfile(json)` → a real file (delete=False) whose contents == json, path
returned; `revoke_token(json)` → posts to Google revoke (mock httpx), returns bool, never raises on
network error.
**Then implement** both (bounded timeout on revoke; never raise). Green.

---

## Task 5 — delivery_step per-user routing (AC-10, AC-11, AC-12, AC-13, AC-14)
**Files:** `app/delivery/delivery_step.py`, `tests/unit/test_delivery_step.py`
**Test first:**
- **AC-10** connected (drive_token_json set) → `_deliver_drive` called with a `token_path` whose temp
  contents == the token; NOT the central path; drive SUCCESS. Assert the temp file is **gone** after
  `deliver_report` returns.
- **AC-11** not-connected (drive_token_json None) → drive client NOT called; `status["drive"].status ==
  FAILED` with `error_message == "user has not connected Google Drive"`; gmail still called (PDF attached).
- **AC-12** per-user upload → drive DeliveryResult ok=False with `"invalid_grant"` in message → drive
  FAILED, email still sent, no raise.
- **AC-13** gmail path/central token identical in connected vs not-connected runs.
- **AC-14** two users → distinct token_path temp contents (no cross-use).
- **AC-15 support** `PER_USER_DRIVE_ENABLED=False` → drive_token_json ignored, central token used.
**Then implement:** `deliver_report(state, *, recipient=None, drive_token_json=None)` +
`deliver_report_sync(..., drive_token_json=None)` (trailing keyword). If `PER_USER_DRIVE_ENABLED` and
`drive_token_json`: `write_token_tempfile` → `try: _deliver_drive(..., token_path=tmp) finally:
os.unlink(tmp)`. Else skip Drive → `status["drive"] = _failed_info("user has not connected Google
Drive")`, do not call the drive client. `_deliver_drive` gains a `token_path` param passed to
`upload_report_to_drive`. Gmail block unchanged (central token, feature-030 PDF/HTML). Green.

---

## Task 6 — Runner threading (AC-12, AC-14)
**Files:** `app/runner/worker.py`, `app/runner/core.py`, `app/api/main.py`, `tests/unit/test_worker.py`,
`tests/unit/test_runner_core.py`
**Breaking existing test to UPDATE (not weaken):** `tests/unit/test_runner_core.py::
test_delivery_called_with_recipient` stubs `deliver_report_sync(state, *, recipient=None)`; once
`run_pipeline` passes `drive_token_json=...` it raises `TypeError`. Add `drive_token_json=None` to that
stub's signature. (`test_worker.py::test_worker_uses_run_pipeline` captures `**kwargs`, so it survives
unchanged — do not touch it.)
**Test first:** worker with a stub user_store: a job whose user_id is connected → `run_pipeline`
receives that user's `drive_token_json`; not-connected/None user_id → `drive_token_json=None`; after a
delivery whose `mcp_delivery_status["drive"]` is FAILED containing `"invalid_grant"` and a per-user
token was used → `user_store.clear_google_credentials(user_id)` is called (AC-12); two users route their
own tokens (AC-14).
**Then implement:** `PipelineWorker.__init__(..., user_store=None)` → `self._user_store`; in `_run_one`
resolve `drive_token = self._user_store.get_google_credentials(rec.user_id)` (if store + user_id) and
pass `run_pipeline(..., drive_token_json=drive_token)`; after delivery, auto-clear on the
`"invalid_grant"` marker. `run_pipeline(..., drive_token_json=None)` → `deliver_report_sync(...,
drive_token_json=...)`. `main.py` lifespan: `PipelineWorker(..., user_store=user_store)`. Green.

---

## Task 7 — Integrations OAuth API (AC-4, AC-5, AC-6, AC-7, AC-7a, AC-8, AC-9, AC-16, AC-17)
**Files:** `app/api/integrations.py` (CREATE), `app/api/main.py` (mount), `tests/unit/test_integrations_api.py` (CREATE)
**Test first** (TestClient with an authenticated session; mock `_build_flow`/`Flow`):
- **AC-4** `/status` 401 no session; `{connected:false}` new; `{connected:true, google_email}` after a
  seeded token. **AC-9** body never contains the token/refresh_token.
- **AC-5** `/authorize` → redirect URL contains `drive.file`, `access_type=offline`, `prompt=consent`,
  a `state`; state stored for the user. **AC-16** changing `GOOGLE_OAUTH_REDIRECT_URI`/scopes constant
  changes the built URL.
- **AC-6** `/callback` valid state+code (mock `fetch_token`/`credentials`) → token stored for current
  user, 302 to `FRONTEND_INTEGRATIONS_URL?...=connected`.
- **AC-7** missing/mismatched state → 4xx, nothing stored; `error=access_denied` → 302 `...=denied`,
  nothing stored, no 500. **AC-7a** replayed (already-popped) state → 4xx.
- **AC-8** `/disconnect` clears token (`/status`→false); revoke failure still disconnects locally.
- **AC-17** every endpoint current-user-scoped: user B cannot see/alter user A's connection.
**Then implement:** `integrations_router = APIRouter(prefix="/api/integrations")`; module-level
single-use `_PENDING` state store (lock + TTL, popped on callback); `_build_flow()` from
`GOOGLE_OAUTH_WEB_CREDENTIALS_PATH` + `GOOGLE_OAUTH_REDIRECT_URI` + scopes; the four handlers per plan
§3.3; Pydantic response models; `_email_of(creds)` (prefer id_token, bounded best-effort). Mount in
`main.py` with `dependencies=[Depends(require_auth)]`. Green.

---

## Task 8 — Frontend integrations connect UI (AC-18, AC-19)
**Files:** `frontend/src/lib/api/client.ts`, `realProvider.ts`, `mockProvider.ts`,
`frontend/src/components/integrations/IntegrationsView.tsx`, `frontend/src/__tests__/integrations.test.tsx`,
`integrations-boundary.test.ts`
**Test first (vitest):** IntegrationsView renders **Connect Google Drive** (enabled) when
`status.connected=false`; **Connected as {googleEmail}** + **Disconnect** when true; Connect navigates to
the absolute authorize URL; Disconnect calls the seam then refetches; Gmail card stays "server-managed".
Update the boundary test to the per-user-Drive reality (not weakened).
**Then implement:** API seam methods (`getGoogleDriveStatus`, `googleDriveAuthorizeUrl` = absolute
`getConfig().apiBaseUrl + "/api/integrations/google/authorize"` — `getConfig` is imported from
`@/lib/config` as in `realProvider.ts`, not a method on `client.ts`, `disconnectGoogleDrive`); real/mock
providers; wire IntegrationsView (fetch status on mount; handle `?google=connected|denied|error`
banner). Green.

---

## Task 9 — Full regression + no-scope-creep gate (AC-15)
- Backend `pytest -q` all green; frontend `vitest run` all green.
- `git diff --name-only main` shows ONLY the §2 files (+ the constitution amendment + specs/031). NO
  graph/edge/`ContractState`/Node-7/`builder.py` change; `MCPDeliveryStatus` enum unchanged; 7 nodes /
  2 conditional edges intact.

---

## Task 10 — Live smoke (requires owner GCP setup)
**Prerequisite (owner):** in GCP Console (project `feedback-487517`) create a **Web-application OAuth
client**, add authorized redirect URI `http://localhost:8000/api/integrations/google/callback`, and
place its secrets at `GOOGLE_OAUTH_WEB_CREDENTIALS_PATH`. Then, with both servers running:
1. Log in as a test account → `/integrations` → **Connect Google Drive** → complete Google consent →
   returns Connected.
2. Upload a contract → confirm the branded PDF lands in **that account's own Google Drive**, and the
   email (from the central account) arrives with the PDF.
3. A **not-connected** account: upload → email arrives, Drive skipped (status shows not-connected).
4. Disconnect → `/status` shows not connected.
Record the result; a failure blocks merge — investigate.

---

## Acceptance-criteria coverage map
AC-1 → T1 · AC-2,3 → T1 · AC-4,5,6,7,7a,8,9 → T7 · AC-10 → T5 · AC-11 → T5 · AC-12 → T5+T6 · AC-13 → T5
· AC-14 → T5+T6 · AC-15 → T9 · AC-16 → T2+T7 · AC-17 → T7 · AC-18,19 → T8. Live verification → T10.
