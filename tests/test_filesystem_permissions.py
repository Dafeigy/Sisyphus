from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from sisyphus import AgentRuntime
from sisyphus.capabilities import FileSystemCapability, PermissionDeniedError
from sisyphus.core import RunOptions, RuntimeContext, TextBlock, ToolCallBlock
from sisyphus.core.events import RuntimeEventEmitter
from sisyphus.models import ModelStreamDelta
from sisyphus.permissions import ApprovalDecision, ApprovalPermissionPolicy, WorkspacePolicy
from sisyphus.tools import builtin_tools


class ScriptedModel:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    async def complete(self, messages, tools, *, system=None, config=None):
        raise NotImplementedError

    async def stream(self, messages, tools, *, system=None, config=None):
        for delta in self.outputs.pop(0):
            yield delta


class FilesystemPermissionTests(unittest.TestCase):
    def test_filesystem_approval_allows_single_read_without_remembering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("hello", encoding="utf-8")
            calls = []

            def approve(request, decision):
                calls.append(request)
                return ApprovalDecision(True, "approved once", remember=False)

            policy = ApprovalPermissionPolicy(WorkspacePolicy(root=root, read="ask"), approve)
            emitter = RuntimeEventEmitter("approval-once")
            fs = FileSystemCapability(root, policy, emitter)

            first = asyncio.run(fs.read_text("note.txt"))
            second = asyncio.run(fs.read_text("note.txt"))

        self.assertEqual(first, "hello")
        self.assertEqual(second, "hello")
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [event.type for event in emitter.events],
            [
                "permission.requested",
                "permission.approval_requested",
                "permission.approval_resolved",
                "permission.resolved",
                "permission.requested",
                "permission.approval_requested",
                "permission.approval_resolved",
                "permission.resolved",
            ],
        )

    def test_filesystem_approval_can_be_remembered_for_same_resource(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("hello", encoding="utf-8")
            calls = []

            def approve(request, decision):
                calls.append(request)
                return ApprovalDecision(True, "always allow this file", remember=True)

            policy = ApprovalPermissionPolicy(WorkspacePolicy(root=root, read="ask"), approve)
            emitter = RuntimeEventEmitter("approval-remember")
            fs = FileSystemCapability(root, policy, emitter)

            asyncio.run(fs.read_text("note.txt"))
            asyncio.run(fs.read_text("note.txt"))

        self.assertEqual(len(calls), 1)
        self.assertTrue(emitter.events[-1].data["decision"]["allowed"])
        self.assertEqual(emitter.events[-1].data["decision"]["reason"], "Approved by remembered permission.")

    def test_filesystem_approval_denial_blocks_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("hello", encoding="utf-8")
            policy = ApprovalPermissionPolicy(
                WorkspacePolicy(root=root, read="ask"),
                lambda request, decision: ApprovalDecision(False, "no"),
            )
            fs = FileSystemCapability(root, policy, RuntimeEventEmitter("approval-deny"))

            with self.assertRaises(PermissionDeniedError):
                asyncio.run(fs.read_text("note.txt"))

    def test_read_file_tool_supports_max_chars_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "long.txt").write_text("abcdef", encoding="utf-8")
            emitter = RuntimeEventEmitter("read-tool")
            policy = WorkspacePolicy(root=root, read=True)
            fs = FileSystemCapability(root, policy, emitter)
            ctx = RuntimeContext(cwd=root, fs=fs, events=emitter)
            tool = builtin_tools(["read_file"])[0]

            result = asyncio.run(tool.execute(ctx, path="long.txt", max_chars=3))

        self.assertEqual(result.content, "abc")
        self.assertEqual(result.metadata["chars"], 3)
        self.assertTrue(result.metadata["truncated"])

    def test_write_file_tool_supports_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("a", encoding="utf-8")
            emitter = RuntimeEventEmitter("write-tool")
            policy = WorkspacePolicy(root=root, write=True)
            fs = FileSystemCapability(root, policy, emitter)
            ctx = RuntimeContext(cwd=root, fs=fs, events=emitter)
            tool = builtin_tools(["write_file"])[0]

            result = asyncio.run(tool.execute(ctx, path="note.txt", content="b", append=True))
            content = (root / "note.txt").read_text(encoding="utf-8")

        self.assertEqual(content, "ab")
        self.assertTrue(result.content["written"])
        self.assertTrue(result.content["append"])

    def test_runtime_permission_request_includes_tool_call_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("hello", encoding="utf-8")
            model = ScriptedModel(
                [
                    [ModelStreamDelta(content=[ToolCallBlock("call-1", "read_file", {"path": "note.txt"})])],
                    [ModelStreamDelta(content=[TextBlock("done")])],
                ]
            )
            runtime = AgentRuntime(
                model=model,
                tools=builtin_tools(["read_file"]),
                permissions=WorkspacePolicy(root=root, read=True),
                cwd=root,
            )

            result = asyncio.run(runtime.run("read", options=RunOptions(run_id="tool-details")))

        requested = next(event for event in result.events if event.type == "permission.requested")
        self.assertEqual(requested.data["request"]["details"]["tool"], {"id": "call-1", "name": "read_file"})


if __name__ == "__main__":
    unittest.main()
