"""Minimal streaming agent loop."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sisyphus.capabilities import FileSystemCapability
from sisyphus.core.context import RuntimeContext
from sisyphus.core.events import RuntimeEvent, RuntimeEventEmitter
from sisyphus.core.messages import ContentBlock, Message, TextBlock, ToolCallBlock, ToolResultBlock
from sisyphus.core.options import RunOptions
from sisyphus.core.results import RunResult
from sisyphus.models import ModelConfig, ModelProvider
from sisyphus.permissions import AllowAllPolicy, PermissionPolicy
from sisyphus.tools import Tool, ToolRegistry, ToolResult


class AgentRuntime:
    def __init__(
        self,
        model: ModelProvider,
        tools: list[Tool] | ToolRegistry | None = None,
        permissions: PermissionPolicy | None = None,
        system_prompt: str | None = None,
        config: ModelConfig | None = None,
    ) -> None:
        self.model = model
        self.tools = tools if isinstance(tools, ToolRegistry) else ToolRegistry(tools)
        self.permissions = permissions or AllowAllPolicy()
        self.system_prompt = system_prompt
        self.config = config

    async def run(
        self,
        input: str | list[Message],
        *,
        context: RuntimeContext | None = None,
        options: RunOptions | None = None,
    ) -> RunResult:
        events = [event async for event in self.stream(input, context=context, options=options)]
        completed = next((event for event in reversed(events) if event.type == "run.completed"), None)
        messages = []
        if completed is not None:
            messages = [_message_from_dict(item) for item in completed.data.get("messages", [])]
        run_id = events[0].run_id if events else None
        return RunResult(messages=messages, events=events, run_id=run_id)

    async def stream(
        self,
        input: str | list[Message],
        *,
        context: RuntimeContext | None = None,
        options: RunOptions | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        resolved_options = options or RunOptions()
        if resolved_options.timeout_seconds is None:
            async for event in self._stream_impl(input, context=context, options=resolved_options):
                yield event
            return

        async with asyncio.timeout(resolved_options.timeout_seconds):
            async for event in self._stream_impl(input, context=context, options=resolved_options):
                yield event

    async def _stream_impl(
        self,
        input: str | list[Message],
        *,
        context: RuntimeContext | None,
        options: RunOptions,
    ) -> AsyncIterator[RuntimeEvent]:
        run_id = options.run_id or str(uuid.uuid4())
        emitter = RuntimeEventEmitter(run_id)
        delivered = 0
        messages = _normalize_input(input)
        ctx = context or self._default_context(emitter, metadata=options.metadata)

        async def emit(event_type: str, data: dict[str, Any] | None = None) -> RuntimeEvent:
            nonlocal delivered
            event = await emitter.emit(event_type, data)
            delivered = len(emitter.events)
            return event

        async def pending_events() -> list[RuntimeEvent]:
            nonlocal delivered
            events = emitter.events[delivered:]
            delivered = len(emitter.events)
            return events

        try:
            yield await emit("run.started", {"messages": [_message_to_dict(message) for message in messages]})

            for iteration in range(options.max_iterations):
                assistant_blocks: list[ContentBlock] = []
                async for delta in self.model.stream(
                    messages,
                    self.tools.specs(),
                    system=self.system_prompt,
                    config=self.config,
                ):
                    assistant_blocks.extend(delta.content)
                    if delta.content and options.stream_tokens:
                        yield await emit(
                            "message.delta",
                            {
                                "iteration": iteration,
                                "content": [_block_to_dict(block) for block in delta.content],
                                "finish_reason": delta.finish_reason,
                            },
                        )

                assistant_message = Message(role="assistant", content=assistant_blocks)
                messages.append(assistant_message)
                yield await emit(
                    "message.completed",
                    {"iteration": iteration, "message": _message_to_dict(assistant_message)},
                )

                tool_calls = [block for block in assistant_blocks if isinstance(block, ToolCallBlock)]
                if not tool_calls:
                    yield await emit(
                        "run.completed",
                        {"iterations": iteration + 1, "messages": [_message_to_dict(message) for message in messages]},
                    )
                    return

                tool_results: list[ToolResultBlock] = []
                for call in tool_calls:
                    events, result = await self._execute_tool_call(call, ctx, emitter, pending_events)
                    for event in events:
                        yield event
                    tool_results.append(result)

                messages.append(Message(role="tool", content=tool_results))

            yield await emit(
                "run.failed",
                {
                    "message": "Maximum iterations reached.",
                    "code": "max_iterations",
                    "messages": [_message_to_dict(message) for message in messages],
                },
            )
        except Exception as exc:
            yield await emit("run.failed", {"message": str(exc), "code": exc.__class__.__name__})
            raise

    async def _execute_tool_call(
        self,
        call: ToolCallBlock,
        ctx: RuntimeContext,
        emitter: RuntimeEventEmitter,
        pending_events,
    ) -> tuple[list[RuntimeEvent], ToolResultBlock]:
        events: list[RuntimeEvent] = []
        await emitter.emit("tool.started", {"id": call.id, "name": call.name, "arguments": call.arguments})
        events.extend(await pending_events())

        tool = self.tools.get(call.name)
        if tool is None:
            result = ToolResult(content=f"Tool not found: {call.name}", is_error=True)
            block = ToolResultBlock(tool_call_id=call.id, content=result.content, is_error=True)
            await emitter.emit("tool.failed", {"id": call.id, "name": call.name, "message": result.content})
            events.extend(await pending_events())
            return events, block

        try:
            result = await tool.execute(ctx, **call.arguments)
            block = ToolResultBlock(tool_call_id=call.id, content=result.content, is_error=result.is_error)
            event_type = "tool.failed" if result.is_error else "tool.completed"
            await emitter.emit(
                event_type,
                {"id": call.id, "name": call.name, "result": _tool_result_to_dict(result)},
            )
        except Exception as exc:
            block = ToolResultBlock(tool_call_id=call.id, content=str(exc), is_error=True)
            await emitter.emit("tool.failed", {"id": call.id, "name": call.name, "message": str(exc)})

        events.extend(await pending_events())
        return events, block

    def _default_context(self, events: RuntimeEventEmitter, *, metadata: dict[str, Any]) -> RuntimeContext:
        cwd = Path.cwd()
        fs = FileSystemCapability(cwd, self.permissions, events)
        return RuntimeContext(cwd=cwd, fs=fs, events=events, metadata=dict(metadata))


def _normalize_input(input: str | list[Message]) -> list[Message]:
    if isinstance(input, str):
        return [Message.text("user", input)]
    return list(input)


def _block_to_dict(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolCallBlock):
        return {"type": "tool_call", "id": block.id, "name": block.name, "arguments": block.arguments}
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_call_id": block.tool_call_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    raise TypeError(f"Unsupported content block: {block!r}")


def _message_to_dict(message: Message) -> dict[str, Any]:
    return {"role": message.role, "content": [_block_to_dict(block) for block in message.content]}


def _message_from_dict(data: dict[str, Any]) -> Message:
    return Message(role=data["role"], content=[_block_from_dict(block) for block in data.get("content", [])])


def _block_from_dict(data: dict[str, Any]) -> ContentBlock:
    block_type = data.get("type")
    if block_type == "text":
        return TextBlock(text=data.get("text", ""))
    if block_type == "tool_call":
        return ToolCallBlock(id=data.get("id", ""), name=data.get("name", ""), arguments=data.get("arguments", {}))
    if block_type == "tool_result":
        return ToolResultBlock(
            tool_call_id=data.get("tool_call_id", ""),
            content=data.get("content", ""),
            is_error=bool(data.get("is_error", False)),
        )
    raise ValueError(f"Unsupported content block type: {block_type}")


def _tool_result_to_dict(result: ToolResult) -> dict[str, Any]:
    return {"content": result.content, "is_error": result.is_error, "metadata": result.metadata}
