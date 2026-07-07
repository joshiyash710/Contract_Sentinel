"""
Drive client wrapper — maps _call_once ToolOutcome → DeliveryResult.
Never raises; all errors are contained as DeliveryResult(ok=False).
"""

import logging
from typing import Optional

from app.delivery.models import DeliveryResult, DriveUploadRequest
from app.delivery.mcp_clients.session import call_tool_with_retry

logger = logging.getLogger("contractsentinel.delivery.drive_client")


async def upload_report_to_drive(
    file_path: str,
    file_name: str,
    mime_type: str,
    folder_id: Optional[str],
    *,
    timeout_seconds: int,
    max_retries: int,
) -> DeliveryResult:
    try:
        req = DriveUploadRequest(
            file_path=file_path,
            file_name=file_name,
            mime_type=mime_type,
            folder_id=folder_id,
        )
        outcome = await call_tool_with_retry(
            "app.delivery.mcp_servers.drive_server",
            "upload_file",
            req.model_dump(),
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        return DeliveryResult(
            service="drive",
            ok=outcome.ok,
            resource_ref=outcome.resource_ref,
            error_message=outcome.error_message,
        )
    except Exception as exc:
        logger.exception("Unexpected Drive client error: %s", exc)
        return DeliveryResult(service="drive", ok=False, error_message=str(exc))
