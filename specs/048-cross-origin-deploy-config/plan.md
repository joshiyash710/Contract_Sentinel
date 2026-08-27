# Feature 048 — Technical plan

Branch: `feature/048-cross-origin-deploy-config`.
Spec: `specs/048-cross-origin-deploy-config/spec.md` (spec-reviewer APPROVED).

## 1. Overview

Two hardcoded same-origin-localhost settings become env-overridable named §3 config, defaults
byte-identical to today. No graph/state/edge/migration change. Files touched:
- `app/config.py` — source the two values from env (new parsing for the CORS list; new SameSite const +
  boot-time safety guard).
- `app/api/auth.py` — thread `AUTH_COOKIE_SAMESITE` into `_set_session_cookie` and
  `_clear_session_cookie`; add `secure=_cfg.AUTH_COOKIE_SECURE` to the clear path.
- `docs/DEPLOYMENT.md` — §8 env table rows for the two new vars.
- Tests: `tests/unit/test_config.py` (helper/default assertions) and `tests/integration/test_auth_session.py`
  (the existing cookie `Set-Cookie` test module — extend it for AC-6).

`app/api/main.py` is **not** edited — it already reads `list(_cfg.CORS_ALLOWED_ORIGINS)`.

## 2. Config implementation (`app/config.py`)

### 2a. `CORS_ALLOWED_ORIGINS` (replace the hardcoded tuple at ~line 593)

```python
_DEFAULT_CORS_ALLOWED_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def _env_origin_tuple(name: str, default: tuple) -> tuple:
    """Comma-separated origin allowlist from env; trims, drops empties.
    If the env var is unset OR parses to zero non-empty origins, return `default`
    (never an empty allowlist — an empty tuple would block the browser entirely)."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    parsed = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parsed if parsed else default


CORS_ALLOWED_ORIGINS: tuple = _env_origin_tuple(
    "CORS_ALLOWED_ORIGINS", _DEFAULT_CORS_ALLOWED_ORIGINS
)
```

- Resolves the reviewer's ambiguity: `CORS_ALLOWED_ORIGINS=","` or `""` ⇒ falls back to the default
  tuple (documented in the docstring + a test), NOT an empty allowlist.
- Order preserved; whitespace trimmed; no de-dup (harmless if a caller repeats an origin; keeping it
  simple avoids surprising reordering). Case is preserved (origins are case-sensitive in practice).
- Keep the existing explanatory comment block below the assignment.

### 2b. `AUTH_COOKIE_SAMESITE` (new const, immediately after `AUTH_COOKIE_SECURE` ~line 683)

```python
_ALLOWED_SAMESITE = ("lax", "strict", "none")


def _env_samesite(name: str, default: str = "lax") -> str:
    val = os.getenv(name, default).strip().lower()
    return val if val in _ALLOWED_SAMESITE else default  # unrecognized ⇒ safe default (lax)


def _validate_samesite_secure(samesite: str, secure: bool) -> None:
    """Safety invariant (spec G4/AC-7): a SameSite=None cookie is dropped by browsers unless it is
    also Secure. Raise loudly at boot rather than ship a login cookie the browser silently discards.
    Extracted as a named function so AC-7 can test it directly (no module reload)."""
    if samesite == "none" and not secure:
        raise ValueError(
            "AUTH_COOKIE_SAMESITE=none requires AUTH_COOKIE_SECURE=True "
            "(browsers drop a SameSite=None cookie without the Secure attribute)."
        )


AUTH_COOKIE_SAMESITE: str = _env_samesite("AUTH_COOKIE_SAMESITE", "lax")
_validate_samesite_secure(AUTH_COOKIE_SAMESITE, AUTH_COOKIE_SECURE)  # boot-time guard
```

- Placed **immediately after** `AUTH_COOKIE_SECURE` (~line 683), before the TTL/idle consts — only
  those two names are needed.
- Both `_env_origin_tuple` (2a) and `_env_samesite`/`_validate_samesite_secure` are **module-level
  named helpers** so the tests exercise them **directly** (call the function with a controlled env /
  args) — this deliberately avoids `importlib.reload(config)`, which would re-trip the boot guard and
  leave global state dirtied for later tests (the reviewer's teardown concern). No reload anywhere.

## 3. Auth cookie wiring (`app/api/auth.py`)

`_set_session_cookie` (~line 261): change `samesite="lax"` → `samesite=_cfg.AUTH_COOKIE_SAMESITE`.

`_clear_session_cookie` (~line 276): change `samesite="lax"` → `samesite=_cfg.AUTH_COOKIE_SAMESITE`
**and** add `secure=_cfg.AUTH_COOKIE_SECURE`. Rationale (spec §4, intentional behavior change, not scope
drift): a cookie written with `Secure` can only be cleared by a delete that also carries `Secure`; the
set and clear attributes must match or logout won't remove the cookie cross-site. This adds `Secure` to
the clear `Set-Cookie` when `AUTH_COOKIE_SECURE=True` (the prod default) — harmless in local dev where
it's `False`.

No other changes to these helpers (name, httponly, max_age, path, no-domain all unchanged).

## 4. Docs (`docs/DEPLOYMENT.md` §8 table)

Add two rows:

| `CORS_ALLOWED_ORIGINS` | backend | comma-separated; e.g. `https://<app>.vercel.app` |
| `AUTH_COOKIE_SAMESITE` | backend | `none` for cross-site `*.vercel.app`↔VM (requires `AUTH_COOKIE_SECURE=True`); `lax` if frontend+backend share a registrable domain |

Also add a one-line note in §5 (frontend/cookies) pointing at `AUTH_COOKIE_SAMESITE=none` as the switch
that makes the cross-site cookie stick, replacing the vaguer "set SameSite=None" prose.

## 5. Test plan (§7 TDD — write tests first)

Strategy: **test the named helpers directly** — no `importlib.reload`, no env-mutation-then-reload,
no global-state teardown risk. Config value assertions (AC-1, AC-3) read the already-loaded module
attributes (they were computed from a clean env at import). Parsing/guard behavior (AC-2, AC-4, AC-5,
AC-7) calls the helper functions with controlled inputs.

`tests/unit/test_config.py` — extend (do NOT reload the module):
- AC-1: `config.CORS_ALLOWED_ORIGINS == ("http://localhost:5173", "http://127.0.0.1:5173")` (defaults
  as loaded — the suite runs with no CORS env set).
- AC-2: call `config._env_origin_tuple("X", default)` with `monkeypatch.setenv("X", "https://cs.vercel.app, https://foo.dev")`
  ⇒ `("https://cs.vercel.app", "https://foo.dev")` (trimmed, ordered).
- Edge: `_env_origin_tuple("X", default)` with env `","` and with env `""` and unset ⇒ returns
  `default` tuple (reviewer ambiguity pinned).
- AC-3: `config.AUTH_COOKIE_SAMESITE == "lax"` (default as loaded).
- AC-4: `config._env_samesite("X", "lax")` with `monkeypatch.setenv("X", "None")` ⇒ `"none"`.
- AC-5: `config._env_samesite("X", "lax")` with env `"bogus"` (and whitespace-only) ⇒ `"lax"`.
- AC-7: `pytest.raises(ValueError, match=...)` on
  `config._validate_samesite_secure("none", secure=False)`; assert the message mentions both
  `AUTH_COOKIE_SAMESITE` and `AUTH_COOKIE_SECURE`. Also assert the valid combo
  `_validate_samesite_secure("none", secure=True)` returns `None` (no raise).

`tests/integration/test_auth_session.py` — extend the existing cookie test module (this is where the
real login/logout `Set-Cookie` assertions live: `test_cookie_flags_secure_httponly_samesite:27` and
`test_cookie_no_secure_flag_when_disabled:35`). Use the module's **proven** override style —
`monkeypatch.setattr(app.config, "AUTH_COOKIE_SAMESITE", "none")` — NOT env+reload, because `auth.py`
reads `_cfg.AUTH_COOKIE_SAMESITE` by attribute at call time (`import app.config as _cfg`, line 25):
- AC-6: `monkeypatch.setattr(_c, "AUTH_COOKIE_SECURE", True)` + `setattr(_c, "AUTH_COOKIE_SAMESITE", "none")`;
  a login `Set-Cookie` (`.lower()`) for `cs_session` contains `samesite=none` **and** `secure`; the
  logout/clear `Set-Cookie` (`.lower()`) likewise contains `samesite=none` **and** `secure` (this is
  what the new `secure=_cfg.AUTH_COOKIE_SECURE` on `_clear_session_cookie` buys). Mirror the existing
  test's `.lower()` + substring style exactly (Starlette normalizes attribute casing).
- The two existing cookie tests stay **unchanged and green**: default `AUTH_COOKIE_SAMESITE="lax"` keeps
  `samesite=lax` in the header, so `test_cookie_flags_secure_httponly_samesite` still passes (AC-8, no
  regression). The clear-path `secure=` addition is a no-op when `AUTH_COOKIE_SECURE=False`
  (`test_cookie_no_secure_flag_when_disabled` unaffected — it only checks the login header, and even a
  clear header would omit `Secure` when disabled).

## 6. Local-override guard (process)

`app/config.py:58` currently carries the uncommitted local `OLLAMA_MODEL_NAME="qwen3:4b"` dev override.
Per the standing rule, **revert it to `"qwen3:8b"` before committing** (it breaks the 4 test_config
model-name assertions) and re-apply after. This feature touches `config.py`, so this guard applies.

## 7. Risk / reversibility

- Fully reversible: unset the two env vars ⇒ byte-identical to pre-048 (localhost tuple + Lax + clear
  path without explicit Secure... note: the clear-path `secure=` addition persists even at default, but
  is a no-op when `AUTH_COOKIE_SECURE=False`, i.e. local dev — verified harmless by the existing logout
  test staying green).
- No migration, no state, no graph. Blast radius = config load + two cookie writes + CORS allowlist
  source.
