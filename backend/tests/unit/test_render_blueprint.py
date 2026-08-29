"""Feature 053 (AC-1): the repo-root render.yaml is a valid Render Blueprint — one Docker web service
on /api/health, required non-secret env inline, secrets as sync:false with NO committed value, no Render
database. Resolved CWD-independently (tests/unit → tests → backend → repo root)."""

from pathlib import Path

import yaml

_RENDER_YAML = Path(__file__).resolve().parents[3] / "render.yaml"


def _blueprint():
    return yaml.safe_load(_RENDER_YAML.read_text(encoding="utf-8"))


def test_one_docker_web_service_on_api_health():
    svc_list = _blueprint()["services"]
    assert len(svc_list) == 1
    svc = svc_list[0]
    assert svc["type"] == "web"
    assert svc["runtime"] == "docker"
    assert svc["rootDir"] == "backend"
    assert svc["healthCheckPath"] == "/api/health"


def test_required_env_and_secrets():
    svc = _blueprint()["services"][0]
    env = {e["key"]: e for e in svc["envVars"]}
    for k in ("LLM_PROVIDER", "EMBED_PROVIDER", "AUTH_COOKIE_SECURE", "AUTH_COOKIE_SAMESITE"):
        assert k in env and "value" in env[k], f"non-secret {k} must be inline"
    assert env["LLM_PROVIDER"]["value"] == "groq"
    assert env["EMBED_PROVIDER"]["value"] == "hf"
    for k in (
        "AUTH_SECRET", "CONTRACTSENTINEL_ENCRYPTION_KEY", "GROQ_API_KEY",
        "HF_API_TOKEN", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN",
    ):
        assert k in env, f"missing secret key {k}"
        assert env[k].get("sync") is False, f"secret {k} must be sync:false"
        assert "value" not in env[k], f"secret {k} must NOT commit a value"


def test_no_render_database_declared():
    assert "databases" not in _blueprint()  # Turso is the DB, not Render Postgres
