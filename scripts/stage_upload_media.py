#!/usr/bin/env python3
"""Stage publish-package media at short ASCII paths without changing bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--root", type=Path, help="Optional ASCII staging root")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    package_path = args.package.expanduser().resolve()
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    media = sorted(payload.get("media", []), key=lambda item: int(item.get("order", 0)))
    if not media or [int(item.get("order", 0)) for item in media] != list(range(1, len(media) + 1)):
        raise SystemExit("media must be non-empty and continuously ordered from 1")

    fingerprint = str(payload.get("package_fingerprint") or "no-fingerprint")
    short_id = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
    root = (args.root or Path(tempfile.gettempdir()) / "xhs-paper-publisher").expanduser().resolve()
    if not str(root).isascii():
        raise SystemExit("staging root must use an ASCII-only path; pass --root with a short ASCII path")
    staging = root / short_id
    staging.mkdir(parents=True, exist_ok=True)

    staged_files: list[dict] = []
    for item in media:
        source = Path(str(item.get("path") or "")).expanduser().resolve()
        if not source.is_file():
            raise SystemExit(f"media file missing: {source}")
        suffix = source.suffix.lower()
        target = staging / f"{int(item['order']):02d}{suffix}"
        source_hash = sha256(source)
        if not target.is_file() or sha256(target) != source_hash:
            shutil.copyfile(source, target)
        target_hash = sha256(target)
        if target_hash != source_hash:
            raise SystemExit(f"staged file hash mismatch: {target}")
        staged_files.append({
            "order": int(item["order"]),
            "source": str(source),
            "staged": str(target),
            "sha256": source_hash,
        })

    print(json.dumps({
        "ok": True,
        "package": str(package_path),
        "staging_dir": str(staging),
        "files": staged_files,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
