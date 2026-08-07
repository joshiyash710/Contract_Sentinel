# Feature 039 — Next.js 14 → 16 Upgrade — Technical Plan

Branch: `feature/039-nextjs-16-upgrade` (git workflow per constitution §11).

Frontend-only security-remediation upgrade of the Next.js App Router app to clear
the two production high-severity advisories (`next` + transitive `postcss`) that
keep the `dependency-audit` CI gate red. No backend, LangGraph, `ContractState`
(001), API-contract, or database change (spec AC-11; constitution §2/§4/§10 —
this plan asserts and preserves "no 001 change"). Behavior-preserving: no screen
is redesigned (spec AC-10).

## SCOPE CORRECTION (implementation finding, 2026-08-07; owner-approved)
`next@16`'s peer is `react: "^18.2.0 || ^19.0.0"` — **React 19 is NOT required**.
`next@16.3.0` on React 18.3 was verified to build, pass `tsc`, and clear the
production audit (0 vulns). The owner chose the **minimal path: Next-only upgrade,
stay on React 18.3.** So **D2 is dropped** (no recharts/lucide/@types/React-19
bumps) and D1 narrows to "Next 14→16 + eslint-config-next 14→16, React unchanged."
`react`/`react-dom`/`@types/react(-dom)` stay at 18.3; `recharts`/`lucide-react`
stay at current versions. The rest of this plan (async-params, lint/ESLint-9,
lockfile, verification) applies as written. D3 (lint→ESLint CLI) and D4
(verification bar) are unchanged.

## Decisions (resolving spec Open Questions 1–4)
- **D1 — Target Next `16.x`** (latest 16 patch), not 15.x. It is the `npm audit`
  validated fix and 15's breaking changes are a subset.
- **D2 — Proactively bump** `recharts` and `lucide-react` to their latest
  React-19-compatible versions (up-front, not at build-time failure).
- **D3 — Migrate `next lint` → ESLint CLI** (`eslint .`) with
  `eslint-config-next@16` (Next 16 removes `next lint`).
- **D4 — Regression bar** = the full Vitest+RTL suite (242 tests) + `tsc` +
  `next build` + one real live smoke against the running backend.

## Context that shapes the plan
- **The only CI workflow is `dependency-audit.yml`.** It does NOT run lint, tsc,
  build, or the Vitest suite — it runs `npm ci` + the audit. So for **AC-2 (CI
  green)** what must hold in CI is: `npm ci` succeeds (npm-10 lockfile) and the
  production audit reports 0 high/critical. `tsc`/`build`/tests/lint (AC-3/4/5/9)
  are **local** acceptance checks, run and gated by this feature manually.
- Pure App Router; `src/pages/` = only `.gitkeep`. No `next/headers`
  `cookies()`/`headers()` server usage. Dev proxy is `next.config.mjs` `rewrites()`.

## 1. Dependency changes (`frontend/package.json`)
Bump (exact target versions pinned at implementation to the latest compatible):
- `next` `^14.2.0` → `^16.x`
- `react` `^18.3.0` → `^19.x`, `react-dom` `^18.3.0` → `^19.x`
- `@types/react` `^18.3.0` → `^19.x`, `@types/react-dom` `^18.3.0` → `^19.x`
- `eslint-config-next` `^14.2.0` → `^16.x`
- `recharts` `^2.12.0` → latest version that declares `react@19` in peerDeps
  (prefer the latest **2.15.x** which added React-19 support; only consider the
  `3.x` major if 2.x does not support React 19 — and if so, treat its charting
  API changes as in-scope work and re-verify all 4 chart components + the report
  donut). This choice is made at implementation after checking peerDeps.
- `lucide-react` `^0.400.0` → latest (React-19 peer-compatible).
- `eslint` `^8.57.0` → whatever `eslint-config-next@16` requires (likely ESLint 9;
  see §3.3) — bump only as forced by the config.

**Preferred mechanism:** run the official Next codemod
`npx @next/codemod@latest upgrade latest` in `frontend/`, which bumps
next/react/react-dom/eslint-config-next together and applies the applicable
codemods (including the async-`params` migration). Then run
`npx types-react-codemod@latest preset-19 ./src` for React-19 type migrations.
Apply/verify each codemod change by hand — do not blindly accept.

## 2. Source migrations (`frontend/src/`)
### 2.1 Async dynamic `params` (spec AC-6) — the two known sites
- `src/app/jobs/[jobId]/page.tsx`: change to
  ```tsx
  export default async function JobPage({ params }: { params: Promise<{ jobId: string }> }) {
    const { jobId } = await params;
    return (<div className="min-h-screen bg-app"><ProcessingView jobId={jobId} /></div>);
  }
  ```
- `src/app/jobs/[jobId]/report/page.tsx`: same shape, rendering `<ReportView jobId={jobId} />`.
- After migrating, run `next build`/`tsc`; if the Next 16 type-checker flags any
  OTHER sync `params`/`searchParams` (or a layout) access, migrate it identically
  (grounded scan found only these two).

### 2.2 React-19 breaking-API fixes (as surfaced by tsc/tests)
Fix any site the React-19 types/runtime flag across the 38 `"use client"`
components and shared utils (e.g. ref-as-prop changes, removed `propTypes`/
`defaultProps` on function components, `useRef()` requiring an initial arg). Each
is fixed at the source (constitution §7 — never suppress or weaken a test to pass).

### 2.3 Lint migration (spec AC-9, D3)
- `package.json` script: `"lint": "next lint"` → `"lint": "eslint ."`.
- Keep the existing minimal `.eslintrc.json` with `eslint-config-next@16` **if**
  that combination runs under the installed ESLint. If `eslint-config-next@16`
  requires ESLint 9 / flat config, migrate to `eslint.config.mjs` (flat) importing
  the Next config, and bump `eslint` accordingly. Prefer the minimal path; escalate
  to flat config only if forced. `npm run lint` must run and report no NEW errors.

### 2.4 Config / misc
- `next.config.mjs`: the `rewrites()` dev proxy and `reactStrictMode` are stable
  across 14→16; verify no key was renamed/removed by the codemod. The proxy MUST
  still map `/api/:path*` → `API_PROXY_ORIGIN` (spec AC-7).
- `src/middleware.ts`: `NextRequest`/`NextResponse` API is stable; verify it
  compiles and `middleware.test.ts` passes unchanged (spec AC-8).
- `src/pages/.gitkeep`: remove `src/pages/` only if Next 16 warns about a mixed/
  empty router dir; otherwise leave it. Non-blocking.
- Node floor: Next 16 requires Node ≥ 20.9. Confirm local + CI `node-version: "20"`
  (setup-node installs latest 20.x ≥ 20.9) satisfies it; bump the workflow's
  `node-version` only if the floor is not met.

## 3. Test-environment compatibility
- `@testing-library/react ^16` already supports React 19 — keep. If React-19
  `act`/concurrent rendering surfaces failing/flaky tests under `vitest ^1.6` +
  `jsdom ^24`, fix the **test setup** (`vitest.setup.ts`/`vitest.config.ts`, or a
  minimal RTL/`@testing-library/dom` bump) — never weaken assertions (§7).
- `vitest`/`vite`/`eslint` dev-tooling advisories are **out of scope** (spec Out of
  scope); do not upgrade vitest here.

## 4. Lockfile (spec AC-12)
Regenerate `frontend/package-lock.json` with **npm 10** (`npx -y npm@10 install`)
so CI's Node-20/npm-10 `npm ci` accepts it. Verify `npm ci` exits 0 under **both**
`npx -y npm@10 ci` and the local `npm ci` (the exact regression fixed in 038).

## 5. Verification (maps to ACs) — run from `frontend/`
1. `npm audit --omit=dev` → 0 `high`/`critical` for `next` and `postcss` (AC-1).
2. `python ../backend/scripts/security_audit.py --skip-backend --severity high` →
   frontend production gate returns 0 → exit 0 (AC-1/AC-2 proxy locally).
3. `npm run build` succeeds (AC-3).
4. `npx tsc --noEmit` → 0 errors (AC-4).
5. `npm test` → all 242 tests / 45 files green (AC-5); any legitimately-changed
   test is justified in the tasks/PR, not weakened (§7).
6. `npm run lint` runs, no new errors (AC-9).
7. `npx -y npm@10 ci` and `npm ci` both exit 0 (AC-12).
8. **Live smoke** (D4/AC-7/AC-8/AC-10): `NEXT_PUBLIC_API_PROVIDER=real`, backend on
   :8000 — login, upload, watch processing, view report (dynamic `[jobId]` routes),
   dashboard, contracts/history; confirm the dev proxy round-trips, middleware
   gating works, charts render, and no console error about sync `params`.
9. Push branch → confirm the `dependency-audit` workflow run is **green** (AC-2).

## 6. Risks
- **Recharts React-19 compat** is the largest unknown; §1 handles it (prefer 2.15.x;
  escalate to 3.x only if forced, treating its API changes as in-scope).
- **ESLint 9 / flat-config** migration if `eslint-config-next@16` forces it (§3.3) —
  contained, and lint is not CI-gated.
- **Hidden sync-`params`/React-19 sites** beyond the grounded two — caught by
  `next build` + `tsc` + the full suite before merge.
- No backend/state risk (frontend-only; AC-11).

## 7. Out of scope (per spec)
Dev-tooling upgrades (`vitest`/`vite`/`eslint` beyond what config forces), any
backend/graph/001/API change, redesigns, Tailwind majors, and other security-plan
items (TLS, Tier-3).
