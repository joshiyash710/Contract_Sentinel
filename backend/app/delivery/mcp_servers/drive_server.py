"""
Google Drive MCP server — exposes a single `upload_file` tool over stdio.

The tool body is factored into _handle_upload() for direct unit-test coverage
without spinning up a stdio server loop.

Run as: python -m app.delivery.mcp_servers.drive_server
"""

import asyncio
import logging

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

import app.config as _config
from app.delivery.models import DriveUploadRequest, ToolOutcome
from app.delivery.mcp_servers.google_auth import (
    CredentialsError,
    build_drive_service,
    load_credentials,
)

logger = logging.getLogger("contractsentinel.delivery.drive_server")

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


def _is_retryable(status: int) -> bool:
    return status in _RETRYABLE_STATUSES


async def _handle_upload(req: DriveUploadRequest) -> ToolOutcome:
    """Drive upload handler — testable without the MCP stdio layer."""
    try:
        creds = await asyncio.to_thread(
            load_credentials,
            _config.GOOGLE_OAUTH_CREDENTIALS_PATH,
            _config.GOOGLE_OAUTH_TOKEN_PATH,
        )
        svc = await asyncio.to_thread(build_drive_service, creds)

        folder_query = f" and '{req.folder_id}' in parents" if req.folder_id else ""
        q = f"name='{req.file_name}'{folder_query} and trashed=false"

        results = await asyncio.to_thread(
            lambda: svc.files().list(q=q, fields="files(id)").execute()
        )
        existing = results.get("files", [])

        media = await asyncio.to_thread(
            lambda: MediaFileUpload(req.file_path, mimetype=req.mime_type)
        )

        if existing:
            file_id = existing[0]["id"]
            result = await asyncio.to_thread(
                lambda: svc.files()
                .update(fileId=file_id, media_body=media, fields="id,webViewLink")
                .execute()
            )
        else:
            parents = [req.folder_id] if req.folder_id else []
            result = await asyncio.to_thread(
                lambda: svc.files()
                .create(
                    body={"name": req.file_name, "parents": parents},
                    media_body=media,
                    fields="id,webViewLink",
                )
                .execute()
            )

        return ToolOutcome(ok=True, resource_ref=result.get("webViewLink"))

    except CredentialsError as exc:
        return ToolOutcome(ok=False, retryable=False, error_message=f"auth: {exc}")
    except HttpError as exc:
        retryable = _is_retryable(exc.resp.status)
        return ToolOutcome(ok=False, retryable=retryable, error_message=str(exc))
    except Exception as exc:
        logger.exception("Unexpected Drive upload error: %s", exc)
        return ToolOutcome(ok=False, retryable=False, error_message=str(exc))


if __name__ == "__main__":
    import asyncio as _asyncio

    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server

        app = Server("drive-server")

        @app.call_tool()
        async def upload_file(name: str, arguments: dict) -> list:
            req = DriveUploadRequest(**arguments)
            outcome = await _handle_upload(req)
            return [{"type": "text", "text": outcome.model_dump_json()}]

        _asyncio.run(stdio_server(app))
    except ImportError:
        pass
