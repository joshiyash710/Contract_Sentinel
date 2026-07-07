"""
deliver_report — post-terminal MCP delivery step (NOT a graph node, spec §8a D1).

Takes the report ReportAgent (Node 7) wrote to disk and delivers it over
Google Drive and Gmail. The graph (builder.py) is untouched by this module.

Returns only {"mcp_delivery_status": {...}}: one key, values keyed by service
("drive" / "gmail"), each {"status", "error_message", "delivered_at"}.
Never raises; never writes current_node / node_timings / error_count.
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

import app.config as _config
from app.delivery.mcp_clients import send_report_via_gmail, upload_report_to_drive
from app.delivery.models import DeliveryResult
from app.graph.state import MCPDeliveryStatus
from app.models.report import ContractReport

logger = logging.getLogger("contractsentinel.delivery")

# ── config re-exposure (mirrors report_agent.py pattern) ──────────────────────
# Re-expose as module-level names so tests can monkeypatch without touching _config.

MCP_DELIVERY_ENABLED = _config.MCP_DELIVERY_ENABLED
MCP_DRIVE_ENABLED = _config.MCP_DRIVE_ENABLED
MCP_GMAIL_ENABLED = _config.MCP_GMAIL_ENABLED
MCP_DELIVERY_RECIPIENT = _config.MCP_DELIVERY_RECIPIENT
MCP_DRIVE_FOLDER_ID = _config.MCP_DRIVE_FOLDER_ID
MCP_DRIVE_UPLOAD_FORMATS = _config.MCP_DRIVE_UPLOAD_FORMATS
MCP_GMAIL_ATTACH_REPORT = _config.MCP_GMAIL_ATTACH_REPORT
MCP_DELIVERY_TIMEOUT_SECONDS = _config.MCP_DELIVERY_TIMEOUT_SECONDS
MCP_DELIVERY_MAX_RETRIES = _config.MCP_DELIVERY_MAX_RETRIES


# ── helpers ───────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_info(result: DeliveryResult) -> dict:
    return {
        "status": MCPDeliveryStatus.SUCCESS if result.ok else MCPDeliveryStatus.FAILED,
        "error_message": result.error_message,
        "delivered_at": _now_iso() if result.ok else None,
    }


def _failed_info(msg: str) -> dict:
    return {
        "status": MCPDeliveryStatus.FAILED,
        "error_message": msg,
        "delivered_at": None,
    }


def _all_enabled_failed(reason: str) -> dict:
    """Return a FAILED entry for each config-enabled channel (D13)."""
    status = {}
    if MCP_DRIVE_ENABLED:
        status["drive"] = _failed_info(reason)
    if MCP_GMAIL_ENABLED:
        status["gmail"] = _failed_info(reason)
    return status


def _load_summary(json_path: Optional[Path]):
    """Load ContractReport.summary from the JSON sibling; None on any error (Edge Case 4)."""
    if json_path is None:
        return None
    try:
        text = json_path.read_text(encoding="utf-8")
        return ContractReport.model_validate_json(text).summary
    except (OSError, ValidationError) as exc:
        logger.warning("Could not load report JSON sibling: %s", exc)
        return None


async def _deliver_drive(md_path: Path, json_path: Path) -> DeliveryResult:
    """Upload each configured format; aggregate into one DeliveryResult."""
    results = []
    md_ref = None

    ext_to_path = {"md": md_path, "json": json_path}
    ext_to_mime = {"md": "text/markdown", "json": "application/json"}

    for ext in MCP_DRIVE_UPLOAD_FORMATS:
        path = ext_to_path.get(ext)
        if path is None:
            continue
        mime = ext_to_mime.get(ext, "application/octet-stream")
        r = await upload_report_to_drive(
            str(path),
            path.name,
            mime,
            MCP_DRIVE_FOLDER_ID,
            timeout_seconds=MCP_DELIVERY_TIMEOUT_SECONDS,
            max_retries=MCP_DELIVERY_MAX_RETRIES,
        )
        results.append(r)
        if ext == "md" and r.ok:
            md_ref = r.resource_ref

    if not results:
        return DeliveryResult(
            service="drive", ok=False, error_message="no upload formats configured"
        )

    all_ok = all(r.ok for r in results)
    errors = [r.error_message for r in results if not r.ok and r.error_message]
    return DeliveryResult(
        service="drive",
        ok=all_ok,
        resource_ref=md_ref,
        error_message="; ".join(errors) if errors else None,
    )


def _compose_email(
    document_id: str, state: dict, summary, drive_ref: Optional[str]
) -> tuple[str, str]:
    original_filename = state.get("original_filename", document_id)

    if summary is not None:
        subject = (
            f"ContractSentinel report — {original_filename}: "
            f"{summary.validated_findings} findings "
            f"({summary.high} high / {summary.medium} med / {summary.low} low)"
        )
        body_lines = [
            f"ContractSentinel has completed analysis of {original_filename}.",
            "",
            f"Summary: {summary.validated_findings} findings — "
            f"{summary.high} high, {summary.medium} medium, {summary.low} low.",
        ]
    else:
        subject = f"ContractSentinel report — {original_filename}"
        body_lines = [
            f"ContractSentinel has completed analysis of {original_filename}.",
        ]

    if drive_ref:
        body_lines += ["", f"View report on Google Drive: {drive_ref}"]

    body_lines += ["", "The full Markdown report is attached to this email."]

    return subject, "\n".join(body_lines)


# ── main orchestrator ─────────────────────────────────────────────────────────


async def deliver_report(state: dict, *, recipient: Optional[str] = None) -> dict:
    """Deliver the Node-7 report via Drive + Gmail. Returns only mcp_delivery_status."""
    if not MCP_DELIVERY_ENABLED or (not MCP_DRIVE_ENABLED and not MCP_GMAIL_ENABLED):
        logger.info("MCP delivery disabled — skipping")
        return {"mcp_delivery_status": {}}

    report_path = state.get("report_path")
    document_id = state.get("document_id", "unknown")
    md_path = Path(report_path) if report_path else None
    json_path = md_path.with_suffix(".json") if md_path else None

    # Guard: missing or non-existent report file
    if report_path is None:
        reason = "no report_path (Node 7 write failed)"
        logger.warning("Delivery skipped: %s", reason)
        return {"mcp_delivery_status": _all_enabled_failed(reason)}
    if not md_path.exists():
        reason = "report file not found"
        logger.warning("Delivery skipped: %s — %s", reason, md_path)
        return {"mcp_delivery_status": _all_enabled_failed(reason)}

    summary = _load_summary(json_path)
    status: dict = {}
    drive_ref: Optional[str] = None

    # ── Drive ─────────────────────────────────────────────────────────────────
    if MCP_DRIVE_ENABLED:
        drive_result = await _deliver_drive(md_path, json_path)
        status["drive"] = _to_info(drive_result)
        if drive_result.ok:
            drive_ref = drive_result.resource_ref

    # ── Gmail ─────────────────────────────────────────────────────────────────
    if MCP_GMAIL_ENABLED:
        to = recipient or MCP_DELIVERY_RECIPIENT
        if not to:
            status["gmail"] = _failed_info("no recipient configured")
        else:
            subject, body = _compose_email(document_id, state, summary, drive_ref)
            attach = str(md_path) if MCP_GMAIL_ATTACH_REPORT else None
            gmail_result = await send_report_via_gmail(
                to,
                subject,
                body,
                attach,
                md_path.name,
                timeout_seconds=MCP_DELIVERY_TIMEOUT_SECONDS,
                max_retries=MCP_DELIVERY_MAX_RETRIES,
            )
            status["gmail"] = _to_info(gmail_result)

    logger.info(
        "MCP delivery completed for %s — %s",
        document_id,
        {k: v["status"] for k, v in status.items()},
    )
    return {"mcp_delivery_status": status}


def deliver_report_sync(state: dict, *, recipient: Optional[str] = None) -> dict:
    """Synchronous wrapper around deliver_report for non-async callers.

    Runs asyncio.run in a dedicated thread so this can be called safely even
    when an event loop is already running in the calling thread (e.g. pytest).
    """
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            asyncio.run, deliver_report(state, recipient=recipient)
        ).result()
