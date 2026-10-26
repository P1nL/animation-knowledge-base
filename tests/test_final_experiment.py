"""Bounded offline checks for frozen final data and authorized runner; no real calls."""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import dify_local as d, export_knowledge, prepare_pages, prepare_final as prep
from scripts import prepare_pilot, run_final, run_pilot


class FinalExperimentTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in (d, export_knowledge, prepare_pages, prep):
            self.stack.enter_context(patch.object(module, "ROOT", self.root))
        self.bundle = self.root / "work/final-v1"
        release = self.root / "corpus/releases/source-v2"
        release.mkdir(parents=True)
        (self.root / "evaluation").mkdir()
        cards = [{"id": f"book-{i:03}", "source_id": "synthetic", "term_ja": "TERM",
                  "title_zh": "SOURCE", "context": "CONTEXT", "summary_zh": "SOURCE ONLY",
                  "pdf_pages": [1], "review_status": "needs_human_review", "extraction_method": "synthetic"}
                 for i in range(1, 35)]
        (release / "cards.jsonl").write_text("".join(json.dumps(c) + "\n" for c in cards), encoding="utf-8")
        raw = self.root / "work/ocr/synthetic"
        raw.mkdir(parents=True)
        pages = []
        for i in range(1, 29):
            name = f"page-{i:04}.txt"
            (raw / name).write_text("RAW SENTINEL\n", encoding="utf-8")
            pages.append({"pdf_page": i, "text_file": name})
        d.save_private(raw / "ocr_index.json", {"source_id": "synthetic", "pages": pages})
        scope = {"version": "source-v2", "card_count": 34, "cards_file": "corpus/releases/source-v2/cards.jsonl",
                 "approved_pdf_pages": list(range(1, 29)), "raw_ocr_indices": ["work/ocr/synthetic/ocr_index.json"]}
        (release / "scope.json").write_text(json.dumps(scope), encoding="utf-8")
        questions = {"split": "held_out", "dataset_version": "final-v1", "source_release": "source-v2",
                     "frozen": True, "must_not_index": True, "must_not_use_for_tuning": True,
                     "questions": [{"id": f"FINAL-{i:02}", "question": f"QUESTION SENTINEL {i}",
                                    "source_card_ids": ["book-001"], "source_pages": [1],
                                    "required_points": ["GOLD SENTINEL"]} for i in range(1, 31)]}
        (self.root / "evaluation/final_v1.json").write_text(json.dumps(questions), encoding="utf-8")

    def prepared(self):
        return prep.prepare(self.bundle, accept_ai_reviewed=True)

    def test_prepare_is_offline_raw_preserved_and_gold_is_separate(self):
        with patch.object(d, "Console", side_effect=AssertionError("No network")):
            config = self.prepared()
            _, requests = prep.validate_bundle(self.bundle)
        self.assertEqual(config["source_counts"], {"G0": 0, "G1": 28, "G2": 34})
        self.assertEqual(len(requests), 90)
        self.assertNotIn("GOLD SENTINEL", json.dumps(requests))
        for p in (self.bundle / "sources").rglob("*.md"):
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("GOLD SENTINEL", text)
            self.assertNotIn("QUESTION SENTINEL", text)
            if p.parent.name == "G1":
                self.assertTrue(text.endswith("RAW SENTINEL\n"))
            else:
                self.assertIn("needs_human_review", text)

    def test_review_acceptance_private_output_and_no_overwrite(self):
        with self.assertRaisesRegex(ValueError, "acceptance"):
            prep.prepare(self.bundle)
        with self.assertRaises(ValueError):
            prep.prepare(self.root / "public", True)
        self.prepared()
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.prepared()

    def test_changed_source_and_gold_in_requests_are_rejected(self):
        self.prepared()
        p = self.bundle / "sources/G2/book-001.md"
        original = p.read_text(encoding="utf-8")
        p.write_text("GOLD SENTINEL", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Source snapshot"):
            prep.validate_bundle(self.bundle)
        p.write_text(original, encoding="utf-8")
        p = self.bundle / "requests.jsonl"
        rows = [json.loads(s) for s in p.read_text(encoding="utf-8").splitlines()]
        rows[0]["gold"] = "GOLD SENTINEL"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "question-only"):
            prep.validate_bundle(self.bundle)

    def test_runner_requires_new_authorization_before_network(self):
        with patch.object(d, "Console", side_effect=AssertionError("No network")):
            with self.assertRaisesRegex(ValueError, "authorization"):
                run_final.run(self.bundle)

    def test_final_runner_90_calls_then_resume_sends_zero_and_failure_stops(self):
        self.prepared()
        state = {"origin": "http://127.0.0.1:18080", "groups": {
            g: {"app_id": g, **({"dataset_id": g, "completed_documents": 28 if g == "G1" else 34}
                                  if g != "G0" else {})} for g in prepare_pilot.CONDITIONS}}
        d.save_private(self.bundle / "state.json", state)

        class Console:
            origin = state["origin"]
            cookies = []

            def __init__(self):
                self.drafts, self.calls = {}, []
                self.opener = self

            def login(self, account):
                pass

            def request(self, method, path, data=None):
                if method == "POST":
                    self.drafts[path] = deepcopy(data)
                return deepcopy(self.drafts.get(path, {}))

            def open(self, request, timeout):
                self.calls.append(json.loads(request.data))
                events = [{"event": "message", "answer": "SYNTHETIC ANSWER"},
                          {"event": "node_finished", "data": {"node_type": "llm", "status": "succeeded",
                                                               "outputs": {"finish_reason": "stop"}}},
                          {"event": "message_end", "metadata": {"usage": {"total_tokens": 1}}},
                          {"event": "workflow_finished", "data": {"status": "succeeded", "id": "fixture"}}]
                return io.BytesIO("".join("data: " + json.dumps(e) + "\n\n" for e in events).encode())

        console = Console()
        with patch.object(d, "Console", return_value=console), redirect_stdout(io.StringIO()):
            first = run_final.run(self.bundle, True)
            second = run_final.run(self.bundle, True)
        self.assertEqual(len(first), 90)
        self.assertEqual(first, second)
        self.assertEqual(len(console.calls), 90)
        self.assertTrue(all(set(c) == {"inputs", "query", "files"} for c in console.calls))
        self.assertNotIn("GOLD SENTINEL", json.dumps(console.calls))
        self.assertTrue(all(a["score"] is None for a in first))
        d.save_private(self.bundle / "runs/FINAL-01-G0.json", {"status": "failed_or_incomplete"})
        with patch.object(d, "Console", side_effect=AssertionError("Stop before network")):
            with self.assertRaisesRegex(ValueError, "Incomplete/failed"):
                run_final.run(self.bundle, True)


if __name__ == "__main__":
    unittest.main()
