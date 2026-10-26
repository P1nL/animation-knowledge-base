"""Prepare source-v2 / final-v1 offline; optionally index sources locally, never generate."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from scripts import dify_local as d, export_knowledge, prepare_pilot as pilot
from scripts.prepare_pages import private_output

ROOT = d.ROOT


def frozen_inputs(accept_ai_reviewed: bool = False):
    if not accept_ai_reviewed:
        raise ValueError("Explicit acceptance of AI-reviewed references is required; not independent human review")
    questions = d.read_json(ROOT / "evaluation/final_v1.json")
    scope = d.read_json(ROOT / "corpus/releases/source-v2/scope.json")
    if (questions.get("split") != "held_out" or questions.get("dataset_version") != "final-v1"
            or questions.get("source_release") != scope.get("version") or scope.get("version") != "source-v2"
            or not all(questions.get(k) for k in ("frozen", "must_not_index", "must_not_use_for_tuning"))):
        raise ValueError("Expected frozen final-v1 bound to source-v2")
    qs = questions["questions"]
    if [q["id"] for q in qs] != [f"FINAL-{i:02}" for i in range(1, 31)]:
        raise ValueError("Expected exactly 30 frozen final questions")
    cards = export_knowledge.load_cards(ROOT / scope["cards_file"], include_drafts=True)
    if len(cards) != scope["card_count"] or len(cards) != 34:
        raise ValueError("Expected 34 frozen source cards")
    by_id = {c["id"]: c for c in cards}
    for q in qs:
        pages = set().union(*(set(by_id[i]["pdf_pages"]) for i in q["source_card_ids"]))
        if not set(q["source_pages"]) <= pages:
            raise ValueError("Question evidence is not bound to its source cards")
    return questions, scope, cards


def source_documents(scope: dict, cards: list[dict]) -> dict:
    raw = {}
    for filename in scope["raw_ocr_indices"]:
        indexpath = private_output(ROOT / filename)
        index = d.read_json(indexpath)
        for page in index["pages"]:
            number = page["pdf_page"]
            textpath = private_output(indexpath.parent / page["text_file"])
            if number in raw or textpath.parent != indexpath.parent:
                raise ValueError("Duplicate page or OCR batch escape")
            text = textpath.read_text(encoding="utf-8")
            raw[number] = (f"# 原始OCR：PDF第{number}页\n\n"
                           f"- 来源：{index['source_id']}\n- PDF 页码：{number}\n"
                           "- 状态：raw_ocr_uncorrected\n- 阅读顺序：engine_order_not_verified\n\n"
                           "## 原始识别文本（未校订）\n\n" + text)
    if len(raw) != 28 or set(raw) != set(scope["approved_pdf_pages"]):
        raise ValueError("Expected the frozen 28-page pool")
    return {"G1": [(f"page-{p:04}.md", raw[p]) for p in sorted(raw)],
            "G2": [(c["id"] + ".md", export_knowledge.render_card(c)) for c in cards]}


def prepare(output: Path, accept_ai_reviewed: bool = False) -> dict:
    output = private_output(output)
    if output.exists():
        raise ValueError("Output already exists; never overwrite frozen experiment inputs")
    questions, scope, cards = frozen_inputs(accept_ai_reviewed)
    documents = source_documents(scope, cards)
    config = {"split": "held_out", "dataset_version": "final-v1", "source_release": "source-v2",
              "question_count": 30, "planned_calls": 90, "maximum_output_tokens": 90 * 2048,
              "model": deepcopy(pilot.MODEL), "system_prompt": pilot.SYSTEM_PROMPT,
              "top_k": 4, "rerank": False, "node_retries": False, "chat_calls_authorized": False,
              "accept_ai_reviewed": True, "review_note": "AI references, not independent human gold",
              "source_counts": {"G0": 0, "G1": 28, "G2": 34},
              "model_version_note": "API alias; retain actual runtime data and date, not a pinned weight revision"}
    output.mkdir(parents=True)
    for name, data in (("config.json", config), ("questions.json", questions), ("scope.json", scope)):
        d.save_private(output / name, data)
    for group, entries in documents.items():
        directory = output / "sources" / group
        directory.mkdir(parents=True)
        for name, text in entries:
            (directory / name).write_text(text, encoding="utf-8")
    requests = [{"question_id": q["id"], "condition": g, "query": q["question"]}
                for q in questions["questions"] for g in pilot.CONDITIONS]
    (output / "requests.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests), encoding="utf-8")
    return config


def validate_bundle(output: Path):
    output = private_output(output)
    config = d.read_json(output / "config.json")
    questions, scope, cards = frozen_inputs(config.get("accept_ai_reviewed", False))
    if (config.get("split") != "held_out" or config.get("dataset_version") != "final-v1"
            or config.get("source_release") != "source-v2" or config.get("planned_calls") != 90
            or config.get("question_count") != 30 or config.get("model") != pilot.MODEL
            or config.get("system_prompt") != pilot.SYSTEM_PROMPT
            or config.get("top_k") != 4 or config.get("rerank") is not False
            or config.get("node_retries") is not False
            or config.get("source_counts") != {"G0": 0, "G1": 28, "G2": 34}):
        raise ValueError("Final batch configuration changed or is not supported")
    if d.read_json(output / "questions.json") != questions or d.read_json(output / "scope.json") != scope:
        raise ValueError("Frozen source/question snapshot changed; create a new version")
    requests = [json.loads(s) for s in (output / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
    expected = [{"question_id": q["id"], "condition": g, "query": q["question"]}
                for q in questions["questions"] for g in pilot.CONDITIONS]
    if requests != expected:
        raise ValueError("Expected exactly the 90 question-only requests, without gold or duplicates")
    for group, entries in source_documents(scope, cards).items():
        actual = {p.name: p.read_text(encoding="utf-8") for p in (output / "sources" / group).iterdir()}
        if actual != dict(entries):
            raise ValueError("Source snapshot changed or contains unexpected evaluation data")
    return config, requests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "work/final-v1")
    parser.add_argument("--accept-ai-reviewed", action="store_true")
    parser.add_argument("--index", action="store_true")
    args = parser.parse_args()
    if not args.output.exists():
        prepare(args.output, args.accept_ai_reviewed)
    validate_bundle(args.output)
    if args.index:
        state = d.read_json(ROOT / "work/local/dify-state.json")
        console = d.Console(state["origin"])
        console.login(d.read_json(ROOT / "work/local/admin.json"))
        state = pilot.index_sources(console, args.output)
        print(json.dumps({g: {"source_documents": s.get("completed_documents", 0),
                              "draft_saved": s.get("draft_saved", False)} for g, s in state["groups"].items()}))
    print("Prepared 90 question-only requests. No answer generation or publication.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
