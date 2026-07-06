"""Workspace-scoped permission policy."""

from __future__ import annotations

from pathlib import Path

from sisyphus.permissions.base import PermissionDecision, PermissionRequest


class WorkspacePolicy:
    def __init__(
        self,
        root: str | Path = ".",
        *,
        read: bool = True,
        write: bool = False,
        allow_shell: bool = False,
    ) -> None:
        self.root = Path(root).resolve()
        self.read = read
        self.write = write
        self.allow_shell = allow_shell

    async def check(self, request: PermissionRequest) -> PermissionDecision:
        if request.kind == "filesystem":
            path = Path(request.resource).resolve()
            if not path.is_relative_to(self.root):
                return PermissionDecision(False, f"Path is outside workspace: {path}")
            if request.action == "read":
                return PermissionDecision(self.read, None if self.read else "Filesystem reads are disabled.")
            if request.action == "write":
                return PermissionDecision(self.write, None if self.write else "Filesystem writes are disabled.")
        if request.kind == "shell":
            return PermissionDecision(self.allow_shell, None if self.allow_shell else "Shell execution is disabled.")
        return PermissionDecision(False, f"Unsupported permission request: {request.kind}.{request.action}")
