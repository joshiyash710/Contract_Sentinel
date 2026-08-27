# Feature 048 — Cross-origin deploy config (env-overridable CORS origins + cookie SameSite)

Branch: `feature/048-cross-origin-deploy-config` (per constitution §11).

## 1. Problem statement

`docs/DEPLOYMENT.md` puts the **frontend on Vercel** (`*.vercel.app`) and the **backend on an Oracle
VM** (separate host). Two auth/CORS settings are currently **hardcoded for same-origin localhost dev**
and silently break that cross-origin topology:

1. **`CORS_ALLOWED_ORIGINS`** (`app/config.py:593`) is a hardcoded tuple of two localhost origins
   (`http://localhost:5173`, `http://127.0.0.1:5173`). The deployed frontend origin cannot be granted
   CORS without editing source — so every cross-origin `fetch`/`EventSource` from the Vercel frontend
   to the backend fails the browser CORS preflight.
2. **The session cookie is written with `samesite="lax"`** (`app/api/auth.py:267` in
   `_set_session_cookie`, and `:281` in `_clear_session_cookie`). With a `Lax` cookie, the browser
   does **not** attach `cs_session` on cross-site requests (Vercel origin → different backend host), so
   login **appears to succeed but never persists** — the classic "logged out on refresh" cross-site
   failure. Cross-site auth requires `SameSite=None; Secure`.

Neither can be worked around at deploy time because both are Python literals, not environment inputs.
This feature makes **both** values **env-overridable named §3 config**, with defaults that reproduce
**today's exact localhost behavior byte-for-byte** — so local dev is unchanged and the change is
purely additive/reversible.

### Position relative to the constitution
- **No graph/edge change, no `ContractState` change, no migration, no new node.** This only changes how
  two existing config values are sourced (literal → `os.getenv` with the literal as default) and threads
  a config value into two existing cookie writes.
- **§3 (named config):** both settings become named, documented config constants read from the
  environment with explicit defaults — the same `os.getenv`/`_env_*` pattern already used by
  `AUTH_COOKIE_SECURE`, `LLM_PROVIDER`, etc.
- **§7 (TDD):** new unit tests assert (a) defaults equal today's values, (b) env override parses
  correctly, (c) the cookie helper emits the configured `SameSite`, (d) the `SameSite=None`+`Secure`
  safety invariant. No existing test is weakened.
- **§11:** developed on `feature/048-cross-origin-deploy-config`.
- **Security posture:** this does **not** loosen anything by default. It *enables* an operator to widen
  CORS and relax SameSite **deliberately, per-deploy, via env** — the same opt-in shape as 046's
  `LLM_PROVIDER`. Defaults stay locked to localhost/Lax.

## 2. Goals / non-goals

**Goals**
- G1. `CORS_ALLOWED_ORIGINS` is overridable from the environment (comma-separated origin list); default
  = the current two localhost origins, in the same order.
- G2. The session-cookie `SameSite` attribute is overridable from the environment
  (`lax` | `strict` | `none`, case-insensitive); default = `lax`.
- G3. Both `_set_session_cookie` and `_clear_session_cookie` use the configured value (they must match,
  or the browser won't clear the cookie it set).
- G4. A safety invariant: when `SameSite=None`, the cookie must also be `Secure` (browsers reject
  `SameSite=None` without `Secure`). This is validated so a misconfigured deploy fails loudly rather
  than shipping a cookie browsers silently drop.
- G5. `docs/DEPLOYMENT.md` env-var reference (§8 table) documents the two new vars.

**Non-goals**
- No change to cookie name, TTL, `HttpOnly`, `Secure` default, or the `path`/no-`domain` behavior.
- No CORS behavior change beyond the origin allowlist source (methods/headers/credentials unchanged).
- No Dockerfile / infra artifacts here (those are non-`app/` infra, handled separately).
- No frontend change.

## 3. Config changes (§3)

| Name | Env var | Type | Default | Notes |
|---|---|---|---|---|
| `CORS_ALLOWED_ORIGINS` | `CORS_ALLOWED_ORIGINS` | tuple[str, …] | `("http://localhost:5173", "http://127.0.0.1:5173")` | Comma-separated in env; whitespace trimmed; empty entries dropped. Empty/unset env ⇒ the default tuple. |
| `AUTH_COOKIE_SAMESITE` | `AUTH_COOKIE_SAMESITE` | `str` (`"lax"`/`"strict"`/`"none"`) | `"lax"` | Lower-cased. Any value not in the allowed set ⇒ fall back to `"lax"` (fail-safe to the strict-est cross-site default, not to `none`). |

Parsing detail for `CORS_ALLOWED_ORIGINS`: read `os.getenv("CORS_ALLOWED_ORIGINS")`; if set and
non-blank, split on `,`, `.strip()` each, drop empties, build a tuple; else use the default tuple.

## 4. Behavior

- `app/api/main.py` CORS middleware already reads `list(_cfg.CORS_ALLOWED_ORIGINS)` — **no change to
  main.py**; it transparently picks up the env-sourced tuple.
- `_set_session_cookie` passes `samesite=_cfg.AUTH_COOKIE_SAMESITE` instead of the literal `"lax"`.
- `_clear_session_cookie` passes the **same** `samesite=_cfg.AUTH_COOKIE_SAMESITE` (and must also carry
  `secure=_cfg.AUTH_COOKIE_SECURE`, matching the set path, so a `Secure`+`None` cookie is actually
  cleared — see AC-6).
- Safety invariant (G4): enforced at config load — if `AUTH_COOKIE_SAMESITE == "none"` and
  `AUTH_COOKIE_SECURE` is `False`, raise a clear `ValueError` at import naming both vars. Rationale:
  a `None`-without-`Secure` cookie is dropped by all modern browsers, so this is never a valid deploy;
  failing at boot is safer than a silently broken login in production.

## 5. Acceptance criteria

- **AC-1** With no env vars set, `config.CORS_ALLOWED_ORIGINS == ("http://localhost:5173",
  "http://127.0.0.1:5173")` (order preserved) — byte-identical to today.
- **AC-2** With `CORS_ALLOWED_ORIGINS="https://cs.vercel.app, https://foo.dev"` in env, the config
  parses to `("https://cs.vercel.app", "https://foo.dev")` (trimmed, order preserved).
- **AC-3** With no env var, `config.AUTH_COOKIE_SAMESITE == "lax"` — byte-identical to today.
- **AC-4** With `AUTH_COOKIE_SAMESITE="None"` (any case) + `AUTH_COOKIE_SECURE=True`, config loads and
  the value normalizes to `"none"`.
- **AC-5** An unrecognized `AUTH_COOKIE_SAMESITE` (e.g. `"bogus"`) falls back to `"lax"` (no crash).
- **AC-6** `_set_session_cookie` and `_clear_session_cookie` both emit the configured `SameSite`; a test
  with `AUTH_COOKIE_SAMESITE="none"` asserts the `Set-Cookie` header contains `SameSite=none` (or the
  Starlette-normalized casing) on **both** set and clear, and `Secure` on both.
- **AC-7** Safety invariant: `AUTH_COOKIE_SAMESITE="none"` with `AUTH_COOKIE_SECURE=False` raises
  `ValueError` at config load, and the message names both env vars.
- **AC-8** Default-config run (no env) still passes the full existing suite — no regression in the CORS
  middleware wiring or auth cookie tests.
- **AC-9** `docs/DEPLOYMENT.md` §8 env table lists `CORS_ALLOWED_ORIGINS` and `AUTH_COOKIE_SAMESITE`
  with their prod values (`https://<app>.vercel.app` and `none` for the pure-$0 cross-site path; `lax`
  if frontend+backend share a registrable domain).

## 6. Test plan (§7 TDD)

New/updated `backend/tests/unit/`:
- `test_config.py`: AC-1..AC-5, AC-7 — exercise defaults + env overrides + the invalid fallback + the
  `ValueError` guard. Use `monkeypatch.setenv` + reload the config module (follow the existing reload
  pattern already used for other env-driven config tests; if none exists, `importlib.reload`).
- `tests/integration/test_auth_session.py` (the existing auth-cookie test module): AC-6 — set
  `AUTH_COOKIE_SAMESITE` via `monkeypatch.setattr` and assert the emitted `Set-Cookie` header on login
  **and** logout carries the configured `SameSite` + `Secure`.

No existing assertion is loosened. The current localhost/Lax tests continue to pass unchanged because
the defaults are identical.

## 7. Out of scope / follow-ups
- Dockerfile, `.dockerignore`, `frontend/.env.example`, prod `.env` template — separate infra artifacts.
- Live cross-origin smoke (login persists Vercel→Oracle) — part of the deployment smoke checklist (§7 of
  `docs/DEPLOYMENT.md`), not this unit-level feature.
