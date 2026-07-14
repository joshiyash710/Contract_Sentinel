# Feature 014 — Landing Page + Single-User Authentication

## 1. Problem statement

The app today opens straight into `/dashboard` with no front door and no access
control — feature 011 D1 fixed the backend as **no-auth, localhost-only**, and 013's
frontend phasing deferred auth ("014"). The reference designs, however, include a
**landing/marketing page** (screen 1, `…31 PM.jpeg`) and a **login/sign-up page**
(screen 2, `…31 PM (1).jpeg`), and the product owner wants the app to look and behave
like a real, trustworthy SaaS. This feature builds both:

1. A public **landing page** at `/` (hero, feature grid, "Analyze Your First Contract"
   CTA, Log In / Sign Up).
2. A **single-user login gate**: email + password accounts (hashed), a session cookie,
   a `/login` screen, and **auth enforcement on every `/api/*` endpoint** so the app is
   no longer open.

### Position relative to the constitution

This feature is authorized by the **constitution §2 amendment (2026-07-14)**: a
single-user login gate is now in scope. It is explicitly **NOT** multi-tenancy, per-user
data scoping, RBAC, or granular permissions (those remain PERMANENTLY CUT). There is
**one shared data space** behind the gate — the login is an access gate, not a
data-partitioning mechanism. It **reverses 011 D1's "no-auth"** decision for the API
surface (all `/api/*` now require a valid session); **localhost-only still holds**. Real
Google/Microsoft SSO stays out of scope (buttons render, disabled).

This adds **no LangGraph node/edge and no `ContractState` field** (constitution §2/§4);
it is API-layer + persistence + frontend only. Per §11 it is developed on
`feature/014-auth-landing`.

## 2. Inputs and outputs

### 2.1 New backend surface (auth) — Pydantic boundary models (§4)

| Endpoint | Body | Result |
| --- | --- | --- |
| `POST /api/auth/signup` | `{ email, password }` | `200 { user: {id, email} }` + sets session cookie; `409` if email exists; `422` on weak/invalid input |
| `POST /api/auth/login` | `{ email, password }` | `200 { user }` + sets session cookie; `401` on bad credentials (generic message — no user enumeration) |
| `POST /api/auth/logout` | — | `200`; clears the session cookie |
| `GET /api/auth/me` | — (cookie) | `200 { user }` if authenticated; `401` otherwise |

New Pydantic models: `SignupRequest`, `LoginRequest`, `AuthUser {id, email}`,
`AuthResponse {user: AuthUser}`, mirrored in `frontend/src/lib/api/types.ts` alongside the
existing boundary types (a drift-lock test, AC-19). A new `users` table (Alembic migration
`0003`, in `data/job_store.db` per D17): `id` (uuid text PK), `email` (unique, lowercased),
`password_hash` (text), `created_at` (iso text).

### 2.2 Auth enforcement on existing endpoints

All existing `/api/*` — `analyze`, `jobs`, `jobs/{id}`, `jobs/{id}/events`,
`jobs/{id}/report`, `dashboard` — gain a `require_auth` FastAPI dependency that
returns `401` without a valid session. **Public exceptions:** `GET /api/health` and the
four `/api/auth/*` endpoints. No endpoint scopes data by user (D4 — shared space).

### 2.3 Resolved decisions (inline, per project preference)

- **D1 — Session = signed JWT (HS256) in an httpOnly cookie.** On signup/login the server
  sets `cs_session` (httpOnly, `SameSite=Lax`, `Path=/`, **no `Domain` attribute** so it
  defaults to the request host and works same-origin through the Next proxy — review N1,
  `Max-Age` = `AUTH_SESSION_TTL`). The JWT is signed **HS256** with `AUTH_SECRET`, carrying
  `{sub: user_id, email, exp}`. **`AUTH_SECRET` is always required** (config/env; never a
  hardcoded default, even locally) — on first run with none set, the app generates a random
  ≥32-byte secret and persists it (so tokens aren't signed with a guessable key even on
  localhost — security review S4). `Secure` is **off on localhost http** (named config
  `AUTH_COOKIE_SECURE`, default False; **must be True behind TLS**). Stateless — no server
  session table; logout clears the cookie. **Accepted tradeoff (security review N1):** with
  no server-side revocation, a stolen token stays valid until `exp` (≤ D12's 7 days);
  acceptable for a localhost single-user tool, noted here explicitly.
- **D2 — Passwords hashed with bcrypt** (`passlib[bcrypt]`), cost from a named config
  (`AUTH_BCRYPT_ROUNDS`, default ≥12). To sidestep **bcrypt's 72-byte truncation** (security
  review S2), the password is **pre-hashed** (SHA-256 → base64) before bcrypt, so full-length
  passwords are honored. Policy: **8–128 chars**, validated on signup (out-of-range → `422`).
  Never store or log plaintext (see the no-logging AC). Login uses a **constant-time verify**,
  and — critically — **also runs a bcrypt verify against a fixed dummy hash when the email is
  unknown** (security review M2) so the unknown-email and wrong-password paths take comparable
  time (no timing-based user enumeration); both return the same generic `401`.
- **D3 — `require_auth` dependency** reads `cs_session`, verifies the JWT **pinning
  `algorithms=["HS256"]`** (rejecting `alg=none` and any algorithm-confusion swap — security
  review M1) plus `exp`, loads the user, and yields it; on any failure raises `401`. Applied
  via a **router-level dependency** on a guarded router so it can't be forgotten as endpoints
  grow (review N6); `/api/health` + `/api/auth/*` live on a separate **unguarded** router.
- **D4 — Single-user gate, shared data (constitution amendment).** Accounts may be
  created, but **no endpoint filters by user** — every authenticated session sees the
  same shared jobs/reports/dashboard. No `user_id` is added to any existing table. (Full
  multi-tenancy would be a separate future amendment.)
- **D5 — Route protection (frontend).** `/` (landing) and `/login` are **public**; every
  app route (`/dashboard`, `/upload`, `/jobs/*`, `/reports`, `/contracts`,
  `/integrations`, `/settings`) is **protected**. A Next.js **middleware** checks for the
  presence of the `cs_session` cookie and redirects unauthenticated requests to `/login`
  (a UX redirect; the API is the real authority via `require_auth`). Authenticated users
  hitting `/login` or `/` are sent to `/dashboard`.
- **D6 — Google / Microsoft SSO buttons render but are disabled** ("coming soon"),
  per the chosen scope — no OAuth is wired.
- **D7 — "Forgot password" is a non-functional placeholder** — there is no email/reset
  infrastructure; the link renders (design fidelity) but is disabled/inert. Password
  reset is out of scope (§5).
- **D8 — Landing CTAs route to auth.** Because the app is now gated, "Analyze Your First
  Contract (Free)" and "Sign Up" go to `/login` (Sign-Up tab); "Log In" goes to `/login`
  (Login tab). The landing nav (Features / Integrations / Pricing / Blog): **Features**
  smooth-scrolls to the on-page feature section; **Integrations** → the feature section
  (the real `/integrations` page is gated); **Pricing / Blog** are inert placeholders
  (no such pages) — not fabricated destinations.
- **D9 — Cookie through the Next dev proxy (risk, must verify).** The browser talks to
  `:3000`; `/api/*` is rewritten to `:8000`. The `Set-Cookie` from `:8000` must reach the
  browser as a same-origin `:3000` cookie, and subsequent requests must send it back
  through the proxy. This is verified in the live smoke (AC-20); if the dev `rewrites()`
  proxy strips `Set-Cookie` (as it buffered SSE in 015 D7), the fallback is documented in
  plan.md (e.g. relative cookie path / same-origin handling). Same-origin `SameSite=Lax`
  should pass; this is called out as the top integration risk.
- **D10 — Provider seam.** `signup`, `login`, `logout`, `me` are added to the `ApiClient`
  interface + both providers. **Mock provider** treats the app as authenticated (a fake
  user) so existing unit tests and mock-mode dev need no backend and are not gated. Real
  provider calls the endpoints; a `401` from any call surfaces as an `ApiError(401)` the
  app maps to a redirect to `/login`.
- **D11 — First-run.** With no users, `/api/auth/me` is `401` → the gate sends you to
  `/login`; the Sign-Up tab creates the first account. No seeded/default admin.
- **D15 — `credentials: "include"` across the whole fetch surface (review B1).** Cookie auth
  requires the browser to *send* the cookie. Every `realProvider` call — `submitAnalysis`,
  `getJob`, `getReport`, `getJobs`, `getDashboardMetrics`, `health`, and the four new
  `auth` calls — sets `credentials: "include"`; the `openJobEvents` `EventSource` uses
  `{ withCredentials: true }`. (Same-origin via the proxy would send it anyway, but this is
  required for any non-proxied/cross-origin deploy and is set explicitly.)
- **D16 — Route-group layout refactor so landing/login have NO app shell (review B3).** The
  current root `layout.tsx` wraps every page in `<AppShell>` (sidebar). This feature moves
  the shell into an **`(app)` route group** and puts the public pages in a **`(marketing)`
  group** with a bare layout (no sidebar): `/` (landing) and `/login`. `/` **replaces** the
  current `redirect("/dashboard")`. Authenticated users hitting `/` or `/login` are sent to
  `/dashboard` by the **middleware** (D5), not by the page.
- **D17 — `users` table lives in the existing job-store DB (review B4).** Migration `0003`
  (`down_revision "0002"`) adds `users` to `data/job_store.db` via the existing Alembic
  chain (`main.py` already runs `upgrade_to_head(JOB_STORE_DB_PATH)`). Not a separate DB, not
  the checkpointer DB.
- **D18 — CSRF posture (security review S1).** Mitigated by `SameSite=Lax` **plus** the rule
  that **every state-changing endpoint is non-GET** (`POST` for analyze + all auth) — Lax
  does not send the cookie on cross-site `fetch`/form POST. No dedicated CSRF token (out of
  scope for localhost single-user); **no mutation may ever be exposed via `GET`.**
- **D19 — CORS / same-origin (review B5).** The Next dev proxy (`/api/* → :8000`) makes all
  calls **same-origin**, so cookie auth needs no CORS in dev. `allow_credentials=True` is
  already set. The current `CORS_ALLOWED_ORIGINS` (`:5173`, stale) is **not** relied on; the
  **proxy same-origin path is the only supported one**. A future cross-origin deploy must add
  the real frontend origin to `CORS_ALLOWED_ORIGINS` (never `"*"` with credentials) — noted,
  not done here.

### 2.4 Outputs (what this feature renders)

- **Landing page** (`/`): the screen-1 marketing layout — top nav with logo + Log In /
  Sign Up, the "AI-Powered Legal Contract Intelligence" hero + shield artwork + CTA, and
  the feature cards (Risk Scoring, Clause-by-Clause Explanation, Contract Comparison,
  Integration Ecosystem). Static; no data.
- **Auth page** (`/login`): the screen-2 card — Login / Sign Up tabs, Work Email +
  Password (with show/hide), Forgot Password (inert, D7), "Continue to ContractSentinel"
  submit, and disabled Google / Microsoft buttons (D6). Inline errors for bad
  credentials / existing email / weak password.
- **Gated app**: unauthenticated navigation to any app route redirects to `/login`;
  after login the user lands on `/dashboard`. A **logout** control in the **Sidebar user
  area** (the existing `Sidebar.tsx` footer, review N3) clears the session and returns to
  `/login`.

## 3. Acceptance criteria

Backend criteria → pytest (TestClient); frontend → Vitest + RTL (mock provider unless
noted). The real cookie flow is the live smoke (AC-20).

**Backend — accounts & session**
- AC-1: `POST /api/auth/signup` with a new email + valid password creates a `users` row
  with a **bcrypt hash** (not plaintext), returns `{user:{id,email}}`, and sets the
  `cs_session` httpOnly cookie.
- AC-2: `POST /api/auth/signup` with an existing email → `409`; the password is never
  stored/echoed; email is stored lowercased.
- AC-3: `POST /api/auth/signup` with a password outside **8–128 chars** → `422` with a clear
  message; no row created. (Bcrypt 72-byte truncation is neutralized by the SHA-256 pre-hash,
  D2 — a >72-char password is honored in full.)
- AC-4: `POST /api/auth/login` with correct credentials → `200 {user}` + cookie; with a
  wrong password OR an unknown email → `401` with the **same generic** message, and **both
  paths invoke a bcrypt verify** (the unknown-email path against a dummy hash) so they are
  timing-equalized — no user enumeration (D2 / security review M2; assert the verify is
  called on the unknown-email path via a spy).
- AC-5: `GET /api/auth/me` with a valid cookie → `200 {user}`; with no/invalid/expired
  cookie → `401`.
- AC-6: `POST /api/auth/logout` clears the cookie; a subsequent `GET /api/auth/me` → `401`.
- AC-7: The JWT is signed HS256 with `AUTH_SECRET`; a tampered/foreign-signed cookie → `401`
  (signature check), an expired token → `401` (exp check), and a token whose header `alg` is
  **`none` or any non-HS256** value → `401` (algorithm pinning, security review M1).
- AC-7a: No response body **or log line** ever contains the plaintext password, the
  `AUTH_SECRET`, or the raw session JWT — in particular the `422` weak-password response does
  not echo the submitted password (security review S3).

**Backend — enforcement**
- AC-8: Every protected endpoint (`analyze`, `jobs`, `jobs/{id}`, `jobs/{id}/events`,
  `jobs/{id}/report`, `dashboard`) returns `401` without a valid session and its normal
  `2xx` **with** one (server-side enforcement, not just the middleware — EC-6).
- AC-9: `GET /api/health` and all `/api/auth/*` respond **without** a session (public).
- AC-10: No protected endpoint filters results by user — two different accounts see the
  same shared jobs/dashboard (D4).

**Frontend — landing & auth**
- AC-11: `/` renders the landing hero, the CTA (→ `/login`), Log In / Sign Up (→
  `/login`), and the feature cards; it is reachable **without** a session and renders
  **without the app sidebar/shell** (the `(marketing)` route group, D16). `/login` likewise
  renders shell-free.
- AC-12: `/login` renders Login/Sign-Up tabs, email + password (show/hide), disabled
  Google/Microsoft buttons, and an inert Forgot-Password link.
- AC-13: Submitting the Login tab calls `apiClient.login(email,password)`; on success it
  navigates to `/dashboard`; on `ApiError(401)` it shows an inline "invalid email or
  password" error and does not navigate.
- AC-14: Submitting the Sign-Up tab calls `apiClient.signup(...)`; on success →
  `/dashboard`; on `409` → inline "an account with this email already exists"; on `422`
  → inline password-policy message.
- AC-15: A logout control calls `apiClient.logout()` and returns to `/login`.

**Frontend — gating**
- AC-16: Next middleware redirects an unauthenticated request for a protected route
  (e.g. `/dashboard`) to `/login`, and lets `/` and `/login` through.
- AC-17: An authenticated request to `/login` or `/` redirects to `/dashboard`.
- AC-18: A `401` returned mid-session from any **fetch-based** `getApiClient()` call
  (`getJob`, `getReport`, `getDashboardMetrics`, `submitAnalysis`, `getJobs`, `me`) surfaces
  as a typed `ApiError(401)` the app handles by redirecting to `/login` (no unhandled throw).
  **SSE caveat (review B2):** `EventSource` errors carry no status code, so the
  `openJobEvents` 401 cannot be typed — but the processing screen drives progress by
  **polling `GET /api/jobs/{id}`** (015 D7), which *is* a fetch call, so an expired session
  during processing is caught on the poll and redirects. The SSE route is still gated
  server-side (AC-8); its `onerror` is treated as a recoverable/lost-connection state, not a
  silent success.
- AC-18a: Every `realProvider` fetch and the `EventSource` send credentials — the fetch
  calls set `credentials: "include"` and `openJobEvents` uses `withCredentials: true` (D15;
  assert on the request options).

**Seam / boundary**
- AC-19: `signup`/`login`/`logout`/`me` exist on the `ApiClient` interface and both
  providers; the auth TS types mirror the Pydantic models (drift-lock test). No page
  imports a provider directly (013 seam). No `backend/app/graph/` file is modified.

**Live end-to-end (real backend)**
- AC-20 (smoke, manual/gated): With `provider=real`, signup → the cookie is set **through
  the Next dev proxy**, `/api/auth/me` returns the user, a protected call (e.g.
  `/api/dashboard`) succeeds with the cookie and `401`s without it, logout clears it, and
  the landing/login pages render. This verifies D9 (the proxy forwards `Set-Cookie`).

## 4. Edge cases

- **EC-1 — Malformed/missing body** on signup/login → `422`, no crash.
- **EC-2 — Case/whitespace in email** → normalized (trim + lowercase) before uniqueness
  check and storage, so `A@x.com` and `a@x.com ` are the same account.
- **EC-3 — Expired session mid-use** → the next protected call `401`s (AC-7/AC-18); the
  app redirects to `/login` rather than showing broken data.
- **EC-4 — Tampered cookie** → `401` (signature verify), treated as unauthenticated.
- **EC-5 — Cookie stripped by the dev proxy (D9)** → the smoke catches it; plan.md carries
  the fallback. Never ship a silently-broken gate.
- **EC-6 — Direct API call without a browser (curl)** → same `401`/`2xx` rules; the gate
  is enforced server-side, not just by the middleware (defense in depth).
- **EC-7 — Double signup / concurrent** → the unique constraint on `email` makes the
  second `409`, not a duplicate row.
- **EC-8 — Existing durable data pre-014** → the shared jobs/reports created before auth
  remain visible once logged in (D4 shared space); no migration of ownership needed.
- **EC-9 — `AUTH_SECRET` missing** → the app **never** signs with a hardcoded default (D1):
  it generates+persists a random ≥32-byte secret on first run (local), and a non-local
  (`AUTH_COOKIE_SECURE=True`) deploy **must** supply an explicit one or startup fails loudly.
- **EC-10 — Anyone who can reach localhost can self-provision (open signup, D13/D4)** and
  then see the single shared data space. This is the accepted stance for a local single-user
  tool (security review N3), stated so it isn't a surprise; `AUTH_SIGNUP_OPEN=False` (D13) is
  the future lever to close it.

## 5. Out of scope

- **Multi-tenancy / per-user data scoping / RBAC / roles / teams** — PERMANENTLY CUT
  (constitution §2); this is a single shared-data gate (D4).
- **Real Google / Microsoft SSO** — buttons disabled (D6); OAuth is a later feature if
  wanted (would need provisioned OAuth apps).
- **Password reset / "forgot password" flow, email verification, magic links** — no
  email infrastructure; the link is inert (D7).
- **Account management** (change email/password, delete account, profile editing beyond
  the existing static Settings screen), **2FA**, **rate limiting / lockout**, **CAPTCHA**
  — not built here; notable ones (rate limiting) can be a follow-up.
- **The Settings "Security / Team / Billing" tabs** (screen 4) — those remain static
  chrome; wiring them is separate.
- **Any graph/node/state change** — none (AC-19).

## 6. Resolved decisions (no open questions)

Per the project's inline-decision preference, every significant choice is resolved in
§2.3 (D1–D11). The three previously-open items are now decided with the recommended
defaults:

- **D12 — Session TTL = 7 days.** `AUTH_SESSION_TTL` defaults to 7 days (a "stay logged
  in" experience for a local single-user tool), a named tunable config.
- **D13 — Open signup.** Anyone may sign up (multiple accounts allowed), and **all
  accounts share the same data** (D4). Matches the mockup's Sign-Up tab. A future
  `AUTH_SIGNUP_OPEN=False` toggle to lock signup after the first account is a trivial
  follow-up, not built now.
- **D14 — Landing depth = hero + full feature grid.** Build screen 1's visible content —
  the hero + CTA + the feature-card grid — and no fabricated **Pricing/Blog** pages
  (those nav items are inert placeholders, D8).
