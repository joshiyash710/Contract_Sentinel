"""
Unit tests for Drive + Gmail MCP server tool handlers (TDD red phase).

Tests exercise _handle_upload / _handle_send directly — no stdio server spin-up.
Google services are mocked; no network calls.

Run: python -m pytest tests/unit/test_mcp_servers.py -v
Expected before Task 9: FAIL (ImportError)
Expected after Task 9:  PASS
"""

import base64
import pytest
from unittest.mock import MagicMock, patch

# ─── Drive server tests ───────────────────────────────────────────────────────


@pytest.fixture
def mock_drive_service():
    svc = MagicMock()
    svc.files.return_value = svc.files_obj
    return svc


def _make_drive_service(list_files=None, create_result=None, update_result=None):
    """Build a mock Drive service with scripted list/create/update responses."""
    svc = MagicMock()
    files = svc.files.return_value
    list_execute = MagicMock(return_value={"files": list_files or []})
    files.list.return_value.execute = list_execute
    if create_result is not None:
        files.create.return_value.execute = MagicMock(return_value=create_result)
    if update_result is not None:
        files.update.return_value.execute = MagicMock(return_value=update_result)
    return svc


async def test_drive_upload_creates_when_absent(tmp_path):
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest

    report = tmp_path / "report.md"
    report.write_text("# Report")
    svc = _make_drive_service(
        list_files=[],
        create_result={
            "id": "file123",
            "webViewLink": "https://drive.google.com/file/123",
        },
    )

    with (
        patch(
            "app.delivery.mcp_servers.drive_server.load_credentials",
            return_value=MagicMock(),
        ),
        patch(
            "app.delivery.mcp_servers.drive_server.build_drive_service",
            return_value=svc,
        ),
        patch(
            "app.delivery.mcp_servers.drive_server.MediaFileUpload",
            return_value=MagicMock(),
        ),
    ):
        req = DriveUploadRequest(
            file_path=str(report), file_name="report.md", mime_type="text/markdown"
        )
        outcome = await _handle_upload(req)

    assert outcome.ok is True
    assert outcome.resource_ref == "https://drive.google.com/file/123"
    svc.files.return_value.create.assert_called_once()
    svc.files.return_value.update.assert_not_called()


async def test_drive_upload_updates_when_present(tmp_path):
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest

    report = tmp_path / "report.md"
    report.write_text("# Report")
    svc = _make_drive_service(
        list_files=[{"id": "existing_id"}],
        update_result={
            "id": "existing_id",
            "webViewLink": "https://drive.google.com/existing",
        },
    )

    with (
        patch(
            "app.delivery.mcp_servers.drive_server.load_credentials",
            return_value=MagicMock(),
        ),
        patch(
            "app.delivery.mcp_servers.drive_server.build_drive_service",
            return_value=svc,
        ),
        patch(
            "app.delivery.mcp_servers.drive_server.MediaFileUpload",
            return_value=MagicMock(),
        ),
    ):
        req = DriveUploadRequest(
            file_path=str(report), file_name="report.md", mime_type="text/markdown"
        )
        outcome = await _handle_upload(req)

    assert outcome.ok is True
    svc.files.return_value.update.assert_called_once()
    svc.files.return_value.create.assert_not_called()


async def test_drive_httperror_5xx_retryable(tmp_path):
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest
    from googleapiclient.errors import HttpError
    from unittest.mock import MagicMock

    report = tmp_path / "report.md"
    report.write_text("# Report")

    mock_resp = MagicMock()
    mock_resp.status = 503
    http_err = HttpError(resp=mock_resp, content=b"Service Unavailable")

    svc = MagicMock()
    svc.files.return_value.list.return_value.execute.side_effect = http_err

    with (
        patch(
            "app.delivery.mcp_servers.drive_server.load_credentials",
            return_value=MagicMock(),
        ),
        patch(
            "app.delivery.mcp_servers.drive_server.build_drive_service",
            return_value=svc,
        ),
        patch(
            "app.delivery.mcp_servers.drive_server.MediaFileUpload",
            return_value=MagicMock(),
        ),
    ):
        req = DriveUploadRequest(
            file_path=str(report), file_name="report.md", mime_type="text/markdown"
        )
        outcome = await _handle_upload(req)

    assert outcome.ok is False
    assert outcome.retryable is True


async def test_drive_httperror_403_not_retryable(tmp_path):
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest
    from googleapiclient.errors import HttpError

    report = tmp_path / "report.md"
    report.write_text("# Report")

    mock_resp = MagicMock()
    mock_resp.status = 403
    http_err = HttpError(resp=mock_resp, content=b"Forbidden")

    svc = MagicMock()
    svc.files.return_value.list.return_value.execute.side_effect = http_err

    with (
        patch(
            "app.delivery.mcp_servers.drive_server.load_credentials",
            return_value=MagicMock(),
        ),
        patch(
            "app.delivery.mcp_servers.drive_server.build_drive_service",
            return_value=svc,
        ),
        patch(
            "app.delivery.mcp_servers.drive_server.MediaFileUpload",
            return_value=MagicMock(),
        ),
    ):
        req = DriveUploadRequest(
            file_path=str(report), file_name="report.md", mime_type="text/markdown"
        )
        outcome = await _handle_upload(req)

    assert outcome.ok is False
    assert outcome.retryable is False


async def test_drive_creds_error_not_retryable(tmp_path):
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest
    from app.delivery.mcp_servers.google_auth import CredentialsError

    report = tmp_path / "report.md"
    report.write_text("# Report")

    with patch(
        "app.delivery.mcp_servers.drive_server.load_credentials",
        side_effect=CredentialsError("token not found"),
    ):
        req = DriveUploadRequest(
            file_path=str(report), file_name="report.md", mime_type="text/markdown"
        )
        outcome = await _handle_upload(req)

    assert outcome.ok is False
    assert outcome.retryable is False
    assert outcome.error_message.startswith("auth")


# ─── Gmail server tests ───────────────────────────────────────────────────────


async def test_gmail_send_builds_mime_and_sends(tmp_path):
    from app.delivery.mcp_servers.gmail_server import _handle_send
    from app.delivery.models import GmailSendRequest

    sent_response = {"id": "msg_abc123"}
    svc = MagicMock()
    svc.users.return_value.messages.return_value.send.return_value.execute.return_value = (
        sent_response
    )

    with (
        patch(
            "app.delivery.mcp_servers.gmail_server.load_credentials",
            return_value=MagicMock(),
        ),
        patch(
            "app.delivery.mcp_servers.gmail_server.build_gmail_service",
            return_value=svc,
        ),
    ):
        req = GmailSendRequest(
            to="user@example.com",
            subject="ContractSentinel report",
            body="Risk summary here.",
        )
        outcome = await _handle_send(req)

    assert outcome.ok is True
    assert outcome.resource_ref == "msg_abc123"
    svc.users.return_value.messages.return_value.send.assert_called_once()


async def test_gmail_attaches_when_path_given(tmp_path):
    from app.delivery.mcp_servers.gmail_server import _handle_send
    from app.delivery.models import GmailSendRequest

    attachment = tmp_path / "report.md"
    attachment.write_text("# Contract Report\n\nRisk: HIGH")

    captured_body = {}

    def mock_send(userId, body):
        captured_body.update(body)
        m = MagicMock()
        m.execute.return_value = {"id": "msg_xyz"}
        return m

    svc = MagicMock()
    svc.users.return_value.messages.return_value.send.side_effect = mock_send

    with (
        patch(
            "app.delivery.mcp_servers.gmail_server.load_credentials",
            return_value=MagicMock(),
        ),
        patch(
            "app.delivery.mcp_servers.gmail_server.build_gmail_service",
            return_value=svc,
        ),
    ):
        req = GmailSendRequest(
            to="user@example.com",
            subject="Report",
            body="Body",
            attachment_path=str(attachment),
            attachment_name="report.md",
        )
        outcome = await _handle_send(req)

    assert outcome.ok is True
    raw_decoded = base64.urlsafe_b64decode(captured_body["raw"] + "==").decode(
        "utf-8", errors="replace"
    )
    assert "report.md" in raw_decoded


async def test_gmail_oversized_not_retryable():
    from app.delivery.mcp_servers.gmail_server import _handle_send
    from app.delivery.models import GmailSendRequest
    from googleapiclient.errors import HttpError

    mock_resp = MagicMock()
    mock_resp.status = 413
    http_err = HttpError(resp=mock_resp, content=b"Request Entity Too Large")

    svc = MagicMock()
    svc.users.return_value.messages.return_value.send.return_value.execute.side_effect = (
        http_err
    )

    with (
        patch(
            "app.delivery.mcp_servers.gmail_server.load_credentials",
            return_value=MagicMock(),
        ),
        patch(
            "app.delivery.mcp_servers.gmail_server.build_gmail_service",
            return_value=svc,
        ),
    ):
        req = GmailSendRequest(to="a@b.com", subject="s", body="b")
        outcome = await _handle_send(req)

    assert outcome.ok is False
    assert outcome.retryable is False


async def test_server_never_raises_across_boundary(tmp_path):
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest

    report = tmp_path / "report.md"
    report.write_text("# Report")

    with patch(
        "app.delivery.mcp_servers.drive_server.load_credentials",
        side_effect=RuntimeError("unexpected internal error"),
    ):
        req = DriveUploadRequest(
            file_path=str(report), file_name="report.md", mime_type="text/markdown"
        )
        outcome = await _handle_upload(req)

    assert outcome.ok is False
    assert outcome.retryable is False
