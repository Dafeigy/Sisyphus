"""Provider-neutral message and content block types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


@dataclass(frozen=True)
class TextBlock:
    text: str


@dataclass(frozen=True)
class ToolCallBlock:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolResultBlock:
    tool_call_id: str
    content: str | dict | list
    is_error: bool = False


ContentBlock: TypeAlias = TextBlock | ToolCallBlock | ToolResultBlock


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentBlock]

    @classmethod
    def text(cls, role: Literal["system", "user", "assistant", "tool"], text: str) -> "Message":
        return cls(role=role, content=[TextBlock(text=text)])
