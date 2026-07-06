"""Permission policy contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any, Callable, Protocol


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


@dataclass(frozen=True)
class ApprovalDecision:
    allowed: bool
    reason: str | None = None
    remember: bool = False


class PermissionPolicy(Protocol):
    async def check(self, request: PermissionRequest) -> PermissionDecision:
        ...


class ApprovalResolver(Protocol):
    async def resolve_approval(
        self,
        request: PermissionRequest,
        decision: PermissionDecision,
    ) -> PermissionDecision:
        ...


class AllowAllPolicy:
    async def check(self, request: PermissionRequest) -> PermissionDecision:
        return PermissionDecision(allowed=True)


ApprovalHandler = Callable[[PermissionRequest, PermissionDecision], ApprovalDecision]


class ApprovalPermissionPolicy:
    """Wrap a policy with dynamic per-request approval decisions."""

    def __init__(self, base: PermissionPolicy, approve: ApprovalHandler) -> None:
        self.base = base
        self.approve = approve
        self._remembered: set[tuple[str, str, str]] = set()

    async def check(self, request: PermissionRequest) -> PermissionDecision:
        if self._key(request) in self._remembered:
            return PermissionDecision(allowed=True, reason="Approved by remembered permission.")
        return await self.base.check(request)

    async def resolve_approval(
        self,
        request: PermissionRequest,
        decision: PermissionDecision,
    ) -> PermissionDecision:
        approval = self.approve(request, decision)
        if isawaitable(approval):
            approval = await approval
        if approval.allowed and approval.remember:
            self._remembered.add(self._key(request))
        return PermissionDecision(
            allowed=approval.allowed,
            reason=approval.reason or decision.reason,
            require_approval=False,
        )

    @staticmethod
    def _key(request: PermissionRequest) -> tuple[str, str, str]:
        return (request.kind, request.action, request.resource)
