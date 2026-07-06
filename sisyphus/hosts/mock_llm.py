"""Development OpenAI-compatible mock LLM server.

This module intentionally lives in ``hosts`` and imports FastAPI only inside
``create_app()`` so the core runtime does not gain a web-framework dependency.
"""

import argparse
import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any


DEFAULT_MODEL = "sisyphus-mock-model"
DEFAULT_PORT = 8881
SCENARIO_AUTO = "auto"
SCENARIO_MESSAGE = "message"
SCENARIO_TOOL_CALL = "tool_call"
SCENARIO_TEXT_AND_TOOL_CALL = "text_and_tool_call"
SCENARIO_MULTIPLE_TOOL_CALLS = "multiple_tool_calls"


def create_app():
    """Create a FastAPI app that exposes OpenAI-compatible chat completions."""

    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse, StreamingResponse
    except ImportError as exc:  # pragma: no cover - depends on optional extras
        raise RuntimeError(
            "The mock LLM server requires FastAPI. Install runtime server dependencies with "
            "`pip install fastapi \"uvicorn[standard]\"`."
        ) from exc

    app = FastAPI(title="Sisyphus Mock LLM", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/")
    @app.post("/chat/completions")
    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        payload = await request.json()
        response = build_chat_completion(payload)
        if payload.get("stream"):
            return StreamingResponse(
                iter_sse(response, delay_seconds=float(payload.get("mock_delay_seconds", 0.02))),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache"},
            )
        return JSONResponse(build_non_stream_response(payload, response))

    return app


def build_chat_completion(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a simple assistant response from an OpenAI-compatible payload."""

    messages = list(payload.get("messages") or [])
    if _last_role(messages) == "tool":
        return {
            "kind": "text",
            "content": _summarize_tool_results(messages),
            "finish_reason": "stop",
        }

    scenario = str(payload.get("mock_scenario") or SCENARIO_AUTO)
    if scenario != SCENARIO_AUTO:
        return _response_for_scenario(scenario, payload)

    prompt = _last_user_text(messages)
    calls = _select_tool_calls(prompt, _available_tool_names(payload))
    if calls:
        return {
            "kind": "tool_calls",
            "content": "I will use the available workspace tools.\n",
            "tool_calls": calls,
            "finish_reason": "tool_calls",
        }

    return {
        "kind": "text",
        "content": (
            "Mock response: I can stream plain text, request tools such as list_files, "
            "read_file, mock_lookup, and echo, then continue after tool results."
        ),
        "finish_reason": "stop",
    }


async def iter_sse(response: dict[str, Any], *, delay_seconds: float = 0.02) -> AsyncIterator[str]:
    """Yield OpenAI-style SSE chunks for a prepared mock response."""

    if response["kind"] == "tool_calls":
        if response.get("content"):
            for chunk in _text_chunks(response["content"]):
                yield _sse({"choices": [{"delta": {"content": chunk}}]})
                await asyncio.sleep(delay_seconds)
        for event in _stream_tool_call_events(response["tool_calls"]):
            yield _sse(event)
            await asyncio.sleep(delay_seconds)
        yield _sse({"choices": [{"delta": {}, "finish_reason": response["finish_reason"]}]})
    else:
        chunks = list(_text_chunks(response.get("content", "")))
        for index, chunk in enumerate(chunks):
            finish_reason = response["finish_reason"] if index == len(chunks) - 1 else None
            choice: dict[str, Any] = {"delta": {"content": chunk}}
            if finish_reason:
                choice["finish_reason"] = finish_reason
            yield _sse({"choices": [choice]})
            await asyncio.sleep(delay_seconds)

    yield "data: [DONE]\n\n"


def build_non_stream_response(payload: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": response.get("content", "")}
    if response["kind"] == "tool_calls":
        message["tool_calls"] = [_tool_call_to_openai(call) for call in response["tool_calls"]]
    return {
        "id": f"chatcmpl-mock-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.get("model") or DEFAULT_MODEL,
        "choices": [{"index": 0, "message": message, "finish_reason": response["finish_reason"]}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _available_tool_names(payload: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for tool in payload.get("tools") or []:
        function = tool.get("function") or {}
        if function.get("name"):
            names.add(str(function["name"]))
    return names


def _response_for_scenario(scenario: str, payload: dict[str, Any]) -> dict[str, Any]:
    available = _available_tool_names(payload)

    if scenario == SCENARIO_MESSAGE:
        return {
            "kind": "text",
            "content": "Mock message-only response.",
            "finish_reason": "stop",
        }

    if scenario == SCENARIO_TOOL_CALL:
        call = _first_available_tool_call(available)
        if call is None:
            return _no_tools_response(scenario)
        return {
            "kind": "tool_calls",
            "content": "",
            "tool_calls": [call],
            "finish_reason": "tool_calls",
        }

    if scenario == SCENARIO_TEXT_AND_TOOL_CALL:
        call = _first_available_tool_call(available)
        if call is None:
            return _no_tools_response(scenario)
        return {
            "kind": "tool_calls",
            "content": "Mock response will call a tool.\n",
            "tool_calls": [call],
            "finish_reason": "tool_calls",
        }

    if scenario == SCENARIO_MULTIPLE_TOOL_CALLS:
        calls = _all_available_tool_calls(available)
        if not calls:
            return _no_tools_response(scenario)
        return {
            "kind": "tool_calls",
            "content": "Mock response will call multiple tools.\n",
            "tool_calls": calls,
            "finish_reason": "tool_calls",
        }

    return {
        "kind": "text",
        "content": f"Unknown mock_scenario: {scenario}",
        "finish_reason": "stop",
    }


def _no_tools_response(scenario: str) -> dict[str, Any]:
    return {
        "kind": "text",
        "content": f"Mock scenario `{scenario}` requested tool calls, but no tools were provided.",
        "finish_reason": "stop",
    }


def _first_available_tool_call(available: set[str]) -> dict[str, Any] | None:
    calls = _all_available_tool_calls(available)
    return calls[0] if calls else None


def _all_available_tool_calls(available: set[str]) -> list[dict[str, Any]]:
    candidates = [
        {"id": "call_mock_list_files", "name": "list_files", "arguments": {"path": "."}},
        {"id": "call_mock_read_file", "name": "read_file", "arguments": {"path": "README.md"}},
        {"id": "call_mock_lookup", "name": "mock_lookup", "arguments": {"query": "mock project status"}},
        {"id": "call_mock_echo", "name": "echo", "arguments": {"text": "mock echo"}},
    ]
    return [call for call in candidates if call["name"] in available]


def _select_tool_calls(prompt: str, available: set[str]) -> list[dict[str, Any]]:
    text = prompt.lower()
    calls: list[dict[str, Any]] = []

    if "list_files" in available and any(word in text for word in ("list", "files", "workspace", "directory")):
        calls.append({"id": "call_mock_list_files", "name": "list_files", "arguments": {"path": "."}})

    if "read_file" in available and any(word in text for word in ("read", "readme", "file", "summarize")):
        path = "README.md" if "readme" in text or "summarize" in text else "PROGRESS.md"
        calls.append({"id": "call_mock_read_file", "name": "read_file", "arguments": {"path": path}})

    if "mock_lookup" in available and any(word in text for word in ("lookup", "search", "mock")):
        calls.append({"id": "call_mock_lookup", "name": "mock_lookup", "arguments": {"query": prompt.strip()}})

    if "echo" in available and "echo" in text:
        calls.append({"id": "call_mock_echo", "name": "echo", "arguments": {"text": prompt.strip()}})

    return calls


def _summarize_tool_results(messages: list[dict[str, Any]]) -> str:
    results = [str(message.get("content", "")) for message in messages if message.get("role") == "tool"]
    if not results:
        return "The tool call completed, but no tool result content was provided."
    preview = "\n".join(_truncate(result, 500) for result in results)
    return f"Tool results received:\n{preview}"


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def _last_role(messages: list[dict[str, Any]]) -> str | None:
    return str(messages[-1].get("role")) if messages else None


def _text_chunks(text: str, size: int = 16) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]


def _stream_tool_call_events(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        arguments = json.dumps(call["arguments"])
        split_at = max(1, len(arguments) // 2)
        first, second = arguments[:split_at], arguments[split_at:]
        events.append(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": index,
                                    "id": call["id"],
                                    "type": "function",
                                    "function": {"name": call["name"], "arguments": first},
                                }
                            ]
                        }
                    }
                ]
            }
        )
        events.append(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": index,
                                    "function": {"arguments": second},
                                }
                            ]
                        }
                    }
                ]
            }
        )
    return events


def _tool_call_to_openai(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call["id"],
        "type": "function",
        "function": {"name": call["name"], "arguments": json.dumps(call["arguments"])},
    }


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, separators=(',', ':'))}\n\n"


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sisyphus.hosts.mock_llm")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - depends on optional extras
        raise RuntimeError(
            "The mock LLM server requires uvicorn. Install runtime server dependencies with "
            "`pip install fastapi \"uvicorn[standard]\"`."
        ) from exc

    uvicorn.run("sisyphus.hosts.mock_llm:create_app", factory=True, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
