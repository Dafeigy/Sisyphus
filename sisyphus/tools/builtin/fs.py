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
        "properties": {
            "path": {"type": "string"},
            "max_chars": {"type": "integer", "minimum": 1, "description": "Maximum characters to return."},
        },
        "required": ["path"],
    }

    async def execute(self, ctx: RuntimeContext, **kwargs: Any) -> ToolResult:
        max_chars = kwargs.get("max_chars")
        if max_chars is not None:
            max_chars = int(max_chars)
            content = await ctx.fs.read_text(kwargs["path"], max_chars=max_chars + 1)
            truncated = len(content) > max_chars
            if truncated:
                content = content[:max_chars]
        else:
            content = await ctx.fs.read_text(kwargs["path"])
            truncated = False
        return ToolResult(
            content=content,
            metadata={
                "path": kwargs["path"],
                "chars": len(content),
                "truncated": truncated,
                "max_chars": max_chars,
            },
        )


class WriteFileTool:
    name = "write_file"
    description = "Write a text file inside the workspace."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "append": {"type": "boolean", "default": False},
            "create_dirs": {"type": "boolean", "default": True},
        },
        "required": ["path", "content"],
    }

    async def execute(self, ctx: RuntimeContext, **kwargs: Any) -> ToolResult:
        append = bool(kwargs.get("append", False))
        create_dirs = bool(kwargs.get("create_dirs", True))
        content = str(kwargs["content"])
        await ctx.fs.write_text(kwargs["path"], content, append=append, create_dirs=create_dirs)
        return ToolResult(
            content={
                "path": kwargs["path"],
                "written": True,
                "append": append,
                "chars": len(content),
            }
        )
