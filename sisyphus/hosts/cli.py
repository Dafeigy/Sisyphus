"""Thin command-line host for Sisyphus."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from sisyphus import AgentRuntime
from sisyphus.core import RunOptions
from sisyphus.models import OpenAIProvider
from sisyphus.permissions import WorkspacePolicy
from sisyphus.tools import builtin_tools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sps")
    parser.add_argument("--message", "-m", help="Message to send to the runtime.")
    parser.add_argument("--cwd", default=".", help="Workspace root for permission-aware tools.")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4.1"), help="OpenAI-compatible model name.")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible base URL.")
    parser.add_argument("--completions-url", default=None, help="Exact chat completions endpoint.")
    parser.add_argument("--max-iterations", type=int, default=20)
    parser.add_argument("command", nargs="?", choices=["chat"], help="Start an interactive chat session.")
    return parser


async def run_once(args: argparse.Namespace) -> int:
    provider = OpenAIProvider(
        model=args.model,
        base_url=args.base_url,
        completions_url=args.completions_url,
    )
    root = Path(args.cwd).resolve()
    runtime = AgentRuntime(
        model=provider,
        tools=builtin_tools(["list_files", "read_file", "mock_lookup", "echo"]),
        permissions=WorkspacePolicy(root=root, read=True, write=False),
    )
    failed = False
    wrote_text = False
    async for event in runtime.stream(args.message, options=RunOptions(max_iterations=args.max_iterations)):
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
    if args.command == "chat":
        return asyncio.run(chat(args))
    if not args.message:
        parser.error("--message is required unless using `sps chat`.")
    return asyncio.run(run_once(args))


if __name__ == "__main__":
    raise SystemExit(main())
