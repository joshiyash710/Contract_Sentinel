"""
Unit tests for MCP client wrappers + call_tool_with_retry (TDD red phase).

call_tool_with_retry is patched with async stubs; retry/timeout logic is tested
by injecting fake tool-call coroutines. Backoff is verified by patching asyncio.sleep.

Run: python -m pytest tests/unit/test_mcp_clients.py -v
Expected before Task 11: FAIL (ImportError)
Expected after Task 11:  PASS
"""

import asyncio
from unittest.mock import AsyncMock, patch

# ─── Drive client mapping ─────────────────────────────────────────────────────


async def test_drive_client_maps_outcome():
    from app.delivery.mcp_clients.drive_client import upload_report_to_drive
    from app.delivery.models import ToolOutcome

    ok_outcome = ToolOutcome(ok=True, resource_ref="https://drive.google.com/file/abc")

    with patch(
        "app.delivery.mcp_clients.drive_client.call_tool_with_retry",
        new=AsyncMock(return_value=ok_outcome),
    ):
        result = await upload_report_to_drive(
            "/tmp/r.md",
            "r.md",
            "text/markdown",
            None,
            timeout_seconds=60,
            max_retries=2,
        )

    assert result.service == "drive"
    assert result.ok is True
    assert result.resource_ref == "https://drive.google.com/file/abc"


async def test_gmail_client_maps_outcome():
    from app.delivery.mcp_clients.gmail_client import send_report_via_gmail
    from app.delivery.models import ToolOutcome

    ok_outcome = ToolOutcome(ok=True, resource_ref="msg_001")

    with patch(
        "app.delivery.mcp_clients.gmail_client.call_tool_with_retry",
        new=AsyncMock(return_value=ok_outcome),
    ):
        result = await send_report_via_gmail(
            "a@b.com",
            "Subject",
            "Body",
            None,
            None,
            timeout_seconds=60,
            max_retries=2,
        )

    assert result.service == "gmail"
    assert result.ok is True
    assert result.resource_ref == "msg_001"


async def test_client_never_raises():
    """If call_tool_with_retry raises unexpectedly, the wrapper catches it."""
    from app.delivery.mcp_clients.drive_client import upload_report_to_drive

    with patch(
        "app.delivery.mcp_clients.drive_client.call_tool_with_retry",
        new=AsyncMock(side_effect=RuntimeError("unexpected")),
    ):
        result = await upload_report_to_drive(
            "/tmp/r.md",
            "r.md",
            "text/markdown",
            None,
            timeout_seconds=60,
            max_retries=2,
        )

    assert result.ok is False
    assert result.error_message is not None


# ─── call_tool_with_retry logic ───────────────────────────────────────────────


async def test_timeout_becomes_failed():
    """Every attempt times out → terminal ToolOutcome(ok=False) with timeout message."""
    from app.delivery.mcp_clients.session import call_tool_with_retry

    async def always_timeout(*args, **kwargs):
        raise asyncio.TimeoutError

    with (
        patch("app.delivery.mcp_clients.session._call_once", new=always_timeout),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        outcome = await call_tool_with_retry(
            "mod", "tool", {}, timeout_seconds=1, max_retries=2
        )

    assert outcome.ok is False
    assert outcome.error_message is not None


async def test_retryable_is_retried_with_backoff():
    """retryable=True outcome is retried max_retries times; sleep is called between attempts."""
    from app.delivery.mcp_clients.session import call_tool_with_retry
    from app.delivery.models import ToolOutcome

    retryable_outcome = ToolOutcome(ok=False, retryable=True, error_message="transient")
    call_count = 0

    async def always_retryable(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return retryable_outcome

    with (
        patch("app.delivery.mcp_clients.session._call_once", new=always_retryable),
        patch("asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        outcome = await call_tool_with_retry(
            "mod", "tool", {}, timeout_seconds=60, max_retries=2
        )

    assert outcome.ok is False
    assert call_count == 3  # 1 initial + 2 retries
    assert mock_sleep.call_count == 2  # sleep between each retry


async def test_non_retryable_fails_immediately():
    """retryable=False → exactly 1 attempt, immediate FAILED."""
    from app.delivery.mcp_clients.session import call_tool_with_retry
    from app.delivery.models import ToolOutcome

    call_count = 0

    async def non_retryable(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return ToolOutcome(ok=False, retryable=False, error_message="auth error")

    with (
        patch("app.delivery.mcp_clients.session._call_once", new=non_retryable),
        patch("asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        outcome = await call_tool_with_retry(
            "mod", "tool", {}, timeout_seconds=60, max_retries=2
        )

    assert outcome.ok is False
    assert call_count == 1
    mock_sleep.assert_not_called()


async def test_worst_case_attempts_bounded():
    """Total attempts never exceed 1 + max_retries regardless of error type."""
    from app.delivery.mcp_clients.session import call_tool_with_retry
    from app.delivery.models import ToolOutcome

    call_count = 0
    max_retries = 3

    async def always_retryable(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return ToolOutcome(ok=False, retryable=True, error_message="transient")

    with (
        patch("app.delivery.mcp_clients.session._call_once", new=always_retryable),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        await call_tool_with_retry(
            "mod", "tool", {}, timeout_seconds=60, max_retries=max_retries
        )

    assert call_count == 1 + max_retries
