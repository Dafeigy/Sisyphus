from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

from sisyphus.core.messages import Message, TextBlock, ToolCallBlock
from sisyphus.models import ModelConfig, OpenAIProvider, ToolSpec


class FakeResponse:
    def __init__(self, body: bytes | list[bytes]) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        assert isinstance(self.body, bytes)
        return self.body

    def __iter__(self):
        assert isinstance(self.body, list)
        return iter(self.body)


class OpenAIProviderTests(unittest.TestCase):
    def test_complete_posts_openai_compatible_payload(self) -> None:
        captured = {}
        response = {
            "model": "mock-model",
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 3},
        }

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(json.dumps(response).encode("utf-8"))

        provider = OpenAIProvider(model="mock-model", api_key="anything", base_url="https://example.test/v1")
        with patch("sisyphus.models.openai.urlopen", fake_urlopen):
            result = asyncio.run(
                provider.complete(
                    [Message.text("user", "hi")],
                    [ToolSpec(name="lookup", description="Lookup data", input_schema={"type": "object"})],
                    system="be brief",
                    config=ModelConfig(temperature=0.2, metadata={"seed": 7}),
                )
            )

        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(captured["timeout"], 60.0)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer anything")
        self.assertEqual(captured["payload"]["messages"][0], {"role": "system", "content": "be brief"})
        self.assertEqual(captured["payload"]["messages"][1], {"role": "user", "content": "hi"})
        self.assertEqual(captured["payload"]["temperature"], 0.2)
        self.assertEqual(captured["payload"]["seed"], 7)
        self.assertEqual(captured["payload"]["tools"][0]["function"]["name"], "lookup")
        self.assertEqual(result.content, [TextBlock(text="hello")])
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.usage, {"total_tokens": 3})

    def test_complete_can_post_to_base_url_without_default_path(self) -> None:
        captured = {}
        response = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            return FakeResponse(json.dumps(response).encode("utf-8"))

        provider = OpenAIProvider(
            model="mock-model",
            api_key="anything",
            base_url="https://dg3dl0.mockapi.dog/",
            chat_completions_path="",
        )
        with patch("sisyphus.models.openai.urlopen", fake_urlopen):
            result = asyncio.run(provider.complete([Message.text("user", "hi")], []))

        self.assertEqual(captured["url"], "https://dg3dl0.mockapi.dog")
        self.assertEqual(result.content, [TextBlock(text="ok")])

    def test_complete_can_post_to_exact_completions_url(self) -> None:
        captured = {}
        response = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            return FakeResponse(json.dumps(response).encode("utf-8"))

        provider = OpenAIProvider(
            model="mock-model",
            api_key="anything",
            completions_url="https://custom.test/inference/openai-compatible",
        )
        with patch("sisyphus.models.openai.urlopen", fake_urlopen):
            result = asyncio.run(provider.complete([Message.text("user", "hi")], []))

        self.assertEqual(captured["url"], "https://custom.test/inference/openai-compatible")
        self.assertEqual(result.content, [TextBlock(text="ok")])

    def test_complete_reads_endpoint_configuration_from_environment(self) -> None:
        captured = {}
        response = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            return FakeResponse(json.dumps(response).encode("utf-8"))

        env = {
            "OPENAI_API_KEY": "from-env",
            "OPENAI_BASE_URL": "https://env.test/v1",
            "OPENAI_CHAT_COMPLETIONS_PATH": "/custom/chat",
        }
        with patch.dict(os.environ, env, clear=False), patch("sisyphus.models.openai.urlopen", fake_urlopen):
            provider = OpenAIProvider(model="mock-model")
            result = asyncio.run(provider.complete([Message.text("user", "hi")], []))

        self.assertEqual(captured["url"], "https://env.test/v1/custom/chat")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer from-env")
        self.assertEqual(result.content, [TextBlock(text="ok")])

    def test_complete_parses_tool_calls(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": "{\"path\":\"README.md\"}"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }

        def fake_urlopen(request, timeout):
            return FakeResponse(json.dumps(response).encode("utf-8"))

        provider = OpenAIProvider(model="mock-model", api_key="anything")
        with patch("sisyphus.models.openai.urlopen", fake_urlopen):
            result = asyncio.run(provider.complete([Message.text("user", "read")], []))

        self.assertEqual(result.content, [ToolCallBlock(id="call_1", name="read_file", arguments={"path": "README.md"})])
        self.assertEqual(result.finish_reason, "tool_calls")

    def test_stream_parses_sse_text_deltas(self) -> None:
        lines = [
            b"data: {\"model\":\"mock-model\",\"choices\":[{\"delta\":{\"content\":\"hel\"}}]}\n\n",
            b"data: {\"model\":\"mock-model\",\"choices\":[{\"delta\":{\"content\":\"lo\"},\"finish_reason\":\"stop\"}]}\n\n",
            b"data: [DONE]\n\n",
        ]

        def fake_urlopen(request, timeout):
            payload = json.loads(request.data.decode("utf-8"))
            self.assertTrue(payload["stream"])
            return FakeResponse(lines)

        async def collect():
            provider = OpenAIProvider(model="mock-model", api_key="anything")
            with patch("sisyphus.models.openai.urlopen", fake_urlopen):
                return [delta async for delta in provider.stream([Message.text("user", "hi")], [])]

        deltas = asyncio.run(collect())

        self.assertEqual([delta.content for delta in deltas], [[TextBlock(text="hel")], [TextBlock(text="lo")]])
        self.assertEqual(deltas[-1].finish_reason, "stop")

    def test_stream_assembles_tool_call_arguments_across_sse_events(self) -> None:
        lines = [
            b"data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"call_1\",\"function\":{\"name\":\"read_file\",\"arguments\":\"{\\\"pa\"}}]}}]}\n\n",
            b"data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"function\":{\"arguments\":\"th\\\":\\\"README\"}}]}}]}\n\n",
            b"data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"function\":{\"arguments\":\".md\\\"}\"}}]},\"finish_reason\":\"tool_calls\"}]}\n\n",
            b"data: [DONE]\n\n",
        ]

        def fake_urlopen(request, timeout):
            return FakeResponse(lines)

        async def collect():
            provider = OpenAIProvider(model="mock-model", api_key="anything")
            with patch("sisyphus.models.openai.urlopen", fake_urlopen):
                return [delta async for delta in provider.stream([Message.text("user", "read")], [])]

        deltas = asyncio.run(collect())

        self.assertEqual(
            deltas[-1].content,
            [ToolCallBlock(id="call_1", name="read_file", arguments={"path": "README.md"})],
        )

    def test_stream_assembles_multiple_tool_calls_by_index(self) -> None:
        lines = [
            b"data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":1,\"id\":\"call_b\",\"function\":{\"name\":\"echo\",\"arguments\":\"{\\\"text\\\":\\\"b\"}},{\"index\":0,\"id\":\"call_a\",\"function\":{\"name\":\"mock_lookup\",\"arguments\":\"{\\\"query\\\":\\\"a\\\"}\"}}]}}]}\n\n",
            b"data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":1,\"function\":{\"arguments\":\"\\\"}\"}}]},\"finish_reason\":\"tool_calls\"}]}\n\n",
            b"data: [DONE]\n\n",
        ]

        def fake_urlopen(request, timeout):
            return FakeResponse(lines)

        async def collect():
            provider = OpenAIProvider(model="mock-model", api_key="anything")
            with patch("sisyphus.models.openai.urlopen", fake_urlopen):
                return [delta async for delta in provider.stream([Message.text("user", "tools")], [])]

        deltas = asyncio.run(collect())

        self.assertEqual(
            deltas[-1].content,
            [
                ToolCallBlock(id="call_a", name="mock_lookup", arguments={"query": "a"}),
                ToolCallBlock(id="call_b", name="echo", arguments={"text": "b"}),
            ],
        )

    def test_stream_supports_mixed_text_and_tool_call_deltas(self) -> None:
        lines = [
            b"data: {\"choices\":[{\"delta\":{\"content\":\"Checking \",\"tool_calls\":[{\"index\":0,\"id\":\"call_1\",\"function\":{\"name\":\"echo\",\"arguments\":\"{}\"}}]}}]}\n\n",
            b"data: {\"choices\":[{\"delta\":{\"content\":\"now\"},\"finish_reason\":\"tool_calls\"}]}\n\n",
            b"data: [DONE]\n\n",
        ]

        def fake_urlopen(request, timeout):
            return FakeResponse(lines)

        async def collect():
            provider = OpenAIProvider(model="mock-model", api_key="anything")
            with patch("sisyphus.models.openai.urlopen", fake_urlopen):
                return [delta async for delta in provider.stream([Message.text("user", "tools")], [])]

        deltas = asyncio.run(collect())

        self.assertEqual(deltas[0].content, [TextBlock(text="Checking ")])
        self.assertEqual(deltas[1].content, [TextBlock(text="now"), ToolCallBlock(id="call_1", name="echo", arguments={})])

    def test_stream_invalid_tool_arguments_fall_back_to_raw(self) -> None:
        lines = [
            b"data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"call_1\",\"function\":{\"name\":\"echo\",\"arguments\":\"{bad\"}}]},\"finish_reason\":\"tool_calls\"}]}\n\n",
            b"data: [DONE]\n\n",
        ]

        def fake_urlopen(request, timeout):
            return FakeResponse(lines)

        async def collect():
            provider = OpenAIProvider(model="mock-model", api_key="anything")
            with patch("sisyphus.models.openai.urlopen", fake_urlopen):
                return [delta async for delta in provider.stream([Message.text("user", "tools")], [])]

        deltas = asyncio.run(collect())

        self.assertEqual(deltas[-1].content, [ToolCallBlock(id="call_1", name="echo", arguments={"_raw": "{bad"})])


if __name__ == "__main__":
    unittest.main()
