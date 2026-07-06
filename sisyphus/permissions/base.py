"""Permission policy contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class PermissionRequest:
    kind: str
    action: str
    resource: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: str | None = None
    require_approval: bool = False


class PermissionPolicy(Protocol):
    async def check(self, request: PermissionRequest) -> PermissionDecision:
        ...


class AllowAllPolicy:
    async def check(self, request: PermissionRequest) -> PermissionDecision:
        return PermissionDecision(allowed=True)
