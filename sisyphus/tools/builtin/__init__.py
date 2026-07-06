"""Small built-in tools for early runtime development."""

from __future__ import annotations

from typing import Any

from sisyphus.tools.base import MockTool, Tool
from sisyphus.tools.builtin.fs import ListFilesTool, ReadFileTool, WriteFileTool


def available_builtin_tool_names() -> list[str]:
    return sorted(_available_builtin_tools())


def builtin_tools(names: list[str] | None = None) -> list[Tool]:
    available = _available_builtin_tools()
    if names is None:
        return list(available.values())

    missing = [name for name in names if name not in available]
    if missing:
        raise ValueError(f"Unknown built-in tool(s): {', '.join(missing)}")
    return [available[name] for name in names]


def _available_builtin_tools() -> dict[str, Tool]:
    return {
        "list_files": ListFilesTool(),
        "read_file": ReadFileTool(),
        "write_file": WriteFileTool(),
        "mock_lookup": MockTool(
            name="mock_lookup",
            description="Return mock lookup data for development.",
            response={"status": "ok", "items": ["mock-a", "mock-b"]},
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        "echo": EchoTool(),
    }


class EchoTool:
    name = "echo"
    description = "Echo input arguments for development."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, ctx, **kwargs: Any):
        from sisyphus.tools.base import ToolResult

        return ToolResult(content=kwargs)
