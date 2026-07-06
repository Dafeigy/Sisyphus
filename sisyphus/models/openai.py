"""OpenAI-compatible chat completions provider."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import AsyncIterator, Iterable
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sisyphus.core.messages import ContentBlock, Message, TextBlock, ToolCallBlock, ToolResultBlock
from sisyphus.models.base import ModelConfig, ModelResponse, ModelStreamDelta, ToolSpec


class OpenAIProviderError(RuntimeError):
    """Raised when an OpenAI-compatible provider returns an invalid response."""


class OpenAIProvider:
    """Provider for OpenAI-compatible `/chat/completions` APIs.

    The implementation intentionally uses the Python standard library so the
    first runtime phase does not take a hard dependency on a specific HTTP SDK.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        chat_completions_path: str | None = None,
        completions_url: str | None = None,
        timeout: float = 60.0,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or ""
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.chat_completions_path = (
            chat_completions_path
            if chat_completions_path is not None
            else os.getenv("OPENAI_CHAT_COMPLETIONS_PATH", "/chat/completions")
        )
        self.completions_url = completions_url or os.getenv("OPENAI_CHAT_COMPLETIONS_URL")
        self.timeout = timeout
        self.default_headers = dict(default_headers or {})

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        config: ModelConfig | None = None,
    ) -> ModelResponse:
        payload = self._build_payload(messages, tools or [], system=system, config=config, stream=False)
        data = await asyncio.to_thread(self._post_json, payload)
        return self._parse_response(data)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        system: str | None = None,
        config: ModelConfig | None = None,
    ) -> AsyncIterator[ModelStreamDelta]:
        payload = self._build_payload(messages, tools or [], system=system, config=config, stream=True)
        queue: asyncio.Queue[ModelStreamDelta | BaseException | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        stop_event = threading.Event()

        def worker() -> None:
            try:
                for event in self._post_sse(payload):
                    if stop_event.is_set():
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, self._parse_stream_event(event))
            except BaseException as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            stop_event.set()
            await task

    def _build_payload(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str | None,
        config: ModelConfig | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._serialize_messages(messages, system=system),
            "stream": stream,
        }
        if tools:
            payload["tools"] = [self._serialize_tool(tool) for tool in tools]
        if config is not None:
            if config.temperature is not None:
                payload["temperature"] = config.temperature
            if config.max_tokens is not None:
                payload["max_tokens"] = config.max_tokens
            if config.top_p is not None:
                payload["top_p"] = config.top_p
            payload.update(config.metadata)
        return payload

    def _serialize_messages(self, messages: list[Message], *, system: str | None) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        if system:
            serialized.append({"role": "system", "content": system})

        for message in messages:
            if message.role == "tool":
                serialized.extend(self._serialize_tool_result_messages(message.content))
                continue

            text = "".join(block.text for block in message.content if isinstance(block, TextBlock))
            item: dict[str, Any] = {"role": message.role, "content": text}
            tool_calls = [block for block in message.content if isinstance(block, ToolCallBlock)]
            if tool_calls:
                item["tool_calls"] = [self._serialize_tool_call(block) for block in tool_calls]
            serialized.append(item)
        return serialized

    def _serialize_tool_result_messages(self, blocks: Iterable[ContentBlock]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, ToolResultBlock):
                continue
            content = block.content if isinstance(block.content, str) else json.dumps(block.content)
            results.append({"role": "tool", "tool_call_id": block.tool_call_id, "content": content})
        return results

    def _serialize_tool_call(self, block: ToolCallBlock) -> dict[str, Any]:
        return {
            "id": block.id,
            "type": "function",
            "function": {"name": block.name, "arguments": json.dumps(block.arguments)},
        }

    def _serialize_tool(self, tool: ToolSpec) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(self._completions_url(), data=body, headers=self._headers("application/json"), method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise OpenAIProviderError(self._read_http_error(exc)) from exc

    def _post_sse(self, payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(self._completions_url(), data=body, headers=self._headers("text/event-stream"), method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                for line in response:
                    decoded = line.decode("utf-8").strip()
                    if not decoded or decoded.startswith(":") or not decoded.startswith("data:"):
                        continue
                    data = decoded.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    yield json.loads(data)
        except HTTPError as exc:
            raise OpenAIProviderError(self._read_http_error(exc)) from exc

    def _headers(self, accept: str) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "Content-Type": "application/json",
            **self.default_headers,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _completions_url(self) -> str:
        if self.completions_url:
            return self.completions_url
        if not self.chat_completions_path:
            return self.base_url
        return f"{self.base_url}/{self.chat_completions_path.lstrip('/')}"

    def _read_http_error(self, exc: HTTPError) -> str:
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = ""
        return f"Provider request failed with HTTP {exc.code}: {body or exc.reason}"

    def _parse_response(self, data: dict[str, Any]) -> ModelResponse:
        choices = data.get("choices") or []
        if not choices:
            raise OpenAIProviderError("Provider response did not include choices.")
        choice = choices[0]
        message = choice.get("message") or {}
        return ModelResponse(
            content=self._parse_message_content(message),
            raw=data,
            model=data.get("model"),
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage"),
        )

    def _parse_message_content(self, message: dict[str, Any]) -> list[ContentBlock]:
        blocks: list[ContentBlock] = []
        text = message.get("content")
        if text:
            blocks.append(TextBlock(text=text))
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            blocks.append(
                ToolCallBlock(
                    id=call.get("id", ""),
                    name=function.get("name", ""),
                    arguments=self._loads_arguments(function.get("arguments")),
                )
            )
        return blocks

    def _parse_stream_event(self, data: dict[str, Any]) -> ModelStreamDelta:
        choices = data.get("choices") or []
        if not choices:
            return ModelStreamDelta(raw=data, model=data.get("model"), usage=data.get("usage"))
        choice = choices[0]
        delta = choice.get("delta") or {}
        blocks: list[ContentBlock] = []
        if delta.get("content"):
            blocks.append(TextBlock(text=delta["content"]))
        for call in delta.get("tool_calls") or []:
            function = call.get("function") or {}
            blocks.append(
                ToolCallBlock(
                    id=call.get("id", ""),
                    name=function.get("name", ""),
                    arguments=self._loads_arguments(function.get("arguments")),
                )
            )
        return ModelStreamDelta(
            content=blocks,
            raw=data,
            model=data.get("model"),
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage"),
        )

    def _loads_arguments(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"_raw": value}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
