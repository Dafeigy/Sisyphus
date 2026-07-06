"""Permission-aware workspace filesystem capability."""

from __future__ import annotations

from pathlib import Path

from sisyphus.core.events import EventSink
from sisyphus.permissions import PermissionDecision, PermissionPolicy, PermissionRequest


class PermissionDeniedError(PermissionError):
    pass


class FileSystemCapability:
    def __init__(self, root: str | Path, permissions: PermissionPolicy, events: EventSink) -> None:
        self.root = Path(root).resolve()
        self.permissions = permissions
        self.events = events

    async def read_text(self, path: str | Path, *, encoding: str = "utf-8") -> str:
        target = self._resolve(path)
        await self._require("read", target)
        return target.read_text(encoding=encoding)

    async def write_text(self, path: str | Path, content: str, *, encoding: str = "utf-8") -> None:
        target = self._resolve(path)
        await self._require("write", target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)

    async def list_files(self, path: str | Path = ".") -> list[str]:
        target = self._resolve(path)
        await self._require("read", target)
        return sorted(str(item.relative_to(self.root)) for item in target.iterdir())

    def _resolve(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return candidate.resolve()

    async def _require(self, action: str, target: Path) -> PermissionDecision:
        request = PermissionRequest(kind="filesystem", action=action, resource=str(target))
        await self.events.emit("permission.requested", {"request": request.__dict__})
        decision = await self.permissions.check(request)
        await self.events.emit("permission.resolved", {"request": request.__dict__, "decision": decision.__dict__})
        if not decision.allowed:
            raise PermissionDeniedError(decision.reason or f"Permission denied: {action} {target}")
        return decision
