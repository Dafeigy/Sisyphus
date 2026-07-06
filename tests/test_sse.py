from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime

from sisyphus.core.events import RuntimeEvent
from sisyphus.hosts.sse import encode_sse, encode_sse_comment, iter_sse


class SSEHostTests(unittest.TestCase):
    def test_encode_sse_uses_runtime_event_type_sequence_and_json_data(self) -> None:
        event = RuntimeEvent(
            type="message.delta",
            run_id="run-1",
            sequence=3,
            timestamp=datetime(2026, 7, 7, 1, 2, 3, tzinfo=UTC),
            data={"content": [{"type": "text", "text": "hello"}]},
        )

        encoded = encode_sse(event)

        self.assertTrue(encoded.startswith("event: message.delta\nid: 3\ndata: "))
        self.assertTrue(encoded.endswith("\n\n"))
        payload = json.loads(encoded.split("data: ", 1)[1].strip())
        self.assertEqual(payload["type"], "message.delta")
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["sequence"], 3)
        self.assertEqual(payload["data"]["content"][0]["text"], "hello")

    def test_encode_sse_splits_multiline_json_data_for_sse_compatibility(self) -> None:
        event = RuntimeEvent(
            type="run.failed",
            run_id="run-1",
            sequence=4,
            timestamp=datetime(2026, 7, 7, 1, 2, 3, tzinfo=UTC),
            data={"message": "line one\nline two", "code": "provider_error"},
        )

        encoded = encode_sse(event, compact=False)

        self.assertIn("\ndata: ", encoded)
        self.assertNotIn("\n{\n", encoded)
        payload_text = "\n".join(
            line.removeprefix("data: ") for line in encoded.splitlines() if line.startswith("data: ")
        )
        self.assertEqual(json.loads(payload_text)["data"]["message"], "line one\nline two")

    def test_encode_sse_comment_formats_heartbeat_comments(self) -> None:
        self.assertEqual(encode_sse_comment("keepalive"), ": keepalive\n\n")

    def test_iter_sse_encodes_each_event(self) -> None:
        events = [
            RuntimeEvent("run.started", "run-1", 0, datetime(2026, 7, 7, tzinfo=UTC), {}),
            RuntimeEvent("run.completed", "run-1", 1, datetime(2026, 7, 7, tzinfo=UTC), {"text": "done"}),
        ]

        encoded = list(iter_sse(events))

        self.assertEqual(len(encoded), 2)
        self.assertIn("event: run.started", encoded[0])
        self.assertIn("event: run.completed", encoded[1])


if __name__ == "__main__":
    unittest.main()
