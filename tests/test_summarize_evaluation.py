"""SYNTHETIC TEST DATA ONLY: no real answers, ratings, or evaluation files."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import summarize_evaluation as tool


def synthetic_questions(count=2):
    return {
        "schema_version": "0.1",
        "split": "development_only",
        "status": "draft_requires_source_and_human_review",
        "questions": [
            {
                "id": f"SYNTHETIC-TEST-{index:02d}",
                "question": "SYNTHETIC TEST QUESTION; NOT AN EVALUATION ITEM",
                "required_points": ["SYNTHETIC TEST RUBRIC; NOT GOLD EVIDENCE"],
                "gold_status": "draft",
            }
            for index in range(1, count + 1)
        ],
    }


def synthetic_rating(index, condition, score, **overrides):
    row = {
        "question_id": f"SYNTHETIC-TEST-{index:02d}",
        "condition": condition,
        "answer_text": "SYNTHETIC TEST ANSWER; NOT A MODEL RESPONSE",
        "score": score,
        "reviewer": "synthetic-test-reviewer" if score is not None else None,
        "notes": "SYNTHETIC TEST SCORE; NOT EMPIRICAL EVIDENCE",
    }
    row.update(overrides)
    return row


def jsonl(rows):
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)


class SummarizeEvaluationTests(unittest.TestCase):
    def load(self, rows, count=2):
        questions = tool.load_questions(io.StringIO(json.dumps(synthetic_questions(count))))
        ratings = tool.load_ratings(io.StringIO(jsonl(rows)), questions)
        return questions, ratings

    def test_complete_pairs_preserve_scores_without_citations(self):
        rows = [
            synthetic_rating(index, condition, score)
            for condition, scores in {"G0": (0, 2), "G1": (2, 1), "G2": (1, 0)}.items()
            for index, score in enumerate(scores, start=1)
        ]
        questions, ratings = self.load(rows)
        result = tool.summarize(questions, ratings)
        for condition, expected_mean in {"G0": 1.0, "G1": 1.5, "G2": 0.5}.items():
            self.assertEqual(result["groups"][condition], {
                "expected": 2, "answered": 2, "scored": 2,
                "missing_answers": 0, "missing_scores": 0, "mean": expected_mean,
            })
        self.assertEqual(result["pairs"]["G0-G1"]["paired"], 2)
        self.assertEqual(result["pairs"]["G0-G1"]["mean_difference"], 0.5)
        self.assertEqual(result["pairs"]["G0-G2"]["paired"], 2)
        self.assertEqual(result["pairs"]["G0-G2"]["mean_difference"], -0.5)
        report = tool.render_report(questions, ratings)
        self.assertIn("| G0 | 2 | 2 | 2 | 0 | 0 | 1.000 | 2 |", report)
        self.assertIn("| G0-G1 | G1 - G0 | 2 | +0.500 |", report)
        self.assertIn("| G0-G2 | G2 - G0 | 2 | -0.500 |", report)
        self.assertIn("G0 没有引文不扣答案分", report)

    def test_partial_results_use_scored_denominators_and_pair_intersections(self):
        rows = [
            synthetic_rating(1, "G0", 0),
            synthetic_rating(2, "G0", 2),
            synthetic_rating(1, "G1", 2),
            synthetic_rating(2, "G1", None),
            synthetic_rating(3, "G1", 2),
            synthetic_rating(1, "G2", None, answer_text=" \t "),
            synthetic_rating(2, "G2", 1),
        ]
        questions, _ = self.load([], count=3)
        # Blank lines are allowed without changing physical line numbering.
        text = "\n \t\n" + "\n\n".join(jsonl([row]) for row in rows) + "\n"
        ratings = tool.load_ratings(io.StringIO(text), questions)
        result = tool.summarize(questions, ratings)
        self.assertEqual(result["groups"]["G0"], {
            "expected": 3, "answered": 2, "scored": 2,
            "missing_answers": 1, "missing_scores": 1, "mean": 1.0,
        })
        self.assertEqual(result["groups"]["G1"], {
            "expected": 3, "answered": 3, "scored": 2,
            "missing_answers": 0, "missing_scores": 1, "mean": 2.0,
        })
        self.assertEqual(result["groups"]["G2"], {
            "expected": 3, "answered": 1, "scored": 1,
            "missing_answers": 2, "missing_scores": 2, "mean": 1.0,
        })
        # G1 minus G0 is 2 on the paired subset, not the group-mean gap of 1.
        self.assertEqual(result["pairs"]["G0-G1"]["paired"], 1)
        self.assertEqual(result["pairs"]["G0-G1"]["mean_difference"], 2.0)
        self.assertEqual(result["pairs"]["G0-G2"]["paired"], 1)
        self.assertEqual(result["pairs"]["G0-G2"]["mean_difference"], -1.0)
        report = tool.render_report(questions, ratings)
        self.assertIn("| G1 | 3 | 3 | 2 | 0 | 1 | 2.000 | 2 |", report)
        self.assertIn("| SYNTHETIC-TEST-02 | 2 | 已回答 / 未评分 | 1 |", report)

    def test_empty_ratings_have_no_computable_results(self):
        questions, _ = self.load([])
        for text in ("", "\n \t\n"):
            with self.subTest(text=repr(text)):
                ratings = tool.load_ratings(io.StringIO(text), questions)
                result = tool.summarize(questions, ratings)
                for group in result["groups"].values():
                    self.assertEqual(group, {
                        "expected": 2, "answered": 0, "scored": 0,
                        "missing_answers": 2, "missing_scores": 2, "mean": None,
                    })
                for pair in result["pairs"].values():
                    self.assertEqual(pair["paired"], 0)
                    self.assertIsNone(pair["mean_difference"])
                report = tool.render_report(questions, ratings)
                self.assertIn("没有结果", report)
                self.assertIn("| G0 | 2 | 0 | 0 | 2 | 2 | 不可计算 | 0 |", report)
                self.assertIn("| G0-G1 | G1 - G0 | 0 | 不可计算 |", report)
                self.assertNotIn("%", report)

    def test_duplicate_and_invalid_inputs_are_errors(self):
        questions, _ = self.load([])
        base = synthetic_rating(1, "G0", 1)
        missing_score = {key: value for key, value in base.items() if key != "score"}
        missing_reviewer = {key: value for key, value in base.items() if key != "reviewer"}
        cases = [
            ([base, base], "ratings line 3: duplicate"),
            ([dict(base, question_id="UNKNOWN-TEST-ID")], "ratings line 2: unknown question_id"),
            ([dict(base, condition="G3")], "ratings line 2: unknown condition"),
            ([missing_score], "ratings line 2: missing required field: score"),
            ([missing_reviewer], "ratings line 2: scored rows require a non-empty reviewer"),
            ([dict(base, reviewer=" \t")], "ratings line 2: scored rows require a non-empty reviewer"),
            ([dict(base, answer_text=" ")], "ratings line 2: scored rows require a non-empty answer_text"),
        ]
        cases.extend(
            ([dict(base, score=score)], "ratings line 2: score must be integer")
            for score in (3, -1, 1.5, "2", True)
        )
        for rows, expected_error in cases:
            with self.subTest(rows=rows):
                with self.assertRaisesRegex(ValueError, expected_error):
                    tool.load_ratings(io.StringIO("\n" + jsonl(rows)), questions)
        with self.assertRaisesRegex(ValueError, "ratings line 2: invalid JSON"):
            tool.load_ratings(io.StringIO("\n{not-json}"), questions)
        duplicate_questions = synthetic_questions()
        duplicate_questions["questions"].append(duplicate_questions["questions"][0])
        with self.assertRaisesRegex(ValueError, "duplicate question id"):
            tool.load_questions(io.StringIO(json.dumps(duplicate_questions)))

    def test_development_labels_and_unreviewed_gold_remain_visible(self):
        questions, ratings = self.load([synthetic_rating(1, "G0", None)])
        report = tool.render_report(questions, ratings)
        for label in (
            "非正式测试结果", "dataset split: `development_only`",
            "dataset status: `draft_requires_source_and_human_review`",
            "gold status（逐题标签计数）: draft=2", "未人工复核完成",
            "不能作为正式测试或 held-out 结果", "不作统计显著声明",
            "已有回答但尚无显式评分", "| G0 | 2 | 1 | 0 | 1 | 2 | 不可计算 | 0 |",
        ):
            self.assertIn(label, report)

    def test_cli_stdout_and_optional_markdown_output(self):
        # All file I/O is replaced with in-memory streams; nothing is saved.
        questions, ratings = self.load([])
        expected_report = tool.render_report(questions, ratings)
        for use_output in (False, True):
            with self.subTest(use_output=use_output):
                argv = ["--questions", "SYNTHETIC-questions.json", "--ratings", "SYNTHETIC-ratings.jsonl"]
                if use_output:
                    argv.extend(["--output", "SYNTHETIC-summary.md"])
                stdout = io.StringIO()
                sources = [io.StringIO(json.dumps(synthetic_questions())), io.StringIO("")]
                with patch.object(tool.Path, "open", side_effect=sources), \
                     patch.object(tool.Path, "write_text") as write, redirect_stdout(stdout):
                    self.assertEqual(tool.main(argv), 0)
                if use_output:
                    write.assert_called_once_with(expected_report, encoding="utf-8")
                    self.assertEqual(stdout.getvalue(), "")
                else:
                    write.assert_not_called()
                    self.assertEqual(stdout.getvalue(), expected_report)

    def test_cli_invalid_row_exits_without_publishing_partial_report(self):
        rows = [synthetic_rating(1, "G0", 1), synthetic_rating(99, "G0", 2)]
        sources = [io.StringIO(json.dumps(synthetic_questions())), io.StringIO(jsonl(rows))]
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(tool.Path, "open", side_effect=sources), \
             patch.object(tool.Path, "write_text") as write, \
             redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as error:
                tool.main([
                    "--questions", "SYNTHETIC-questions.json", "--ratings", "SYNTHETIC-ratings.jsonl",
                    "--output", "SYNTHETIC-summary.md",
                ])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("ratings line 2: unknown question_id", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
