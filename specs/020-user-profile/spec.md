# Feature 020 — User Profile (Name/Title) + Report-to-Owner Email

## 1. Problem statement

After 019 shipped per-user workspaces, three gaps remain in how the app treats the
logged-in person:

1. **Signup collects no identity.** The form asks only email + password, so the app has no
   real name to show. Real professional SaaS signups capture at least a **full name** (often a
   job title / company too).
2. **The UI shows a hardcoded person.** The sidebar and every page's top bar render
   **"Sarah Jenkins" / "Legal Counsel"** (013 demo chrome). A logged-in user should see
   **their own** name and title.
3. **Report emails go to one hardcoded inbox.** The Gmail delivery recipient is a single
   fixed address (`MCP_DELIVERY_RECIPIENT`, currently the owner's email via env). With
   per-user isolation, each user's report should be emailed to **that user's own** address.

This feature is **phase 1** of a three-phase set (020 profile/email → 021 report history →
022 report redesign). Google/Microsoft SSO is **deferred** to a later feature (it needs a
provisioned OAuth app); the buttons stay disabled (014 D6).

### Position relative to the constitution

**No amendment needed.** This adds no LangGraph node/edge and no `ContractState` field
(§2/§4) — it extends the `users` table + auth boundary models and changes a delivery-recipient
default. It stays within the existing single-account-auth + per-user-isolation scope (014/019
amendments). Per §11 it is developed on `feature/020-user-profile`.

## 2. Inputs and outputs

### 2.1 Data model change
- **Alembic migration `0005`** (`down_revision = "0004"`), in `data/job_store.db`: add two
  **nullable TEXT** columns to `users`: `name` and `title`. Nullable so pre-020 accounts
  (created in 014/019) load with `name=NULL` — the UI falls back gracefully (D3). `UserRow`
  and `UserStore.create/get_by_email/get_by_id` carry `name`/`title`.

### 2.2 Auth boundary (Pydantic ↔ types.ts, §4)
- `SignupRequest` gains **`name`** (required) and **`title`** (optional). `AuthUser` gains
  **`name: Optional[str]`** and **`title: Optional[str]`**. `/api/auth/signup`, `/login`, and
  `/me` all return the enriched `AuthUser`. Mirrored in `frontend/src/lib/api/types.ts`
  (drift-lock test). **No new endpoint.**
- The session **JWT is unchanged** (`{sub, email, exp}`) — `require_auth` already loads the
  user row, so `name`/`title` are read from the store per request (no extra PII in the token,
  security-review-friendly — D2).

### 2.3 Report-to-owner email
- `POST /api/analyze` sets the job's delivery **recipient = the explicit request `recipient`
  if provided, else `current_user.email`** (D4). So a user's report is emailed to their own
  address by default; the hardcoded `MCP_DELIVERY_RECIPIENT` env default is no longer relied
  on for normal use (it remains only a last-resort fallback if a recipient is somehow empty —
  which can't happen for an authenticated user, since email is required).

### 2.4 Outputs (what changes visibly)
- **Signup form** (`/login` → Sign Up tab): adds **Full Name** (required) and **Job Title**
  (optional) fields above/below email+password. Login tab is unchanged (email + password).
- **Sidebar user block + top-bar avatar**: show the **real** logged-in name (and title where
  shown), replacing "Sarah Jenkins" / "Legal Counsel". Sourced from `/api/auth/me` via a
  `useCurrentUser` hook (D5). The mock provider returns a fixture user with a name/title so
  mock-mode dev and tests still render a person.
- **Report email**: lands in the logged-in user's inbox.

## 3. Resolved decisions (inline)

- **D1 — Fields & validation.** `name` **required**, trimmed, **1–100 chars** (empty/whitespace
  → `422`). `title` **optional**, ≤100 chars. Email/password validation unchanged (014). Names
  are display-only text (never used in SQL string-building — parameterized), so no injection
  surface.
- **D2 — Name/title live in the DB, not the JWT.** `require_auth` returns an `AuthUser` built
  from the user row, so name/title are always current and the token stays minimal
  (`{sub,email,exp}`). Changing a name later (future feature) needs no re-issue.
- **D3 — Legacy accounts (NULL name).** Pre-020 users have `name=NULL`. The UI falls back to a
  friendly derivation (the email's local part, e.g. `smoke@…` → "smoke") so nothing shows
  "null"/blank. No forced backfill or migration of existing rows.
- **D4 — Recipient default = owner email, still overridable.** `analyze` uses
  `recipient or current_user.email`. The optional `recipient` form field (011) still wins if a
  client sends one, preserving "send to a colleague" without new UI. Delivery mechanics
  (Drive+Gmail, feature 010) are otherwise untouched.
- **D5 — One `useCurrentUser` hook is the single source.** A client hook calls
  `getApiClient().me()` (cached), returning `{name,title,email}` (with the D3 fallback for
  name). The Sidebar `UserProfileBlock` and the `TopBar` avatar consume it; the five app pages
  stop passing `userName="Sarah Jenkins"`. On a `401` the hook yields no user (the gate/redirect
  already handles auth elsewhere — this hook never throws into the tree).
- **D6 — Login unchanged.** Only the Sign-Up tab gains fields; `login(email,password)` and its
  error mapping are untouched (014 AC-13). `signup` gains name/title args on the `ApiClient`
  seam + both providers.
- **D7 — SSO still deferred.** Google/Microsoft buttons remain disabled (014 D6); real OAuth is
  a separate future feature (needs a provisioned app). Not in scope here.

## 4. Acceptance criteria

Backend → pytest (TestClient). Frontend → Vitest + RTL (mock provider unless noted).

**Backend**
- **AC-1:** `POST /api/auth/signup {email,password,name,title}` stores `name`/`title` on the
  `users` row and returns them in the `AuthUser`; `/api/auth/me` returns them too.
- **AC-2:** Signup with a missing/blank `name` → `422` (name required, D1); `title` omitted is
  accepted (stored NULL).
- **AC-3:** A legacy user row with `name=NULL` (seeded directly) is returned by `/me` without
  error (`name` is null on the wire; the frontend applies the fallback).
- **AC-4:** After `POST /api/analyze` as user U (no explicit `recipient`), the job's stored
  `recipient == U.email` (D4). If an explicit `recipient` form field is sent, that value wins.
- **AC-5:** `name`/`title` are never used in raw SQL (parameterized) and never logged in
  plaintext with the password/secret (extends 014 AC-7a).

**Frontend**
- **AC-6:** The Sign-Up tab renders **Full Name** (required) + **Job Title** (optional) inputs;
  submitting calls `apiClient.signup(email, password, name, title)` and on success →
  `/dashboard`. Login tab has no name/title fields.
- **AC-7:** With a mock/fake current user, the sidebar user block and the top-bar avatar show
  the **real** name (and title in the sidebar) — no "Sarah Jenkins"/"Legal Counsel" string
  remains in the rendered app shell.
- **AC-8:** `useCurrentUser` derives a non-empty display name from the email when `name` is
  null (D3), and renders nothing user-identifying (no throw) when unauthenticated.
- **AC-9:** `AuthUser`/`AuthResponse` TS types mirror the Pydantic models incl. `name`/`title`
  (drift-lock). No page imports a provider directly (seam preserved).

**Live (real backend)**
- **AC-10 (smoke, manual):** Sign up with a name → the sidebar/top-bar show that name; upload a
  contract → the report email arrives at **that account's** email (not the old hardcoded one).

## 5. Edge cases
- **EC-1 — Whitespace-only name** → trimmed → empty → `422` (D1).
- **EC-2 — Very long name/title** (>100) → `422`.
- **EC-3 — Legacy NULL name** → email-local-part fallback in UI (D3); never renders "null".
- **EC-4 — Explicit recipient still honored** → `analyze` `recipient` form field overrides the
  owner-email default (D4), so "email this to my colleague" keeps working.
- **EC-5 — `me()` 401 mid-session** → `useCurrentUser` returns no user; the existing gate
  redirects to `/login` (014) — the hook doesn't crash the shell.
- **EC-6 — Gmail delivery disabled / no OAuth token** → unchanged 010 behavior (Gmail records
  FAILED, Drive proceeds); this feature only changes *which address* is targeted.

## 6. Out of scope
- **Google/Microsoft SSO / real OAuth** — deferred to a later feature (buttons stay disabled).
- **Profile editing** (change name/title/email/password after signup), avatars/photo upload,
  company/org fields beyond name+title — not built here (name+title only).
- **Report history page** — feature 021. **Report page redesign** — feature 022.
- **Any graph/node/state change** — none.

## 7. Notes for plan.md / tasks.md (pointers, not decisions)
- Migration `0005` adds `users.name`, `users.title` (nullable). Pull requires
  `alembic upgrade head`.
- Backend touch: `user_store.py` (UserRow + 3 methods + create signature), `auth.py`
  (SignupRequest/AuthUser + signup/login/me), `routes.py` (analyze recipient default),
  `0005` migration. Update `test_user_store.py`, `test_auth_endpoints.py`, `test_api_analyze.py`.
- Frontend touch: `types.ts` (AuthUser+name/title), `client.ts`/providers (`signup` gains
  name/title; `me` returns them), `fixtures.ts` (authUserFixture name/title), `_fakeClient.ts`,
  new `useCurrentUser.ts`, `AuthView.tsx` (signup fields), `UserProfileBlock.tsx` + `TopBar.tsx`
  (consume the hook), the five pages (drop the hardcoded `userName`). Update `authView.test.tsx`,
  `auth-fields.test.ts`, and the `primitives.test.tsx` guard that asserts no "Sarah Jenkins".
- TDD (§7): failing tests first; 014 auth behavior preserved.
- **KEY TEST-IMPACT — required `name` breaks every signup call site.** Because `name` becomes
  required (422 without it), the integration helpers that sign up must send one: the
  `authenticate(client)` and `authenticate_as(client,email,pw)` helpers in
  `tests/integration/conftest.py`, `seed_owner_user` (inserts users directly — add name column
  value), and the `_signup` helper + inline signup POSTs in `test_auth_endpoints.py`. This is
  the 020 analogue of 019's "stamp the seeded rows" migration — enumerate every signup POST in
  the suite and add a default `name` so the whole backend suite stays green. (Behavior
  preserved; the calls just include a name now.)
- **Recipient-default test-impact.** `analyze` now sets `recipient=current_user.email` by
  default — any existing test asserting a job's recipient is `None`/empty without an explicit
  recipient must expect the authed user's email instead (or pass an explicit `recipient`).
