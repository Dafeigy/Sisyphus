"""Runtime configuration objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RunOptions:
    run_id: str | None = None
    max_iterations: int = 20
    timeout_seconds: float | None = None
    stream_tokens: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
