"""
Unit tests for the deliver_report orchestrator (TDD red phase).

Drive/Gmail client wrappers are patched with async stubs returning canned
DeliveryResults. Config names are monkeypatched on the module. No network,
no real Google account.

Run: python -m pytest tests/unit/test_delivery_step.py -v
Expected before Task 13: FAIL (ImportError)
Expected after Task 13:  PASS
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.graph.state import MCPDeliveryStatus
from app.models.report import ContractReport, ReportSummary

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_summary(high=1, medium=2, low=1) -> ReportSummary:
    return ReportSummary(
        total_clauses=10,
        validated_findings=high + medium + low,
        clean_clauses=6,
        high=high,
        medium=medium,
        low=low,
    )


def _make_report_json(tmp_path: Path, document_id: str = "doc123") -> tuple[Path, Path]:
    """Write a real ContractReport JSON + stub MD file; return (md_path, json_path)."""
    report = ContractReport(
        document_id=document_id,
        original_filename="contract.pdf",
        uploaded_at="2026-07-07T00:00:00+00:00",
        generated_at="2026-07-07T01:00:00+00:00",
        summary=_make_summary(),
        findings=[],
    )
    md_path = tmp_path / f"{document_id}.md"
    json_path = tmp_path / f"{document_id}.json"
    md_path.write_text("# Contract Report\n\n", encoding="utf-8")
    json_path.write_text(report.model_dump_json(), encoding="utf-8")
    return md_path, json_path


def _make_state(tmp_path: Path, document_id: str = "doc123") -> dict:
    md_path, _ = _make_report_json(tmp_path, document_id)
    return {
        "document_id": document_id,
        "original_filename": "contract.pdf",
        "report_path": str(md_path),
    }


def _ok_drive(ref="https://drive.google.com/file/123"):
    from app.delivery.models import DeliveryResult

    return DeliveryResult(service="drive", ok=True, resource_ref=ref)


def _ok_gmail(ref="msg_001"):
    from app.delivery.models import DeliveryResult

    return DeliveryResult(service="gmail", ok=True, resource_ref=ref)


def _fail_drive(msg="drive error"):
    from app.delivery.models import DeliveryResult

    return DeliveryResult(service="drive", ok=False, error_message=msg)


def _fail_gmail(msg="gmail error"):
    from app.delivery.models import DeliveryResult

    return DeliveryResult(service="gmail", ok=False, error_message=msg)


def _patch_clients(drive_result=None, gmail_result=None):
    """Context manager patching both client wrappers on the delivery_step module."""
    import contextlib

    drive_result = drive_result or _ok_drive()
    gmail_result = gmail_result or _ok_gmail()

    return contextlib.ExitStack()  # placeholder — tests use explicit patches


# ── tests ─────────────────────────────────────────────────────────────────────


async def test_happy_path_both_channels(tmp_path):
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)

    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_ok_drive()),
        ),
        patch(
            "app.delivery.delivery_step.send_report_via_gmail",
            new=AsyncMock(return_value=_ok_gmail()),
        ),
    ):
        result = await deliver_report(state, recipient="a@b.com")

    status = result["mcp_delivery_status"]
    assert status["drive"]["status"] == MCPDeliveryStatus.SUCCESS
    assert status["gmail"]["status"] == MCPDeliveryStatus.SUCCESS
    assert status["drive"]["delivered_at"] is not None
    assert status["gmail"]["delivered_at"] is not None


async def test_status_keys_and_info_shape(tmp_path):
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)

    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_ok_drive()),
        ),
        patch(
            "app.delivery.delivery_step.send_report_via_gmail",
            new=AsyncMock(return_value=_ok_gmail()),
        ),
    ):
        result = await deliver_report(state)

    status = result["mcp_delivery_status"]
    assert set(status.keys()) <= {"drive", "gmail"}
    for entry in status.values():
        assert set(entry.keys()) == {"status", "error_message", "delivered_at"}


async def test_never_writes_pending(tmp_path):
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)

    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_ok_drive()),
        ),
        patch(
            "app.delivery.delivery_step.send_report_via_gmail",
            new=AsyncMock(return_value=_ok_gmail()),
        ),
    ):
        result = await deliver_report(state)

    for entry in result["mcp_delivery_status"].values():
        assert entry["status"] != MCPDeliveryStatus.PENDING


async def test_partial_update_only(tmp_path):
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)

    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_ok_drive()),
        ),
        patch(
            "app.delivery.delivery_step.send_report_via_gmail",
            new=AsyncMock(return_value=_ok_gmail()),
        ),
    ):
        result = await deliver_report(state)

    assert set(result.keys()) == {"mcp_delivery_status"}
    banned = {"current_node", "node_timings", "error_count", "processing_completed_at"}
    assert not banned.intersection(result.keys())


async def test_drive_disabled_no_entry(tmp_path):
    import app.delivery.delivery_step as ds
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)
    drive_stub = AsyncMock(return_value=_ok_drive())
    gmail_stub = AsyncMock(return_value=_ok_gmail())

    with (
        patch.object(ds, "MCP_DRIVE_ENABLED", False),
        patch("app.delivery.delivery_step.upload_report_to_drive", new=drive_stub),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        result = await deliver_report(state)

    status = result["mcp_delivery_status"]
    assert "drive" not in status
    assert "gmail" in status
    drive_stub.assert_not_called()


async def test_gmail_disabled_no_entry(tmp_path):
    import app.delivery.delivery_step as ds
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)
    drive_stub = AsyncMock(return_value=_ok_drive())
    gmail_stub = AsyncMock(return_value=_ok_gmail())

    with (
        patch.object(ds, "MCP_GMAIL_ENABLED", False),
        patch("app.delivery.delivery_step.upload_report_to_drive", new=drive_stub),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        result = await deliver_report(state)

    status = result["mcp_delivery_status"]
    assert "gmail" not in status
    assert "drive" in status
    gmail_stub.assert_not_called()


async def test_both_disabled_noop(tmp_path):
    import app.delivery.delivery_step as ds
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)

    with (
        patch.object(ds, "MCP_DELIVERY_ENABLED", False),
        patch(
            "app.delivery.delivery_step.upload_report_to_drive", new=AsyncMock()
        ) as drive_stub,
        patch(
            "app.delivery.delivery_step.send_report_via_gmail", new=AsyncMock()
        ) as gmail_stub,
    ):
        result = await deliver_report(state)

    assert result == {"mcp_delivery_status": {}}
    drive_stub.assert_not_called()
    gmail_stub.assert_not_called()


async def test_drive_failure_does_not_block_gmail(tmp_path):
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)

    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_fail_drive()),
        ),
        patch(
            "app.delivery.delivery_step.send_report_via_gmail",
            new=AsyncMock(return_value=_ok_gmail()),
        ),
    ):
        result = await deliver_report(state, recipient="a@b.com")

    status = result["mcp_delivery_status"]
    assert status["drive"]["status"] == MCPDeliveryStatus.FAILED
    assert status["gmail"]["status"] == MCPDeliveryStatus.SUCCESS


async def test_gmail_failure_keeps_drive_success(tmp_path):
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)

    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_ok_drive()),
        ),
        patch(
            "app.delivery.delivery_step.send_report_via_gmail",
            new=AsyncMock(return_value=_fail_gmail()),
        ),
    ):
        result = await deliver_report(state)

    status = result["mcp_delivery_status"]
    assert status["drive"]["status"] == MCPDeliveryStatus.SUCCESS
    assert status["gmail"]["status"] == MCPDeliveryStatus.FAILED


async def test_total_failure_non_fatal(tmp_path):
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)

    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_fail_drive()),
        ),
        patch(
            "app.delivery.delivery_step.send_report_via_gmail",
            new=AsyncMock(return_value=_fail_gmail()),
        ),
    ):
        result = await deliver_report(state)  # must not raise

    status = result["mcp_delivery_status"]
    assert status["drive"]["status"] == MCPDeliveryStatus.FAILED
    assert status["gmail"]["status"] == MCPDeliveryStatus.FAILED


async def test_no_report_path_fails_enabled_channels(tmp_path):
    from app.delivery.delivery_step import deliver_report

    state = {"document_id": "doc1", "original_filename": "c.pdf", "report_path": None}
    drive_stub = AsyncMock(return_value=_ok_drive())
    gmail_stub = AsyncMock(return_value=_ok_gmail())

    with (
        patch("app.delivery.delivery_step.upload_report_to_drive", new=drive_stub),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        result = await deliver_report(state)

    status = result["mcp_delivery_status"]
    assert "drive" in status
    assert status["drive"]["status"] == MCPDeliveryStatus.FAILED
    drive_stub.assert_not_called()
    gmail_stub.assert_not_called()


async def test_missing_file_fails(tmp_path):
    from app.delivery.delivery_step import deliver_report

    state = {
        "document_id": "doc1",
        "original_filename": "c.pdf",
        "report_path": str(tmp_path / "nonexistent.md"),
    }
    drive_stub = AsyncMock(return_value=_ok_drive())

    with patch("app.delivery.delivery_step.upload_report_to_drive", new=drive_stub):
        result = await deliver_report(state)

    status = result["mcp_delivery_status"]
    assert status["drive"]["status"] == MCPDeliveryStatus.FAILED
    drive_stub.assert_not_called()


async def test_missing_recipient_fails_gmail_drive_ok(tmp_path):
    import app.delivery.delivery_step as ds
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)

    with (
        patch.object(ds, "MCP_DELIVERY_RECIPIENT", ""),
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_ok_drive()),
        ),
        patch(
            "app.delivery.delivery_step.send_report_via_gmail",
            new=AsyncMock(return_value=_ok_gmail()),
        ) as gmail_stub,
    ):
        result = await deliver_report(state)

    status = result["mcp_delivery_status"]
    assert status["drive"]["status"] == MCPDeliveryStatus.SUCCESS
    assert status["gmail"]["status"] == MCPDeliveryStatus.FAILED
    assert "recipient" in status["gmail"]["error_message"].lower()
    gmail_stub.assert_not_called()


async def test_recipient_override_used(tmp_path):
    from app.delivery.delivery_step import deliver_report
    import app.delivery.delivery_step as ds

    state = _make_state(tmp_path)
    gmail_stub = AsyncMock(return_value=_ok_gmail())

    with (
        patch.object(ds, "MCP_DELIVERY_RECIPIENT", ""),
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_ok_drive()),
        ),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        result = await deliver_report(state, recipient="override@example.com")

    status = result["mcp_delivery_status"]
    assert status["gmail"]["status"] == MCPDeliveryStatus.SUCCESS
    called_to = gmail_stub.call_args[0][0]
    assert called_to == "override@example.com"


async def test_email_counts_from_json_sibling(tmp_path):
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)  # summary has high=1, medium=2, low=1
    gmail_stub = AsyncMock(return_value=_ok_gmail())

    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_ok_drive()),
        ),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        await deliver_report(state, recipient="a@b.com")

    subject = gmail_stub.call_args[0][1]
    assert "1 high" in subject.lower() or "1" in subject


async def test_missing_json_sibling_generic_email(tmp_path):
    from app.delivery.delivery_step import deliver_report

    # Only write the MD file, no JSON sibling
    md_path = tmp_path / "doc_nojson.md"
    md_path.write_text("# Report", encoding="utf-8")
    state = {
        "document_id": "doc_nojson",
        "original_filename": "c.pdf",
        "report_path": str(md_path),
    }
    gmail_stub = AsyncMock(return_value=_ok_gmail())

    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_ok_drive()),
        ),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        result = await deliver_report(state, recipient="a@b.com")

    # Gmail should still succeed with a generic subject
    assert result["mcp_delivery_status"]["gmail"]["status"] == MCPDeliveryStatus.SUCCESS


async def test_gmail_body_links_drive_only_when_ok(tmp_path):
    from app.delivery.delivery_step import deliver_report
    from app.delivery.models import DeliveryResult

    state = _make_state(tmp_path)

    # Case 1: Drive ok with resource_ref → gmail body contains the link
    drive_with_ref = DeliveryResult(
        service="drive", ok=True, resource_ref="https://drive.google.com/file/ABC"
    )
    gmail_stub = AsyncMock(return_value=_ok_gmail())

    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=drive_with_ref),
        ),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        await deliver_report(state, recipient="a@b.com")

    body = gmail_stub.call_args[0][2]
    assert "https://drive.google.com/file/ABC" in body

    # Case 2: Drive failed → no link in body
    gmail_stub.reset_mock()
    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_fail_drive()),
        ),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        await deliver_report(state, recipient="a@b.com")

    body2 = gmail_stub.call_args[0][2]
    assert "https://drive.google.com/file/ABC" not in body2

    # Case 3: Drive ok but resource_ref is None → no link, drive still SUCCESS
    drive_no_ref = DeliveryResult(service="drive", ok=True, resource_ref=None)
    gmail_stub.reset_mock()
    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=drive_no_ref),
        ),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        result3 = await deliver_report(state, recipient="a@b.com")

    body3 = gmail_stub.call_args[0][2]
    assert "drive.google.com" not in body3
    assert (
        result3["mcp_delivery_status"]["drive"]["status"] == MCPDeliveryStatus.SUCCESS
    )


async def test_drive_uploads_configured_formats(tmp_path):
    import app.delivery.delivery_step as ds
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)
    drive_stub = AsyncMock(return_value=_ok_drive())
    gmail_stub = AsyncMock(return_value=_ok_gmail())

    # Default: uploads both md and json
    with (
        patch("app.delivery.delivery_step.upload_report_to_drive", new=drive_stub),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        await deliver_report(state, recipient="a@b.com")

    uploaded_names = [c[0][1] for c in drive_stub.call_args_list]
    assert any(n.endswith(".md") for n in uploaded_names)
    assert any(n.endswith(".json") for n in uploaded_names)

    # md-only config
    drive_stub.reset_mock()
    with (
        patch.object(ds, "MCP_DRIVE_UPLOAD_FORMATS", ("md",)),
        patch("app.delivery.delivery_step.upload_report_to_drive", new=drive_stub),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        await deliver_report(state, recipient="a@b.com")

    uploaded_names2 = [c[0][1] for c in drive_stub.call_args_list]
    assert all(n.endswith(".md") for n in uploaded_names2)
    assert not any(n.endswith(".json") for n in uploaded_names2)


async def test_drive_filename_matches_report_basename(tmp_path):
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)
    drive_stub = AsyncMock(return_value=_ok_drive())

    with (
        patch("app.delivery.delivery_step.upload_report_to_drive", new=drive_stub),
        patch(
            "app.delivery.delivery_step.send_report_via_gmail",
            new=AsyncMock(return_value=_ok_gmail()),
        ),
    ):
        await deliver_report(state, recipient="a@b.com")

    md_path = Path(state["report_path"])
    uploaded_names = [c[0][1] for c in drive_stub.call_args_list]
    assert md_path.name in uploaded_names
    assert md_path.with_suffix(".json").name in uploaded_names


async def test_config_values_read_not_hardcoded(tmp_path):
    import app.delivery.delivery_step as ds
    from app.delivery.delivery_step import deliver_report

    state = _make_state(tmp_path)
    drive_stub = AsyncMock(return_value=_ok_drive())
    gmail_stub = AsyncMock(return_value=_ok_gmail())

    with (
        patch.object(ds, "MCP_DELIVERY_RECIPIENT", "config@example.com"),
        patch.object(ds, "MCP_DRIVE_FOLDER_ID", "folder_xyz"),
        patch.object(ds, "MCP_DELIVERY_TIMEOUT_SECONDS", 99),
        patch.object(ds, "MCP_DELIVERY_MAX_RETRIES", 7),
        patch("app.delivery.delivery_step.upload_report_to_drive", new=drive_stub),
        patch("app.delivery.delivery_step.send_report_via_gmail", new=gmail_stub),
    ):
        await deliver_report(state)

    drive_call = drive_stub.call_args
    assert drive_call.kwargs["timeout_seconds"] == 99
    assert drive_call.kwargs["max_retries"] == 7

    gmail_call = gmail_stub.call_args
    assert gmail_call.args[0] == "config@example.com"
    assert gmail_call.kwargs["timeout_seconds"] == 99
    assert gmail_call.kwargs["max_retries"] == 7


async def test_sync_wrapper_runs(tmp_path):
    from app.delivery.delivery_step import deliver_report_sync

    state = _make_state(tmp_path)

    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_ok_drive()),
        ),
        patch(
            "app.delivery.delivery_step.send_report_via_gmail",
            new=AsyncMock(return_value=_ok_gmail()),
        ),
    ):
        result = deliver_report_sync(state, recipient="a@b.com")

    assert "mcp_delivery_status" in result
    assert result["mcp_delivery_status"]["drive"]["status"] == MCPDeliveryStatus.SUCCESS


async def test_redelivery_idempotent_state_shape(tmp_path):
    from app.delivery.delivery_step import deliver_report
    from app.graph.state import merge_dicts

    state = _make_state(tmp_path)

    with (
        patch(
            "app.delivery.delivery_step.upload_report_to_drive",
            new=AsyncMock(return_value=_ok_drive()),
        ),
        patch(
            "app.delivery.delivery_step.send_report_via_gmail",
            new=AsyncMock(return_value=_ok_gmail()),
        ),
    ):
        first = await deliver_report(state, recipient="a@b.com")
        second = await deliver_report(state, recipient="a@b.com")

    # Both returns must have exactly {drive, gmail}
    assert set(first["mcp_delivery_status"].keys()) == {"drive", "gmail"}
    assert set(second["mcp_delivery_status"].keys()) == {"drive", "gmail"}

    # Feeding through merge_dicts reducer replaces entries (second wins), no duplicates
    merged = merge_dicts(first["mcp_delivery_status"], second["mcp_delivery_status"])
    assert set(merged.keys()) == {"drive", "gmail"}
