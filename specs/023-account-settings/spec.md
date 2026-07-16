# Feature 023 — Account Settings (editable profile + change password)

## 1. Problem statement

The **Settings** page (`/settings`) is still a placeholder stub ("built on this foundation in spec
018" — never actually built). The design ref screen (3) **"User Profile & Settings"** shows an
account screen with an avatar column and tabbed sections. Users need a real settings page where they
can **edit their profile** (the name/title added in 020) and **change their password** (the
bcrypt-hashed credential from 014/019). This is **phase 1** of the post-022 set (**023 account
settings** → 024 integrations).

### Position relative to the constitution

**No amendment. No graph/`ContractState` change. No migration.** This touches only the **auth/user**
surface, which is already IN scope (014 single-user login, amended 019 per-user isolation). It adds
two authenticated endpoints and two `UserStore` methods; the `users` table already has every column
needed (`name`, `title` from Alembic 0005; `password_hash` from 0003). Per constitution §4, all new
request/response bodies are **Pydantic** boundary models; the LangGraph state is untouched (settings
has nothing to do with the 7-node pipeline). Per §11 it is developed on
`feature/023-account-settings`.

**Cuts forced by the constitution / product reality** (the mockup shows more than we build): the
**Billing** and **Team** tabs and **Team-Management** toggles are **cut** — there is no payment
system anywhere in the project, and teams/RBAC/multi-tenant admin are **PERMANENTLY CUT** (§2). The
**Integrations** tab is **not** on this page — the user chose two separate pages, so Integrations is
its own route in **024** (D1). Google/Microsoft **SSO** stays deferred (014 D6).

## 2. Inputs and outputs

### 2.1 Backend — two new authenticated endpoints (on the existing `auth_router`)

Both require a valid session (`require_auth`) and act only on **`current_user`** (per-user scoping,
019 — a user can only change *their own* profile/password; no `user_id` on the wire).

**`PATCH /api/auth/me`** — update the caller's profile.
- Request `UpdateProfileRequest { name: str, title: Optional[str] }` — same validation as signup
  (`name` 1–100 chars required; `title` ≤100 chars, blank→null). Reuse the existing validators.
- Effect: `UserStore.update_profile(user_id, name, title)` updates `users.name` / `users.title`.
- Response `AuthResponse { user: AuthUser }` — the refreshed user (same shape `GET /me` returns).

**`POST /api/auth/me/password`** — change the caller's password.
- Request `ChangePasswordRequest { current_password: str, new_password: str }`. `new_password`
  validated with the existing `AUTH_PASSWORD_MIN/MAX` bounds.
- Effect: load the caller's `UserRow`; `verify_password(current_password, row.password_hash)` — on
  mismatch return **400** (`{ detail: "Current password is incorrect" }`) and change nothing. On
  match: `UserStore.update_password(user_id, hash_password(new_password))`.
- Response: **200** `{ ok: true }`. The session cookie stays valid (no forced re-login — D3).

New `UserStore` methods (no schema change): `update_profile(user_id, name, title) -> UserRow` and
`update_password(user_id, new_hash) -> None`. Reuse `hash_password` / `verify_password` from
`app/api/security.py` — no new crypto (D5).

### 2.2 Frontend — the `/settings` page

Replaces the stub with a real account page whose **visual layout follows design ref (3)
"User Profile & Settings"** (`…31 PM (3).jpeg`) — see D8:
- **Page title** "User Profile & Settings" (via `TopBar`), then a **two-column** body: a tall
  **avatar column card** on the left and a **tabbed content card** on the right, exactly as in the
  ref.
- **Avatar column card** (left, from the mockup): a large circular avatar (initials block — no photo
  upload, D4) with the user's **name** and **title** beneath it (from `useCurrentUser`, 020).
- **Tab bar** (right, styled like the ref): a horizontal row of tabs with the **active tab
  underlined in the accent color**. Per D1/the tab decision the tabs are **Profile** and **Security**
  only (the ref's Billing/Team are §2-cut; Integrations is its own page — feature 024).
- **Profile tab:** a **card section** with **Full Name** (editable), **Job Title** (editable), and
  **Email** (read-only — D2). **Save** → `updateProfile()` → on success refresh `useCurrentUser` so
  the shell (Sidebar/TopBar name/title from 020) updates immediately; success + error states.
- **Security tab:** a **card section** with a **Change Password** form — **Current password**,
  **New password**, **Confirm new password** (confirm checked client-side only). **Update password**
  → `changePassword()`; wrong-current → inline error; success → confirmation, fields cleared.

Provider **seam**: add `updateProfile(body)` and `changePassword(body)` to the `ApiClient` interface,
implemented in both the **mock** and **real** providers (mock returns an updated `authUserFixture` /
resolves ok, and can be scripted to reject for error-state tests). Pages reach the backend **only**
via `getApiClient()` (D6).

## 3. Resolved decisions (inline)

- **D1 — `/settings` = Profile + Security only; two separate pages.** Per the user's choice,
  Integrations is **not** a tab here — it is its own `/integrations` route (feature 024). Billing +
  Team tabs from the mockup are dropped (no backend / §2 cut). Both sidebar nav items remain.
- **D2 — Editable name/title; email read-only.** Email is the login identity and is `UNIQUE`;
  changing it implies a uniqueness check + re-auth flow that is out of scope. The email field renders
  disabled with a hint.
- **D3 — Change-password verifies the current password; session stays valid after change.** The app
  uses a stateless signed-cookie session (no server session store to revoke), and it is a
  single-owner tool, so we do **not** force re-login or invalidate the cookie on change. (Reversible
  later if desired.) New password reuses `AUTH_PASSWORD_MIN/MAX`.
- **D4 — No avatar upload, no Billing, no Team, no email change, no SSO.** The avatar is initials/a
  static block. Billing/Team are cut (§2 / no backend). SSO stays deferred (014 D6).
- **D5 — Reuse existing validation + crypto.** The signup `name`/`title` validators and
  `hash_password`/`verify_password` are reused; no new validation rules or crypto are introduced.
- **D6 — Seam preserved.** The page imports no provider directly; it calls `getApiClient()`. The two
  new client methods exist in the interface + mock + real providers so the page renders in mock
  dev/tests.
- **D7 — No migration.** `name`/`title`/`password_hash` columns already exist (Alembic 0005 / 0003).
  This feature adds no Alembic revision.
- **D8 — Visual grounded in design ref (3) "User Profile & Settings."** The page reproduces the
  ref's layout: the "User Profile & Settings" title, a left **avatar column card** (avatar +
  name + title), and a right **tabbed content card** with an **accent-underlined active tab** and
  **card-based** sections. The tab bar is trimmed to the two tabs that map to real functionality —
  **Profile** and **Security** — because the ref's **Billing** and **Team** are PERMANENTLY CUT
  (§2) and **Integrations** is its own page (feature 024, per the two-separate-pages choice). No
  disabled "coming soon" tabs are shown (chosen over reproducing dead tabs).

## 4. Acceptance criteria

### Backend (pytest)
- **AC-1:** `PATCH /api/auth/me` with a valid session and `{name, title}` updates the row and returns
  `AuthResponse` with the new `name`/`title`; a subsequent `GET /api/auth/me` reflects them.
- **AC-2:** `PATCH /api/auth/me` with a blank/oversized `name` (or >100-char `title`) returns a
  validation error (422) and changes nothing.
- **AC-3:** `PATCH /api/auth/me` **without** a session returns **401** (require_auth).
- **AC-4:** `POST /api/auth/me/password` with the **correct** current password + a valid new password
  returns **200 `{ok:true}`**; afterward `login` succeeds with the **new** password and fails with
  the **old** one.
- **AC-5:** `POST /api/auth/me/password` with an **incorrect** current password returns **400**
  (`"Current password is incorrect"`) and does **not** change the stored hash.
- **AC-6:** `POST /api/auth/me/password` with a **too-short/too-long** new password returns a
  validation error and changes nothing; **without** a session returns **401**.
- **AC-7:** A user can only affect their **own** account — the endpoints derive the target from
  `current_user` (no `user_id`/email accepted from the body to target another account); 019 isolation
  holds.
- **AC-8:** `UserStore.update_profile` / `update_password` persist across a store re-open (durable
  SQLite write), and leave other columns (email, created_at, id) unchanged.

### Frontend (Vitest + RTL, mock/fake provider)
- **AC-9:** `/settings` renders the **Profile** and **Security** tabs; Profile shows the current
  name/title/email from the client's `me()` (via `useCurrentUser`), with email **read-only/disabled**.
- **AC-10:** Editing name/title and clicking **Save** calls `updateProfile()` with the new values and
  shows a success state; a rejected call shows an error state (no crash).
- **AC-11:** On a successful profile save, `useCurrentUser` is refreshed so the displayed name/title
  update without a full reload.
- **AC-12:** The **Security** tab's Change-Password form calls `changePassword()` with
  current/new; **confirm≠new** is blocked client-side with an inline message and **no** call is made;
  a backend "incorrect current password" rejection shows an inline error; success clears the fields
  and shows a confirmation.
- **AC-13:** **Seam/boundary:** no `components/settings/**` (or the settings page) imports a provider
  module directly — only `getApiClient()` / hooks.

### Live (real backend)
- **AC-14 (smoke, manual):** With `provider=real`, log in → open Settings → edit name/title → Save →
  the sidebar/topbar name updates and `GET /me` returns the new values; change the password with the
  correct current one → log out → log back in with the **new** password (old one rejected); a wrong
  current password shows the inline error.

## 5. Edge cases
- **EC-1 — Wrong current password** → 400 inline error, nothing changes (AC-5).
- **EC-2 — New password fails length bounds** → validation error surfaced on the field (AC-6).
- **EC-3 — New password equals current** → allowed (not worth blocking); succeeds normally.
- **EC-4 — Unauthenticated / expired session** on either endpoint → 401; the page surfaces it (e.g.
  redirect to login via the existing 401 handling) rather than crashing.
- **EC-5 — Profile save with unchanged values** → idempotent 200; success state still shown.
- **EC-6 — Blank title** → stored as `null` (reuse signup normalization), rendered as empty.
- **EC-7 — Very long name/title** → rejected by validation before write (AC-2).
- **EC-8 — `useCurrentUser` 401/no-throw** (020 behavior) is preserved — Settings degrades to
  empty/login rather than throwing.

## 6. Out of scope
- **Integrations** page — feature **024** (Drive+Gmail, frontend-only).
- **Billing / payments** and **Team / RBAC / sharing** — cut (§2 / no backend).
- **Email change**, **avatar upload**, **account deletion**, **2FA**, and **session
  invalidation/other-device logout on password change** — none built (D2/D3/D4).
- **Google/Microsoft SSO** — deferred (014 D6).
- **Any LangGraph node/edge, `ContractState`, or Alembic migration** — none.

## 7. Notes for plan.md / tasks.md (pointers)
- **Backend:** add `UserStore.update_profile` / `update_password` (app/runner/user_store.py); add
  `UpdateProfileRequest` / `ChangePasswordRequest` models + `PATCH /api/auth/me` and
  `POST /api/auth/me/password` handlers (app/api/auth.py, on `auth_router`, each `Depends(require_auth)`);
  reuse the signup validators + `hash_password`/`verify_password`. New pytest covering AC-1..8
  (happy, wrong-current, validation, unauth, isolation, durability).
- **Frontend:** `src/app/settings/page.tsx` (replace stub → `<TopBar/>` + settings view);
  `src/components/settings/*` (tabbed Profile + Security forms + avatar column); extend the
  `ApiClient` interface + mock + real providers with `updateProfile` / `changePassword`; a hook (or
  reuse `useCurrentUser`) to save + refresh. Vitest for AC-9..13 + a settings-boundary grep. TDD (§7)
  — failing tests first; 020 shell name/title wiring preserved.
- **Password change is security-sensitive** — write the wrong-current-password, weak-password, and
  unauth tests first and confirm they fail before implementing.
