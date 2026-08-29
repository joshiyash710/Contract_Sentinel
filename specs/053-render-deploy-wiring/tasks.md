# Feature 053 — Tasks: Render + Turso deploy wiring

Implements `specs/053-render-deploy-wiring/plan.md` (spec + plan spec-reviewer-APPROVED). TDD per §7:
write/run tests FAILING first, then implement. All tests are **static/offline** (parse/grep the config +
docs; monkeypatch the guard) and **Windows-runnable**. The live Render deploy is AC-8 (operator-run,
deferred). Run from `backend/`. Each task cites its AC.

---

## T0 — Preconditions (no code change)
0.1 `git branch --show-current` == `feature/053-render-deploy-wiring`.
0.2 **Revert any local `OLLAMA_MODEL_NAME` qwen3:4b→qwen3:8b override** before `test_config`.
0.3 Baseline: `python -m pytest -q` green.

## T1 — Dependency for the blueprint test
1.1 Add `"pyyaml>=6.0"` to `[project.optional-dependencies].dev` in `pyproject.toml` (AC-1 parses
    `render.yaml`). `uv lock` + `uv sync --extra dev`. Verify `python -c "import yaml"`.

## T2 — (TEST FIRST) startup prod-config guard — AC-7
2.1 Create `tests/unit/test_prod_config_guard.py`. Monkeypatch `app.config` module names then call
    `app.config.validate_prod_config()`:
    - `EMBED_PROVIDER="hf"` + `HF_API_TOKEN=""` → raises `RuntimeError` whose message contains
      `HF_API_TOKEN` and NOT any token value.
    - `LLM_PROVIDER="groq"` + `GROQ_API_KEY=""` → raises naming `GROQ_API_KEY`.
    - `TURSO_DATABASE_URL="libsql://x"` + `TURSO_AUTH_TOKEN=""` → raises naming `TURSO_AUTH_TOKEN`.
    - Defaults (`ollama`/`ollama`, `TURSO_DATABASE_URL=""`) → no raise.
    - `TURSO_DATABASE_URL="libsql://x"` + `TURSO_AUTH_TOKEN="t"` + `ENCRYPTION_KEY_ENV` unset in
      `os.environ` → no raise, but a `caplog` WARNING mentions the encryption key var; assert no secret
      value in the log.
2.2 Run → **FAIL** (`validate_prod_config` absent).

## T3 — (IMPL) the guard — AC-7
3.1 In `app/config.py`: add `import logging` + `_log = logging.getLogger(__name__)` (none today), and
    `def validate_prod_config() -> None:` per plan §4 (hf/groq/turso presence → `RuntimeError` naming the
    var, never echoing a value; encryption-key-not-pinned → `_log.warning` when `TURSO_DATABASE_URL` set
    and `os.environ.get(ENCRYPTION_KEY_ENV)` is falsy).
3.2 In `app/api/main.py` lifespan, call `_cfg.validate_prod_config()` as the **first** statement (before
    `bootstrap_secret()`), so a misconfigured deploy fails fast.
3.3 Run `test_prod_config_guard.py` + `tests/integration/` smoke (app still boots under defaults) →
    **green**.

## T4 — (TEST FIRST) render.yaml blueprint — AC-1
4.1 Create `tests/unit/test_render_blueprint.py`: resolve `Path(__file__).resolve().parents[3] /
    "render.yaml"`, `yaml.safe_load` it; assert exactly one `services` entry with `type: web`,
    `runtime: docker`, `rootDir: backend`, `healthCheckPath: "/api/health"`; the required non-secret env
    keys present WITH a `value`; every required secret key (`AUTH_SECRET`,
    `CONTRACTSENTINEL_ENCRYPTION_KEY`, `GROQ_API_KEY`, `HF_API_TOKEN`, `TURSO_DATABASE_URL`,
    `TURSO_AUTH_TOKEN`) present with `sync: false` and **no `value`** (no secret committed); and no Render
    database service declared.
4.2 Run → **FAIL** (`render.yaml` absent).

## T5 — (IMPL) render.yaml — AC-1
5.1 Create repo-root `render.yaml` per plan §1 (web service, docker, `rootDir: backend`,
    `healthCheckPath: /api/health`, inline non-secrets, `sync: false` secrets, no Render DB).
5.2 Run `test_render_blueprint.py` → **green**.

## T6 — (TEST FIRST) entrypoint + Dockerfile — AC-2, AC-3
6.1 Create `tests/unit/test_docker_entrypoint.py`: read `docker-entrypoint.sh` — assert it references
    `upgrade_to_head` and does NOT contain a bare `alembic upgrade head` line; read `Dockerfile` — assert
    it contains `COPY data/kb`.
6.2 Run → **FAIL**.

## T7 — (IMPL) entrypoint + Dockerfile — AC-2, AC-3
7.1 In `docker-entrypoint.sh`, replace `alembic upgrade head` with the Turso-aware Python call
    (plan §2): `python -c "import app.config as c; from app.runner.migrations import upgrade_to_head;
    upgrade_to_head(c.JOB_STORE_DB_PATH)"`. Keep `set -e` and the `exec "$@"`.
7.2 In `Dockerfile`, add `COPY data/kb ./data/kb` next to `COPY app ./app` / `COPY alembic ./alembic`.
7.3 Run `test_docker_entrypoint.py` → **green**.

## T8 — (TEST FIRST) .env.example — AC-4
8.1 Create `tests/unit/test_env_example.py`: read `.env.example`; assert every deploy key from spec §2.4
    is present (`LLM_PROVIDER`, `GROQ_API_KEY`, `GROQ_MODEL`, `EMBED_PROVIDER`, `HF_API_TOKEN`,
    `HF_EMBED_MODEL`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `AUTH_SECRET`,
    `CONTRACTSENTINEL_ENCRYPTION_KEY`, `CORS_ALLOWED_ORIGINS`, `AUTH_COOKIE_SECURE`,
    `AUTH_COOKIE_SAMESITE`, `GOOGLE_OAUTH_REDIRECT_URI`, `FRONTEND_INTEGRATIONS_URL`); assert NO real
    secret values (no `hf_`, `gsk_`, `eyJ` substrings — placeholders only).
8.2 Run → **FAIL** (keys missing).

## T9 — (IMPL) .env.example — AC-4
9.1 Append a commented "# ── Deploy (features 046–053) ──" block to `.env.example` with each key from §2.4
    (placeholder values), plus a one-line note that `AUTH_SECRET` + `CONTRACTSENTINEL_ENCRYPTION_KEY` MUST
    be pinned in a durable deploy. Keep existing keys.
9.2 Run `test_env_example.py` → **green**.

## T10 — (TEST FIRST) DEPLOYMENT.md — AC-5
10.1 Create `tests/unit/test_deployment_doc.py`: read `docs/DEPLOYMENT.md` — assert greppable tokens:
     `"Render"` and `"Turso"` present; `"Oracle"` NOT the active plan (allow it only in a
     "superseded/why-not" note, or assert Render appears before/instead — simplest: assert the doc's
     title/architecture names Render+Turso); `AUTH_SECRET` and `CONTRACTSENTINEL_ENCRYPTION_KEY` both
     appear near a "pin"/"data loss" context; `/api/health` present; and each of `050`/`051`/`052` +
     `Dockerfile` named in the go-live checklist.
10.2 Run → **FAIL** (still the Oracle runbook).

## T11 — (IMPL) DEPLOYMENT.md rewrite — AC-5
11.1 Rewrite `docs/DEPLOYMENT.md` per plan §6 (Render+Turso architecture, blueprint, mandatory pinned
     secrets + data-loss warning, external setup, keep-alive `/api/health` cron, go-live checklist with
     the four deferred validations, honest caveats retained).
11.2 Run `test_deployment_doc.py` → **green**.

## T12 — Full suite + diff-scope + lint — AC-6
12.1 `python -m pytest -q` → whole suite **green** (guard is a no-op under the default suite env).
12.2 `ruff check` clean on the touched app/test files (pre-existing `config.py` E402 excluded).
12.3 `git diff --name-only <branch-point>` == plan §0 allow-list (`render.yaml`, `docker-entrypoint.sh`,
     `Dockerfile`, `.env.example`, `app/config.py`, `app/api/main.py`, `docs/DEPLOYMENT.md`,
     `pyproject.toml`+`uv.lock`, the 5 new test files, `specs/053-**`). **No** graph/edge/`ContractState`/
     migration change; `OLLAMA_MODEL_NAME` unchanged.

## T13 — Merge (git-finish) — deferred: AC-8 (live deploy)
13.1 T12 green + diff clean + `OLLAMA_MODEL_NAME` reverted. Rebase branch point, merge
     `feature/053-render-deploy-wiring`, delete branch. This completes the 048→053 deploy chain (the whole
     chain then git-finishes to main per the deploy-phase plan).
13.2 **AC-8 (operator-run Render deploy):** follow `docs/DEPLOYMENT.md` — set pinned secrets, deploy the
     blueprint, confirm `/api/health`, run the go-live checklist (Turso replay + restart-survival +
     report durability + HF index rebuild + Docker build), verify the end-to-end flow + Drive/Gmail
     delivery. Record results in `docs/DEPLOYMENT.md`.

---

### Notes for the implementation model
- The guard reads live `app.config` module names and is called first in the lifespan; it NEVER logs or
  raises a secret value (only names the var). Tests monkeypatch `app.config.<NAME>`.
- `render.yaml` lives at the **repo root** (one level above `backend/`); the AC-1 test resolves it via
  `Path(__file__).resolve().parents[3]`.
- Do not change any pipeline/storage/auth behavior — 053 only wires 046–052's existing env flags + adds
  the boot guard + deploy artifacts.
