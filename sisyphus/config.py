"""Optional TOML configuration for Sisyphus hosts."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sisyphus.tools.builtin import available_builtin_tool_names


DEFAULT_CONFIG_FILES = ("sisyphus.toml", ".sisyphus.toml")
SUPPORTED_MODEL_PROVIDERS = {"openai"}


class ConfigError(ValueError):
    """Raised when a Sisyphus config file is invalid."""


@dataclass(frozen=True)
class ModelSettings:
    provider: str = "openai"
    model: str | None = None
    base_url: str | None = None
    chat_completions_path: str | None = None
    completions_url: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeSettings:
    max_iterations: int = 20
    timeout_seconds: float | None = None
    stream_tokens: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceSettings:
    root: str = "."
    read: bool | str = True
    write: bool | str = False


@dataclass(frozen=True)
class ToolsSettings:
    enabled: list[str] = field(default_factory=lambda: ["list_files", "read_file", "mock_lookup", "echo"])


@dataclass(frozen=True)
class SisyphusConfig:
    model: ModelSettings = field(default_factory=ModelSettings)
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    workspace: WorkspaceSettings = field(default_factory=WorkspaceSettings)
    tools: ToolsSettings = field(default_factory=ToolsSettings)


def load_config(path: str | Path | None) -> SisyphusConfig:
    """Load a Sisyphus TOML config file, or return defaults when path is None."""

    if path is None:
        return SisyphusConfig()
    try:
        with Path(path).open("rb") as file:
            data = tomllib.load(file)
    except OSError as exc:
        raise ConfigError(f"Unable to read config file {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in config file {path}: {exc}") from exc
    return validate_config(config_from_dict(data))


def discover_config_path(start: str | Path = ".") -> Path | None:
    """Find a default config file in a directory, if one exists."""

    root = Path(start)
    for name in DEFAULT_CONFIG_FILES:
        path = root / name
        if path.is_file():
            return path
    return None


def config_from_dict(data: dict[str, Any]) -> SisyphusConfig:
    """Build typed config from a parsed TOML dictionary."""

    _check_unknown_tables(data)
    return SisyphusConfig(
        model=_model_settings(_table(data, "model")),
        runtime=_runtime_settings(_table(data, "runtime")),
        workspace=_workspace_settings(_table(data, "workspace")),
        tools=_tools_settings(_table(data, "tools")),
    )


def validate_config(config: SisyphusConfig) -> SisyphusConfig:
    """Validate semantic config values that require project knowledge."""

    if config.model.provider not in SUPPORTED_MODEL_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_MODEL_PROVIDERS))
        raise ConfigError(f"Unsupported model provider: {config.model.provider}. Supported providers: {supported}.")
    if config.runtime.max_iterations < 1:
        raise ConfigError("[runtime].max_iterations must be at least 1.")
    if config.runtime.timeout_seconds is not None and config.runtime.timeout_seconds <= 0:
        raise ConfigError("[runtime].timeout_seconds must be greater than 0.")

    available = set(available_builtin_tool_names())
    unknown_tools = [name for name in config.tools.enabled if name not in available]
    if unknown_tools:
        raise ConfigError(
            "Unknown tool(s) in [tools].enabled: "
            f"{', '.join(unknown_tools)}. Available tools: {', '.join(sorted(available))}."
        )
    return config


def _model_settings(data: dict[str, Any]) -> ModelSettings:
    known = {
        "provider",
        "model",
        "base_url",
        "chat_completions_path",
        "completions_url",
        "temperature",
        "max_tokens",
        "top_p",
        "metadata",
    }
    metadata = dict(_table(data, "metadata"))
    for key, value in data.items():
        if key not in known:
            metadata[key] = value
    return ModelSettings(
        provider=str(data.get("provider", "openai")),
        model=_optional_str(data.get("model")),
        base_url=_optional_str(data.get("base_url")),
        chat_completions_path=_optional_str(data.get("chat_completions_path")),
        completions_url=_optional_str(data.get("completions_url")),
        temperature=_optional_float(data.get("temperature")),
        max_tokens=_optional_int(data.get("max_tokens")),
        top_p=_optional_float(data.get("top_p")),
        metadata=metadata,
    )


def _runtime_settings(data: dict[str, Any]) -> RuntimeSettings:
    max_iterations = _optional_int(data.get("max_iterations"))
    return RuntimeSettings(
        max_iterations=20 if max_iterations is None else max_iterations,
        timeout_seconds=_optional_float(data.get("timeout_seconds")),
        stream_tokens=bool(data.get("stream_tokens", True)),
        metadata=dict(_table(data, "metadata")),
    )


def _workspace_settings(data: dict[str, Any]) -> WorkspaceSettings:
    return WorkspaceSettings(
        root=str(data.get("root", ".")),
        read=_permission_mode(data.get("read", True), "read"),
        write=_permission_mode(data.get("write", False), "write"),
    )


def _tools_settings(data: dict[str, Any]) -> ToolsSettings:
    enabled = data.get("enabled")
    if enabled is None:
        return ToolsSettings()
    if not isinstance(enabled, list):
        raise ValueError("[tools].enabled must be a list of tool names.")
    return ToolsSettings(enabled=[str(name) for name in enabled])


def _check_unknown_tables(data: dict[str, Any]) -> None:
    known = {"model", "runtime", "workspace", "tools"}
    unknown = sorted(key for key in data if key not in known)
    if unknown:
        raise ConfigError(f"Unknown top-level config table(s): {', '.join(unknown)}.")


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{key}] must be a TOML table.")
    return value


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _permission_mode(value: Any, key: str) -> bool | str:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value in {"allow", "deny", "ask"}:
        return value
    raise ConfigError(f"[workspace].{key} must be true, false, \"allow\", \"deny\", or \"ask\".")
