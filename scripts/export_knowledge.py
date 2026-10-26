"""Export source-only knowledge cards as local Markdown; never upload them."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def load_cards(path: Path, include_drafts: bool = False) -> list[dict]:
    if not path.resolve().is_relative_to((ROOT / "corpus").resolve()):
        raise ValueError("Only corpus/ is an import source; evaluation data is not knowledge")
    cards = []
    seen = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        card = json.loads(line)
        identifier = card.get("id", "")
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", identifier):
            raise ValueError(f"Line {line_number}: invalid card id")
        if identifier in seen:
            raise ValueError(f"Duplicate card id: {identifier}")
        seen.add(identifier)
        for field in ("source_id", "term_ja", "title_zh", "context", "summary_zh", "extraction_method"):
            if not isinstance(card.get(field), str) or not card[field].strip():
                raise ValueError(f"{identifier}: missing {field}")
        pages = card.get("pdf_pages")
        if not isinstance(pages, list) or not pages or any(type(page) is not int or page < 1 for page in pages):
            raise ValueError(f"{identifier}: invalid source pages")
        status = card.get("review_status")
        if status != "human_reviewed" and not (include_drafts and status == "needs_human_review"):
            raise ValueError(f"{identifier}: not human-reviewed; use --include-drafts only for internal preparation")
        cards.append(card)
    if not cards:
        raise ValueError("No source cards")
    return cards


def render_card(card: dict) -> str:
    lines = [
        f"# {card['title_zh']}",
        "",
        f"- 条目 ID：{card['id']}",
        f"- 日文术语：{card['term_ja']}",
        f"- 语境：{card['context']}",
        f"- 来源：{card['source_id']}",
        f"- PDF 页码：{', '.join(map(str, card['pdf_pages']))}",
        f"- 整理方法：{card['extraction_method']}",
        f"- 校订状态：{card['review_status']}",
        "",
    ]
    if card["review_status"] != "human_reviewed":
        lines.extend(["**内部草案：尚待人工校订，不是已确认的知识或评测真值。**", ""])
    lines.extend(["## 资料概括", "", card["summary_zh"], ""])
    if card.get("original_excerpt_ja"):
        lines.extend(["## 必要日文原句", "", card["original_excerpt_ja"], ""])
    if card.get("ambiguities"):
        lines.extend(["## 语境和边界", ""] + [f"- {item}" for item in card["ambiguities"]] + [""])
    if card.get("related_terms"):
        lines.extend(["相关术语：" + "、".join(card["related_terms"]), ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards", type=Path, default=ROOT / "corpus/curated/book_cards.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "work/dify-import")
    parser.add_argument("--include-drafts", action="store_true")
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        if not output.is_relative_to((ROOT / "work").resolve()):
            raise ValueError("Exports must remain in ignored work/ until publication scope is approved")
        cards = load_cards(args.cards, args.include_drafts)
        output.mkdir(parents=True, exist_ok=True)
        for card in cards:
            (output / f"{card['id']}.md").write_text(render_card(card), encoding="utf-8")
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    print(f"Exported {len(cards)} local Markdown source cards. No upload or indexing was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
