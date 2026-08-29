# Feature 053 — Technical plan: Render + Turso deploy wiring

Branch: `feature/053-render-deploy-wiring` (per constitution §11).

Derived from `spec.md` (spec-reviewer-APPROVED). Wires 046–052's env switches into an actual Render +
Turso deploy: a `render.yaml` blueprint, a Turso-aware container migration, the KB index in the image,
the full prod env surface, a `docs/DEPLOYMENT.md` rewrite, and one small startup prod-config guard.
Resume-on-boot already exists (feature 012). No graph/edge/`ContractState`/migration change.

## 0. Scope of change (files touched)
```
render.yaml                              (NEW — repo-root Render Blueprint)
backend/docker-entrypoint.sh             (Turso-aware migration; was bare `alembic upgrade head` CLI)
backend/Dockerfile                       (COPY data/kb ./data/kb)
backend/.env.example                     (full prod env surface, placeholders only)
backend/app/api/main.py                  (call _validate_prod_config() in the lifespan — the only app/ code)
backend/app/config.py                    (NEW _validate_prod_config() helper OR put it in main.py — plan §4)
docs/DEPLOYMENT.md                       (rewrite: Oracle → Render + Turso runbook + go-live checklist)
backend/tests/unit/test_render_blueprint.py   (NEW — AC-1)
backend/tests/unit/test_env_example.py        (NEW — AC-4)
backend/tests/unit/test_deployment_doc.py     (NEW — AC-5)
backend/tests/unit/test_prod_config_guard.py  (NEW — AC-7)
backend/tests/unit/test_docker_entrypoint.py  (NEW/extend — AC-2/AC-3 text checks)
specs/053-render-deploy-wiring/{spec,plan,tasks}.md
```
- **The only `app/` runtime change is the startup guard** (`main.py` lifespan call + a small validator).
  Everything else is deploy config / docs / static-check tests. Local dev is unchanged.
- **⚠ Revert any local `OLLAMA_MODEL_NAME` qwen3:4b→qwen3:8b override before committing.**

## 1. `render.yaml` (repo root) — Render Blueprint
```yaml
services:
  - type: web
    name: contractsentinel-api
    runtime: docker
    rootDir: backend                 # build context = backend/ (Dockerfile COPYs are backend-relative; EC-6)
    dockerfilePath: ./Dockerfile
    healthCheckPath: /api/health     # the existing public endpoint + keep-alive target
    plan: free
    envVars:
      # ── non-secret config (inline) ──
      - { key: LLM_PROVIDER,          value: groq }
      - { key: EMBED_PROVIDER,        value: hf }
      - { key: GROQ_MODEL,            value: openai/gpt-oss-120b }
      - { key: HF_EMBED_MODEL,        value: BAAI/bge-m3 }
      - { key: AUTH_COOKIE_SECURE,    value: "true" }
      - { key: AUTH_COOKIE_SAMESITE,  value: none }
      - { key: CORS_ALLOWED_ORIGINS,  sync: false }   # the Vercel/Pages origin(s)
      - { key: GOOGLE_OAUTH_REDIRECT_URI, sync: false }
      - { key: FRONTEND_INTEGRATIONS_URL, sync: false }
      # ── secrets (set in the dashboard; never committed) ──
      - { key: AUTH_SECRET,                    sync: false }
      - { key: CONTRACTSENTINEL_ENCRYPTION_KEY, sync: false }
      - { key: GROQ_API_KEY,                   sync: false }
      - { key: HF_API_TOKEN,                   sync: false }
      - { key: TURSO_DATABASE_URL,             sync: false }
      - { key: TURSO_AUTH_TOKEN,               sync: false }
```
- **No Render database** is declared (Turso is the DB — EC-5). `plan: free`. The exact field names are
  validated against Render's current Blueprint schema during the go-live build (AC-8); the plan uses the
  documented `type: web` + `runtime: docker` + `rootDir` + `healthCheckPath` + `envVars` shape.

## 2. `docker-entrypoint.sh` — Turso-aware migration (D2)
Replace the bare CLI call so the container migration targets the configured DB (Turso in prod):
```sh
echo "[entrypoint] running migrations (Turso-aware)…"
python -c "import app.config as c; from app.runner.migrations import upgrade_to_head; upgrade_to_head(c.JOB_STORE_DB_PATH)"
echo "[entrypoint] starting: $*"
exec "$@"
```
This is the SAME `upgrade_to_head` the lifespan runs (`main.py:67`), so it builds the `sqlite+libsql://`
URL when `TURSO_DATABASE_URL` is set (Linux image has `sqlalchemy-libsql` via the 051 marker) and the
local `sqlite:///` URL otherwise. A migration failure now stops the container before serving. `set -e`
is retained.

## 3. `Dockerfile` — ship the KB index (D3)
Add, next to the existing `COPY app ./app` / `COPY alembic ./alembic`:
```dockerfile
COPY data/kb ./data/kb
```
`data/kb/` (incl. the committed `clauses.faiss`) is tracked in git, so this copies the artifact directly
(no CI step). The runbook orders an **HF rebuild** of the index before the image build (050 AC-10) so the
indexed vectors match the prod HF query embeddings (else the 052 `.provider` marker warns; EC-2).

## 4. Startup prod-config guard (D6) — the only `app/` change
New `app/config.py::validate_prod_config()` (co-located with the config it reads; imported and called by
the lifespan so tests can monkeypatch config before it runs). **`config.py` has no logger today — add
`import logging` + `_log = logging.getLogger(__name__)`** for the key-pin warning below:
```python
def validate_prod_config() -> None:
    """Fail-fast on the most common deploy misconfig. Never echoes secret values."""
    errs = []
    if EMBED_PROVIDER == "hf" and not HF_API_TOKEN:
        errs.append("EMBED_PROVIDER=hf but HF_API_TOKEN is empty")
    if LLM_PROVIDER == "groq" and not GROQ_API_KEY:
        errs.append("LLM_PROVIDER=groq but GROQ_API_KEY is empty")
    if TURSO_DATABASE_URL and not TURSO_AUTH_TOKEN:
        errs.append("TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is empty")
    if errs:
        raise RuntimeError("Invalid production config: " + "; ".join(errs))
    if TURSO_DATABASE_URL and not os.environ.get(ENCRYPTION_KEY_ENV):
        _log.warning(
            "TURSO_DATABASE_URL is set but %s is not pinned via env — a restart regenerates the "
            "at-rest key and makes stored ciphertext undecryptable. Pin it.", ENCRYPTION_KEY_ENV,
        )
```
- In `main.py` lifespan, call `_cfg.validate_prod_config()` **first** (before `bootstrap_secret()` /
  `upgrade_to_head`), so a misconfigured deploy fails immediately with a clear message.
- Reads live module-level config values (tests monkeypatch `app.config.<NAME>` then call the function).
- **Never** logs/raises a token value (only names the var).

## 5. `.env.example` — full prod env surface
Append a clearly-commented "Deploy (features 046–053)" block documenting every var in spec §2.4 with a
**placeholder** value (never a real secret; `.env`/`backend/.env` stay gitignored). Keep the existing
keys. Include a one-line note that `AUTH_SECRET` + `CONTRACTSENTINEL_ENCRYPTION_KEY` MUST be pinned in a
durable deploy.

## 6. `docs/DEPLOYMENT.md` — rewrite (Oracle → Render + Turso)
Replace the Oracle runbook. Sections: architecture (Render web svc + Turso + HF + Groq + Vercel
frontend); the `render.yaml` blueprint; **mandatory pinned secrets** with the data-loss warning
(`AUTH_SECRET`, `CONTRACTSENTINEL_ENCRYPTION_KEY`); external setup (Turso DB + DB-scoped token, HF token,
Groq token, Google OAuth redirect reconfiguration); the **keep-alive cron** (cron-job.org → `/api/health`
every ~10 min); and a **go-live checklist** ordering the deferred validations: (a) HF-rebuild
`clauses.faiss` + retrieval eval (050 AC-10), (b) `alembic upgrade head` replays 0001–0009 on Turso +
restart-survival (051 AC-10), (c) report-BLOB durability across restart (052 AC-9), (d) Docker build
validation (EC-6 context). Retain the honest caveats (Groq token/day cap, HF free-tier reliability, Turso
free tier, "not legal advice").

## 7. Test plan (TDD, `tests/unit/`) — failing-first per §7; all static/offline, Windows-runnable
- **AC-1 (`test_render_blueprint.py`):** resolve the blueprint CWD-independently via
  `Path(__file__).resolve().parents[3] / "render.yaml"` (tests/unit → tests → backend → repo root),
  `yaml.safe_load` it; assert one `type: web` service, `healthCheckPath == "/api/health"`, `runtime: docker`, `rootDir:
  backend`; the required non-secret keys present with values; every required secret key present with
  `sync: false`; and **no secret VALUE** is committed (secret entries have no `value:`). (Add `pyyaml`
  to dev deps if not already resolvable.)
- **AC-2/AC-3 (`test_docker_entrypoint.py`):** text-assert `docker-entrypoint.sh` invokes
  `upgrade_to_head` and does **not** contain the bare `alembic upgrade head` CLI line; text-assert the
  `Dockerfile` contains `COPY data/kb`.
- **AC-4 (`test_env_example.py`):** `.env.example` contains every deploy key from §2.4; assert it has no
  value that looks like a real secret (e.g. no `hf_`/`gsk_`/`eyJ` prefixes; placeholders only).
- **AC-5 (`test_deployment_doc.py`):** greppable tokens per spec AC-5 (Render, Turso, not-Oracle-as-plan,
  `AUTH_SECRET` + `CONTRACTSENTINEL_ENCRYPTION_KEY` in a pinning/data-loss context, `/api/health`, the
  four deferred validations named).
- **AC-7 (`test_prod_config_guard.py`):** monkeypatch `app.config` — `EMBED_PROVIDER="hf"` + empty
  `HF_API_TOKEN` → `validate_prod_config()` raises `RuntimeError` naming `HF_API_TOKEN` (token value not
  present); same for groq/turso; with the defaults (ollama/ollama, no Turso) → no raise. Assert the
  encryption-key warning fires (caplog) when `TURSO_DATABASE_URL` set + key env unset, and that no secret
  value is logged.
- **AC-6:** whole `pytest` green; the guard is a no-op under the suite's default env (the 051 conftest
  already forces `TURSO_DATABASE_URL=""`; providers default to ollama).

## 8. Live validation (AC-8 — operator-run Render deploy; deferred)
Per the runbook: set the pinned secrets, deploy the blueprint, confirm `/api/health`, run the go-live
checklist (Turso replay + restart-survival + report durability + HF index), verify
register→login→upload→analyze→download and Drive/Gmail delivery. Record results in `docs/DEPLOYMENT.md`.

## 9. Risks / limitations
- **Blueprint schema drift** — Render's Blueprint fields evolve; AC-1 checks our intent, the go-live build
  (AC-8) validates against the live schema. Keep `render.yaml` minimal.
- **Guard scope** — deliberately small (token presence + key-pin warning); not a full config validator.
- **KB index freshness** — shipping the committed bge-m3 index without the HF rebuild degrades retrieval
  (EC-2); the runbook orders the rebuild.
- **External steps** — the actual durability/keep-alive/OAuth only take effect once the operator does the
  Render/Turso/HF/Google setup; the runbook is the source of truth.

## 10. Merge
Whole `pytest` green (Windows, unit); diff = §0 allow-list; `OLLAMA_MODEL_NAME` reverted. Rebase the
branch point, merge `feature/053-render-deploy-wiring` (completes the 048→053 chain — the whole chain is
then git-finished to main per the deploy-phase plan), delete branch. AC-8 (the live deploy) follows via
the runbook. This is the final feature of the Render + Turso deploy phase ([[project_render_turso_deploy]]).
