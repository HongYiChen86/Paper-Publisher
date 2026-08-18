#!/usr/bin/env python3
"""Create polished 3:4 Xiaohongshu cards from a verified content manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


WIDTH, HEIGHT = 1242, 1656
MARGIN = 90


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", required=True, type=Path, help="content.json")
    parser.add_argument("--output", required=True, type=Path, help="Card output directory")
    return parser.parse_args()


def pick_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ["msyhbd.ttc", "simhei.ttf", "msyh.ttc"] if bold else ["msyh.ttc", "simhei.ttf"]
    candidates = [Path("C:/Windows/Fonts") / name for name in names]
    candidates += [
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    text = str(text).strip()
    if not text:
        return []
    lines: list[str] = []
    for paragraph in text.splitlines():
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            trial = current + char
            if current and draw.textbbox((0, 0), trial, font=font)[2] > max_width:
                lines.append(current)
                current = char
            else:
                current = trial
        if current:
            lines.append(current)
    return lines


def draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    xy: tuple[int, int],
    font: ImageFont.ImageFont,
    fill: str,
    spacing: int,
    max_lines: int | None = None,
) -> int:
    x, y = xy
    selected = lines if max_lines is None else lines[:max_lines]
    if max_lines is not None and len(lines) > max_lines and selected:
        selected[-1] = selected[-1].rstrip("。.!！?") + "…"
    for line in selected:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line or "字", font=font)
        y += (bbox[3] - bbox[1]) + spacing
    return y


def rounded_image(image: Image.Image, size: tuple[int, int], radius: int = 34) -> Image.Image:
    fitted = ImageOps.contain(image.convert("RGB"), size)
    canvas = Image.new("RGB", size, "white")
    x = (size[0] - fitted.width) // 2
    y = (size[1] - fitted.height) // 2
    canvas.paste(fitted, (x, y))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    canvas.putalpha(mask)
    return canvas


def resolve_source(card: dict, base_dir: Path) -> Image.Image | None:
    raw = card.get("source_image")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = base_dir / path
    if not path.is_file():
        raise FileNotFoundError(f"Card source image not found: {path}")
    image = Image.open(path).convert("RGB")
    crop = card.get("crop")
    if crop is not None:
        if not isinstance(crop, list) or len(crop) != 4:
            raise ValueError("crop must be [left, top, right, bottom]")
        left, top, right, bottom = [float(value) for value in crop]
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError(f"Invalid normalized crop: {crop}")
        image = image.crop((
            round(left * image.width), round(top * image.height),
            round(right * image.width), round(bottom * image.height),
        ))
    return image


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "card"


def render_card(card: dict, style: dict, index: int, total: int, base_dir: Path) -> Image.Image:
    bg = style.get("background", "#FFF8F4")
    fg = style.get("foreground", "#241F20")
    accent = style.get("accent", "#FF2442")
    muted = style.get("muted", "#736A6C")
    canvas = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle((MARGIN, 58, MARGIN + 190, 72), radius=7, fill=accent)
    kicker_font = pick_font(30, bold=True)
    title_font = pick_font(74, bold=True)
    subtitle_font = pick_font(36)
    bullet_font = pick_font(38)
    meta_font = pick_font(27)

    kicker = str(card.get("kicker", "PAPER NOTE"))
    draw.text((MARGIN, 105), kicker, font=kicker_font, fill=accent)
    title_lines = wrap(draw, str(card.get("title", "")), title_font, WIDTH - 2 * MARGIN)
    y = draw_lines(draw, title_lines, (MARGIN, 165), title_font, fg, 18, max_lines=3)
    subtitle = str(card.get("subtitle", "")).strip()
    if subtitle:
        y += 16
        y = draw_lines(
            draw, wrap(draw, subtitle, subtitle_font, WIDTH - 2 * MARGIN),
            (MARGIN, y), subtitle_font, muted, 12, max_lines=2,
        )

    source = resolve_source(card, base_dir)
    image_bottom = y
    if source is not None:
        image_top = max(y + 28, 420)
        image_height = 650 if card.get("kind") in {"method", "experiment"} else 520
        image_width = WIDTH - 2 * MARGIN
        framed = rounded_image(source, (image_width, image_height))
        canvas.paste(framed, (MARGIN, image_top), framed)
        image_bottom = image_top + image_height
        label = str(card.get("source_label", "")).strip()
        if label:
            label_right = MARGIN + 22 + min(720, 26 * len(label) + 34)
            draw.rounded_rectangle(
                (MARGIN + 22, image_bottom - 54, label_right, image_bottom - 12),
                radius=18, fill="#F4ECE9",
            )
            draw.text((MARGIN + 38, image_bottom - 50), label, font=meta_font, fill=muted)

    bullets = [str(value).strip() for value in card.get("bullets", []) if str(value).strip()]
    bullet_y = max(image_bottom + 42, 650 if source is None else image_bottom + 42)
    for bullet in bullets[:4]:
        if bullet_y > HEIGHT - 210:
            break
        draw.ellipse((MARGIN, bullet_y + 13, MARGIN + 18, bullet_y + 31), fill=accent)
        lines = wrap(draw, bullet, bullet_font, WIDTH - 2 * MARGIN - 48)
        bullet_y = draw_lines(draw, lines, (MARGIN + 42, bullet_y), bullet_font, fg, 11, max_lines=2) + 22

    footer_y = HEIGHT - 112
    draw.line((MARGIN, footer_y - 22, WIDTH - MARGIN, footer_y - 22), fill="#E7DEDB", width=2)
    tag = str(style.get("author_tag", "PAPER NOTE"))
    draw.text((MARGIN, footer_y), tag, font=meta_font, fill=muted)
    page_label = f"{index:02d} / {total:02d}"
    page_width = draw.textbbox((0, 0), page_label, font=meta_font)[2]
    draw.text((WIDTH - MARGIN - page_width, footer_y), page_label, font=meta_font, fill=muted)
    return canvas


def package_fingerprint(payload: dict) -> str:
    canonical = dict(payload)
    canonical.pop("package_fingerprint", None)
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def clean_topics(values: list[object]) -> list[str]:
    topics: list[str] = []
    seen: set[str] = set()
    for raw in values:
        topic = str(raw or "").strip().lstrip("#").strip()
        key = topic.casefold().replace(" ", "")
        if topic and key not in seen:
            seen.add(key)
            topics.append(topic)
    return topics


def absolute_or_empty(value: object, base_dir: Path) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return str(path.resolve())


def write_post_files(content: dict, card_paths: list[Path], output: Path) -> None:
    post = content.get("post", {})
    topic_values = post.get("topics", post.get("hashtags", []))
    topics = clean_topics(topic_values if isinstance(topic_values, list) else [])
    hashtags = [f"#{topic}" for topic in topics]
    body = str(post.get("body", "")).strip()
    title = str(post.get("title", "")).strip()
    post_text = f"# {title}\n\n{body}\n\n{' '.join(hashtags)}\n"
    root = output.parent
    (root / "post.md").write_text(post_text, encoding="utf-8")
    source = content.get("source", {}) if isinstance(content.get("source"), dict) else {}
    publish = content.get("publish", {}) if isinstance(content.get("publish"), dict) else {}
    originality = publish.get("originality", {}) if isinstance(publish.get("originality"), dict) else {}
    created_at = datetime.now(timezone.utc).isoformat()
    package = {
        "schema_version": 2,
        "platform": "xiaohongshu",
        "content_type": "image",
        "media_mode": "cards",
        "package_fingerprint": "",
        "created_at": created_at,
        "source": {
            "paper_pdf": absolute_or_empty(source.get("paper_pdf"), root),
            "paper_title": str(source.get("paper_title") or "").strip(),
            "selection_file": absolute_or_empty(source.get("selection_file", "selection.md"), root),
        },
        "media": [
            {"order": index, "path": str(path.resolve()), "ratio": "3:4"}
            for index, path in enumerate(card_paths, start=1)
        ],
        "form": {
            "title": title,
            "body": body,
            "topics": topics,
            "publish_mode": str(publish.get("mode", post.get("publish_mode", "draft"))),
            "scheduled_at": publish.get("scheduled_at", post.get("scheduled_at")),
            "timezone": str(publish.get("timezone", post.get("timezone", "Asia/Shanghai"))),
            "visibility": str(publish.get("visibility", "public")),
            "originality": {
                "enabled": originality.get("enabled") is True,
                "rights_confirmed": originality.get("rights_confirmed") is True,
                "basis": str(originality.get("basis", "paper commentary with cited figures")),
            },
        },
        "safety": {"final_submit_authorized": False},
    }
    package["package_fingerprint"] = package_fingerprint(package)
    (root / "publish_package.json").write_text(
        json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    state = {
        "schema_version": 1,
        "platform": "xiaohongshu",
        "package_fingerprint": package["package_fingerprint"],
        "status": "PREPARED",
        "phase": "prepare",
        "updated_at": created_at,
        "blocker": None,
        "gates": {
            "assets": {"ok": True, "evidence": {"count": len(card_paths)}},
            "preflight": {"ok": False, "evidence": {}},
        },
        "learning": {"incident_count": 0, "last_incident_id": None},
        "history": [{"phase": "prepare", "status": "PREPARED", "at": created_at}],
    }
    (root / "publish_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    args = parse_args()
    content_path = args.content.expanduser().resolve()
    if not content_path.is_file():
        raise SystemExit(f"Content file not found: {content_path}")
    content = json.loads(content_path.read_text(encoding="utf-8"))
    cards = content.get("cards")
    if not isinstance(cards, list) or not 4 <= len(cards) <= 5:
        raise SystemExit("content.json must contain 4 or 5 cards")
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    style = content.get("style", {})
    paths: list[Path] = []
    for index, card in enumerate(cards, start=1):
        image = render_card(card, style, index, len(cards), content_path.parent)
        path = output / f"{index:02d}-{slug(str(card.get('kind', 'card')))}.png"
        image.save(path, "PNG", optimize=True)
        paths.append(path)
    write_post_files(content, paths, output)
    print(json.dumps({
        "output": str(output),
        "card_count": len(paths),
        "cards": [str(path) for path in paths],
        "publish_package": str(output.parent / "publish_package.json"),
        "publish_state": str(output.parent / "publish_state.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
