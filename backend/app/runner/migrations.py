"""Alembic migration helper for the ContractSentinel store DB.

upgrade_to_head() is the single call site used by the FastAPI lifespan, the container entrypoint, and
tests to migrate a fresh or existing store DB to the latest schema without a shell step (spec AC-18/19,
EC-8 — fail fast on any Alembic error).

Feature 053: when TURSO_DATABASE_URL is set, migrate the Turso (libSQL) store DB via `sqlalchemy-libsql`.
The auth token is passed via **connect_args** (`{"auth_token": …}`), NOT in the URL query — the dialect
does not consume `?authToken=` (a URL-token connects with an empty JWT → 401). The live connection is
injected into Alembic through `config.attributes["connection"]` (see alembic/env.py). That dialect builds
only on Linux, so the Turso branch runs only in the Linux deploy. TURSO_AUTH_TOKEN is redacted from any
raised error.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

import app.config as _config


def _turso_url() -> str:
    """sqlalchemy-libsql remote URL WITHOUT the token (token goes via connect_args — the documented
    remote form). `libsql://<host>` → `sqlite+libsql://<host>?secure=true`.
    """
    host = _config.TURSO_DATABASE_URL.split("://", 1)[-1].rstrip("/")
    return f"sqlite+libsql://{host}?secure=true"


def upgrade_to_head(db_path: str) -> None:
    """Run `alembic upgrade head` on the store DB.

    Default: the local SQLite file (`sqlite:///{db_path}`). When TURSO_DATABASE_URL is set, migrate the
    Turso DB via the sqlalchemy-libsql dialect (Linux-only), with the auth token in connect_args and the
    live connection injected into Alembic. Raises on any error (spec EC-8), with TURSO_AUTH_TOKEN redacted.
    """
    alembic_dir = Path(__file__).parents[2] / "alembic"
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    try:
        if _config.TURSO_DATABASE_URL:
            engine = create_engine(
                _turso_url(), connect_args={"auth_token": _config.TURSO_AUTH_TOKEN}
            )
            try:
                with engine.connect() as connection:
                    cfg.attributes["connection"] = connection  # consumed by alembic/env.py
                    command.upgrade(cfg, "head")
            finally:
                engine.dispose()
        else:
            cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
            command.upgrade(cfg, "head")
    except Exception as exc:
        token = _config.TURSO_AUTH_TOKEN
        if token and token in str(exc):
            # Never let a connection error leak the token via its message.
            raise type(exc)(str(exc).replace(token, "<redacted>")) from None
        raise
