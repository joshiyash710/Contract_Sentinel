"""Feature 052 migration 0009 (integration): additive `report_blobs` table for Turso blob storage.
Serves AC-7."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def _cfg(db_path: str) -> Config:
    alembic_dir = Path(__file__).resolve().parents[2] / "alembic"
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_head_is_0009(tmp_path):
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_cfg(str(tmp_path / "x.db")))
    assert script.get_current_head() == "0009"


def test_0009_down_revision_is_0008(tmp_path):
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_cfg(str(tmp_path / "x.db")))
    assert script.get_revision("0009").down_revision == "0008"


def test_0009_creates_report_blobs(tmp_path):
    db = str(tmp_path / "m9.db")
    command.upgrade(_cfg(db), "head")
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(report_blobs)").fetchall()}
    conn.close()
    assert {"key", "data", "created_at"} <= cols


def test_0009_downgrade_drops_report_blobs(tmp_path):
    db = str(tmp_path / "m9d.db")
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0008")
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "report_blobs" not in tables
