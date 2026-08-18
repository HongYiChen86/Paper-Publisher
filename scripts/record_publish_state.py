#!/usr/bin/env python3
"""Atomically record a Xiaohongshu browser publishing phase and evidence."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


PHASES = {"prepare", "preview", "adapt", "preflight", "inspect", "upload", "mutate", "verify", "submit"}
CONTENT_CONFIRMATION_REQUIRED = {"upload", "mutate", "verify", "submit"}
BROWSER_GATES = {
    "authenticated", "contentType", "draftIdentity", "media", "title", "body", "topics",
    "collection", "originality", "schedule", "noBlockingDialog", "finalButton", "safety", "draftSaved",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path, help="publish_state.json")
    parser.add_argument("--package", required=True, type=Path, help="publish_package.json")
    parser.add_argument("--phase", required=True, choices=sorted(PHASES))
    parser.add_argument("--status", required=True)
    parser.add_argument("--gates-json", default="{}", help="JSON object merged into gates")
    parser.add_argument("--evidence-json", default="{}", help="JSON object stored in history")
    parser.add_argument("--blocker-code")
    parser.add_argument("--blocker-message")
    parser.add_argument("--retryable", action="store_true")
    parser.add_argument("--requires-user", action="store_true")
    return parser.parse_args()


def backup_path_for(path: Path) -> Path:
    return path.with_name(f"{path.stem}.backup{path.suffix}")


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    backup_temp_name: str | None = None
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        if path.is_file():
            backup = backup_path_for(path)
            backup_handle, backup_temp_name = tempfile.mkstemp(
                prefix=backup.name + ".", suffix=".tmp", dir=path.parent,
            )
            os.close(backup_handle)
            shutil.copyfile(path, backup_temp_name)
            os.replace(backup_temp_name, backup)
            backup_temp_name = None
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        if backup_temp_name and os.path.exists(backup_temp_name):
            os.unlink(backup_temp_name)


def read_state_with_recovery(state_path: Path, fingerprint: str) -> tuple[dict, dict | None]:
    if not state_path.is_file():
        return {"schema_version": 1, "platform": "xiaohongshu", "gates": {}, "history": []}, None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("publish state is not a JSON object")
        return state, None
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as primary_error:
        backup_path = backup_path_for(state_path)
        try:
            backup = json.loads(backup_path.read_text(encoding="utf-8"))
            if not isinstance(backup, dict):
                raise ValueError("publish state backup is not a JSON object")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as backup_error:
            raise SystemExit(
                "STATE_CORRUPT_NO_VALID_BACKUP: "
                f"primary={primary_error}; backup={backup_error}"
            )
        if str(backup.get("package_fingerprint") or "") != fingerprint:
            raise SystemExit("STATE_CORRUPT_NO_VALID_BACKUP: backup belongs to another package fingerprint")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        corrupt_path = state_path.with_name(f"{state_path.stem}.corrupt-{stamp}{state_path.suffix}")
        os.replace(state_path, corrupt_path)
        gates = backup.setdefault("gates", {})
        for key in BROWSER_GATES:
            gates.pop(key, None)
        recovered_at = datetime.now(timezone.utc).isoformat()
        recovery = {
            "at": recovered_at,
            "backup": str(backup_path),
            "corrupt": str(corrupt_path),
            "fingerprint": fingerprint,
        }
        backup.setdefault("recovery_events", []).append(recovery)
        backup["recovery_events"] = backup["recovery_events"][-20:]
        backup.update({
            "phase": "inspect",
            "status": "STATE_RECOVERED_REQUIRES_INSPECT",
            "updated_at": recovered_at,
            "blocker": {
                "code": "STATE_RECOVERED_REQUIRES_INSPECT",
                "message": "Recovered matching backup; fresh browser inspection is required",
                "retryable": True,
                "requires_user": False,
                "evidence": recovery,
            },
        })
        backup.setdefault("history", []).append({
            "phase": "inspect",
            "status": "STATE_RECOVERED_REQUIRES_INSPECT",
            "at": recovered_at,
            "blocker": backup["blocker"],
            "evidence": recovery,
        })
        atomic_write(state_path, backup)
        return backup, recovery


def main() -> int:
    args = parse_args()
    state_path = args.state.expanduser().resolve()
    package_path = args.package.expanduser().resolve()
    package = json.loads(package_path.read_text(encoding="utf-8"))
    fingerprint = str(package.get("package_fingerprint") or "")
    if not fingerprint:
        raise SystemExit("publish_package.json has no package_fingerprint")
    state, recovery = read_state_with_recovery(state_path, fingerprint)
    if recovery:
        print(json.dumps({
            "state": str(state_path),
            "phase": "inspect",
            "status": "STATE_RECOVERED_REQUIRES_INSPECT",
            "recovery": recovery,
            "package_fingerprint": fingerprint,
        }, ensure_ascii=False, indent=2))
        return 10
    existing = str(state.get("package_fingerprint") or "")
    if existing and existing != fingerprint:
        raise SystemExit("publish_state.json belongs to a different package fingerprint")
    gates = json.loads(args.gates_json)
    evidence = json.loads(args.evidence_json)
    if not isinstance(gates, dict) or not isinstance(evidence, dict):
        raise SystemExit("--gates-json and --evidence-json must be JSON objects")
    existing_gates = state.setdefault("gates", {})
    if gates.get("contentConfirmed") is True:
        if args.phase != "preview":
            raise SystemExit("contentConfirmed may only be granted while recording the preview phase")
        if not evidence.get("confirmation_scope"):
            raise SystemExit("content confirmation requires evidence.confirmation_scope")
    effective_content_confirmed = gates.get("contentConfirmed", existing_gates.get("contentConfirmed"))
    if args.phase in CONTENT_CONFIRMATION_REQUIRED and effective_content_confirmed is not True:
        raise SystemExit("CONTENT_CONFIRMATION_REQUIRED: record current-version user confirmation before browser mutation")
    now = datetime.now(timezone.utc).isoformat()
    blocker = None
    if args.blocker_code:
        blocker = {
            "code": args.blocker_code,
            "message": args.blocker_message or args.blocker_code,
            "retryable": args.retryable,
            "requires_user": args.requires_user,
            "evidence": evidence,
        }
    state.update({
        "schema_version": 1,
        "platform": "xiaohongshu",
        "package_fingerprint": fingerprint,
        "phase": args.phase,
        "status": args.status,
        "updated_at": now,
        "blocker": blocker,
    })
    state.setdefault("gates", {}).update(gates)
    state.setdefault("history", []).append({
        "phase": args.phase,
        "status": args.status,
        "at": now,
        "blocker": blocker,
        "evidence": evidence,
    })
    atomic_write(state_path, state)
    print(json.dumps({
        "state": str(state_path),
        "phase": args.phase,
        "status": args.status,
        "blocker": blocker,
        "package_fingerprint": fingerprint,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
