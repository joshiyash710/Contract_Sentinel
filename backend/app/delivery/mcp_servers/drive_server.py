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


def _build_server():
    """Register the `upload_file` tool on a Server. Shared by _run_server and tests."""
    from mcp import types
    from mcp.server import Server

    server = Server("drive-server")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="upload_file",
                description="Upload a file to Google Drive, overwriting an existing file with the same name.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "file_name": {"type": "string"},
                        "mime_type": {"type": "string"},
                        "folder_id": {"type": ["string", "null"]},
                    },
                    "required": ["file_path", "file_name", "mime_type"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
        req = DriveUploadRequest(**(arguments or {}))
        outcome = await _handle_upload(req)
        return [types.TextContent(type="text", text=outcome.model_dump_json())]

    return server


async def _run_server() -> None:
    """Build and run the Drive MCP stdio server."""
    from mcp.server.stdio import stdio_server

    server = _build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(_run_server())
