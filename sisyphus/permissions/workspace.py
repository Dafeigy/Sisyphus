"""Workspace-scoped permission policy."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from sisyphus.permissions.base import PermissionDecision, PermissionRequest

PermissionMode = bool | Literal["allow", "deny", "ask"]


class WorkspacePolicy:
    def __init__(
        self,
        root: str | Path = ".",
        *,
        read: PermissionMode = True,
        write: PermissionMode = False,
        allow_shell: bool = False,
    ) -> None:
        self.root = Path(root).resolve()
        self.read = _normalize_mode(read)
        self.write = _normalize_mode(write)
        self.allow_shell = allow_shell

    async def check(self, request: PermissionRequest) -> PermissionDecision:
        if request.kind == "filesystem":
            path = Path(request.resource).resolve()
            if not path.is_relative_to(self.root):
                return PermissionDecision(False, f"Path is outside workspace: {path}")
            if request.action == "read":
                return _decision_for_mode(self.read, "Filesystem reads")
            if request.action == "write":
                return _decision_for_mode(self.write, "Filesystem writes")
        if request.kind == "shell":
            return PermissionDecision(self.allow_shell, None if self.allow_shell else "Shell execution is disabled.")
        return PermissionDecision(False, f"Unsupported permission request: {request.kind}.{request.action}")


def _normalize_mode(value: PermissionMode) -> Literal["allow", "deny", "ask"]:
    if value is True:
        return "allow"
    if value is False:
        return "deny"
    if value not in {"allow", "deny", "ask"}:
        raise ValueError(f"Unsupported permission mode: {value}")
    return value


def _decision_for_mode(mode: Literal["allow", "deny", "ask"], label: str) -> PermissionDecision:
    if mode == "allow":
        return PermissionDecision(True)
    if mode == "ask":
        return PermissionDecision(False, f"{label} require approval.", require_approval=True)
    return PermissionDecision(False, f"{label} are disabled.")
