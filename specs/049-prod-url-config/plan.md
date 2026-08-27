# Feature 049 — Technical plan

Branch: `feature/049-prod-url-config` (off the 048 deploy-config tip).
Spec: spec-reviewer APPROVED.

## 1. Overview
Two hardcoded-localhost config literals become env-overridable via a new `_env_str` helper. Defaults
byte-identical. No graph/state/edge/migration change. Files touched:
- `app/config.py` — add `_env_str`; wrap `GOOGLE_OAUTH_REDIRECT_URI` (:531) and
  `FRONTEND_INTEGRATIONS_URL` (:542).
- `docs/DEPLOYMENT.md` — §6 + §8 rows.
- `tests/unit/test_config.py` — helper tests (AC-3/AC-4 + edge).

`app/api/integrations.py` is NOT edited (it reads `_config.GOOGLE_OAUTH_REDIRECT_URI` /
`_config.FRONTEND_INTEGRATIONS_URL` by attribute, so it transparently picks up the env-sourced value).

## 2. Config implementation (`app/config.py`)

Add the helper next to `_env_bool`/`_env_int` (~line 39, after `_env_int`):
```python
def _env_str(name: str, default: str) -> str:
    """Read a string env override; falls back to default on unset/blank (mirrors _env_bool/_env_int)."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()
```

Wrap the two constants (keep the existing explanatory comments beneath each):
```python
GOOGLE_OAUTH_REDIRECT_URI: str = _env_str(
    "GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/api/integrations/google/callback"
)
...
FRONTEND_INTEGRATIONS_URL: str = _env_str(
    "FRONTEND_INTEGRATIONS_URL", "http://localhost:3000/integrations"
)
```
Note: `_env_str` trims, so a non-blank value is returned stripped (harmless for URLs). Defaults are the
exact current literals ⇒ the 031 tests (`test_per_user_drive_031_constants_match_spec`) stay green.

## 3. Docs (`docs/DEPLOYMENT.md`)
- §8 env table: add `GOOGLE_OAUTH_REDIRECT_URI` (prod = `https://api.<domain>/api/integrations/google/callback`)
  and `FRONTEND_INTEGRATIONS_URL` (prod = `https://<app>.vercel.app/integrations`).
- §6 (Google OAuth): note that the deployed backend must set `GOOGLE_OAUTH_REDIRECT_URI` to the exact
  URI registered on the GCP Web OAuth client, and `FRONTEND_INTEGRATIONS_URL` to the Vercel integrations
  page (else the post-connect 302 lands on dead localhost).

## 4. Test plan (§7 TDD — write first)
`tests/unit/test_config.py` (extend, no reload — mirror the 048 helper tests at ~line 639+):
- AC-3: `monkeypatch.setenv("CS_TEST_REDIRECT", "https://api.example.com/api/integrations/google/callback")`
  ⇒ `config._env_str("CS_TEST_REDIRECT", "x")` equals it.
- AC-4: `monkeypatch.setenv("CS_TEST_FRONT", "https://app.example.com/integrations")` ⇒ `_env_str` equals it.
- Edge: `_env_str("CS_TEST_UNSET", default)` unset / `""` / whitespace ⇒ returns `default`.
- AC-1/AC-2: optional explicit default asserts (031 tests already cover; keep them unmodified).

## 5. Pre-commit guard
- `app/config.py:58` `OLLAMA_MODEL_NAME` is currently `qwen3:8b` (was reverted for the 048 commits on
  this branch's parent). Confirm it is still `qwen3:8b` before committing (do NOT reintroduce qwen3:4b).

## 6. Risk / reversibility
Fully reversible (unset env ⇒ pre-049 localhost defaults). No migration/state/graph. Blast radius = two
config reads + docs.
