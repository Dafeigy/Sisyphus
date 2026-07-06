"""Aggregated runtime results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sisyphus.core.events import RuntimeEvent
from sisyphus.core.messages import Message, TextBlock


@dataclass(frozen=True)
class RunResult:
    messages: list[Message]
    events: list[RuntimeEvent] = field(default_factory=list)
    run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        parts: list[str] = []
        for message in self.messages:
            if message.role != "assistant":
                continue
            parts.extend(block.text for block in message.content if isinstance(block, TextBlock))
        return "".join(parts)
