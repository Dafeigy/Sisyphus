"""Serializable runtime events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class RuntimeEvent:
    type: str
    run_id: str
    sequence: int
    timestamp: datetime
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
        }


class EventSink(Protocol):
    async def emit(self, event_type: str, data: dict[str, Any] | None = None) -> RuntimeEvent:
        ...


class RuntimeEventEmitter:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._sequence = 0
        self.events: list[RuntimeEvent] = []

    async def emit(self, event_type: str, data: dict[str, Any] | None = None) -> RuntimeEvent:
        event = RuntimeEvent(
            type=event_type,
            run_id=self.run_id,
            sequence=self._sequence,
            timestamp=datetime.now(UTC),
            data=data or {},
        )
        self._sequence += 1
        self.events.append(event)
        return event
