# Per-User Data Isolation + Landing/Auth Redesign — Implementation Tasks

Reference documents:
- Spec: `specs/019-multi-tenant-data/spec.md`
- Plan: `specs/019-multi-tenant-data/plan.md`
- Constitution: `specs/000-constitution.md` (§2 amendment for 019 is Task 0)
- Consumed: 011 (`app/api/routes.py`, `main.py`), 012 (`app/runner/store.py`,
  `registry.py`, migrations), 014 (`app/api/auth.py` `require_auth`/`AuthUser`,
  `AUTH_SIGNUP_OPEN`), 018 (`app/api/aggregate.py`, `store.list/all/count`,
  dashboard/reports views + empty states), 013 design tokens, the two mockups
  (landing `…31 PM.jpeg`, auth `…31 PM (1).jpeg`)

Backend paths relative to `backend/`, frontend to `frontend/`.

**Workflow reminders:**
- TDD (§7): tests written + confirmed FAILING before implementation. The sanctioned test
  *modifications* here (Task 5) are the integration tests whose endpoint contract changed
  from shared → scoped — assertions are inverted/tightened, never weakened.
- **No `backend/app/graph/` change and no `ContractState` field** (AC-A9). Persistence + API
  scoping + frontend only.
- **`aggregate.py` stays pure and UNCHANGED** — scoping is at the store/route read boundary;
  do not add user logic to aggregate.
- **`user_id` never crosses the wire** — no boundary Pydantic / `types.ts` change. Ownership
  is server-only.
- Security is the point of Part A — the ownership check returns **`404`** (not `403`) and runs
  **before** any file is served / SSE stream opens.
- NEVER `next build` while `next dev` runs. Stop dev first.

---

## Task 0: Constitution amendment + branch
- [ ] **[MODIFY] `specs/000-constitution.md`** — under §2, directly after the existing
  "AMENDMENT (2026-07-14, feature 014)" paragraph, add the **feature-019 amendment** from
  spec §7 verbatim: per-user data ownership/partitioning is now IN scope; RBAC, roles,
  permission grants, teams/orgs, cross-account sharing/collaboration, and tenant-admin
  remain PERMANENTLY CUT; legacy (no-owner) rows are hidden not migrated; open signup
  re-enabled. (Docs only — allowed before the branch/code per §1.)
- [ ] From up-to-date `main`, create `feature/019-multi-tenant-data` (`git-start`).

**Verify:** `git branch --show-current` → `feature/019-multi-tenant-data`; the amendment
text is present in §2.

---

## Task 1: Migration `0004` (add `jobs.user_id`)
- [ ] **[NEW] `alembic/versions/0004_add_jobs_user_id.py`** — `revision="0004"`,
  `down_revision="0003"`. Upgrade: `op.add_column("jobs", sa.Column("user_id", sa.Text,
  nullable=True))`. Downgrade: `with op.batch_alter_table("jobs") as batch:
  batch.drop_column("user_id")` (SQLite can't drop in place).
- [ ] **[MODIFY] `tests/integration/test_alembic_head.py`** — update the expected head to
  `0004` and assert the `jobs.user_id` column exists after `upgrade_to_head`.

**Verify:** `pytest tests/integration/test_alembic_head.py` → PASS; `alembic upgrade head`
on a scratch DB adds a nullable `user_id`.

---

## Task 2: Store — `user_id` + scoped reads (tests first)
- [ ] **[MODIFY] `tests/unit/test_job_store.py`** — confirm FAILING: upsert a `JobRow` with
  `user_id="u1"`, `get(job_id)` returns it with `user_id=="u1"`.
- [ ] **[MODIFY] `tests/unit/test_store_list.py`** — confirm FAILING: seed rows for `u1`,
  `u2`, and one `user_id=None`; `list("u1",limit,offset)` / `all("u1")` / `count("u1")`
  return only `u1` rows (u2 and NULL excluded); `count("u2")` counts only `u2` (AC-A2/A6).
- [ ] **[MODIFY] `app/runner/store.py`**:
  - Add `user_id: Optional[str] = None` to `JobRow` (append LAST, after `original_filename`).
  - Thread it through `_encode` (append to the VALUES tuple) and `_decode`
    (`r["user_id"] if "user_id" in r.keys() else None`).
  - Extend the `upsert` INSERT column list + placeholders with `user_id` (not needed in the
    `ON CONFLICT DO UPDATE SET` clause — it is set at create and immutable).
  - `list(self, user_id, limit, offset)`, `all(self, user_id)`, `count(self, user_id)` gain
    a `WHERE user_id=?` filter (keep `ORDER BY submitted_at DESC`).
  - Leave `get`, `nonterminal`, `prune` unchanged.

**Verify:** `pytest tests/unit/test_job_store.py tests/unit/test_store_list.py` → PASS.

---

## Task 3: Registry — carry `user_id` (tests first)
- [ ] **[MODIFY] `tests/unit/test_registry.py`** + **`tests/unit/test_registry_writethrough.py`**
  — confirm FAILING: a `JobRecord(user_id="u1", …)` persists `user_id` on the initial insert
  and round-trips through `from_row`; `list_jobs/all_rows/count` forward the `user_id` arg.
- [ ] **[MODIFY] `app/runner/registry.py`**:
  - Add `user_id: Optional[str] = None` to `JobRecord` (plain init field beside
    `original_filename`); include it in `_to_row()` and `from_row()` (read `row.user_id`).
  - `list_jobs(self, user_id, limit, offset)`, `all_rows(self, user_id)`,
    `count(self, user_id)` forward the arg to the store (store=None → `[]`/`0`).

**Verify:** `pytest tests/unit/test_registry.py tests/unit/test_registry_writethrough.py`
→ PASS.

---

## Task 4: Routes — stamp, scope, ownership (tests first)
- [ ] **[NEW] `tests/integration/test_isolation.py`** — confirm FAILING (two authed clients
  A and B via the `authenticate_as` helper from Task 5):
  - A creates a job (via `POST /api/analyze` + wait for terminal); **B** `GET /api/jobs` is
    empty and `total==0`; **A** sees its job (AC-A2).
  - **B** `GET /api/jobs/{A_id}`, `.../report`, `.../events` → `404`; **A** → `2xx`
    (AC-A3/A4).
  - `GET /api/dashboard`: B all-zero, A non-zero (AC-A5).
  - Seed a `user_id=None` row directly in the store → visible to neither A nor B (AC-A6).
- [ ] **[MODIFY] `tests/integration/test_api_analyze.py`** — after `POST /api/analyze` as the
  authed user, the stored `JobRow.user_id` == that user's id (AC-A1).
- [ ] **[MODIFY] `app/api/routes.py`**:
  - Import `AuthUser, require_auth` from `app.api.auth`.
  - Add `current_user: AuthUser = Depends(require_auth)` to `analyze`, `list_jobs`,
    `dashboard`, `get_job`, `get_job_events`, `get_job_report` (FastAPI dedupes the
    router-level dep — runs once).
  - `analyze`: construct `JobRecord(..., user_id=current_user.id)`.
  - `list_jobs`: `reg.list_jobs(current_user.id, limit, offset)` + `reg.count(current_user.id)`.
  - `dashboard`: `build_dashboard_metrics(reg.all_rows(current_user.id), read_report_data,
    today=_utc_today())`.
  - Add `_owned_or_404(ctx, job_id, current_user) -> JobRecord`: `rec = ctx.registry.get(
    job_id); if rec is None or rec.user_id != current_user.id: raise HTTPException(404, "Job
    not found"); return rec`. Use it in `get_job`, `get_job_events`, `get_job_report`
    **before** any stream/file work.
- [ ] **[MODIFY] `app/config.py`** — set `AUTH_SIGNUP_OPEN = True` (comment: isolation makes
  open signup safe again; `False` remains the lock-down lever).

**Verify:** `pytest tests/integration/test_isolation.py tests/integration/test_api_analyze.py`
→ PASS.

---

## Task 5: Migrate existing integration tests to scoped world (the careful one)
- [ ] **[MODIFY] `tests/integration/conftest.py`** — add helpers:
  - `authenticate_as(client, email, password)` — signup-or-login (idempotent: on `409`/`403`
    → login), persisting the cookie on that client instance.
  - `current_user_id(client) -> str` — `GET /api/auth/me` → `body["user"]["id"]` (for
    stamping directly-seeded rows).
  Keep the existing single-user `authenticate(client)` for the shared `client` fixture.
- [ ] **[MODIFY] the integration tests that seed or read jobs** so their data belongs to the
  authed user (per plan §7 — directly-seeded `JobRow`s are now `user_id=NULL` = hidden):
  - `test_api_jobs.py` — seed rows with `user_id=current_user_id(client)` (or create via
    `POST /api/analyze`); assert the scoped list (AC-A2).
  - `test_dashboard_endpoints.py` — same stamping; add an **empty-account** assertion
    (all-zero payload, AC-A5/EC-5).
  - `test_auth_endpoints.py` — **REPLACE** `test_two_accounts_share_jobs` with
    `test_two_accounts_isolated`: two accounts, each sees only its own jobs (AC-A(t)); keep
    every other auth assertion unchanged.
  - Any other integration test that directly seeds a `JobRow` and reads it back through a
    gated endpoint (grep the suite) — stamp the authed user's id.

**Verify:** `pytest` (WHOLE backend suite) → all green.

---

## Task 6: Landing redesign — Part B (tests first)
- [ ] **[MODIFY] `src/__tests__/landing.test.tsx`** — update for the new structure while
  KEEPING behavior: renders hero + primary CTA (→`/login`), Log In / Sign Up (→`/login`),
  the full feature grid, a "How it works" section, a closing CTA, and **no app sidebar**;
  Pricing/Blog inert (AC-B1/B2). Confirm FAILING against the new component names.
- [ ] **[NEW] `src/components/marketing/MarketingNav.tsx`, `Hero.tsx`, `HeroArt.tsx`,
  `FeatureGrid.tsx`, `HowItWorks.tsx`, `ClosingCTA.tsx`** — per plan §4.1 (sticky blur nav;
  aurora hero + shield SVG artwork; full feature grid with gradient icon chips + hover-lift;
  3-step strip; final CTA band + minimal footer with inert links). Reuse 013 tokens.
- [ ] **[REWRITE] `src/components/marketing/LandingView.tsx`** — compose the sections.
- [ ] **[MODIFY] `src/app/globals.css`** — add `@keyframes aurora` + `.bg-aurora` utility
  (layered radial-gradients from existing `--accent`/gradient vars; honor
  `prefers-reduced-motion`). **No new color token.**

**Verify:** `vitest run src/__tests__/landing.test.tsx` → PASS.

---

## Task 7: Auth redesign — Part B (tests first)
- [ ] **[MODIFY] `src/__tests__/authView.test.tsx`** — update for the split layout + underline
  tabs while KEEPING behavior: tabs switch forms (AC-B3); login submit → `login()` →
  `replace('/dashboard')`, `401` → inline error no-nav; signup → `signup()`, `409`/`422` →
  inline errors (AC-B4); Google/Microsoft disabled + Forgot inert (AC-B5). Confirm FAILING.
- [ ] **[NEW] `src/components/auth/AuthBrandPanel.tsx`** — left brand/value panel (`hidden
  md:flex`, aurora bg, logo + one-line value prop + subtle stat).
- [ ] **[REWRITE] `src/components/auth/AuthView.tsx`** — `md:grid md:grid-cols-2` host
  (panel + form card); underline Login/Sign-Up tabs with animated indicator; Work Email +
  `PasswordInput`; inert Forgot (span, D7); gradient submit w/ loading; disabled Google/
  Microsoft (D6); **unchanged error mapping** (`401`/`409`/`422`) via `getApiClient()` (no
  provider import — seam preserved).

**Verify:** `vitest run src/__tests__/authView.test.tsx` + `src/__tests__/auth-boundary.test.ts`
→ PASS.

---

## Task 8: Empty states (Part A consequence — tests first)
- [ ] **[NEW] `src/__tests__/emptyStates.test.tsx`** — confirm FAILING: with a zero-jobs fake
  client, `DashboardView` and `ReportsView` render a polished "Upload your first contract"
  empty state (icon + copy + CTA → `/upload`), not demo numbers (AC-B6).
- [ ] **[MODIFY as needed] `src/components/dashboard/DashboardView.tsx`,
  `src/components/dashboard/ReportsView.tsx`, `src/app/contracts/page.tsx`** — polish/extend
  the 018 zero-jobs empty states. (Mock provider still returns fixtures, so existing
  mock-based tests are unaffected.)

**Verify:** `vitest run src/__tests__/emptyStates.test.tsx` → PASS.

---

## Task 9: Full verification
- [ ] `pytest` (whole backend) GREEN.
- [ ] `vitest run` (whole frontend) GREEN; `tsc --noEmit` clean; `npm run lint` clean.
- [ ] Stop dev; `next build` succeeds (`/`, `/login`, dashboard, reports build).
- [ ] `git diff --name-only main` — no `backend/app/graph/` file changed; no boundary
  Pydantic / `types.ts` change for `user_id` (AC-A9).

---

## Task 10: Security review + live smoke (AC-A10)
- [ ] Run the **`/security-review`** skill on the branch diff (verify no read path bypasses
  the `user_id` scope; ownership returns `404` before side effects); address findings.
- [ ] `alembic upgrade head` (applies `0004`). Start `uvicorn`; set `frontend/.env.local`
  `NEXT_PUBLIC_API_PROVIDER=real`; `npm run dev`.
- [ ] Smoke: sign up **A**, upload a contract → appears in A's dashboard/jobs. Sign up **B**
  (fresh) → B's dashboard/jobs **empty**; B `GET /api/jobs/{A_id}` and `.../report` → `404`.
  Back as **A** → data intact. Confirms server-side scoping through the Next proxy.
- [ ] Reset `.env.local` to `mock`. Report the outcome.

---

## Task 11: Merge
- [ ] All suites + `tsc` + `build` green; security review clean; smoke noted.
- [ ] Rebase `main`, merge `feature/019-multi-tenant-data`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/019-multi-tenant-data`, opened after
spec + plan + tasks are approved. Migration `0004` requires `alembic upgrade head` after
pulling. No new backend deps.*
