# Feature 053 — Render + Turso deploy wiring (the $0 durable deploy)

Branch: `feature/053-render-deploy-wiring` (per constitution §11).

## 1. Problem statement

Features 048–052 made the app deploy-ready and durable behind env switches (CORS/SameSite/OAuth URLs,
HF embeddings, Groq generation, Turso store + report BLOBs). This final feature **wires them together for
an actual Render + Turso deploy**: a `render.yaml` blueprint, the container fixes needed for the Turso +
HF path to work in prod, the complete prod env surface, and a rewritten `docs/DEPLOYMENT.md` runbook
(replacing the Oracle plan) with the go-live checklist that folds in the deferred Linux validations
(050 AC-10, 051 AC-10, 052 AC-9, Dockerfile build).

**Resume-on-boot already exists** (feature 012: `main.py::_recover` enumerates `store.nonterminal()` and
re-enqueues jobs on startup, with `test_recover_missing_upload.py` already covering the
ephemeral-upload-after-restart case 052 created) — so this feature adds **no** recovery code, only
documents the behavior.

### Real correctness items this feature fixes (grounded)
1. **Container migration hits the wrong DB on Turso.** `docker-entrypoint.sh` runs the **alembic CLI**
   (`alembic upgrade head`), which uses the `alembic.ini` placeholder URL (local SQLite) — NOT the
   Turso-aware `app.runner.migrations.upgrade_to_head` the lifespan uses. On Turso the entrypoint would
   migrate a throwaway local file. Fix: the entrypoint must run the **Turso-aware** migration (call
   `upgrade_to_head`) or defer entirely to the lifespan (which already migrates correctly).
2. **The FAISS KB index is not in the image.** The `Dockerfile` copies `app/` + `alembic/` but **not**
   `data/kb/clauses.faiss` — so `kb_retriever.load_kb()` finds nothing and every clause uses web
   fallback (degraded CRAG). Fix: `COPY data/kb ./data/kb` (the index must be **HF-rebuilt** first, per
   050 AC-10 — the go-live checklist orders this).
3. **Pinned secrets or data loss on restart.** On Render's ephemeral disk, `AUTH_SECRET` (JWT signing)
   and `CONTRACTSENTINEL_ENCRYPTION_KEY` (Fernet, feature 032: env > key file > generate) regenerate on
   every restart unless pinned via env — which would invalidate all sessions and make **all
   Turso-stored encrypted OAuth tokens undecryptable**. The blueprint + runbook must make pinning these
   loud and mandatory.

### Position relative to the constitution
No LangGraph node/edge change, no `ContractState` change, no new migration. The only app-adjacent code
is a shell-script fix (`docker-entrypoint.sh`) and an optional startup config guard; everything else is
deploy config (`render.yaml`, `Dockerfile`, `.env.example`) and docs. Fully reversible — none of it
changes local-dev behavior (local runs ignore `render.yaml` and keep the default env). Developed on
`feature/053-render-deploy-wiring`, the last of the 048→053 deploy chain.

## 2. Inputs and outputs

No `ContractState` change. The deliverables:

### 2.1 NEW `render.yaml` (repo root) — Render Blueprint
A single web service:
- built from `backend/Dockerfile` (Docker runtime, `rootDir: backend` or the equivalent Docker context),
- `healthCheckPath: /api/health` (the existing public endpoint — also the keep-alive target),
- env vars: the non-secret config inline (`LLM_PROVIDER=groq`, `EMBED_PROVIDER=hf`,
  `AUTH_COOKIE_SECURE=true`, `AUTH_COOKIE_SAMESITE=none`, `CORS_ALLOWED_ORIGINS`,
  `GOOGLE_OAUTH_REDIRECT_URI`, `FRONTEND_INTEGRATIONS_URL`, model names, MCP toggles), and the **secrets
  as `sync: false`** (set in the dashboard, never committed): `AUTH_SECRET`,
  `CONTRACTSENTINEL_ENCRYPTION_KEY`, `GROQ_API_KEY`, `HF_API_TOKEN`, `TURSO_DATABASE_URL`,
  `TURSO_AUTH_TOKEN`, and the Google OAuth client secret.

### 2.2 `docker-entrypoint.sh` — Turso-aware migration
Replace the raw `alembic upgrade head` (CLI, wrong URL on Turso) with the Turso-aware Python helper
(`python -c "from app.runner.migrations import upgrade_to_head; import app.config as c;
upgrade_to_head(c.JOB_STORE_DB_PATH)"`) — the SAME migration the lifespan runs, so it targets Turso when
configured and local SQLite otherwise. (Alternative: drop the entrypoint migration and rely solely on
the lifespan's `upgrade_to_head`; decided in the plan.)

### 2.3 `Dockerfile` — ship the KB index
Add `COPY data/kb ./data/kb` so `CRAG_KB_INDEX_PATH` resolves in the container (local KB retrieval works
instead of all-web-fallback). **`data/kb/` (incl. `clauses.faiss`) is already tracked in git** — only
`data/kb/sources/`, `data/reports/`, `data/uploads/`, `data/secrets/`, and `data/*.db` are gitignored —
so `COPY data/kb` copies the committed artifact directly at build time (no CI/pre-build step needed). The
real decision (D3 / Open Question 4): ship the **currently-committed bge-m3-built** index, or **re-build
it via HF first** (050 AC-10) so the indexed vectors match the prod HF query embeddings — the runbook
orders rebuild-then-image-build for retrieval correctness.

### 2.4 `.env.example` — complete prod env surface
Add the deploy vars introduced by 046–052 that aren't yet documented there: `LLM_PROVIDER`,
`GROQ_API_KEY`, `GROQ_MODEL`, `EMBED_PROVIDER`, `HF_API_TOKEN`, `HF_EMBED_MODEL`, `TURSO_DATABASE_URL`,
`TURSO_AUTH_TOKEN`, `AUTH_SECRET`, `CONTRACTSENTINEL_ENCRYPTION_KEY`, `CORS_ALLOWED_ORIGINS`,
`AUTH_COOKIE_SECURE`, `AUTH_COOKIE_SAMESITE`, `GOOGLE_OAUTH_REDIRECT_URI`, `FRONTEND_INTEGRATIONS_URL` —
each with a one-line comment and a **placeholder** (never a real secret; `.env` stays gitignored).

### 2.5 `docs/DEPLOYMENT.md` — Render + Turso runbook (rewrite)
Replace the Oracle plan with the Render + Turso architecture: the blueprint, the **mandatory pinned
secrets** (with the data-loss warning), the Turso setup (DB + DB-scoped token), the HF token, the Groq
token, the **keep-alive cron** (cron-job.org → `/api/health` every ~10 min, to defeat the 15-min spin-down),
the Vercel/Cloudflare frontend + OAuth-redirect reconfiguration, and a **go-live checklist** that orders
the deferred Linux validations: (a) 050 AC-10 rebuild `clauses.faiss` via HF + retrieval eval, (b) 051
AC-10 `alembic upgrade head` replays 0001–0009 on Turso + restart-survival, (c) 052 AC-9 report-BLOB
durability across restart, (d) Dockerfile build validation. Keep the honest caveats (Groq token/day cap,
HF free-tier reliability, Turso free tier, "not legal advice").

### 2.6 Startup prod-config guard (INCLUDED — D6)
A small fail-fast check in the lifespan: if `EMBED_PROVIDER=hf` then `HF_API_TOKEN` must be non-empty; if
`LLM_PROVIDER=groq` then `GROQ_API_KEY`; if `TURSO_DATABASE_URL` set then `TURSO_AUTH_TOKEN`; and — given
the data-loss risk (EC-1) — if `TURSO_DATABASE_URL` is set, warn when `CONTRACTSENTINEL_ENCRYPTION_KEY`
is not pinned via env (only the generated key-file). Each adapter already raises lazily on first use;
this centralizes the check to fail at boot with one clear message (no secret echoed). This is the one
`app/`-touching change in 053 and is an in-scope deliverable (resolves the prior open question).

## 3. Resolved decisions (inline)
- **D1 — Reuse existing switches; no new runtime behavior.** 053 only wires 046–052's env flags; it adds
  no feature flag of its own. Local dev is unchanged (ignores `render.yaml`).
- **D2 — Turso-aware container migration** (§2.2) so `alembic upgrade head` targets the right DB in the
  Linux image (where `sqlalchemy-libsql` is installed via the 051 marker).
- **D3 — Ship the HF-built KB index in the image** (§2.3) so CRAG local retrieval works in prod.
- **D4 — Secrets are `sync: false`** in `render.yaml` (dashboard-set), never committed; the runbook
  makes `AUTH_SECRET` + `CONTRACTSENTINEL_ENCRYPTION_KEY` pinning mandatory (data-loss otherwise).
- **D5 — Resume-on-boot is feature 012** — documented, not rebuilt.
- **D6 — Include the startup prod-config guard** (§2.6) — a small hf/groq/turso/encryption-key presence
  check at boot; the one `app/`-touching change, low-risk, catches the most common deploy misconfig.

## 4. Acceptance criteria

### Static / unit-checkable (no live deploy)
- **AC-1 (`render.yaml` valid + complete):** a test parses `render.yaml` (YAML) and asserts one web
  service with `healthCheckPath: /api/health`, the Docker build, the inline non-secret env keys present, and
  every required secret listed with `sync: false` (no secret VALUES committed).
- **AC-2 (entrypoint Turso-aware):** `docker-entrypoint.sh` no longer calls the bare `alembic upgrade
  head` CLI; it invokes `upgrade_to_head` (asserted by a text check on the script), so the container
  migration targets Turso when configured.
- **AC-3 (Dockerfile ships the KB index):** the `Dockerfile` contains `COPY data/kb` (asserted by a text
  check) so `CRAG_KB_INDEX_PATH` resolves in the image.
- **AC-4 (`.env.example` complete):** a test asserts `.env.example` documents every deploy var in §2.4
  (keys present) and contains **no** real secret values (only placeholders).
- **AC-5 (`docs/DEPLOYMENT.md` rewritten):** greppable content checks — "Render" and "Turso" appear;
  "Oracle" is not the active plan; `AUTH_SECRET` and `CONTRACTSENTINEL_ENCRYPTION_KEY` both appear in a
  mandatory-pinning / data-loss context; `/api/health` appears as the keep-alive target; and the four
  deferred validations (050 AC-10, 051 AC-10, 052 AC-9, Dockerfile build) are each named.
- **AC-6 (no regression):** whole `pytest` green; no app-behavior change on the default (local) env; the
  startup guard (AC-7) does not fire in the suite (which sets no prod env).
- **AC-7 (startup guard, INCLUDED):** with `EMBED_PROVIDER=hf` and empty `HF_API_TOKEN` (resp. groq /
  turso), startup raises a clear error naming the missing var (no token echoed); with the test defaults
  (all providers local, no Turso) it is a no-op so the suite is unaffected.

### Live (AC-8 — the actual Render deploy; operator-run, deferred)
- **AC-8:** following the runbook: Turso DB migrated (0001–0009), image built with the HF index, service
  live behind `/api/health`, keep-alive configured; register→login→upload→analyze→download works; a Render
  restart preserves accounts + job history + reports (051/052 durability); Drive/Gmail delivery works
  with the reconfigured OAuth redirect. Recorded in `docs/DEPLOYMENT.md` go-live results.

## 5. Edge cases
- **EC-1 — encryption key not pinned:** if `CONTRACTSENTINEL_ENCRYPTION_KEY` is unset in prod, a restart
  regenerates it → Turso-stored OAuth-token ciphertext is undecryptable. The runbook flags this as
  mandatory; the startup guard (AC-7, D6) warns if it's unset while `TURSO_DATABASE_URL` is set.
- **EC-2 — KB index provider mismatch:** the committed `clauses.faiss` is bge-m3-built; if shipped
  without the HF rebuild (050 AC-10) while `EMBED_PROVIDER=hf`, the index/query vectors differ → the 052
  `.provider` marker warns and retrieval degrades (not a crash). The go-live checklist orders the HF
  rebuild before the image build. (A genuinely absent index → `load_kb` None → all-web fallback.)
- **EC-3 — keep-alive stops:** the free service spins down after 15 min; the next request cold-starts
  (~1 min). Documented, not code.
- **EC-4 — migration replay fails on Turso:** surfaced by `upgrade_to_head` (051 EC-2) at container
  start; the go-live checklist runs it first (051 AC-10).
- **EC-5 — Render free Postgres is NOT used** (Turso is the DB) — the blueprint declares no Render DB;
  ensure no `DATABASE_URL`-style Render DB is implied.
- **EC-6 — wrong Docker build context:** the Dockerfile's `COPY data/kb`/`COPY app` are backend-relative,
  so `render.yaml` must set the build context to `backend/` (Open Question 3); a wrong `rootDir` fails
  the build at `COPY` — a common blueprint mistake, checked in the go-live build validation.

## 6. Out of scope
- Any change to the analysis pipeline, storage, or auth (046–052 own those; 053 only wires their flags).
- Building resume-on-boot (exists — feature 012) or a durable checkpointer (051 accepted-ephemeral).
- Automating the external steps (Turso/HF/Groq signup, Render service creation, OAuth reconfiguration,
  keep-alive cron) — these are operator steps the runbook documents.
- Frontend deploy specifics beyond the OAuth-redirect/URL reconfiguration already covered by 048/049.
- CI/CD auto-deploy on push — the blueprint enables manual/dashboard deploys; auto-deploy is a later
  option.

## 7. Open questions
1. ~~Include the §2.6 startup guard?~~ **RESOLVED — included (D6).** A small hf/groq/turso/
   encryption-key presence guard at boot; low-risk, catches the most common deploy misconfig.
2. **Entrypoint: Turso-aware migration vs drop-and-rely-on-lifespan.** Both work — the lifespan
   **already** runs `upgrade_to_head(JOB_STORE_DB_PATH)` unconditionally (`main.py:67`), so dropping the
   entrypoint migration skips nothing. Recommend the entrypoint call `upgrade_to_head` anyway so a
   migration failure stops the container before serving (clear failure) rather than at first request.
   Plan decides.
3. **`render.yaml` Docker context** — `rootDir: backend` with `dockerfilePath: Dockerfile`, vs a
   repo-root Dockerfile path. The Dockerfile's `COPY data/kb`/`COPY app` are backend-relative, so the
   build context must be `backend/` (EC-6). Plan pins the exact `render.yaml` fields against Render's
   current Blueprint schema.
4. **Ship the committed index vs HF-rebuild first.** The index IS committed (`data/kb/clauses.faiss`,
   not gitignored), so `COPY data/kb` just works. The genuinely-open question is whether to ship the
   currently-committed **bge-m3-built** index or **re-build it via HF** (050 AC-10) so the indexed
   vectors match the prod HF query embeddings. Recommend rebuild-then-image-build (the runbook orders
   it). Confirm.
