"""Runtime context exposed to tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sisyphus.capabilities import FileSystemCapability
from sisyphus.core.events import EventSink


@dataclass
class RuntimeContext:
    cwd: Path
    fs: FileSystemCapability
    events: EventSink
    metadata: dict[str, Any] = field(default_factory=dict)
