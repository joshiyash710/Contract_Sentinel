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


def _raw_token(store, user_id):
    """Read the raw (possibly-ciphertext) google_oauth_token straight from the DB, bypassing decrypt."""
    row = store._conn.execute(
        "SELECT google_oauth_token FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return row[0] if row is not None else None


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


def test_create_with_name_title_roundtrip(user_db):
    """Feature 020 (AC-1): name/title persist and read back; title may be None."""
    row = user_db.create("dana@example.com", "hash_dana", "Dana Scully", "Special Agent")
    assert row.name == "Dana Scully"
    assert row.title == "Special Agent"

    by_email = user_db.get_by_email("dana@example.com")
    assert by_email.name == "Dana Scully" and by_email.title == "Special Agent"
    by_id = user_db.get_by_id(row.id)
    assert by_id.name == "Dana Scully" and by_id.title == "Special Agent"

    # title omitted → stored None (legacy-friendly).
    row2 = user_db.create("eve@example.com", "hash_eve", "Eve")
    assert row2.name == "Eve" and row2.title is None
    assert user_db.get_by_id(row2.id).title is None


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


# ── Feature 031: per-user Google Drive credentials ───────────────────────────
def test_google_credentials_default_none(user_db):
    row = user_db.create("g0@example.com", "h")
    assert user_db.get_google_credentials(row.id) is None
    assert user_db.get_google_email(row.id) is None
    # loaded row also reflects not-connected
    assert user_db.get_by_id(row.id).google_oauth_token is None


def test_set_and_get_google_credentials(user_db):
    row = user_db.create("g1@example.com", "h")
    user_db.set_google_credentials(row.id, '{"refresh_token":"abc"}', "g1@gmail.com")
    assert user_db.get_google_credentials(row.id) == '{"refresh_token":"abc"}'
    assert user_db.get_google_email(row.id) == "g1@gmail.com"
    assert user_db.get_by_id(row.id).google_email == "g1@gmail.com"


def test_clear_google_credentials(user_db):
    row = user_db.create("g2@example.com", "h")
    user_db.set_google_credentials(row.id, '{"refresh_token":"x"}', "g2@gmail.com")
    user_db.clear_google_credentials(row.id)
    assert user_db.get_google_credentials(row.id) is None
    assert user_db.get_google_email(row.id) is None


def test_google_credentials_scoped_per_user(user_db):
    a = user_db.create("ga@example.com", "h")
    b = user_db.create("gb@example.com", "h")
    user_db.set_google_credentials(a.id, '{"refresh_token":"A"}', "a@gmail.com")
    # B is untouched; clearing A does not touch B
    assert user_db.get_google_credentials(b.id) is None
    user_db.set_google_credentials(b.id, '{"refresh_token":"B"}', "b@gmail.com")
    user_db.clear_google_credentials(a.id)
    assert user_db.get_google_credentials(a.id) is None
    assert user_db.get_google_credentials(b.id) == '{"refresh_token":"B"}'


# ── Feature 032 (W1): OAuth-token encryption at rest ─────────────────────────────


def test_stored_token_is_ciphertext_and_roundtrips(user_db):
    # AC-2: the stored value is NOT the plaintext and does not leak "refresh_token".
    row = user_db.create("enc@example.com", "h")
    plaintext = '{"refresh_token": "secret-abc", "token": "t"}'
    user_db.set_google_credentials(row.id, plaintext, "e@gmail.com")

    raw = _raw_token(user_db, row.id)
    assert raw is not None
    assert raw != plaintext
    assert "refresh_token" not in raw
    assert "secret-abc" not in raw
    # Decrypt-on-read returns exactly the original.
    assert user_db.get_google_credentials(row.id) == plaintext
    # _row_to_user also decrypts (consistency): UserRow carries plaintext, never ciphertext.
    assert user_db.get_by_id(row.id).google_oauth_token == plaintext


def test_legacy_plaintext_token_read_then_reencrypted(user_db):
    # AC-5: a pre-032 plaintext value is readable as-is, and re-encrypted on the next write.
    row = user_db.create("legacy@example.com", "h")
    legacy = '{"refresh_token": "legacy-plain"}'
    # Simulate a row written before feature 032 (plaintext straight into the column).
    with user_db._lock:
        user_db._conn.execute(
            "UPDATE users SET google_oauth_token = ? WHERE id = ?", (legacy, row.id)
        )
        user_db._conn.commit()
    assert _raw_token(user_db, row.id) == legacy  # still plaintext on disk
    assert user_db.get_google_credentials(row.id) == legacy  # tolerated on read

    # Next write encrypts it.
    user_db.set_google_credentials(row.id, legacy, "l@gmail.com")
    raw = _raw_token(user_db, row.id)
    assert raw != legacy
    assert "legacy-plain" not in raw
    assert user_db.get_google_credentials(row.id) == legacy


def test_corrupt_ciphertext_reads_as_none(user_db):
    # EC-1/EC-2: corrupt/foreign value that is neither valid ciphertext nor a plaintext token → None.
    row = user_db.create("corrupt@example.com", "h")
    with user_db._lock:
        user_db._conn.execute(
            "UPDATE users SET google_oauth_token = ? WHERE id = ?",
            ("!!not-a-valid-fernet-token!!", row.id),
        )
        user_db._conn.commit()
    assert user_db.get_google_credentials(row.id) is None
    assert user_db.get_by_id(row.id).google_oauth_token is None


def test_empty_token_stored_as_null(user_db):
    # EC-11: encrypting empty/None must store SQL NULL, not encrypt("").
    row = user_db.create("empty@example.com", "h")
    user_db.set_google_credentials(row.id, "", "e@gmail.com")
    assert _raw_token(user_db, row.id) is None
    assert user_db.get_google_credentials(row.id) is None
