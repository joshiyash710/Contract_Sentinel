# Account Settings (editable profile + change password) — Technical Plan

## Git Branch

`feature/023-account-settings` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

Implements `specs/023-account-settings/spec.md` (phase 1 of 2) — a **backend + frontend** feature.
Turns the `/settings` stub into a real account page with a **Profile** tab (edit name/title) and a
**Security** tab (change password), backed by two new authenticated endpoints on the existing
`auth_router`. **No LangGraph/`ContractState` change, no Alembic migration** — the `users` table
already has `name`/`title` (0005) and `password_hash` (0003). Reuses the existing signup validators
and `hash_password`/`verify_password` (no new crypto). Everything is scoped to `current_user` via
`require_auth` (019 isolation). Integrations is a separate page (feature 024), not built here.

---

## 2. Files to Create / Modify

### Backend (`backend/`)
```
app/runner/user_store.py     [MODIFY] add update_profile(user_id,name,title)->UserRow and update_password(user_id,new_hash)->None (mirror create(): with self._lock + commit)
app/api/auth.py              [MODIFY] add UpdateProfileRequest, ChangePasswordRequest models; PATCH /api/auth/me and POST /api/auth/me/password handlers (each Depends(require_auth))
tests/integration/test_settings_endpoints.py [NEW] AC-1..7 (patch profile, change password, wrong-current, validation, unauth, isolation)
tests/unit/test_user_store_update.py          [NEW] AC-8 (update_profile/update_password persist + reopen; other columns unchanged)
```
No migration; no `app/graph/**` change.

### Frontend (`frontend/`)
```
src/lib/api/client.ts            [MODIFY] extend ApiClient interface: updateProfile(body)->AuthUser, changePassword(body)->void
src/lib/api/realProvider.ts      [MODIFY] PATCH /api/auth/me (unwrap .user) + POST /api/auth/me/password (credentials:"include")
src/lib/api/mockProvider.ts      [MODIFY] updateProfile → merged authUserFixture; changePassword → resolve
src/__tests__/_fakeClient.ts     [MODIFY] add updateProfile/changePassword to makeFakeClient + opts (updateProfileError, changePasswordError)
src/lib/useCurrentUser.ts        [MODIFY] add refreshCurrentUser() + a subscriber registry so mounted Sidebar/TopBar update live (AC-11); backward-compatible
src/app/settings/page.tsx        [MODIFY] replace stub → <TopBar title="User Profile & Settings"/> + <AccountSettingsView/> (D8)
src/components/settings/AccountSettingsView.tsx [NEW] avatar column + Profile/Security tab switch
src/components/settings/ProfileForm.tsx         [NEW] name/title editable, email disabled, Save → updateProfile → refreshCurrentUser
src/components/settings/SecurityForm.tsx        [NEW] current/new/confirm-new, Update → changePassword
src/__tests__/settings.test.tsx                 [NEW] AC-9..12
src/__tests__/settings-boundary.test.ts         [NEW] AC-13 (no provider import under components/settings)
```
No `types.ts` change required (bodies are inline object types; `AuthUser`/`AuthResponse` already
exist). No new endpoint beyond the two above.

---

## 3. Backend design

### 3.1 `UserStore` (mirror the existing `create()` pattern)
```python
def update_profile(self, user_id: str, name: str, title: Optional[str]) -> UserRow:
    with self._lock:
        self._conn.execute(
            "UPDATE users SET name = ?, title = ? WHERE id = ?", (name, title, user_id)
        )
        self._conn.commit()
    return self.get_by_id(user_id)  # fresh row; None only if the user vanished (require_auth precludes)

def update_password(self, user_id: str, new_hash: str) -> None:
    with self._lock:
        self._conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id)
        )
        self._conn.commit()
```
Same `self._lock` + `commit()` discipline as `create()`; no other columns touched (AC-8).

### 3.2 Models + endpoints (`app/api/auth.py`, on `auth_router`)
- `UpdateProfileRequest { name: str; title: Optional[str] = None }` — **reuse the exact signup
  `name`/`title` `field_validator` logic** (1–100 required; ≤100, blank→None). To avoid drift,
  factor the validators into module-level helper functions used by both `SignupRequest` and
  `UpdateProfileRequest` (small refactor, no behavior change — confirm signup tests still green).
- `ChangePasswordRequest { current_password: str; new_password: str }` — `new_password` uses the same
  `AUTH_PASSWORD_MIN/MAX` validator as signup.
- `PATCH /api/auth/me` (`current_user = Depends(require_auth)`):
  `user_store.update_profile(current_user.id, body.name, body.title)` → `AuthResponse(user=AuthUser(...))`.
- `POST /api/auth/me/password` (`Depends(require_auth)`): load `row = user_store.get_by_id(current_user.id)`;
  if `not verify_password(body.current_password, row.password_hash)` → `raise HTTPException(400,
  "Current password is incorrect")` (AC-5, no write); else
  `user_store.update_password(current_user.id, hash_password(body.new_password))` → `{"ok": True}`.
  The session cookie is left intact (D3).
- `user_store` is read from `request.app.state.user_store` exactly as `require_auth` /signup do.

### 3.3 Isolation (AC-7)
Neither endpoint accepts a `user_id`/email in the body; the target is always `current_user.id` from
the verified session — a caller cannot address another account. No `user_id` on the wire (019).

---

## 4. Frontend design

> **Client/server (§8).** `AccountSettingsView`/forms are client components (`useState`,
> `useCurrentUser`). `app/settings/page.tsx` stays a thin server shell rendering `<TopBar/>` + the
> view (mirrors `dashboard`/`contracts`).

### 4.1 Seam methods
- `client.ts` interface: `updateProfile(body: { name: string; title?: string | null }):
  Promise<AuthUser>;` and `changePassword(body: { current_password: string; new_password: string }):
  Promise<void>;`.
- `realProvider`: `PATCH ${base()}/api/auth/me` (JSON body, `credentials:"include"`) → return
  `body.user`; `POST ${base()}/api/auth/me/password` → resolve on ok, throw `ApiError` on non-ok
  (surfacing the 400 message for the inline error). Mirrors the existing `signup`/`me` methods.
- `mockProvider`: `updateProfile` → `{ ...authUserFixture, ...body }`; `changePassword` → resolve.
- `_fakeClient.ts`: `updateProfile: vi.fn(async (b) => opts.updatedUser ?? { ...authUserFixture,
  ...b })`, rejecting `opts.updateProfileError` if set; `changePassword: vi.fn(async () => { if
  (opts.changePasswordError) throw opts.changePasswordError; })`.

### 4.2 `useCurrentUser` live refresh (AC-11)
Add a module-level subscriber `Set<() => void>` and:
```ts
export async function refreshCurrentUser(): Promise<void> {
  _cached = null;                 // drop the cached me() promise
  await fetchCurrentUser();       // re-fetch once
  subscribers.forEach((fn) => fn());
}
```
`useCurrentUser` registers a bump-callback on mount (increment a local counter to re-read
`fetchCurrentUser()`), unregisters on unmount. Existing consumers (Sidebar/TopBar, 020) gain live
updates with **no API change** to the hook's return shape.

### 4.3 `AccountSettingsView.tsx` (layout grounded in design ref (3) — D8)
Two-column body (mirrors the ref): `grid gap-6 lg:grid-cols-[minmax(0,20rem)_1fr]`, single column
below `lg`.
- **Left — avatar column card:** a `Card` with a large circular **initials** avatar (from
  `displayNameFor(user)`; no photo upload — D4), the user's **name**, and **title** beneath. Reuses
  the app's `Card` primitive + accent styling.
- **Right — tabbed content card:** reuse the existing **`Tabs` primitive with `variant="underline"`**
  (already built "for Profile/Billing… screen 4", emits `role="tab"`/`aria-selected`) — items
  `[{value:"profile",label:"Profile"},{value:"security",label:"Security"}]`; local
  `tab` state (default `profile`) toggles between `<ProfileForm/>` and `<SecurityForm/>`, each in a
  **card section**. (Billing/Team omitted — §2 cut; Integrations is feature 024 — D1/D8.)
- **Reuse primitives, don't hand-roll:** `Avatar` (`size="lg"`, initials), `Tabs` (underline),
  `TextInput` (name/title/email), `PasswordInput` (current/new/confirm), `Button`, `Card` — all
  already in `src/components/ui/`.
- The page title "User Profile & Settings" comes from `<TopBar title="User Profile & Settings" />`
  in `app/settings/page.tsx` (matches the ref header).

### 4.4 `ProfileForm.tsx`
- Controlled `name`/`title` seeded from `useCurrentUser`; **Email** input `disabled` with a hint
  (D2). **Save** → `getApiClient().updateProfile({ name, title })`; on success →
  `await refreshCurrentUser()` + success message; on reject → error message (AC-10/11). Disable Save
  while pending; basic required-name guard before calling.

### 4.5 `SecurityForm.tsx`
- Controlled `current` / `next` / `confirm`. **Update** → if `next !== confirm`, show inline message
  and **do not** call (AC-12); else `getApiClient().changePassword({ current_password: current,
  new_password: next })`; on success clear fields + confirmation; on reject show the error
  (e.g. "Current password is incorrect"). Minimal length hint mirrors `AUTH_PASSWORD_MIN`.
- **Seam:** forms call only `getApiClient()` / hooks — no provider import (AC-13).

---

## 5. Tests mapped to acceptance criteria

**Backend (pytest, `backend/tests/integration/`).** Reuse the integration `client` fixture (a
`TestClient` **already authenticated** as `integration_test@example.com` / `IntTestPass1!` via
`authenticate(c)`), plus `authenticate_as(client,email,pw)` / `current_user_id(client)` from
`tests/integration/conftest.py`. Unauth cases use a bare `TestClient(create_app())` with no login (or
`client.cookies.clear()`).
- `test_settings_endpoints.py`: `client.patch("/api/auth/me", json=...)` updates + `GET /api/auth/me`
  reflects (AC-1); invalid name/title → 422 (AC-2); no session → 401 (AC-3);
  `client.post("/api/auth/me/password", …)` with current `IntTestPass1!` → 200, then
  `login` with the new password works & the old fails (AC-4); wrong-current → 400 + hash unchanged,
  i.e. old password still logs in (AC-5); bad new-password → 422 & no session → 401 (AC-6); a **second**
  client `authenticate_as(c2,"other@x.com")` changing its own profile/password does not affect the
  first account (AC-7).
- `test_user_store_update.py` (`backend/tests/unit/`): build `UserStore(str(tmp))` after
  `upgrade_to_head`, `create` a user, `update_profile`/`update_password`, **re-open** a new
  `UserStore` on the same path and assert the change persisted and id/email/created_at are unchanged
  (AC-8).

**Frontend (Vitest + RTL; mock/fake provider).**
- `settings.test.tsx`: renders Profile+Security tabs; Profile shows name/title/email with email
  disabled (AC-9); edit + Save calls `updateProfile` and shows success; rejected call → error
  (AC-10); success triggers `refreshCurrentUser` (spy) (AC-11); Security: confirm≠new blocks the call
  with a message; a `changePasswordError` rejection shows the inline error; success clears fields
  (AC-12).
- `settings-boundary.test.ts`: no `realProvider`/`mockProvider` import under `components/settings`
  (AC-13).

**Live smoke (AC-14):** `provider=real`; edit name/title → shell updates + `/me` reflects; change
password (correct current) → re-login with new (old rejected); wrong current → inline error.

---

## 6. Implementation order (TDD — §7)

1. **Backend tests (red):** write `test_user_store_update.py` + `test_settings_endpoints.py` first;
   confirm failing.
2. **Backend (green):** add `UserStore.update_profile`/`update_password`; factor the shared
   name/title/password validators; add the two models + endpoints; run backend suite GREEN (confirm
   the validator refactor didn't disturb signup).
3. **Seam (red→green):** extend the `ApiClient` interface + real + mock + `_fakeClient`; add
   `refreshCurrentUser` to `useCurrentUser`.
4. **Frontend tests (red):** write `settings.test.tsx` against the intended view API; confirm
   failing.
5. **Frontend (green):** build `AccountSettingsView` + `ProfileForm` + `SecurityForm`; swap
   `app/settings/page.tsx`; make tests pass.
6. **Boundary:** `settings-boundary.test.ts`.
7. **Verify:** `pytest` GREEN; `vitest run` GREEN; `tsc --noEmit`, `npm run lint`, `next build`
   (dev STOPPED). `git diff --name-only main` — no `app/graph/**`, no new migration.
8. **Live smoke (AC-14).** `.env.local` unchanged.

Tests are written failing first (§7). The one refactor (extracting signup's validators for reuse) is
behavior-preserving and guarded by the existing signup tests.

---

## 7. Notes / risks

- **`useCurrentUser` caches at module scope** — a plain `clearCurrentUser()` does NOT live-update
  already-mounted Sidebar/TopBar; hence the small subscriber/`refreshCurrentUser` addition (§4.2).
  Keep it backward-compatible so 020 consumers are unaffected.
- **Password change is security-sensitive** — verify current server-side (never trust the client);
  wrong-current returns 400 with **no** write; new-password bounds enforced by Pydantic. Tests for
  these are written first.
- **No session invalidation on password change (D3)** — acceptable for a single-owner stateless-cookie
  app; revisit only if forced re-login is later wanted.
- **Validator reuse vs. drift** — extract the signup validators rather than copy-paste so profile
  edits and signup stay identical; re-run signup tests to confirm.
- **`next build` vs `next dev`** — never build while dev runs; step 7 builds with dev stopped.
- **Out-of-scope discipline** — no Billing, Team, email change, avatar upload, SSO, 2FA, or the
  Integrations page (024).

---

*Per §1/§11, a `feature/023-account-settings` branch opens only after this plan.md + spec.md are
approved and `tasks.md` exists. No migration. No `tasks.md`/implementation in this pass — plan only.*
