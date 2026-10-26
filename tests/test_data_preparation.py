import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import export_knowledge, prepare_pages


class PreparationTests(unittest.TestCase):
    def test_selected_pages_are_bounded_and_deduplicated(self):
        self.assertEqual(prepare_pages.parse_pages("56-58,57,165", 224), [56, 57, 58, 165])
        for value in ("0", "225", "58-56", "", "x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                prepare_pages.parse_pages(value, 224)

    def test_page_images_stay_in_private_work(self):
        with self.assertRaises(ValueError):
            prepare_pages.private_output(prepare_pages.ROOT / "public")

    def test_export_refuses_evaluation_input_and_requires_draft_opt_in(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(export_knowledge, "ROOT", Path(directory)):
            root = Path(directory)
            cards_file = root / "corpus/cards.jsonl"
            cards_file.parent.mkdir()
            card = {
                "id": "TEST-01", "source_id": "test-fixture", "term_ja": "test",
                "title_zh": "synthetic fixture", "context": "test", "summary_zh": "test only",
                "pdf_pages": [1], "extraction_method": "fixture", "review_status": "needs_human_review",
            }
            cards_file.write_text(json.dumps(card) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                export_knowledge.load_cards(root / "evaluation/pilot.json")
            with self.assertRaises(ValueError):
                export_knowledge.load_cards(cards_file)
            loaded = export_knowledge.load_cards(cards_file, include_drafts=True)
            self.assertEqual(len(loaded), 1)
            self.assertIn("尚待人工校订", export_knowledge.render_card(loaded[0]))
            cards_file.write_text((json.dumps(card) + "\n") * 2, encoding="utf-8")
            with self.assertRaises(ValueError):
                export_knowledge.load_cards(cards_file, include_drafts=True)


if __name__ == "__main__":
    unittest.main()
