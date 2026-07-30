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
    token_path: Optional[str] = None  # feature 031: per-user Drive token; None → central token


class GmailSendRequest(BaseModel):
    to: str
    subject: str
    body: str
    html_body: Optional[str] = None  # feature 030: HTML alternative body (plain `body` is the fallback)
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
