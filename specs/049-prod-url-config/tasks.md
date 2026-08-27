# Feature 049 — Implementation tasks

Branch: `feature/049-prod-url-config`. TDD order (§7): failing tests → implement.

## T0 — Pre-flight
- [ ] On branch `feature/049-prod-url-config`.
- [ ] Confirm `app/config.py:58` `OLLAMA_MODEL_NAME == "qwen3:8b"` (do NOT reintroduce qwen3:4b).

## T1 — Failing tests (`tests/unit/test_config.py`)
- [ ] AC-3: `monkeypatch.setenv("CS_TEST_REDIRECT", "https://api.example.com/api/integrations/google/callback")`
      ⇒ `config._env_str("CS_TEST_REDIRECT", "x")` equals it.
- [ ] AC-4: `monkeypatch.setenv("CS_TEST_FRONT", "https://app.example.com/integrations")`
      ⇒ `config._env_str("CS_TEST_FRONT", "x")` equals it.
- [ ] Edge: `config._env_str("CS_TEST_UNSET", default)` with unset / `""` / whitespace ⇒ `default`.
- [ ] Run → red (no `_env_str` yet).

## T2 — Implement (`app/config.py`)
- [ ] Add `_env_str(name, default)` after `_env_int` (~line 39): unset/blank ⇒ default, else `.strip()`.
- [ ] Wrap `GOOGLE_OAUTH_REDIRECT_URI` (:531) = `_env_str("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/api/integrations/google/callback")`.
- [ ] Wrap `FRONTEND_INTEGRATIONS_URL` (:542) = `_env_str("FRONTEND_INTEGRATIONS_URL", "http://localhost:3000/integrations")`.
- [ ] Keep both existing explanatory comments.
- [ ] Run T1 → green. Confirm the two 031 tests stay green (unmodified). (AC-1/AC-2/AC-6)

## T3 — Docs (`docs/DEPLOYMENT.md`)
- [ ] §8 env table: add `GOOGLE_OAUTH_REDIRECT_URI` + `FRONTEND_INTEGRATIONS_URL` rows with prod examples.
- [ ] §6: note the deployed backend must set both (redirect URI = the exact GCP-registered URI; integrations
      URL = the Vercel `/integrations` page). (AC-5)

## T4 — Full suite + commit (only when user asks)
- [ ] `python -m pytest -q` from `backend/` → all green.
- [ ] `git status` — only config.py, DEPLOYMENT.md, test_config.py, the 3 spec files changed; no qwen3:4b;
      pre-existing dirt (builder.py, specs/009, specs/035) left unstaged.
- [ ] Commit `feat(049): env-overridable OAuth redirect + frontend integrations URL for prod deploy`.

## Acceptance mapping
AC-1→T2(031 tests), AC-2→T2(031 tests), AC-3→T1, AC-4→T1, AC-5→T3, AC-6→T2/T4.
