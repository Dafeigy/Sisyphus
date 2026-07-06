"""Thin command-line host for Sisyphus."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from sisyphus.capabilities import FileSystemCapability
from sisyphus import AgentRuntime
from sisyphus.core import RunOptions
from sisyphus.config import ConfigError, SisyphusConfig, discover_config_path, load_config, validate_config
from sisyphus.models import ModelConfig, OpenAIProvider
from sisyphus.permissions import WorkspacePolicy
from sisyphus.tools import builtin_tools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sps")
    parser.add_argument("--config", help="Optional TOML config file.")
    parser.add_argument("--message", "-m", help="Message to send to the runtime.")
    parser.add_argument("--cwd", default=None, help="Workspace root for permission-aware tools.")
    parser.add_argument("--model", default=None, help="OpenAI-compatible model name.")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible base URL.")
    parser.add_argument("--completions-url", default=None, help="Exact chat completions endpoint.")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--check", action="store_true", help="Validate config and CLI setup without running a message.")
    parser.add_argument("command", nargs="?", choices=["chat"], help="Start an interactive chat session.")
    return parser


def resolve_config(args: argparse.Namespace) -> SisyphusConfig:
    path = args.config or discover_config_path()
    return load_config(path)


def build_runtime(args: argparse.Namespace, config: SisyphusConfig) -> AgentRuntime:
    validate_config(config)
    model_settings = config.model
    if model_settings.provider != "openai":
        raise ConfigError(f"Unsupported model provider: {model_settings.provider}")

    provider = OpenAIProvider(
        model=args.model or model_settings.model or os.getenv("OPENAI_MODEL", "gpt-4.1"),
        base_url=args.base_url or model_settings.base_url,
        chat_completions_path=model_settings.chat_completions_path,
        completions_url=args.completions_url or model_settings.completions_url,
    )
    root = Path(args.cwd or config.workspace.root).resolve()
    model_config = ModelConfig(
        temperature=model_settings.temperature,
        max_tokens=model_settings.max_tokens,
        top_p=model_settings.top_p,
        metadata=dict(model_settings.metadata),
    )
    return AgentRuntime(
        model=provider,
        tools=builtin_tools(config.tools.enabled),
        permissions=WorkspacePolicy(root=root, read=config.workspace.read, write=config.workspace.write),
        config=model_config,
        cwd=root,
    )


def build_run_options(args: argparse.Namespace, config: SisyphusConfig) -> RunOptions:
    return RunOptions(
        max_iterations=args.max_iterations if args.max_iterations is not None else config.runtime.max_iterations,
        timeout_seconds=config.runtime.timeout_seconds,
        stream_tokens=config.runtime.stream_tokens,
        metadata=dict(config.runtime.metadata),
    )


async def run_once(args: argparse.Namespace) -> int:
    config = resolve_config(args)
    runtime = build_runtime(args, config)
    options = build_run_options(args, config)
    failed = False
    wrote_text = False
    async for event in runtime.stream(args.message, options=options):
        if event.type == "message.delta":
            for block in event.data.get("content", []):
                if block.get("type") == "text" and block.get("text"):
                    print(block["text"], end="", flush=True)
                    wrote_text = True
        elif event.type == "tool.started":
            if wrote_text:
                print()
                wrote_text = False
            print(f"[tool] {event.data.get('name')} started", file=sys.stderr)
        elif event.type == "tool.completed":
            print(f"[tool] {event.data.get('name')} completed", file=sys.stderr)
        elif event.type == "tool.failed":
            message = event.data.get("message", "Tool failed.")
            code = event.data.get("code", "tool_failed")
            print(f"[tool] {code}: {message}", file=sys.stderr)
        elif event.type == "run.failed":
            if wrote_text:
                print()
                wrote_text = False
            message = event.data.get("message", "Run failed.")
            code = event.data.get("code", "run_failed")
            print(f"[run] {code}: {message}", file=sys.stderr)
            failed = True
    if wrote_text:
        print()
    return 1 if failed else 0


def check_config(args: argparse.Namespace) -> int:
    config = resolve_config(args)
    runtime = build_runtime(args, config)
    options = build_run_options(args, config)
    workspace = runtime.cwd or Path.cwd()
    if not workspace.exists():
        raise ConfigError(f"Workspace root does not exist: {workspace}")
    if not workspace.is_dir():
        raise ConfigError(f"Workspace root is not a directory: {workspace}")
    # Build the default filesystem capability once so workspace path and policy setup are validated together.
    FileSystemCapability(workspace, runtime.permissions, events=_NullEventSink())
    print(
        "Configuration OK "
        f"(model={runtime.model.model}, tools={len(runtime.tools.specs())}, max_iterations={options.max_iterations})"
    )
    return 0


async def chat(args: argparse.Namespace) -> int:
    while True:
        try:
            message = input("> ")
        except EOFError:
            return 0
        if not message.strip():
            continue
        if message.strip() in {"exit", "quit"}:
            return 0
        args.message = message
        await run_once(args)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.check:
        try:
            return check_config(args)
        except (ConfigError, ValueError) as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            return 2
    if args.command == "chat":
        try:
            return asyncio.run(chat(args))
        except (ConfigError, ValueError) as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            return 2
    if not args.message:
        parser.error("--message is required unless using `sps chat`.")
    try:
        return asyncio.run(run_once(args))
    except (ConfigError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2


class _NullEventSink:
    async def emit(self, event_type, data=None):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
