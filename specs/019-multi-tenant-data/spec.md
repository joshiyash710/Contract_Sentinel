# Feature 019 — Per-User Data Isolation (Multi-Tenant) + Landing/Auth Redesign

## 1. Problem statement

Two problems surfaced by the owner after 014 shipped, bundled here because both are
about making the product a real, trustworthy AI-SaaS:

1. **Shared data is wrong for a real product.** Feature 014 deliberately built a
   *single-user gate with one shared data space* (014 **D4 / AC-10**; the constitution §2
   amendment explicitly cut per-user scoping). In practice this means **any** account that
   logs in sees **every** job, report, and dashboard number in the system — two accounts see
   each other's contracts. The owner wants each account to see **only its own** uploaded
   contracts, reports, and dashboard metrics: **per-user data isolation** (lightweight
   multi-tenancy) — one private workspace per account, partitioned by owner.

2. **The landing / login / sign-up pages must look like a premium AI-SaaS product.** 014
   shipped functional pages matching the reference mockups' skeleton but missing the hero
   illustration, the second feature row, and the textured auth background. The owner wants to
   push **beyond** the reference mockups to a more polished, premium look.

### Position relative to the constitution

**Part A requires a new constitution amendment** (proposed text in §7). It narrows the
"PERMANENTLY CUT — multi-tenant access control" line and reverses 014's "NOT per-user data
scoping" stance: **per-user data ownership/partitioning is now IN scope.** What stays
**permanently cut**: RBAC, roles, permission grants, teams/orgs, cross-account sharing or
collaboration, and any tenant-admin surface. Every account is a **flat, private,
single-owner workspace** with no cross-account visibility.

Part A adds **no LangGraph node/edge and no `ContractState` field** (constitution §2/§4) —
the 7-node pipeline is untouched; this is a persistence + API-scoping change. Part B is
frontend-only. Per §11 both are developed on `feature/019-multi-tenant-data`.

---

## 2. Part A — Per-user data isolation (backend)

### 2.1 Data model change

- **Alembic migration `0004`** (`down_revision = "0003"`), in `data/job_store.db`: add a
  **`user_id` TEXT (nullable)** column to the `jobs` table. It holds the `users.id` of the
  account that created the job.
- **Existing pre-019 rows have `user_id = NULL`.** No live account has a NULL id, so those
  rows are **never returned by any scoped read** — they become legacy/hidden, and each
  account starts from a clean, empty workspace. They are **preserved on disk** (not deleted);
  a future migration could assign them if ever wanted. This realizes the owner's chosen
  option ("existing shared jobs become legacy/hidden").
- The column is added **nullable** (SQLite cannot add a NOT NULL column without a default to
  an existing table, and NULL is exactly the "legacy/unowned" marker we want).

### 2.2 Ownership stamped on create

- `POST /api/analyze` reads the authenticated user via `require_auth` and stamps the new job
  with `user_id = current_user.id`. `JobRecord` and `JobRow` gain a `user_id` field that is
  written on the initial durable insert and every write-through persist (so a job's owner is
  durable across restarts).

### 2.3 Scoped reads — the core of the feature

Every read endpoint filters by the authenticated user's id:

| Endpoint | Scoping behavior |
| --- | --- |
| `GET /api/jobs` | Returns **only the caller's** jobs; both the page and the `total` count are scoped. |
| `GET /api/dashboard` | Metrics aggregated over **only the caller's** jobs. A brand-new account sees a **real empty dashboard** (zeros + empty state), never demo numbers. |
| `GET /api/jobs/{id}` | `404` if the job does not exist **or** is not owned by the caller. |
| `GET /api/jobs/{id}/events` | Ownership checked (same `404`) **before** the SSE stream opens. |
| `GET /api/jobs/{id}/report` | Ownership checked (same `404`) **before** the file is served. |

**Ownership failures return the same `404` as "not found"** — a caller can't distinguish
"job doesn't exist" from "job exists but is someone else's," so job-ids don't leak across
accounts (D-A3).

### 2.4 Signup reopens (multi-user)

- Full multi-tenancy needs multiple accounts, so **`AUTH_SIGNUP_OPEN` returns to `True`**
  (open signup). The security rationale that closed it in the 014 post-review (open signup on
  a *shared* data space = anyone who reaches the app sees everything) is **nullified by
  isolation**: a new account now sees only its own empty workspace. `AUTH_SIGNUP_OPEN=False`
  remains as a lock-down lever (e.g. after the intended accounts exist). See EC-6.

### 2.5 Background processing / recovery unchanged

- Startup recovery (`JobStore.nonterminal()`) resumes in-flight jobs **regardless of owner** —
  there is no user session at process start, and a half-run pipeline must finish. A resumed
  job keeps its stored `user_id`, so once it completes it appears only in its owner's views.
  Recovery logic is otherwise unchanged; the `user_id` column is simply carried through.

### 2.6 Seam impact (where the change lives)

- `JobRow` (store) + `JobRecord` (registry): add `user_id`; thread through `_encode`/`_decode`,
  `_to_row`, `from_row`.
- `JobStore.list/all/count`: gain a `user_id` filter (`WHERE user_id = ?`). `JobStore.get`
  still fetches by `job_id` (ownership is checked in the handler so the same `404` path covers
  both cases and rehydration keeps working).
- `JobRegistry.list_jobs/all_rows/count`: pass the `user_id` through to the store.
- `routes.py` handlers: each gains `current_user: AuthUser = Depends(require_auth)` (the
  dependency is already applied router-level; adding the param just surfaces the value — FastAPI
  evaluates it once per request) and uses `current_user.id` for stamping / scoping / ownership.
- `aggregate.py`: unchanged in logic — it already aggregates whatever rows it's handed; it's now
  handed only the caller's rows.
- **No graph/pipeline/`ContractState` change** (AC-A9).

---

## 3. Part B — Landing / Auth premium redesign (frontend)

Push **beyond** the reference mockups (`…31 PM.jpeg` landing, `…31 PM (1).jpeg` auth) to a
premium AI-SaaS look, reusing the 013 design-system tokens (no new color system). All 014
decisions that still hold are preserved: SSO buttons disabled (014 D6), Forgot-Password inert
(014 D7), landing CTAs → `/login` (014 D8), marketing pages render shell-free in the
`(marketing)` route group (014 D16), and no marketing/auth component imports a provider
directly (013 seam / 014 AC-19).

### 3.1 Landing page (`/`)

- **Sticky top nav** — logo + Features / Integrations (on-page anchors) / Pricing / Blog
  (inert placeholders, 014 D8) + Log In / Sign Up (→ `/login`); gains a subtle
  translucent/blur treatment.
- **Hero** — large gradient headline ("AI-Powered Legal Contract Intelligence"), subcopy,
  primary CTA "Analyze Your First Contract (Free)" (→ `/login`) + a secondary "See how it
  works" anchor, over a subtle animated aurora/gradient dark background. Includes the **hero
  visual** the current build lacks: the shield + layered-documents artwork with a glow
  (recreated with layered SVG/CSS, no external asset dependency).
- **Feature grid** — the full set the ref shows (the four primary cards — Risk Scoring,
  Clause-by-Clause Explanation, Contract Comparison, Integration Ecosystem — plus a second
  row), each with a gradient icon chip and a hover-lift.
- **"How it works"** — a 3-step strip (Upload → AI analyzes → Get your report), new vs. the
  ref, to read as a real product page.
- **Closing CTA band + minimal footer** — final "Get started" call-to-action and a light
  footer (links inert where no page exists — no fabricated destinations, 014 D8).

### 3.2 Auth page (`/login`)

- **Split two-column layout on wide screens** (push beyond the ref's single card): a left
  **brand panel** (logo, one-line value prop, a subtle testimonial/stat, aurora background)
  and the right **form card**; collapses to the single centered card on mobile.
- **Underline-style Login / Sign Up tabs** (matching the ref) with an animated active
  indicator, replacing the current pill tabs.
- **Fields** — Work Email + Password (show/hide eye), inert "Forgot password?" (014 D7),
  gradient "Continue to ContractSentinel" submit with a loading state, "Or continue with"
  divider, and **disabled** Google / Microsoft buttons with real brand glyphs (014 D6).
- **Inline error + validation states** — bad credentials / existing email / weak password map
  to the existing messages (014 AC-13/14), styled as polished inline alerts.

### 3.3 Consequence of Part A on the app screens

Because reads are now scoped, a freshly signed-up account lands on `/dashboard` with **its
own (initially empty) data**. The dashboard / reports / contracts **empty states** must be
polished "upload your first contract" states (extending 018's real empty states), since every
new account now legitimately starts empty — no demo/placeholder numbers on the real provider.
(The **mock** provider keeps returning fixtures for tests/dev; that is unchanged.)

---

## 4. Acceptance criteria

Backend → pytest (TestClient). Frontend → Vitest + RTL (mock provider unless noted). Real
scoped flow → live smoke (AC-A10).

### Part A — backend isolation

- **AC-A1:** `POST /api/analyze` while authenticated as user *U* creates a job whose
  persisted `user_id == U.id` (assert on the stored `JobRow`).
- **AC-A2:** `GET /api/jobs` returns only jobs owned by the caller; a second account *V* with
  its own jobs sees a disjoint list, and each `total` reflects only that account's jobs.
- **AC-A3:** `GET /api/jobs/{id}` for a job owned by **another** account returns **`404`**
  (identical to a nonexistent id — no existence leak); the owner gets `200`.
- **AC-A4:** `GET /api/jobs/{id}/report` and `GET /api/jobs/{id}/events` for a non-owned job
  return `404` **before** any file is served / stream is opened; the owner gets the normal
  `2xx`.
- **AC-A5:** `GET /api/dashboard` aggregates only the caller's jobs — a brand-new account gets
  an all-zero / empty-state payload while another account with completed jobs gets non-zero
  metrics from the same server.
- **AC-A6:** Pre-019 rows (`user_id = NULL`, seeded directly) are returned by **no** scoped
  read for any authenticated account (jobs list, dashboard, get-by-id all exclude them).
- **AC-A7:** `AUTH_SIGNUP_OPEN` defaults to `True` again; a second account can sign up while a
  first account exists, and lands on an **empty** workspace (its own).
- **AC-A8:** Recovery/`nonterminal` still resumes a stored in-flight job and preserves its
  `user_id` (a rehydrated job round-trips its owner).
- **AC-A9:** No file under `backend/app/graph/` is modified; no `ContractState` field is added.

### Part A — test-impact (intentional §7 changes)

- **AC-A(t):** 014's `test_two_accounts_share_jobs` (AC-10, shared data) is **replaced** by an
  isolation test (two accounts, disjoint data) — the endpoint contract legitimately changed,
  so the assertion is inverted, not weakened. Store/registry/aggregate tests are updated for
  the new `user_id` parameter with **behavior preserved** (scoping added, nothing removed).

### Part B — landing & auth UI

- **AC-B1:** `/` renders shell-free (marketing group) with: the hero + CTA (→ `/login`), the
  hero visual, the full feature grid, a "How it works" section, and a closing CTA — all
  without an app sidebar.
- **AC-B2:** Landing "Analyze Your First Contract", "Log In", and "Sign Up" all navigate to
  `/login`; Pricing / Blog remain inert (no navigation / no fabricated route).
- **AC-B3:** `/login` renders the split brand-panel + form layout on wide screens (single card
  on mobile), with underline Login / Sign-Up tabs that switch the active form.
- **AC-B4:** Login submit calls `apiClient.login`; success → `/dashboard`; `401` → inline
  "invalid email or password", no navigation. Sign-Up submit calls `apiClient.signup`; success
  → `/dashboard`; `409` → "account already exists"; `422` → password-policy message. (014
  AC-13/14 behavior preserved through the redesign.)
- **AC-B5:** Google / Microsoft buttons are `disabled`; "Forgot password?" is inert (no
  navigation). No `realProvider`/`mockProvider` import in `components/marketing` or
  `components/auth` (seam boundary preserved).

### Part A — frontend consequence

- **AC-B6:** With the **mock** provider unchanged (fixtures) existing dashboard/reports tests
  stay green; the dashboard/reports/contracts **empty states** render a polished "upload your
  first contract" state when the client returns zero jobs (asserted with an empty fake client).

### Live end-to-end (real backend)

- **AC-A10 (smoke, manual/gated):** With `provider=real`: sign up account **A**, upload a
  contract, see it in A's dashboard/jobs; sign up account **B** (fresh) → B's dashboard/jobs
  are **empty** and B gets `404` fetching A's job/report by id; back as A the data is intact.
  Confirms server-side scoping through the Next proxy.

---

## 5. Edge cases

- **EC-1 — Non-owned job id guessed/enumerated** → `404` for get / report / events (identical
  to nonexistent). Ownership never returns `403` (which would confirm existence).
- **EC-2 — Job created before login state changes** → ownership is stamped at create time from
  the session; there is no re-assignment. A job always belongs to whoever uploaded it.
- **EC-3 — Legacy NULL-owner rows** → excluded from every scoped read (§2.1 / AC-A6); not
  deleted. Startup recovery may still resume a NULL-owner in-flight legacy job (it completes
  and then, being NULL-owner, is visible to no one) — acceptable, documented.
- **EC-4 — Two accounts, same uploaded file** → two independent jobs with different `user_id`;
  no dedup across accounts (each workspace is private).
- **EC-5 — Dashboard/aggregate for an empty account** → returns a valid all-zero payload (no
  divide-by-zero, no crash), driving the empty state.
- **EC-6 — Open signup exposure** → with `AUTH_SIGNUP_OPEN=True`, anyone who can reach the app
  can self-provision, but a new account sees **only its own** (empty) workspace — the 014
  shared-data exposure is gone. `AUTH_SIGNUP_OPEN=False` closes signup after provisioning.
- **EC-7 — Retention prune across owners** → `JobStore.prune` (global oldest-first retention
  cap) may still evict rows across accounts; retention remains a **global** cap, not per-user
  (per-user quotas are out of scope). Documented so it isn't a surprise.
- **EC-8 — Expired/again-unauthenticated mid-use** → unchanged 014 behavior: the next scoped
  call `401`s and the app redirects to `/login`.

---

## 6. Out of scope

- **RBAC, roles, permission grants, teams/orgs, cross-account sharing/collaboration, tenant
  admin** — permanently cut (see the §7 amendment). Every account is a flat private workspace.
- **Per-user quotas / per-user retention** — retention stays a global cap (EC-7).
- **Account management** (change email/password, delete account & its data, profile editing),
  **2FA, rate limiting/lockout, CAPTCHA, password reset, SSO** — unchanged from 014's
  out-of-scope; not built here.
- **Re-assigning legacy NULL-owner jobs** to an account — not done (they stay hidden).
- **Any graph/node/state change** — none (AC-A9).
- **New color system / design tokens** — Part B reuses the 013 design system.

---

## 7. Proposed constitution amendment (§2)

To be added under §2 (alongside the 2026-07-14 / feature-014 amendment), pending approval:

> **AMENDMENT (2026-07-14, feature 019) — per-user data isolation is now IN scope.**
> This narrows the "multi-tenant access control" item in PERMANENTLY CUT and reverses feature
> 014's "one shared data space / NOT per-user data scoping" stance (014 D4/AC-10). Each
> authenticated account now **privately owns the contracts it uploads**: every data read
> (`/api/jobs`, `/api/dashboard`, `/api/jobs/{id}` and its `report`/`events`) is **scoped to
> the owning account**, and a job is stamped with its creator's `user_id` at upload. What
> remains **permanently cut**: RBAC, roles, permission grants, teams/orgs, cross-account
> sharing or collaboration, and any tenant-admin surface — there is **no cross-account
> visibility and no access-control matrix**; every account is a flat, single-owner, private
> workspace. This adds no LangGraph node/edge and no `ContractState` field. Legacy rows created
> before this feature (no owner) are hidden from all accounts, not migrated. Open signup is
> re-enabled (`AUTH_SIGNUP_OPEN=True`) because isolation removes the shared-data exposure that
> justified closing it.

---

## 8. Notes for plan.md / tasks.md (not decisions — pointers)

- Migration `0004` adds `jobs.user_id`; the Alembic chain already runs on startup
  (`upgrade_to_head(JOB_STORE_DB_PATH)`), and pulling this feature requires `alembic upgrade
  head` (as with 0002/0003).
- TDD (§7): the isolation ACs (A2/A3/A5/A6) are written failing first; the 014 shared-data
  test is intentionally replaced (AC-A(t)).
- Store/registry/aggregate signatures gain a `user_id` param — all their existing tests are
  updated to pass it, behavior preserved.
- Part B keeps every 014 auth behavior (D6/D7/D8/D16, error mapping, seam) — the redesign is
  visual; the existing `authView`/`landing` tests are updated for the new structure with the
  same behavioral assertions.
