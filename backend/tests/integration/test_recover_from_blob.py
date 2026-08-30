"""Feature 054 (AC-3): a non-terminal job whose source exists ONLY as a Turso upload blob is recovered
on boot and runs to a terminal state by reading the blob — proving restart-survival.

Unlike test_recover_missing_upload (which fully fakes the graph), this test's fake graph calls the REAL
`ingest_agent`, so the real `_materialize_plaintext` blob read is genuinely exercised (plan §6 warning).
"""

import sqlite3
import time
from pathlib import Path

import app.config as _cfg
import app.blob_store as blob_store
from app.runner.migrations import upgrade_to_head
from app.runner.models import JobState
from app.runner.store import JobRow, JobStore
from app.security import crypto


def _local_turso_conn():
    c = sqlite3.connect(_cfg.JOB_STORE_DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _seed_blob_source(job_store_path, document_path, pdf_bytes):
    """Migrate the DB and store the ENCRYPTED sample PDF as the ONLY copy of the source (blob, no disk)."""
    upgrade_to_head(job_store_path)  # creates upload_blobs (0010)
    conn = sqlite3.connect(job_store_path)
    conn.execute(
        "INSERT INTO upload_blobs (key, data, created_at) VALUES (?,?,?)",
        (document_path, crypto.encrypt_bytes(pdf_bytes), "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()


def _seed_queued(job_store_path, job_id, user_id, document_path):
    store = JobStore(job_store_path)
    store.upsert(
        JobRow(
            job_id=job_id,
            document_path=document_path,
            recipient=None,
            status=JobState.queued,
            submitted_at="2026-01-01T00:00:00+00:00",
            started_at=None,
            finished_at=None,
            current_node=None,
            completed_nodes=[],
            report_path=None,
            mcp_delivery_status={},
            error=None,
            user_id=user_id,
        )
    )
    store.close()


def _make_client(monkeypatch, tmp_path, job_store_path, checkpoints_path):
    from app.api.main import create_app
    from starlette.testclient import TestClient

    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / "recover.md"
    json_path = report_dir / "recover.json"
    md_path.write_text("# Risk Report\n")
    json_path.write_text('{"risk_score": "HIGH", "findings": []}')

    def _fake_build_graph_real_ingest(checkpointer=None):
        from app.graph.nodes.ingest_agent import ingest_agent

        class _FG:
            def stream(self, initial, stream_mode=None, config=None):
                doc = (initial or {}).get("document_path", "")
                ing = ingest_agent({"document_path": doc})  # REAL ingest → reads the upload blob
                if ing.get("ingest_error"):
                    yield {"current_node": "ingest_agent", "document_path": doc,
                           "ingest_error": ing["ingest_error"]}
                    return
                for node in ["ingest_agent", "clause_splitter", "crag_retrieval",
                             "self_rag_validation", "risk_score", "redline"]:
                    yield {"current_node": node, "document_path": doc, "node_timings": {node: 0.01}}
                yield {"current_node": "report", "document_path": doc,
                       "node_timings": {"report": 0.01}, "report_path": str(md_path),
                       "document_id": "recover"}

        return _FG()

    monkeypatch.setattr("app.runner.core.build_graph", _fake_build_graph_real_ingest)
    monkeypatch.setattr(
        "app.runner.core.deliver_report_sync",
        lambda state, *, recipient=None, drive_token_json=None: {"mcp_delivery_status": {}},
    )
    monkeypatch.setattr(_cfg, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(_cfg, "JOB_STORE_DB_PATH", job_store_path)
    monkeypatch.setattr(_cfg, "CHECKPOINTER_DB_PATH", checkpoints_path)
    monkeypatch.setattr(_cfg, "STARTUP_RECOVERY_ENABLED", True)
    # Feature 054: Turso backend, routed at the local migrated job_store.db (has upload_blobs).
    monkeypatch.setattr(_cfg, "TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setattr(_cfg, "TURSO_AUTH_TOKEN", "dummy-token")  # satisfy the lifespan prod-config guard
    monkeypatch.setattr(blob_store, "_conn", _local_turso_conn)
    # Windows can't drive the libsql SQLAlchemy dialect (migrations) or real libsql stores, so route the
    # app's stores at local sqlite and skip the lifespan migration (already applied by _seed_blob_source).
    # This simulates "Turso" with local sqlite for ALL db access — exactly like the blob-store unit tests.
    import app.runner.db_backend as db_backend

    def _local_connect(db_path):
        c = sqlite3.connect(db_path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(db_backend, "connect", _local_connect)
    monkeypatch.setattr("app.api.main.upgrade_to_head", lambda db_path: None)
    monkeypatch.setenv("AUTH_SECRET", "recover_blob_test_secret_" + "x" * 12)
    monkeypatch.setattr(_cfg, "AUTH_SECRET_FILE", str(tmp_path / "auth_secret"))

    return TestClient(create_app())


def test_recover_reads_source_from_blob(monkeypatch, tmp_path, sample_pdf_path):
    """A queued job with source only in upload_blobs completes on recovery (AC-3)."""
    job_id = "recover-from-blob-job"
    job_store = str(tmp_path / "job_store.db")
    checkpoints = str(tmp_path / "checkpoints.db")
    document_path = str(tmp_path / "uploads" / f"{job_id}.pdf")  # never written to disk
    with open(sample_pdf_path, "rb") as f:
        pdf_bytes = f.read()

    from tests.integration.conftest import RECOVERY_USER_ID, authenticate_as, seed_owner_user

    email, pw = seed_owner_user(job_store)
    _seed_blob_source(job_store, document_path, pdf_bytes)
    _seed_queued(job_store, job_id, RECOVERY_USER_ID, document_path)

    assert not Path(document_path).exists()  # source is ONLY in the blob store

    with _make_client(monkeypatch, tmp_path, job_store, checkpoints) as c:
        authenticate_as(c, email, pw)
        deadline = time.monotonic() + 8.0
        final = None
        while time.monotonic() < deadline:
            r = c.get(f"/api/jobs/{job_id}")
            if r.status_code == 200 and r.json()["status"] in ("completed", "failed"):
                final = r.json()
                break
            time.sleep(0.05)
        assert final is not None, "job never reached a terminal state"
        # Completed via the blob read — NOT the corrupted_file path a missing source would give.
        assert final["status"] == "completed", f"expected completed, got {final}"
