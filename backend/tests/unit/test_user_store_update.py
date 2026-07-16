"""Feature 023 — UserStore.update_profile / update_password (spec AC-8).

Unit-level: build a store on a tmp DB, mutate, re-open a fresh store on the same path and
assert the write persisted while id/email/created_at are untouched.
"""

from app.api.security import hash_password, verify_password
from app.runner.migrations import upgrade_to_head
from app.runner.user_store import UserStore


def _fresh_db(tmp_path) -> str:
    db = str(tmp_path / "users.db")
    upgrade_to_head(db)
    return db


def test_update_profile_persists_and_preserves_other_columns(tmp_path):
    db = _fresh_db(tmp_path)
    store = UserStore(db)
    u = store.create("a@x.com", hash_password("Pw1!pass"), name="Old", title="OldTitle")

    updated = store.update_profile(u.id, "New Name", "New Title")
    assert updated.name == "New Name"
    assert updated.title == "New Title"
    store.close()

    row = UserStore(db).get_by_id(u.id)  # re-open → durable
    assert row.name == "New Name"
    assert row.title == "New Title"
    assert row.email == "a@x.com"
    assert row.id == u.id
    assert row.created_at == u.created_at


def test_update_profile_can_null_title(tmp_path):
    db = _fresh_db(tmp_path)
    store = UserStore(db)
    u = store.create("b@x.com", hash_password("Pw1!pass"), name="B", title="T")

    store.update_profile(u.id, "B", None)
    store.close()

    assert UserStore(db).get_by_id(u.id).title is None


def test_update_password_persists(tmp_path):
    db = _fresh_db(tmp_path)
    store = UserStore(db)
    u = store.create("c@x.com", hash_password("OldPw1!"), name="C")

    store.update_password(u.id, hash_password("NewPw2!"))
    store.close()

    row = UserStore(db).get_by_id(u.id)
    assert verify_password("NewPw2!", row.password_hash)
    assert not verify_password("OldPw1!", row.password_hash)
