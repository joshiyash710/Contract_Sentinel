# Feature 013 — Frontend Design System + App Shell

## 1. Problem statement

Features 001–012 delivered the complete backend: the fixed 7-node LangGraph
pipeline, MCP Drive/Gmail delivery (010), the FastAPI + SSE runner (011), and
durable SQLite persistence (012). The `frontend/` directory holds only an empty
Next.js `package.json` scaffold — **there is no UI**. Feature 011 §5 explicitly
states it "exposes the HTTP + SSE contract the future `frontend/` will consume;
it ships no UI." This feature begins building that consumer.

This is the **first of a phased frontend rollout** (013–018). Its scope is the
*foundation only* — the design system and application shell that every later
feature screen is built on. It intentionally ships **no feature screen**
(no upload flow, no analysis workspace, no reports view). Those are owned by
later specs (see §5). Building the foundation first was an explicit decision so
that the visual language (extracted pixel-exact from the reference images) and
the app scaffolding are defined once, in one place, before six screen-groups
are built against them.

### Position relative to the fixed architecture (constitution §2)

The frontend sits **entirely outside** the LangGraph StateGraph. It adds no
graph node and no conditional edge; it does not touch `backend/app/graph/`.
It is a pure HTTP/SSE client of the boundary that feature 011 already defined.
Per constitution §11, this feature still follows the one-branch-per-feature git
workflow (`feature/013-frontend-design-system`) even though it is frontend, not
backend.

### Reference-image fidelity mandate

Twelve reference images live in
`specs/013-frontend-design-system/design-refs/`. The user's requirement is
**pixel-exact fidelity** to these designs. The literal *text* in the mockups is
AI-generated placeholder (lorem-ipsum / garbled) and is **not** authoritative;
the *layout, spacing, color, typography, component shapes, and iconography*
**are**. This spec's job is to codify that visual language as reusable tokens
and primitives so the later screen specs inherit it automatically.

### Constitutional conflict surfaced (not silently resolved — see §6)

Some reference screens depict features that are **PERMANENTLY CUT** in
constitution §2 (Notion/Slack/Dropbox integrations; login/SSO/auth). This
foundation feature does not build those screens, but it does define the shell's
navigation and the integration-card / auth-form primitives that those screens
would use. Whether those primitives are built at all is an architecturally
significant question left open in §6 rather than guessed.

## 2. Inputs and outputs

### 2.1 Relationship to `ContractState` (001) and the 011 API contract

This feature **introduces no new backend field** and does not conflict with any
name in `001-contract-state-schema.md`. It is a *consumer*, and it consumes the
Pydantic boundary models that feature 011 already defined — never the internal
`ContractState` `TypedDict` directly (constitution §4: the `TypedDict` never
crosses the HTTP boundary).

The design-system layer itself renders **no live contract data** (feature
screens do that later). What it owns is the **typed API-client seam** — the
single module through which every later screen talks to the backend, and the
TypeScript mirror types for the 011 contract. Those mirror types must match
011 §2 exactly:

| TS type (this feature) | Mirrors (011 / 001) | Notes |
| --- | --- | --- |
| `AnalyzeAccepted` | 011 §2.2 `AnalyzeAccepted` | `{ job_id, status, submitted_at }` |
| `JobStatus` | 011 §2.3 | **all nine fields, field-for-field:** `job_id`, `status: JobState`, `current_node?`, `completed_nodes`, `submitted_at`, `started_at?`, `finished_at?`, `report_available`, `mcp_delivery_status`, `error?`. (Mirror 011 §2.3 verbatim — do not trim.) |
| `JobState` | 011 §2.3 enum | `"queued" \| "running" \| "completed" \| "failed"` |
| `ProgressEvent` | 011 §2.4 | SSE payload: `event`, `job_id`, `node?`, `index?`, `total?`, `elapsed_seconds?`, `final?`. **`final: JobStatus` is present ONLY on the terminal `completed`/`failed` event, never on `progress`** (011 §2.4) — type it optional/terminal-only. |
| `MCPDeliveryInfo` | 001 lines 75–78 | `{ status, error_message?, delivered_at? }` |
| `MCPDeliveryStatus` | 001 lines 70–73 | `"pending" \| "success" \| "failed"` |
| `RiskLevel` | 001 lines 65–68 | `"low" \| "medium" \| "high"` — drives risk-badge/donut colors |
| `ErrorInfo` | 011 §2.3 `error` | `{ … }` shape as 011 defines it |

These are **type mirrors**, not a new schema. If 011's contract changes, these
change with it; this spec does not get to invent divergent field names
(constitution §10 spirit, applied to the frontend mirror).

### 2.2 Design tokens (the primary output artifact)

The core deliverable is a single source-of-truth token set, extracted
pixel-exact from the reference images, exposed both as CSS custom properties and
through the Tailwind theme config so primitives and later screens consume the
*same* values. The token groups, with values read from the reference images:

**Color — surfaces (dark theme, the only theme in scope):**
| Token | Role | Approx. value (to be color-picked exact in plan) |
| --- | --- | --- |
| `--bg-app` | App background (near-black navy) | ~`#0A0B0F` / `#0B0E14` |
| `--bg-sidebar` | Left nav background (slightly distinct from app) | ~`#0D0F16` |
| `--bg-card` | Card / panel surface (one step lighter) | ~`#141821` / `#161A23` |
| `--bg-card-raised` | Nested/raised surface (chips, inner cards) | ~`#1B2030` |
| `--border-subtle` | Hairline card & divider borders | ~`#232838` |
| `--border-focus` | Focused input / active outline | violet, see accent |

**Color — brand accent (violet→blue gradient):**
| Token | Role | Approx. value |
| --- | --- | --- |
| `--accent` | Primary solid violet | ~`#6D5EF6` / `#7C6CF5` |
| `--accent-gradient-from` | Gradient start (violet) | ~`#7A5CFF` |
| `--accent-gradient-to` | Gradient end (blue) | ~`#5B8DEF` |
| `--accent-fg` | Text/icon on accent | `#FFFFFF` |
| `--logo-gradient` | The "C" logo circle | violet→blue radial |

**Color — risk scale (must map 1:1 to `RiskLevel` from 001):**
| Token | `RiskLevel` | Approx. value |
| --- | --- | --- |
| `--risk-high` | `high` | red ~`#EF4444` |
| `--risk-medium` | `medium` (a.k.a. "Amber") | amber ~`#F59E0B` |
| `--risk-low` | `low` | green ~`#22C55E` |

The "Amber" label seen in some mockups is a **display synonym for
`medium`**, not a fourth level — 001 defines exactly three risk levels. This is
recorded so no later screen invents an "amber" enum value.

**Numeric risk score ("78/100", "65/100").** Screens 7, 8, 10, 11, 12 show a
*numeric* 0–100 score pill, visually distinct from the categorical High/Medium/
Low badge. **001 defines no 0–100 numeric-score field** on `ContractState` (only
the categorical `RiskLevel` per clause). Recorded here — like the Amber note —
so later screens do NOT assume a backend field: this pill is either a
display-only value derived by a screen, or it has no data source and renders from
mock data. Resolving where the number comes from is deferred to the owning screen
spec (018/017); the design-system layer ships only the pill *primitive*, not a
data source. See Open Question Q7.

**Color — text:**
`--text-primary` (near-white ~`#F5F6FA`), `--text-secondary` (muted
~`#9AA3B2`), `--text-tertiary`/placeholder (~`#5C6472`).

**Typography:** a single geometric-sans family (bold, tight tracking on
headings; the plan picks the exact font — Inter or a close match to the
mockups) with a defined scale: hero/display (the landing hero, screen 1), page-title (the large
bold in-app page heading — "AI Command Center", "Generate & Download Reports:" —
sized between display and h1, so the shell heading is a token, not ad-hoc), h1,
h2, h3, body, small, caption.
Weights: regular / medium / semibold / bold.

**Spacing, radius, elevation:** an 4px-based spacing scale; card radius
(~12–16px, matching the mockups' rounded panels); the soft violet outer-glow /
shadow used behind active cards and the primary button.

**Charts palette:** derived tokens for the donut (risk colors), bar charts
(violet/blue pair, incl. a **grouped/2-series** variant seen on screen 3), area
chart (violet gradient fill), the heatmap (yellow→orange→red ramp), and the
**radial gauge** (the "Overall Portfolio Health Score" gauges on screen 3). Chart
*components* are wrappers (see §2.3); their *colors* come from tokens.

Exact hex values are color-picked from the reference images in `plan.md`; this
spec fixes the token **names, roles, and structure** so they are stable.

### 2.3 App shell + primitive inventory (structural output)

The shell and primitives observed across all 12 reference images, that this
feature builds as reusable, screen-agnostic components:

**App shell:**
- Left **sidebar**: logo (gradient "C" + "ContractSentinel" wordmark) at top;
  vertical nav of icon+label rows — **Dashboard, Contracts, Reports,
  Integrations, Settings** (the exact set repeated across screens 3, 4, 5, 7,
  9–12); an **active-item highlight** (violet pill / filled row, seen on
  "Dashboard" and "Reports" in different screens); an **expandable nav-item
  variant** (the "Integrations" row shows a chevron / collapsible submenu on
  screens 9, 10, 12, and renders flat on screens 3, 4, 5, 7 — so the nav item
  supports an optional expand/collapse affordance); a **user-profile block**
  pinned to the sidebar bottom (avatar + name + role, e.g. "Sarah Jenkins /
  Legal Counsel").
- **Top bar**: page title (left), an **optional** search field (present on
  screens 10, 11 & 12, absent on others — so it is a slot, not always rendered),
  and a right cluster of settings gear, notifications bell (with unread dot),
  and avatar/account menu.
- **App layout / routing**: Next.js App Router layout that composes
  sidebar + top bar + a content outlet; route registration for the later
  screen groups (routes declared as placeholders here, screens filled in by
  014–018).

**Primitives** (each built once, driven by tokens):
- Buttons: **primary** (gradient violet→blue, e.g. "Continue to
  ContractSentinel", "Upload New Contract", "Browse Files"), **secondary /
  outline**, **ghost/icon** button, and a **chip** variant (small pill-shaped
  action, e.g. the "Is this risky?" / "Compare with standard" / "[Rewrite]"
  suggestion chips on screens 5, 6, 7).
- **Avatar** — the circular user/AI image with an **initials fallback** (appears
  in the sidebar profile block, top-bar account cluster, and later chat/activity
  rows — screens 3, 4, 7, 8, 9, 10, 11, 12). Reusable, `size` + `fallback` props;
  never bakes a mockup name (spec EC-5).
- **ProgressBar** — a determinate horizontal progress bar (the violet bar on the
  Processing screen 6 and the Clause-doc panel screen 5), distinct from the
  discrete **Stepper**. Driven by a 0–100 / `index`·`total` value, so 015/016 can
  wire it to the SSE `index`/`total` progress fields (011 §2.4).
- **ListRow** — a generic row (leading icon/marker slot + title/subtitle text
  stack + optional trailing slot) underlying the Activity Feed and Notifications
  lists on screen 10 and the notification rows on screen 11. Fully props-driven.
- **Card / panel** (the bordered raised surface used everywhere), incl. the
  active-glow variant.
- **Risk badge** — pill rendering High/Medium/Low, colored from the risk
  tokens, driven by the `RiskLevel` type.
- **Status badge** — the neutral/semantic pills seen in the history table
  ("Analysed", "Redlined", "Needs Review"); label set is a prop, not
  hardcoded to those three (screen 12 owns the real set later).
- **Inputs**: text field, password field with show/hide eye toggle, search
  field.
- **Tabs** — supports **two variants**: a **segmented** control (Login/Sign Up,
  screen 2) and an **underline** style (Profile/Billing/Integrations/Security/
  Team on screen 4; Chat/Active on screen 7).
- **Toggle switch** (settings screen).
- **Stepper** (the "1 Upload · 2 AI Analysis · 3 Review" progress header).
- **Dropdown / Select** (the filter dropdowns on screens 3 & 12 — "Filter",
  "Risk", "Date"; and the top-bar account-menu chevron). A single themed
  select/menu primitive, screen-agnostic.
- **Data table** (`Table` / `DataTable`) — the dense history table on screen 12,
  with **sortable column headers**, **row-select / select-all checkboxes**, and a
  per-row **actions** slot. Built as a reusable, screen-agnostic primitive here;
  the concrete History *screen* (rows, real columns) is spec 017. This is the
  densest cross-screen pattern, so it belongs in the foundation, not a screen.
- **Chart wrappers**: `DonutChart`, `BarChart` (incl. grouped/2-series),
  `AreaChart`, `Heatmap`, and `GaugeChart` (radial progress — screen 3's
  portfolio-health gauges) — thin typed wrappers over the chosen chart lib (plan
  chooses; e.g. Recharts), pre-themed with token colors. These render
  **sample/placeholder data in this feature** (no live data source exists at the
  shell layer).

### 2.4 API-client seam (mock↔real swap point)

A single client module is the only place any screen reaches the backend. It
exposes typed methods mirroring 011's surface — `submitAnalysis(file,
recipient?)`, `getJob(jobId)`, `openJobEvents(jobId)` (SSE via `EventSource` /
`addEventListener` per 011 §2.4), `getReportUrl(jobId, format)`, `health()`.
It is backed by a **provider abstraction** with two implementations selected by
one config flag: a **mock provider** (static fixtures, for screens with no
backend and for isolated dev) and a **real provider** (fetch/EventSource against
the configured API base URL). Swapping mock→real for a given screen is a
one-place change (mirrors the single-seam registry pattern feature 011 built for
its own 012 swap; AC-21 there).

**Inputs to this seam (config):** the backend API base URL (default the local
011 server, `http://127.0.0.1:8000`) and the `mock | real` provider flag —
both environment-config, not hardcoded.

## 3. Acceptance criteria

Each is written to become a test/assertion directly (unit tests via the Next.js
test runner the plan selects; visual criteria are assertable via component
render + computed-style checks or a lightweight snapshot).

**Tokens**
- AC-1: A single token source defines every group in §2.2; both a CSS
  custom-property layer and the Tailwind theme resolve to the **same** values
  (no duplicated/divergent hex literals — a test asserts a primitive's computed
  color equals the token value, not a stray literal).
- AC-2: The three risk tokens map 1:1 onto the `RiskLevel` union (`low`,
  `medium`, `high`); rendering a risk badge for each level yields the matching
  `--risk-*` color. No "amber"/4th value exists in the type.
- AC-3: There is exactly one theme (dark). No light-theme tokens are shipped
  (out of scope, §5) — a token audit finds no light-mode duplication.

**App shell**
- AC-4: The sidebar renders the five nav items (Dashboard, Contracts, Reports,
  Integrations, Settings) with icon+label, and marks exactly one active based on
  the current route; navigating changes which item is active.
- AC-5: The sidebar renders a bottom user-profile block (avatar + name + role)
  from props/placeholder data (no auth/user backend is called — §5).
- AC-6: The top bar renders a page title, a right cluster (settings,
  notifications-with-dot, avatar), and an **optional** search slot that is
  present only when a screen supplies it (absent by default).
- AC-7: The App Router layout composes sidebar + top bar + content outlet; a
  placeholder route rendered inside the outlet shows the shell around it.

**Primitives**
- AC-8: Each primitive in §2.3 renders in its documented variants (e.g. button:
  primary-gradient / secondary / ghost / **chip**; input: text / password-with-
  toggle / search; **Tabs: segmented and underline**) and pulls all color/spacing
  from tokens (AC-1 audit applies).
- AC-9: The password input's show/hide toggle switches the field between masked
  and plain text and updates the eye icon.
- AC-10: The stepper renders N steps with exactly one "current", correct
  past/future styling, matching the "1 Upload · 2 AI Analysis · 3 Review"
  reference.
- AC-11: The five chart wrappers (`DonutChart`, `BarChart`, `AreaChart`,
  `Heatmap`, `GaugeChart`) render with sample data using the token chart palette
  (donut uses the risk colors; heatmap uses the yellow→red ramp; gauge renders a
  radial 0–100 progress arc). `BarChart` supports a grouped/2-series variant.
- AC-12: The risk-badge and status-badge components accept their label/level via
  props (status labels are not hardcoded to a fixed three). A separate
  **numeric-score pill** renders an arbitrary `n/100` value via props with no
  backend dependency (per the numeric-score note in §2.2).
- AC-12a: The **Dropdown/Select** primitive opens, lists options, fires a
  selection callback, and reflects the chosen value; it pulls all styling from
  tokens.
- AC-12b: The **Table/DataTable** primitive renders arbitrary columns+rows from
  props, toggles ascending/descending on a sortable header click, supports
  row-select and select-all checkboxes, and renders a per-row actions slot — all
  driven by props, with **no hardcoded reference-mockup strings** (EC-5).
- AC-12c: The **Avatar**, **ProgressBar**, and **ListRow** primitives each render
  from props: Avatar shows an image or an initials fallback at the given `size`
  (never a baked mockup name, EC-5); ProgressBar renders a determinate fill for a
  0–100 value (distinct from the discrete Stepper); ListRow renders a leading
  slot + title/subtitle + optional trailing slot. All colors/spacing from tokens.

**API-client seam**
- AC-13: The client exposes typed methods for all five 011 endpoints
  (`submitAnalysis`, `getJob`, `openJobEvents`, `getReportUrl`, `health`) whose
  TypeScript request/response types match the 011 §2 mirror table in §2.1.
- AC-14: Selecting the **mock** provider makes those methods resolve from static
  fixtures with **zero network calls** (asserted by a spy on fetch/EventSource);
  selecting **real** issues requests to the configured base URL.
- AC-15: Provider selection is a **single** config switch — a test swaps
  mock→real without editing any component, proving the seam is localized.
- AC-16: `openJobEvents` consumes SSE per 011 §2.4 — it dispatches on the named
  events (`progress` / `completed` / `failed`) and surfaces the terminal
  `final: JobStatus` payload.
- AC-17: The `JobState`, `RiskLevel`, and `MCPDeliveryStatus` TS unions are
  exact string-literal mirrors of the 001/011 enums (a type-level test / const
  assertion catches drift).

**Fidelity**
- AC-18: For at least the shell chrome (sidebar, top bar) and the primary
  button, a side-by-side check against the corresponding reference image shows
  matching color, corner radius, spacing, and typography within a small
  tolerance (the plan defines the exact tolerance and which reference image is
  the canonical source for each).

**Build / boundary**
- AC-19: The frontend builds (`next build`) and lints clean; no file under
  `backend/` is modified by this feature (structural check — frontend-only).
- AC-20: No component in this feature calls the backend for **live contract
  data** — the shell/primitives layer renders only placeholder/sample data
  (live data arrives with the feature screens in 014–018).

## 4. Edge cases

- **EC-1 — Backend unreachable (real provider):** the client seam surfaces a
  typed error state; since this feature ships no live-data screen, the failure
  path is exercised via the mock/real switch and a stubbed network error, not a
  real screen. Full user-facing error UI belongs to the screens that fetch
  (014–018).
- **EC-2 — SSE stream opened for an already-finished/unknown job:** the seam
  must not hang — it mirrors 011 EC-11/AC-11 semantics (immediate terminal event
  or 404 surfaced as a typed error). Verified against the mock provider here.
- **EC-3 — Dev-server origin vs. backend CORS allowlist:** feature 011 D7
  defaults its CORS allowlist to the **Vite** origin (`http://localhost:5173`),
  but the committed scaffold is **Next.js** (`next dev`, default `:3000`). A
  browser call from `:3000` to the API on `:8000` is cross-origin and will be
  blocked unless handled. This is a real integration seam — see Open Question
  Q4; the plan must resolve it (Next.js dev proxy/rewrite, or adding `:3000` to
  011's allowlist) and it does not silently "work".
- **EC-4 — Long/slow pipeline runs (constitution §9):** local-Ollama runs take
  minutes; any future data screen must lean on SSE progress, not a blocking
  request. The seam exposes SSE as a first-class method (AC-16) so screens are
  not tempted to poll-block. No wall-clock assumption is baked into the seam.
- **EC-5 — Placeholder/garbled reference text:** because mockup copy is not
  authoritative (§1), primitives must not hardcode any mockup string as
  semantic content; labels are props. A primitive that baked in "Sarah Jenkins"
  or "MSA_AcmeCorp_v2" as a literal would be a defect.
- **EC-6 — Reference screens depicting cut features:** the Integrations nav item
  and any auth/integration-card primitive must not, in this feature, wire to a
  non-existent or PERMANENTLY-CUT backend (Notion/Slack/Dropbox/auth). If those
  primitives are built at all (Q1/Q2), they render inert/placeholder only. No
  code path in this feature calls a cut integration.
- **EC-7 — Missing chart data:** chart wrappers render an empty/skeleton state
  rather than throwing when handed an empty dataset (they ship with sample data
  here, but must tolerate empty since real screens may load late).

## 5. Out of scope

- **All feature screens** — the actual Upload (screen 9), Processing (6),
  Analysis Workspace (7), Clause Chat (5), Comparison (8), Reports (11), History
  (12), Command-Center dashboard (10), Risk-analytics dashboard (3), Settings
  (4), Auth (2), Landing (1) views. Owned by the **later phased specs**:
  - **014** — auth + marketing (screens 1, 2)
  - **015** — upload + processing (screens 9, 6). *Note for 015:* screen 9's
    drag-drop shows a **TXT** file card, but IngestAgent + 011 fix
    `ALLOWED_EXTENSIONS = {.pdf, .docx}` (011 §6.1, AC-15 rejects `.txt` with
    `400`). 015 must not build a TXT path against a backend that rejects it.
  - **016** — analysis workspace + clause chat + comparison (screens 7, 5, 8)
  - **017** — reports + history (screens 11, 12)
  - **018** — dashboards / command center / settings (screens 10, 3, 4)
  This feature ships only the shell + tokens + primitives those screens consume.
- **Any live contract data rendering** — the design-system layer shows sample
  data only (AC-20). Real `JobStatus`/report/clause rendering is a screen
  concern (015–018).
- **Authentication / login / SSO / user accounts** — PERMANENTLY CUT
  (constitution §2; reaffirmed by 011 D1, no-auth localhost-only). Even though
  screens 1–2 show login + Google/Microsoft SSO, no auth is implemented. Whether
  the auth *form primitive* is even built is Q1.
- **Notion / Slack / Dropbox integrations** — PERMANENTLY CUT (constitution §2,
  "Slack, Notion, or any MCP integration beyond Drive + Gmail"). The only
  permitted integrations are Drive + Gmail (delivery, feature 010). See Q2.
- **Interactive clause chat, contract diff/comparison engine, persisted
  analytics/portfolio aggregates** — these have **no backend** (not built in
  001–012). Their *screens* are later specs and will render from the **mock
  provider**; the underlying backends are not in scope for any 013–018 frontend
  spec and would require their own backend features (out of the current phased
  plan). Flagged so later specs don't assume a data source that doesn't exist.
- **Chat message bubbles + composer, and the "Changes Summary" popover/modal** —
  the chat transcript UI (screens 5, 7) and the comparison popover (screen 8) are
  each used only within **spec 016** (workspace/chat/comparison), so they are
  **screen-local 016 components**, not 013 foundation primitives. Recorded here
  (not silently omitted) per the review; if 016 finds either is reused across
  screen groups, it may promote it back into the design system at that point.
- **Light theme / theming switcher** — one dark theme only (AC-3).
- **Backend changes** — no file under `backend/` is touched (AC-19). If the CORS
  allowlist needs `:3000` (EC-3/Q4), that is called out as a *backend* change to
  be made under 011's ownership, not silently here.
- **Internationalization, accessibility audit beyond basic semantics, and
  responsive/mobile layouts** — the mockups are desktop; a formal a11y/i18n/mobile
  pass is not in this foundation (may be revisited per Q5).

## 6. Open questions

These need your decision before this spec is final. I did not guess on anything
architecturally significant — especially the constitutional conflicts.

1. **Auth screens vs. PERMANENTLY CUT.** Screens 1 (Landing w/ Log In/Sign Up)
   and 2 (Login/Sign Up + Google/Microsoft SSO) depict authentication, which is
   PERMANENTLY CUT (constitution §2) and already fixed no-auth by 011 D1. Options:
   (a) **drop** the auth/landing screens from the frontend entirely (deviates
   from "pixel-exact all 12"); (b) build them as **inert visual-only** shells
   (forms render but submit nowhere / SSO buttons are decorative) purely to match
   the designs, with a clear "non-functional" note; (c) something else. Which?
   My recommendation: **(b)** for the *primitive* (a generic tabs/input/form
   primitive is reusable and not itself "auth"), and defer the decision on the
   actual login *screen* to spec 014. Confirm.

2. **Integrations UI (Notion/Slack/Dropbox) vs. PERMANENTLY CUT.** Screens 4 &
   11 show Notion/Slack cards and "Integrate with Notion"; screen 9 shows Dropbox
   "connect". All are cut — only **Drive + Gmail** are permitted (feature 010).
   Options: (a) build the Integrations screen later showing **only Drive +
   Gmail**, dropping the cut providers (honors the constitution, deviates from
   the image); (b) render the cut provider cards as **visually-present but
   permanently-disabled** ("not available") to match the mockup; (c) drop the
   Integrations screen concept. Which? My recommendation: **(a)** — the
   constitution outranks the mockup; the Integrations nav item stays, but its
   screen (spec 018) shows Drive + Gmail only. Confirm so I can scope the
   sidebar's "Integrations" item correctly now.

3. **Sidebar nav item set.** The reference images consistently show five items:
   Dashboard, Contracts, Reports, Integrations, Settings. Given Q1/Q2, do you
   want all five in the shell now (with Integrations scoped per Q2), or a reduced
   set? My recommendation: keep all five (they match the images and map to
   014–018), with Integrations meaning Drive+Gmail only.

4. **Next.js dev origin vs. 011 CORS allowlist (EC-3).** The scaffold is Next.js
   (`:3000`) but 011's CORS default is the Vite origin (`:5173`). Preferred fix:
   (a) a **Next.js dev rewrite/proxy** so the browser calls same-origin and no
   backend change is needed (keeps this feature backend-free per AC-19); (b) add
   `http://localhost:3000` to 011's CORS allowlist (a small, 011-owned backend
   change). My recommendation: **(a)** now, and optionally (b) later. Confirm.

5. **Chart library + fidelity tolerance.** For pixel-exact charts (donut, bar,
   area, heatmap) — any preference between a React charting lib (e.g. Recharts /
   visx) vs. hand-rolled SVG? And what fidelity tolerance is acceptable for AC-18
   (exact-to-the-pixel is impractical for anti-aliased text/gradients across
   machines)? My recommendation: Recharts for donut/bar/area, a small custom SVG
   grid for the heatmap; tolerance defined per-token (exact hex on fills, ~±2px
   on spacing). Confirm or override.

6. **Test runner / component-test approach.** The scaffold has no test setup.
   For the primitive/token/seam tests (AC-1…AC-20), preference between Vitest +
   React Testing Library vs. Jest vs. Playwright component tests? My
   recommendation: Vitest + React Testing Library (fast, TS-native), with the
   visual AC-18 check as a lightweight computed-style assertion rather than a
   full screenshot-diff harness in this foundation. Confirm.

7. **Numeric risk-score data source.** The "78/100" score pill (screens 7, 8,
   10, 11, 12) has **no backing field in 001** (only categorical `RiskLevel`
   exists). Is this number (a) a display-only value a screen derives locally from
   the categorical risk mix, (b) something you expect the backend to add later
   (which would be a 001 change under constitution §10, owned by a backend spec,
   NOT this frontend phase), or (c) mock-only for now? My recommendation: **(c)**
   mock-only in 013–018, and if a real score is wanted later it goes through a
   proper 001/backend spec — the frontend never invents a field. The design
   system ships only the pill primitive regardless. Confirm.

---

*No `plan.md`, `tasks.md`, or implementation was written in this pass — spec
only, per the constitution's spec-driven workflow (§1) and the spec-generation
instructions. A feature branch (`feature/013-frontend-design-system`,
constitution §11) may open only after this spec.md **and** a plan.md are
approved.*
