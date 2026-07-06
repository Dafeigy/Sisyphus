from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from sisyphus import AgentRuntime
from sisyphus.capabilities import FileSystemCapability
from sisyphus.core import Message, RunOptions, RuntimeContext, TextBlock, ToolCallBlock
from sisyphus.core.events import RuntimeEventEmitter
from sisyphus.models import ModelResponse, ModelStreamDelta
from sisyphus.permissions import WorkspacePolicy
from sisyphus.tools import MockTool, builtin_tools


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


if __name__ == "__main__":
    unittest.main()
