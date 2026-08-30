"""Alembic migration helper for the ContractSentinel store DB.

upgrade_to_head() is the single call site used by the FastAPI lifespan and tests to migrate a fresh or
existing store DB to the latest schema without a shell step (spec AC-18/19, EC-8 — fail fast on any
Alembic error).

Feature 051: when TURSO_DATABASE_URL is set, migrate the Turso (libSQL) store DB via the
`sqlalchemy-libsql` dialect instead of the local SQLite file. That dialect builds only on Linux, so the
Turso branch runs only in the Linux deploy (Windows dev uses local SQLite). TURSO_AUTH_TOKEN is redacted
from any raised error so a connection failure cannot leak it.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

import app.config as _config


def _turso_sqlalchemy_url() -> str:
    """Build the sqlalchemy-libsql URL for the Turso store DB (Linux-only migration path).

    TURSO_DATABASE_URL is `libsql://<host>`; the dialect wants
    `sqlite+libsql://<host>/?authToken=<token>&secure=true`.
    """
    host = _config.TURSO_DATABASE_URL.split("://", 1)[-1].rstrip("/")
    # No trailing slash before the query — a "/" path can make the dialect treat it as a local DB file
    # and drop the remote authToken (matches the documented sqlalchemy-libsql form).
    return f"sqlite+libsql://{host}?authToken={_config.TURSO_AUTH_TOKEN}&secure=true"


def upgrade_to_head(db_path: str) -> None:
    """Run `alembic upgrade head` on the store DB.

    Default: the local SQLite file (`sqlite:///{db_path}`), byte-for-byte as before. When
    TURSO_DATABASE_URL is set, migrate the Turso DB via the sqlalchemy-libsql dialect (Linux-only).
    Resolves the Alembic script directory relative to this file (spec AC-18). Raises on any Alembic
    error — never swallows (spec EC-8) — with TURSO_AUTH_TOKEN redacted from the message.
    """
    alembic_dir = Path(__file__).parents[2] / "alembic"
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    if _config.TURSO_DATABASE_URL:
        cfg.set_main_option("sqlalchemy.url", _turso_sqlalchemy_url())
    else:
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    try:
        command.upgrade(cfg, "head")
    except Exception as exc:
        token = _config.TURSO_AUTH_TOKEN
        if token and token in str(exc):
            # Never let a connection error leak the token via its URL-bearing message.
            raise type(exc)(str(exc).replace(token, "<redacted>")) from None
        raise
