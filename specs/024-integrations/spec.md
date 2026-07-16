# Feature 024 — Integrations page (Google Drive + Gmail)

## 1. Problem statement

The **Integrations** page (`/integrations`) is still a placeholder stub. The sidebar has always
carried an "Integrations" nav item (013), and the design ref (3) shows integration cards, but no real
page was ever built. This feature makes `/integrations` a real, honest page describing the **two
integrations the product actually uses — Google Drive and Gmail** — which power automatic **report
delivery** (010 MCP delivery: on analysis completion a report is saved to Drive and emailed to the
account owner, whose address defaults to `current_user.email` per 020).

This is **phase 2** of the post-022 set (023 account settings ✓ → **024 integrations**).

### Position relative to the constitution

**No amendment. No backend/graph/`ContractState`/endpoint/migration change. Frontend-only.** Drive +
Gmail are the **only** integrations §2 permits ("Slack, Notion, or any MCP integration beyond Drive +
Gmail" is PERMANENTLY CUT), so the mockup's **Notion, Slack, Dropbox** cards and the **Team**
management toggles are not built. The page consumes only already-available data: the logged-in
user's email via the existing `useCurrentUser` (020) through the `getApiClient()` seam. Per §11 it is
developed on `feature/024-integrations`.

## 2. Inputs and outputs

### 2.1 Data source (unchanged)
The only dynamic input is the current user's **email** (the report destination), read from
`useCurrentUser()` (020) — which already reaches the backend only via `getApiClient().me()`. No new
endpoint, no new field. Everything else on the page is descriptive/static copy about how delivery
works.

### 2.2 The Integrations page (`/integrations`)
Replaces the stub with a real page:
- **Header** — `TopBar` "Integrations" + a short intro explaining that ContractSentinel delivers
  every finished analysis report through these connected services.
- **Two integration cards** (Drive + Gmail), each with the service icon/name, a one-line description
  of its role in delivery, and a **status/affordance** (see D3):
  - **Google Drive** — "Your analysis reports are automatically saved to Google Drive."
  - **Gmail** — "Finished reports are emailed to you at **{owner email}**." (the email from
    `useCurrentUser`; a neutral fallback while loading / if unavailable — EC-1).
- A short **"How delivery works"** note tying it together (on completion → saved to Drive + emailed
  to the owner). No fabricated per-user connection toggles (the mockup's inert toggles are omitted —
  D5).
- Polished **loading** (while the email resolves) consistent with the dashboard (018).

## 3. Resolved decisions (inline)

- **D1 — Standalone `/integrations` page.** Per the two-separate-pages choice made for 023/024,
  Integrations is its own route (not a Settings tab). The sidebar "Integrations" item already points
  to `/integrations` (013) — **no nav change**.
- **D2 — Google Drive + Gmail only.** Notion, Slack, Dropbox (from the mockups) and Team management
  are **cut** (§2 PERMANENTLY CUT / no backend). The page shows exactly the two supported services.
- **D3 — Descriptive, not a per-user OAuth connect flow.** Report delivery uses a **server-managed**
  Google connection (one provisioned token — 010 / OAuth bootstrap), not per-user OAuth. There is no
  per-account "Connect" backend, so the page **describes** each integration and its status as
  **managed by the app**; any Connect/Manage affordance is rendered **disabled/informational**
  (the same honest posture as the deferred SSO buttons, 014 D6). Rationale: real per-user OAuth needs
  a Google Cloud app + per-user token storage + a callback — a separate, backend-touching feature.
- **D4 — Frontend-only; the one dynamic element is the owner email.** Showing where reports are sent
  (`useCurrentUser().email`, 020) makes the page real and honest without any backend change. No
  endpoint, migration, graph, or state change.
- **D5 — No fabricated toggles or fake "Connected" per-user state.** The mockup's inert on/off
  toggles and a per-user "Connected" badge would misrepresent the server-managed model; instead the
  cards state plainly what each service does and that it is managed by ContractSentinel.
- **D6 — Reuse primitives + patterns.** Built from `Card`/`Button` and brand icons already in the
  design system, with the 018 loading pattern; reaches the backend only via `useCurrentUser` (seam).
- **D7 — No live per-job delivery status here.** Whether a *specific* report was delivered
  (`mcp_delivery_status`) belongs to the report/job views, not this page (out of scope — §6).

## 4. Acceptance criteria

Frontend → Vitest + RTL (mock/fake provider). No backend criteria (unchanged).

- **AC-1:** `/integrations` renders a **Google Drive** card and a **Gmail** card (was a stub).
- **AC-2:** **Only** Drive + Gmail appear — no "Notion", "Slack", "Dropbox", or "Team" card/text is
  rendered anywhere on the page (§2).
- **AC-3:** Each card shows a description of its role in **report delivery** (Drive = reports saved;
  Gmail = reports emailed).
- **AC-4:** The Gmail/delivery card shows the **owner email** from `useCurrentUser()`
  (e.g. contains `sarah@acme.com` for that fixture); while the email is loading or unavailable, a
  neutral fallback renders (no crash, no literal "null"/"undefined").
- **AC-5:** Any Connect/Manage affordance is **disabled/informational** — it is not a live OAuth
  action (no navigation to an OAuth URL, matching the deferred-SSO posture).
- **AC-6:** **Seam/boundary:** no file under `components/integrations/**` imports a provider module
  directly (only `getApiClient()` / `useCurrentUser`); **no `backend/**` change**; no new endpoint.

**Live (real backend)**
- **AC-7 (smoke, manual):** With `provider=real`, open Integrations → the Drive + Gmail cards render
  with the **real** logged-in owner email as the delivery address; no Notion/Slack/Dropbox/Team.

## 5. Edge cases
- **EC-1 — Email loading / unavailable** (`useCurrentUser` still resolving, or a 401 yielding no
  user — 020 no-throw) → the Gmail card shows a neutral fallback ("your account email") instead of a
  blank or "undefined" (AC-4).
- **EC-2 — Narrow viewport** → the two cards stack to a single column; no horizontal overflow.
- **EC-3 — Logged-out / gated** → the route is behind the existing auth gate (middleware); this page
  adds no new auth handling.

## 6. Out of scope
- **Per-user OAuth "Connect" flows** (Google/any) — a separate backend feature (D3); buttons here are
  informational only.
- **Notion, Slack, Dropbox**, and **Team/collaboration** integrations — PERMANENTLY CUT (§2).
- **Live per-job delivery status / retry** (`mcp_delivery_status`) — belongs to the report/job views
  (D7).
- **Uploading contracts *from* Drive** (the mockup's upload-source connect) — not built; upload is
  the existing drag-drop/file flow (015).
- **Any backend / endpoint / graph / state / migration change** — none.

## 7. Notes for plan.md / tasks.md (pointers)
- **Frontend touch:** `src/app/integrations/page.tsx` (replace the stub → `<TopBar/>` + the new
  view), a new `src/components/integrations/IntegrationsView.tsx` (+ small card sub-component), reuse
  `Card`/`Button` and **lucide icons** (e.g. `HardDrive` for Drive, `Mail` for Gmail — the design
  system is lucide-based; no dedicated Drive/Gmail brand SVGs exist), and `useCurrentUser` (020) for
  the owner email. Optionally a tiny static config array for the two integrations.
- **Tests:** an `integrations` view test (Drive+Gmail present, owner email shown, no
  Notion/Slack/Dropbox/Team, disabled connect) + a boundary grep (no provider import under
  `components/integrations`). TDD (§7): failing tests first. No backend tests (unchanged).
