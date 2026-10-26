"""Run local PaddleOCR on prepared source pages; retain raw, unreviewed output."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path

from scripts.prepare_pages import ROOT, parse_pages, private_output

DETECTION_MODEL = "PP-OCRv5_mobile_det"
RECOGNITION_MODEL = "PP-OCRv5_server_rec"


def select_images(index_path: Path, selection: str) -> tuple[dict, list[tuple[dict, Path]]]:
    index_path = private_output(index_path)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    requested = parse_pages(selection, index["document_pages"])
    available = {page["pdf_page"]: page for page in index["pages"]}
    selected = []
    for number in requested:
        if number not in available:
            raise ValueError(f"Page {number} has no prepared image")
        page = available[number]
        image = private_output(index_path.parent / page["image_file"])
        if not image.is_file():
            raise ValueError(f"Prepared image missing for page {number}")
        selected.append((page, image))
    return index, selected


def extract_text(raw: dict) -> str:
    """Keep engine order and spelling; do not silently correct or merge columns."""
    payload = raw.get("res", raw)
    lines = payload.get("rec_texts")
    if not isinstance(lines, list) or any(not isinstance(line, str) for line in lines):
        raise ValueError("OCR result has no supported rec_texts array")
    return "\n".join(lines) + ("\n" if lines else "")


def create_engine(cpu_threads: int):
    # Download model weights only. Page images are supplied to the local pipeline.
    os.environ["PADDLE_PDX_MODEL_SOURCE"] = "BOS"
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(ROOT / "work/model-cache")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    from paddleocr import PaddleOCR

    return PaddleOCR(
        text_detection_model_name=DETECTION_MODEL,
        text_recognition_model_name=RECOGNITION_MODEL,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device="cpu",
        cpu_threads=cpu_threads,
        enable_mkldnn=False,
        text_det_limit_side_len=1536,
        text_det_limit_type="max",
    )


def run(index_path: Path, selection: str, output: Path, cpu_threads: int = 4) -> dict:
    output = private_output(output)
    if output.exists():
        raise ValueError("Use a new output directory; existing raw OCR must not be overwritten")
    if cpu_threads < 1:
        raise ValueError("cpu_threads must be positive")
    index, selected = select_images(index_path, selection)
    engine = create_engine(cpu_threads)
    output.mkdir(parents=True)
    manifest = {
        "source_id": index["source_id"],
        "source_title": index.get("source_title"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "engine": "PaddleOCR",
        "versions": {name: version(name) for name in ("paddleocr", "paddlepaddle", "paddlex")},
        "device": "cpu",
        "cpu_threads": cpu_threads,
        "enable_mkldnn": False,
        "detection_model": DETECTION_MODEL,
        "recognition_model": RECOGNITION_MODEL,
        "text_det_limit_side_len": 1536,
        "text_det_limit_type": "max",
        "document_orientation": False,
        "document_unwarping": False,
        "textline_orientation": False,
        "review_status": "needs_human_review",
        "reading_order": "engine_order_not_verified",
        "text_transform": "join_rec_texts_with_newlines_no_corrections",
        "pages": [],
    }
    for page, image in selected:
        number = page["pdf_page"]
        results = list(engine.predict(str(image)))
        if len(results) != 1:
            raise ValueError(f"Expected one OCR result for page {number}, got {len(results)}")
        raw_path = output / f"page-{number:04d}.json"
        results[0].save_to_json(str(raw_path))
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        text = extract_text(raw)
        text_path = output / f"page-{number:04d}.txt"
        text_path.write_text(text, encoding="utf-8")
        manifest["pages"].append({
            "pdf_page": number,
            "printed_page": page.get("printed_page"),
            "image_file": image.relative_to(ROOT).as_posix(),
            "raw_file": raw_path.name,
            "text_file": text_path.name,
            "text_characters": len(text),
            "recognized_lines": len(raw.get("res", raw)["rec_texts"]),
            "review_status": "needs_human_review",
        })
        # The index is a downstream input; update after each completed page.
        (output / "ocr_index.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Page {number}: {len(text)} raw OCR characters; not human-reviewed", flush=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page-index", type=Path, default=ROOT / "work/pages/page_index.json")
    parser.add_argument("--pages", default="151,165-166")
    parser.add_argument("--output", type=Path, default=ROOT / "work/ocr/sample-v1")
    parser.add_argument("--cpu-threads", type=int, default=4)
    args = parser.parse_args()
    try:
        manifest = run(args.page_index, args.pages, args.output, args.cpu_threads)
    except (ValueError, KeyError, OSError, ImportError) as error:
        parser.error(str(error))
    print(f"Completed {len(manifest['pages'])} pages locally. No upload, indexing or answer evaluation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
