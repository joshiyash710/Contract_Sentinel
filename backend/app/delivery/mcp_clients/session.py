"""
call_tool_with_retry — bounded exponential-backoff retry wrapper for MCP tool calls.

Abstracts the stdio client session lifecycle so Drive/Gmail clients are thin mappers.
Never raises; returns a terminal ToolOutcome on all failure paths.
"""

import asyncio
import logging

from app.delivery.models import ToolOutcome

logger = logging.getLogger("contractsentinel.delivery.session")

_BACKOFF_BASE: float = 0.5  # seconds; doubles each retry


async def _call_once(
    server_module: str, tool_name: str, arguments: dict, *, timeout_seconds: int
) -> ToolOutcome:
    """Open a stdio ClientSession, call one tool, return a parsed ToolOutcome."""
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters

    params = StdioServerParameters(
        command="python",
        args=["-m", server_module],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            raw = await asyncio.wait_for(
                session.call_tool(tool_name, arguments),
                timeout=timeout_seconds,
            )
            # The server encodes ToolOutcome as JSON in the first text content block.
            import json

            text = raw.content[0].text if raw.content else "{}"
            data = json.loads(text)
            return ToolOutcome(**data)


async def call_tool_with_retry(
    server_module: str,
    tool_name: str,
    arguments: dict,
    *,
    timeout_seconds: int,
    max_retries: int,
) -> ToolOutcome:
    """Call a server tool with bounded exponential-backoff retry. Never raises."""
    last_outcome: ToolOutcome = ToolOutcome(ok=False, error_message="no attempts made")

    for attempt in range(1 + max_retries):
        try:
            outcome = await _call_once(
                server_module, tool_name, arguments, timeout_seconds=timeout_seconds
            )
            if outcome.ok:
                return outcome
            if not outcome.retryable:
                return outcome
            last_outcome = outcome
        except asyncio.TimeoutError:
            last_outcome = ToolOutcome(
                ok=False,
                retryable=True,
                error_message=f"timeout after {timeout_seconds}s on attempt {attempt + 1}",
            )
        except Exception as exc:
            last_outcome = ToolOutcome(
                ok=False,
                retryable=True,
                error_message=f"connection error: {exc}",
            )

        if attempt < max_retries:
            delay = _BACKOFF_BASE * (2**attempt)
            logger.debug(
                "Retrying %s/%s in %.1fs (attempt %d/%d)",
                server_module,
                tool_name,
                delay,
                attempt + 1,
                1 + max_retries,
            )
            await asyncio.sleep(delay)

    return last_outcome
