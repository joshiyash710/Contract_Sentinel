"""Alembic migration helper for the ContractSentinel job store.

upgrade_to_head() is the single call site used by the FastAPI lifespan and
tests to migrate a fresh or existing SQLite DB to the latest schema without
a shell step (spec AC-18/19, EC-8 — fail fast on any Alembic error).
"""

from pathlib import Path

from alembic import command
from alembic.config import Config


def upgrade_to_head(db_path: str) -> None:
    """Run `alembic upgrade head` on the given SQLite job-store file.

    Resolves the Alembic script directory relative to this file so the helper
    works regardless of the process working directory (spec AC-18).
    Raises on any Alembic error — never swallows (spec EC-8).
    """
    alembic_dir = Path(__file__).parents[2] / "alembic"
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")
