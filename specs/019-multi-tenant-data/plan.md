# Per-User Data Isolation + Landing/Auth Redesign — Technical Plan

## Git Branch

`feature/019-multi-tenant-data` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

Implements `specs/019-multi-tenant-data/spec.md`, in two parts on one branch:

**Part A — per-user data isolation (backend).** Add a nullable `jobs.user_id` column
(Alembic `0004`), stamp every new job with the authenticated `current_user.id` at
`POST /api/analyze`, and **scope every read** (`/api/jobs`, `/api/dashboard`,
`/api/jobs/{id}` + its `report`/`events`) to the caller. Non-owned/legacy rows return the
same `404` as nonexistent (no existence leak). Re-open signup (`AUTH_SIGNUP_OPEN=True`)
since isolation removes the shared-data exposure. **No graph node/edge, no `ContractState`
field** (constitution §2/§4). The change threads one field through the existing
store→registry→route seam; `aggregate.py` is **pure** (it already aggregates whatever rows
it is handed) and is **not modified** — it is simply handed only the caller's rows.

**Part B — premium landing/auth redesign (frontend).** Rewrite `LandingView` and `AuthView`
(decomposed into section components) to push beyond the reference mockups — aurora hero +
shield artwork, full feature grid, "How it works", closing CTA; a split brand-panel auth
layout with underline tabs — reusing the 013 design tokens (no new colors). All 014 auth
behavior is preserved (SSO disabled, forgot inert, CTAs → `/login`, error mapping, seam).
Because reads are now scoped, new accounts land on their own empty workspace, so the
dashboard/reports/contracts **empty states** are polished.

Authorized by the proposed **constitution §2 amendment** (spec §7); tasks.md amends the
constitution first (as 014 did).

---

## 2. Files to Create / Modify

### Backend (`backend/`)
```
alembic/versions/0004_add_jobs_user_id.py   [NEW]    add nullable jobs.user_id (down_revision "0003")
app/runner/store.py                          [MODIFY] JobRow.user_id; _encode/_decode; upsert cols; list/all/count filter by user_id
app/runner/registry.py                       [MODIFY] JobRecord.user_id; _to_row/from_row; list_jobs/all_rows/count pass user_id through
app/api/routes.py                            [MODIFY] analyze stamps user_id; reads scoped; ownership → 404 on get/report/events
app/config.py                                [MODIFY] AUTH_SIGNUP_OPEN back to True (§2.4)
app/api/aggregate.py                         [UNCHANGED] pure; handed scoped rows only (listed for clarity)

tests/unit/test_job_store.py                 [MODIFY] user_id round-trip via upsert/get
tests/unit/test_store_list.py                [MODIFY] list/all/count scoped by user_id (+ NULL-owner excluded)
tests/unit/test_registry.py                  [MODIFY] JobRecord user_id + pass-through args
tests/unit/test_registry_writethrough.py     [MODIFY] user_id persisted on write-through
tests/unit/test_aggregate.py                 [MODIFY only if it builds JobRow positionally] add user_id kwarg
tests/integration/test_isolation.py          [NEW]    two-account isolation (AC-A2/A3/A4/A5/A6) — the core feature test
tests/integration/test_api_analyze.py        [MODIFY] assert created job's persisted user_id == caller (AC-A1)
tests/integration/test_api_jobs.py           [MODIFY] seed rows under the authed user; scoped list (AC-A2)
tests/integration/test_dashboard_endpoints.py[MODIFY] scoped aggregation; empty-account payload (AC-A5)
tests/integration/test_auth_endpoints.py     [MODIFY] REPLACE test_two_accounts_share_jobs (AC-10) with isolation assertion (AC-A(t))
tests/integration/conftest.py                [MODIFY] add authenticate_as(client,email,pw) + current_user_id(client) helpers
```

### Frontend (`frontend/`)
```
src/components/marketing/LandingView.tsx     [REWRITE] compose the sections below
src/components/marketing/MarketingNav.tsx    [NEW]  sticky blur nav (logo, anchors, Log In/Sign Up → /login)
src/components/marketing/Hero.tsx            [NEW]  aurora hero + headline + CTAs (→ /login)
src/components/marketing/HeroArt.tsx         [NEW]  shield + layered-documents SVG/CSS artwork (no external asset)
src/components/marketing/FeatureGrid.tsx     [NEW]  full feature-card grid (gradient icon chips, hover-lift)
src/components/marketing/HowItWorks.tsx      [NEW]  3-step strip (Upload → Analyze → Report)
src/components/marketing/ClosingCTA.tsx      [NEW]  final CTA band + minimal footer (inert links, D8)
src/components/auth/AuthView.tsx             [REWRITE] split layout host + tabs + form + error mapping (behavior preserved)
src/components/auth/AuthBrandPanel.tsx       [NEW]  left brand/value panel (wide screens only)
src/app/globals.css                          [MODIFY] add @keyframes aurora + utility (animation only — NO new color tokens)
src/components/dashboard/DashboardView.tsx   [MODIFY if needed] polish zero-jobs empty state (AC-B6)
src/components/dashboard/ReportsView.tsx     [MODIFY if needed] polish zero-jobs empty state (AC-B6)
src/app/contracts/page.tsx                   [MODIFY if needed] polish zero-jobs empty state (AC-B6)

src/__tests__/landing.test.tsx               [MODIFY] new structure, SAME behavior (hero, CTAs→/login, cards, no sidebar)
src/__tests__/authView.test.tsx              [MODIFY] split layout + underline tabs, SAME behavior (AC-B3/B4/B5)
src/__tests__/emptyStates.test.tsx           [NEW]  dashboard/reports render "upload your first contract" on zero jobs (AC-B6)
```

No `backend/app/graph/` file is touched (AC-A9). No boundary Pydantic model or `types.ts`
changes — `user_id` is internal ownership, never on the wire (so Part A has **no frontend
seam change**; the app screens "just work" once the server scopes them).

---

## 3. Backend design

### 3.1 Migration `0004_add_jobs_user_id.py`
`revision="0004"`, `down_revision="0003"`. Upgrade:
```python
op.add_column("jobs", sa.Column("user_id", sa.Text, nullable=True))
```
(SQLite supports `ALTER TABLE ADD COLUMN` natively.) Downgrade uses batch mode because
SQLite cannot drop a column in place:
```python
with op.batch_alter_table("jobs") as batch:
    batch.drop_column("user_id")
```
Nullable is deliberate: existing rows get `user_id = NULL` = "legacy/unowned", which no
live account's id equals, so scoped reads exclude them (spec §2.1 / AC-A6). The Alembic
chain already runs on startup (`upgrade_to_head(JOB_STORE_DB_PATH)`); pulling this feature
requires `alembic upgrade head` (as 0002/0003 did).

### 3.2 `store.py` — `JobRow` + scoped reads
- **`JobRow`**: add `user_id: Optional[str] = None` (appended LAST, like `original_filename`,
  to preserve the "no non-default after default" ordering and the positional `_encode`
  tuple). Thread it through `_encode` (append to the VALUES tuple) and `_decode`
  (`r["user_id"] if "user_id" in r.keys() else None`). Extend the `upsert` INSERT column
  list + placeholders with `user_id` (it is set at create and immutable, so it need not be
  in the `ON CONFLICT DO UPDATE SET` clause).
- **Scoped reads** gain a `user_id` parameter and a `WHERE user_id = ?` filter:
  - `list(self, user_id: str, limit: int, offset: int)` → `... WHERE user_id=? ORDER BY submitted_at DESC LIMIT ? OFFSET ?`
  - `all(self, user_id: str)` → `... WHERE user_id=? ORDER BY submitted_at DESC`
  - `count(self, user_id: str)` → `SELECT COUNT(*) ... WHERE user_id=?`
- **Unchanged:** `get(job_id)` (still by id — ownership is checked in the handler so a miss
  and a not-owned both map to the same `404`, and cross-restart rehydration keeps working);
  `nonterminal()` (recovery is not user-scoped, §2.5); `prune()` (retention stays a global
  cap, EC-7).

### 3.3 `registry.py` — `JobRecord` + pass-throughs
- **`JobRecord`**: add `user_id: Optional[str] = None` (a plain init field beside
  `original_filename`). Include it in `_to_row()` and in `from_row()` (read `row.user_id`).
  It is set once at create and never mutated, so no lock method changes.
- **Pass-throughs** forward the arg to the store:
  - `list_jobs(self, user_id, limit, offset)` → `self._store.list(user_id, limit, offset)`
  - `all_rows(self, user_id)` → `self._store.all(user_id)`
  - `count(self, user_id)` → `self._store.count(user_id)`
  (store=None still returns `[]`/`0`.)

### 3.4 `routes.py` — stamp, scope, ownership
Each guarded handler adds `current_user: AuthUser = Depends(require_auth)`. The dependency is
already applied router-level (`main.py` include), and FastAPI **dedupes the same dependency**,
so it runs once per request — the param just surfaces the value. Import `AuthUser`/`require_auth`
from `app.api.auth`.
- **`analyze`**: build the `JobRecord` with `user_id=current_user.id` (the initial durable
  insert then persists it — AC-A1).
- **`list_jobs`**: `reg.list_jobs(current_user.id, limit, offset)` and
  `reg.count(current_user.id)` (both scoped — AC-A2).
- **`dashboard`**: `build_dashboard_metrics(reg.all_rows(current_user.id), read_report_data,
  today=…)` (AC-A5; an empty account yields an all-zero payload — aggregate already handles
  `rows=[]` without divide-by-zero, EC-5).
- **`get_job` / `get_job_events` / `get_job_report`**: after `rec = ctx.registry.get(job_id)`,
  treat **`rec is None` OR `rec.user_id != current_user.id`** as `404 "Job not found"` — one
  branch, identical response, checked **before** streaming/serving (AC-A3/A4, EC-1). A helper
  `_owned_or_404(ctx, job_id, current_user)` keeps the three handlers consistent.

### 3.5 `config.py`
Flip `AUTH_SIGNUP_OPEN` back to `True` (§2.4 / AC-A7). Leave a comment noting isolation is
why it's safe again, and that `False` remains the lock-down lever.

### 3.6 Ownership semantics (why 404, not 403)
Returning `403` on a non-owned id would confirm the id exists in someone else's workspace
(enumeration leak). `404` makes "doesn't exist" and "not yours" indistinguishable (EC-1).
`GET /api/jobs` never lists other owners' ids, so ids aren't discoverable in the first place.

---

## 4. Frontend design (Part B)

> **Client/server (constitution §8).** `AuthView` and the interactive marketing bits stay
> client components (`useRouter`, `useState`, `usePathname`). `app/page.tsx` /
> `app/login/page.tsx` remain thin hosts. **No route-group refactor** — the conditional
> `AppShell` already renders `/` and `/login` shell-free; Part B only rewrites the two views.

### 4.1 Landing (`LandingView` → section components)
Compose `MarketingNav + Hero + FeatureGrid + HowItWorks + ClosingCTA`:
- **MarketingNav** — logo + Features/Integrations (on-page anchors) + Pricing/Blog (inert
  spans) + Log In / Sign Up (`Link href="/login"`); `sticky top-0` with `backdrop-blur` and a
  subtle border that intensifies on scroll.
- **Hero** — gradient headline "AI-Powered Legal Contract Intelligence", subcopy, primary CTA
  "Analyze Your First Contract (Free)" (`Link href="/login"`) + secondary "See how it works"
  (`href="#how"`), over the **aurora** background (§4.3). Renders **HeroArt** on the right.
- **HeroArt** — the shield + layered-documents artwork as inline SVG + CSS glow (uses
  `--accent`/gradient tokens; no external asset, no new dependency).
- **FeatureGrid** (`id="features"`) — the four primary cards plus a second row, each a `Card`
  with a gradient icon chip (lucide icon) and a hover-lift (`transition` + `-translate-y`).
- **HowItWorks** (`id="how"`) — a 3-step strip (Upload → AI analyzes → Get your report) with
  numbered gradient badges.
- **ClosingCTA** — final "Get started" band (→ `/login`) + a minimal footer; footer links are
  inert where no page exists (D8 — no fabricated destinations).

### 4.2 Auth (`AuthView` + `AuthBrandPanel`)
- **Layout** — `md:grid md:grid-cols-2`: left `AuthBrandPanel` (logo, one-line value prop, a
  subtle stat/testimonial, aurora bg) shown `hidden md:flex`; right the form card. On mobile
  the panel is hidden and the card centers (matches the ref's single-card feel).
- **Tabs** — underline-style Login / Sign Up with an animated active indicator (replacing the
  current pill tabs); switches the active form without navigation.
- **Form** — Work Email (`TextInput`) + Password (`PasswordInput` show/hide), inert
  "Forgot password?" (span, D7), gradient "Continue to ContractSentinel" submit with a
  loading state, "Or continue with" divider, **disabled** Google/Microsoft with brand glyphs
  (D6). Submit → `getApiClient().login|signup` → `router.replace("/dashboard")`; **error
  mapping unchanged** (`401`→"invalid email or password", `409`→"account already exists",
  `422`→password-policy) rendered as a polished inline alert (`role="alert"`).
- **Seam** — no provider import here (uses `getApiClient()` via `@/lib/api/provider`), so the
  `auth-boundary` grep test stays green (AC-B5).

### 4.3 Aurora / animation (`globals.css`)
Add an `@keyframes aurora` + a `.bg-aurora` utility (layered `radial-gradient`s built from the
existing `--accent`/`--accent-gradient-*` vars with a slow drift). **Only animation/gradient
composition is added — no new color token** (globals.css stays the single source of truth for
color, 013 AC-1). Respect `prefers-reduced-motion` (disable the drift).

### 4.4 Empty states (Part A consequence — AC-B6)
A brand-new account now legitimately has zero jobs on the **real** provider, so the
dashboard/reports/contracts screens must render a polished "Upload your first contract" empty
state (icon + copy + CTA → `/upload`) when the client returns `total: 0`. Verify/extend the
existing 018 empty states in `DashboardView`/`ReportsView` (and the contracts page). The
**mock** provider still returns fixtures, so existing mock-based tests are unaffected; the new
`emptyStates.test.tsx` drives these with a zero-jobs fake client.

---

## 5. Tests mapped to acceptance criteria

**Backend (pytest).**
- `test_job_store.py` / `test_store_list.py`: upsert a row with `user_id` and read it back;
  `list/all/count` return only the matching user's rows and **exclude NULL-owner rows**
  (AC-A2/A6); a second user's rows are disjoint.
- `test_registry.py` / `test_registry_writethrough.py`: `JobRecord.user_id` round-trips
  through `_to_row`/`from_row`; write-through persists it (AC-A8 substrate); pass-throughs
  forward the arg.
- `test_api_analyze.py`: after `POST /api/analyze` as the authed user, the stored `JobRow`'s
  `user_id` equals that user's id (AC-A1).
- **`test_isolation.py` (NEW, the core):** build two authenticated clients (users A and B via
  `authenticate_as`). A uploads/creates a job; assert **B's** `GET /api/jobs` is empty and
  `total==0` (AC-A2); **B** `GET /api/jobs/{A's id}` → `404`, and `.../report` + `.../events`
  → `404` (AC-A3/A4); **A** still gets `200` for all three; `GET /api/dashboard` for B is
  all-zero while A's reflects its jobs (AC-A5). Seed a `user_id=NULL` row directly and assert
  it appears for neither (AC-A6). A second signup while A exists succeeds and B's workspace is
  empty (AC-A7).
- `test_dashboard_endpoints.py`: scoped aggregation; empty-account all-zero payload (AC-A5/EC-5).
- `test_auth_endpoints.py`: **replace** `test_two_accounts_share_jobs` with
  `test_two_accounts_isolated` (disjoint jobs) — the endpoint contract changed (AC-A(t));
  keep all other auth assertions.
- **No new graph test**; `test_runner_graph_untouched.py` and `test_alembic_head.py` (now at
  head `0004`) stay green (AC-A9).

**Frontend (Vitest + RTL, mock provider unless noted).**
- `landing.test.tsx` (MODIFIED): hero + CTA (→`/login`), Log In/Sign Up (→`/login`), the full
  feature grid, a "How it works" section, closing CTA, and **no sidebar** (AC-B1/B2). Pricing/
  Blog inert.
- `authView.test.tsx` (MODIFIED): split layout host renders; underline tabs switch forms
  (AC-B3); login/signup submit + `401/409/422` error mapping + `replace('/dashboard')` on
  success (AC-B4); Google/Microsoft disabled + Forgot inert (AC-B5).
- `emptyStates.test.tsx` (NEW): with a zero-jobs fake client, dashboard + reports render the
  "upload your first contract" empty state (AC-B6).
- `auth-boundary.test.ts` (existing): still passes — no provider import in
  `components/auth`/`components/marketing` (AC-B5).
- Existing 013/015/017/018 suites stay green (mock fixtures unchanged).

**Live smoke (AC-A10):** `provider=real`; sign up A, upload, see it in A's dashboard/jobs;
sign up B → B empty and `404` on A's job/report by id; back as A intact. Reset `.env.local`
to `mock` after.

**Security review of the diff:** run `/security-review` before merge (ownership checks are
security-sensitive — verify no read path bypasses the `user_id` scope / 404 rule).

---

## 6. Implementation order (TDD — constitution §7)

0. **Docs:** amend `specs/000-constitution.md` §2 with the spec-§7 amendment text
   (per-user isolation IN; RBAC/roles/teams/sharing still CUT). (No app code yet — §1.)
1. **Migration:** `0004_add_jobs_user_id.py`; extend `test_alembic_head.py` expectations to
   head `0004`.
2. **Store (red→green):** `test_job_store.py`/`test_store_list.py` for `user_id` round-trip +
   scoped `list/all/count` (incl. NULL exclusion) written failing; then add `JobRow.user_id`,
   `_encode/_decode`, upsert cols, and the `WHERE user_id=?` filters.
3. **Registry:** `test_registry*.py` for `user_id` on `JobRecord` + pass-throughs failing;
   then thread it through `_to_row`/`from_row` and `list_jobs/all_rows/count`.
4. **Routes:** `test_isolation.py` + `test_api_analyze.py` scoping assertions failing; then
   stamp `user_id` in `analyze`, scope `list_jobs`/`dashboard`, and add `_owned_or_404` to the
   three by-id handlers. Flip `AUTH_SIGNUP_OPEN=True`.
5. **Migrate existing integration tests:** update `test_api_jobs.py`,
   `test_dashboard_endpoints.py`, and replace the `test_auth_endpoints.py` share test; add the
   `authenticate_as`/`current_user_id` conftest helpers. Run the **whole backend suite** green.
6. **Frontend Part B:** rewrite `LandingView` (+ section components) and `AuthView`
   (+ brand panel); add the aurora keyframes; polish empty states. Update
   `landing.test.tsx`/`authView.test.tsx` (same behavior), add `emptyStates.test.tsx`.
7. **Verify:** `pytest` (whole), `vitest run` (whole), `tsc --noEmit`, `npm run lint`,
   `next build` (dev STOPPED). Confirm no `backend/app/graph/` change (AC-A9).
8. **Security review** (`/security-review`) + **live smoke** (AC-A10). Reset `.env.local`
   to `mock`.

Each step's tests are written failing first (§7). Step 5's edits to existing integration
tests are the sanctioned test *modifications* — the endpoint contract legitimately changed
from shared to scoped; assertions are inverted/tightened, never weakened to force a pass.

---

## 7. Notes / risks

- **Direct-seed integration tests break silently if not stamped.** Any existing test that
  writes a `JobRow` **directly** into the store and then expects it via `GET /api/jobs` or
  `/api/dashboard` will now get an **empty** result (its seeded rows are `user_id=NULL` →
  hidden). Fix: seed with the authenticated user's id (via a `current_user_id(client)` helper
  that calls `/api/auth/me`, or seed through `POST /api/analyze` which auto-stamps). This is
  the single most likely source of surprise failures — call it out in tasks.md for every
  touched integration test.
- **SQLite `drop_column`** needs `op.batch_alter_table` (no in-place drop); `add_column` is
  native. Downgrade is rarely run but must be correct (§3.1).
- **`aggregate.py` stays pure and untouched** — scoping is entirely at the read boundary
  (store filter + which rows the route hands it). Do not add user logic to aggregate.
- **`AUTH_SIGNUP_OPEN` flip** makes the 014 fixture overrides that force it `True` redundant;
  leave or remove them, but don't let a lingering `False` override mask AC-A7.
- **Ownership check must precede side effects** — check `_owned_or_404` **before** opening the
  SSE stream or returning the `FileResponse` (AC-A4), not after.
- **No boundary/`types.ts` change** — `user_id` never crosses the wire; if a test or reviewer
  expects it in `JobStatus`/`JobListItem`, that's wrong by design (ownership is server-only).
- **Redesign must preserve 014 behavior** — the `authView`/`landing` tests keep their
  behavioral assertions (CTAs→/login, disabled SSO, inert forgot, error mapping); only
  structure/markup changes. Don't weaken those assertions to fit new markup.
- **`next build` vs `next dev`** — never build while dev runs (013/015 lesson); step 7 builds
  with dev stopped.
- **Retention is still global** (EC-7) — `prune` may evict across accounts; per-user quotas
  are explicitly out of scope. Don't "fix" this here.

---

*Per constitution §1/§11, a `feature/019-multi-tenant-data` branch opens only after this
plan.md and its spec.md are approved and `tasks.md` exists. No `tasks.md` or implementation
was written in this pass — plan only.*
