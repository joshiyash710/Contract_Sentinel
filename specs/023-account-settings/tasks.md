# Account Settings (editable profile + change password) — Implementation Tasks

Reference documents:
- Spec: `specs/023-account-settings/spec.md`
- Plan: `specs/023-account-settings/plan.md`
- Constitution: `specs/000-constitution.md` (**no amendment**, **no migration**, no graph change)
- Consumed: 014 auth (`auth_router`, `require_auth`, `hash_password`/`verify_password`,
  `AuthUser`/`AuthResponse`, `SignupRequest` validators), 019 per-user isolation, 020
  (`users.name`/`title`, `useCurrentUser`), 013 UI primitives (`Tabs`, `Avatar`, `TextInput`,
  `PasswordInput`, `Button`, `Card`), integration test fixtures (`tests/integration/conftest.py`:
  `client`, `authenticate_as`, `current_user_id`).

Backend paths relative to `backend/`, frontend paths relative to `frontend/`.

**Workflow reminders:**
- TDD (§7): tests written + confirmed FAILING before implementation. **Password-change is
  security-sensitive** — write the wrong-current / weak-password / unauth tests FIRST.
- **No Alembic migration** (`name`/`title`/`password_hash` columns already exist); **no
  `app/graph/**` change**; **no `ContractState`** change.
- Backend endpoints act only on `current_user` (from `require_auth`) — never accept a `user_id`/email
  from the body to target another account (019).
- Frontend reaches the backend only via `getApiClient()` / hooks — no provider import under
  `components/settings` (seam). **Reuse the `src/components/ui/` primitives — do not hand-roll.**
- NEVER `next build` while `next dev` runs. Stop dev first.

---

## Task 0: Branch
- [ ] From up-to-date `main`, create `feature/023-account-settings` (`git-start`). Commit the 023
  `spec.md`/`plan.md`/`tasks.md` on the branch.

**Verify:** `git branch --show-current` → `feature/023-account-settings`.

---

## Task 1: Backend tests (red)
- [ ] **[NEW] `tests/unit/test_user_store_update.py`** — confirm FAILING. `upgrade_to_head(str(tmp))`;
  `store = UserStore(str(tmp))`; `u = store.create(email, hash_password("Pw1!pass"), name="A",
  title="T")`. Assert:
  - `update_profile(u.id, "New Name", "New Title")` returns a row with the new name/title;
    a fresh `UserStore(str(tmp))).get_by_id(u.id)` reflects them (persisted); `email`/`id`/
    `created_at` unchanged (AC-8).
  - `update_password(u.id, hash_password("Pw2!pass"))` persists; after re-open,
    `verify_password("Pw2!pass", row.password_hash)` is True and the old is False (AC-8).
- [ ] **[NEW] `tests/integration/test_settings_endpoints.py`** — confirm FAILING. Use the integration
  `client` fixture (already authed as `integration_test@example.com` / `IntTestPass1!`). Cover
  AC-1..7 exactly as Task 2/plan §5 describe (patch profile happy + GET /me reflects; invalid
  name/title 422; **unauth 401 via `client.cookies.clear()`** on the fixture client — NOT a bare
  `TestClient(create_app())`, which would run lifespan against the real DB paths; change-password
  happy → login-with-new works & old fails; wrong-current 400 + old still logs in; weak new-password
  422; **isolation (AC-7):** on the same `client`, `authenticate_as(client, "other@x.com",
  "OtherPw1!")` (this switches the session to the new account), change *that* account's password,
  then `client.cookies.clear()` and confirm account A still logs in with `IntTestPass1!` — i.e. one
  account's change never touches another; the request bodies expose no `user_id`/email to target
  another account).

**Verify:** both files fail (endpoints/methods not yet present).

---

## Task 2: Backend (green)
- [ ] **[MODIFY] `app/runner/user_store.py`** — add (mirror `create()`'s `with self._lock: … commit()`):
  ```python
  def update_profile(self, user_id, name, title):   # -> UserRow
      with self._lock:
          self._conn.execute("UPDATE users SET name=?, title=? WHERE id=?", (name, title, user_id))
          self._conn.commit()
      return self.get_by_id(user_id)
  def update_password(self, user_id, new_hash):      # -> None
      with self._lock:
          self._conn.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user_id))
          self._conn.commit()
  ```
- [ ] **[MODIFY] `app/api/auth.py`**:
  - Extract the signup field-validator bodies into module functions `_validate_name(v)`,
    `_validate_title(v)`, `_validate_password(v)`; have `SignupRequest`'s validators call them
    (behavior-preserving — the existing signup tests must stay green).
  - Add `UpdateProfileRequest { name: str; title: Optional[str] = None }` (validators →
    `_validate_name` / `_validate_title`) and `ChangePasswordRequest { current_password: str;
    new_password: str }` (`new_password` → `_validate_password`).
  - `@auth_router.patch("/me", response_model=AuthResponse)` `async def update_me(body:
    UpdateProfileRequest, request: Request, current_user: AuthUser = Depends(require_auth))`:
    `row = request.app.state.user_store.update_profile(current_user.id, body.name, body.title)`;
    return `AuthResponse(user=AuthUser(id=row.id, email=row.email, name=row.name, title=row.title))`.
  - `@auth_router.post("/me/password")` `async def change_password(body: ChangePasswordRequest,
    request: Request, current_user: AuthUser = Depends(require_auth))`: `store =
    request.app.state.user_store`; `row = store.get_by_id(current_user.id)`; if `not
    verify_password(body.current_password, row.password_hash)` → `raise HTTPException(400,
    "Current password is incorrect")`; else `store.update_password(current_user.id,
    hash_password(body.new_password))`; `return {"ok": True}`.

**Verify:** `pytest tests/unit/test_user_store_update.py tests/integration/test_settings_endpoints.py`
→ PASS; full `pytest` GREEN (signup/login unaffected by the validator extraction).

---

## Task 3: Frontend seam + live-refresh
- [ ] **[MODIFY] `src/lib/api/client.ts`** — add to the `ApiClient` interface (after `me()`):
  `updateProfile(body: { name: string; title?: string | null }): Promise<AuthUser>;` and
  `changePassword(body: { current_password: string; new_password: string }): Promise<void>;`.
- [ ] **[MODIFY] `src/lib/api/realProvider.ts`** — `updateProfile`: `PATCH ${base()}/api/auth/me`
  (headers JSON, `body: JSON.stringify(body)`, `credentials:"include"`), return `(await res.json()).user`;
  `changePassword`: `POST ${base()}/api/auth/me/password` (same options), resolve on ok, throw
  `ApiError(message, res.status)` on non-ok (surface the 400 detail). Mirror the existing
  `signup`/`me` error handling.
- [ ] **[MODIFY] `src/lib/api/mockProvider.ts`** — `updateProfile: async (b) => ({ ...authUserFixture,
  ...b })`; `changePassword: async () => {}`.
- [ ] **[MODIFY] `src/__tests__/_fakeClient.ts`** — add opts `updateProfileError?`,
  `changePasswordError?`; `updateProfile: vi.fn(async (b) => { if (opts.updateProfileError) throw
  opts.updateProfileError; return { ...(opts.authUser ?? authUserFixture), ...b }; })`;
  `changePassword: vi.fn(async () => { if (opts.changePasswordError) throw opts.changePasswordError; })`.
- [ ] **[MODIFY] `src/lib/useCurrentUser.ts`** — add a module `Set<() => void>` of subscribers and
  `export async function refreshCurrentUser(): Promise<void>` (`_cached = null; await
  fetchCurrentUser(); subscribers.forEach(fn => fn())`). In `useCurrentUser`, register a re-render
  callback on mount / unregister on unmount so mounted Sidebar/TopBar update after a save (AC-11).
  Keep the return shape unchanged (backward-compatible with 020 consumers).

**Verify:** `tsc --noEmit` clean; existing auth/shell tests still green.

---

## Task 4: Frontend tests (red)
- [ ] **[NEW] `src/__tests__/settings.test.tsx`** — confirm FAILING. Mock `@/lib/api/provider` with
  `makeFakeClient`; mock `@/lib/useCurrentUser` to return a known `{user,displayName,title,email,
  loading}` plus a **spy `refreshCurrentUser`**. Render `<AccountSettingsView/>` (or the page). Cover:
  - Profile + Security tabs render (`role="tab"` names "Profile"/"Security"); Profile shows
    name/title/email with the **Email** input `disabled` (AC-9).
  - Edit Full Name → click **Save** → `updateProfile` called with the new value; success message
    (AC-10); with `updateProfileError` set → error message, no crash (AC-10).
  - On successful save, the spy `refreshCurrentUser` was called (AC-11).
  - Security tab: set New ≠ Confirm → **Update** shows an inline mismatch message and
    `changePassword` is **not** called; New = Confirm → `changePassword` called with current/new;
    with `changePasswordError` (an `ApiError` "Current password is incorrect") → inline error;
    success → fields cleared + confirmation (AC-12).

**Verify:** the test imports the intended components and fails.

---

## Task 5: Frontend (green)
- [ ] **[NEW] `src/components/settings/AccountSettingsView.tsx`** (`"use client"`) — two-column
  layout (`grid gap-6 lg:grid-cols-[minmax(0,20rem)_1fr]`): left `Card` with `<Avatar
  name={displayName} size="lg" />` + name + title; right `Card` with `<Tabs variant="underline"
  items={[{value:"profile",label:"Profile"},{value:"security",label:"Security"}]} value={tab}
  onChange={setTab} />` and the active form. Default tab `profile`.
- [ ] **[NEW] `src/components/settings/ProfileForm.tsx`** — `TextInput`s for Full Name + Job Title
  (seeded from `useCurrentUser`), a `disabled` Email `TextInput`, and a **Save** `Button`. On submit
  → `getApiClient().updateProfile({ name, title })`; on success `await refreshCurrentUser()` + success
  text; on reject → error text. Disable Save while pending; block empty name.
- [ ] **[NEW] `src/components/settings/SecurityForm.tsx`** — `PasswordInput`s for Current / New /
  Confirm + an **Update password** `Button`. If New ≠ Confirm → inline message, no call. Else
  `getApiClient().changePassword({ current_password, new_password })`; success → clear fields +
  confirmation; reject → inline error (show `err.message`).
- [ ] **[MODIFY] `src/app/settings/page.tsx`** — replace the stub with
  `<><TopBar title="User Profile & Settings" /><AccountSettingsView /></>` (D8).

**Verify:** `vitest run src/__tests__/settings.test.tsx` → PASS.

---

## Task 6: Boundary test
- [ ] **[NEW] `src/__tests__/settings-boundary.test.ts`** — assert no `realProvider`/`mockProvider`
  import under `src/components/settings` (model on `report-boundary.test.ts`, AC-13).

**Verify:** `vitest run src/__tests__/settings-boundary.test.ts` → PASS.

---

## Task 7: Full verification
- [ ] `pytest` (whole backend) GREEN.
- [ ] `vitest run` (whole frontend) GREEN; `tsc --noEmit` clean; `npm run lint` clean.
- [ ] Stop dev; `next build` succeeds.
- [ ] `git diff --name-only main` — no `app/graph/**`, no new Alembic revision under
  `app/runner/migrations/`, no `ContractState` change.

---

## Task 8: Live smoke (AC-14)
- [ ] Start `uvicorn app.api.main:app --port 8000` + `npm run dev` (provider `real`, per `.env.local`).
- [ ] Smoke: log in → **User Profile & Settings** → edit name/title → **Save** → the sidebar/topbar
  name updates without reload and `GET /api/auth/me` returns the new values; **Security** → change
  password with the correct current one → log out → log back in with the **new** password (old
  rejected); a **wrong** current password shows the inline error. Report the outcome.

---

## Task 9: Merge
- [ ] All backend + frontend suites + `tsc` + `build` green; smoke noted.
- [ ] Rebase `main`, merge `feature/023-account-settings`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/023-account-settings`, opened after spec +
plan + tasks are approved. No migration.*
