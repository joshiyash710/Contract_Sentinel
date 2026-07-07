"""
Boundary transport Pydantic models for the MCP delivery step (constitution §4).

These types are validated before/after MCP tool calls and are never stored
in graph state. The graph state key `mcp_delivery_status` is built as a
plain dict by the orchestrator (delivery_step.py).
"""

from typing import Optional

from pydantic import BaseModel


class DriveUploadRequest(BaseModel):
    file_path: str
    file_name: str
    mime_type: str
    folder_id: Optional[str] = None


class GmailSendRequest(BaseModel):
    to: str
    subject: str
    body: str
    attachment_path: Optional[str] = None
    attachment_name: Optional[str] = None


class ToolOutcome(BaseModel):
    ok: bool
    resource_ref: Optional[str] = (
        None  # Drive webViewLink / Gmail message id (D12: not persisted)
    )
    error_message: Optional[str] = None
    retryable: bool = False


class DeliveryResult(BaseModel):
    service: str  # "drive" | "gmail"
    ok: bool
    resource_ref: Optional[str] = None
    error_message: Optional[str] = None
