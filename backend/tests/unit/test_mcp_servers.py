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


# ─── Round-trip tests: full client → MCP Server → handler plumbing ───────────
# These tests verify that the _run_server() registration (list_tools / call_tool
# handlers, TextContent serialization) is correct end-to-end using the MCP SDK's
# in-process memory transport — no subprocess, no real Google credentials.


async def test_drive_server_round_trip(tmp_path):
    """Drive: client calls upload_file via in-process MCP streams; ToolOutcome parses back."""
    import anyio
    from mcp import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams

    from app.delivery.models import ToolOutcome

    report = tmp_path / "report.md"
    report.write_text("# Report")

    svc = _make_drive_service(
        list_files=[],
        create_result={"id": "rt_id", "webViewLink": "https://drive.google.com/rt"},
    )

    # Drive the real registration code from _run_server (via _build_server)
    from app.delivery.mcp_servers.drive_server import _build_server

    server = _build_server()

    received: list[ToolOutcome] = []

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
        async with create_client_server_memory_streams() as (
            client_streams,
            server_streams,
        ):
            client_read, client_write = client_streams
            server_read, server_write = server_streams

            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    server.run,
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )

                async with ClientSession(client_read, client_write) as session:
                    await session.initialize()
                    raw = await session.call_tool(
                        "upload_file",
                        {
                            "file_path": str(report),
                            "file_name": "report.md",
                            "mime_type": "text/markdown",
                        },
                    )
                    text = raw.content[0].text
                    received.append(ToolOutcome.model_validate_json(text))

                tg.cancel_scope.cancel()

    assert len(received) == 1
    outcome = received[0]
    assert outcome.ok is True
    assert outcome.resource_ref == "https://drive.google.com/rt"


async def test_gmail_server_round_trip():
    """Gmail: client calls send_message via in-process MCP streams; ToolOutcome parses back."""
    import anyio
    from mcp import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams

    from app.delivery.models import ToolOutcome

    sent_response = {"id": "rt_gmail_001"}
    svc = MagicMock()
    svc.users.return_value.messages.return_value.send.return_value.execute.return_value = (
        sent_response
    )

    from app.delivery.mcp_servers.gmail_server import _build_server

    server = _build_server()

    received: list[ToolOutcome] = []

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
        async with create_client_server_memory_streams() as (
            client_streams,
            server_streams,
        ):
            client_read, client_write = client_streams
            server_read, server_write = server_streams

            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    server.run,
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                )

                async with ClientSession(client_read, client_write) as session:
                    await session.initialize()
                    raw = await session.call_tool(
                        "send_message",
                        {"to": "a@b.com", "subject": "Test", "body": "Body"},
                    )
                    text = raw.content[0].text
                    received.append(ToolOutcome.model_validate_json(text))

                tg.cancel_scope.cancel()

    assert len(received) == 1
    outcome = received[0]
    assert outcome.ok is True
    assert outcome.resource_ref == "rt_gmail_001"


# ─── Feature 030: HTML alternative body + PDF attachment ──────────────────────
def _parse_mime(raw_b64: str):
    import base64
    import email as _email

    return _email.message_from_bytes(base64.urlsafe_b64decode(raw_b64))


def test_gmail_build_mime_html_alternative_and_pdf():
    """AC-8/AC-11/AC-12: html_body + PDF → multipart/mixed[alternative(plain,html) + application/pdf]."""
    import tempfile
    from pathlib import Path
    from app.delivery.mcp_servers.gmail_server import _build_mime
    from app.delivery.models import GmailSendRequest

    tmp = Path(tempfile.mkdtemp()) / "report.pdf"
    tmp.write_bytes(b"%PDF-1.4 fake")

    req = GmailSendRequest(
        to="user@example.com",
        subject="ContractSentinel report",
        body="Plain summary.",
        html_body="<html><body><b>Summary</b></body></html>",
        attachment_path=str(tmp),
        attachment_name="report.pdf",
    )
    msg = _parse_mime(_build_mime(req))

    assert msg.get_content_type() == "multipart/mixed"
    subtypes = [p.get_content_type() for p in msg.walk()]
    assert "multipart/alternative" in subtypes
    assert "text/plain" in subtypes
    assert "text/html" in subtypes
    assert "application/pdf" in subtypes
    # the PDF part is an attachment with a .pdf filename
    pdf_parts = [p for p in msg.walk() if p.get_content_type() == "application/pdf"]
    assert pdf_parts and pdf_parts[0].get_filename() == "report.pdf"
    assert "attachment" in pdf_parts[0].get("Content-Disposition", "")


def test_gmail_build_mime_plain_only_when_no_html():
    """Parity: html_body None → plain body present, no text/html part (pre-030 shape)."""
    from app.delivery.mcp_servers.gmail_server import _build_mime
    from app.delivery.models import GmailSendRequest

    req = GmailSendRequest(to="u@e.com", subject="s", body="plain only")
    msg = _parse_mime(_build_mime(req))
    subtypes = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in subtypes
    assert "text/html" not in subtypes


def test_gmail_build_mime_md_fallback_attachment_type():
    """AC-13/AC-15: a .md fallback attachment keeps a sensible (non-pdf) content type."""
    import tempfile
    from pathlib import Path
    from app.delivery.mcp_servers.gmail_server import _build_mime
    from app.delivery.models import GmailSendRequest

    tmp = Path(tempfile.mkdtemp()) / "report.md"
    tmp.write_text("# Report")
    req = GmailSendRequest(
        to="u@e.com", subject="s", body="p",
        attachment_path=str(tmp), attachment_name="report.md",
    )
    msg = _parse_mime(_build_mime(req))
    md_parts = [p for p in msg.walk() if (p.get_filename() or "").endswith(".md")]
    assert md_parts
    assert md_parts[0].get_content_type() != "application/pdf"


# ─── Feature 031: Drive per-user token_path ──────────────────────────────────
def test_drive_upload_tool_schema_has_token_path():
    """The upload_file tool inputSchema must declare token_path so it survives MCP arg
    validation across the stdio boundary (feature 031)."""
    import inspect
    from app.delivery.mcp_servers import drive_server as ds

    assert '"token_path"' in inspect.getsource(ds._build_server)


async def test_drive_handle_upload_uses_per_user_token_path(tmp_path):
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest

    f = tmp_path / "r.pdf"; f.write_bytes(b"%PDF-1.4 x")
    seen = {}

    def fake_load(creds_path, token_path):
        seen["token_path"] = token_path
        return MagicMock()

    svc = MagicMock()
    svc.files.return_value.list.return_value.execute.return_value = {"files": []}
    svc.files.return_value.create.return_value.execute.return_value = {"id": "1", "webViewLink": "L"}

    with (
        patch("app.delivery.mcp_servers.drive_server.load_credentials", side_effect=fake_load),
        patch("app.delivery.mcp_servers.drive_server.build_drive_service", return_value=svc),
        patch("app.delivery.mcp_servers.drive_server.MediaFileUpload", MagicMock()),
    ):
        req = DriveUploadRequest(
            file_path=str(f), file_name="r.pdf", mime_type="application/pdf",
            token_path="data/secrets/user_ABC.json",
        )
        out = await _handle_upload(req)
    assert out.ok is True
    assert seen["token_path"] == "data/secrets/user_ABC.json"  # per-user, not central


async def test_drive_handle_upload_defaults_to_central_token(tmp_path):
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest
    from app import config as _config

    f = tmp_path / "r.pdf"; f.write_bytes(b"%PDF-1.4 x")
    seen = {}

    def fake_load(creds_path, token_path):
        seen["token_path"] = token_path
        return MagicMock()

    svc = MagicMock()
    svc.files.return_value.list.return_value.execute.return_value = {"files": []}
    svc.files.return_value.create.return_value.execute.return_value = {"id": "1", "webViewLink": "L"}

    with (
        patch("app.delivery.mcp_servers.drive_server.load_credentials", side_effect=fake_load),
        patch("app.delivery.mcp_servers.drive_server.build_drive_service", return_value=svc),
        patch("app.delivery.mcp_servers.drive_server.MediaFileUpload", MagicMock()),
    ):
        req = DriveUploadRequest(file_path=str(f), file_name="r.pdf", mime_type="application/pdf")
        await _handle_upload(req)
    assert seen["token_path"] == _config.GOOGLE_OAUTH_TOKEN_PATH  # central default


# ─── Feature 033 — Drive folder + human-readable naming ───────────────────────

_FOLDER_MIME = "application/vnd.google-apps.folder"


def _make_folder_drive_service(
    *,
    folder_list=None,
    name_match_list=None,
    folder_create_result=None,
    file_create_result=None,
    update_result=None,
    folder_list_error=None,
    folder_create_error=None,
):
    """A Drive fake that routes list results by the `q` string (folder-query vs
    name-match) and routes create by `body['mimeType']` (folder-create vs
    file-create). Supports injecting HttpError on the folder list/create."""
    from unittest.mock import MagicMock

    svc = MagicMock()
    files = svc.files.return_value

    def list_side_effect(q=None, fields=None, orderBy=None, **kw):
        is_folder_q = f"mimeType='{_FOLDER_MIME}'" in (q or "")

        def execute():
            if is_folder_q:
                if folder_list_error is not None:
                    raise folder_list_error
                return {"files": folder_list or []}
            return {"files": name_match_list or []}

        req = MagicMock()
        req.execute = execute
        return req

    files.list.side_effect = list_side_effect

    def create_side_effect(body=None, media_body=None, fields=None, **kw):
        is_folder = (body or {}).get("mimeType") == _FOLDER_MIME

        def execute():
            if is_folder:
                if folder_create_error is not None:
                    raise folder_create_error
                return folder_create_result or {"id": "NEWFOLDER"}
            return file_create_result or {
                "id": "file123",
                "webViewLink": "https://drive.google.com/file/123",
            }

        req = MagicMock()
        req.execute = execute
        return req

    files.create.side_effect = create_side_effect
    if update_result is not None:
        files.update.return_value.execute = MagicMock(return_value=update_result)
    return svc


def _list_qs(svc):
    """All `q` strings passed to files().list, in order."""
    return [c.kwargs.get("q", "") for c in svc.files.return_value.list.call_args_list]


def _create_bodies(svc):
    """All `body` dicts passed to files().create, in order."""
    return [
        c.kwargs.get("body", {}) for c in svc.files.return_value.create.call_args_list
    ]


def _patched(svc):
    return (
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
    )


async def test_folder_created_when_absent(tmp_path):  # AC-1
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest

    f = tmp_path / "r.pdf"
    f.write_text("x")
    svc = _make_folder_drive_service(folder_list=[], name_match_list=[])
    p1, p2, p3 = _patched(svc)
    with p1, p2, p3:
        req = DriveUploadRequest(
            file_path=str(f),
            file_name="r.pdf",
            mime_type="application/pdf",
            folder_name="ContractSentinel",
        )
        outcome = await _handle_upload(req)

    assert outcome.ok is True
    bodies = _create_bodies(svc)
    folder_bodies = [b for b in bodies if b.get("mimeType") == _FOLDER_MIME]
    file_bodies = [b for b in bodies if b.get("mimeType") != _FOLDER_MIME]
    assert len(folder_bodies) == 1 and folder_bodies[0]["name"] == "ContractSentinel"
    assert file_bodies and file_bodies[0]["parents"] == ["NEWFOLDER"]


async def test_folder_reused_when_present(tmp_path):  # AC-2
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest

    f = tmp_path / "r.pdf"
    f.write_text("x")
    svc = _make_folder_drive_service(folder_list=[{"id": "F1"}], name_match_list=[])
    p1, p2, p3 = _patched(svc)
    with p1, p2, p3:
        req = DriveUploadRequest(
            file_path=str(f),
            file_name="r.pdf",
            mime_type="application/pdf",
            folder_name="ContractSentinel",
        )
        outcome = await _handle_upload(req)

    assert outcome.ok is True
    assert not any(b.get("mimeType") == _FOLDER_MIME for b in _create_bodies(svc))
    file_bodies = [b for b in _create_bodies(svc) if b.get("mimeType") != _FOLDER_MIME]
    assert file_bodies[0]["parents"] == ["F1"]
    assert any("'F1' in parents" in q for q in _list_qs(svc))  # name-match scoped (AC-6a)


async def test_folder_duplicate_uses_first_and_orders_by_created_time(tmp_path):  # AC-3
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest

    f = tmp_path / "r.pdf"
    f.write_text("x")
    svc = _make_folder_drive_service(
        folder_list=[{"id": "OLD"}, {"id": "NEW"}], name_match_list=[]
    )
    p1, p2, p3 = _patched(svc)
    with p1, p2, p3:
        req = DriveUploadRequest(
            file_path=str(f),
            file_name="r.pdf",
            mime_type="application/pdf",
            folder_name="ContractSentinel",
        )
        await _handle_upload(req)

    assert not any(b.get("mimeType") == _FOLDER_MIME for b in _create_bodies(svc))
    file_bodies = [b for b in _create_bodies(svc) if b.get("mimeType") != _FOLDER_MIME]
    assert file_bodies[0]["parents"] == ["OLD"]
    folder_calls = [
        c
        for c in svc.files.return_value.list.call_args_list
        if f"mimeType='{_FOLDER_MIME}'" in c.kwargs.get("q", "")
    ]
    assert folder_calls and folder_calls[0].kwargs.get("orderBy") == "createdTime"


async def test_explicit_folder_id_skips_resolution(tmp_path):  # AC-4
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest

    f = tmp_path / "r.pdf"
    f.write_text("x")
    svc = _make_folder_drive_service(name_match_list=[])
    p1, p2, p3 = _patched(svc)
    with p1, p2, p3:
        req = DriveUploadRequest(
            file_path=str(f),
            file_name="r.pdf",
            mime_type="application/pdf",
            folder_id="EXPLICIT",
            folder_name="ContractSentinel",
        )
        await _handle_upload(req)

    qs = _list_qs(svc)
    assert not any(f"mimeType='{_FOLDER_MIME}'" in q for q in qs)  # no folder-resolution query
    assert any("'EXPLICIT' in parents" in q for q in qs)  # name-match ran, scoped
    file_bodies = [b for b in _create_bodies(svc) if b.get("mimeType") != _FOLDER_MIME]
    assert file_bodies[0]["parents"] == ["EXPLICIT"]


async def test_no_folder_uploads_to_root(tmp_path):  # AC-5
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest

    f = tmp_path / "r.pdf"
    f.write_text("x")
    svc = _make_folder_drive_service(name_match_list=[])
    p1, p2, p3 = _patched(svc)
    with p1, p2, p3:
        req = DriveUploadRequest(
            file_path=str(f),
            file_name="r.pdf",
            mime_type="application/pdf",
            folder_id=None,
            folder_name=None,
        )
        await _handle_upload(req)

    qs = _list_qs(svc)
    assert all("in parents" not in q for q in qs)  # name-match unscoped
    file_bodies = [b for b in _create_bodies(svc) if b.get("mimeType") != _FOLDER_MIME]
    assert file_bodies[0]["parents"] == []


@pytest.mark.parametrize("token_path", ["/tmp/user_token.json", None])
async def test_folder_resolution_token_agnostic(tmp_path, token_path):  # AC-6
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest

    f = tmp_path / "r.pdf"
    f.write_text("x")
    svc = _make_folder_drive_service(folder_list=[], name_match_list=[])
    p1, p2, p3 = _patched(svc)
    with p1, p2, p3:
        req = DriveUploadRequest(
            file_path=str(f),
            file_name="r.pdf",
            mime_type="application/pdf",
            folder_name="ContractSentinel",
            token_path=token_path,
        )
        outcome = await _handle_upload(req)

    assert outcome.ok is True
    file_bodies = [b for b in _create_bodies(svc) if b.get("mimeType") != _FOLDER_MIME]
    assert file_bodies[0]["parents"] == ["NEWFOLDER"]


async def test_q_escapes_single_quotes(tmp_path):  # AC-12
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest

    f = tmp_path / "r.pdf"
    f.write_text("x")
    svc = _make_folder_drive_service(folder_list=[], name_match_list=[])
    p1, p2, p3 = _patched(svc)
    with p1, p2, p3:
        req = DriveUploadRequest(
            file_path=str(f),
            file_name="O'Brien (a3f1c9).pdf",
            mime_type="application/pdf",
            folder_name="Con'tract",
        )
        outcome = await _handle_upload(req)

    assert outcome.ok is True  # no HttpError from a malformed query
    qs = _list_qs(svc)
    assert any("Con\\'tract" in q for q in qs)  # folder name escaped
    assert any("O\\'Brien" in q for q in qs)  # file name escaped


async def test_folder_list_httperror_contained(tmp_path):  # AC-16 (i)
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest
    from googleapiclient.errors import HttpError

    f = tmp_path / "r.pdf"
    f.write_text("x")
    resp = MagicMock()
    resp.status = 500
    svc = _make_folder_drive_service(
        folder_list_error=HttpError(resp=resp, content=b"boom"), name_match_list=[]
    )
    p1, p2, p3 = _patched(svc)
    with p1, p2, p3:
        req = DriveUploadRequest(
            file_path=str(f),
            file_name="r.pdf",
            mime_type="application/pdf",
            folder_name="ContractSentinel",
        )
        outcome = await _handle_upload(req)

    assert outcome.ok is False  # contained, no raise


async def test_folder_create_httperror_contained(tmp_path):  # AC-16 (ii)
    from app.delivery.mcp_servers.drive_server import _handle_upload
    from app.delivery.models import DriveUploadRequest
    from googleapiclient.errors import HttpError

    f = tmp_path / "r.pdf"
    f.write_text("x")
    resp = MagicMock()
    resp.status = 500
    svc = _make_folder_drive_service(
        folder_list=[],
        folder_create_error=HttpError(resp=resp, content=b"boom"),
        name_match_list=[],
    )
    p1, p2, p3 = _patched(svc)
    with p1, p2, p3:
        req = DriveUploadRequest(
            file_path=str(f),
            file_name="r.pdf",
            mime_type="application/pdf",
            folder_name="ContractSentinel",
        )
        outcome = await _handle_upload(req)

    assert outcome.ok is False  # folder-create failure contained; file path never reached
