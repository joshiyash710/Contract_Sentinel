# Integrations page (Google Drive + Gmail) — Technical Plan

## Git Branch

`feature/024-integrations` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

Implements `specs/024-integrations/spec.md` (phase 2 of 2) — **frontend-only**. Turns the
`/integrations` stub into a real, honest page describing the **two** integrations the product uses —
**Google Drive + Gmail** — which power automatic report delivery (010: on completion a report is
saved to Drive and emailed to the account owner, `current_user.email` per 020). The only dynamic
element is the owner email, read via the existing `useCurrentUser` (020) through the `getApiClient()`
seam. **No backend, endpoint, graph, `ContractState`, or migration change.** Notion/Slack/Dropbox and
Team are cut (§2). The sidebar already points "Integrations" → `/integrations` (013) — no nav change.

---

## 2. Files to Create / Modify

### Frontend (`frontend/`)
```
src/app/integrations/page.tsx                     [MODIFY] replace stub → <TopBar title="Integrations"/> + <IntegrationsView/>
src/components/integrations/IntegrationsView.tsx  [NEW]    intro + Drive/Gmail cards + "how delivery works" note; reads useCurrentUser for the owner email
src/__tests__/integrations.test.tsx               [NEW]    AC-1..5 (both cards, owner email, no Notion/Slack/Dropbox/Team, disabled connect)
src/__tests__/integrations-boundary.test.ts       [NEW]    AC-6 (no provider import under components/integrations)
```
No `backend/**`, no `types.ts`, no `app/graph/**`, no new endpoint/migration.

---

## 3. Frontend design

> **Client/server (§8).** `IntegrationsView` is a client component (`useCurrentUser`).
> `app/integrations/page.tsx` stays a thin server shell rendering `<TopBar/>` + the view (mirrors
> `dashboard`/`settings`).

### 3.1 `IntegrationsView.tsx`
- **Data:** `const { email, loading } = useCurrentUser();` — the report destination. No other fetch.
- **Header/intro:** a short line: "ContractSentinel delivers every finished analysis report through
  these connected services." (Static.)
- **Integration cards** — a small static config drives two `<IntegrationCard>`s:
  ```ts
  const INTEGRATIONS = [
    { key: "drive", name: "Google Drive", Icon: HardDrive,
      description: "Your analysis reports are automatically saved to Google Drive." },
    { key: "gmail", name: "Gmail", Icon: Mail,
      description: "Finished reports are emailed to you." }, // owner email appended at render
  ];
  ```
  - Each card: `Card` with the lucide icon (brand-accent color), the name, the description, and a
    **status/affordance** row. For Gmail, append the destination: `Finished reports are emailed to
    you at {email ?? "your account email"}` — the fallback covers `loading`/absent (EC-1/AC-4).
  - **Affordance (D3/AC-5):** a **disabled** "Connected — managed by ContractSentinel" state (a
    `Button` `disabled`, or a static pill), NOT a live OAuth link. No `href` to any OAuth URL. This
    mirrors the deferred-SSO posture (014 D6).
- **"How delivery works" note:** one short paragraph tying it together (on completion → saved to
  Drive + emailed to the owner). Static.
- **Responsive:** cards in a `grid gap-4 sm:grid-cols-2` (stack on narrow — EC-2).
- **Seam:** reaches the backend only via `useCurrentUser` (→ `getApiClient().me()`); no provider
  import (AC-6).
- **Icons:** lucide `HardDrive` (Drive) + `Mail` (Gmail) — the design system is lucide-based; no
  brand SVGs are added (an inline `GoogleGlyph` exists in `AuthView` but there are no Drive/Gmail
  brand icons, and monochrome lucide keeps visual consistency).

### 3.2 `app/integrations/page.tsx`
```tsx
return (<><TopBar title="Integrations" /><IntegrationsView /></>);
```
(Mirrors `settings/page.tsx` from 023.)

---

## 4. Tests mapped to acceptance criteria

**Frontend (Vitest + RTL).** Mock `@/lib/useCurrentUser` directly (mirroring 023's settings test) so
the test controls the email and can exercise the fallback — cleaner than routing through the client.
- `integrations.test.tsx`:
  - renders a **Google Drive** card and a **Gmail** card (AC-1); each shows a delivery-role
    description (AC-3).
  - with the mock returning `email: "owner@acme.com"` the Gmail/delivery card contains that email
    (AC-4); with the mock returning `email: null` (logged-out/loading) → a neutral fallback, no
    "undefined"/"null" text (AC-4/EC-1).
  - `queryByText(/notion|slack|dropbox|team/i)` is null (AC-2).
  - the Connect/Manage affordance is disabled and is not an anchor to an OAuth URL (AC-5).
- `integrations-boundary.test.ts`: no `realProvider`/`mockProvider` import under
  `components/integrations` (model on `settings-boundary.test.ts`, AC-6).

**Live smoke (AC-7):** `provider=real`; open Integrations → Drive + Gmail cards with the real owner
email as the delivery address; no Notion/Slack/Dropbox/Team.

---

## 5. Implementation order (TDD — §7)

1. **View test (red):** write `integrations.test.tsx` against the intended `IntegrationsView`
   (cards, owner email, no cut services, disabled connect); confirm failing.
2. **View (green):** build `IntegrationsView` (intro + config-driven cards + note) until it passes;
   reuse `Card`/`Button` + lucide icons + `useCurrentUser`.
3. **Route:** swap `app/integrations/page.tsx` to render `TopBar` + the view.
4. **Boundary:** `integrations-boundary.test.ts`.
5. **Verify:** `vitest run` (whole) GREEN; `tsc --noEmit`, `npm run lint`, `next build` (dev
   STOPPED). Backend untouched — `git diff --name-only main` shows no `backend/**`; run `pytest` once
   to confirm still green (no changes expected).
6. **Live smoke (AC-7).** `.env.local` unchanged.

Each step's tests are written failing first (§7). No pre-existing test needs changing (the stub had
no assertions of its own beyond, at most, a title).

---

## 6. Notes / risks

- **Honesty over the mockup.** The reference shows Notion/Slack/Dropbox cards and per-item toggles;
  we deliberately show only Drive + Gmail and no inert toggles/fake "Connected" per-user badge — the
  connection is server-managed (D3/D5). Keep the affordance clearly non-actionable.
- **No per-user connect backend.** Do NOT wire any OAuth link/redirect; that is a separate,
  backend-touching feature (§6). The buttons are informational only.
- **Owner email fallback.** `useCurrentUser` is no-throw and async (020) — always guard the email
  with a neutral fallback so the card never renders "undefined"/blank (EC-1).
- **`next build` vs `next dev`** — never build while dev runs; step 5 builds with dev stopped.
- **Out-of-scope discipline** — no live per-job delivery status, no Drive upload-source, no
  Notion/Slack/Dropbox/Team, no backend change.

---

*Per §1/§11, a `feature/024-integrations` branch opens only after this plan.md + spec.md are approved
and `tasks.md` exists. Frontend-only; no backend deps, no migration. No `tasks.md`/implementation in
this pass — plan only.*
