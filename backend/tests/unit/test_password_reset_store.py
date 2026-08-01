"""
Unit tests for PasswordResetStore (feature 034) — SQL CRUD over password_reset_tokens.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.runner.migrations import upgrade_to_head


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture
def store(tmp_path):
    from app.runner.password_reset_store import PasswordResetStore

    db = str(tmp_path / "prt.db")
    upgrade_to_head(db)
    s = PasswordResetStore(db)
    yield s
    s.close()


def test_create_and_get_by_hash(store):
    now = _now()
    exp = (now + timedelta(minutes=30)).isoformat()
    store.create("t1", "user-a", "HASH_A", now.isoformat(), exp)

    row = store.get_by_hash("HASH_A")
    assert row is not None
    assert row.id == "t1"
    assert row.user_id == "user-a"
    assert row.token_hash == "HASH_A"
    assert row.expires_at == exp
    assert row.used_at is None

    assert store.get_by_hash("nope") is None


def test_mark_used(store):
    now = _now()
    store.create("t1", "user-a", "HASH_A", now.isoformat(), (now + timedelta(minutes=30)).isoformat())
    used = now.isoformat()
    assert store.mark_used("t1", used) is True  # consumed
    assert store.get_by_hash("HASH_A").used_at == used


def test_mark_used_is_atomic_single_use(store):
    """Only the FIRST consume returns True; a second returns False (TOCTOU guard, AC-12)."""
    now = _now()
    store.create("t1", "user-a", "HASH_A", now.isoformat(), (now + timedelta(minutes=30)).isoformat())
    assert store.mark_used("t1", now.isoformat()) is True
    assert store.mark_used("t1", (now + timedelta(seconds=1)).isoformat()) is False


def test_invalidate_user_tokens_scoped_to_unused(store):
    now = _now()
    iso = now.isoformat()
    exp = (now + timedelta(minutes=30)).isoformat()
    store.create("t1", "user-a", "HASH_A", iso, exp)          # unused
    store.create("t2", "user-a", "HASH_A2", iso, exp)         # unused
    store.create("t3", "user-b", "HASH_B", iso, exp)          # other user
    store.mark_used("t2", iso)                                 # already used

    store.invalidate_user_tokens("user-a", iso)

    assert store.get_by_hash("HASH_A").used_at == iso          # unused → now used
    assert store.get_by_hash("HASH_A2").used_at == iso         # stays used (unchanged value ok)
    assert store.get_by_hash("HASH_B").used_at is None         # other user untouched


def test_delete_expired_or_used_for_user(store):
    now = _now()
    iso = now.isoformat()
    fresh_exp = (now + timedelta(minutes=30)).isoformat()
    past_exp = (now - timedelta(minutes=1)).isoformat()

    store.create("fresh", "user-a", "H_FRESH", iso, fresh_exp)   # keep
    store.create("expired", "user-a", "H_EXP", iso, past_exp)    # delete (expired)
    store.create("used", "user-a", "H_USED", iso, fresh_exp)     # delete (used)
    store.mark_used("used", iso)
    store.create("other", "user-b", "H_OTHER", iso, past_exp)    # keep (other user)

    store.delete_expired_or_used_for_user("user-a", iso)

    assert store.get_by_hash("H_FRESH") is not None
    assert store.get_by_hash("H_EXP") is None
    assert store.get_by_hash("H_USED") is None
    assert store.get_by_hash("H_OTHER") is not None
