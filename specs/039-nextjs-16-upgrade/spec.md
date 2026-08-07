# Feature 039 — Next.js 14 → 16 Upgrade (security remediation)

## Problem statement

The `dependency-audit` CI workflow (Security Tier 2, item 7) gates the build on
**production** dependency vulnerabilities at high/critical severity. After the
safe non-breaking bumps landed, the workflow is green on `npm ci` and the backend
audit but still **red at the audit gate**, failing on exactly two production
high-severity advisories:

- **`next`** (the app's framework) — a high-severity advisory in `next@14.2.x`.
- **`postcss`** — a high-severity advisory pulled in transitively **through
  `next`** (`node_modules/next/node_modules/postcss`).

`npm` reports the fix for both as **`next@16.3.0`** (`npm audit fix --force` →
"Will install next@16.3.0, which is a breaking change"). There is no non-breaking
fix; both advisories are resolved only by upgrading Next.js to a patched major.
This feature performs that upgrade so the production-only audit reports **zero**
high/critical findings and the CI gate goes green.

Place in the architecture: this is **frontend-only** and touches **no** part of
the fixed pipeline. Per constitution §2 it adds/removes **no** LangGraph node or
edge, and per §4/§10 it changes **no** `ContractState` field, no backend, no API
contract, and no database. It is a framework/dependency maintenance upgrade of
the Next.js App Router frontend delivered in the 013–024 frontend phase. It is
not in the PHASE 2 DEFERRED or PERMANENTLY CUT lists.

**SCOPE CORRECTION (implementation finding, 2026-08-07; owner-approved):** The
original premise that "Next.js 16 requires React 19" is **false** —
`next@16`'s peer dependency is `react: "^18.2.0 || ^19.0.0"`, i.e. React 18.3 is
supported. Verified empirically: `next@16.3.0` on React 18.3 builds cleanly, `tsc`
passes, and the production `npm audit` reports **0** vulnerabilities (both `next`
and `postcss` cleared). The owner chose the **minimal path: upgrade Next only and
stay on React 18.3**, which fully achieves the security goal at the lowest risk.
Therefore React `19`, `@types/react(-dom)@19`, and the `recharts`/`lucide-react`
React-19 bumps are **NOT part of this feature** (no security benefit, added risk).
What IS in scope: `next 14→16`, `eslint-config-next 14→16` (which requires
ESLint 9 + flat config), and the async-`params` migration. All React-19-specific
acceptance criteria / edge cases below are read as "N/A — React stays 18.3." The
app is a **pure App Router** application (`src/pages/` contains only `.gitkeep`),
keeping the breaking-change surface small.

## Inputs and outputs

This feature does **not** read or write any `ContractState`
(`001-contract-state-schema.md`) field — it is orthogonal to the graph state.
Stated explicitly to satisfy §10: **no 001 change is required or made.** Inputs
and outputs are frontend build-system artifacts and source only.

### Inputs (current state)
- `frontend/package.json` — `next ^14.2.0`, `react ^18.3.0`, `react-dom ^18.3.0`,
  `eslint-config-next ^14.2.0`, plus `@types/react*`, `recharts ^2.12.0`,
  `lucide-react ^0.400.0`, `@testing-library/react ^16.0.0`, `vitest ^1.6.0`,
  `jsdom ^24.0.0`, `typescript ^5.4.0`.
- `frontend/package-lock.json` (must stay **npm 10-compatible** — CI runs Node 20
  / npm 10; regenerate with npm 10, per the lesson recorded in feature 038's CI
  fix).
- `frontend/next.config.mjs` — `reactStrictMode: true` and the dev-proxy
  `rewrites()` mapping `/api/:path*` → `API_PROXY_ORIGIN` (default
  `http://127.0.0.1:8000`). This proxy is what the `NEXT_PUBLIC_API_PROVIDER=real`
  provider seam relies on in dev.
- Source under `frontend/src/` — 2 server-component pages using synchronous
  `params`; 38 `"use client"` components; `src/middleware.ts` using
  `NextRequest`/`NextResponse`; the 45 Vitest test files (242 tests).

### Outputs (post-upgrade)
- `package.json` / `package-lock.json` with `next@16.x`, `react@19`,
  `react-dom@19`, `@types/react@19`, `@types/react-dom@19`,
  `eslint-config-next@16` (+ any third-party bump required for React-19 compat),
  lockfile regenerated with npm 10.
- Migrated source: the 2 dynamic-route pages made `async` with `await params`; the
  `lint` script migrated if `next lint` is removed in 16; any React-19 breaking
  API usages fixed. No functional/visual change to any screen.
- A dependency-audit run in which the production-only gate reports **0**
  high/critical for `next` and `postcss`.

## Acceptance criteria

Each is specific and testable.

- **AC-1 (vuln cleared — the goal).** After the upgrade,
  `npm audit --omit=dev --json` in `frontend/` reports **0** advisories at
  `high` or `critical` severity for `next` and for `postcss`. (The production gate
  in `backend/scripts/security_audit.py` returns 0 production findings for the
  frontend.)
- **AC-2 (CI gate green).** A `dependency-audit` workflow run on the upgrade
  branch completes with the **"Run dependency audit" step succeeding** (job
  conclusion `success`), given the backend is already clean. The whole workflow
  (checkout → uv sync → npm ci → audit) is green.
- **AC-3 (build).** `npm run build` (`next build`) completes successfully with no
  errors, producing a production build.
- **AC-4 (types).** `npx tsc --noEmit` passes with **0** errors under React 19
  types (`@types/react@19`).
- **AC-5 (tests).** `npm test` (`vitest run`) passes **all 242 tests across 45
  files** (or the same count minus any test that must legitimately change for a
  React-19/RTL API change, which must be explicitly justified — tests are never
  weakened to force a pass, constitution §7).
- **AC-6 (async params migrated).** `src/app/jobs/[jobId]/page.tsx` and
  `src/app/jobs/[jobId]/report/page.tsx` type `params` as a `Promise` and `await`
  it (or use `React.use(params)`); navigating to `/jobs/{id}` and
  `/jobs/{id}/report` renders the ProcessingView/ReportView for the correct
  `jobId` with no runtime error or console warning about sync params access.
- **AC-7 (dev-proxy seam intact).** With `NEXT_PUBLIC_API_PROVIDER=real` and the
  backend on `:8000`, a browser request to a same-origin `/api/*` path is proxied
  to the backend (the `rewrites()` still applies) — i.e. login/upload/report
  round-trips succeed against the real backend, unchanged from pre-upgrade.
- **AC-8 (middleware intact).** `src/middleware.ts` still compiles and runs:
  the PUBLIC_ROUTES gate, the authenticated→dashboard bounce, and the recovery-
  route handling behave exactly as before (the existing `middleware.test.ts`
  passes unchanged).
- **AC-9 (lint runs).** `npm run lint` still runs successfully. If `next lint` is
  removed/changed in Next 16, the `lint` script is migrated to the supported
  replacement (ESLint CLI with `eslint-config-next@16`) and produces no new
  errors.
- **AC-10 (no behavior/visual regression).** The existing screens (landing, auth,
  upload, processing, report/workspace, dashboard, contracts/history, settings,
  integrations) render and behave the same as before the upgrade — verified by the
  full Vitest+RTL suite (AC-5) plus a manual/real smoke pass on the live app.
- **AC-11 (no backend/graph/state change).** No file under `backend/`,
  `specs/001`, or the graph builder changes; the diff is confined to
  `frontend/` (deps, config, and the minimal source migrations above).
- **AC-12 (lockfile CI-compatible).** `npm ci` exits 0 under **both** npm 10
  (CI's version) and the local npm — the lockfile is regenerated with npm 10 so
  the audit workflow's `npm ci` step does not regress.

## Edge cases

- **React 19 removed/changed APIs.** React 19 removes legacy APIs (e.g.
  `ReactDOM.render`/`hydrate` legacy signatures, string refs, `propTypes`/
  `defaultProps` on function components, `React.createFactory`) and changes ref
  handling (ref-as-prop; `forwardRef` no longer required). If any of the 38
  client components or a shared util relies on a removed/changed API, `tsc` or a
  test will fail; each such site is migrated (not suppressed). The React 19
  codemods (`npx types-react-codemod`, `npx @next/codemod`) may be used.
- **Third-party React-19 compatibility.** `recharts ^2.12` (charts),
  `lucide-react ^0.400` (icons), and `@testing-library/react ^16` (tests) must
  support React 19. RTL 16 already does. If `recharts`/`lucide-react` peer-warn or
  break under React 19, bump them to a React-19-compatible version; if none
  exists for a library, that is a blocking Open Question (do not ship a broken
  chart). The 4 chart components (Donut/Gauge/Bar/Heatmap) and the risk donut on
  the report must still render.
- **`next lint` removal (Next 16).** Next 16 removes the built-in `next lint`
  command. `npm run lint` would then fail. Migrate the script to the ESLint CLI
  (`eslint .`) with `eslint-config-next@16`, or the officially documented path
  (AC-9). Do not silently drop linting.
- **Async `params`/`searchParams` beyond the two known pages.** The grounded scan
  found only the two dynamic-route pages using sync `params`. If `next build`/the
  Next 16 type-checker flags any additional sync `params`/`searchParams` (or a
  layout) access, migrate it too. `cookies()`/`headers()` from `next/headers` are
  **not** used server-side (already confirmed), so that class of breakage does not
  apply.
- **Caching-default change (Next 15+).** `fetch()` and route handlers are no
  longer cached by default. Data is fetched **client-side** via the provider seam
  (browser `fetch` through the dev proxy), so server-side caching changes should
  have no functional impact; verify the report/dashboard still show fresh data and
  that nothing relied on implicit server caching.
- **Empty `src/pages/.gitkeep`.** A stray empty `pages/` dir is harmless but may
  cause a Next warning about mixed routers; remove `src/pages/` (keeping App
  Router only) if it warns, or leave it if silent. Non-blocking.
- **Node version floor.** Next 16 raises the minimum Node version (≥ 20.9). CI
  uses Node 20 — confirm the exact minor satisfies Next 16's floor; if not, bump
  the workflow's `node-version`. Document the required local Node version.
- **Test-environment stack.** `vitest ^1.6` + `jsdom ^24` + RTL 16 must run React
  19 render/act correctly. If React 19's `act`/concurrent changes surface flaky or
  failing tests, fix the test setup (e.g. RTL/`@testing-library/dom` bump) rather
  than weakening assertions. (Note: dev-tooling advisories for `vitest`/`vite` are
  **not** part of this feature — see Out of scope.)
- **npm 10 vs 11 lockfile drift.** Regenerating with npm 11 records the
  optional-dep tree differently and breaks `npm ci` on CI's npm 10 (the exact
  failure fixed in feature 038). The lockfile MUST be produced/verified with npm
  10 (AC-12).

## Out of scope

- **The dev-only advisories** (`vitest` critical, `vite`, `eslint`,
  `glob` high) — these are test/build tooling, **not shipped to users**, and are
  deliberately **not gated** by the prod-only audit policy. Upgrading them
  (e.g. `vitest 1.x → 4.x`) is a **separate future dev-tooling task**, not part of
  this security remediation. This feature only needs to clear the two production
  advisories.
- **Any backend, LangGraph, `ContractState`, API-contract, or database change** —
  owned by their existing specs; this feature is frontend-only (AC-11).
- **New features, redesigns, or UX changes** — no screen is redesigned; the goal
  is behavior-preserving (AC-10). Any deferred design items stay as previously
  scoped (022/024).
- **Tailwind / design-system major upgrades** — not upgraded unless React 19
  strictly requires it; the design-system spec (013) still owns tokens/styling.
- **TLS and other remaining security items** (Tier-1 TLS, Tier-3 report-file
  encryption / data-retention) — separate items in the security plan, not this
  feature.

## Open questions

**RESOLVED 2026-08-07 (owner confirmed the recommended answers; operationalized in
plan.md §Decisions):** (1) target **Next 16.x** (latest patch); (2) **yes** —
proactively bump `recharts` + `lucide-react` to React-19-compatible versions;
(3) migrate `next lint` → **ESLint CLI** (`eslint .`) with `eslint-config-next@16`;
(4) regression bar = **full Vitest+RTL suite + one real live smoke**. The items
below are retained for rationale.

1. **Target Next 16 vs Next 15?** `npm audit` names the fix as **`next@16.3.0`**
   (current major), and Next 15's breaking changes (React 19, async `params`) are
   a subset of 16's, so targeting **16.x** is recommended — it is the validated
   fix version and avoids a second upgrade later. Confirm target **16.x** (pin to
   the latest 16 patch), or do you want to stop at 15.x (still requires React 19;
   verify it also clears both advisories)?
2. **Proactively bump `recharts` and `lucide-react`?** Recommended: bump both to
   their latest React-19-compatible versions as part of this upgrade (rather than
   discovering incompatibility at build time). Confirm, or hold them at current
   ranges and only bump if React 19 forces it?
3. **`next lint` migration target.** Recommended: migrate `npm run lint` to the
   ESLint CLI (`eslint .`) with `eslint-config-next@16` (Next's documented
   replacement). Confirm, or keep whatever Next 16 provides if `next lint` is
   retained in your target patch?
4. **Verification depth for AC-10.** The Vitest+RTL suite (AC-5) plus a real live
   smoke is the proposed regression bar. Is the automated suite + one manual
   smoke sufficient, or do you want an explicit screen-by-screen visual check of
   all 12 reference screens before merge?
