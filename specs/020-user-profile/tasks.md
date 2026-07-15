# User Profile (Name/Title) + Report-to-Owner Email — Implementation Tasks

Reference documents:
- Spec: `specs/020-user-profile/spec.md`
- Plan: `specs/020-user-profile/plan.md`
- Constitution: `specs/000-constitution.md` (**no amendment needed** for 020)
- Consumed: 014 (`app/api/auth.py`, `user_store.py`, auth seam), 019 (`routes.py` analyze
  already has `current_user`; conftest `authenticate`/`authenticate_as`/`seed_owner_user`),
  018 (dashboard/topbar), 013 shell (Sidebar/TopBar/UserProfileBlock)

Backend paths relative to `backend/`, frontend to `frontend/`.

**Workflow reminders:**
- TDD (§7): tests written + confirmed FAILING before implementation. The sanctioned test
  *modifications* here are the signup call sites (contract gained a required `name`) and the
  recipient-default expectations — assertions preserved/extended, never weakened.
- **No `backend/app/graph/` change, no `ContractState` field, no new endpoint.**
- **JWT stays `{sub,email,exp}`** — name/title are loaded from the DB in `require_auth`, never
  baked into the token.
- SSO stays deferred (Google/Microsoft buttons remain disabled).
- NEVER `next build` while `next dev` runs. Stop dev first.

---

## Task 0: Branch
- [ ] Confirm spec + plan approved (§1). From up-to-date `main`, create
  `feature/020-user-profile` (`git-start`). Commit the 020 `spec.md`/`plan.md`/`tasks.md`
  (docs) on the branch. (No constitution amendment for this feature.)

**Verify:** `git branch --show-current` → `feature/020-user-profile`.

---

## Task 1: Migration `0005` (users.name, users.title)
- [ ] **[NEW] `alembic/versions/0005_add_user_name_title.py`** — `revision="0005"`,
  `down_revision="0004"`. Upgrade: `op.add_column("users", sa.Column("name", sa.Text,
  nullable=True))` and `op.add_column("users", sa.Column("title", sa.Text, nullable=True))`.
  Downgrade drops both (plain `op.drop_column`, mirroring 0002/0004 style).
- [ ] **[MODIFY] `tests/integration/test_alembic_head.py`** — assert the `users` table now has
  `name` and `title` columns after `upgrade_to_head` (add a users-columns check if the file
  only checks `jobs`; otherwise extend the existing users assertion).

**Verify:** `pytest tests/integration/test_alembic_head.py` → PASS.

---

## Task 2: UserStore name/title (tests first)
- [ ] **[MODIFY] `tests/unit/test_user_store.py`** — confirm FAILING: `create(email, pw, name,
  title)` then `get_by_id`/`get_by_email` return `name`/`title`; a row created with
  `title=None` reads back `title is None`.
- [ ] **[MODIFY] `app/runner/user_store.py`**:
  - `UserRow` gains `name: Optional[str]` + `title: Optional[str]`.
  - `create(self, email, password_hash, name, title)` — INSERT includes `name`,`title`.
  - `get_by_email` / `get_by_id` — SELECT + populate `name`/`title`.
  - All values bound via `?` (no string-building).

**Verify:** `pytest tests/unit/test_user_store.py` → PASS.

---

## Task 3: Auth models + endpoints name/title (tests first) — includes the signup-call-site fix
- [ ] **[MODIFY] `tests/integration/test_auth_endpoints.py`** — confirm FAILING first, then green:
  - New: signup with `{email,password,name,title}` → `AuthUser` (and `/me`) return `name`+`title`
    (AC-1).
  - New: signup with **missing/blank `name`** → `422` (AC-2); signup with **no `title`** → `200`,
    title stored NULL.
  - New: a directly-seeded `name=NULL` user → `GET /api/auth/me` `200` with `name: null` (AC-3).
  - **[SIGNUP-CALL-SITE FIX]** Add a valid `name` (e.g. `"Test User"`) to the `_signup` helper
    default AND to **every inline** `auth_client.post("/api/auth/signup", json={...})` in this
    file (e.g. `test_signup_email_stored_lowercase`, `test_signup_short_password_422`,
    `test_signup_long_password_422`, `test_signup_exact_boundary_passwords`,
    `test_two_accounts_isolated`) — EXCEPT the new missing-name test, which omits it on purpose.
    (Without a valid name those tests would 422 for the wrong reason.)
- [ ] **[MODIFY] `tests/integration/conftest.py`** — `authenticate(client)` and
  `authenticate_as(client,email,pw)` include a default `name` in their signup POST body.
  (`seed_owner_user` is unaffected — direct SQL, nullable columns.)
- [ ] **[MODIFY] `app/api/auth.py`**:
  - `SignupRequest`: `name: str` validator (trim; `1..100` chars else `ValueError` → 422);
    `title: Optional[str] = None` (trim; `≤100`). Email/password validators unchanged.
  - `AuthUser`: `+ name: Optional[str] = None`, `+ title: Optional[str] = None`.
  - `signup`: `create(body.email, pw_hash, body.name, body.title)`; build
    `AuthUser(id,email,name,title)` for `make_session` (reads only id/email — JWT unchanged) and
    the response.
  - `login`, `require_auth`, `me`: build `AuthUser` from the row **including** `row.name`/
    `row.title`. `LoginRequest` unchanged.

**Verify:** `pytest tests/integration/test_auth_endpoints.py` → PASS.

---

## Task 4: Recipient defaults to owner email (tests first)
- [ ] **[MODIFY] `tests/integration/test_api_analyze.py`** — confirm FAILING: after `POST
  /api/analyze` as the authed user with NO `recipient`, the stored `JobRow.recipient ==`
  that user's email (`current_user_id`→email via `/me`, or assert equals the fixture email);
  with an explicit `recipient` form field, that value wins (AC-4).
- [ ] **[MODIFY] `app/api/routes.py`** — in `analyze`, before building the `JobRecord`, set
  `recipient = recipient or current_user.email`.
- [ ] Grep the delivery/analyze tests for any assertion that a job's `recipient` is `None`/empty
  without an explicit one; update to expect the authed user's email.

**Verify:** `pytest tests/integration/test_api_analyze.py` + **whole backend suite** → green.

---

## Task 5: Frontend seam (tests first)
- [ ] **[MODIFY] `src/lib/api/types.ts`** — `AuthUser` gains `name?: string | null;
  title?: string | null`.
- [ ] **[MODIFY] `src/__tests__/auth-fields.test.ts`** — drift-lock `AuthUser` incl. `name`/
  `title` (AC-9). Confirm FAILING, then green.
- [ ] **[MODIFY] `src/lib/api/client.ts`** — `signup(email, password, name: string, title?:
  string): Promise<AuthResponse>`.
- [ ] **[MODIFY] `src/lib/api/realProvider.ts`** — `signup` POSTs `{email,password,name,title}`
  (`credentials:"include"` already present); `me()` unchanged.
- [ ] **[MODIFY] `src/lib/api/mockProvider.ts`** — `signup(email,password,name,title)` resolves
  `{user:{...authUserFixture,email,name: name ?? authUserFixture.name}}`; `me()` returns
  `authUserFixture`.
- [ ] **[MODIFY] `src/lib/api/fixtures.ts`** — `authUserFixture` gains `name: "Alex Morgan"`,
  `title: "Legal Counsel"`.
- [ ] **[MODIFY] `src/__tests__/_fakeClient.ts`** — `signup` records `(email,password,name,
  title)`; `me()` returns the configured authUser (default `authUserFixture`).

**Verify:** `vitest run src/__tests__/auth-fields.test.ts` + `tsc --noEmit` clean.

---

## Task 6: `useCurrentUser` hook (tests first)
- [ ] **[NEW] `src/__tests__/useCurrentUser.test.tsx`** — confirm FAILING (mock `getApiClient`):
  returns the real name when `me()` has one; **email-local-part fallback when name is null**
  (AC-8); returns no user / does not throw on `ApiError(401)`.
- [ ] **[NEW] `src/lib/useCurrentUser.ts`** — client hook (model on `useDashboard`): on mount
  call `getApiClient().me()`; expose `{ displayName, title, email, loading }` where
  `displayName = name?.trim() || emailLocalPart(email) || "there"`. Memoize the in-flight
  `me()` promise at module scope (single fetch shared by Sidebar+TopBar); export a
  `clearCurrentUser()` to invalidate on logout. On error → no user, no throw.

**Verify:** `vitest run src/__tests__/useCurrentUser.test.tsx` → PASS.

---

## Task 7: AuthView signup fields (tests first)
- [ ] **[MODIFY] `src/__tests__/authView.test.tsx`**:
  - Sign-Up tab renders **Full Name** (required) + **Job Title** (optional); Login tab does NOT.
  - AC-14 signup tests **fill the Full Name field** and assert `signup("new@b.com",
    "password123","<name>", "<title|undefined>")` → `/dashboard`. 401/409/422 mapping preserved.
- [ ] **[MODIFY] `src/components/auth/AuthView.tsx`** — when `tab === "signup"`, render Full Name
  (`id="name"`, required, label "Full Name") + Job Title (`id="title"`, optional); keep email +
  `PasswordInput`. Submit (signup) → `getApiClient().signup(email, password, name, title ||
  undefined)`. Error mapping unchanged. Preserve existing `getByLabelText(/email/i)` /
  `"Password"` hooks.

**Verify:** `vitest run src/__tests__/authView.test.tsx src/__tests__/auth-boundary.test.ts`
→ PASS.

---

## Task 8: Sidebar / TopBar / pages wiring (tests first)
- [ ] **[MODIFY] `src/__tests__/shell.test.tsx`** — the `user_profile_block` test now renders
  `<UserProfileBlock />` (no props) and **async** asserts the current user's real name from the
  hook (mock fixture "Alex Morgan") via `findByText`; assert "Sarah Jenkins"/"Legal Counsel" are
  gone. Ensure `getApiClient` is the mock provider (me() → authUserFixture).
- [ ] **[MODIFY] `src/components/shell/UserProfileBlock.tsx`** — consume `useCurrentUser()`
  (`displayName` + `title`); drop reliance on `name`/`role` props (keep them optional overrides
  if desired, default to the hook). On logout, call `clearCurrentUser()` before
  `router.replace("/login")`.
- [ ] **[MODIFY] `src/components/shell/Sidebar.tsx`** — render `<UserProfileBlock />` with no
  hardcoded name/role.
- [ ] **[MODIFY] `src/components/shell/TopBar.tsx`** — `"use client"`; avatar name from
  `useCurrentUser().displayName` (fallback "User Profile"); `userName` prop optional.
- [ ] **[MODIFY] `src/app/{dashboard,upload,reports,integrations,settings}/page.tsx`** — remove
  `userName="Sarah Jenkins"` from `<TopBar>`.
- [ ] **[MODIFY] `src/__tests__/primitives.test.tsx`** — keep the "no Sarah Jenkins" guard green;
  optionally extend its scanned file set to include `components/shell` now that it's clean (locks
  the fix). Do not scan files with legitimate occurrences.

**Verify:** `vitest run src/__tests__/shell.test.tsx src/__tests__/primitives.test.tsx` → PASS.

---

## Task 9: Full verification
- [ ] `pytest` (whole backend) GREEN.
- [ ] `vitest run` (whole frontend) GREEN; `tsc --noEmit` clean; `npm run lint` clean.
- [ ] Stop dev; `next build` succeeds.
- [ ] `git diff --name-only main` — no `backend/app/graph/` file changed; no new endpoint.

---

## Task 10: Live smoke (AC-10)
- [ ] `alembic upgrade head` (applies `0005`). Start `uvicorn`; set `frontend/.env.local`
  `NEXT_PUBLIC_API_PROVIDER=real`; `npm run dev`.
- [ ] Smoke: sign up with a **Full Name** (+ optional title) → the sidebar user block and the
  top-bar avatar show that name (not "Sarah Jenkins"). Upload a contract → the report email
  arrives at **that account's** email address (not the old hardcoded recipient). Log in as a
  second account → its own name shows.
- [ ] Reset `.env.local` to `mock`. Report the outcome.

---

## Task 11: Merge
- [ ] All suites + `tsc` + `build` green; smoke noted.
- [ ] Rebase `main`, merge `feature/020-user-profile`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/020-user-profile`, opened after spec +
plan + tasks are approved. Migration `0005` requires `alembic upgrade head` after pulling. No
new backend deps.*
