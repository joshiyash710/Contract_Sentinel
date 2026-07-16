# Integrations page (Google Drive + Gmail) — Implementation Tasks

Reference documents:
- Spec: `specs/024-integrations/spec.md`
- Plan: `specs/024-integrations/plan.md`
- Constitution: `specs/000-constitution.md` (**no amendment**, **no backend change**, §2 Drive+Gmail only)
- Consumed: 020 (`useCurrentUser` → owner email via the `getApiClient().me()` seam), 013 UI
  primitives (`Card`, `Button`, lucide icons), 023 (`settings/page.tsx` + `settings-boundary.test.ts`
  as the pattern), 010/OAuth (server-managed Drive+Gmail delivery — context only, not touched).

Frontend paths relative to `frontend/`.

**Workflow reminders:**
- TDD (§7): tests written + confirmed FAILING before implementation.
- **Frontend-only** — no `backend/**`, no `types.ts`, no endpoint, no `app/graph/**`, no migration.
- Reach the backend only via `useCurrentUser` (→ `getApiClient().me()`) — no provider import under
  `components/integrations` (seam).
- **Honesty over the mockup:** show ONLY Google Drive + Gmail (Notion/Slack/Dropbox/Team are §2-cut);
  NO inert toggles, NO fake per-user "Connected" badge, NO live OAuth link — the connection is
  server-managed, so any Connect/Manage affordance is disabled/informational (like the deferred SSO
  buttons, 014 D6).
- The sidebar already points "Integrations" → `/integrations` (013) — **no nav change**.
- NEVER `next build` while `next dev` runs. Stop dev first.

---

## Task 0: Branch
- [ ] From up-to-date `main`, create `feature/024-integrations` (`git-start`). Commit the 024
  `spec.md`/`plan.md`/`tasks.md` on the branch.

**Verify:** `git branch --show-current` → `feature/024-integrations`.

---

## Task 1: View test (red)
- [ ] **[NEW] `src/__tests__/integrations.test.tsx`** — confirm FAILING. Mock
  `@/lib/useCurrentUser` (mirroring `settings.test.tsx`) so the test controls the email:
  ```ts
  let mockUser: { email: string | null } = { email: "owner@acme.com" };
  vi.mock("@/lib/useCurrentUser", () => ({
    useCurrentUser: () => ({ user: null, displayName: "there", title: null, email: mockUser.email, loading: false }),
  }));
  ```
  Render `<IntegrationsView />` and cover:
  - a **Google Drive** card and a **Gmail** card render (AC-1), each with a delivery-role
    description (AC-3).
  - the Gmail/delivery card text contains `owner@acme.com` (AC-4).
  - set `mockUser.email = null` before a render → a neutral fallback (e.g. "your account email")
    shows and there is **no** literal "undefined"/"null" in the document (AC-4/EC-1).
  - `screen.queryByText(/notion|slack|dropbox|team/i)` is `null` (AC-2).
  - the Connect/Manage control is **disabled** and is **not** an anchor to an OAuth URL — e.g. the
    button has the `disabled` attribute, and `screen.queryByRole("link", { name: /connect/i })` is
    null (AC-5).

**Verify:** the test imports `IntegrationsView` and fails (not built).

---

## Task 2: `IntegrationsView` (green)
- [ ] **[NEW] `src/components/integrations/IntegrationsView.tsx`** (`"use client"`) — build until the
  Task 1 test passes:
  - `const { email } = useCurrentUser();`
  - A short static intro line about report delivery through these services.
  - A static config array drives two cards (reuse `Card`; lucide `HardDrive` for Drive, `Mail` for
    Gmail, with a brand-accent color):
    - **Google Drive** — "Your analysis reports are automatically saved to Google Drive."
    - **Gmail** — "Finished reports are emailed to you at **{email ?? 'your account email'}**." (the
      fallback covers loading/absent — AC-4/EC-1).
  - Each card shows a **disabled** affordance: a `Button` with `disabled` (or a static pill) reading
    e.g. "Connected · Managed by ContractSentinel" — **no `href`/anchor to any OAuth URL** (AC-5).
  - A short static "How delivery works" note (on completion → saved to Drive + emailed to the owner).
  - Responsive `grid gap-4 sm:grid-cols-2` (stack on narrow — EC-2).
  - **Seam:** import only `useCurrentUser` + UI primitives + lucide — no provider import (AC-6).

**Verify:** `vitest run src/__tests__/integrations.test.tsx` → PASS.

---

## Task 3: Route
- [ ] **[MODIFY] `src/app/integrations/page.tsx`** — replace the stub with
  `<><TopBar title="Integrations" /><IntegrationsView /></>` (mirror `settings/page.tsx`).

**Verify:** `tsc --noEmit` clean; the page renders the view (covered by the view test + build).

---

## Task 4: Boundary test
- [ ] **[NEW] `src/__tests__/integrations-boundary.test.ts`** — assert no `realProvider`/
  `mockProvider` import under `src/components/integrations` (model on `settings-boundary.test.ts`,
  AC-6).

**Verify:** `vitest run src/__tests__/integrations-boundary.test.ts` → PASS.

---

## Task 5: Full verification
- [ ] `vitest run` (whole frontend) GREEN; `tsc --noEmit` clean; `npm run lint` clean.
- [ ] Stop dev; `next build` succeeds.
- [ ] `pytest` (whole backend) still GREEN (no backend changes expected).
- [ ] `git diff --name-only main` — no `backend/**`, no `types.ts`, no `app/graph/**`, no migration.

---

## Task 6: Live smoke (AC-7)
- [ ] Start `uvicorn app.api.main:app --port 8000` + `npm run dev` (provider `real`, per `.env.local`).
  (Before starting, kill any stale uvicorn/python on :8000 from a prior session — see
  [[feature-023-complete]] gotcha.)
- [ ] Smoke: log in → **Integrations** → the Google Drive + Gmail cards render with the **real**
  logged-in owner email as the delivery address; no Notion/Slack/Dropbox/Team; the Connect affordance
  is inert. Report the outcome.

---

## Task 7: Merge
- [ ] Whole frontend suite + `tsc` + `build` green; backend green; smoke noted.
- [ ] Rebase `main`, merge `feature/024-integrations`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/024-integrations`, opened after spec + plan +
tasks are approved. Frontend-only; no backend deps, no migration.*
