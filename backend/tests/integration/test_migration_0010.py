"""Feature 054 migration 0010 (integration): additive `upload_blobs` table for durable uploads.
Serves AC-8."""

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


def test_0010_down_revision_is_0009(tmp_path):
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_cfg(str(tmp_path / "x.db")))
    assert script.get_revision("0010").down_revision == "0009"


def test_0010_creates_upload_blobs(tmp_path):
    db = str(tmp_path / "m10.db")
    command.upgrade(_cfg(db), "head")
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(upload_blobs)").fetchall()}
    conn.close()
    assert {"key", "data", "created_at"} <= cols


def test_0010_downgrade_drops_upload_blobs(tmp_path):
    db = str(tmp_path / "m10d.db")
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0009")
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "upload_blobs" not in tables
