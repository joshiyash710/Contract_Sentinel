# Feature 039 — Next.js 14 → 16 Upgrade — Tasks

Ordered steps. This is a framework/dependency upgrade, so the regression gate is
the **existing** suite (242 Vitest tests / 45 files) + `tsc` + `next build` +
prod `npm audit` — no new product tests are written; per constitution §7 no
existing test is weakened to force a pass (any legitimately-changed test must be
justified). Every task traces to a spec AC. Branch:
`feature/039-nextjs-16-upgrade`. All commands run from `frontend/` unless noted.

Baseline to preserve (pre-upgrade, re-confirm before starting): `tsc` clean,
`npm test` = 242 passed / 45 files, `npm run build` succeeds.

---

## Phase A — Prep & baseline

### T1 — Confirm green baseline
From `frontend/`: run `npx tsc --noEmit`, `npm test`, `npm run build` — record
that all pass on the current (Next 14) tree. If anything is already failing, STOP
and report (don't attribute pre-existing breakage to the upgrade).

### T2 — Snapshot the prod-audit target (AC-1)
`npm audit --omit=dev` — record the 2 production high advisories (`next`,
`postcss`) that must be gone after the upgrade.

---

## Phase B — Dependency upgrade (spec §1 / D1, D2)

### T3 — Run the Next upgrade codemod
`npx @next/codemod@latest upgrade latest` — bumps `next`→16, `react`/`react-dom`
→19, `eslint-config-next`→16, and applies applicable codemods. Review every file
it changes; do not blindly accept. If it does not bump `@types/react*`, set
`@types/react@^19` + `@types/react-dom@^19` in `package.json`.

### T4 — React-19 type codemod
`npx types-react-codemod@latest preset-19 ./src` — apply React-19 type migrations;
hand-verify each change.

### T5 — Bump chart/icon libs for React 19 (D2)
Check `recharts` peerDeps for `react@19`: set `recharts` to the latest **2.15.x**
that supports React 19 (only move to `3.x` if 2.x does not — and if so, re-verify
all 4 chart components + the report donut render, treating API changes as in-scope).
Bump `lucide-react` to latest. Record chosen versions.

### T6 — Regenerate lockfile with npm 10 (AC-12)
`npx -y npm@10 install` to produce an npm-10 `package-lock.json`. (Do the version
edits in package.json first, then this resolves them.)

---

## Phase C — Source migrations (spec §2)

### T7 — Async `params` on the 2 dynamic-route server pages (AC-6)
Edit `src/app/jobs/[jobId]/page.tsx` and `src/app/jobs/[jobId]/report/page.tsx`:
make the default export `async`, type `params` as `Promise<{ jobId: string }>`,
and `const { jobId } = await params;` before use. (The codemod in T3 may already
do this — verify the result matches; fix if not.)

### T8 — Fix any other flagged React-19 / async-params sites (AC-4, AC-6)
Run `npx tsc --noEmit` and `npm run build`; migrate every additional site the
type-checker/build flags (sync `params`/`searchParams`, ref-as-prop, removed
`defaultProps`/`propTypes`, `useRef()` needing an arg, etc.) at the source. The
grounded scan found only the two T7 pages, but treat build/tsc as authoritative.

### T9 — Lint migration (AC-9 / D3)
Change `package.json` script `"lint": "next lint"` → `"lint": "eslint ."`. Keep
`.eslintrc.json` with `eslint-config-next@16` if it runs under the installed
ESLint; if `eslint-config-next@16` requires ESLint 9 / flat config, add
`eslint.config.mjs` (flat) importing the Next config and bump `eslint`. `npm run
lint` must run and report no NEW errors.

### T10 — Config/misc checks (AC-7, AC-8)
- `next.config.mjs`: confirm `rewrites()` (`/api/:path*` → `API_PROXY_ORIGIN`) and
  `reactStrictMode` survive; fix any key the codemod renamed.
- `src/middleware.ts`: confirm it compiles unchanged.
- `src/pages/`: remove it only if Next 16 warns about the empty/mixed router dir.
- Node floor: confirm local Node ≥ 20.9 and CI `node-version: "20"` satisfies
  Next 16; bump the workflow only if not.

---

## Phase D — Verify (spec §5, maps to ACs)

### T11 — Types + build
`npx tsc --noEmit` → 0 errors (AC-4). `npm run build` → success (AC-3).

### T12 — Test suite (AC-5)
`npm test` → all 242 tests / 45 files green. If React-19/RTL surfaces
test-env failures, fix the **setup** (`vitest.setup.ts`/`vitest.config.ts`, or a
minimal RTL bump) — never weaken assertions (§7). Justify any test that must
legitimately change.

### T13 — Lint (AC-9)
`npm run lint` runs, no new errors.

### T14 — Production audit cleared (AC-1)
`npm audit --omit=dev` → 0 high/critical for `next` and `postcss`. Then
`python ../backend/scripts/security_audit.py --skip-backend --severity high` →
frontend prod gate returns 0 → exit 0.

### T15 — Lockfile CI-compat (AC-12)
`npx -y npm@10 ci` → exit 0, AND `npm ci` (local npm) → exit 0.

---

## Phase E — Ship

### T16 — Live smoke (AC-7, AC-8, AC-10 / D4) — owner-run
`NEXT_PUBLIC_API_PROVIDER=real`, backend on :8000 (`AUTH_COOKIE_SECURE=False`),
Ollama warm. Exercise: login → upload → processing (`/jobs/{id}`) → report
(`/jobs/{id}/report`) → dashboard → contracts/history → settings/integrations.
Confirm: dev-proxy round-trips, middleware gating, charts render, no console
error about sync `params`, no visual/behavior regression.

### T17 — Push & confirm CI green (AC-2, AC-11)
Commit; push the branch; confirm the `dependency-audit` workflow run is **green**
(npm ci passes, prod audit 0 findings). Confirm the diff is confined to
`frontend/` (no backend/`specs/001`/graph change, AC-11). Then `/code-review` and
git-finish.
