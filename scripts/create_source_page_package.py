#!/usr/bin/env python3
"""Create a Xiaohongshu draft package from unmodified rendered PDF pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", required=True, type=Path, help="source-pages content.json")
    parser.add_argument("--output", required=True, type=Path, help="output outbox directory")
    return parser.parse_args()


def fingerprint(payload: dict) -> str:
    canonical = dict(payload)
    canonical.pop("package_fingerprint", None)
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
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


def resolve_path(value: object, base_dir: Path) -> Path:
    path = Path(str(value or "").strip()).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def main() -> int:
    args = parse_args()
    content_path = args.content.expanduser().resolve()
    if not content_path.is_file():
        raise SystemExit(f"Content file not found: {content_path}")
    content = json.loads(content_path.read_text(encoding="utf-8"))
    pages = content.get("source_pages")
    if not isinstance(pages, list) or not 4 <= len(pages) <= 5:
        raise SystemExit("content.json must contain 4 or 5 source_pages")

    output = args.output.expanduser().resolve()
    media_dir = output / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    media: list[dict] = []
    expected_orders = list(range(1, len(pages) + 1))
    actual_orders = [item.get("order") for item in pages if isinstance(item, dict)]
    if actual_orders != expected_orders:
        raise SystemExit(f"source_pages order must be {expected_orders}, got {actual_orders}")
    for item in pages:
        source = resolve_path(item.get("path"), content_path.parent)
        if not source.is_file():
            raise SystemExit(f"Source page not found: {source}")
        page_number = int(item.get("source_page"))
        target = media_dir / f"{item['order']:02d}-pdf-page-{page_number:03d}{source.suffix.lower()}"
        shutil.copy2(source, target)
        media.append({
            "order": item["order"],
            "path": str(target),
            "ratio": "original",
            "presentation": "source_page",
            "source_page": page_number,
        })

    source = content.get("source", {}) if isinstance(content.get("source"), dict) else {}
    post = content.get("post", {}) if isinstance(content.get("post"), dict) else {}
    publish = content.get("publish", {}) if isinstance(content.get("publish"), dict) else {}
    originality = publish.get("originality", {}) if isinstance(publish.get("originality"), dict) else {}
    collection = publish.get("collection", {}) if isinstance(publish.get("collection"), dict) else {}
    topics = clean_topics(post.get("topics", []) if isinstance(post.get("topics"), list) else [])
    title = str(post.get("title") or "").strip()
    body = str(post.get("body") or "").strip()
    created_at = datetime.now(timezone.utc).isoformat()
    package = {
        "schema_version": 2,
        "platform": "xiaohongshu",
        "content_type": "image",
        "media_mode": "source_pages",
        "package_fingerprint": "",
        "created_at": created_at,
        "source": {
            "paper_pdf": str(resolve_path(source.get("paper_pdf"), content_path.parent)),
            "paper_title": str(source.get("paper_title") or "").strip(),
            "selection_file": str(resolve_path(source.get("selection_file", "selection.md"), content_path.parent)),
        },
        "media": media,
        "form": {
            "title": title,
            "body": body,
            "topics": topics,
            "publish_mode": str(publish.get("mode", "draft")),
            "scheduled_at": publish.get("scheduled_at"),
            "timezone": str(publish.get("timezone", "Asia/Shanghai")),
            "visibility": str(publish.get("visibility", "public")),
            "collection": {
                "enabled": collection.get("enabled") is not False,
                "name": str(collection.get("name", "论文分享")).strip() or "论文分享",
            },
            "originality": {
                "enabled": originality.get("enabled") is True,
                "requested_default": originality.get("requested_default") is not False,
                "rights_confirmed": originality.get("rights_confirmed") is True,
                "basis": str(originality.get("basis", "paper commentary using original PDF pages")),
            },
        },
        "safety": {"final_submit_authorized": False},
    }
    package["package_fingerprint"] = fingerprint(package)
    output.mkdir(parents=True, exist_ok=True)
    (output / "publish_package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    hashtags = " ".join(f"#{topic}" for topic in topics)
    (output / "post.md").write_text(f"# {title}\n\n{body}\n\n{hashtags}\n", encoding="utf-8")
    state = {
        "schema_version": 1,
        "platform": "xiaohongshu",
        "package_fingerprint": package["package_fingerprint"],
        "status": "PREPARED",
        "phase": "prepare",
        "updated_at": created_at,
        "blocker": None,
        "gates": {
            "assets": {"ok": True, "evidence": {"count": len(media), "media_mode": "source_pages"}},
            "preflight": {"ok": False, "evidence": {}},
        },
        "learning": {"incident_count": 0, "last_incident_id": None},
        "history": [{"phase": "prepare", "status": "PREPARED", "at": created_at}],
    }
    (output / "publish_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "media_mode": "source_pages",
        "page_count": len(media),
        "media": [item["path"] for item in media],
        "publish_package": str(output / "publish_package.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
