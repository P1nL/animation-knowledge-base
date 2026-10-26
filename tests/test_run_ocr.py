import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import prepare_pages, run_ocr


class FakeResult:
    def save_to_json(self, path):
        Path(path).write_text(json.dumps({
            "rec_texts": ["中1", "中一", "中なし"],
            "rec_scores": [0.8, 0.7, 0.9],
            "rec_boxes": [[0, 0, 10, 10]] * 3,
        }, ensure_ascii=False), encoding="utf-8")


class FakeEngine:
    def predict(self, image):
        return [FakeResult()]


class OCRTests(unittest.TestCase):
    def test_raw_spelling_and_engine_order_are_preserved(self):
        expected = "中1\n中一\n中なし\n"
        self.assertEqual(run_ocr.extract_text({"rec_texts": ["中1", "中一", "中なし"]}), expected)
        self.assertEqual(run_ocr.extract_text({"res": {"rec_texts": ["中1", "中一", "中なし"]}}), expected)
        self.assertEqual(run_ocr.extract_text({"rec_texts": []}), "")
        with self.assertRaises(ValueError):
            run_ocr.extract_text({"text": "not a supported result"})

    def test_private_inputs_page_selection_and_missing_pages(self):
        with self.assertRaises(ValueError):
            run_ocr.select_images(run_ocr.ROOT / "evaluation/pilot.json", "1")
        with tempfile.TemporaryDirectory() as directory, patch.object(prepare_pages, "ROOT", Path(directory)):
            root = Path(directory)
            pages = root / "work/pages"
            pages.mkdir(parents=True)
            index = pages / "page_index.json"
            index.write_text(json.dumps({"document_pages": 224, "pages": [
                {"pdf_page": 165, "image_file": "page-0165.png"},
            ]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing"):
                run_ocr.select_images(index, "165")
            (pages / "page-0165.png").touch()
            self.assertEqual(run_ocr.select_images(index, "165")[1][0][0]["pdf_page"], 165)
            with self.assertRaisesRegex(ValueError, "no prepared image"):
                run_ocr.select_images(index, "166")

    def test_local_run_preserves_raw_provenance_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pages = root / "work/pages"
            pages.mkdir(parents=True)
            image = pages / "page-0165.png"
            image.touch()
            source = {"source_id": "synthetic", "source_title": "fixture"}
            selected = [({"pdf_page": 165, "printed_page": None}, image)]
            output = root / "work/ocr/sample"
            with patch.object(prepare_pages, "ROOT", root), patch.object(run_ocr, "ROOT", root), \
                 patch.object(run_ocr, "select_images", return_value=(source, selected)), \
                 patch.object(run_ocr, "create_engine", return_value=FakeEngine()) as create, \
                 patch.object(run_ocr, "version", return_value="synthetic-test"):
                result = run_ocr.run(pages / "page_index.json", "165", output)
                self.assertEqual(result["review_status"], "needs_human_review")
                self.assertEqual(result["pages"][0]["printed_page"], None)
                self.assertEqual(result["pages"][0]["recognized_lines"], 3)
                self.assertEqual((output / "page-0165.txt").read_text(encoding="utf-8"), "中1\n中一\n中なし\n")
                self.assertIn("rec_boxes", json.loads((output / "page-0165.json").read_text(encoding="utf-8")))
                self.assertEqual(json.loads((output / "ocr_index.json").read_text(encoding="utf-8")), result)
                with self.assertRaisesRegex(ValueError, "new output"):
                    run_ocr.run(pages / "page_index.json", "165", output)
                create.assert_called_once_with(4)


if __name__ == "__main__":
    unittest.main()
