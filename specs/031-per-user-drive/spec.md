# Feature 031 — Per-user Google Drive delivery (Phase 2: per-user OAuth)

## 1. Problem statement

Today all report delivery uses a **single, server-managed Google account** (feature 010; the
`/integrations` page (024) is honest that Drive + Gmail are "server-managed"). Feature 030 made the
delivered artifacts professional (branded PDF + SaaS HTML email), but the **PDF is still uploaded to
the app owner's Drive**, not the user's own. Users want their report saved to **their own Google
Drive**.

This feature (Phase 2) lets each authenticated account **connect its own Google account** so that the
reports it generates are uploaded to **that user's own Drive** (`drive.file` scope), while the
notification email continues to be sent from the central app account.

### Position relative to the constitution

Explicitly **authorized by the §2 AMENDMENT (2026-07-28, feature 031)**. This work is entirely in the
**auth/integration + post-terminal delivery layers** — the delivery step is **NOT a graph node**
(feature 010 §8a D1). Therefore:

- **No LangGraph node/edge change; the fixed 7-node / 2-conditional-edge graph (§2) is untouched.**
- **No `ContractState` change (001).** Per-user credentials are resolved outside the graph (by the
  runner/delivery layer) and never enter graph state. The report artifacts are unchanged.
- **Gmail stays central** — email is still sent FROM the single app account TO the user (feature 020
  recipient logic + feature 030 PDF/HTML email intact). This is **NOT** per-user Gmail.
- **Login is unchanged** — this is a Drive *integration* connection, **NOT** Google SSO login;
  authentication stays email + password (§2 amendment; 014's SSO-login deferral untouched).
- **Stays within Drive + Gmail** — no new provider; adds no item to the PERMANENTLY-CUT list. RBAC,
  teams, sharing, tenant-admin, and per-user Gmail remain CUT.
- New tunables are **named config constants** (§3). API/DB boundary models are **Pydantic** (§4).
- Per §1 + the review gate, spec → plan → tasks → implementation on branch `feature/031-per-user-drive`;
  per §7 TDD; per §9 (external OAuth calls have network latency/timeouts, handled gracefully).

## 2. Inputs and outputs

### 2.1 Per-user token storage (`users` table — new column; no `ContractState` change)

The `users` table (in `job_store.db`; today: `id, email, password_hash, created_at, name, title`)
gains a nullable column for the connecting account's Google credentials:

- `google_oauth_token: TEXT NULL` — the JSON of the user's authorized-user credentials (refresh token
  + client id/secret + scopes + token_uri), i.e. what `Credentials.to_json()` produces. **NULL = not
  connected.** Stored **unencrypted**. NOTE (traceability): the constitution's original PHASE-2-DEFERRED
  list says "Encryption at rest … do not build," which would otherwise forbid this; the **feature-031
  §2 amendment (2026-07-28)** explicitly overrides that for these tokens — *"Encryption-at-rest of
  stored OAuth tokens remains a Phase-2-DEFERRED concern — tokens are stored like today's single
  `google_token.json` until that item lands (a noted, accepted interim posture)."* Plaintext storage
  here is the amendment-authorized interim posture, not a violation of the DEFERRED list.
- Optionally `google_email: TEXT NULL` — the connected Google account's email, for display ("Connected
  as …"). NULL = not connected.

Delivered via a new **Alembic migration `0006`** (latest is `0005`). `UserStore` gains, all
`user_id`-scoped: `set_google_credentials(user_id, token_json, google_email)`,
`get_google_credentials(user_id) -> Optional[str]`, `clear_google_credentials(user_id)`, and a
`get_google_email(user_id)` (or fold into `get_by_id`). No other table changes; `jobs.user_id`
(feature 019) already exists and is the identity that flows to delivery.

### 2.2 Per-user OAuth connect endpoints (`/api/integrations/google/*` — Pydantic boundary, §4)

All require a valid session (`require_auth`) and are **scoped to `current_user`** (mirrors
`app/api/auth.py`). Reuse the existing `GOOGLE_OAUTH_CREDENTIALS_PATH` client secrets.

- `GET /api/integrations/google/status` → `{ "connected": bool, "google_email": Optional[str] }` for
  the current user.
- `GET /api/integrations/google/authorize` → begins the web OAuth flow: builds the Google consent URL
  (`google-auth-oauthlib` `Flow`, `scope=[drive.file]`, `access_type=offline`, `prompt=consent`) with a
  **CSRF-safe `state`** bound to the current session/user, and redirects the browser to Google (or
  returns the URL for the frontend to open).
- `GET /api/integrations/google/callback?code&state` → Google redirects here. **Verifies `state`**,
  exchanges `code` for tokens, extracts the refresh token + Google email, **stores them for
  `current_user`**, and redirects back to `/integrations` (success or error indicator). This is the
  one endpoint reached via a browser redirect from Google — see §6 Q1/Q2 (redirect URI / client type).
- `POST /api/integrations/google/disconnect` → clears the current user's stored credentials
  (best-effort Google token revoke; always deletes locally).

### 2.3 Delivery credential selection (runner + delivery layer)

- The **runner** (which owns `UserStore` and the job's `user_id`) resolves the uploading user's Google
  credentials and passes an **optional per-user Drive credential** into delivery — so the delivery
  layer stays decoupled from the user store. `deliver_report(state, *, recipient=...)` and
  `deliver_report_sync` gain an optional `drive_credentials` (or `drive_token_json`) parameter;
  `run_pipeline` threads it through (alongside the existing `recipient`).
- **Connected user:** the Drive upload (PDF + json, feature 030) authenticates with **that user's**
  credentials → files land in **their** Drive. The Drive MCP path is parametrized to accept a per-user
  token: `google_auth.load_credentials` already takes a `token_path`; `drive_server` currently hardcodes
  the central `GOOGLE_OAUTH_TOKEN_PATH` — it must accept the per-user token (via a new optional field on
  `DriveUploadRequest`, e.g. a token reference the server loads).
- **Not-connected user:** the **Drive step is skipped** — nothing is uploaded to any Drive (never the
  central/app or another user's). `mcp_delivery_status["drive"]` records this with the **existing
  `MCPDeliveryStatus.FAILED` status plus a distinguishing `error_message="user has not connected Google
  Drive"`** (resolved decision, see §6): this keeps the existing status shape and enum (no
  `ContractState`/enum change — AC-15) while clearly separating "not connected" from a genuine Drive
  failure via the message. **The central Gmail email is still sent** (with the PDF attached).
- **Gmail is unchanged** — central token, feature 020 recipient (the user's email), feature 030 PDF +
  HTML email. `mcp_delivery_status` keeps its existing shape `{drive|gmail: {status, error_message,
  delivered_at}}`.

### 2.4 Frontend (`IntegrationsView.tsx`, feature 024)

The currently **disabled** "Connect" affordance becomes real: a **Connect Google Drive** button (→
`authorize`), a real **Connected / Not-connected** state (← `status`, showing the connected Google
email), and a **Disconnect** action (→ `disconnect`). Copy stays honest: **Drive is per-user**; the
**Gmail** card note stays "server-managed / sent from the app account."

## 3. Acceptance criteria

### Token storage + migration
- **AC-1** Migration `0006` adds the `google_oauth_token` (+ `google_email`) nullable column(s);
  `alembic upgrade head` then `downgrade` round-trips cleanly; existing user rows are unaffected
  (columns default NULL = not connected).
- **AC-2** `UserStore.set_google_credentials(user_id, token_json, email)` persists, and
  `get_google_credentials(user_id)` returns it; `clear_google_credentials(user_id)` sets it back to
  NULL. All are strictly scoped by `user_id` (user A cannot read/clear user B's token).
- **AC-3** A freshly created user has `connected == False` (token NULL).

### OAuth endpoints (all require auth; all current-user-scoped)
- **AC-4** `GET /status` returns `{connected: false}` for a new user and `{connected: true,
  google_email: "..."}` after a successful connect; **401** without a session.
- **AC-5** `GET /authorize` returns/redirects to a Google consent URL containing the `drive.file`
  scope, `access_type=offline`, `prompt=consent`, and a `state` value; the `state` is stored/bound so
  the callback can verify it.
- **AC-6** `GET /callback` with a **valid** `state` + `code` exchanges the code (mocked in tests),
  stores the refresh token + google_email for the **current user**, and redirects to `/integrations`.
- **AC-7** `GET /callback` with a **missing/mismatched `state`** (CSRF) is **rejected** (4xx, no token
  stored). A callback carrying Google's `error=access_denied` (user declined) stores nothing and
  redirects with an error indicator — no 500.
- **AC-7a** The `state` is **single-use / expiring**: a **replayed** (already-consumed) but otherwise
  well-formed `state` is rejected just like a mismatch (no token stored), distinct from AC-7's
  missing/mismatched case.
- **AC-8** `POST /disconnect` clears the current user's token (`status` then reports
  `connected:false`); it attempts a best-effort Google revoke but **succeeds locally even if the revoke
  call fails**.
- **AC-9** A user's token is never exposed on the wire: `/status` returns only `connected` +
  `google_email`, never the token JSON/refresh token.

### Delivery routing
- **AC-10** For a **connected** uploader, the Drive upload authenticates with **that user's**
  credentials (assert the per-user token — not the central `GOOGLE_OAUTH_TOKEN_PATH` — is used), and
  `mcp_delivery_status["drive"].status == success`.
- **AC-11** For a **not-connected** uploader, **no Drive upload is attempted** (the drive client is not
  called with real credentials / is skipped), `mcp_delivery_status["drive"].status == FAILED` with
  `error_message == "user has not connected Google Drive"` (the resolved not-connected representation),
  and **the Gmail send still happens** (email delivered, PDF attached).
- **AC-12** Per-user **token-refresh failure** (`invalid_grant` / expired): the Drive upload fails
  gracefully (`mcp_delivery_status["drive"].status == failed` with a clear message), the user is marked
  needing reconnect (`/status` may reflect it — see §6 Q4), and **the email is still sent**. No raise.
- **AC-13** **Gmail is unchanged**: it uses the central token and the feature-030 PDF + HTML email,
  regardless of the uploader's Drive-connection state (assert Gmail path/central token unaffected).
- **AC-14** The uploader's identity reaches delivery: a report for user A's job uses A's credentials;
  a report for user B's job uses B's — no cross-user credential use (assert with two users).

### Constitution / non-regression
- **AC-15** No `ContractState` field added/renamed/removed; the graph still has 7 nodes / 2 conditional
  edges; `report_agent.py`/`builder.py` untouched.
- **AC-16** All new tunables are **sourced from named config constants** (the OAuth redirect URI, the
  `drive.file` scope list, the frontend-redirect target) — no inline literals for scopes/URLs in
  endpoint logic. (The AC asserts the redirect URI is *read from a named constant*; its concrete value
  is pending §6 Q1/Q2 and is set in config once resolved.)
- **AC-17** Feature 019 isolation holds: every `/api/integrations/google/*` endpoint reads/writes only
  the calling account's connection; there is no endpoint that lists or touches another account's token.

### Frontend
- **AC-18** `IntegrationsView` shows **Not connected** with an enabled **Connect Google Drive** button
  when `/status.connected == false`, and **Connected as {google_email}** with a **Disconnect** button
  when true; Connect triggers the authorize flow, Disconnect calls `/disconnect` and re-renders.
- **AC-19** The Gmail card copy remains "server-managed" (central); the page never claims per-user
  Gmail. Existing feature-024 boundary tests are updated (not weakened) to the new per-user-Drive
  reality.

## 4. Edge cases

- **Not connected (the common initial state):** Drive skipped, email sent (AC-11). This is normal, not
  an error — the delivery status must distinguish "user hasn't connected" from a genuine Drive failure.
- **Callback CSRF / replay:** missing, mismatched, or reused `state` → reject, store nothing (AC-7).
- **User denies consent at Google** (`error=access_denied`) → graceful redirect with an error hint,
  nothing stored.
- **Revoked / expired per-user refresh token** (`invalid_grant` on refresh) → Drive fails gracefully,
  email still sent, user flagged to reconnect (AC-12). Mirrors the central-token diagnosis experience.
- **User disconnects while a job is mid-flight:** the credential is resolved at delivery time; if
  cleared before delivery, that job's Drive step is skipped (email still sent) — no crash.
- **Missing/invalid client secrets** (`GOOGLE_OAUTH_CREDENTIALS_PATH` absent): `authorize` returns a
  clear 5xx/500-with-message; connect is unavailable but the app and non-Drive delivery still work.
- **Concurrent connects / double callback:** idempotent — the latest successful token wins; no partial
  state.
- **Legacy users (pre-031):** `google_oauth_token` NULL → treated as not connected; unaffected.
- **`user_id` NULL on a legacy job** (feature 019 legacy rows): resolves to not-connected → Drive
  skipped; email still sent (or the existing legacy-row handling applies).
- **OAuth network timeout** on token exchange/refresh (§9): bounded + surfaced as an error, never a
  hang or unhandled raise.

## 5. Out of scope

- **Token encryption at rest** — per-user tokens are stored unencrypted for now (accepted interim per
  the amendment); encryption is a **Phase-2-DEFERRED** item (constitution §2) owned by a future feature.
- **Per-user Gmail sending** — email stays sent from the central app account (amendment). A future
  amendment would be required to change the sender.
- **Google SSO login** — authentication stays email + password; this feature only *connects* Drive, it
  does not add a login method (014's SSO-login deferral stands).
- **Per-user Drive folder organization** — reports go to the user's Drive root (`drive.file` app-owned
  files); no per-user folder picker/hierarchy in Phase 2.
- **Other providers** (Microsoft/OneDrive/Dropbox, etc.) — PERMANENTLY CUT beyond Google Drive + Gmail.
- **Sharing / RBAC / teams / tenant-admin** — remain CUT; a connection is private to its owner.
- **Changing the report content or the graph** — owned by Node 7 / the pipeline; unchanged here.
- **Migrating existing central-Drive reports** into users' Drives — not attempted.

## 6. Open questions

### Resolved inline (decided; carried into the plan)
- **Q5 — not-connected delivery-status shape → option (b)**: `mcp_delivery_status["drive"]` uses the
  existing `MCPDeliveryStatus.FAILED` + `error_message="user has not connected Google Drive"` (no enum /
  `ContractState` change; distinguishes not-connected from a real failure via the message). Reflected in
  §2.3 and AC-11.
- **Q3 — disconnect → best-effort Google revoke + always delete locally** (AC-8): the revoke is
  attempted but a revoke failure never blocks the local disconnect.
- **Q4 — per-user `invalid_grant` → auto-mark the user disconnected** (clear/flag the token) so `/status`
  shows "reconnect needed"; Drive is skipped, the email still sends (AC-12). No raise.

### Resolved (2026-07-28) — OAuth client + redirect URI
- **Q1 + Q2 → backend `:8000` callback.** Redirect URI = **`http://localhost:8000/api/integrations/
  google/callback`** (baked into a named config constant). The owner will register this on a
  **Web-application OAuth client** in GCP Console (project `feedback-487517`) and point the web-client
  secrets at `GOOGLE_OAUTH_CREDENTIALS_PATH` (or a new web-secrets path) — a setup step required before
  the live connect test, not before the build. The callback hits the backend directly and 302s back to
  the frontend `/integrations`. Prod will need its own registered URI later (future).

### (original open items, now resolved above)
1. **(OAuth client type + redirect URI — owner GCP setup, architecturally significant)** The current
   OAuth client is a **Desktop** client used with `InstalledAppFlow` (loopback). A web connect flow
   needs a **Web-application** OAuth client with an **authorized redirect URI** registered in Google
   Cloud Console — e.g. `http://localhost:8000/api/integrations/google/callback` for local dev.
   **Recommendation:** in GCP Console (project `feedback-487517`) either add a Web-application OAuth
   client (or add the redirect URI to the existing client if it can be a Web type) and point
   `GOOGLE_OAUTH_CREDENTIALS_PATH` (or a new web-client secrets path) at it. **This is a setup step the
   owner must do** — confirm you'll add the Web client + redirect URI, and tell me the exact redirect
   URI to bake into config.
2. **(Callback host / redirect URI value)** Should the callback be hit **directly on the backend**
   (`http://localhost:8000/api/integrations/google/callback`) or **through the Next dev proxy**
   (`http://localhost:3000/api/...` → proxied to :8000)? Recommendation: **register the backend URL**
   (`:8000`) as the redirect URI (simplest, avoids proxy edge cases), and have the callback 302 back to
   the frontend `/integrations`. Confirm the value; note prod will need its own registered URI later.
