"""Tool contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from sisyphus.core.context import RuntimeContext


@dataclass(frozen=True)
class ToolResult:
    content: str | dict[str, Any] | list[Any]
    is_error: bool = False
    metadata: dict[str, Any] | None = None


class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]

    async def execute(self, ctx: RuntimeContext, **kwargs: Any) -> ToolResult:
        ...


@dataclass(frozen=True)
class MockTool:
    name: str
    description: str
    response: str | dict[str, Any] | list[Any]
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})

    async def execute(self, ctx: RuntimeContext, **kwargs: Any) -> ToolResult:
        return ToolResult(content=self.response, metadata={"arguments": kwargs})
