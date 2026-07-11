
# Frontend Design System + App Shell — Technical Plan

## Git Branch

`feature/013-frontend-design-system` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

This plan details how to implement the **frontend design system + app shell** specified in
`specs/013-frontend-design-system/spec.md`. It is the **first of a phased frontend rollout
(013–018)** and builds the *foundation only*: design tokens (extracted pixel-exact from the
12 reference images in `design-refs/`), the Next.js App Router **app shell** (sidebar + top
bar + layout), the **UI primitives** repeated across the mockups, and the **API-client
seam** that later screens use to reach the feature-011 FastAPI/SSE backend. **It ships no
feature screen** (upload, workspace, reports, dashboards) — those are 014–018 (spec §5).

**Boundary posture (constitution §2, §4).** The frontend sits entirely outside the
LangGraph StateGraph — it adds no node, no edge, and modifies **no file under `backend/`**
(spec AC-19). It is a pure HTTP/SSE *client* of the boundary feature 011 already defined.
It consumes 011's **Pydantic** boundary models as **TypeScript mirror types** and never
touches the internal `ContractState` `TypedDict` (spec §2.1). Constitution §11's git
workflow applies to this frontend feature exactly as to backend features.

**Constitutional conflicts — resolved by the spec's open-question decisions (§6 → below).**
The mockups depict several PERMANENTLY CUT features (auth/SSO; Notion/Slack/Dropbox). This
foundation builds **generic, inert primitives** where the *shape* is reusable and not itself
a cut feature, and it wires **no** code path to any cut backend (spec EC-6). The concrete
cut *screens* are decided in their owning specs (014/018).

### 1.1 Resolved open questions (spec §6 Q1–Q7) carried into this plan

The user approved the spec's recommended defaults. Recorded here so the implementation does
not re-litigate them:

- **Q1 — Auth: build the generic *form* primitive only; no auth.** A reusable
  `Tabs` + `TextInput` + `PasswordInput` + `Button` composition is built (not "auth"). The
  actual login/SSO *screen* is deferred to spec 014. Nothing in 013 authenticates, stores a
  credential, or calls an auth backend (auth is PERMANENTLY CUT; 011 D1 fixed no-auth).
- **Q2 — Integrations = Drive + Gmail only.** The "Integrations" nav item stays, but its
  future screen (018) shows only Drive + Gmail. **No** Notion/Slack/Dropbox card, provider,
  or "connect" affordance is built anywhere in 013 (constitution §2). The generic
  integration-*card* primitive is **not** built in this foundation (it has no permitted use
  yet); it is deferred to 018 where the Drive+Gmail-only screen lives.
- **Q3 — Sidebar keeps all five items:** Dashboard, Contracts, Reports, Integrations,
  Settings, with Integrations meaning Drive+Gmail only (Q2).
- **Q4 — CORS: Next.js dev rewrite/proxy.** The frontend calls **same-origin** relative
  paths (`/api/...`); `next.config.mjs` rewrites `/api/*` → `http://127.0.0.1:8000/api/*`
  in dev. This sidesteps the 011 `:5173`-vs-Next.js-`:3000` CORS mismatch (spec EC-3)
  **with zero backend change** (AC-19 preserved). A note is recorded for a future prod
  reverse-proxy; adding `:3000` to 011's allowlist stays an optional 011-owned change.
- **Q5 — Charts: Recharts for donut/bar/area/gauge; hand-rolled SVG heatmap.** Fidelity
  tolerance: **exact hex on fills/strokes** (from tokens), **±2px** on spacing/positioning
  for AC-18. Screenshot-diffing is out of scope for this foundation.
- **Q6 — Tests: Vitest + React Testing Library + jsdom.** AC-18's visual check is a
  lightweight `getComputedStyle` assertion against token values, not a pixel screenshot.
- **Q7 — Numeric "n/100" score: mock-only.** The `ScorePill` primitive renders an
  arbitrary `n/100` from props; **001 defines no numeric-score field**, so no real data
  source exists in 013–018. If a real score is ever wanted it goes through a proper
  001/backend spec (constitution §10) — the frontend never invents a field.

### 1.2 Stack decisions

| Concern | Choice | Rationale |
|---|---|---|
| Framework | **Next.js (App Router) + React + TypeScript** | The committed `frontend/package.json` already uses `next`; App Router gives file-based layout/routing for the shell (spec §2.3). |
| Styling | **Tailwind CSS v3 + CSS custom properties** | Single token source-of-truth (spec AC-1): CSS variables in `globals.css` are the canonical values; Tailwind's theme *references* those variables so utilities and raw CSS resolve to the **same** hex (no divergent literals). |
| Fonts | **Inter via `next/font/google`** | Matches the bold geometric-sans in the mockups; self-hosted by `next/font` (no runtime CDN, no layout shift). |
| Charts | **Recharts** (donut/bar/area/gauge) + **custom SVG** (heatmap) | Q5. Recharts is React-native and themeable via token colors; the heatmap grid is a trivial SVG and cheaper hand-rolled than bent out of a chart lib. |
| Tests | **Vitest + React Testing Library + jsdom** | Q6. Fast, TS-native, no separate Jest/Babel config; `@testing-library/jest-dom` matchers. |
| Icons | **lucide-react** | Clean line icons matching the mockups' nav/utility glyphs; tree-shakeable. |

---

## 2. Directory Structure (all NEW, all under `frontend/`)

```
frontend/
  package.json                 [MODIFY] add deps + scripts
  next.config.mjs              [NEW] dev proxy rewrite (Q4)
  tsconfig.json                [NEW] strict TS
  tailwind.config.ts           [NEW] theme references CSS vars
  postcss.config.mjs           [NEW]
  vitest.config.ts             [NEW]
  vitest.setup.ts              [NEW] jest-dom + jsdom shims
  .env.local.example           [NEW] documents the two env knobs
  src/
    app/
      layout.tsx               [NEW] root layout: fonts, globals, <AppShell>
      globals.css              [NEW] CSS custom properties = the tokens (canonical)
      page.tsx                 [NEW] redirect '/' → '/dashboard' (placeholder)
      dashboard/page.tsx       [NEW] placeholder route (shell demo)
      contracts/page.tsx       [NEW] placeholder route
      reports/page.tsx         [NEW] placeholder route
      integrations/page.tsx    [NEW] placeholder route
      settings/page.tsx        [NEW] placeholder route
    components/
      shell/  AppShell, Sidebar, SidebarNavItem, TopBar, UserProfileBlock
      ui/     Button, Card, Avatar, RiskBadge, StatusBadge, ScorePill, ProgressBar,
              ListRow, TextInput, PasswordInput, SearchInput, Tabs, Toggle, Stepper,
              Dropdown, DataTable
      charts/ DonutChart, BarChart, AreaChart, Heatmap, GaugeChart
    lib/
      api/    types.ts, client.ts, provider.ts, mockProvider.ts,
              realProvider.ts, fixtures.ts
      config.ts               [NEW] reads env: API base + provider flag
      tokens.ts               [NEW] TS mirror of chart-relevant token hex (for Recharts props)
    __tests__/                 colocated test files (see §5)
```

No file outside `frontend/` is created or modified (spec AC-19). `frontend/src/` currently
holds only the empty scaffold; this feature populates it.

---

## 3. Files to Create / Modify

### 3.1 `[MODIFY] frontend/package.json`

Replace the `latest` pins with concrete ranges and add the deps + scripts. Representative:

```jsonc
{
  "name": "contractsentinel-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "next": "^14.2.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "recharts": "^2.12.0",
    "lucide-react": "^0.400.0",
    "clsx": "^2.1.0"
  },
  "devDependencies": {
    "typescript": "^5.4.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@types/node": "^20.12.0",
    "tailwindcss": "^3.4.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "vitest": "^1.6.0",
    "@vitejs/plugin-react": "^4.3.0",
    "jsdom": "^24.0.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/dom": "^10.1.0",
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/user-event": "^14.5.0",
    "eslint": "^8.57.0",
    "eslint-config-next": "^14.2.0"
  }
}
```

`clsx` for conditional class composition. React 18 (Next 14 App Router). No state library —
the foundation has no cross-screen state; screens add their own later.

### 3.2 `[NEW] frontend/next.config.mjs` — dev proxy (Q4, spec EC-3)

```js
/** @type {import('next').NextConfig} */
const API_ORIGIN = process.env.API_PROXY_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Dev: browser calls same-origin /api/* ; Next proxies to the 011 backend,
    // so no cross-origin request is made and 011's CORS allowlist (:5173) is moot.
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};
export default nextConfig;
```

Because the browser only ever hits `/api/...` on its own origin, SSE (`EventSource`) and
`fetch` both work in dev with **no** backend change. Prod deployment uses a real reverse
proxy or the optional 011 allowlist addition (recorded for later, not built here).

### 3.3 `[NEW] frontend/src/app/globals.css` — the canonical tokens (spec §2.2, AC-1/AC-3)

The **single source of truth**. Exact hex values color-committed from the reference images
(dark-navy surfaces, violet→blue accent, risk red/amber/green). One `:root`; **one dark
theme only** (AC-3 — no light-mode block).

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  /* ── Surfaces (dark navy) ── */
  --bg-app:          #0A0B12;
  --bg-sidebar:      #0C0E16;
  --bg-card:         #141824;
  --bg-card-raised:  #1B2030;
  --border-subtle:   #242A3A;

  /* ── Brand accent (violet → blue) ── */
  --accent:              #7C6CF5;
  --accent-gradient-from:#7A5CFF;
  --accent-gradient-to:  #5B8DEF;
  --accent-fg:           #FFFFFF;
  --border-focus:        #7C6CF5;

  /* ── Risk scale — maps 1:1 to 001 RiskLevel (AC-2). "Amber" == medium (spec §2.2). ── */
  --risk-high:   #EF4444;   /* RiskLevel.HIGH   */
  --risk-medium: #F59E0B;   /* RiskLevel.MEDIUM (a.k.a. "Amber") */
  --risk-low:    #22C55E;   /* RiskLevel.LOW    */

  /* ── Text ── */
  --text-primary:   #F5F6FA;
  --text-secondary: #9AA3B2;
  --text-tertiary:  #5C6472;

  /* ── Radius / spacing base / elevation ── */
  --radius-card: 14px;
  --radius-input: 10px;
  --radius-pill: 9999px;
  --space-unit: 4px;               /* spacing scale is multiples of this */
  --glow-accent: 0 0 0 1px rgba(124,108,245,.35), 0 8px 40px -8px rgba(124,108,245,.45);

  /* ── Chart palette (derived from the above; consumed by tokens.ts for Recharts) ── */
  --chart-bar-1: var(--accent);
  --chart-bar-2: var(--accent-gradient-to);
  --chart-area-from: rgba(124,108,245,.55);
  --chart-area-to:   rgba(124,108,245,.02);
  --heat-0: #FEF3C7;  --heat-1: #FCD34D;  --heat-2: #F59E0B;
  --heat-3: #F97316;  --heat-4: #EF4444;
}

body { background: var(--bg-app); color: var(--text-primary); }
```

> **Exact-hex discipline (AC-1).** These CSS variables are the ONLY place a hex literal
> appears. Tailwind (§3.4) and `tokens.ts` (§3.11) both *reference* these variables — no
> component hardcodes a color. The token-audit test (§5, `test_no_hardcoded_hex`) greps
> `src/components` for `#[0-9a-fA-F]{3,6}` and fails on any hit outside `globals.css`/
> `tokens.ts`.

### 3.4 `[NEW] frontend/tailwind.config.ts` — theme references the CSS vars

```ts
import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        app: "var(--bg-app)",
        sidebar: "var(--bg-sidebar)",
        card: "var(--bg-card)",
        "card-raised": "var(--bg-card-raised)",
        subtle: "var(--border-subtle)",
        accent: "var(--accent)",
        "accent-fg": "var(--accent-fg)",
        "risk-high": "var(--risk-high)",
        "risk-medium": "var(--risk-medium)",
        "risk-low": "var(--risk-low)",
        "text-primary": "var(--text-primary)",
        "text-secondary": "var(--text-secondary)",
        "text-tertiary": "var(--text-tertiary)",
      },
      borderRadius: {
        card: "var(--radius-card)", input: "var(--radius-input)", pill: "var(--radius-pill)",
      },
      backgroundImage: {
        "accent-gradient":
          "linear-gradient(90deg, var(--accent-gradient-from), var(--accent-gradient-to))",
      },
      boxShadow: { glow: "var(--glow-accent)" },
      fontFamily: { sans: ["var(--font-inter)", "system-ui", "sans-serif"] },
      fontSize: {   /* scale from the mockups */
        display: ["3.5rem", { lineHeight: "1.05", fontWeight: "800", letterSpacing: "-0.02em" }],
        "page-title": ["2.375rem", { lineHeight: "1.1", fontWeight: "700", letterSpacing: "-0.01em" }], // in-app page heading (screens 10/11) — between display and h1
        h1: ["2rem", { lineHeight: "1.15", fontWeight: "700" }],
        h2: ["1.5rem", { lineHeight: "1.2", fontWeight: "700" }],
        h3: ["1.125rem", { lineHeight: "1.3", fontWeight: "600" }],
        body: ["0.9375rem", { lineHeight: "1.5" }],
        small: ["0.8125rem", { lineHeight: "1.4" }],
        caption: ["0.6875rem", { lineHeight: "1.3" }],
      },
    },
  },
  plugins: [],
};
export default config;
```

### 3.5 `[NEW] frontend/src/app/layout.tsx` — root layout + shell (spec §2.3, AC-7)

```tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AppShell } from "@/components/shell/AppShell";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
export const metadata: Metadata = { title: "ContractSentinel" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
```

### 3.6 `[NEW] frontend/src/components/shell/` — the app shell

**`AppShell.tsx`** composes `<Sidebar/>` + `<TopBar/>` + a content outlet (children):

```tsx
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-app text-text-primary">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <TopBar />
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}
```

**`Sidebar.tsx`** — logo (gradient "C" + wordmark), the five `SidebarNavItem`s, and a
bottom `UserProfileBlock`. Nav model is data-driven so 014–018 don't rebuild it:

```tsx
import { LayoutDashboard, FileText, BarChart3, Plug, Settings } from "lucide-react";
export const NAV_ITEMS = [
  { href: "/dashboard",    label: "Dashboard",    icon: LayoutDashboard },
  { href: "/contracts",    label: "Contracts",    icon: FileText },
  { href: "/reports",      label: "Reports",      icon: BarChart3 },
  { href: "/integrations", label: "Integrations", icon: Plug, expandable: true }, // Q3/N-1
  { href: "/settings",     label: "Settings",     icon: Settings },
] as const;
```

**`SidebarNavItem.tsx`** — marks active via `usePathname()` (active = route matches
`href`); renders the icon+label row with the violet active-highlight, and supports the
optional **expandable** chevron variant (spec §2.3 / review N-1) as a visual affordance
(no submenu content in 013). **`UserProfileBlock.tsx`** — avatar + name + role from
**props/placeholder** (no auth backend; spec AC-5, EC-5): defaults render a placeholder,
never a hardcoded mockup name baked into the component.

**`TopBar.tsx`** — page title (prop), an **optional** `search` slot (rendered only when a
screen passes one; spec AC-6, present on screens 10/11/12), and the right cluster: settings
gear, notifications bell **with unread dot**, avatar/account chevron (a `Dropdown` trigger).

### 3.7 `[NEW] frontend/src/components/ui/` — primitives (spec §2.3, AC-8…AC-12b)

Each is token-driven (no hardcoded color), variant-prop based, and label/data via props
(spec EC-5 forbids baking mockup strings). Key contracts:

- **`Button.tsx`** — `variant: "primary" | "secondary" | "ghost" | "chip"`. Primary uses
  `bg-accent-gradient text-accent-fg`; secondary is outline (`border-subtle`); ghost/icon
  is transparent; **chip** is a small `rounded-pill` action (the suggestion chips on
  screens 5/6/7). `disabled` supported (used by 018 for inert cut-provider states, Q2).
- **`Card.tsx`** — `bg-card border border-subtle rounded-card`; `glow?: boolean` adds
  `shadow-glow` (the violet active-card glow).
- **`Avatar.tsx`** — circular image with **initials fallback** when no `src`; `size` prop
  (sm/md/lg — the 96px settings avatar vs the 28px top-bar one). Never bakes a mockup name
  (spec EC-5). Reused by `UserProfileBlock`, `TopBar`, and later chat/activity rows.
- **`ProgressBar.tsx`** — determinate horizontal bar; `value: number` (0–100). Distinct
  from `Stepper`. 015/016 wire it to SSE `index`/`total` (011 §2.4). Track =
  `bg-card-raised`, fill = `bg-accent-gradient`.
- **`ListRow.tsx`** — generic row: `leading?` slot (icon/colored dot/avatar), `title`,
  `subtitle?`, `trailing?` slot (badge/timestamp). Underlies the Activity Feed +
  Notifications lists (screens 10/11). Props-driven; no baked strings.
- **`RiskBadge.tsx`** — `level: RiskLevel` (`"low"|"medium"|"high"` from `types.ts`) → pill
  colored by `--risk-*`. Exactly three levels (AC-2); no "amber" value (it's medium).
- **`StatusBadge.tsx`** — `label: string` + `tone` prop; **labels are NOT hardcoded** to
  Analysed/Redlined/Needs Review (screen-12's real set is spec 017; AC-12).
- **`ScorePill.tsx`** — `value: number` → renders `` `${value}/100` `` with a tone ramp;
  **no backend field** (Q7/N-4). Purely presentational.
- **`TextInput` / `PasswordInput` / `SearchInput`** — themed inputs; `PasswordInput` has a
  show/hide **eye toggle** switching `type` between `password`/`text` and swapping the icon
  (spec AC-9).
- **`Tabs.tsx`** — `variant: "segmented" | "underline"` (`items`, `value`, `onChange`):
  segmented = the Login/Sign-Up pill (screen 2); underline = Profile/Billing/… (screen 4)
  and Chat/Active (screen 7). Generic — not "auth" (Q1).
- **`Toggle.tsx`** — controlled switch (`checked`, `onChange`) — settings toggles.
- **`Stepper.tsx`** — `steps: string[]`, `current: number`; exactly one current, correct
  past/future styling ("1 Upload · 2 AI Analysis · 3 Review"; AC-10).
- **`Dropdown.tsx`** — generic select/menu (`options`, `value`, `onSelect`); the filter
  dropdowns (screens 3/12) and the top-bar account menu (AC-12a).
- **`DataTable.tsx`** — generic table: `columns: {key,header,sortable?,render?}[]`,
  `rows: T[]`, sortable-header click toggles asc/desc, row-select + select-all checkboxes,
  per-row `actions` render slot (AC-12b). All from props — no mockup strings baked in. The
  concrete History columns are spec 017.

### 3.8 `[NEW] frontend/src/components/charts/` — chart wrappers (spec §2.3, AC-11)

Thin typed wrappers over Recharts (+ custom SVG heatmap), pre-themed from `tokens.ts`
(§3.11). Each accepts data via props and **renders an empty/skeleton state on empty data**
(spec EC-7). Inventory: `DonutChart` (risk colors), `BarChart` (single + **grouped/2-series**
variant, review B-3), `AreaChart` (violet gradient fill), `Heatmap` (SVG grid, yellow→red
ramp), `GaugeChart` (radial 0–100 progress arc — the screen-3 portfolio-health gauges,
review B-3). In 013 they render **sample/placeholder data only** — no live source exists at
the shell layer (spec AC-20).

### 3.9 `[NEW] frontend/src/lib/api/types.ts` — the 011/001 mirror types (spec §2.1)

Exact TypeScript mirrors of feature 011 §2 and 001's enums. These are the single typed
contract every later screen imports. **Field-for-field with 011 §2.3** (review B-1) and
`final` **terminal-only** (review B-2):

```ts
// Mirrors 001 RiskLevel (lines 65–68) — exactly three levels.
export type RiskLevel = "low" | "medium" | "high";
// Mirrors 001 MCPDeliveryStatus (lines 70–73).
export type MCPDeliveryStatus = "pending" | "success" | "failed";
// Mirrors 001 MCPDeliveryInfo (lines 75–78).
export interface MCPDeliveryInfo {
  status: MCPDeliveryStatus;
  error_message?: string | null;
  delivered_at?: string | null;
}
// Mirrors 011 §2.3 JobState.
export type JobState = "queued" | "running" | "completed" | "failed";
export interface ErrorInfo { kind: string; message: string; }   // 011 ErrorInfo

// Mirrors 011 §2.2 AnalyzeAccepted.
export interface AnalyzeAccepted { job_id: string; status: JobState; submitted_at: string; }

// Mirrors 011 §2.3 JobStatus — ALL nine fields, verbatim (review B-1).
export interface JobStatus {
  job_id: string;
  status: JobState;
  current_node?: string | null;
  completed_nodes: string[];
  submitted_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  report_available: boolean;
  mcp_delivery_status: Record<string, MCPDeliveryInfo>;
  error?: ErrorInfo | null;
}

// Mirrors 011 §2.4 ProgressEvent. `final` present ONLY on terminal events (review B-2).
export type SseEventName = "progress" | "completed" | "failed";
export interface ProgressEvent {
  event: SseEventName;
  job_id: string;
  node?: string | null;
  index?: number | null;
  total?: number | null;
  elapsed_seconds?: number | null;
  final?: JobStatus | null;   // only on "completed" | "failed"
}
```

> **Drift lock (spec AC-17).** A test asserts the union string sets equal the 001/011 enums
> (`JobState`, `RiskLevel`, `MCPDeliveryStatus`) via `const` tuples, so a future contract
> change that isn't mirrored fails compilation/test.

### 3.10 `[NEW] frontend/src/lib/api/` — the client seam (spec §2.4, AC-13…AC-16)

**`client.ts`** defines the interface every screen uses (the *only* backend surface):

```ts
export interface ApiClient {
  submitAnalysis(file: File, recipient?: string): Promise<AnalyzeAccepted>;
  getJob(jobId: string): Promise<JobStatus>;
  openJobEvents(jobId: string, handlers: {
    onProgress?: (e: ProgressEvent) => void;
    onTerminal?: (e: ProgressEvent) => void;   // completed|failed, carries final
    onError?: (err: unknown) => void;
  }): () => void;                                // returns an unsubscribe fn
  getReportUrl(jobId: string, format: "md" | "json"): string;
  health(): Promise<{ status: string }>;
}
```

**`realProvider.ts`** — implements `ApiClient` against the configured base URL:
`fetch` for the JSON/multipart endpoints, and `EventSource` for `openJobEvents`, dispatching
on the **named** SSE events via `addEventListener("progress"|"completed"|"failed", …)`
(011 §2.4; spec AC-16). It maps all five 011 endpoints (`POST /api/analyze`,
`GET /api/jobs/{id}`, `GET /api/jobs/{id}/events`, `GET /api/jobs/{id}/report`,
`GET /api/health`). Base URL defaults to `""` (same-origin → hits the Next dev proxy, Q4).

**`mockProvider.ts`** — implements the same interface from `fixtures.ts` with **zero
network calls** (spec AC-14): `submitAnalysis` returns a canned `AnalyzeAccepted`; `getJob`
returns a scripted `JobStatus`; `openJobEvents` emits a scripted `progress…→completed`
sequence via `setTimeout` and honors unsubscribe; an "already-finished/unknown job" path
emits an immediate terminal or a typed error (spec EC-2). No hang.

**`provider.ts`** — the **single switch** (spec AC-15): reads `config.ts` and returns the
mock or real singleton. Swapping a screen mock↔real is this one flag — no component edit.

```ts
import { getConfig } from "@/lib/config";
export function getApiClient(): ApiClient {
  return getConfig().provider === "mock" ? mockClient : realClient;
}
```

### 3.11 `[NEW] frontend/src/lib/config.ts` and `tokens.ts`

**`config.ts`** — the two env knobs (spec §2.4), no hardcoding:

```ts
export interface AppConfig { apiBaseUrl: string; provider: "mock" | "real"; }
export function getConfig(): AppConfig {
  return {
    apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "",       // "" = same-origin (dev proxy)
    provider: (process.env.NEXT_PUBLIC_API_PROVIDER as "mock" | "real") ?? "mock",
  };
}
```

`.env.local.example` documents both. Default `provider="mock"` so the shell/primitives run
with no backend (spec AC-20). **`tokens.ts`** re-exports the chart-relevant hex by reading
the CSS variables at runtime (`getComputedStyle(document.documentElement)`) with a static
fallback map for SSR/tests — so Recharts receives real color strings while `globals.css`
stays the single source (§3.3).

### 3.12 `[NEW] placeholder routes` (`src/app/*/page.tsx`)

`dashboard/`, `contracts/`, `reports/`, `integrations/`, `settings/` each export a minimal
placeholder page (a `<Card>` naming the route) so the shell renders around real routes and
active-nav switching is demonstrable (spec AC-4/AC-7). `page.tsx` at root redirects `'/'` →
`'/dashboard'`. **No feature content** — screens are 014–018.

---

## 4. Config / Test Infra Files

- **`tsconfig.json`** — `strict: true`, `"@/*": ["./src/*"]` path alias, `jsx: preserve`,
  Next.js `next-env.d.ts` types.
- **`vitest.config.ts`** — `@vitejs/plugin-react`, `environment: "jsdom"`,
  `setupFiles: ["./vitest.setup.ts"]`, the same `@/` alias.
- **`vitest.setup.ts`** — imports `@testing-library/jest-dom`; stubs `EventSource` and
  `matchMedia` for jsdom (Recharts/`ResizeObserver` shim too).
- **`.env.local.example`** — `NEXT_PUBLIC_API_BASE_URL=`, `NEXT_PUBLIC_API_PROVIDER=mock`,
  `API_PROXY_ORIGIN=http://127.0.0.1:8000`.

---

## 5. Tests (Vitest + RTL) mapped to acceptance criteria

Every AC in spec §3 gets at least one test. Files colocated under `src/__tests__/`.

#### `tokens.test.ts` (spec AC-1, AC-2, AC-3)
| Test | Verifies |
|---|---|
| `test_single_token_source` | A primitive's `getComputedStyle` color equals the `--token` value, not a stray literal (AC-1) |
| `test_no_hardcoded_hex` | Grep `src/components` for `#[0-9a-fA-F]{3,6}` → zero hits outside `globals.css`/`tokens.ts` (AC-1) |
| `test_risk_tokens_map_to_levels` | `RiskBadge` for `low/medium/high` yields `--risk-low/medium/high`; no 4th value (AC-2) |
| `test_single_dark_theme` | No light-theme token block / `.light` selector exists (AC-3) |

#### `shell.test.tsx` (spec AC-4…AC-7)
| Test | Verifies |
|---|---|
| `test_sidebar_five_items` | Renders Dashboard/Contracts/Reports/Integrations/Settings with icon+label (AC-4) |
| `test_active_item_by_route` | Mocked `usePathname` marks exactly one active; changing route changes it (AC-4) |
| `test_integrations_expandable_variant` | The Integrations item renders the chevron affordance (N-1) |
| `test_user_profile_block` | Bottom block renders avatar+name+role from props; no auth call (AC-5) |
| `test_topbar_slots` | Title + right cluster (settings/bell-with-dot/avatar) render; search absent by default, present when supplied (AC-6) |
| `test_layout_composes_outlet` | A placeholder child renders inside the shell (AC-7) |

#### `primitives.test.tsx` (spec AC-8…AC-12b)
| Test | Verifies |
|---|---|
| `test_button_variants` | primary-gradient / secondary / ghost render; disabled works; colors from tokens (AC-8) |
| `test_password_toggle` | Eye toggle flips `type` password↔text and swaps icon (AC-9) |
| `test_stepper_current` | N steps, exactly one current, correct past/future styling (AC-10) |
| `test_charts_render_sample` | Donut/Bar/Area/Heatmap/Gauge render with sample data + token palette (AC-11) |
| `test_bar_grouped_variant` | `BarChart` renders a 2-series grouped variant (B-3) |
| `test_badges_props_driven` | RiskBadge(level) + StatusBadge(label) + ScorePill(value) render from props; status labels not hardcoded (AC-12) |
| `test_dropdown_select` | Dropdown opens, lists options, fires `onSelect`, reflects value (AC-12a) |
| `test_datatable` | Renders columns/rows from props; header click toggles sort; row-select + select-all; actions slot (AC-12b) |
| `test_no_baked_mockup_strings` | No primitive hardcodes "Sarah Jenkins"/"MSA_AcmeCorp" etc. (EC-5) |
| `test_charts_empty_state` | Empty dataset → skeleton/empty, no throw (EC-7) |

#### `api-client.test.ts` (spec AC-13…AC-17, EC-1/EC-2)
| Test | Verifies |
|---|---|
| `test_client_exposes_five_endpoints` | `submitAnalysis/getJob/openJobEvents/getReportUrl/health` exist with the mirror types (AC-13) |
| `test_mock_provider_no_network` | Mock methods resolve from fixtures with a fetch/EventSource spy asserting **zero** calls (AC-14) |
| `test_real_provider_hits_base_url` | Real methods issue requests to the configured base URL (AC-14) |
| `test_single_provider_switch` | Flipping the config flag swaps mock→real with no component edit (AC-15) |
| `test_sse_named_events` | `openJobEvents` dispatches on `progress`/`completed`/`failed` and surfaces terminal `final: JobStatus` (AC-16) |
| `test_sse_finished_or_unknown_no_hang` | Already-finished/unknown job → immediate terminal or typed error, never hangs (EC-2) |
| `test_enum_mirrors_exact` | `JobState`/`RiskLevel`/`MCPDeliveryStatus` const tuples equal the 001/011 enum sets (AC-17) |
| `test_backend_unreachable_typed_error` | Real provider + stubbed network error → typed error state, not a throw-through (EC-1) |

#### Build / boundary (spec AC-18…AC-20)
| Test | Verifies |
|---|---|
| `fidelity.test.tsx` | Shell chrome + primary button computed color/radius/spacing/font match the canonical reference token values within tolerance (exact hex, ±2px) (AC-18) |
| `test_next_build` (CI script) | `next build` + `next lint` succeed clean (AC-19) |
| `test_no_backend_edits` (CI/structural) | `git diff --name-only` touches no path under `backend/` (AC-19) |
| `test_shell_no_live_fetch` | Rendering the shell/primitives triggers **no** ApiClient call for live data (default mock, sample data only) (AC-20) |

---

## 6. Implementation Order (TDD where practical — constitution §7)

1. **Scaffold + config** — `package.json`, `tsconfig`, `tailwind.config`, `postcss`,
   `next.config.mjs` (dev proxy), `vitest.config` + setup, `.env.local.example`. Confirm
   `next build` and an empty `vitest run` are green. (Gates everything.)
2. **Tokens** — `globals.css` (canonical hex) + Tailwind theme + `tokens.ts`. Write
   `tokens.test.ts` first (red), implement to green (AC-1/2/3).
3. **API seam** — `types.ts` (mirrors), `client.ts`, `provider.ts`, `mock`/`real`
   providers, `fixtures.ts`, `config.ts`. `api-client.test.ts` first → green
   (AC-13…AC-17, EC-1/2). Independent of any component, so it can proceed in parallel
   with step 4.
4. **Primitives** — `Button`, `Card`, `RiskBadge`, `StatusBadge`, `ScorePill`, inputs,
   `Tabs`, `Toggle`, `Stepper`, `Dropdown`, `DataTable`, then charts. `primitives.test.tsx`
   per component (red→green; AC-8…AC-12b, EC-5/7).
5. **App shell** — `Sidebar`/`SidebarNavItem`/`UserProfileBlock`/`TopBar`/`AppShell`,
   `layout.tsx`, placeholder routes. `shell.test.tsx` (AC-4…AC-7).
6. **Fidelity + boundary** — `fidelity.test.tsx` (AC-18), the no-backend-edits / no-live-
   fetch checks (AC-19/20), final `next build` + `next lint`.

Each step's tests are written and confirmed **failing** before its implementation
(constitution §7); a post-impl failure fixes the code, never the test.

---

## 7. Notes for later phased specs (out of this feature's scope)

- **015 (upload):** screen 9 shows a **TXT** card, but IngestAgent/011 fix
  `ALLOWED_EXTENSIONS = {.pdf,.docx}` (011 §6.1, AC-15 → `400` on `.txt`). Do not build a
  TXT upload path (spec §5 note).
- **017/018 numeric score:** the `ScorePill` has no 001 field (Q7). Any real number needs a
  001/backend spec first (constitution §10) — screens render it from mock until then.
- **018 integrations:** Drive + Gmail only (Q2). Cut providers (Notion/Slack/Dropbox) are
  never built; if the mockup card is matched visually it is a permanently-disabled inert
  element with no backend.
- **CORS in prod (Q4):** the dev proxy is dev-only; production needs a real reverse proxy or
  the optional 011 allowlist addition (an 011-owned backend change, not a 013 concern).
- **016 screen-local components (deferred, not omitted — review):** the **chat message
  bubble + composer** (screens 5, 7) and the **"Changes Summary" popover/modal** (screen 8)
  are each used only within spec 016, so they are built there as screen-local components,
  not 013 foundation primitives. If 016 finds either reused across screen groups it may
  promote it into the design system at that point. (Avatar, ProgressBar, ListRow, and the
  chip Button variant, by contrast, span ≥2 screen specs and ARE 013 primitives.)

---

*Per constitution §1, a `feature/013-frontend-design-system` branch may open only after this
plan.md and its spec.md are approved and `tasks.md` exists. No `tasks.md` or implementation
was written in this pass — plan only.*
