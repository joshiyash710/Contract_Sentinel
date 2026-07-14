# Landing Page + Single-User Authentication — Implementation Tasks

Reference documents:
- Spec: `specs/014-auth-landing/spec.md`
- Plan: `specs/014-auth-landing/plan.md`
- Constitution: `specs/000-constitution.md` (§2 amendment 2026-07-14 authorizes this)
- Consumed: 011 (`app/api/routes.py`, `main.py`), 012 (`app/runner/store.py`, migrations),
  013/017/018 frontend seam (`lib/api/*`), the two mockups: screen 1 (`…31 PM.jpeg`,
  landing) + screen 2 (`…31 PM (1).jpeg`, login)

Backend paths relative to `backend/`, frontend to `frontend/`.

**Workflow reminders:**
- TDD (§7): tests written + confirmed FAILING before implementation. The one sanctioned
  test *modification* is authenticating the existing integration tests (Task 5) — their
  behavior assertions are preserved; they just sign in first (the endpoint contract
  legitimately changed to gated).
- **No `backend/app/graph/` change** (AC-19). This is API + persistence + frontend only.
- **Security is the point** — do not skip: pin JWT `algorithms=["HS256"]`; SHA-256 pre-hash
  before bcrypt; dummy-hash verify on unknown-email login; never log password/secret/JWT;
  `AUTH_SECRET` never hardcoded; cookie httpOnly + SameSite=Lax + **no Domain**;
  `credentials:"include"` on every frontend call.
- Boundary = Pydantic (backend) mirrored in `types.ts` (§4). No graph/`ContractState`.
- NEVER `next build` while `next dev` runs. Stop dev first.

---

## Task 0: Branch
- [ ] Confirm spec + plan + tasks approved (§1/§11). From up-to-date `main`, create
  `feature/014-auth-landing` (`git-start`).

**Verify:** `git branch --show-current` → `feature/014-auth-landing`.

---

## Task 1: Deps + config (backend)
- [ ] **[MODIFY] `pyproject.toml`** — add `passlib[bcrypt]` and `pyjwt`; install into the
  venv (`pip install -e .` or the project's install path). Confirm `import passlib`, `import jwt`.
- [ ] **[MODIFY] `app/config.py`** — add the `AUTH_*` block (plan §3.1): `AUTH_COOKIE_NAME`,
  `AUTH_SESSION_TTL_SECONDS` (7d), `AUTH_COOKIE_SECURE` (False), `AUTH_BCRYPT_ROUNDS` (12),
  `AUTH_PASSWORD_MIN` (8), `AUTH_PASSWORD_MAX` (128), `AUTH_SIGNUP_OPEN` (True),
  `AUTH_SECRET_FILE` (`data/auth_secret`).
- [ ] **[MODIFY] `.gitignore`** — add `backend/data/auth_secret` (like the DBs).

**Verify:** `python -c "import app.config, passlib, jwt"` clean.

---

## Task 2: Security core `app/api/security.py` (tests first)
- [ ] **[NEW] `tests/unit/test_auth_security.py`** — confirm FAILING:
  - `hash_verify_roundtrip`: `verify_password(pw, hash_password(pw))` true; wrong pw false.
  - `long_password_honored`: a 100-char password (>72 bytes) hashes+verifies (SHA-256
    pre-hash, D2/S2); two passwords sharing a 72-byte prefix do NOT collide.
  - `jwt_roundtrip`: `read_session(make_session(user))` returns `{sub,email}`.
  - `jwt_rejects_tampered_alg_expired`: a tampered token, a token with header `alg:"none"`
    or a non-HS256 alg, and an expired token each raise (AC-7 / M1).
  - `secret_bootstrap`: with `AUTH_SECRET` unset and no file, `load_secret()` generates +
    persists a ≥32-byte secret to `AUTH_SECRET_FILE`; a second call reads the same value;
    with the env var set, that value wins; **never returns a hardcoded default** (S4).
- [ ] **[NEW] `app/api/security.py`** per plan §3.4: `CryptContext(bcrypt)`, `hash_password`
  (sha256→base64→bcrypt), `verify_password`, `DUMMY_HASH`, `make_session`/`read_session`
  (HS256, `algorithms=["HS256"]` pinned), `load_secret()` (env → file → generate+persist,
  0600). Never log the secret/JWT/password.

**Verify:** `pytest tests/unit/test_auth_security.py` → PASS.

---

## Task 3: Migration + `UserStore` (tests first)
- [ ] **[NEW] `alembic/versions/0003_create_users.py`** — `revision="0003"`,
  `down_revision="0002"`; `users(id PK, email UNIQUE NOT NULL, password_hash NOT NULL,
  created_at NOT NULL)`; downgrade drops it.
- [ ] **[NEW] `tests/unit/test_user_store.py`** — confirm FAILING (temp DB + `upgrade_to_head`):
  `create` + `get_by_email`/`get_by_id` round-trip; duplicate email raises `EmailExists`;
  email normalized (trim+lower, EC-2); `count()`.
- [ ] **[NEW] `app/runner/user_store.py`** — `UserRow`, `UserStore(db_path)` (lock-guarded
  like `JobStore`), `EmailExists`, the methods above. Lives in `job_store.db` (D17).

**Verify:** `pytest tests/unit/test_user_store.py` + the alembic-head test still green.

---

## Task 4: Auth endpoints + guard wiring (tests first)
- [ ] **[NEW] `tests/integration/test_auth_endpoints.py`** — confirm FAILING (TestClient):
  - `signup_sets_cookie_hashes_pw` (AC-1): 200 + `cs_session` cookie; the stored
    `password_hash` is bcrypt (not plaintext).
  - `signup_dup_409` (AC-2); email stored lowercased.
  - `signup_password_out_of_range_422` (AC-3) **and the 422 body does not echo the password**
    (AC-7a).
  - `login_ok_and_generic_401` (AC-4): correct → 200+cookie; wrong-pw AND unknown-email →
    same generic 401; **spy asserts `verify_password` runs on the unknown-email path** (M2).
  - `me_requires_cookie` (AC-5); `logout_clears_cookie` then `me`→401 (AC-6).
  - `jwt_alg_none_rejected` (AC-7): a crafted `alg:none`/foreign-signed cookie → 401.
  - `protected_requires_session` (AC-8): `/api/dashboard` + `/api/jobs` → 401 without,
    2xx with; `health` + `/api/auth/*` public (AC-9).
  - `two_accounts_share_data` (AC-10): sign up two users; both see the same jobs list.
  - `no_secrets_logged` (AC-7a): capture logs during signup/login; assert no plaintext
    password / `AUTH_SECRET` / raw JWT appears.
- [ ] **[NEW] `app/api/auth.py`** per plan §3.5: models (`SignupRequest`, `LoginRequest`,
  `AuthUser`, `AuthResponse`), `auth_router` (`/api/auth/{signup,login,logout,me}`), cookie
  set with `httponly, samesite="lax", secure=AUTH_COOKIE_SECURE, max_age=TTL, path="/"`,
  **no domain**; `require_auth(request)->AuthUser` reading `request.app.state.user_store`.
  Signup honors `AUTH_SIGNUP_OPEN`. Login uses `DUMMY_HASH` on unknown email (M2).
- [ ] **[MODIFY] `app/api/routes.py`** — move `health` onto a new `public_router =
  APIRouter(prefix="/api")`; leave the job/dashboard endpoints on `router`. (Handlers
  unchanged.) Refresh the module docstring's endpoint count while here.
- [ ] **[MODIFY] `app/api/main.py`** — in lifespan: `security.load_secret()` (bootstrap);
  build `UserStore(JOB_STORE_DB_PATH)` → `application.state.user_store`. In create_app:
  `include_router(public_router)` + `include_router(auth_router)` (unguarded) +
  `include_router(router, dependencies=[Depends(require_auth)])` (guarded).

**Verify:** `pytest tests/integration/test_auth_endpoints.py` → PASS.

---

## Task 5: Migrate existing integration tests to authenticate (the big one — plan §7)
- [ ] **[MODIFY] `tests/integration/conftest.py`** — add an idempotent helper
  `authenticate(client)`: `POST /api/auth/signup {email,password}`; on `409` `POST
  /api/auth/login`. (TestClient persists the cookie on the instance.) Call it in the shared
  `client` fixture before `yield`.
- [ ] **[MODIFY] the 6 self-client files** — after each `TestClient(create_app())` /
  `_make_client(...)` construction, call `authenticate(client)`:
  `test_api_jobs.py`, `test_ingest_error_durable.py`, `test_recover_missing_upload.py`,
  `test_recover_queued_fresh.py`, `test_recover_terminal_untouched.py`,
  `test_restart_get_survives.py`. For the **restart** tests, authenticate BOTH `c1`
  (signs up) and `c2` (same DB → 409 → logs in) — the idempotent helper handles both.

**Verify:** `pytest` (WHOLE backend suite) → all green (011/012/018 + new 014).

---

## Task 6: Frontend seam + credentials (tests first)
- [ ] **[MODIFY] `src/lib/api/types.ts`** — `AuthUser{id,email}`, `AuthResponse{user}`.
- [ ] **[MODIFY] `src/lib/api/client.ts`** — `signup`/`login`/`logout`/`me` on `ApiClient`.
- [ ] **[MODIFY] `src/lib/api/realProvider.ts`** — implement the 4; add
  `credentials:"include"` to **every** fetch (the 4 + `submitAnalysis`, `getJob`,
  `getReport`, `getJobs`, `getDashboardMetrics`, `health`) and `{withCredentials:true}` to
  the `openJobEvents` EventSource (D15).
- [ ] **[MODIFY] `src/lib/api/mockProvider.ts`** — `me`/`login`/`signup` → `authUserFixture`
  (always authenticated); `logout` resolves.
- [ ] **[MODIFY] `src/lib/api/fixtures.ts`** — `authUserFixture`.
- [ ] **[MODIFY] `src/__tests__/_fakeClient.ts`** — add the 4 (+ `authError` scripting).
- [ ] **[NEW] `src/__tests__/auth-fields.test.ts`** — `AuthUser`/`AuthResponse` drift lock (AC-19).
- [ ] **[NEW] `src/__tests__/realProvider-credentials.test.ts`** — stub `fetch`/`EventSource`;
  assert every call passes `credentials:"include"` / `withCredentials:true` (AC-18a).

**Verify:** those two tests PASS; `tsc --noEmit` clean.

---

## Task 7: Middleware gate + conditional shell (tests first)
- [ ] **[NEW] `src/lib/authRoutes.ts`** — `PUBLIC_ROUTES = ["/","/login"]`, `isProtected(path)`.
- [ ] **[NEW] `src/__tests__/middleware.test.ts`** — confirm FAILING: build `NextRequest`s →
  protected + no cookie → redirect `/login` (AC-16); `/` + cookie → `/dashboard` (AC-17);
  public + no cookie → next; `NEXT_PUBLIC_API_PROVIDER="mock"` → always next.
- [ ] **[NEW] `src/middleware.ts`** — mock-skip; cookie-presence redirects per plan §4.2;
  `config.matcher` excludes `/_next`, static, `/api`.
- [ ] **[MODIFY] `src/components/shell/AppShell.tsx`** — `"use client"`; `usePathname()`;
  render `<>{children}</>` for `PUBLIC_ROUTES`, else the sidebar layout (AC-11).

**Verify:** `vitest run src/__tests__/middleware.test.ts` PASS; existing 013/015/017/018
page tests still green (mock middleware skip + conditional shell keep them working).

---

## Task 8: Landing + login + logout UI (tests first)
- [ ] **[NEW] `src/__tests__/authView.test.tsx`** — confirm FAILING (mock provider; router
  mock with `replace`): login submit → `login()` → `replace('/dashboard')`; `401` → inline
  error, no nav (AC-13); signup → `signup()`; `409`/`422` → inline errors (AC-14); SSO
  buttons disabled + Forgot-Password inert (AC-12).
- [ ] **[NEW] `src/__tests__/landing.test.tsx`** — `/` landing renders hero + CTA (→`/login`)
  + Log In/Sign Up (→`/login`) + feature cards, **without a sidebar** (AC-11).
- [ ] **[NEW] `src/components/marketing/LandingView.tsx`** — screen-1 hero + nav + feature grid (D8/D14).
- [ ] **[NEW] `src/components/auth/AuthView.tsx`** — screen-2 card: tabs, email + `PasswordInput`,
  inert Forgot-Password, disabled Google/Microsoft, submit + error mapping.
- [ ] **[MODIFY] `src/app/page.tsx`** — replace `redirect("/dashboard")` with `<LandingView/>`.
- [ ] **[NEW] `src/app/login/page.tsx`** — `<AuthView/>`.
- [ ] **[MODIFY] `src/components/shell/UserProfileBlock.tsx`** — logout control →
  `getApiClient().logout()` → `router.replace('/login')` (AC-15).
- [ ] **[NEW] `src/__tests__/auth-boundary.test.ts`** — no `realProvider`/`mockProvider`
  import in `components/auth` / `components/marketing`.

**Verify:** `vitest run` for these → PASS.

---

## Task 9: Full verification
- [ ] `pytest` (whole backend) GREEN.
- [ ] `vitest run` (whole frontend) GREEN; `tsc --noEmit` clean; `npm run lint` clean.
- [ ] Stop dev; `next build` succeeds (`/`, `/login` build; middleware compiles).
- [ ] `git diff --name-only` — no `backend/app/graph/` file changed (AC-19).

---

## Task 10: Security review + live smoke (AC-20)
- [ ] Run the **`/security-review`** skill on the branch diff (auth is security-sensitive);
  address findings.
- [ ] `alembic upgrade head` (applies `0003`). Start `uvicorn` + set
  `frontend/.env.local` `NEXT_PUBLIC_API_PROVIDER=real`; `npm run dev`.
- [ ] Smoke: visit `/` (landing, no shell) → `/login`; **sign up** → confirm the
  `cs_session` cookie is set **through the Next proxy** (DevTools) and you land on
  `/dashboard`; reload → still in (cookie persists); `curl` a protected endpoint without the
  cookie → 401; **logout** → back to `/login` and protected routes redirect there. This
  verifies D9 (Set-Cookie survives the proxy).
- [ ] Reset `.env.local` to `mock`. Report the outcome.

---

## Task 11: Merge
- [ ] All suites + `tsc` + `build` green; security review clean; smoke noted.
- [ ] Rebase `main`, merge `feature/014-auth-landing`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/014-auth-landing`, opened after spec +
plan + tasks are approved. New backend deps: `passlib[bcrypt]`, `pyjwt`. The `data/auth_secret`
file is git-ignored (Task 1).*
