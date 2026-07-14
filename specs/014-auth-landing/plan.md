# Landing Page + Single-User Authentication — Technical Plan

## Git Branch

`feature/014-auth-landing` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

Implements `specs/014-auth-landing/spec.md`: a public **landing page** (`/`), a
**`/login`** screen, and a **single-user auth gate** — email/password accounts (bcrypt),
a signed **HS256 JWT in an httpOnly cookie**, `/api/auth/*` endpoints, and `require_auth`
on **every existing `/api/*`** (health + auth stay public). Authorized by the constitution
§2 amendment (single-user gate; **not** multi-tenant/RBAC; reverses 011's no-auth). No
graph node/edge, no `ContractState` field.

Three parts:
1. **Backend auth** — new `users` table (Alembic `0003` in `job_store.db`), a `UserStore`,
   a security module (SHA-256-prehash→bcrypt; HS256 JWT with pinned alg; secret bootstrap),
   an unguarded `/api/auth` router, and a router-level `require_auth` guard on the existing
   routes.
2. **Frontend gate** — a Next `middleware.ts` (cookie-presence redirect, skipped in mock
   mode), a **conditional app shell** (landing/login render shell-free), and the seam
   `signup/login/logout/me` + **`credentials:"include"` across every call**.
3. **Landing + login UI** — screen-1 marketing page and the screen-2 auth card (Login/
   Sign-Up tabs, disabled Google/Microsoft, inert Forgot-Password), plus a Sidebar logout.

All the security-review fixes (pin `alg`, dummy-hash unknown-email login, no-secrets-logging,
always-required secret, CSRF via SameSite=Lax+no-GET-mutations, 72-byte pre-hash) are in §3.

---

## 2. Files to Create / Modify

### Backend (`backend/`)
```
pyproject.toml                          [MODIFY] + deps: passlib[bcrypt], pyjwt
app/config.py                           [MODIFY] + AUTH_* config (§3.1)
alembic/versions/0003_create_users.py   [NEW] users table (down_revision "0002")
app/runner/user_store.py                [NEW] UserStore + UserRow (SQLite, job_store.db)
app/api/security.py                     [NEW] password hash/verify, JWT encode/verify, secret bootstrap, DUMMY_HASH
app/api/auth.py                         [NEW] auth models + auth_router (/api/auth/*) + require_auth dependency
app/api/routes.py                       [MODIFY] split health onto a public_router; main router stays for gated endpoints
app/api/main.py                         [MODIFY] build UserStore + bootstrap secret in lifespan; include public + auth (unguarded) + main (guarded) routers
tests/unit/test_auth_security.py        [NEW] hash/verify, JWT encode/verify + alg-pin, secret bootstrap
tests/unit/test_user_store.py           [NEW] create/get_by_email/get_by_id/dup + migration
tests/integration/test_auth_endpoints.py[NEW] signup/login/logout/me, enforcement, no-enum, no-logging
```

### Frontend (`frontend/`)
```
src/lib/api/types.ts                    [MODIFY] + AuthUser/AuthResponse mirrors
src/lib/api/client.ts                   [MODIFY] + signup/login/logout/me on ApiClient
src/lib/api/realProvider.ts             [MODIFY] + 4 auth calls; credentials:"include" on ALL fetches; EventSource withCredentials (D15)
src/lib/api/mockProvider.ts             [MODIFY] + 4 auth calls (always-authenticated fake user)
src/lib/api/fixtures.ts                 [MODIFY] + authUserFixture
src/__tests__/_fakeClient.ts            [MODIFY] + signup/login/logout/me (+ error scripting)
src/middleware.ts                       [NEW] cookie-gate redirect (skipped when provider=mock)
src/components/shell/AppShell.tsx       [MODIFY] "use client" + usePathname → shell-free for PUBLIC_ROUTES
src/components/shell/UserProfileBlock.tsx [MODIFY] + logout control → apiClient.logout() → /login
src/app/page.tsx                        [MODIFY] replace redirect("/dashboard") with <LandingView/>
src/app/login/page.tsx                  [NEW] <AuthView/>
src/components/marketing/LandingView.tsx [NEW] screen-1 hero + feature grid
src/components/auth/AuthView.tsx        [NEW] screen-2 login/signup card
src/lib/authRoutes.ts                   [NEW] PUBLIC_ROUTES + isProtected(path) (shared by middleware + shell)
src/__tests__/auth-fields.test.ts       [NEW] AuthUser/AuthResponse drift lock
src/__tests__/authView.test.tsx         [NEW] login/signup submit + error mapping (AC-13/14)
src/__tests__/middleware.test.ts        [NEW] redirect logic (AC-16/17)
src/__tests__/realProvider-credentials.test.ts [NEW] every call sends credentials (AC-18a)
```

No `backend/app/graph/` file is touched (AC-19).

---

## 3. Backend design

### 3.1 Config (`app/config.py`) — all tunable (§3)
```python
# ── Authentication (feature 014) ──────────────────────────────────────────────
AUTH_COOKIE_NAME: str = "cs_session"
AUTH_SESSION_TTL_SECONDS: int = 7 * 24 * 3600      # D12 — 7 days
AUTH_COOKIE_SECURE: bool = False                   # D1 — True behind TLS
AUTH_BCRYPT_ROUNDS: int = 12                       # D2
AUTH_PASSWORD_MIN: int = 8
AUTH_PASSWORD_MAX: int = 128                        # D2 (bcrypt 72-byte pre-hashed)
AUTH_SIGNUP_OPEN: bool = True                       # D13
AUTH_SECRET_FILE: str = "data/auth_secret"          # persisted random secret if AUTH_SECRET unset
# AUTH_SECRET itself is read from env at bootstrap (security.py) — never a hardcoded default.
```

### 3.2 Migration `0003_create_users.py`
`revision="0003"`, `down_revision="0002"`. `users`: `id TEXT PK`, `email TEXT NOT NULL
UNIQUE`, `password_hash TEXT NOT NULL`, `created_at TEXT NOT NULL`; `downgrade` drops it.
Lands in `job_store.db` via the existing alembic chain (D17).

### 3.3 `app/runner/user_store.py`
`UserRow{id, email, password_hash, created_at}`; `UserStore(db_path)` (shares the pattern +
lock discipline of `JobStore`): `create(email, password_hash) -> UserRow` (raises
`EmailExists` on the UNIQUE violation), `get_by_email(email) -> UserRow|None`,
`get_by_id(id) -> UserRow|None`, `count() -> int`. Email normalized (trim+lower) by the
caller before storage/lookup (EC-2).

### 3.4 `app/api/security.py` — the security-sensitive core
- **Password (D2 / review S2):** `hash_password(pw)` = `bcrypt(base64(sha256(pw)))` via
  `passlib` `CryptContext(schemes=["bcrypt"], bcrypt__rounds=AUTH_BCRYPT_ROUNDS)`; the
  SHA-256 pre-hash removes bcrypt's 72-byte cap. `verify_password(pw, hash) -> bool`.
  `DUMMY_HASH` = a module-level precomputed hash used to timing-equalize the unknown-email
  login path (review M2).
- **JWT (D1 / review M1):** `make_session(user) -> str` = `jwt.encode({"sub":id,"email":…,
  "exp":now+TTL}, SECRET, algorithm="HS256")`; `read_session(token) -> claims` =
  `jwt.decode(token, SECRET, algorithms=["HS256"])` — **algorithms pinned**, so `alg=none`/
  confusion and bad signatures/exp all raise → treated as unauthenticated.
- **Secret bootstrap (D1 / review S4):** `load_secret()` = `os.environ["AUTH_SECRET"]` if
  set (must be ≥32 bytes when `AUTH_COOKIE_SECURE`); else read `AUTH_SECRET_FILE`; else
  generate `secrets.token_urlsafe(48)`, persist to the file (0600 where supported), and use
  it. **Never a hardcoded default.** Never logged (review S3).

### 3.5 `app/api/auth.py`
- Models: `SignupRequest{email, password}`, `LoginRequest{email, password}`,
  `AuthUser{id, email}`, `AuthResponse{user: AuthUser}`. Signup validates
  `AUTH_PASSWORD_MIN..MAX` (→ `422`, and the error **never echoes the password**, review S3).
- `auth_router = APIRouter(prefix="/api/auth")` (unguarded):
  - `POST /signup` → normalize email; if `not AUTH_SIGNUP_OPEN and count()>0` → `403`;
    `create()` (dup → `409`); set cookie; `200 AuthResponse`.
  - `POST /login` → `get_by_email`; **always** run a `verify_password` (against the real
    hash, or `DUMMY_HASH` when the email is unknown — review M2); on mismatch → generic
    `401`; on success set cookie; `200 AuthResponse`.
  - `POST /logout` → clear the cookie (`Max-Age=0`); `200`.
  - `GET /me` → `require_auth` → `200 AuthResponse`.
  - Cookie set with: `httponly=True, samesite="lax", secure=AUTH_COOKIE_SECURE,
    max_age=TTL, path="/"`, **no `domain`** (review N1) — via `response.set_cookie(...)`.
- `require_auth(request) -> AuthUser` dependency: read `request.cookies[AUTH_COOKIE_NAME]`
  → `read_session` → `UserStore.get_by_id(sub)`; any failure → `HTTPException(401)`. Reads
  `request.app.state.user_store`.

### 3.6 `routes.py` + `main.py` wiring (review N6 — router-level guard)
- **`routes.py`:** move `health` onto a new `public_router = APIRouter(prefix="/api")`;
  the existing `router` keeps all job/dashboard endpoints (now to be guarded at include
  time). (Its handlers are unchanged — the guard is additive; they already take `request`.)
- **`main.py` lifespan:** `bootstrap_secret()`; build `UserStore(JOB_STORE_DB_PATH)` (the
  same DB, already `upgrade_to_head`-migrated) → `application.state.user_store`.
- **`main.py` create_app:** `include_router(public_router)` + `include_router(auth_router)`
  (both unguarded) + `include_router(router, dependencies=[Depends(require_auth)])` (all
  existing endpoints now require a session — AC-8). CORS unchanged (`allow_credentials=True`
  already set; proxy same-origin is the supported path, D19).

---

## 4. Frontend design

> **Client/server (constitution §8).** `AppShell` becomes a client component (`usePathname`).
> `AuthView`, `LandingView`'s interactive bits, and `UserProfileBlock`'s logout are client.
> `middleware.ts` runs in the Next middleware runtime (not jsdom) — unit-tested as a plain
> function. `app/page.tsx` and `app/login/page.tsx` are thin server shells rendering the
> client views.

### 4.1 Seam (`types.ts`/`client.ts`/providers/fixtures)
- **types.ts:** `AuthUser{id:string; email:string}`, `AuthResponse{user:AuthUser}`.
  `auth-fields.test.ts` locks them (AC-19).
- **client.ts:** `signup(email,password):Promise<AuthResponse>`,
  `login(email,password):Promise<AuthResponse>`, `logout():Promise<void>`,
  `me():Promise<AuthUser>` on `ApiClient`.
- **realProvider.ts:** implement the 4 (POST `/api/auth/*`, GET `/api/auth/me`), and add
  **`credentials:"include"` to every `fetch`** (the 4 auth + `submitAnalysis`, `getJob`,
  `getReport`, `getJobs`, `getDashboardMetrics`, `health`) and **`{withCredentials:true}`**
  to the `openJobEvents` `EventSource` (D15/AC-18a). A `401` → `ApiError(401)`.
- **mockProvider.ts:** `me`/`login`/`signup` return `authUserFixture` wrapped
  (always-authenticated); `logout` resolves. So mock-mode dev/tests are never gated.
- **_fakeClient.ts:** add the 4 with `authError`/`meError` scripting for the view tests.

### 4.2 `middleware.ts` + `lib/authRoutes.ts`
- `authRoutes.ts`: `PUBLIC_ROUTES = ["/", "/login"]`; `isProtected(pathname)` = not public
  and not a Next asset. Shared by the middleware and `AppShell`.
- `middleware.ts`: **if `process.env.NEXT_PUBLIC_API_PROVIDER === "mock"` → `NextResponse.
  next()`** (mock is ungated dev/test). Else: read the `cs_session` cookie —
  - protected path without cookie → `redirect("/login")` (AC-16);
  - `/` or `/login` **with** cookie → `redirect("/dashboard")` (AC-17);
  - else `next()`. `config.matcher` excludes `/_next`, static, and `/api` (the API guards
    itself). Presence-only check — the API is the real authority (D5); a garbage cookie
    passes middleware then the first data call `401`s → redirect (AC-18; brief flash
    accepted).

### 4.3 Conditional shell (`AppShell.tsx`)
`"use client"`; `const pathname = usePathname();` if `PUBLIC_ROUTES.includes(pathname)`
return `<>{children}</>` (no sidebar — AC-11); else the existing sidebar layout. Keeps every
current app page unchanged.

### 4.4 Landing (`app/page.tsx` → `LandingView`)
Replace `redirect("/dashboard")`. `LandingView` (screen 1): top nav (logo, Features /
Integrations / Pricing / Blog, **Log In / Sign Up → `/login`**), hero "AI-Powered Legal
Contract Intelligence" + shield artwork + **"Analyze Your First Contract (Free)" → `/login`**
(D8), and the feature-card grid (Risk Scoring, Clause-by-Clause Explanation, Contract
Comparison, Integration Ecosystem). Pricing/Blog inert; Features anchors on-page (D8/D14).

### 4.5 Auth page (`app/login/page.tsx` → `AuthView`)
`"use client"` (screen 2): Login/Sign-Up tabs; Work Email + Password (reuse
`PasswordInput` show/hide); inert Forgot-Password (D7); "Continue to ContractSentinel"
submit; disabled Google/Microsoft (D6). Submit → `apiClient.login|signup` →
`router.replace("/dashboard")`; map `ApiError`: `401`→"invalid email or password",
`409`→"account already exists", `422`→password-policy message (AC-13/14).

### 4.6 Logout (`UserProfileBlock.tsx`)
Add a logout affordance (menu/button) in the Sidebar footer → `getApiClient().logout()` →
`router.replace("/login")` (AC-15).

---

## 5. Tests mapped to acceptance criteria

**Backend (pytest).**
- `test_auth_security.py`: `hash/verify` round-trip; a >72-char password verifies (pre-hash);
  `make_session/read_session` round-trip; **tampered → error, `alg=none`/non-HS256 → error,
  expired → error** (AC-7); secret bootstrap generates+persists when unset, and never a
  hardcoded default (AC-7 spirit / S4).
- `test_user_store.py`: create + `get_by_email`/`get_by_id`; duplicate email raises
  (`409` source, AC-2); email normalized (EC-2); migration adds `users` (AC-1 substrate).
- `test_auth_endpoints.py` (TestClient): signup sets cookie + bcrypt hash stored not
  plaintext (AC-1); dup email `409` (AC-2); short/long password `422` **without echoing the
  password** (AC-3/AC-7a); login ok sets cookie, wrong-password AND unknown-email both `401`
  generic and **both invoke verify_password** (AC-4, spy on the unknown path); `me` with/
  without cookie `200`/`401` (AC-5); logout clears cookie then `me`→`401` (AC-6); a
  protected endpoint (`/api/dashboard`, `/api/jobs`) `401` w/o cookie and `2xx` with (AC-8);
  `health` + `/api/auth/*` public (AC-9); two accounts see the same shared jobs (AC-10);
  a response/log never contains the password/secret/JWT (AC-7a).

**Frontend (Vitest + RTL, mock provider).**
- `auth-fields.test.ts`: `AuthUser`/`AuthResponse` field lock (AC-19).
- `middleware.test.ts`: construct `NextRequest`s → protected w/o cookie → `/login` (AC-16);
  `/`+cookie → `/dashboard` (AC-17); public w/o cookie → next; `provider=mock` → always next.
- `authView.test.tsx`: login submit → `login()` → `replace('/dashboard')`; `401`→inline
  error, no nav (AC-13); signup → `signup()`; `409`/`422`→inline errors (AC-14); SSO buttons
  disabled + Forgot-Password inert (AC-12).
- `realProvider-credentials.test.ts`: stub `fetch`/`EventSource`; assert every call passes
  `credentials:"include"` / `withCredentials:true` (AC-18a).
- Landing render test: hero + CTA (→`/login`) + feature cards, and it renders **without a
  sidebar** under the mock/public path (AC-11). Boundary grep: no direct provider import in
  `components/auth`/`components/marketing`.
- Existing 013/015/017/018 suites stay green (mock middleware skip + conditional shell keep
  all current pages working).

**Live smoke (AC-20):** `provider=real`; signup → cookie set **through the Next proxy**;
`me` returns the user; `/api/dashboard` succeeds with the cookie and `401`s without; logout
clears it; landing/login render shell-free. Verifies D9 (Set-Cookie survives the proxy).

**Security review of the diff:** run the `/security-review` skill before merge (auth is
security-sensitive) in addition to the code review.

---

## 6. Implementation order (TDD — constitution §7)

1. **Deps + config:** add `passlib[bcrypt]`+`pyjwt` to `pyproject.toml` (install into the
   venv); add `AUTH_*` config.
2. **Security core:** `security.py` + `test_auth_security.py` (hash/verify, JWT + alg-pin,
   secret bootstrap) — red→green, no HTTP.
3. **Persistence:** migration `0003` + `user_store.py` + `test_user_store.py`.
4. **Auth endpoints + guard:** `auth.py` (models, router, `require_auth`); split `health`
   onto `public_router`; wire `main.py` (UserStore + secret in lifespan; guarded include);
   `test_auth_endpoints.py`. Then **migrate the existing integration tests to authenticate**
   (see §7 — this is bigger than one fixture) and run the **whole backend suite** green.
5. **Frontend seam:** `types` + `client` + providers (+ `credentials:"include"` everywhere)
   + fixtures + `auth-fields` + `realProvider-credentials` tests.
6. **Gate + shell:** `authRoutes.ts` → `middleware.ts` (+ test) → `AppShell` conditional.
7. **UI:** `LandingView` (`/`) + `AuthView` (`/login`) + `UserProfileBlock` logout;
   `authView.test.tsx` + landing render test.
8. **Verify:** `pytest` (whole), `vitest run` (whole), `tsc --noEmit`, `npm run lint`,
   `next build` (dev STOPPED). Confirm no `backend/app/graph/` change (AC-19).
9. **Security review** (`/security-review`) + **live smoke** (AC-20). Reset `.env.local`
   to `mock` after.

Each step’s tests are written failing first (§7). Step 4’s fixture change to the existing
integration suite is the one place existing tests are *modified* — because the endpoints’
contract legitimately changed (now gated); the assertions on behavior are preserved, the
tests just authenticate first.

---

## 7. Notes / risks

- **Gating breaks existing integration tests until they authenticate — bigger than one
  fixture (verified against the real suite).** Starlette `TestClient` (httpx-backed) DOES
  persist cookies on the instance, so one auth call makes an instance authenticated. But the
  surface is two-pronged:
  - **7 tests use the shared `client` fixture** (conftest.py) → one fixture change: call a
    new `authenticate(client)` helper before `yield`.
  - **6 files build their OWN TestClient** and hit gated routes — `test_api_jobs.py`,
    `test_ingest_error_durable.py`, `test_recover_{missing_upload,queued_fresh,terminal_untouched}.py`,
    `test_restart_get_survives.py` — each must call `authenticate(client)` after constructing
    its client. The **restart** tests build a *second* client (`c2`) on the SAME DB where the
    user row persists but the cookie does not, so the helper must be **idempotent —
    signup-or-login** (`POST /signup`; on `409` `POST /login`) so `c1` signs up and `c2`
    logs in. Provide `authenticate(client)` in `conftest.py` and call it in the fixture AND
    in each self-client file (and after each restart `_make_client`). Estimate: ~1 shared
    helper + ~8 call-site edits — plan tasks.md for all of them, not a single change.
- **Cookie through the Next proxy (D9/AC-20)** — Next `rewrites()` forwards response headers
  incl. `Set-Cookie` (the SSE issue was body *streaming*, not headers); the load-bearing
  detail is **no `Domain` attribute** on the cookie so it binds to `localhost:3000`. Smoke
  confirms.
- **Mock-mode ungated (middleware skip)** keeps all existing unit tests + mock dev working
  without a backend; real gating is exercised by `middleware.test.ts` (function-level) +
  the live smoke.
- **New backend deps** (`passlib[bcrypt]`, `pyjwt`) must be installed in the venv before the
  backend runs/tests; note bcrypt’s native wheel.
- **Secret file** `data/auth_secret` is generated on first run and must be **git-ignored**
  (like the DBs). Add to `.gitignore`.
- **`next build` vs `next dev`** — never build while dev runs (013/015 lesson); step 8 builds
  with dev stopped.
- **Security posture is documented, not hardened for scale** — no rate limiting/lockout/2FA
  (§5); acceptable for localhost single-user, revisit if ever deployed (D1/D18/EC-10 notes).

---

*Per constitution §1/§11, a `feature/014-auth-landing` branch opens only after this plan.md
and its spec.md are approved and `tasks.md` exists. No `tasks.md` or implementation was
written in this pass — plan only.*
