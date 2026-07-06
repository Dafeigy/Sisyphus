from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from sisyphus import AgentRuntime
from sisyphus.capabilities import FileSystemCapability
from sisyphus.core import Message, RunOptions, RuntimeContext, TextBlock, ToolCallBlock
from sisyphus.core.events import RuntimeEventEmitter
from sisyphus.models import ModelResponse, ModelStreamDelta
from sisyphus.permissions import WorkspacePolicy
from sisyphus.tools import MockTool, ToolResult, builtin_tools


class ScriptedModel:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def complete(self, messages, tools, *, system=None, config=None):
        return ModelResponse(content=[])

    async def stream(self, messages, tools, *, system=None, config=None):
        self.calls.append({"messages": list(messages), "tools": list(tools), "system": system, "config": config})
        for delta in self.outputs.pop(0):
            yield delta


class FailingModel:
    async def complete(self, messages, tools, *, system=None, config=None):
        return ModelResponse(content=[])

    async def stream(self, messages, tools, *, system=None, config=None):
        raise RuntimeError("provider exploded")
        yield


class ExplodingTool:
    name = "explode"
    description = "Raise an exception."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, ctx: RuntimeContext, **kwargs: Any) -> ToolResult:
        raise ValueError("boom")


class RuntimeTests(unittest.TestCase):
    def test_run_aggregates_streamed_text(self) -> None:
        model = ScriptedModel([[ModelStreamDelta(content=[TextBlock("hel")]), ModelStreamDelta(content=[TextBlock("lo")])]])
        runtime = AgentRuntime(model=model)

        result = asyncio.run(runtime.run("hi", options=RunOptions(run_id="run-1")))

        self.assertEqual(result.run_id, "run-1")
        self.assertEqual(result.text, "hello")
        self.assertEqual([event.type for event in result.events], [
            "run.started",
            "message.delta",
            "message.delta",
            "message.completed",
            "run.completed",
        ])
        self.assertEqual([event.sequence for event in result.events], [0, 1, 2, 3, 4])

    def test_runtime_executes_tool_calls_and_continues_loop(self) -> None:
        model = ScriptedModel(
            [
                [ModelStreamDelta(content=[ToolCallBlock("call-1", "mock_lookup", {"query": "x"})])],
                [ModelStreamDelta(content=[TextBlock("done")])],
            ]
        )
        runtime = AgentRuntime(
            model=model,
            tools=[MockTool(name="mock_lookup", description="Lookup", response={"answer": 42})],
        )

        result = asyncio.run(runtime.run([Message.text("user", "lookup x")], options=RunOptions(run_id="tools")))

        self.assertEqual(result.text, "done")
        self.assertEqual([event.type for event in result.events], [
            "run.started",
            "message.delta",
            "message.completed",
            "tool.started",
            "tool.completed",
            "message.delta",
            "message.completed",
            "run.completed",
        ])
        self.assertEqual(model.calls[0]["tools"][0].name, "mock_lookup")
        self.assertEqual(model.calls[1]["messages"][-1].role, "tool")

    def test_filesystem_capability_emits_permission_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("hello", encoding="utf-8")
            emitter = RuntimeEventEmitter("fs")
            policy = WorkspacePolicy(root=root, read=True, write=False)
            fs = FileSystemCapability(root, policy, emitter)
            ctx = RuntimeContext(cwd=root, fs=fs, events=emitter)

            content = asyncio.run(ctx.fs.read_text("README.md"))

        self.assertEqual(content, "hello")
        self.assertEqual([event.type for event in emitter.events], ["permission.requested", "permission.resolved"])
        self.assertTrue(emitter.events[-1].data["decision"]["allowed"])

    def test_builtin_read_file_tool_uses_runtime_context_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("mock content", encoding="utf-8")
            emitter = RuntimeEventEmitter("tool-fs")
            policy = WorkspacePolicy(root=root, read=True, write=False)
            fs = FileSystemCapability(root, policy, emitter)
            ctx = RuntimeContext(cwd=root, fs=fs, events=emitter)
            tool = builtin_tools(["read_file"])[0]

            result = asyncio.run(tool.execute(ctx, path="note.txt"))

        self.assertEqual(result.content, "mock content")
        self.assertEqual([event.type for event in emitter.events], ["permission.requested", "permission.resolved"])

    def test_unknown_tool_emits_failed_event_and_tool_result(self) -> None:
        model = ScriptedModel(
            [
                [ModelStreamDelta(content=[ToolCallBlock("call-1", "missing_tool", {"query": "x"})])],
                [ModelStreamDelta(content=[TextBlock("done")])],
            ]
        )
        runtime = AgentRuntime(model=model)

        result = asyncio.run(runtime.run("use missing", options=RunOptions(run_id="unknown-tool")))

        failed = next(event for event in result.events if event.type == "tool.failed")
        self.assertEqual(failed.data["code"], "unknown_tool")
        self.assertEqual(failed.data["details"], {"id": "call-1", "name": "missing_tool"})
        self.assertTrue(failed.data["recoverable"])
        tool_message = model.calls[1]["messages"][-1]
        self.assertEqual(tool_message.role, "tool")
        self.assertTrue(tool_message.content[0].is_error)

    def test_tool_exception_emits_failed_event_and_continues_loop(self) -> None:
        model = ScriptedModel(
            [
                [ModelStreamDelta(content=[ToolCallBlock("call-1", "explode", {})])],
                [ModelStreamDelta(content=[TextBlock("done")])],
            ]
        )
        runtime = AgentRuntime(model=model, tools=[ExplodingTool()])

        result = asyncio.run(runtime.run("explode", options=RunOptions(run_id="tool-exception")))

        self.assertEqual(result.text, "done")
        failed = next(event for event in result.events if event.type == "tool.failed")
        self.assertEqual(failed.data["code"], "tool_exception")
        self.assertEqual(failed.data["message"], "boom")
        self.assertEqual(failed.data["details"]["exception_type"], "ValueError")
        self.assertTrue(model.calls[1]["messages"][-1].content[0].is_error)

    def test_permission_denied_produces_serializable_failed_event(self) -> None:
        model = ScriptedModel(
            [
                [ModelStreamDelta(content=[ToolCallBlock("call-1", "read_file", {"path": "README.md"})])],
                [ModelStreamDelta(content=[TextBlock("done")])],
            ]
        )
        runtime = AgentRuntime(
            model=model,
            tools=builtin_tools(["read_file"]),
            permissions=WorkspacePolicy(root=Path.cwd(), read=False, write=False),
        )

        result = asyncio.run(runtime.run("read", options=RunOptions(run_id="permission-denied")))

        failed = next(event for event in result.events if event.type == "tool.failed")
        self.assertEqual(failed.data["code"], "permission_denied")
        self.assertEqual(failed.data["details"]["exception_type"], "PermissionDeniedError")
        json.dumps(failed.to_dict())

    def test_max_iterations_emits_run_failed(self) -> None:
        model = ScriptedModel([[ModelStreamDelta(content=[ToolCallBlock("call-1", "missing_tool", {})])]])
        runtime = AgentRuntime(model=model)

        result = asyncio.run(runtime.run("loop", options=RunOptions(run_id="max", max_iterations=1)))

        failed = result.events[-1]
        self.assertEqual(failed.type, "run.failed")
        self.assertEqual(failed.data["code"], "max_iterations")
        self.assertFalse(failed.data["recoverable"])
        json.dumps(failed.to_dict())

    def test_provider_failure_emits_run_failed(self) -> None:
        runtime = AgentRuntime(model=FailingModel())

        result = asyncio.run(runtime.run("fail", options=RunOptions(run_id="provider-failure")))

        self.assertEqual([event.type for event in result.events], ["run.started", "run.failed"])
        failed = result.events[-1]
        self.assertEqual(failed.data["code"], "provider_error")
        self.assertEqual(failed.data["details"]["exception_type"], "RuntimeError")
        self.assertFalse(failed.data["recoverable"])

    def test_stream_tokens_false_suppresses_deltas_but_completes_message(self) -> None:
        model = ScriptedModel([[ModelStreamDelta(content=[TextBlock("hel")]), ModelStreamDelta(content=[TextBlock("lo")])]])
        runtime = AgentRuntime(model=model)

        result = asyncio.run(runtime.run("hi", options=RunOptions(run_id="quiet", stream_tokens=False)))

        self.assertEqual(result.text, "hello")
        self.assertEqual([event.type for event in result.events], ["run.started", "message.completed", "run.completed"])


if __name__ == "__main__":
    unittest.main()
