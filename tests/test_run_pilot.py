"""Synthetic streaming fixtures; no real model requests or evaluation scores."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import prepare_pages, run_pilot as tool


def events(status="succeeded", finish="stop"):
    return [
        {"event": "node_finished", "data": {"node_type": "llm", "status": status, "outputs": {"finish_reason": finish}}},
        {"event": "message", "answer": "SYNTHETIC ANSWER"},
        {"event": "message_end", "metadata": {"usage": {"total_tokens": 7}, "retriever_resources": []}},
        {"event": "workflow_finished", "data": {"id": "synthetic-run", "status": status, "elapsed_time": 0.1}},
    ]


class FakeConsole:
    origin = "http://127.0.0.1:18080"
    cookies = []

    def __init__(self, stream):
        self.stream = stream
        self.opener = self
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        return io.BytesIO("".join("data: " + json.dumps(e) + "\n\n" for e in self.stream).encode())


class PilotRunTests(unittest.TestCase):
    def test_authorization_is_required_before_any_network_access(self):
        with patch.object(tool.dify_local, "Console", side_effect=AssertionError("No network without authorization")):
            with self.assertRaisesRegex(ValueError, "authorization"):
                tool.run(Path("unused"))

    def test_stream_preserves_actual_usage_and_leaves_scores_unassigned(self):
        answer = tool.answer_from_events(events())
        self.assertEqual(answer["answer_text"], "SYNTHETIC ANSWER")
        self.assertEqual(answer["usage"]["total_tokens"], 7)
        self.assertIsNone(answer["score"])
        self.assertIsNone(answer["reviewer"])

    def test_failed_and_truncated_streams_are_not_promoted_to_answers(self):
        for stream in (events("failed"), events(finish="length"), events()[:-1]):
            with self.assertRaises(ValueError):
                tool.answer_from_events(stream)

    def test_completed_attempt_is_not_repeated_and_reference_points_are_not_sent(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(prepare_pages, "ROOT", Path(directory)):
            path = Path(directory) / "work/runs/synthetic.json"
            console = FakeConsole(events())
            row = {"question_id": "SYNTHETIC-01", "condition": "G0", "query": "SYNTHETIC QUESTION",
                   "required_points": ["GOLD MUST NOT BE SENT"]}
            first = tool.execute_one(console, "synthetic-app", row, path)
            second = tool.execute_one(console, "synthetic-app", row, path)
            self.assertEqual(first, second)
            self.assertEqual(len(console.calls), 1)
            payload = json.loads(console.calls[0].data)
            self.assertEqual(payload, {"inputs": {}, "query": "SYNTHETIC QUESTION", "files": []})
            self.assertNotIn("GOLD MUST NOT BE SENT", console.calls[0].data.decode())

    def test_failed_attempt_is_saved_and_never_automatically_retried(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(prepare_pages, "ROOT", Path(directory)):
            path = Path(directory) / "work/runs/synthetic.json"
            console = FakeConsole(events("failed"))
            row = {"question_id": "SYNTHETIC-01", "condition": "G1", "query": "SYNTHETIC QUESTION"}
            for _ in range(2):
                with self.assertRaises(ValueError):
                    tool.execute_one(console, "synthetic-app", row, path)
            self.assertEqual(len(console.calls), 1)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "failed_or_incomplete")


if __name__ == "__main__":
    unittest.main()
