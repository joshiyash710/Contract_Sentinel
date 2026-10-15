"""Feature 066 migration 0011 (integration): additive nullable risk-summary columns on `jobs`. AC-1."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

_NEW_COLS = {"risk_high", "risk_medium", "risk_low", "validated_findings",
             "total_clauses", "analysis_degraded", "risk_by_type"}


def _cfg(db_path: str) -> Config:
    alembic_dir = Path(__file__).resolve().parents[2] / "alembic"
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_0011_down_revision_is_0010(tmp_path):
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_cfg(str(tmp_path / "x.db")))
    assert script.get_revision("0011").down_revision == "0010"


def test_0011_adds_nullable_risk_columns(tmp_path):
    db = str(tmp_path / "m11.db")
    command.upgrade(_cfg(db), "head")
    conn = sqlite3.connect(db)
    info = {r[1]: r for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    conn.close()
    assert _NEW_COLS <= set(info)
    for c in _NEW_COLS:
        assert info[c][3] == 0  # notnull flag is 0 → nullable (legacy rows → NULL)


def test_0011_preserves_existing_rows_as_null(tmp_path):
    db = str(tmp_path / "m11b.db")
    cfg = _cfg(db)
    command.upgrade(cfg, "0010")  # schema BEFORE 0011
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO jobs (job_id, document_path, status, submitted_at, completed_nodes, "
        "mcp_delivery_status) VALUES ('j1','/u/j1.pdf','completed','2026-01-01T00:00:00+00:00','[]','{}')"
    )
    conn.commit()
    conn.close()
    command.upgrade(cfg, "0011")  # add the columns to a DB with an existing row
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT risk_high, risk_by_type FROM jobs WHERE job_id='j1'").fetchone()
    conn.close()
    assert row == (None, None)  # pre-existing row survives with the new cols NULL


def test_0011_downgrade_drops_the_columns(tmp_path):
    db = str(tmp_path / "m11d.db")
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0010")
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    conn.close()
    assert not (_NEW_COLS & cols)  # all seven dropped
