"""
Integration-suite fixtures for ContractSentinel backend tests.

Scoped to tests/integration/ (pytest discovers conftest.py hierarchically),
so these fixtures apply only to the integration tests, on top of the shared
fixtures in tests/conftest.py.
"""

import time
import pytest

import app.graph.nodes.report_agent as report_agent_mod

# ---------------------------------------------------------------------------
# Auth helpers (Task 5 — all integration tests must authenticate after 014)
# ---------------------------------------------------------------------------

_AUTH_EMAIL = "integration_test@example.com"
_AUTH_PASSWORD = "IntTestPass1!"


def authenticate(client) -> None:
    """Idempotent: sign up or log in a shared test user on the given TestClient.

    TestClient (httpx-backed) persists cookies on the instance, so one call
    makes the whole client session authenticated (plan §7 / spec D1).
    Signup-or-login handles the restart tests where c1 signs up and c2 logs in
    against the same persistent DB (409 → login).
    """
    r = client.post(
        "/api/auth/signup",
        json={"email": _AUTH_EMAIL, "password": _AUTH_PASSWORD},
    )
    if r.status_code in (409, 403):
        # 409 = dup email (same DB shared across clients in restart tests)
        # 403 = signup closed (AUTH_SIGNUP_OPEN=False, count>0 → fall back to login)
        r2 = client.post(
            "/api/auth/login",
            json={"email": _AUTH_EMAIL, "password": _AUTH_PASSWORD},
        )
        assert r2.status_code == 200, f"Login after {r.status_code} failed: {r2.text}"
    else:
        assert r.status_code == 200, f"Signup failed: {r.text}"


@pytest.fixture(autouse=True)
def _reset_auth_secret(monkeypatch):
    """Reset the security module's in-process secret cache before each test.

    load_secret() memoises to a module-level _SECRET. Without resetting it,
    a monkeypatched AUTH_SECRET from test A leaks into test B's lifespan call.
    """
    import app.api.security as sec
    monkeypatch.setattr(sec, "_SECRET", None)


@pytest.fixture(autouse=True)
def _isolate_report_output(tmp_path, monkeypatch):
    """Redirect ReportAgent's output directory to a per-test temp dir for the
    WHOLE integration suite.

    Feature-009 wired Node 7 (ReportAgent) as the terminal node, so every
    integration test that invokes the real ``build_graph()`` and runs to END now
    passes through ``report_agent``, which writes a Markdown + JSON report to
    ``REPORT_OUTPUT_DIR`` (default ``data/reports/``). Without this fixture those
    full-graph tests would litter ``backend/data/reports/`` in the working tree on
    every ``pytest tests/`` run. Redirecting the module-level ``REPORT_OUTPUT_DIR``
    (read by bare name in the node) to ``tmp_path`` keeps the working tree clean.

    ``test_report_graph.py`` also sets this explicitly; that per-test override still
    wins (both are function-scoped, its monkeypatch is applied later), so there is
    no conflict.
    """
    monkeypatch.setattr(
        report_agent_mod, "REPORT_OUTPUT_DIR", str(tmp_path / "reports")
    )


# ── Feature-011 runner/API helpers ───────────────────────────────────────────


def _stub_delivery(state, *, recipient=None):
    """Default delivery stub: both channels succeed."""
    return {
        "mcp_delivery_status": {
            "drive": {"status": "SUCCESS", "error_message": None, "delivered_at": "t"},
            "gmail": {"status": "SUCCESS", "error_message": None, "delivered_at": "t"},
        }
    }


def _wait_for(client, job_id: str, target_state: str, timeout: float = 5.0) -> dict:
    """Poll GET /api/jobs/{job_id} until status == target_state; return the JSON."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/jobs/{job_id}")
        if r.status_code == 200 and r.json().get("status") == target_state:
            return r.json()
        time.sleep(0.05)
    raise TimeoutError(
        f"Job {job_id!r} did not reach {target_state!r} within {timeout}s"
    )


@pytest.fixture
def client(monkeypatch, tmp_path):
    """TestClient for the runner/API layer with fast scripted fakes.

    Patches:
      - app.runner.core.build_graph  → fast 7-node scripted graph
      - app.runner.core.deliver_report_sync → stub that succeeds
      - app.config.UPLOAD_DIR → tmp_path/uploads

    The fake graph writes both {stem}.md and {stem}.json to tmp_path/reports
    on the terminal state, so report-download tests work (review T3).

    Tests that need different behaviour (ingest_error, exception, slow) may
    further monkeypatch within the test function.

    NOTE (review T1): tests that hold a job running via a threading.Event MUST
    event.set() to release the job before the 'with TestClient(...)' block exits,
    otherwise worker.stop() blocks for the full join_timeout.
    """
    import app.config as _config
    from app.api.main import create_app
    from starlette.testclient import TestClient

    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    def _fake_build_graph(checkpointer=None):
        stem = "test_contract"
        md_path = report_dir / f"{stem}.md"
        json_path = report_dir / f"{stem}.json"
        md_path.write_text("# Risk Report\n\n## Summary\n")
        json_path.write_text('{"risk_score": "HIGH", "findings": []}')

        class _FakeGraph:
            def stream(self, initial, stream_mode=None, config=None):
                doc_path = (initial or {}).get("document_path", "c.pdf")
                for node in [
                    "ingest_agent",
                    "clause_splitter",
                    "crag_retrieval",
                    "self_rag_validation",
                    "risk_score",
                    "redline",
                ]:
                    # node_timings mirrors what real nodes write ({current_node: elapsed})
                    # so the runner can surface elapsed_seconds (spec §2.4).
                    yield {
                        "current_node": node,
                        "document_path": doc_path,
                        "node_timings": {node: 0.01},
                    }
                yield {
                    "current_node": "report",
                    "document_path": doc_path,
                    "node_timings": {"report": 0.01},
                    "report_path": str(md_path),
                    "document_id": stem,
                }

        return _FakeGraph()

    monkeypatch.setattr("app.runner.core.build_graph", _fake_build_graph)
    monkeypatch.setattr("app.runner.core.deliver_report_sync", _stub_delivery)
    monkeypatch.setattr(_config, "UPLOAD_DIR", str(tmp_path / "uploads"))
    # Redirect DB paths to tmp so the test does not touch backend/data/
    monkeypatch.setattr(_config, "JOB_STORE_DB_PATH", str(tmp_path / "job_store.db"))
    monkeypatch.setattr(_config, "CHECKPOINTER_DB_PATH", str(tmp_path / "checkpoints.db"))
    # Disable startup recovery so tests control exactly which jobs run
    monkeypatch.setattr(_config, "STARTUP_RECOVERY_ENABLED", False)
    # Auth (feature 014) — fixed secret so tokens survive across multiple clients
    monkeypatch.setenv("AUTH_SECRET", "integration_test_secret_" + "x" * 16)
    monkeypatch.setattr(_config, "AUTH_SECRET_FILE", str(tmp_path / "auth_secret"))
    monkeypatch.setattr(_config, "AUTH_SIGNUP_OPEN", True)

    # NOTE (review T2): do NOT re-patch report_agent.REPORT_OUTPUT_DIR here —
    # the autouse _isolate_report_output already redirects it. Since build_graph is
    # FAKED, the real report_agent never runs, so REPORT_OUTPUT_DIR is moot for
    # these tests. What matters is that _fake_build_graph writes its own files under
    # tmp_path and sets report_path to the .md path.

    with TestClient(create_app()) as c:
        authenticate(c)
        yield c
