"""Permission-aware workspace filesystem capability."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sisyphus.core.events import EventSink
from sisyphus.permissions import PermissionDecision, PermissionPolicy, PermissionRequest


class PermissionDeniedError(PermissionError):
    pass


class FileSystemCapability:
    def __init__(
        self,
        root: str | Path,
        permissions: PermissionPolicy,
        events: EventSink,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.permissions = permissions
        self.events = events
        self.metadata = metadata if metadata is not None else {}

    async def read_text(self, path: str | Path, *, encoding: str = "utf-8", max_chars: int | None = None) -> str:
        target = self._resolve(path)
        await self._require("read", target, details={"encoding": encoding, "max_chars": max_chars})
        if max_chars is None:
            return target.read_text(encoding=encoding)
        with target.open("r", encoding=encoding) as file:
            return file.read(max_chars)

    async def write_text(
        self,
        path: str | Path,
        content: str,
        *,
        encoding: str = "utf-8",
        append: bool = False,
        create_dirs: bool = True,
    ) -> None:
        target = self._resolve(path)
        await self._require(
            "write",
            target,
            details={
                "encoding": encoding,
                "append": append,
                "create_dirs": create_dirs,
                "bytes": len(content.encode(encoding)),
            },
        )
        if create_dirs:
            target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with target.open(mode, encoding=encoding) as file:
            file.write(content)

    async def list_files(self, path: str | Path = ".") -> list[str]:
        target = self._resolve(path)
        await self._require("read", target)
        return sorted(str(item.relative_to(self.root)) for item in target.iterdir())

    def _resolve(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return candidate.resolve()

    async def _require(
        self,
        action: str,
        target: Path,
        *,
        details: dict[str, Any] | None = None,
    ) -> PermissionDecision:
        request = PermissionRequest(kind="filesystem", action=action, resource=str(target), details=self._details(details))
        await self.events.emit("permission.requested", {"request": request.__dict__})
        decision = await self.permissions.check(request)
        if decision.require_approval:
            await self.events.emit("permission.approval_requested", {"request": request.__dict__, "decision": decision.__dict__})
            resolver = getattr(self.permissions, "resolve_approval", None)
            if resolver is None:
                decision = PermissionDecision(False, decision.reason or "Permission approval is required.")
            else:
                decision = await resolver(request, decision)
            await self.events.emit("permission.approval_resolved", {"request": request.__dict__, "decision": decision.__dict__})
        await self.events.emit("permission.resolved", {"request": request.__dict__, "decision": decision.__dict__})
        if not decision.allowed:
            raise PermissionDeniedError(decision.reason or f"Permission denied: {action} {target}")
        return decision

    def _details(self, details: dict[str, Any] | None) -> dict[str, Any]:
        merged = dict(details or {})
        tool = self.metadata.get("tool")
        if tool:
            merged["tool"] = tool
        return merged
