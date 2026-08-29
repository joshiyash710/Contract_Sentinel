"""Feature 053 (AC-4): .env.example documents the full deploy env surface (keys only, placeholders —
never a real secret value)."""

from pathlib import Path

_ENV = Path(__file__).resolve().parents[2] / ".env.example"

REQUIRED = [
    "LLM_PROVIDER", "GROQ_API_KEY", "GROQ_MODEL", "EMBED_PROVIDER", "HF_API_TOKEN", "HF_EMBED_MODEL",
    "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "AUTH_SECRET", "CONTRACTSENTINEL_ENCRYPTION_KEY",
    "CORS_ALLOWED_ORIGINS", "AUTH_COOKIE_SECURE", "AUTH_COOKIE_SAMESITE", "GOOGLE_OAUTH_REDIRECT_URI",
    "FRONTEND_INTEGRATIONS_URL",
]


def test_documents_all_deploy_keys():
    txt = _ENV.read_text(encoding="utf-8")
    for k in REQUIRED:
        assert f"{k}=" in txt, f".env.example is missing {k}="


def test_no_real_secret_values():
    txt = _ENV.read_text(encoding="utf-8")
    for bad in ("hf_", "gsk_", "eyJ"):  # HF token / Groq key / JWT prefixes
        assert bad not in txt, f".env.example appears to commit a real secret ({bad!r})"
