"""Server-Sent Events helpers for runtime host adapters."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from sisyphus.core.events import RuntimeEvent


def encode_sse(event: RuntimeEvent, *, compact: bool = True) -> str:
    """Encode a runtime event as a Server-Sent Events message.

    The runtime itself stays transport-neutral; host frameworks can use this
    helper when exposing ``AgentRuntime.stream()`` through ``text/event-stream``.
    """

    payload = json.dumps(
        event.to_dict(),
        ensure_ascii=False,
        separators=(",", ":") if compact else None,
    )
    lines = [
        f"event: {event.type}",
        f"id: {event.sequence}",
        *_data_lines(payload),
        "",
        "",
    ]
    return "\n".join(lines)


def encode_sse_comment(comment: str = "") -> str:
    """Encode an SSE comment, useful for host-level heartbeat messages."""

    return "".join(f": {line}\n" for line in str(comment).splitlines() or [""]) + "\n"


def iter_sse(events: Iterable[RuntimeEvent], *, compact: bool = True) -> Iterable[str]:
    """Encode each runtime event in an iterable as SSE text."""

    for event in events:
        yield encode_sse(event, compact=compact)


def _data_lines(payload: str) -> list[str]:
    return [f"data: {line}" for line in payload.splitlines() or [""]]
