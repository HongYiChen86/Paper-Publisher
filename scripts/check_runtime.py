#!/usr/bin/env python3
"""Check the Python runtime required by the paper-to-Xiaohongshu pipeline."""

from __future__ import annotations

import importlib.util
import json
import sys
from importlib import metadata
from pathlib import Path


REQUIRED = {
    "PIL": "Pillow",
    "pypdf": "pypdf",
    "pypdfium2": "pypdfium2",
}


def package_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return ""


def main() -> int:
    modules = {
        module: {
            "available": importlib.util.find_spec(module) is not None,
            "distribution": distribution,
            "version": package_version(distribution),
        }
        for module, distribution in REQUIRED.items()
    }
    missing = [value["distribution"] for value in modules.values() if not value["available"]]
    result = {
        "ok": not missing,
        "python": sys.executable,
        "skill_root": str(Path(__file__).resolve().parent.parent),
        "modules": modules,
        "missing": missing,
        "repair_command": "" if not missing else f'"{sys.executable}" -m pip install ' + " ".join(missing),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())

