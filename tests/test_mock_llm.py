from __future__ import annotations

import asyncio
import json
import unittest

from sisyphus.hosts.mock_llm import build_chat_completion, build_non_stream_response, create_app, iter_sse


class MockLLMTests(unittest.TestCase):
    def test_build_chat_completion_selects_multiple_tool_calls(self) -> None:
        payload = {
            "model": "mock",
            "messages": [{"role": "user", "content": "List files and lookup mock status"}],
            "tools": [
                {"type": "function", "function": {"name": "list_files"}},
                {"type": "function", "function": {"name": "mock_lookup"}},
            ],
        }

        response = build_chat_completion(payload)

        self.assertEqual(response["kind"], "tool_calls")
        self.assertEqual([call["name"] for call in response["tool_calls"]], ["list_files", "mock_lookup"])

    def test_build_chat_completion_supports_message_only_scenario(self) -> None:
        response = build_chat_completion(
            {
                "model": "mock",
                "mock_scenario": "message",
                "messages": [{"role": "user", "content": "hello"}],
                "tools": [{"type": "function", "function": {"name": "echo"}}],
            }
        )

        self.assertEqual(response["kind"], "text")
        self.assertEqual(response["finish_reason"], "stop")

    def test_build_chat_completion_supports_tool_call_only_scenario(self) -> None:
        response = build_chat_completion(
            {
                "model": "mock",
                "mock_scenario": "tool_call",
                "messages": [{"role": "user", "content": "call a tool"}],
                "tools": [{"type": "function", "function": {"name": "echo"}}],
            }
        )

        self.assertEqual(response["kind"], "tool_calls")
        self.assertEqual(response["content"], "")
        self.assertEqual(response["tool_calls"], [{"id": "call_mock_echo", "name": "echo", "arguments": {"text": "mock echo"}}])

    def test_build_chat_completion_supports_multiple_tool_call_scenario(self) -> None:
        response = build_chat_completion(
            {
                "model": "mock",
                "mock_scenario": "multiple_tool_calls",
                "messages": [{"role": "user", "content": "call tools"}],
                "tools": [
                    {"type": "function", "function": {"name": "read_file"}},
                    {"type": "function", "function": {"name": "mock_lookup"}},
                ],
            }
        )

        self.assertEqual([call["name"] for call in response["tool_calls"]], ["read_file", "mock_lookup"])

    def test_iter_sse_streams_tool_call_arguments_in_fragments(self) -> None:
        response = {
            "kind": "tool_calls",
            "content": "checking\n",
            "finish_reason": "tool_calls",
            "tool_calls": [
                {"id": "call_1", "name": "read_file", "arguments": {"path": "README.md"}},
            ],
        }

        async def collect() -> list[str]:
            return [chunk async for chunk in iter_sse(response, delay_seconds=0)]

        chunks = asyncio.run(collect())
        payloads = [
            json.loads(chunk.removeprefix("data:").strip())
            for chunk in chunks
            if chunk.startswith("data:") and "[DONE]" not in chunk
        ]

        tool_events = [
            payload
            for payload in payloads
            if payload["choices"][0].get("delta", {}).get("tool_calls")
        ]
        self.assertEqual(len(tool_events), 2)
        self.assertEqual(tool_events[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(payloads[-1]["choices"][0]["finish_reason"], "tool_calls")

    def test_iter_sse_tool_call_only_omits_text_delta(self) -> None:
        response = {
            "kind": "tool_calls",
            "content": "",
            "finish_reason": "tool_calls",
            "tool_calls": [
                {"id": "call_1", "name": "echo", "arguments": {"text": "hello"}},
            ],
        }

        async def collect() -> list[str]:
            return [chunk async for chunk in iter_sse(response, delay_seconds=0)]

        chunks = asyncio.run(collect())
        payloads = [
            json.loads(chunk.removeprefix("data:").strip())
            for chunk in chunks
            if chunk.startswith("data:") and "[DONE]" not in chunk
        ]

        self.assertFalse(any(payload["choices"][0].get("delta", {}).get("content") for payload in payloads))
        self.assertTrue(any(payload["choices"][0].get("delta", {}).get("tool_calls") for payload in payloads))

    def test_non_stream_response_is_openai_compatible(self) -> None:
        payload = {"model": "mock", "messages": [{"role": "user", "content": "hello"}]}
        response = build_chat_completion(payload)

        data = build_non_stream_response(payload, response)

        self.assertEqual(data["object"], "chat.completion")
        self.assertEqual(data["choices"][0]["message"]["role"], "assistant")
        self.assertEqual(data["choices"][0]["finish_reason"], "stop")

    def test_fastapi_route_accepts_json_request_body(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("FastAPI test client is not installed.")

        client = TestClient(create_app())
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock",
                "stream": False,
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["choices"][0]["message"]["role"], "assistant")


if __name__ == "__main__":
    unittest.main()
