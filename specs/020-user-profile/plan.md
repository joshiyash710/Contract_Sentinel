# User Profile (Name/Title) + Report-to-Owner Email — Technical Plan

## Git Branch

`feature/020-user-profile` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

Implements `specs/020-user-profile/spec.md` (phase 1 of 3). Three small, cohesive changes:

1. **Identity on the account.** Alembic `0005` adds nullable `users.name` + `users.title`.
   Signup captures **name (required)** + **title (optional)**; `AuthUser` / `/api/auth/*` carry
   them; the session JWT stays minimal (`require_auth` reads them from the row).
2. **Real name in the UI.** A `useCurrentUser` hook (`getApiClient().me()`) feeds the sidebar
   user block + top-bar avatar, removing the hardcoded **"Sarah Jenkins" / "Legal Counsel"**.
   Legacy (null-name) accounts fall back to the email local part.
3. **Report to the owner.** `POST /api/analyze` defaults the delivery recipient to
   `current_user.email` (explicit `recipient` form field still overrides), so each user's
   report emails to their own inbox instead of the hardcoded `MCP_DELIVERY_RECIPIENT`.

No graph node/edge, no `ContractState` field, no constitution amendment. SSO stays deferred
(buttons disabled). Real OAuth is a later feature.

---

## 2. Files to Create / Modify

### Backend (`backend/`)
```
alembic/versions/0005_add_user_name_title.py  [NEW]    add nullable users.name, users.title (down_revision "0004")
app/runner/user_store.py                        [MODIFY] UserRow +name/title; create(email,pw,name,title); SELECT name/title in get_by_email/get_by_id
app/api/auth.py                                 [MODIFY] SignupRequest +name(req)/title(opt); AuthUser +name/title; signup passes them; login/me/require_auth surface them
app/api/routes.py                               [MODIFY] analyze: recipient = recipient or current_user.email

tests/unit/test_user_store.py                   [MODIFY] name/title round-trip via create/get
tests/integration/test_auth_endpoints.py        [MODIFY] _signup +name; assert name/title on signup/me; missing/blank name → 422
tests/integration/test_api_analyze.py           [MODIFY] recipient defaults to authed user's email (AC-4)
tests/integration/test_alembic_head.py          [MODIFY] users table now has name,title columns
tests/integration/conftest.py                   [MODIFY] authenticate()/authenticate_as() send a default name (required-field impact)
```

### Frontend (`frontend/`)
```
src/lib/api/types.ts                    [MODIFY] AuthUser +name?:string|null +title?:string|null
src/lib/api/client.ts                   [MODIFY] signup(email,password,name,title?) signature
src/lib/api/realProvider.ts             [MODIFY] signup body +name/title (credentials already set); me() unchanged (returns enriched AuthUser)
src/lib/api/mockProvider.ts             [MODIFY] signup(...args) + me() return a user with name/title
src/lib/api/fixtures.ts                 [MODIFY] authUserFixture +name/title
src/lib/useCurrentUser.ts               [NEW]  client hook: cached me() → {name(display),title,email}; no throw on 401
src/components/auth/AuthView.tsx        [MODIFY] Sign-Up tab: Full Name (required) + Job Title (optional); pass to signup()
src/components/shell/UserProfileBlock.tsx [MODIFY] consume useCurrentUser (name + title), drop the passed-in demo values
src/components/shell/Sidebar.tsx        [MODIFY] stop passing name="Sarah Jenkins" role="Legal Counsel"
src/components/shell/TopBar.tsx         [MODIFY] "use client"; avatar name from useCurrentUser (userName prop optional/removed)
src/app/{dashboard,upload,reports,integrations,settings}/page.tsx [MODIFY] drop userName="Sarah Jenkins"
src/__tests__/_fakeClient.ts            [MODIFY] signup accepts name/title; me() returns authUser
src/__tests__/auth-fields.test.ts       [MODIFY] AuthUser drift-lock incl. name/title
src/__tests__/authView.test.tsx         [MODIFY] signup asserts (email,password,name,title); Login tab has no name field
src/__tests__/useCurrentUser.test.tsx   [NEW]  real name vs email-fallback vs unauthenticated
src/__tests__/shell.test.tsx            [MODIFY] sidebar shows the current user's real name (mock), not "Sarah Jenkins"
src/__tests__/primitives.test.tsx       [MODIFY] the "no Sarah Jenkins" guard now also covers the cleaned shell files
```

No `backend/app/graph/` change; no new endpoint.

---

## 3. Backend design

### 3.1 Migration `0005_add_user_name_title.py`
`revision="0005"`, `down_revision="0004"`. Upgrade: `op.add_column("users", sa.Column("name",
sa.Text, nullable=True))` + `op.add_column("users", sa.Column("title", sa.Text,
nullable=True))`. Downgrade drops both (mirror 0002's plain `op.drop_column` style). Nullable ⇒
pre-020 rows load fine (D3). Runs via the existing startup Alembic chain (`alembic upgrade
head` after pulling).

### 3.2 `user_store.py`
- `UserRow` gains `name: Optional[str]` + `title: Optional[str]`.
- `create(email, password_hash, name, title)` — INSERT the two extra columns.
- `get_by_email` / `get_by_id` — SELECT + populate `name`/`title` (`row["name"]` etc.).
- All values bound via `?` params (no SQL string-building — AC-5).

### 3.3 `auth.py`
- `SignupRequest`: add `name: str` with a validator (trim; `1..100` chars, else `ValueError` →
  422) and `title: Optional[str] = None` (trim; `≤100`). Email/password validators unchanged.
- `AuthUser`: add `name: Optional[str] = None`, `title: Optional[str] = None`.
- `signup`: `row = user_store.create(body.email, pw_hash, body.name, body.title)`; build
  `AuthUser(id,email,name,title)` for both `make_session` (which still reads only id/email —
  JWT unchanged, D2) and the `AuthResponse`.
- `login` / `require_auth` / `me`: build `AuthUser` from the row **including** `row.name` /
  `row.title`, so every authenticated surface returns the profile. `LoginRequest` unchanged.

### 3.4 `routes.py` — recipient default
In `analyze` (already has `current_user: AuthUser = Depends(require_auth)` from 019), set
`recipient = recipient or current_user.email` before building the `JobRecord`
(`recipient=recipient`). The `JobRecord.recipient` → store → worker delivery path (011/012) is
otherwise untouched; the worker's `MCP_DELIVERY_RECIPIENT` fallback becomes vestigial for
authenticated uploads (D4). No delivery-mechanics change.

---

## 4. Frontend design

> **Client/server (§8).** `useCurrentUser`, `UserProfileBlock`, `AuthView` are client
> components. `TopBar` becomes `"use client"` to read the hook (pages that render it are server
> shells and can host a client child). The five app pages drop the hardcoded `userName`.

### 4.1 Seam (`types.ts`/`client.ts`/providers/fixtures/_fakeClient)
- `AuthUser`: `+ name?: string | null; title?: string | null`. `auth-fields.test.ts` locks it.
- `client.ts`: `signup(email, password, name: string, title?: string): Promise<AuthResponse>`.
- `realProvider.signup`: POST `/api/auth/signup` with `{email,password,name,title}`
  (`credentials:"include"` already there); `me()` unchanged (parses the now-enriched `AuthUser`).
- `mockProvider`: `signup(email,password,name,title)` resolves `{user: {...authUserFixture,
  email, name: name ?? authUserFixture.name}}`; `me()` returns `authUserFixture` (always-auth,
  D10 from 014). So mock dev/tests show a real person.
- `fixtures.authUserFixture`: add `name: "Alex Morgan"`, `title: "Legal Counsel"`.
- `_fakeClient`: `signup` records `(email,password,name,title)`; `me()` returns the configured
  authUser (default `authUserFixture`).

### 4.2 `useCurrentUser.ts` (new)
Client hook modelled on `useDashboard`/`useJobs`: on mount calls `getApiClient().me()`, stores
`{ email, name, title }`. **Display name** = `name?.trim() || emailLocalPart(email) ||
"there"` (D3). On `ApiError(401)`/any error → returns `{ user: null }` (never throws into the
tree; the middleware/gate handles the redirect). Memoize the in-flight promise at module scope
so Sidebar + TopBar share one `me()` call per load (avoid double fetch). Expose
`{ displayName, title, email, loading }`.

### 4.3 `AuthView.tsx` — signup fields
When `tab === "signup"`, render **Full Name** (`id="name"`, required) above email, and **Job
Title** (`id="title"`, optional) — both `TextInput`. Keep the login tab fields-only (email +
password). On submit for signup: `getApiClient().signup(email, password, name, title || undefined)`.
Error mapping unchanged (401/409/422); a 422 from a bad name shows the policy alert. The
existing `getByLabelText(/email/i)` / `"Password"` hooks are preserved; add `getByLabelText(/full
name/i)` for the new field.

### 4.4 Sidebar + TopBar wiring
- `UserProfileBlock`: read `useCurrentUser()`; render `displayName` and `title` (fallback to a
  neutral role label or nothing when title is null). Remove the `name`/`role` props usage (or
  keep props as optional overrides but default to the hook). The existing logout control (015)
  is untouched.
- `Sidebar`: render `<UserProfileBlock />` with no hardcoded name/role.
- `TopBar`: `"use client"`; avatar `name` from `useCurrentUser().displayName` (fallback "User
  Profile"); remove the `userName="Sarah Jenkins"` call sites on the five pages.

---

## 5. Tests mapped to acceptance criteria

**Backend (pytest).**
- `test_user_store.py`: `create(...,name,title)` → `get_by_id/email` returns them; a row created
  with `title=None` reads back None (AC-1/legacy substrate).
- `test_auth_endpoints.py`: signup with name+title → stored + echoed in `AuthUser`, `/me`
  returns them (AC-1); **missing/blank name → 422**, title omitted OK (AC-2); a directly-seeded
  `name=NULL` user → `/me` 200 with `name: null` (AC-3); no password/secret/name logged (AC-5,
  extends 014 AC-7a). **`_signup` helper + every inline signup POST gains a `name`.**
- `test_api_analyze.py`: after analyze as U (no recipient), stored `JobRow.recipient == U.email`
  (AC-4); with an explicit `recipient` form field, that value wins.
- `test_alembic_head.py`: `users` columns now include `name`,`title`.
- `conftest.py`: `authenticate` / `authenticate_as` send a default `name` (see §7).

**Frontend (Vitest + RTL, mock provider).**
- `auth-fields.test.ts`: `AuthUser` has `name`/`title` (drift-lock, AC-9).
- `authView.test.tsx`: Sign-Up tab renders Full Name (required) + Job Title; submit calls
  `signup("new@b.com","password123","<name>","<title>")` → `/dashboard` (AC-6); Login tab has no
  name field; 401/409/422 mapping preserved.
- `useCurrentUser.test.tsx` (new): real name when `me()` returns one; **email-local-part fallback
  when name is null** (AC-8); no user / no throw on 401.
- `shell.test.tsx`: the sidebar user block shows the mock user's real name (AC-7); assert
  "Sarah Jenkins"/"Legal Counsel" are gone.
- `primitives.test.tsx`: the "no Sarah Jenkins" guard now passes over the cleaned shell files.

**Live smoke (AC-10):** `provider=real`; sign up with a name → sidebar/top-bar show it; upload →
report email arrives at that account's address.

---

## 6. Implementation order (TDD — §7)

1. **Migration `0005`** + update `test_alembic_head.py`.
2. **Store (red→green):** `test_user_store.py` name/title round-trip; then `UserRow` +
   `create`/`get_*`.
3. **Auth endpoints:** `test_auth_endpoints.py` (name stored/echoed, 422 on blank, `/me`);
   then `SignupRequest`/`AuthUser`/`signup`/`login`/`require_auth`/`me`. **Fix the signup call
   sites** (`_signup`, conftest `authenticate`/`authenticate_as`) so the whole backend suite is
   green.
4. **Recipient default:** `test_api_analyze.py` (recipient == user email / explicit wins); then
   the one-line `analyze` change. Run the **whole backend suite** green.
5. **Frontend seam:** `types` + `client` + providers + `fixtures` + `_fakeClient` +
   `auth-fields` drift test.
6. **useCurrentUser** (+ test) → **AuthView** signup fields (+ test) → **Sidebar/UserProfileBlock/
   TopBar** + pages (+ shell/primitives tests).
7. **Verify:** `pytest` (whole), `vitest run` (whole), `tsc --noEmit`, `npm run lint`,
   `next build` (dev STOPPED). No `backend/app/graph/` change.
8. **Live smoke** (AC-10). Reset `.env.local` to `mock`.

Each step's tests are written failing first (§7). Step 3's signup-call-site edits are the
sanctioned test modification (the signup contract legitimately gained a required field).

---

## 7. Notes / risks

- **Required `name` breaks API-signup call sites (the main gotcha).** `authenticate` /
  `authenticate_as` (conftest) and `_signup` + inline signup POSTs (`test_auth_endpoints.py`)
  POST `{email,password}` only → they'd 422. Add a default `name` (e.g. `"Test User"`) to each.
  **`seed_owner_user` is NOT affected** — it inserts users via direct SQL and `name`/`title` are
  nullable, so its INSERT (id,email,password_hash,created_at) still works (name defaults NULL).
- **Recipient default changes an existing assumption.** Any test expecting an empty/None
  recipient without an explicit one must now expect the authed user's email (or pass an explicit
  `recipient`). Grep the delivery/analyze tests.
- **`me()` fan-out.** Memoize the in-flight `me()` promise at module scope so Sidebar + TopBar
  don't double-fetch on every navigation; invalidate on logout (clear the cache) so a re-login
  as a different user shows the new name.
- **TopBar → client.** Making `TopBar` a client component is required to read the hook; verify
  the five pages still compile (server shells rendering a client child is fine).
- **JWT unchanged** keeps the token minimal and avoids a name/PII-in-token security note; name is
  always fresh from the DB (D2).
- **`next build` vs `next dev`** — never build while dev runs; step 7 builds with dev stopped.
- **Scope discipline** — no profile *editing*, no company field, no SSO here (all deferred).

---

*Per §1/§11, a `feature/020-user-profile` branch opens only after this plan.md + spec.md are
approved and `tasks.md` exists. Migration `0005` requires `alembic upgrade head` after pulling.
No new backend deps. No `tasks.md`/implementation written in this pass — plan only.*
