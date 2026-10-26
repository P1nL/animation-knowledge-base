"""Extract the supplied book's single-image scans privately; no OCR or general PDF rendering."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAGES = "56-61,151-152,165-167,224"


def parse_pages(value: str, total: int) -> list[int]:
    selected: set[int] = set()
    for part in value.split(","):
        pieces = part.strip().split("-")
        if len(pieces) == 1 and pieces[0].isdigit():
            start = end = int(pieces[0])
        elif len(pieces) == 2 and all(piece.isdigit() for piece in pieces):
            start, end = map(int, pieces)
        else:
            raise ValueError(f"Invalid page range: {part!r}")
        if not 1 <= start <= end <= total:
            raise ValueError(f"Page range outside 1..{total}: {part!r}")
        selected.update(range(start, end + 1))
    if not selected:
        raise ValueError("Select at least one page")
    return sorted(selected)


def private_output(path: Path) -> Path:
    target = path.resolve()
    if not target.is_relative_to((ROOT / "work").resolve()):
        raise ValueError("Output must stay inside this repository's ignored work/ directory")
    return target


def prepare(source_config: Path, selection: str, output: Path) -> dict:
    from pypdf import PdfReader

    source = json.loads(source_config.read_text(encoding="utf-8"))
    original = Path(source["local_path"])
    output = private_output(output)
    with original.open("rb") as stream:
        document = PdfReader(stream)
        pages = parse_pages(selection, len(document.pages))
        output.mkdir(parents=True, exist_ok=True)
        index = {
            "source_id": source["source_id"],
            "source_title": source.get("title"),
            "document_pages": len(document.pages),
            "image_method": "single_embedded_scan_at_native_resolution",
            "general_pdf_rendering": False,
            "ocr_performed": False,
            "text_method": "existing_pdf_text_layer_only",
            "pages": [],
        }
        for number in pages:
            page = document.pages[number - 1]
            text = (page.extract_text() or "").strip()
            if len(page.images) != 1 or page.rotation or page.cropbox != page.mediabox or text:
                raise ValueError(f"Page {number} is not a supported single-image scan; inspect it separately")
            image_name = f"page-{number:04d}.png"
            image = page.images[0].image.convert("RGB")
            image.save(output / image_name, format="PNG")
            index["pages"].append({
                "pdf_page": number,
                "printed_page": None,
                "image_file": image_name,
                "image_width": image.width,
                "image_height": image.height,
                "text_file": None,
                "text_characters": len(text),
                "review_status": "not_reviewed_by_this_tool",
            })
        (output / "page_index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-config", type=Path, default=ROOT / "work/source.local.json")
    parser.add_argument("--pages", default=DEFAULT_PAGES)
    parser.add_argument("--output", type=Path, default=ROOT / "work/pages")
    args = parser.parse_args()
    try:
        index = prepare(args.source_config, args.pages, args.output)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    nonempty = sum(bool(page["text_characters"]) for page in index["pages"])
    print(f"Prepared {len(index['pages'])} private page images; {nonempty} have existing text.")
    print("OCR was NOT run. Empty text layers must not be reported as extracted OCR text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
