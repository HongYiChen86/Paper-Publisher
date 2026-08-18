#!/usr/bin/env python3
"""Extract PDF text, render pages, and rank likely paper-content pages."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pypdf import PdfReader


KEYWORDS = {
    "method": (
        "method", "methodology", "approach", "architecture", "framework",
        "pipeline", "overview", "network", "module", "algorithm", "模型",
        "方法", "框架", "架构", "流程", "模块",
    ),
    "experiment": (
        "experiment", "results", "benchmark", "comparison", "ablation",
        "accuracy", "performance", "evaluation", "dataset", "实验", "结果",
        "对比", "消融", "性能", "数据集", "准确率",
    ),
    "conclusion": (
        "conclusion", "discussion", "limitation", "future work", "结论", "局限",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Source PDF")
    parser.add_argument("--output", required=True, type=Path, help="Output directory")
    parser.add_argument("--dpi", type=int, default=144, help="Render DPI (default: 144)")
    parser.add_argument("--contact-columns", type=int, default=4)
    parser.add_argument("--contact-pages", type=int, default=20)
    return parser.parse_args()


def safe_text(page) -> str:
    try:
        text = page.extract_text() or ""
    except Exception:
        text = ""
    return re.sub(r"[ \t]+", " ", text).strip()


def score_text(text: str) -> dict[str, int]:
    lower = text.lower()
    scores: dict[str, int] = {}
    for group, words in KEYWORDS.items():
        scores[group] = sum(lower.count(word.lower()) for word in words)
    figure_hits = len(re.findall(r"\b(fig(?:ure)?|table|algorithm)\s*\d+", lower))
    scores["visual"] = figure_hits
    scores["method"] += figure_hits
    scores["experiment"] += 2 * len(re.findall(r"\btable\s*\d+", lower))
    return scores


def font(size: int) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def render_pages(pdf_path: Path, pages_dir: Path, dpi: int) -> list[Path]:
    document = pdfium.PdfDocument(str(pdf_path))
    scale = dpi / 72.0
    outputs: list[Path] = []
    for index in range(len(document)):
        page = document[index]
        bitmap = page.render(scale=scale, rotation=0)
        image = bitmap.to_pil().convert("RGB")
        path = pages_dir / f"page-{index + 1:03d}.png"
        image.save(path, "PNG", optimize=True)
        outputs.append(path)
        page.close()
    document.close()
    return outputs


def make_contact_sheets(
    page_paths: list[Path], output: Path, columns: int, per_sheet: int
) -> list[Path]:
    thumb_size = (250, 330)
    gap = 24
    label_height = 42
    sheet_paths: list[Path] = []
    label_font = font(24)
    for chunk_start in range(0, len(page_paths), per_sheet):
        chunk = page_paths[chunk_start : chunk_start + per_sheet]
        rows = math.ceil(len(chunk) / columns)
        canvas = Image.new(
            "RGB",
            (columns * thumb_size[0] + (columns + 1) * gap,
             rows * (thumb_size[1] + label_height) + (rows + 1) * gap),
            "#EDE8E5",
        )
        draw = ImageDraw.Draw(canvas)
        for offset, page_path in enumerate(chunk):
            row, col = divmod(offset, columns)
            x = gap + col * (thumb_size[0] + gap)
            y = gap + row * (thumb_size[1] + label_height + gap)
            with Image.open(page_path) as source:
                thumb = ImageOps.contain(source.convert("RGB"), thumb_size)
            px = x + (thumb_size[0] - thumb.width) // 2
            py = y + (thumb_size[1] - thumb.height) // 2
            canvas.paste(thumb, (px, py))
            page_number = chunk_start + offset + 1
            draw.text((x, y + thumb_size[1] + 7), f"PDF {page_number}", fill="#241F20", font=label_font)
        sheet_number = len(sheet_paths) + 1
        path = output / f"contact-sheet-{sheet_number:02d}.png"
        canvas.save(path, "PNG", optimize=True)
        sheet_paths.append(path)
    return sheet_paths


def best_pages(pages: list[dict], key: str, limit: int = 4) -> list[int]:
    ranked = sorted(
        pages,
        key=lambda item: (item["scores"].get(key, 0), item["scores"].get("visual", 0)),
        reverse=True,
    )
    return [item["page_number"] for item in ranked[:limit] if item["scores"].get(key, 0) > 0]


def main() -> int:
    args = parse_args()
    pdf_path = args.input.expanduser().resolve()
    if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
        raise SystemExit(f"Input must be an existing PDF: {pdf_path}")
    if args.dpi < 72 or args.dpi > 300:
        raise SystemExit("--dpi must be between 72 and 300")

    output = args.output.expanduser().resolve()
    pages_dir = output / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(pdf_path))
    texts = [safe_text(page) for page in reader.pages]
    rendered = render_pages(pdf_path, pages_dir, args.dpi)
    if len(rendered) != len(texts):
        raise RuntimeError("Rendered page count does not match extracted page count")

    page_records = []
    for index, (text, image_path) in enumerate(zip(texts, rendered), start=1):
        page_records.append(
            {
                "page_number": index,
                "image": str(image_path.relative_to(output)).replace("\\", "/"),
                "text_excerpt": text[:1800],
                "text_length": len(text),
                "scores": score_text(text),
            }
        )

    first_lines = [line.strip() for line in texts[0].splitlines() if line.strip()] if texts else []
    title_hint = first_lines[0][:300] if first_lines else pdf_path.stem
    contacts = make_contact_sheets(
        rendered, output, max(2, args.contact_columns), max(4, args.contact_pages)
    )
    manifest = {
        "source_pdf": str(pdf_path),
        "title_hint": title_hint,
        "page_count": len(page_records),
        "render_dpi": args.dpi,
        "pages": page_records,
        "candidates": {
            "cover": [1] if page_records else [],
            "method": best_pages(page_records, "method"),
            "experiment": best_pages(page_records, "experiment"),
            "conclusion": best_pages(page_records, "conclusion"),
        },
        "contact_sheets": [path.name for path in contacts],
        "note": "Keyword rankings are hints only; visually inspect all selected pages.",
    }
    (output / "paper_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "paper.txt").write_text(
        "\n\n".join(f"===== PDF PAGE {i} =====\n{text}" for i, text in enumerate(texts, start=1)),
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(output),
        "page_count": len(page_records),
        "manifest": str(output / "paper_manifest.json"),
        "contact_sheets": [str(path) for path in contacts],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
