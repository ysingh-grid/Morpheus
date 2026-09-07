"""Async MCP stdio client used only by Temporal activities."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from typing import TYPE_CHECKING, Any, TypedDict

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

if TYPE_CHECKING:
    from agent.state import ToolSpec


class ResolvedMcpTool(TypedDict):
    """Concrete server configuration resolved for one registered MCP tool."""

    spec: ToolSpec
    command: str
    args: list[str]
    env: dict[str, str]


def _default_tool_registry() -> dict[str, dict[str, Any]]:
    """Return built-in MCP tools while allowing per-tool server configuration."""
    return {
        "tavily_search": {
            "description": "Search the public web for current information.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "minLength": 1}},
                "required": ["query"],
                "additionalProperties": False,
            },
            "timeout_seconds": int(os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "30")),
            "command": os.getenv("MCP_SERVER_COMMAND", ""),
            "args": shlex.split(os.getenv("MCP_SERVER_ARGS", "")),
            "env": {},
        },
        "calculator": {
            "description": "Evaluate a mathematical expression with a configured local calculator MCP server.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "minLength": 1}},
                "required": ["expression"],
                "additionalProperties": False,
            },
            "timeout_seconds": int(os.getenv("CALCULATOR_MCP_TIMEOUT_SECONDS", "10")),
            "command": os.getenv("CALCULATOR_MCP_SERVER_COMMAND", "uvx"),
            "args": shlex.split(
                os.getenv("CALCULATOR_MCP_SERVER_ARGS", "mcp-server-calculator")
            ),
            "env": {},
        },
        "get_full_table": {
            "description": (
                "Retrieve full normalized markdown, row count, column count, and context "
                "for a specific table using doc_id and table_id from attached documents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "The unique document identifier containing the table.",
                    },
                    "table_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "The table identifier within the document.",
                    },
                },
                "required": ["doc_id", "table_id"],
                "additionalProperties": False,
            },
            "timeout_seconds": int(os.getenv("TABLE_TOOL_TIMEOUT_SECONDS", "30")),
            "command": "native",
            "args": [],
            "env": {},
        },
    }


def _configured_tool_registry() -> dict[str, dict[str, Any]]:
    """Merge optional JSON-defined tools into the built-in MCP registry."""
    registry = _default_tool_registry()
    raw_registry = os.getenv("MCP_TOOL_REGISTRY_JSON", "").strip()
    if not raw_registry:
        return registry
    try:
        configured = json.loads(raw_registry)
    except json.JSONDecodeError as error:
        raise ValueError("MCP_TOOL_REGISTRY_JSON must contain a JSON object.") from error
    if not isinstance(configured, dict):
        raise ValueError("MCP_TOOL_REGISTRY_JSON must contain a JSON object.")
    for name, config in configured.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(config, dict):
            raise ValueError("Each MCP tool registry entry must have a non-empty name and object.")
        registry[name] = dict(config)
    return registry


def registered_tool_specs() -> list[ToolSpec]:
    """Return tool metadata that the agent planner is allowed to select."""
    specs: list[ToolSpec] = []
    for name, config in _configured_tool_registry().items():
        description = config.get("description")
        parameters = config.get("parameters")
        timeout_seconds = config.get("timeout_seconds")
        if (
            not isinstance(description, str)
            or not isinstance(parameters, dict)
            or not isinstance(timeout_seconds, int)
            or timeout_seconds <= 0
        ):
            raise ValueError(f"MCP tool '{name}' has an invalid registry specification.")
        specs.append(
            {
                "name": name,
                "description": description,
                "parameters": parameters,
                "timeout_seconds": timeout_seconds,
            }
        )
    return specs


def default_web_search_tool() -> str | None:
    """Return the registry-owned default tool for explicit web-search requests."""
    return next(
        (spec["name"] for spec in registered_tool_specs() if spec["name"] == "tavily_search"),
        None,
    )


def resolve_mcp_tool(tool_name: str) -> ResolvedMcpTool:
    """Resolve command, arguments, environment, and schema for a registered tool."""
    registry = _configured_tool_registry()
    config = registry.get(tool_name)
    if config is None:
        raise ValueError(f"MCP tool '{tool_name}' is not registered.")
    spec = next((item for item in registered_tool_specs() if item["name"] == tool_name), None)
    command = config.get("command")
    args = config.get("args")
    environment = config.get("env", {})
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"MCP tool '{tool_name}' is missing a server command.")
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise ValueError(f"MCP tool '{tool_name}' has invalid server arguments.")
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in environment.items()
    ):
        raise ValueError(f"MCP tool '{tool_name}' has invalid environment settings.")
    if spec is None:
        raise ValueError(f"MCP tool '{tool_name}' has an invalid registry specification.")
    return {
        "spec": spec,
        "command": command,
        "args": args,
        "env": {
            key: os.getenv(value[1:], "") if value.startswith("$") else value
            for key, value in environment.items()
        },
    }


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
    *,
    server_env: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Start one stdio MCP server, invoke its tool, and return its result.

    Both MCP initialization and the tool call are bounded so a blocked server
    cannot consume an activity worker indefinitely.
    """
    effective_env = None
    if server_env:
        effective_env = {**os.environ, **server_env}
    parameters = StdioServerParameters(
        command=server_command,
        args=server_args,
        env=effective_env,
    )
    timeout = timeout_seconds if timeout_seconds is not None else _timeout_seconds()
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await asyncio.wait_for(session.initialize(), timeout=timeout)
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments),
                timeout=timeout,
            )
    return _result_to_dict(result)
