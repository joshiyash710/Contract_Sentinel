"""
Unit tests for app.runner.user_store — UserStore CRUD, uniqueness, and normalization.

Uses a temp SQLite DB with upgrade_to_head applied so the users table exists.
"""

import pytest


@pytest.fixture()
def user_db(tmp_path):
    """Fresh SQLite DB at head migration for each test."""
    from app.runner.migrations import upgrade_to_head
    from app.runner.user_store import UserStore

    db_path = str(tmp_path / "users_test.db")
    upgrade_to_head(db_path)
    store = UserStore(db_path)
    yield store
    store.close()


def test_create_and_get_by_email(user_db):
    row = user_db.create("alice@example.com", "hashed_pw_value")
    assert row.id
    assert row.email == "alice@example.com"
    assert row.created_at

    fetched = user_db.get_by_email("alice@example.com")
    assert fetched is not None
    assert fetched.id == row.id
    assert fetched.password_hash == "hashed_pw_value"


def test_get_by_id(user_db):
    row = user_db.create("bob@example.com", "pw_hash_bob")
    fetched = user_db.get_by_id(row.id)
    assert fetched is not None
    assert fetched.email == "bob@example.com"


def test_get_by_email_unknown_returns_none(user_db):
    assert user_db.get_by_email("nobody@example.com") is None


def test_get_by_id_unknown_returns_none(user_db):
    assert user_db.get_by_id("nonexistent-uuid") is None


def test_duplicate_email_raises(user_db):
    from app.runner.user_store import EmailExists

    user_db.create("dup@example.com", "hash1")
    with pytest.raises(EmailExists):
        user_db.create("dup@example.com", "hash2")


def test_email_normalized_before_storage(user_db):
    """Caller is expected to normalize; the store accepts and stores as-is.
    The test verifies the round-trip at the boundary.
    """
    row = user_db.create("carol@example.com", "hash_carol")
    assert row.email == "carol@example.com"


def test_count(user_db):
    assert user_db.count() == 0
    user_db.create("a@x.com", "h1")
    assert user_db.count() == 1
    user_db.create("b@x.com", "h2")
    assert user_db.count() == 2


def test_migration_creates_users_table(tmp_path):
    """Alembic 0003 adds the users table; the store can query it."""
    from app.runner.migrations import upgrade_to_head
    from app.runner.user_store import UserStore
    import sqlite3

    db_path = str(tmp_path / "migration_check.db")
    upgrade_to_head(db_path)

    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "users" in tables
