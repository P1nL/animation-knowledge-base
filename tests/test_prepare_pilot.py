"""Synthetic preparation fixtures only; never invoke a paid model."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import export_knowledge, prepare_pages, prepare_pilot as tool


class LocalConsole:
    origin = "http://127.0.0.1:18080"

    def __init__(self):
        self.calls = []
        self.datasets = {}
        self.apps = []

    def request(self, method, path, data=None, token=None):
        self.calls.append((method, path, data))
        if method == "POST" and path == "/console/api/datasets":
            identifier = f"synthetic-dataset-{len(self.datasets)}"
            self.datasets[identifier] = []
            return {"id": identifier}
        if path == "/console/api/datasets/api-keys":
            return {"token": "synthetic-only-key"}
        if path.startswith("/v1/datasets/"):
            documents = self.datasets[path.split("/")[3]]
            if method == "GET":
                return {"data": documents}
            if path.endswith("/document/create-by-text"):
                document = {"id": f"synthetic-doc-{len(documents)}", "name": data["name"], "indexing_status": "completed"}
                documents.append(document)
                return {"document": document}
        if path == "/console/api/apps":
            identifier = f"synthetic-app-{len(self.apps)}"
            self.apps.append(identifier)
            return {"id": identifier}
        if method == "POST" and path.endswith("/workflows/draft"):
            return {}
        raise AssertionError(f"Unexpected endpoint: {method} {path}")


class PilotPreparationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in (tool, export_knowledge, prepare_pages):
            self.stack.enter_context(patch.object(module, "ROOT", self.root))
        (self.root / "corpus/curated").mkdir(parents=True)
        (self.root / "evaluation").mkdir()
        card = {"source_id": "synthetic-source", "term_ja": "SYNTHETIC TERM",
                "title_zh": "SYNTHETIC SOURCE", "context": "SYNTHETIC CONTEXT",
                "summary_zh": "SYNTHETIC SOURCE CONTENT", "extraction_method": "synthetic_fixture",
                "pdf_pages": [56], "review_status": "human_reviewed"}
        self.cards_path = self.root / "corpus/curated/book_cards.jsonl"
        self.cards_path.write_text("".join(json.dumps({**card, "id": f"synthetic-{i:03d}"}) + "\n"
                                           for i in range(13)), encoding="utf-8")
        self.pilot = {"split": "development_only", "status": "synthetic_reviewed",
                      "questions": [{"id": f"SYNTHETIC-{i:02d}", "gold_status": "human_reviewed",
                                     "question": "QUESTION_ONLY_SENTINEL", "required_points": ["GOLD_ONLY_SENTINEL"]}
                                    for i in range(10)]}
        self.pilot_path = self.root / "evaluation/pilot.json"
        self.pilot_path.write_text(json.dumps(self.pilot), encoding="utf-8")
        pages = {"sample-v1": (151, 165, 166), "core-rest-v1": (56, 57, 58, 59, 60, 61, 152, 167, 224)}
        for batch, numbers in pages.items():
            directory = self.root / "work/ocr" / batch
            directory.mkdir(parents=True)
            entries = []
            for number in numbers:
                name = f"page-{number:04d}.txt"
                (directory / name).write_text("RAW OCR SENTINEL\nUncorrected OCR\n", encoding="utf-8")
                entries.append({"pdf_page": number, "text_file": name})
            (directory / "ocr_index.json").write_text(json.dumps({"source_id": "synthetic-source", "pages": entries}), encoding="utf-8")
        self.output = self.root / "work/pilot-synthetic"

    def test_prepare_is_offline_and_keeps_gold_out_of_source_and_request_payloads(self):
        with patch.object(tool.dify_local, "Console", side_effect=AssertionError("No network in offline prepare")):
            config = tool.prepare(self.output)
        self.assertEqual(config["source_counts"], {"G0": 0, "G1": 12, "G2": 13})
        self.assertEqual(config["planned_calls"], 30)
        self.assertEqual(config["maximum_output_tokens"], 61440)
        self.assertFalse(config["chat_calls_authorized"])
        for source in (self.output / "sources").glob("*/*.md"):
            self.assertNotIn("QUESTION_ONLY_SENTINEL", source.read_text(encoding="utf-8"))
            self.assertNotIn("GOLD_ONLY_SENTINEL", source.read_text(encoding="utf-8"))
        requests = (self.output / "requests.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("GOLD_ONLY_SENTINEL", requests)
        self.assertEqual(len(requests.splitlines()), 30)
        self.assertIn("GOLD_ONLY_SENTINEL", (self.output / "questions.json").read_text(encoding="utf-8"))

    def test_raw_ocr_body_is_preserved_and_reviewed_cards_have_no_draft_warning(self):
        documents = tool.source_documents()
        self.assertTrue(all(text.endswith("RAW OCR SENTINEL\nUncorrected OCR\n") for _, text in documents["G1"]))
        self.assertTrue(all("raw_ocr_uncorrected" in text for _, text in documents["G1"]))
        self.assertTrue(all("human_reviewed" in text and "内部草案" not in text for _, text in documents["G2"]))

    def test_workflows_share_task_and_model_without_weakening_g0(self):
        config = {"model": tool.MODEL, "system_prompt": tool.SYSTEM_PROMPT}
        for condition in tool.CONDITIONS:
            payload = tool.workflow(condition, None if condition == "G0" else "synthetic-dataset", config)
            nodes = {n["id"]: n["data"] for n in payload["graph"]["nodes"]}
            llm = nodes["llm"]
            self.assertEqual(llm["model"], tool.MODEL)
            self.assertTrue(llm["prompt_template"][0]["text"].startswith(tool.SYSTEM_PROMPT + "\n\n参考资料：\n"))
            self.assertFalse(llm["retry_config"]["retry_enabled"])
            self.assertEqual(llm["context"]["enabled"], condition != "G0")
            self.assertEqual("knowledge" in nodes, condition != "G0")
            if condition == "G0":
                self.assertNotIn("{{#context#}}", llm["prompt_template"][0]["text"])
                self.assertEqual(payload["graph"]["edges"][0]["target"], "llm")
            else:
                self.assertEqual(nodes["knowledge"]["dataset_ids"], ["synthetic-dataset"])
        self.assertEqual(tool.MODEL["completion_params"]["max_tokens"], 2048)

    def test_unreviewed_questions_and_wrong_split_are_rejected(self):
        for change in ("draft", "held_out"):
            data = deepcopy(self.pilot)
            if change == "draft":
                data["questions"][0]["gold_status"] = change
            else:
                data["split"] = change
            self.pilot_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                tool.prepare(self.output)
            self.assertFalse(self.output.exists())

    def test_unreviewed_cards_do_not_become_reviewed_automatically(self):
        text = self.cards_path.read_text(encoding="utf-8").replace('"human_reviewed"', '"needs_human_review"')
        self.cards_path.write_text(text, encoding="utf-8")
        with self.assertRaises(ValueError):
            tool.prepare(self.output)
        self.assertFalse(self.output.exists())

    def test_snapshots_are_private_and_not_overwritten(self):
        with self.assertRaises(ValueError):
            tool.prepare(self.root / "public")
        tool.prepare(self.output)
        with self.assertRaises(ValueError):
            tool.prepare(self.output)

    def test_indexing_is_source_only_local_idempotent_and_never_generates(self):
        tool.prepare(self.output)
        console = LocalConsole()
        state = tool.index_sources(console, self.output)
        self.assertEqual(len(console.apps), 3)
        self.assertEqual(state["groups"]["G1"]["completed_documents"], 12)
        self.assertEqual(state["groups"]["G2"]["completed_documents"], 13)
        self.assertNotIn("dataset_id", state["groups"]["G0"])
        before = sum(method == "POST" for method, _, _ in console.calls)
        tool.index_sources(console, self.output)
        self.assertEqual(sum(method == "POST" for method, _, _ in console.calls), before)
        for method, path, data in console.calls:
            self.assertNotIn("/run", path)
            self.assertNotIn("/publish", path)
            if path.endswith("/document/create-by-text"):
                self.assertNotIn("GOLD_ONLY_SENTINEL", data["text"])
                self.assertNotIn("QUESTION_ONLY_SENTINEL", data["text"])
                self.assertEqual(data["embedding_model_provider"], tool.dify_local.EMBEDDING_PROVIDER)


if __name__ == "__main__":
    unittest.main()
