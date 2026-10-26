"""Offline, standard-library-only summary of saved answers and supplied scores."""

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import TextIO


CONDITIONS = ("G0", "G1", "G2")


@dataclass(frozen=True)
class QuestionSet:
    split: str
    status: str
    gold_statuses: dict[str, str]


def load_questions(source: TextIO) -> QuestionSet:
    """Read only the metadata and IDs needed to define the denominators."""
    try:
        data = json.load(source)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"questions line {error.lineno}: invalid JSON: {error.msg}"
        ) from error
    if not isinstance(data, dict):
        raise ValueError("questions: expected a JSON object")
    for field in ("split", "status"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"questions: {field} must be a non-empty string")
    if not isinstance(data.get("questions"), list):
        raise ValueError("questions: questions must be an array")

    gold_statuses = {}
    for position, question in enumerate(data["questions"], start=1):
        context = f"questions item {position}"
        if not isinstance(question, dict):
            raise ValueError(f"{context}: expected an object")
        for field in ("id", "gold_status"):
            if not isinstance(question.get(field), str) or not question[field].strip():
                raise ValueError(f"{context}: {field} must be a non-empty string")
        question_id = question["id"]
        if question_id in gold_statuses:
            raise ValueError(f"{context}: duplicate question id: {question_id!r}")
        gold_statuses[question_id] = question["gold_status"]
    return QuestionSet(data["split"], data["status"], gold_statuses)


def load_ratings(source: TextIO, questions: QuestionSet) -> dict:
    """Reject invalid rows rather than repairing, skipping, or overwriting them."""
    ratings = {}
    for line_number, line in enumerate(source, start=1):
        if not line.strip():
            continue
        context = f"ratings line {line_number}"
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{context}: invalid JSON: {error.msg}") from error
        if not isinstance(row, dict):
            raise ValueError(f"{context}: expected a JSON object")
        for field in ("question_id", "condition", "answer_text", "score"):
            if field not in row:
                raise ValueError(f"{context}: missing required field: {field}")

        question_id, condition = row["question_id"], row["condition"]
        if not isinstance(question_id, str) or question_id not in questions.gold_statuses:
            raise ValueError(f"{context}: unknown question_id: {question_id!r}")
        if not isinstance(condition, str) or condition not in CONDITIONS:
            raise ValueError(f"{context}: unknown condition: {condition!r}")
        key = (question_id, condition)
        if key in ratings:
            raise ValueError(f"{context}: duplicate (question_id, condition): {key!r}")
        if not isinstance(row["answer_text"], str):
            raise ValueError(f"{context}: answer_text must be a string")
        score = row["score"]
        # bool is an int subclass, but JSON true/false are not explicit scores.
        if score is not None and (type(score) is not int or score not in (0, 1, 2)):
            raise ValueError(f"{context}: score must be integer 0, 1, 2 or null")
        reviewer = row.get("reviewer")
        if reviewer is not None and not isinstance(reviewer, str):
            raise ValueError(f"{context}: reviewer must be a string or null")
        if score is not None:
            if not row["answer_text"].strip():
                raise ValueError(f"{context}: scored rows require a non-empty answer_text")
            if reviewer is None or not reviewer.strip():
                raise ValueError(f"{context}: scored rows require a non-empty reviewer")
        ratings[key] = row
    return ratings


def summarize(questions: QuestionSet, ratings: dict) -> dict:
    """Use scored subsets for means and matched subsets for paired differences."""
    expected = len(questions.gold_statuses)
    groups = {}
    for condition in CONDITIONS:
        rows = [row for (_, group), row in ratings.items() if group == condition]
        answered = sum(bool(row["answer_text"].strip()) for row in rows)
        scores = [row["score"] for row in rows if row["score"] is not None]
        groups[condition] = {
            "expected": expected,
            "answered": answered,
            "scored": len(scores),
            "missing_answers": expected - answered,
            "missing_scores": expected - len(scores),
            "mean": sum(scores) / len(scores) if scores else None,
        }

    pairs = {}
    for condition in ("G1", "G2"):
        differences = []
        for question_id in questions.gold_statuses:
            baseline = ratings.get((question_id, "G0"))
            comparison = ratings.get((question_id, condition))
            if baseline is not None and comparison is not None:
                if baseline["score"] is not None and comparison["score"] is not None:
                    differences.append(comparison["score"] - baseline["score"])
        pairs[f"G0-{condition}"] = {
            "definition": f"{condition} - G0",
            "paired": len(differences),
            "mean_difference": sum(differences) / len(differences) if differences else None,
        }
    return {"groups": groups, "pairs": pairs}


def render_report(questions: QuestionSet, ratings: dict) -> str:
    summary = summarize(questions, ratings)
    title = (
        "开发预实验离线汇总（非正式测试结果）"
        if questions.split == "development_only"
        else "离线评测汇总（仅复述输入证据）"
    )
    gold_counts = Counter(questions.gold_statuses.values())
    gold_label = ", ".join(f"{status}={count}" for status, count in sorted(gold_counts.items()))
    lines = [
        f"# {title}",
        "",
        f"- dataset split: `{questions.split}`",
        f"- dataset status: `{questions.status}`",
        f"- gold status（逐题标签计数）: {gold_label or '无题目'}",
        f"- 每组预期题数: {len(questions.gold_statuses)}",
        "",
    ]
    if questions.split == "development_only":
        lines.extend([
            "> 这是 development_only 开发预实验，不能作为正式测试或 held-out 结果。",
            "",
        ])
    if "draft" in gold_counts or questions.status == "draft_requires_source_and_human_review":
        lines.extend([
            "> gold 尚有草案或待核对状态，未人工复核完成；本工具不将其提升为已确认真值。",
            "",
        ])
    if not any(group["answered"] for group in summary["groups"].values()):
        lines.extend(["没有结果：尚无非空回答；均分和配对差值不可计算。", ""])
    elif not any(group["scored"] for group in summary["groups"].values()):
        lines.extend(["已有回答但尚无显式评分；均分和配对差值不可计算。", ""])

    lines.extend([
        "## 分组覆盖与评分",
        "",
        "| 组 | 预期题数 | 已回答 | 已评分 | 缺失回答 | 缺失评分 | 均分（0-2） | 均分分母 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ])
    for condition, group in summary["groups"].items():
        mean = "不可计算" if group["mean"] is None else f"{group['mean']:.3f}"
        lines.append(
            f"| {condition} | {group['expected']} | {group['answered']} | {group['scored']} "
            f"| {group['missing_answers']} | {group['missing_scores']} | {mean} | {group['scored']} |"
        )
    lines.extend([
        "",
        "已回答指 answer_text 非空且非纯空白；已评分指有显式 0/1/2 分及非空 reviewer 的已保存回答。",
        "缺失回答 = 预期题数 - 已回答；缺失评分 = 预期题数 - 已评分（包含未回答题）。",
        "均分 = 已评分题分数之和 / 已评分题数；0 分计入分母，null 和缺失不补为 0。",
        "这些是完成数量与评分均值，不是全体题的准确率。",
        "",
        "## 配对差值",
        "",
        "| 对照 | 差值方向 | 配对数（分母） | 配对平均差值 |",
        "| --- | --- | ---: | --- |",
    ])
    for label, pair in summary["pairs"].items():
        difference = (
            "不可计算" if pair["mean_difference"] is None else f"{pair['mean_difference']:+.3f}"
        )
        lines.append(f"| {label} | {pair['definition']} | {pair['paired']} | {difference} |")
    lines.extend([
        "",
        "各对照仅取两组都有评分的同题交集：先逐题相减，再对差值取均值。",
        "正值表示该配对子集上 G1/G2 分数高于 G0；不相减各组不同子集的总体均分。",
        "两项对照的交集可以不同；无配对时不可计算，不作统计显著声明。",
        "",
        "## 逐题状态",
        "",
        "| 题号 | G0 | G1 | G2 |",
        "| --- | --- | --- | --- |",
    ])
    for question_id in questions.gold_statuses:
        cells = []
        for condition in CONDITIONS:
            row = ratings.get((question_id, condition))
            if row is None or not row["answer_text"].strip():
                cells.append("缺失回答 / 未评分")
            elif row["score"] is None:
                cells.append("已回答 / 未评分")
            else:
                cells.append(str(row["score"]))
        lines.append(f"| {question_id} | {' | '.join(cells)} |")
    lines.extend([
        "",
        "## 证据边界",
        "",
        "- 仅汇总输入中的已保存回答状态与显式评分；不生成答案、不以关键词命中判对、不调用模型裁判。",
        "- 所有组均原样使用输入 score；G0 没有引文不扣答案分，citations 不参与计分。",
        "- 完整回答、reviewer、notes、citations 保留在输入 JSONL；此报告不推断失败原因或引用支持度。",
        "- split、gold status 与 reviewer 均来自输入；本工具不验证人工审核事实，也不自动认定正式测试资格。",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True, help="question JSON with split and gold status")
    parser.add_argument("--ratings", type=Path, required=True, help="saved answers and supplied scores, in JSONL")
    parser.add_argument("--output", type=Path, help="write Markdown here instead of stdout")
    args = parser.parse_args(argv)
    try:
        if args.output is not None and args.output.resolve() in {
            args.questions.resolve(), args.ratings.resolve()
        }:
            raise ValueError("--output must differ from --questions and --ratings")
        with args.questions.open(encoding="utf-8-sig") as source:
            questions = load_questions(source)
        with args.ratings.open(encoding="utf-8-sig") as source:
            ratings = load_ratings(source, questions)
        report = render_report(questions, ratings)
        if args.output is None:
            print(report, end="")
        else:
            args.output.write_text(report, encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
