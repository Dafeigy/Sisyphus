"""Common model provider contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from sisyphus.core.messages import ContentBlock, Message


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelConfig:
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelResponse:
    content: list[ContentBlock]
    raw: dict[str, Any] | None = None
    model: str | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class ModelStreamDelta:
    content: list[ContentBlock] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    model: str | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


class ModelProvider(Protocol):
    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str | None = None,
        config: ModelConfig | None = None,
    ) -> ModelResponse:
        ...

    def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str | None = None,
        config: ModelConfig | None = None,
    ) -> AsyncIterator[ModelStreamDelta]:
        ...
