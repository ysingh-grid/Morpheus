"""Async MCP stdio client used only by Temporal activities."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _timeout_seconds() -> float:
    """Return the bounded MCP operation timeout."""
    return float(os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "30"))


def _result_to_dict(result: Any) -> dict[str, Any]:
    """Convert an MCP tool result into JSON-compatible data."""
    if hasattr(result, "model_dump"):
        return dict(result.model_dump(mode="json"))
    return {"content": str(result)}


async def call_mcp_tool(
    server_command: str,
    server_args: list[str],
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Start one stdio MCP server, invoke its tool, and return its result.

    Both MCP initialization and the tool call are bounded so a blocked server
    cannot consume an activity worker indefinitely.
    """
    parameters = StdioServerParameters(command=server_command, args=server_args)
    timeout = _timeout_seconds()
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await asyncio.wait_for(session.initialize(), timeout=timeout)
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments),
                timeout=timeout,
            )
    return _result_to_dict(result)
