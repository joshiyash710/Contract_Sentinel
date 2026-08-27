# Feature 048 — Implementation tasks

Branch: `feature/048-cross-origin-deploy-config`.
Spec + plan: spec-reviewer APPROVED. TDD order (§7): write failing tests first, then implement.

## T0 — Pre-flight (process guard)
- [ ] Confirm on branch `feature/048-cross-origin-deploy-config`.
- [ ] Note: `app/config.py:58` has the local `OLLAMA_MODEL_NAME="qwen3:4b"` dev override. It will be
      reverted to `"qwen3:8b"` in **T6** (pre-commit), re-applied after merge. Do NOT commit `qwen3:4b`.

## T1 — Failing tests: config helpers (`tests/unit/test_config.py`)
Write these first; they should fail (helpers/consts don't exist yet):
- [ ] AC-1: `config.CORS_ALLOWED_ORIGINS == ("http://localhost:5173", "http://127.0.0.1:5173")`.
- [ ] AC-2: `config._env_origin_tuple("CS_TEST_ORIGINS", <default>)` with
      `monkeypatch.setenv("CS_TEST_ORIGINS", "https://cs.vercel.app, https://foo.dev")`
      ⇒ `("https://cs.vercel.app", "https://foo.dev")`.
- [ ] Edge: same helper with env `","`, env `""`, and unset ⇒ returns the passed `default` tuple.
- [ ] AC-3: `config.AUTH_COOKIE_SAMESITE == "lax"`.
- [ ] AC-4: `config._env_samesite("CS_TEST_SS", "lax")` with env `"None"` ⇒ `"none"`.
- [ ] AC-5: `_env_samesite` with env `"bogus"` and whitespace-only ⇒ `"lax"`.
- [ ] AC-7: `pytest.raises(ValueError, match="AUTH_COOKIE_SAMESITE.*AUTH_COOKIE_SECURE")` on
      `config._validate_samesite_secure("none", secure=False)`; and
      `config._validate_samesite_secure("none", secure=True)` returns `None` (no raise);
      `_validate_samesite_secure("lax", secure=False)` also no raise.

## T2 — Failing test: auth cookie SameSite (`tests/integration/test_auth_session.py`)
- [ ] AC-6: new test — `monkeypatch.setattr(_c, "AUTH_COOKIE_SECURE", True)` +
      `monkeypatch.setattr(_c, "AUTH_COOKIE_SAMESITE", "none")`; assert login `Set-Cookie` (`.lower()`)
      for `cs_session` contains `samesite=none` and `secure`; assert the logout/clear `Set-Cookie`
      (`.lower()`) contains `samesite=none` and `secure`. (Follow the existing `_login` helper +
      `.lower()` substring style at lines 27-40.)

## T3 — Implement config (`app/config.py`)
- [ ] Add `_DEFAULT_CORS_ALLOWED_ORIGINS` + `_env_origin_tuple(name, default)` per plan §2a; replace the
      hardcoded `CORS_ALLOWED_ORIGINS` tuple (~line 593) with `_env_origin_tuple("CORS_ALLOWED_ORIGINS",
      _DEFAULT_CORS_ALLOWED_ORIGINS)`; keep the existing explanatory comment.
- [ ] Add `_ALLOWED_SAMESITE`, `_env_samesite(name, default)`, `_validate_samesite_secure(samesite,
      secure)` per plan §2b immediately after `AUTH_COOKIE_SECURE` (~line 683); define
      `AUTH_COOKIE_SAMESITE = _env_samesite("AUTH_COOKIE_SAMESITE", "lax")` then call the boot guard
      `_validate_samesite_secure(AUTH_COOKIE_SAMESITE, AUTH_COOKIE_SECURE)`.
- [ ] Run T1 → green.

## T4 — Implement auth cookie wiring (`app/api/auth.py`)
- [ ] `_set_session_cookie` (~line 264): `samesite="lax"` → `samesite=_cfg.AUTH_COOKIE_SAMESITE`.
- [ ] `_clear_session_cookie` (~line 276): `samesite="lax"` → `samesite=_cfg.AUTH_COOKIE_SAMESITE`, and
      add `secure=_cfg.AUTH_COOKIE_SECURE`.
- [ ] Run T2 → green. Confirm the two pre-existing cookie tests
      (`test_cookie_flags_secure_httponly_samesite`, `test_cookie_no_secure_flag_when_disabled`) stay
      green (AC-8, no regression).

## T5 — Docs (`docs/DEPLOYMENT.md`)
- [ ] §8 env table: add `CORS_ALLOWED_ORIGINS` and `AUTH_COOKIE_SAMESITE` rows (plan §4 wording).
- [ ] §5: replace the vague "SameSite=None" prose with the concrete `AUTH_COOKIE_SAMESITE=none` switch
      (+ note it requires `AUTH_COOKIE_SECURE=True`, and that `lax` suffices if frontend+backend share a
      registrable domain). (AC-9)

## T6 — Full suite + pre-commit guard
- [ ] Revert `app/config.py:58` `OLLAMA_MODEL_NAME` `qwen3:4b` → `qwen3:8b` (breaks 4 model-name
      test_config assertions otherwise).
- [ ] Run the full backend suite: `python -m pytest -q` from `backend/` — expect all green (prior
      baseline 1024; +new 048 tests).
- [ ] `git status` — confirm only intended files changed (config.py, auth.py, DEPLOYMENT.md, the two
      test files, the three spec artifacts). No `qwen3:4b`.

## T7 — Commit (only when the user asks) + finish
- [ ] Commit `feat(048): env-overridable CORS origins + cookie SameSite for cross-origin deploy`.
- [ ] git-finish against origin/main (rebase/verify → `merge --ff-only` → push → delete branch) — on
      user's go-ahead.
- [ ] Re-apply the local `qwen3:4b` override after merge (local dev only, uncommitted).

## Acceptance mapping
AC-1→T1, AC-2→T1, AC-3→T1, AC-4→T1, AC-5→T1, AC-6→T2/T4, AC-7→T1, AC-8→T4/T6, AC-9→T5.
