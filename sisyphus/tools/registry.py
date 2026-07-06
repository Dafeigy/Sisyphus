"""Tool registry and conversion helpers."""

from __future__ import annotations

from collections.abc import Iterable

from sisyphus.models import ToolSpec
from sisyphus.tools.base import Tool


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name=tool.name, description=tool.description, input_schema=tool.input_schema)
            for tool in self._tools.values()
        ]

    def __iter__(self):
        return iter(self._tools.values())
