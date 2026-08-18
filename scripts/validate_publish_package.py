#!/usr/bin/env python3
"""Validate a Xiaohongshu paper-carousel publish package before browser work."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from PIL import Image


VALID_MODES = {"draft", "immediate", "scheduled"}
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="publish_package.json")
    parser.add_argument("--write-fingerprint", action="store_true")
    parser.add_argument("--sync-state", action="store_true", help="Update sibling publish_state.json")
    return parser.parse_args()


def clean_topic(value: object) -> str:
    return str(value or "").strip().lstrip("#").strip()


def fingerprint(payload: dict) -> str:
    canonical = dict(payload)
    canonical.pop("package_fingerprint", None)
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def image_info(path: Path) -> tuple[int, int, str]:
    with Image.open(path) as image:
        return image.width, image.height, str(image.format or "").upper()


def parse_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def validate(payload: dict, package_path: Path, allow_fingerprint_refresh: bool = False) -> tuple[list[str], list[str], str]:
    errors: list[str] = []
    warnings: list[str] = []
    if payload.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if payload.get("platform") != "xiaohongshu":
        errors.append("platform must be xiaohongshu")
    if payload.get("content_type") != "image":
        errors.append("content_type must be image")
    media_mode = str(payload.get("media_mode") or "cards")
    if media_mode not in {"cards", "source_pages"}:
        errors.append("media_mode must be cards or source_pages")

    form = payload.get("form") if isinstance(payload.get("form"), dict) else {}
    title = str(form.get("title") or "").strip()
    body = str(form.get("body") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not title:
        errors.append("form.title is required")
    if len(title) > 20:
        errors.append(f"form.title is {len(title)}/20 Unicode codepoints")
    if "\\n" in title or "\\n" in body:
        errors.append("title/body contains literal escaped newline; use real newlines")
    if not body:
        errors.append("form.body is required for paper image posts")

    raw_topics = form.get("topics") if isinstance(form.get("topics"), list) else []
    topics = [clean_topic(value) for value in raw_topics]
    if not topics or any(not value for value in topics):
        errors.append("form.topics must contain non-empty topic names")
    folded = [value.casefold().replace(" ", "") for value in topics if value]
    if len(folded) != len(set(folded)):
        errors.append("form.topics contains duplicates")
    if len(topics) > 7:
        warnings.append("more than 7 topics may reduce focus; verify current platform behavior")

    mode = str(form.get("publish_mode") or "draft")
    if mode not in VALID_MODES:
        errors.append(f"form.publish_mode must be one of {sorted(VALID_MODES)}")
    scheduled = None
    try:
        scheduled = parse_datetime(form.get("scheduled_at"))
    except ValueError:
        errors.append("form.scheduled_at must be ISO 8601")
    if mode == "scheduled":
        if scheduled is None:
            errors.append("scheduled mode requires form.scheduled_at")
        elif scheduled.tzinfo is None or scheduled.utcoffset() is None:
            errors.append("form.scheduled_at must include a timezone offset")
        elif scheduled <= datetime.now(scheduled.tzinfo):
            errors.append("form.scheduled_at must be in the future")
    elif scheduled is not None:
        warnings.append("scheduled_at is set but publish_mode is not scheduled")

    collection = form.get("collection") if isinstance(form.get("collection"), dict) else {}
    if collection.get("enabled") is not True:
        errors.append("form.collection.enabled must be true")
    if not str(collection.get("name") or "").strip():
        errors.append("form.collection.name is required")

    originality = form.get("originality") if isinstance(form.get("originality"), dict) else {}
    if originality.get("enabled") is True and originality.get("rights_confirmed") is not True:
        errors.append("originality.enabled requires originality.rights_confirmed=true")
    if originality.get("requested_default") is True and originality.get("enabled") is not True:
        warnings.append("originality is planned but requires explicit rights confirmation before enabling")
    if payload.get("safety", {}).get("final_submit_authorized") is True:
        errors.append("final publish authorization must not be persisted in the package")

    media = payload.get("media") if isinstance(payload.get("media"), list) else []
    if not 4 <= len(media) <= 5:
        errors.append("media must contain 4 or 5 images")
    expected_orders = list(range(1, len(media) + 1))
    actual_orders = [item.get("order") for item in media if isinstance(item, dict)]
    if actual_orders != expected_orders:
        errors.append(f"media order must be consecutive: expected {expected_orders}, got {actual_orders}")
    seen_paths: set[Path] = set()
    for index, item in enumerate(media, start=1):
        if not isinstance(item, dict):
            errors.append(f"media[{index}] must be an object")
            continue
        raw_path = str(item.get("path") or "").strip()
        path = Path(raw_path)
        if raw_path and not path.is_absolute():
            path = (package_path.parent / path).resolve()
        else:
            path = path.expanduser().resolve() if raw_path else path
        if not raw_path or not path.is_file():
            errors.append(f"media[{index}] file not found: {raw_path or '(missing)'}")
            continue
        if path in seen_paths:
            errors.append(f"media[{index}] duplicates another path: {path}")
        seen_paths.add(path)
        file_size = path.stat().st_size
        if file_size > MAX_UPLOAD_BYTES:
            errors.append(
                f"media[{index}] exceeds 32 MiB upload limit: {file_size / (1024 * 1024):.2f} MiB"
            )
        try:
            width, height, fmt = image_info(path)
        except Exception as exc:
            errors.append(f"media[{index}] is not a readable image: {exc}")
            continue
        if fmt not in {"PNG", "JPEG", "WEBP"}:
            errors.append(f"media[{index}] unsupported format: {fmt}")
        ratio = width / height if height else 0
        if media_mode == "cards" and abs(ratio - 0.75) >= 0.01:
            errors.append(f"media[{index}] must be 3:4 in cards mode, got {width}x{height}")
        if width < 720 or height < 960:
            warnings.append(f"media[{index}] is below the reference 720x960 size: {width}x{height}")
        if media_mode == "cards" and item.get("ratio") != "3:4":
            errors.append(f"media[{index}].ratio must be 3:4 in cards mode")
        if media_mode == "source_pages":
            if item.get("ratio") != "original":
                errors.append(f"media[{index}].ratio must be original in source_pages mode")
            if item.get("presentation") != "source_page":
                errors.append(f"media[{index}].presentation must be source_page")
            if not isinstance(item.get("source_page"), int) or item.get("source_page") < 1:
                errors.append(f"media[{index}].source_page must be a positive integer")

    expected = fingerprint(payload)
    supplied = str(payload.get("package_fingerprint") or "")
    if supplied and supplied != expected:
        if allow_fingerprint_refresh:
            warnings.append("package_fingerprint refreshed after package edits")
        else:
            errors.append("package_fingerprint does not match package content")
    return errors, warnings, expected


def sync_state(package_path: Path, package_fingerprint: str, ok: bool, errors: list[str], warnings: list[str]) -> None:
    state_path = package_path.parent / "publish_state.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {
            "schema_version": 1,
            "platform": "xiaohongshu",
            "history": [],
            "gates": {},
        }
    now = datetime.now().astimezone().isoformat()
    old_fingerprint = state.get("package_fingerprint")
    fingerprint_changed = bool(old_fingerprint and old_fingerprint != package_fingerprint)
    if fingerprint_changed:
        state["gates"] = {}
    state.update({
        "package_fingerprint": package_fingerprint,
        "status": "PREFLIGHT_OK" if ok else "BLOCKED",
        "phase": "preflight",
        "updated_at": now,
        "blocker": None if ok else {
            "code": "ASSET_INVALID" if any("media" in error for error in errors) else "FORM_MISMATCH",
            "message": "; ".join(errors),
            "retryable": True,
            "requires_user": False,
        },
    })
    gates = state.setdefault("gates", {})
    gates["preflight"] = {
        "ok": ok,
        "evidence": {"errors": errors, "warnings": warnings, "fingerprint_changed": fingerprint_changed},
    }
    state.setdefault("history", []).append({
        "phase": "preflight",
        "status": state["status"],
        "at": now,
        "package_fingerprint": package_fingerprint,
        "invalidated_previous_gates": fingerprint_changed,
    })
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    package_path = args.package.expanduser().resolve()
    if not package_path.is_file():
        raise SystemExit(f"Package file not found: {package_path}")
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    errors, warnings, expected = validate(
        payload, package_path, allow_fingerprint_refresh=args.write_fingerprint
    )
    if args.write_fingerprint and not errors:
        payload["package_fingerprint"] = expected
        package_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.sync_state:
        sync_state(package_path, expected, not errors, errors, warnings)
    result = {
        "ok": not errors,
        "package": str(package_path),
        "fingerprint": expected,
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
