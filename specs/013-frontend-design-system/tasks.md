# Frontend Design System + App Shell — Implementation Tasks

Reference documents:
- Spec: `specs/013-frontend-design-system/spec.md`
- Plan: `specs/013-frontend-design-system/plan.md`
- API contract consumed: `specs/011-pipeline-runner-api/spec.md` §2
- State schema (enum source): `specs/001-contract-state-schema.md`
- Constitution: `specs/000-constitution.md`
- Design references (pixel-exact target): `specs/013-frontend-design-system/design-refs/*.jpeg`

All file paths below are relative to `frontend/` unless stated otherwise.

**Workflow reminders:**
- Follow TDD per constitution §7 — write tests, confirm they FAIL, then implement to make them PASS. Never weaken a test to force a pass.
- This feature is the **frontend foundation only**: design tokens, app shell, UI primitives, and the API-client seam. It ships **NO feature screen** (no upload, workspace, reports, dashboards) — those are specs 014–018.
- **NO backend change.** Do not create or modify any file under `backend/` (spec AC-19). The frontend is a pure HTTP/SSE client of the feature-011 API. If you feel the need to touch the backend (e.g. CORS), STOP — the Next.js dev proxy (Task 1) handles it instead.
- **Pixel-exact fidelity is the mandate.** The literal text in the mockups is placeholder/garbled — do NOT copy it. Extract layout, color, spacing, typography, component shapes. Never hardcode a mockup string (e.g. "Sarah Jenkins", "MSA_AcmeCorp") into a component — everything is props (spec EC-5).
- **One token source of truth (spec AC-1).** Hex literals live ONLY in `src/app/globals.css` (and the fallback map in `src/lib/tokens.ts`). Every component pulls color via a Tailwind class or CSS variable — never an inline hex. A test greps for stray hex and fails on any.
- **Consume 011's contract exactly (spec §2.1).** The TypeScript types in `src/lib/api/types.ts` mirror feature 011 §2 field-for-field and 001's enums. Do not invent divergent field names.
- **Cut features are NOT built (constitution §2).** No auth/login/SSO logic, no Notion/Slack/Dropbox provider/card/connect. Integrations = Drive + Gmail only (decided; built in spec 018, not here).

**The seven locked decisions (spec §6 Q1–Q7, plan §1.1):**
- **Q1** — auth: generic form primitives only (Tabs/inputs/button); no auth; login screen is spec 014.
- **Q2** — Integrations = Drive+Gmail only; no Notion/Slack/Dropbox anywhere; integration-card primitive deferred to 018.
- **Q3** — sidebar keeps all five items (Dashboard, Contracts, Reports, Integrations, Settings).
- **Q4** — CORS solved by Next.js dev proxy (`/api/*` → `http://127.0.0.1:8000`); zero backend change.
- **Q5** — charts: Recharts (donut/bar/area/gauge) + hand-rolled SVG heatmap; exact hex, ±2px tolerance.
- **Q6** — tests: Vitest + React Testing Library + jsdom.
- **Q7** — numeric `n/100` ScorePill is mock-only; no 001 field invented.
- Branch: `feature/013-frontend-design-system` per constitution §11.

---

## Task 0: Create feature branch

- [ ] Confirm `spec.md`, `plan.md`, and this `tasks.md` all exist and are approved (constitution §1 / §11 gate).
- [ ] From an up-to-date `main`, create and check out `feature/013-frontend-design-system` (the `git-start` skill does this mechanically).

**Why**: Constitution §11 — every feature (frontend included) is developed on its own branch off latest `main`.

**Verify**: `git branch --show-current` prints `feature/013-frontend-design-system`.

**Note**: The working tree has untracked `specs/013-frontend-design-system/`. Confirm with the user whether to commit the spec docs before branching so the feature starts from a clean tree (same as prior features).

---

## Task 1: Scaffold the frontend toolchain (GATING — do first)

Everything else depends on the build + test toolchain existing. No app code yet.

- [ ] **`[MODIFY] package.json`** — replace the `latest` pins with the concrete deps + scripts from plan §3.1 (Next 14, React 18, TypeScript 5, Tailwind 3, Recharts, lucide-react, clsx; devDeps: vitest, @vitejs/plugin-react, jsdom, @testing-library/{react,dom,jest-dom,user-event}, eslint-config-next). Add scripts: `dev`, `build`, `start`, `lint`, `test` (`vitest run`), `test:watch` (`vitest`).
- [ ] **`[NEW] tsconfig.json`** — `strict: true`, `jsx: "preserve"`, `moduleResolution: "bundler"`, path alias `"@/*": ["./src/*"]`, include Next types. (Next generates `next-env.d.ts` on first build.)
- [ ] **`[NEW] next.config.mjs`** — the dev proxy rewrite from plan §3.2 (`/api/:path*` → `${API_PROXY_ORIGIN ?? "http://127.0.0.1:8000"}/api/:path*`), `reactStrictMode: true`.
- [ ] **`[NEW] tailwind.config.ts`** — the config from plan §3.4 (content globs `./src/**/*.{ts,tsx}`; colors/radius/gradient/shadow/font all reference CSS variables; the fontSize scale).
- [ ] **`[NEW] postcss.config.mjs`** — `{ plugins: { tailwindcss: {}, autoprefixer: {} } }`.
- [ ] **`[NEW] vitest.config.ts`** — `@vitejs/plugin-react`, `test.environment: "jsdom"`, `test.globals: true`, `setupFiles: ["./vitest.setup.ts"]`, and the same `@/` alias as tsconfig.
- [ ] **`[NEW] vitest.setup.ts`** — `import "@testing-library/jest-dom"`; add jsdom shims used by Recharts/components: stub `ResizeObserver`, `matchMedia`, and a minimal `EventSource` (a class capturing listeners) so `src/lib/api` tests can drive SSE.
- [ ] **`[NEW] .env.local.example`** — document `NEXT_PUBLIC_API_BASE_URL=`, `NEXT_PUBLIC_API_PROVIDER=mock`, `API_PROXY_ORIGIN=http://127.0.0.1:8000`.
- [ ] Install deps (`npm install` from `frontend/`).

**Why**: Gates all tests and the build (spec AC-19). The dev proxy (Q4) is what lets the browser reach the 011 backend same-origin without any backend CORS change.

**Verify**:
- `npm run build` — a bare Next build succeeds (even with no pages yet Next needs an `app/` dir; if it complains, add the minimal `src/app/layout.tsx` + `page.tsx` stubs from Task 14 early, or a temporary `app/page.tsx` returning `null`).
- `npm run test` — `vitest run` exits 0 with "no test files" (toolchain wired).

---

## Task 2: Write the token tests (confirm FAILING)

- [ ] **`[NEW] src/__tests__/tokens.test.tsx`** — add these tests (per spec AC-1/2/3, plan §5):

```tsx
import { render, screen } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { RiskBadge } from "@/components/ui/RiskBadge";

describe("design tokens", () => {
  test("no_hardcoded_hex", () => {
    // Hex literals may appear ONLY in globals.css and tokens.ts (spec AC-1).
    const dir = path.join(process.cwd(), "src/components");
    const files: string[] = [];
    const walk = (d: string) => fs.readdirSync(d, { withFileTypes: true }).forEach((e) => {
      const p = path.join(d, e.name);
      e.isDirectory() ? walk(p) : files.push(p);
    });
    walk(dir);
    const offenders = files.filter((f) => /#[0-9a-fA-F]{3,6}\b/.test(fs.readFileSync(f, "utf8")));
    expect(offenders).toEqual([]);
  });

  test("risk_tokens_map_to_levels", () => {
    // RiskBadge for each level uses the matching --risk-* variable, not a literal (AC-2).
    (["low", "medium", "high"] as const).forEach((level) => {
      const { unmount } = render(<RiskBadge level={level} />);
      const el = screen.getByTestId(`risk-badge-${level}`);
      // class-based assertion: the badge carries the token-backed class for its level
      expect(el.className).toMatch(new RegExp(`risk-${level}`));
      unmount();
    });
  });

  test("single_dark_theme", () => {
    // Exactly one theme: no light-mode selector/block (AC-3).
    const css = fs.readFileSync(path.join(process.cwd(), "src/app/globals.css"), "utf8");
    expect(css).not.toMatch(/\.light\b|prefers-color-scheme:\s*light|\[data-theme=.light.\]/);
  });
});
```

**Verify**: `npm run test` — these FAIL (missing `globals.css` / `RiskBadge`). That is expected.

---

## Task 3: Implement the tokens

- [ ] **`[NEW] src/app/globals.css`** — exactly the canonical token set from plan §3.3 (one `:root` with surfaces, accent, risk scale mapped 1:1 to `RiskLevel`, text, radius/spacing/glow, chart palette; `@tailwind` directives; body defaults). Hex literals live ONLY here. **No light-theme block.**
- [ ] **`[NEW] src/lib/tokens.ts`** — per plan §3.11: read chart-relevant CSS variables at runtime via `getComputedStyle(document.documentElement)` with a static fallback hex map (for SSR/tests) so Recharts gets real color strings. This file is the ONE other place hex may appear (the fallback map).
- [ ] Ensure `tailwind.config.ts` (Task 1) already maps the semantic classes (`bg-card`, `text-text-primary`, `risk-high/medium/low`, `bg-accent-gradient`, `shadow-glow`, etc.) to the variables.

**Why**: Single source of truth (spec AC-1). Tailwind + tokens.ts reference the variables so utilities, raw CSS, and charts all resolve to the same hex.

**Verify**: The `no_hardcoded_hex` and `single_dark_theme` tests PASS. `risk_tokens_map_to_levels` still fails until `RiskBadge` exists (Task 8) — that is fine; it is re-run there.

---

## Task 4: Write the API-seam tests (confirm FAILING)

- [ ] **`[NEW] src/__tests__/api-client.test.ts`** — per spec AC-13…AC-17, EC-1/EC-2, plan §5. Include at minimum:

```ts
import { getApiClient } from "@/lib/api/provider";
import { mockClient } from "@/lib/api/mockProvider";
import { realClient } from "@/lib/api/realProvider";

const RISK = ["low", "medium", "high"] as const;
const JOBSTATE = ["queued", "running", "completed", "failed"] as const;
const DELIVERY = ["pending", "success", "failed"] as const;

describe("api seam", () => {
  test("enum_mirrors_exact", () => {
    // AC-17: unions equal the 001/011 enum sets. Import const tuples from types.
    // (assert via a const-tuple defined alongside the type — see types.ts)
    const { JOB_STATES, RISK_LEVELS, DELIVERY_STATES } = require("@/lib/api/types");
    expect([...JOB_STATES].sort()).toEqual([...JOBSTATE].sort());
    expect([...RISK_LEVELS].sort()).toEqual([...RISK].sort());
    expect([...DELIVERY_STATES].sort()).toEqual([...DELIVERY].sort());
  });

  test("client_exposes_five_endpoints", () => {
    const c = mockClient;
    ["submitAnalysis", "getJob", "openJobEvents", "getReportUrl", "health"]
      .forEach((m) => expect(typeof (c as any)[m]).toBe("function"));
  });

  test("mock_provider_no_network", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    await mockClient.getJob("job-1");
    await mockClient.health();
    expect(fetchSpy).not.toHaveBeenCalled();   // AC-14: zero network from mock
  });

  test("single_provider_switch", () => {
    // AC-15: flipping the config flag swaps the returned client, no component edit.
    vi.stubEnv("NEXT_PUBLIC_API_PROVIDER", "mock");
    expect(getApiClient()).toBe(mockClient);
    vi.stubEnv("NEXT_PUBLIC_API_PROVIDER", "real");
    expect(getApiClient()).toBe(realClient);
  });

  test("sse_named_events_and_terminal", async () => {
    // AC-16: onProgress fires for progress; onTerminal fires with final: JobStatus.
    const events: string[] = [];
    let terminalFinal: any = null;
    const stop = mockClient.openJobEvents("job-1", {
      onProgress: (e) => events.push(e.event),
      onTerminal: (e) => { terminalFinal = e.final; },
    });
    await vi.waitFor(() => expect(terminalFinal).not.toBeNull());
    expect(events).toContain("progress");
    expect(terminalFinal.status).toBe("completed");
    stop();
  });

  test("sse_finished_or_unknown_no_hang", async () => {
    // EC-2: an already-finished/unknown job emits an immediate terminal or typed error, no hang.
    let done = false;
    mockClient.openJobEvents("unknown", { onTerminal: () => { done = true; }, onError: () => { done = true; } });
    await vi.waitFor(() => expect(done).toBe(true));
  });
});
```

Add a `realProvider` test that spies on `fetch`/`EventSource` and asserts a call to the configured base URL (AC-14 real path), and a `backend_unreachable_typed_error` test (EC-1) where a rejected `fetch` surfaces a typed error rather than throwing through.

**Verify**: `npm run test` — these FAIL (missing modules).

---

## Task 5: Implement the API mirror types

- [ ] **`[NEW] src/lib/api/types.ts`** — exactly the mirror types from plan §3.9 (RiskLevel, MCPDeliveryStatus, MCPDeliveryInfo, JobState, ErrorInfo, AnalyzeAccepted, **JobStatus with all nine fields**, ProgressEvent with `final` terminal-only). 
- [ ] Also export const tuples used by the drift-lock test: `export const JOB_STATES = ["queued","running","completed","failed"] as const;` and likewise `RISK_LEVELS`, `DELIVERY_STATES`. Define each type as `(typeof X)[number]` so the tuple and the type cannot drift.

**Why**: Spec §2.1 / AC-17 — the single typed contract; field-for-field with 011 §2 (review B-1) and `final` present only on terminal events (review B-2).

**Verify**: `enum_mirrors_exact` PASSES. TypeScript compiles (`npx tsc --noEmit`).

---

## Task 6: Implement the API client seam (mock + real)

- [ ] **`[NEW] src/lib/config.ts`** — `getConfig()` reading `NEXT_PUBLIC_API_BASE_URL` (default `""` = same-origin) and `NEXT_PUBLIC_API_PROVIDER` (default `"mock"`), per plan §3.11.
- [ ] **`[NEW] src/lib/api/client.ts`** — the `ApiClient` interface from plan §3.10 (submitAnalysis/getJob/openJobEvents/getReportUrl/health; `openJobEvents` takes handler callbacks and returns an unsubscribe fn).
- [ ] **`[NEW] src/lib/api/fixtures.ts`** — static `AnalyzeAccepted`, a scripted `JobStatus` (status `completed`, `report_available: true`, a couple `completed_nodes`), and a scripted event sequence (`progress` ×N → `completed` carrying `final`). No mockup strings as semantic data.
- [ ] **`[NEW] src/lib/api/mockProvider.ts`** — `mockClient: ApiClient` from fixtures with **zero** network calls (spec AC-14). `openJobEvents` emits the scripted sequence via `setTimeout`, honors unsubscribe, and for an unknown/finished job emits an immediate terminal (or `onError`) — no hang (EC-2).
- [ ] **`[NEW] src/lib/api/realProvider.ts`** — `realClient: ApiClient` mapping all five 011 endpoints: `fetch` for JSON/multipart (`POST /api/analyze` builds `FormData`), `EventSource` for `openJobEvents` using `addEventListener("progress"|"completed"|"failed", …)` (011 §2.4), `getReportUrl` returns `` `${base}/api/jobs/${id}/report?format=${fmt}` ``. Wrap `fetch` errors into a typed error (EC-1). Base URL from `getConfig().apiBaseUrl`.
- [ ] **`[NEW] src/lib/api/provider.ts`** — `getApiClient()` returning `mockClient` or `realClient` per the config flag (spec AC-15, the single seam).

**Why**: Spec §2.4 — one place every screen reaches the backend; mock↔real is a one-flag swap (mirrors 011's single-seam registry pattern).

**Verify**: All `api-client.test.ts` tests PASS. `npx tsc --noEmit` clean.

---

## Task 7: Write primitive tests — Part A (confirm FAILING)

- [ ] **`[NEW] src/__tests__/primitives.test.tsx`** — Part A covers Button, Card, Avatar, RiskBadge, StatusBadge, ScorePill, ProgressBar, ListRow, TextInput, PasswordInput, SearchInput (spec AC-8, AC-9, AC-12, AC-12c, EC-5). Include:
  - `button_variants`: renders `primary`/`secondary`/`ghost`/**`chip`**; `disabled` sets the disabled attribute; primary carries the `bg-accent-gradient` class and chip carries `rounded-pill` (token-driven) (AC-8).
  - `password_toggle`: clicking the eye toggles input `type` password↔text and swaps the icon (spec AC-9); use `@testing-library/user-event`.
  - `badges_props_driven`: `RiskBadge` renders per level with `data-testid="risk-badge-<level>"`; `StatusBadge` renders an arbitrary `label` (NOT hardcoded to Analysed/Redlined/Needs Review); `ScorePill` renders `` `${value}/100` `` from a numeric prop (AC-12, Q7).
  - `avatar_fallback`: `Avatar` with no `src` renders the initials fallback; with `src` renders an `img`; honors `size` (AC-12c, EC-5 — no baked name).
  - `progressbar_value`: `ProgressBar value={35}` renders a fill at ~35% width (assert the style/aria-valuenow); distinct from Stepper (AC-12c).
  - `listrow_slots`: `ListRow` renders leading + title/subtitle + trailing slots from props (AC-12c).
  - `no_baked_mockup_strings`: grep the `ui/` components for `/Sarah Jenkins|MSA_AcmeCorp|AcmeCorp/` → zero (spec EC-5).

**Verify**: FAIL (components missing). Re-run `tokens.test.tsx::risk_tokens_map_to_levels` — still failing until Task 8.

---

## Task 8: Implement primitives — Part A

- [ ] **`[NEW] src/components/ui/Button.tsx`** — `variant: "primary"|"secondary"|"ghost"|"chip"`, `disabled`. Primary = `bg-accent-gradient text-accent-fg`; secondary = outline `border border-subtle`; ghost = transparent icon button; **chip** = small `rounded-pill` `bg-card-raised` action (screens 5/6/7 suggestion chips). Use `clsx`.
- [ ] **`[NEW] src/components/ui/Card.tsx`** — `bg-card border border-subtle rounded-card`; optional `glow` → `shadow-glow`.
- [ ] **`[NEW] src/components/ui/Avatar.tsx`** — circular; `src?`, `name` (for initials fallback + alt), `size?: "sm"|"md"|"lg"`. Renders `img` when `src` given, else initials from `name` on an accent-tinted circle. Never hardcodes a name (spec EC-5).
- [ ] **`[NEW] src/components/ui/ProgressBar.tsx`** — `value: number` (0–100); track `bg-card-raised rounded-pill`, fill `bg-accent-gradient` at `${value}%`; ARIA `role="progressbar"` + `aria-valuenow`. Distinct from Stepper.
- [ ] **`[NEW] src/components/ui/ListRow.tsx`** — props `leading?`, `title`, `subtitle?`, `trailing?`; row layout used by Activity Feed + Notifications (screens 10/11). Props-driven only.
- [ ] **`[NEW] src/components/ui/RiskBadge.tsx`** — `level: RiskLevel`; pill with class `risk-<level>` mapping to `bg-risk-<level>` (token). `data-testid={`risk-badge-${level}`}`.
- [ ] **`[NEW] src/components/ui/StatusBadge.tsx`** — `label: string`, `tone?: "neutral"|"success"|"warning"|"danger"`. Labels via props only.
- [ ] **`[NEW] src/components/ui/ScorePill.tsx`** — `value: number` → `` `${value}/100` ``; presentational tone ramp; no backend dependency (Q7).
- [ ] **`[NEW] src/components/ui/TextInput.tsx`, `PasswordInput.tsx`, `SearchInput.tsx`** — themed inputs (`bg-card-raised`, `rounded-input`, `border-subtle`, focus `border-focus`). `PasswordInput` has the eye show/hide toggle (spec AC-9) using a lucide `Eye`/`EyeOff` icon.

**Why**: Spec §2.3 — reusable, token-driven, props-based primitives (spec AC-8/9/12, EC-5).

**Verify**: Part A of `primitives.test.tsx` and `tokens.test.tsx::risk_tokens_map_to_levels` PASS.

---

## Task 9: Write primitive tests — Part B (confirm FAILING)

- [ ] Extend **`src/__tests__/primitives.test.tsx`** for Tabs, Toggle, Stepper, Dropdown, DataTable (spec AC-10, AC-12a, AC-12b):
  - `stepper_current`: `steps=["Upload","AI Analysis","Review"]`, `current=1` → exactly one current, correct past/future classes (AC-10).
  - `tabs`: renders items, calls `onChange` on click, reflects `value`; renders **both** `variant="segmented"` (screen 2) and `variant="underline"` (screens 4/7) with the correct active styling per variant.
  - `toggle`: controlled `checked`/`onChange` flips.
  - `dropdown_select`: opens, lists options, fires `onSelect`, reflects the chosen value (AC-12a).
  - `datatable`: renders columns/rows from props; clicking a sortable header toggles asc/desc order; row-select + select-all checkboxes toggle; a per-row `actions` slot renders (AC-12b).

**Verify**: FAIL (components missing).

---

## Task 10: Implement primitives — Part B

- [ ] **`[NEW] src/components/ui/Tabs.tsx`** — `variant: "segmented"|"underline"` (`items`, `value`, `onChange`): segmented = pill (Login/Sign-Up, screen 2); underline = active tab underlined (Profile/Billing/…, screen 4; Chat/Active, screen 7). Generic — not "auth" (Q1).
- [ ] **`[NEW] src/components/ui/Toggle.tsx`** — controlled switch.
- [ ] **`[NEW] src/components/ui/Stepper.tsx`** — `steps: string[]`, `current: number`; exactly one current, past/future styling (spec AC-10).
- [ ] **`[NEW] src/components/ui/Dropdown.tsx`** — generic select/menu (`options`, `value`, `onSelect`); used for filters + the top-bar account menu (spec AC-12a).
- [ ] **`[NEW] src/components/ui/DataTable.tsx`** — generic table: `columns: {key,header,sortable?,render?}[]`, `rows: T[]`, sortable-header toggle, row-select + select-all, per-row `actions` render slot (spec AC-12b). All props-driven; no baked strings.

**Verify**: Part B tests PASS. `no_hardcoded_hex` still PASS (no literals leaked).

---

## Task 11: Write chart-wrapper tests (confirm FAILING)

- [ ] **`[NEW] src/__tests__/charts.test.tsx`** — spec AC-11, EC-7, review B-3:
  - `charts_render_sample`: `DonutChart`, `BarChart`, `AreaChart`, `Heatmap`, `GaugeChart` each render with sample data without throwing; assert a container/`svg` is present.
  - `bar_grouped_variant`: `BarChart` renders a 2-series grouped variant (screen 3).
  - `gauge_renders_radial`: `GaugeChart` with `value=70` renders a radial arc (screen-3 portfolio-health gauge).
  - `charts_empty_state`: each chart handed an empty dataset renders a skeleton/empty state, no throw (spec EC-7).

**Note for jsdom**: Recharts needs a sized container; the `ResizeObserver` shim from Task 1 plus wrapping in a fixed-size `div` (or Recharts `<ResponsiveContainer>` with an explicit width/height in tests) makes these deterministic.

**Verify**: FAIL (components missing).

---

## Task 12: Implement chart wrappers

- [ ] **`[NEW] src/components/charts/DonutChart.tsx`** — Recharts `PieChart` donut; colors from `tokens.ts` (risk colors for the risk-distribution donut).
- [ ] **`[NEW] src/components/charts/BarChart.tsx`** — Recharts `BarChart`; single + grouped/2-series variant (`--chart-bar-1`/`--chart-bar-2`).
- [ ] **`[NEW] src/components/charts/AreaChart.tsx`** — Recharts `AreaChart` with the violet gradient fill (`--chart-area-from`→`--chart-area-to`).
- [ ] **`[NEW] src/components/charts/Heatmap.tsx`** — hand-rolled SVG grid; cell fill from the `--heat-0..4` ramp by value bucket (screen-3 clause-category heatmap).
- [ ] **`[NEW] src/components/charts/GaugeChart.tsx`** — radial 0–100 progress arc (Recharts `RadialBarChart` or SVG arc); accent fill (screen-3 portfolio-health gauge).
- [ ] Each renders an empty/skeleton state on empty data (spec EC-7) and uses **sample data only** in this feature (spec AC-20).
- [ ] **No hex literal in `src/components/charts/*`** — every chart color comes from a `tokens.ts` import (which holds the fallback map), NOT an inline `fill="#..."`. The `no_hardcoded_hex` audit (Task 2) scans `src/components` and will fail on any inline chart hex — so pass token strings, never literals (spec AC-1).

**Why**: Spec §2.3 / AC-11 — the five chart primitives 018/017 inherit, pre-themed from tokens. Gauge + grouped-bar are the review B-3 additions.

**Verify**: `charts.test.tsx` PASSES.

---

## Task 13: Write app-shell tests (confirm FAILING)

- [ ] **`[NEW] src/__tests__/shell.test.tsx`** — spec AC-4…AC-7, review N-1. Mock `next/navigation`'s `usePathname`. Include:
  - `sidebar_five_items`: renders Dashboard/Contracts/Reports/Integrations/Settings with icon+label (AC-4).
  - `active_item_by_route`: with `usePathname` → `/reports`, exactly the Reports item has the active class; switching the mock to `/dashboard` moves it (AC-4).
  - `integrations_expandable_variant`: the Integrations item renders the chevron affordance (N-1).
  - `user_profile_block`: bottom block renders avatar+name+role from props; no ApiClient/auth call (AC-5).
  - `topbar_slots`: title + right cluster (settings, bell-with-dot, avatar) render; search absent by default, present when a `search` prop/slot is supplied (AC-6).
  - `layout_composes_outlet`: a placeholder child renders inside the shell (AC-7).

**Verify**: FAIL (components missing).

---

## Task 14: Implement the app shell + layout + placeholder routes

- [ ] **`[NEW] src/components/shell/Sidebar.tsx`** — logo (gradient "C" + wordmark), the `NAV_ITEMS` array from plan §3.6 (five items; Integrations `expandable: true`), maps to `SidebarNavItem`, and renders `UserProfileBlock` pinned bottom.
- [ ] **`[NEW] src/components/shell/SidebarNavItem.tsx`** — icon+label row; active via `usePathname()` matching `href` → violet active-highlight; optional expandable chevron variant (visual only in 013, no submenu).
- [ ] **`[NEW] src/components/shell/UserProfileBlock.tsx`** — avatar+name+role from props with placeholder defaults (no auth backend; spec AC-5, EC-5).
- [ ] **`[NEW] src/components/shell/TopBar.tsx`** — page title (prop), optional `search` slot (spec AC-6), right cluster (settings gear, notifications bell with unread dot, avatar/account `Dropdown`).
- [ ] **`[NEW] src/components/shell/AppShell.tsx`** — composes `Sidebar` + `TopBar` + `<main>` content outlet (plan §3.6).
- [ ] **`[NEW] src/app/layout.tsx`** — root layout: Inter via `next/font` (sets `--font-inter`), imports `globals.css`, wraps children in `<AppShell>` (plan §3.5).
- [ ] **`[NEW] src/app/page.tsx`** — redirect `'/'` → `'/dashboard'`.
- [ ] **`[NEW] src/app/{dashboard,contracts,reports,integrations,settings}/page.tsx`** — each a minimal placeholder `<Card>` naming the route (NO feature content; screens are 014–018).

**Why**: Spec §2.3 / AC-4…AC-7 — the shell every later screen sits in; routes registered so active-nav switching is demonstrable.

**Verify**: `shell.test.tsx` PASSES. `npm run dev` renders the shell with the five nav items and switchable active state.

---

## Task 15: Fidelity + boundary tests

- [ ] **`[NEW] src/__tests__/fidelity.test.tsx`** (spec AC-18) — render the sidebar chrome, top bar, and a primary `Button`; assert `getComputedStyle` color/border-radius/font-family match the canonical token values, and spacing within ±2px (Q5 tolerance). Use the token values as the source of truth (not a screenshot).
- [ ] **`[NEW] src/__tests__/boundary.test.tsx`** (spec AC-20) — render the shell + a placeholder route with the default (`mock`) provider and assert the ApiClient's methods are **not** called for live data (spy on `getApiClient()` methods → zero calls). The shell/primitives show only sample/placeholder data.
- [ ] **No-backend-edits check (spec AC-19)** — add a CI/script assertion (or a documented manual step) that `git diff --name-only origin/main...HEAD` lists no path under `backend/`.

**Verify**: `fidelity.test.tsx` and `boundary.test.tsx` PASS.

---

## Task 16: Full verification pass

- [ ] `npm run test` — the entire Vitest suite is GREEN (tokens, api-client, primitives A+B, charts, shell, fidelity, boundary).
- [ ] `npx tsc --noEmit` — no type errors (the mirror types compile; drift-lock holds).
- [ ] `npm run lint` — `next lint` clean.
- [ ] `npm run build` — `next build` succeeds.
- [ ] `git diff --name-only` — confirm **no** file under `backend/` was touched (spec AC-19).
- [ ] Manual pixel check: run `npm run dev`, open each placeholder route, and compare the shell chrome (sidebar, top bar, primary button, card, risk badges, stepper, a sample of each chart) side-by-side against the corresponding `design-refs/*.jpeg` — colors/radius/spacing/typography match within tolerance (spec AC-18). Note any deviation before merge.

**Why**: Confirms every acceptance criterion in spec §3 (AC-1…AC-20, AC-12a/12b) is met and the boundary rules hold.

---

## Task 17: Finish the feature branch

- [ ] Ensure the full suite passes and the build is clean (Task 16).
- [ ] Rebase/merge latest `main` into the branch, resolve any conflicts on the branch (constitution §11), then merge to `main` and delete the branch (the `git-finish` skill does this mechanically).

**Why**: Constitution §11 — a feature branch merges to `main` only once its tests pass; conflicts are resolved on the branch, never on `main`; the branch is deleted after a clean merge.

**Verify**: `git branch --show-current` prints `main`; `feature/013-frontend-design-system` is gone; the Vitest suite + `next build` pass on `main`.

---

*Per constitution §1/§11, implementation happens only on `feature/013-frontend-design-system`, opened after spec.md + plan.md + this tasks.md are approved. Later phased specs (014–018) build the actual feature screens on this foundation; forward-notes for them live in plan §7.*
