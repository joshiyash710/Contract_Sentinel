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
from app.delivery.report_naming import drive_escape
from app.delivery.mcp_servers.google_auth import (
    CredentialsError,
    build_drive_service,
    load_credentials,
)

logger = logging.getLogger("contractsentinel.delivery.drive_server")

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_FOLDER_MIME = "application/vnd.google-apps.folder"


def _is_retryable(status: int) -> bool:
    return status in _RETRYABLE_STATUSES


async def _resolve_folder_id(svc, req: DriveUploadRequest):
    """Resolve the parent folder id for the upload (feature 033).

    Precedence (spec Decision 3 / AC-4): an explicit `folder_id` wins and skips
    find-or-create. Else, when `folder_name` is set, find-or-create it in the
    authenticated Drive (AC-1/AC-2/AC-3). Else → None (root, AC-5)."""
    if req.folder_id:
        return req.folder_id
    if not req.folder_name:
        return None

    q = (
        f"mimeType='{_FOLDER_MIME}' and name='{drive_escape(req.folder_name)}' "
        "and trashed=false"
    )
    results = await asyncio.to_thread(
        lambda: svc.files()
        .list(q=q, fields="files(id)", orderBy="createdTime")
        .execute()
    )
    folders = results.get("files", [])
    if folders:
        return folders[0]["id"]  # oldest match reused deterministically (AC-3)

    created = await asyncio.to_thread(
        lambda: svc.files()
        .create(body={"name": req.folder_name, "mimeType": _FOLDER_MIME}, fields="id")
        .execute()
    )
    return created["id"]


async def _handle_upload(req: DriveUploadRequest) -> ToolOutcome:
    """Drive upload handler — testable without the MCP stdio layer."""
    try:
        # Feature 031: authenticate as the per-user token when provided, else the central token.
        token_path = req.token_path or _config.GOOGLE_OAUTH_TOKEN_PATH
        creds = await asyncio.to_thread(
            load_credentials,
            _config.GOOGLE_OAUTH_CREDENTIALS_PATH,
            token_path,
        )
        svc = await asyncio.to_thread(build_drive_service, creds)

        # Feature 033: resolve (find-or-create) the target folder, then scope the
        # name-match query and file parents to that resolved id (AC-4/AC-6a).
        resolved_folder_id = await _resolve_folder_id(svc, req)

        folder_query = (
            f" and '{resolved_folder_id}' in parents" if resolved_folder_id else ""
        )
        q = f"name='{drive_escape(req.file_name)}'{folder_query} and trashed=false"

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
            parents = [resolved_folder_id] if resolved_folder_id else []
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
                        "folder_name": {"type": ["string", "null"]},
                        "token_path": {"type": ["string", "null"]},
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
