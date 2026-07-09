"""
Unit tests for app.runner.__main__ CLI entry point.

run_pipeline is patched so no Ollama/Google calls are made.
TDD red phase: all tests FAIL (ImportError) until Task 17 implements the module.
Run: python -m pytest tests/unit/test_cli.py -v
"""

from dataclasses import dataclass
from typing import Optional
from unittest.mock import patch


@dataclass
class FakeRunResult:
    final_state: dict
    report_path: Optional[str]
    mcp_delivery_status: dict
    ingest_error: Optional[dict]


def _happy_result():
    return FakeRunResult(
        final_state={"report_path": "data/reports/doc.md"},
        report_path="data/reports/doc.md",
        mcp_delivery_status={"drive": "SUCCESS"},
        ingest_error=None,
    )


def _ingest_error_result():
    return FakeRunResult(
        final_state={},
        report_path=None,
        mcp_delivery_status={},
        ingest_error={"message": "bad pdf"},
    )


def test_cli_uses_run_pipeline():
    """main(['c.pdf']) calls run_pipeline('c.pdf', recipient=None, on_progress=<callable>)."""
    import app.runner.__main__ as cli_mod

    calls = []

    def capture(doc_path, *, recipient=None, on_progress=None, **kwargs):
        calls.append(
            {"doc": doc_path, "recipient": recipient, "on_progress": on_progress}
        )
        return _happy_result()

    with patch.object(cli_mod, "run_pipeline", side_effect=capture):
        cli_mod.main(["c.pdf"])

    assert len(calls) == 1
    assert calls[0]["doc"] == "c.pdf"
    assert calls[0]["recipient"] is None
    assert callable(calls[0]["on_progress"])


def test_cli_passes_recipient():
    """main(['c.pdf', '--recipient', 'x@y.z']) passes recipient='x@y.z'."""
    import app.runner.__main__ as cli_mod

    calls = []

    def capture(doc_path, *, recipient=None, on_progress=None, **kwargs):
        calls.append(recipient)
        return _happy_result()

    with patch.object(cli_mod, "run_pipeline", side_effect=capture):
        cli_mod.main(["c.pdf", "--recipient", "x@y.z"])

    assert calls[0] == "x@y.z"


def test_cli_prints_report_path(capsys):
    """On success, stdout contains report_path; return code is 0."""
    import app.runner.__main__ as cli_mod

    with patch.object(cli_mod, "run_pipeline", return_value=_happy_result()):
        rc = cli_mod.main(["c.pdf"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "data/reports/doc.md" in out


def test_cli_ingest_error_exit_2(capsys):
    """RunResult.ingest_error set → return code 2, ingest error on stderr."""
    import app.runner.__main__ as cli_mod

    with patch.object(cli_mod, "run_pipeline", return_value=_ingest_error_result()):
        rc = cli_mod.main(["c.pdf"])

    assert rc == 2
    err = capsys.readouterr().err
    assert err  # some error output


def test_cli_exception_exit_1(capsys):
    """run_pipeline raising → stderr error, return code 1."""
    import app.runner.__main__ as cli_mod

    with patch.object(cli_mod, "run_pipeline", side_effect=RuntimeError("boom")):
        rc = cli_mod.main(["c.pdf"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "boom" in err
