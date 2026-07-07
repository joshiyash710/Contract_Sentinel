"""
Gmail MCP server — exposes a single `send_message` tool over stdio.

The tool body is factored into _handle_send() for direct unit-test coverage
without spinning up a stdio server loop.

Run as: python -m app.delivery.mcp_servers.gmail_server
"""

import asyncio
import base64
import logging
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from googleapiclient.errors import HttpError

import app.config as _config
from app.delivery.models import GmailSendRequest, ToolOutcome
from app.delivery.mcp_servers.google_auth import (
    CredentialsError,
    build_gmail_service,
    load_credentials,
)

logger = logging.getLogger("contractsentinel.delivery.gmail_server")

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_NON_RETRYABLE_STATUSES = frozenset({400, 401, 403, 413})


def _is_retryable(status: int) -> bool:
    return status in _RETRYABLE_STATUSES


def _build_mime(req: GmailSendRequest) -> str:
    msg = MIMEMultipart()
    msg["to"] = req.to
    msg["subject"] = req.subject
    msg.attach(MIMEText(req.body, "plain"))

    if req.attachment_path and Path(req.attachment_path).exists():
        with open(req.attachment_path, "rb") as f:
            data = f.read()
        name = req.attachment_name or Path(req.attachment_path).name
        part = MIMEApplication(data, Name=name)
        part["Content-Disposition"] = f'attachment; filename="{name}"'
        msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return raw


async def _handle_send(req: GmailSendRequest) -> ToolOutcome:
    """Gmail send handler — testable without the MCP stdio layer."""
    try:
        creds = await asyncio.to_thread(
            load_credentials,
            _config.GOOGLE_OAUTH_CREDENTIALS_PATH,
            _config.GOOGLE_OAUTH_TOKEN_PATH,
        )
        svc = await asyncio.to_thread(build_gmail_service, creds)

        raw = await asyncio.to_thread(_build_mime, req)

        result = await asyncio.to_thread(
            lambda: svc.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )

        return ToolOutcome(ok=True, resource_ref=result.get("id"))

    except CredentialsError as exc:
        return ToolOutcome(ok=False, retryable=False, error_message=f"auth: {exc}")
    except HttpError as exc:
        retryable = _is_retryable(exc.resp.status)
        return ToolOutcome(ok=False, retryable=retryable, error_message=str(exc))
    except Exception as exc:
        logger.exception("Unexpected Gmail send error: %s", exc)
        return ToolOutcome(ok=False, retryable=False, error_message=str(exc))


if __name__ == "__main__":
    import asyncio as _asyncio

    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server

        app = Server("gmail-server")

        @app.call_tool()
        async def send_message(name: str, arguments: dict) -> list:
            req = GmailSendRequest(**arguments)
            outcome = await _handle_send(req)
            return [{"type": "text", "text": outcome.model_dump_json()}]

        _asyncio.run(stdio_server(app))
    except ImportError:
        pass
