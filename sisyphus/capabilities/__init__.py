"""Capability public API."""

from sisyphus.capabilities.fs import FileSystemCapability, PermissionDeniedError

__all__ = ["FileSystemCapability", "PermissionDeniedError"]
