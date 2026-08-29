"""Feature 051 (AC-4): the three stores obtain their connection from the db_backend factory
(not a direct sqlite3.connect), so setting TURSO_DATABASE_URL routes them to Turso.
"""

import sqlite3
from unittest.mock import MagicMock

import app.runner.db_backend as db_backend
from app.runner.store import JobStore
from app.runner.user_store import UserStore
from app.runner.password_reset_store import PasswordResetStore


def _spy(monkeypatch):
    """Patch db_backend.connect with a spy returning a real in-memory SQLite conn (store still works)."""
    real = sqlite3.connect(":memory:", check_same_thread=False)
    real.row_factory = sqlite3.Row
    spy = MagicMock(return_value=real)
    monkeypatch.setattr(db_backend, "connect", spy)
    return spy


def test_jobstore_routes_through_db_backend(monkeypatch, tmp_path):
    spy = _spy(monkeypatch)
    JobStore(str(tmp_path / "s.db"))
    spy.assert_called_once_with(str(tmp_path / "s.db"))


def test_userstore_routes_through_db_backend(monkeypatch, tmp_path):
    spy = _spy(monkeypatch)
    UserStore(str(tmp_path / "s.db"))
    spy.assert_called_once_with(str(tmp_path / "s.db"))


def test_password_reset_store_routes_through_db_backend(monkeypatch, tmp_path):
    spy = _spy(monkeypatch)
    PasswordResetStore(str(tmp_path / "s.db"))
    spy.assert_called_once_with(str(tmp_path / "s.db"))
