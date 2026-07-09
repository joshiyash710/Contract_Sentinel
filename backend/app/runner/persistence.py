"""
SqliteSaver factory and checkpoint utilities (spec D2, §2.5).

build_saver() is the single call site for constructing the shared SqliteSaver
so the lifespan and CLI don't duplicate the construction or the setup() call.
"""

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver


def build_saver(db_path: str) -> SqliteSaver:
    """Create a SqliteSaver on the given file path.

    Uses check_same_thread=False because the worker thread and the lifespan
    (asyncio loop) both access the saver; SqliteSaver is internally thread-safe.
    setup() is idempotent — creates the checkpointer schema on first call and
    is a no-op on subsequent calls (spec D1 — owns its own schema, never Alembic).
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def has_checkpoint(saver: SqliteSaver, thread_id: str) -> bool:
    """Return True if a checkpoint exists for the given thread_id (spec AC-9)."""
    return saver.get_tuple({"configurable": {"thread_id": thread_id}}) is not None
