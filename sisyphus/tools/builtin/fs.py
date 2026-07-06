"""Filesystem tools backed by RuntimeContext.fs."""

from __future__ import annotations

from typing import Any

from sisyphus.core.context import RuntimeContext
from sisyphus.tools.base import ToolResult


class ListFilesTool:
    name = "list_files"
    description = "List files in a workspace directory."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"path": {"type": "string", "default": "."}},
    }

    async def execute(self, ctx: RuntimeContext, **kwargs: Any) -> ToolResult:
        files = await ctx.fs.list_files(kwargs.get("path", "."))
        return ToolResult(content=files)


class ReadFileTool:
    name = "read_file"
    description = "Read a text file from the workspace."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    async def execute(self, ctx: RuntimeContext, **kwargs: Any) -> ToolResult:
        content = await ctx.fs.read_text(kwargs["path"])
        return ToolResult(content=content)


class WriteFileTool:
    name = "write_file"
    description = "Write a text file inside the workspace."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, ctx: RuntimeContext, **kwargs: Any) -> ToolResult:
        await ctx.fs.write_text(kwargs["path"], kwargs["content"])
        return ToolResult(content={"path": kwargs["path"], "written": True})
