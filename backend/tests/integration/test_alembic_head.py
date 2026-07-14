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

    # Table exists with the expected columns (13 after migration 0002 added
    # original_filename for feature 018).
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
    }
    assert col_names == expected

    # job_id is the primary key (pk == 1)
    pk_cols = [r["name"] for r in cols_info if r["pk"] == 1]
    assert pk_cols == ["job_id"]

    # ix_jobs_submitted_at index exists
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(jobs)").fetchall()}
    assert "ix_jobs_submitted_at" in indexes

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
