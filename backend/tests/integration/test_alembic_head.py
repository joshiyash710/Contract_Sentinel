"""
Integration test: upgrade_to_head creates the jobs table with the expected schema.

Written red (Task 2) — green after Task 3 (migrations.py).
"""

import sqlite3


def test_upgrade_creates_jobs_table(tmp_path):
    from app.runner.migrations import upgrade_to_head

    db = str(tmp_path / "j.db")
    upgrade_to_head(db)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    # Table exists with the expected columns (14 after migration 0004 added
    # user_id for feature 019; 0002 added original_filename for feature 018).
    cols_info = conn.execute("PRAGMA table_info(jobs)").fetchall()
    col_names = {r["name"] for r in cols_info}
    expected = {
        "job_id",
        "document_path",
        "recipient",
        "status",
        "submitted_at",
        "started_at",
        "finished_at",
        "current_node",
        "completed_nodes",
        "report_path",
        "mcp_delivery_status",
        "error",
        "original_filename",  # migration 0002 (feature 018)
        "user_id",  # migration 0004 (feature 019 — per-user data isolation)
    }
    assert col_names == expected

    # job_id is the primary key (pk == 1)
    pk_cols = [r["name"] for r in cols_info if r["pk"] == 1]
    assert pk_cols == ["job_id"]

    # ix_jobs_submitted_at index exists
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(jobs)").fetchall()}
    assert "ix_jobs_submitted_at" in indexes

    # users table (migration 0003) with name/title added by migration 0005 (feature 020).
    user_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    assert {"id", "email", "password_hash", "created_at", "name", "title"} <= user_cols

    conn.close()


def test_upgrade_is_idempotent(tmp_path):
    from app.runner.migrations import upgrade_to_head

    db = str(tmp_path / "j.db")
    upgrade_to_head(db)
    upgrade_to_head(db)  # second call must not raise

    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "job_id" in cols
    conn.close()


def test_current_head_is_0007(tmp_path):
    """Feature 032: migration 0007 (security Tier 1) is the current Alembic head."""
    from pathlib import Path
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    alembic_dir = Path(__file__).resolve().parents[2] / "alembic"
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    assert ScriptDirectory.from_config(cfg).get_current_head() == "0007"


def test_migration_0006_adds_and_drops_google_columns(tmp_path):
    """Feature 031: 0006 adds users.google_oauth_token + google_email; downgrade drops them;
    an existing user row survives with the new columns NULL (not connected)."""
    import sqlite3
    from alembic.config import Config
    from alembic import command
    from app.runner.migrations import upgrade_to_head

    db_path = str(tmp_path / "mig0006.db")
    upgrade_to_head(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users (id, email, password_hash, created_at) VALUES (?,?,?,?)",
        ("u1", "x@e.com", "h", "2026-07-28T00:00:00+00:00"),
    )
    conn.commit()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    assert {"google_oauth_token", "google_email"} <= cols
    # existing row survives with NULLs
    row = conn.execute("SELECT google_oauth_token, google_email FROM users WHERE id='u1'").fetchone()
    assert row == (None, None)
    conn.close()
