"""
Feature 032 migration 0007 (integration): additive DDL (session_epoch + lockout state) plus the
idempotent OAuth-token backfill (encrypt legacy plaintext in place). Serves AC-5, AC-18.
"""

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

    # Feature 052 added migration 0009 (report_blobs), now the head; 0007 remains in the chain
    # (verified by the upgrade/downgrade tests below).
    script = ScriptDirectory.from_config(_cfg(str(tmp_path / "x.db")))
    assert script.get_current_head() == "0009"


def test_0007_adds_columns_and_encrypts_legacy_plaintext(tmp_path):
    from app.security import crypto

    db = str(tmp_path / "m7.db")
    cfg = _cfg(db)
    command.upgrade(cfg, "0006")  # stop just before 0007

    legacy = '{"refresh_token": "legacy-mig"}'
    already = crypto.encrypt('{"refresh_token": "already-enc"}')
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO users (id,email,password_hash,created_at,google_oauth_token) VALUES (?,?,?,?,?)",
        ("u1", "a@e.com", "h", "t", legacy),
    )
    conn.execute(
        "INSERT INTO users (id,email,password_hash,created_at,google_oauth_token) VALUES (?,?,?,?,?)",
        ("u2", "b@e.com", "h", "t", already),
    )
    conn.execute(
        "INSERT INTO users (id,email,password_hash,created_at) VALUES (?,?,?,?)",
        ("u3", "c@e.com", "h", "t"),  # NULL token
    )
    conn.commit()
    conn.close()

    command.upgrade(cfg, "0007")

    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    assert {"session_epoch", "failed_login_count", "first_failure_at", "lockout_until"} <= cols
    # additive defaults
    assert conn.execute("SELECT session_epoch, failed_login_count FROM users WHERE id='u1'").fetchone() == (0, 0)

    # u1: legacy plaintext is now encrypted in place.
    v1 = conn.execute("SELECT google_oauth_token FROM users WHERE id='u1'").fetchone()[0]
    assert "refresh_token" not in v1
    assert crypto.decrypt(v1) == legacy

    # u2: already-encrypted value is NOT double-encrypted (decrypts in one step — idempotent, AC-5).
    v2 = conn.execute("SELECT google_oauth_token FROM users WHERE id='u2'").fetchone()[0]
    assert crypto.decrypt(v2) == '{"refresh_token": "already-enc"}'

    # u3: NULL stays NULL.
    assert conn.execute("SELECT google_oauth_token FROM users WHERE id='u3'").fetchone()[0] is None
    conn.close()


def test_0007_downgrade_drops_the_four_columns(tmp_path):
    db = str(tmp_path / "m7d.db")
    cfg = _cfg(db)
    command.upgrade(cfg, "0007")
    command.downgrade(cfg, "0006")

    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    conn.close()
    assert not ({"session_epoch", "failed_login_count", "first_failure_at", "lockout_until"} & cols)
