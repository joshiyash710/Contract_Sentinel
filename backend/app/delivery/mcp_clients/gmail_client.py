"""
Gmail client wrapper — maps _call_once ToolOutcome → DeliveryResult.
Never raises; all errors are contained as DeliveryResult(ok=False).
"""

import logging
from typing import Optional

from app.delivery.models import DeliveryResult, GmailSendRequest
from app.delivery.mcp_clients.session import call_tool_with_retry

logger = logging.getLogger("contractsentinel.delivery.gmail_client")


async def send_report_via_gmail(
    to: str,
    subject: str,
    body: str,
    attachment_path: Optional[str],
    attachment_name: Optional[str],
    *,
    timeout_seconds: int,
    max_retries: int,
) -> DeliveryResult:
    try:
        req = GmailSendRequest(
            to=to,
            subject=subject,
            body=body,
            attachment_path=attachment_path,
            attachment_name=attachment_name,
        )
        outcome = await call_tool_with_retry(
            "app.delivery.mcp_servers.gmail_server",
            "send_message",
            req.model_dump(),
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        return DeliveryResult(
            service="gmail",
            ok=outcome.ok,
            resource_ref=outcome.resource_ref,
            error_message=outcome.error_message,
        )
    except Exception as exc:
        logger.exception("Unexpected Gmail client error: %s", exc)
        return DeliveryResult(service="gmail", ok=False, error_message=str(exc))
