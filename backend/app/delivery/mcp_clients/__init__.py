"""
app.delivery.mcp_clients — async client wrappers for Drive and Gmail MCP servers.

Public API:
    upload_report_to_drive(file_path, file_name, mime_type, folder_id, *, timeout_seconds, max_retries) -> DeliveryResult
    send_report_via_gmail(to, subject, body, attachment_path, attachment_name, *, timeout_seconds, max_retries) -> DeliveryResult
"""

from app.delivery.mcp_clients.drive_client import upload_report_to_drive
from app.delivery.mcp_clients.gmail_client import send_report_via_gmail

__all__ = ["upload_report_to_drive", "send_report_via_gmail"]
