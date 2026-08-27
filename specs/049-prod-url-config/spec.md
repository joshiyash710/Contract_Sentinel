# Feature 049 — Prod URL config (env-overridable OAuth redirect + frontend integrations URL)

Branch: `feature/049-prod-url-config` (per constitution §11). Builds on the 048 deploy-config work.

## 1. Problem statement

Two config values consumed by the Google OAuth connect flow are **hardcoded to localhost** and are NOT
env-read, so a cross-origin production deploy (`docs/DEPLOYMENT.md`: Vercel frontend + VM backend) breaks
Drive/Gmail delivery:

1. `GOOGLE_OAUTH_REDIRECT_URI` (`app/config.py:531`, used at `app/api/integrations.py:77`) =
   `http://localhost:8000/api/integrations/google/callback`. Google rejects any callback whose redirect
   URI is not the one registered on the Web OAuth client; in prod that must be
   `https://api.<domain>/api/integrations/google/callback`. Unchangeable without editing source today.
2. `FRONTEND_INTEGRATIONS_URL` (`app/config.py:542`, used at `app/api/integrations.py:143`) =
   `http://localhost:3000/integrations`. After the OAuth callback the backend 302-redirects the user's
   **browser** here — in prod that sends the user to a dead `localhost:3000`, not the Vercel app.

This is the same class of blocker 048 fixed for CORS/cookies. `FRONTEND_RESET_URL` (`config.py:770`) is
already env-read via `os.getenv` (feature 034) — this feature makes the above two consistent with it.

### Position relative to the constitution
No graph/edge/state/migration change. Two existing §3 config literals become `os.getenv(NAME, <current
literal>)` — **defaults byte-identical to today**, so local dev + the existing 031 tests are unchanged.
§7 TDD; §11 branch. Purely additive/reversible (unset env ⇒ pre-049 behavior).

## 2. Goals / non-goals
**Goals**
- G1. `GOOGLE_OAUTH_REDIRECT_URI` reads env `GOOGLE_OAUTH_REDIRECT_URI`, default = current localhost value.
- G2. `FRONTEND_INTEGRATIONS_URL` reads env `FRONTEND_INTEGRATIONS_URL`, default = current localhost value.
- G3. `docs/DEPLOYMENT.md` §6 + §8 document both vars with prod examples.

**Non-goals**
- No change to the OAuth flow logic, scopes, credential path, or any other constant.
- No frontend change (the frontend already uses `NEXT_PUBLIC_API_BASE_URL`).

## 3. Config changes (§3)
| Name | Env var | Default (unchanged) |
|---|---|---|
| `GOOGLE_OAUTH_REDIRECT_URI` | `GOOGLE_OAUTH_REDIRECT_URI` | `http://localhost:8000/api/integrations/google/callback` |
| `FRONTEND_INTEGRATIONS_URL` | `FRONTEND_INTEGRATIONS_URL` | `http://localhost:3000/integrations` |

Introduce a small named helper `_env_str(name, default)` (companion to the existing
`_env_bool`/`_env_int` at `config.py:23`/`:31`, and the 048 `_env_origin_tuple`/`_env_samesite`) that
returns `default` when the env var is unset **or blank**, else the trimmed value. Both constants become
`_env_str("GOOGLE_OAUTH_REDIRECT_URI", <literal>)` and `_env_str("FRONTEND_INTEGRATIONS_URL", <literal>)`.
Using the named helper (not raw `os.getenv`) matches the 048 helper-testing precedent so AC-3/AC-4 can
test it directly with **no module reload**.

## 3a. Edge cases
- **Blank/whitespace env var** (`GOOGLE_OAUTH_REDIRECT_URI=""`): `_env_str` returns the default (mirrors
  `_env_bool`/`_env_int`, which fall back on empty) — an accidental empty value never yields an empty
  redirect URI. Tested.
- **Unset env var:** returns the default (byte-identical to today).
- **Set non-blank value:** returns it (trimmed). No URL-format validation (out of scope; the operator
  must register the exact URI in GCP either way).

## 4. Acceptance criteria
- **AC-1** No env ⇒ `config.GOOGLE_OAUTH_REDIRECT_URI == "http://localhost:8000/api/integrations/google/callback"` (byte-identical; existing 031 test stays green).
- **AC-2** No env ⇒ `config.FRONTEND_INTEGRATIONS_URL == "http://localhost:3000/integrations"` (byte-identical; existing 031 test stays green).
- **AC-3** `GOOGLE_OAUTH_REDIRECT_URI="https://api.example.com/api/integrations/google/callback"` in env ⇒ config reflects it.
- **AC-4** `FRONTEND_INTEGRATIONS_URL="https://app.example.com/integrations"` in env ⇒ config reflects it.
- **AC-5** `docs/DEPLOYMENT.md` §6/§8 list both env vars with prod examples.
- **AC-6** Full suite green (no regression; the two 031 constant tests unchanged).

## 5. Test plan (§7 TDD)
Follow the 048 precedent already in `test_config.py` (comment at ~line 639: "Tests exercise the named
helpers directly (no importlib.reload)"). **No module reload anywhere.**
- AC-1/AC-2: assert the loaded defaults `config.GOOGLE_OAUTH_REDIRECT_URI` / `config.FRONTEND_INTEGRATIONS_URL`
  equal the localhost literals (the existing 031 test already covers this and stays green — a new
  explicit assertion is optional but harmless).
- AC-3: `monkeypatch.setenv("CS_TEST_REDIRECT", "https://api.example.com/api/integrations/google/callback")`
  then `config._env_str("CS_TEST_REDIRECT", "x") == "https://api.example.com/api/integrations/google/callback"`.
- AC-4: same shape for the frontend URL via `_env_str`.
- Edge: `_env_str("CS_TEST_X", default)` with env unset, `""`, and whitespace-only ⇒ returns `default`.

The two existing 031 tests (`test_per_user_drive_031_constants_match_spec`, `..._types`) are NOT modified
and must stay green (defaults are byte-identical).

## 6. Out of scope
- Dockerfile/env-template edits beyond DEPLOYMENT.md are optional docs, not required by ACs.
