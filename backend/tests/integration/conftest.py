"""
Integration-suite fixtures for ContractSentinel backend tests.

Scoped to tests/integration/ (pytest discovers conftest.py hierarchically),
so these fixtures apply only to the integration tests, on top of the shared
fixtures in tests/conftest.py.
"""

import pytest

import app.graph.nodes.report_agent as report_agent_mod


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
