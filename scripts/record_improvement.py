#!/usr/bin/env python3
"""Record and promote sanitized learning events for the Xiaohongshu skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


CATEGORIES = {
    "content", "asset", "platform-rule", "ui-drift", "browser-channel",
    "runtime", "transient", "auth-risk", "user-correction",
}
STAGES = {"prepare", "preview", "adapt", "preflight", "inspect", "upload", "mutate", "verify", "submit"}
SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(cookie|password|passwd|token|secret|验证码)\b\s*[:=]\s*\S+"),
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def sanitize(value: object) -> str:
    text = str(value or "").strip()
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]", text)
    return text[:4000]


def event_path(outbox: Path) -> Path:
    folder = outbox / "learning"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "incidents.jsonl"


def read_events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def append_event(path: Path, event: dict) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def package_fingerprint(outbox: Path) -> str:
    package = outbox / "publish_package.json"
    if not package.is_file():
        return ""
    try:
        return str(json.loads(package.read_text(encoding="utf-8")).get("package_fingerprint") or "")
    except (OSError, json.JSONDecodeError):
        return ""


def update_state(outbox: Path, incident_id: str, status: str) -> None:
    state_path = outbox / "publish_state.json"
    if not state_path.is_file():
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    learning = state.setdefault("learning", {})
    learning["incident_count"] = int(learning.get("incident_count", 0)) + (1 if status == "observed" else 0)
    learning["last_incident_id"] = incident_id
    learning["last_status"] = status
    learning["updated_at"] = now_iso()
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def make_incident_id(code: str, recurrence_key: str, observed: str) -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    digest = hashlib.sha256(f"{code}|{recurrence_key}|{observed}|{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"inc-{stamp}-{digest}"


def command_record(args: argparse.Namespace) -> int:
    outbox = args.outbox.expanduser().resolve()
    outbox.mkdir(parents=True, exist_ok=True)
    recurrence_key = sanitize(args.recurrence_key) or f"{args.category}:{args.code.lower()}"
    observed = sanitize(args.observed)
    incident_id = make_incident_id(args.code, recurrence_key, observed)
    event = {
        "event": "incident_observed",
        "incident_id": incident_id,
        "at": now_iso(),
        "stage": args.stage,
        "code": args.code,
        "category": args.category,
        "recurrence_key": recurrence_key,
        "expected": sanitize(args.expected),
        "observed": observed,
        "evidence": sanitize(args.evidence),
        "local_fix": sanitize(args.local_fix),
        "package_fingerprint": package_fingerprint(outbox),
        "status": "observed",
    }
    path = event_path(outbox)
    append_event(path, event)
    update_state(outbox, incident_id, "observed")
    print(json.dumps({"ok": True, "incident_id": incident_id, "log": str(path)}, ensure_ascii=False, indent=2))
    return 0


def command_promote(args: argparse.Namespace) -> int:
    outbox = args.outbox.expanduser().resolve()
    path = event_path(outbox)
    events = read_events(path)
    incident = next(
        (item for item in events if item.get("event") == "incident_observed" and item.get("incident_id") == args.incident_id),
        None,
    )
    if incident is None:
        raise SystemExit(f"Incident not found: {args.incident_id}")
    if incident.get("category") in {"auth-risk", "transient"}:
        raise SystemExit(f"Category {incident.get('category')} cannot be auto-promoted")
    if not args.changed_file or not args.verification:
        raise SystemExit("Promotion requires --changed-file and --verification")

    skill_root = Path(__file__).resolve().parent.parent
    changed_files: list[str] = []
    for raw in args.changed_file:
        candidate = Path(raw)
        resolved = candidate.resolve() if candidate.is_absolute() else (skill_root / candidate).resolve()
        try:
            relative = resolved.relative_to(skill_root)
        except ValueError as exc:
            raise SystemExit(f"Changed file must stay inside the skill: {raw}") from exc
        if not resolved.is_file():
            raise SystemExit(f"Changed file does not exist: {raw}")
        changed_files.append(relative.as_posix())

    registry_path = (args.registry or (skill_root / "references" / "learned-rules.json")).expanduser().resolve()
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    else:
        registry = {"schema_version": 1, "updated_at": now_iso(), "rules": []}
    rules = registry.setdefault("rules", [])
    recurrence_key = str(incident.get("recurrence_key") or "")
    rule_id = "rule-" + hashlib.sha256(recurrence_key.encode("utf-8")).hexdigest()[:12]
    rule = {
        "rule_id": rule_id,
        "recurrence_key": recurrence_key,
        "category": incident.get("category"),
        "root_cause": sanitize(args.root_cause),
        "fix_summary": sanitize(args.fix_summary),
        "changed_files": changed_files,
        "verification": [sanitize(value) for value in args.verification],
        "source_incident": args.incident_id,
        "promoted_at": now_iso(),
        "status": "active",
    }
    rules[:] = [item for item in rules if item.get("recurrence_key") != recurrence_key]
    rules.append(rule)
    registry["updated_at"] = rule["promoted_at"]
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    promotion = {
        "event": "incident_promoted",
        "incident_id": args.incident_id,
        "rule_id": rule_id,
        "at": rule["promoted_at"],
        "changed_files": changed_files,
        "verification": rule["verification"],
        "status": "promoted",
    }
    append_event(path, promotion)
    update_state(outbox, args.incident_id, "promoted")
    print(json.dumps({"ok": True, "rule_id": rule_id, "registry": str(registry_path)}, ensure_ascii=False, indent=2))
    return 0


def command_resolve(args: argparse.Namespace) -> int:
    outbox = args.outbox.expanduser().resolve()
    path = event_path(outbox)
    events = read_events(path)
    incident = next(
        (item for item in events if item.get("event") == "incident_observed" and item.get("incident_id") == args.incident_id),
        None,
    )
    if incident is None:
        raise SystemExit(f"Incident not found: {args.incident_id}")
    event = {
        "event": "incident_resolved",
        "incident_id": args.incident_id,
        "at": now_iso(),
        "disposition": args.disposition,
        "resolution": sanitize(args.resolution),
        "verification": [sanitize(value) for value in args.verification],
        "status": args.disposition,
    }
    append_event(path, event)
    update_state(outbox, args.incident_id, args.disposition)
    print(json.dumps({"ok": True, "incident_id": args.incident_id, "status": args.disposition}, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    record = subparsers.add_parser("record", help="Record a sanitized incident")
    record.add_argument("--outbox", type=Path, required=True)
    record.add_argument("--stage", choices=sorted(STAGES), required=True)
    record.add_argument("--code", required=True)
    record.add_argument("--category", choices=sorted(CATEGORIES), required=True)
    record.add_argument("--expected", required=True)
    record.add_argument("--observed", required=True)
    record.add_argument("--evidence", default="")
    record.add_argument("--local-fix", default="")
    record.add_argument("--recurrence-key", default="")
    record.set_defaults(func=command_record)

    promote = subparsers.add_parser("promote", help="Promote a verified reusable fix")
    promote.add_argument("--outbox", type=Path, required=True)
    promote.add_argument("--incident-id", required=True)
    promote.add_argument("--root-cause", required=True)
    promote.add_argument("--fix-summary", required=True)
    promote.add_argument("--changed-file", action="append", required=True)
    promote.add_argument("--verification", action="append", required=True)
    promote.add_argument("--registry", type=Path)
    promote.set_defaults(func=command_promote)

    resolve = subparsers.add_parser("resolve", help="Close a local, candidate, or blocked incident")
    resolve.add_argument("--outbox", type=Path, required=True)
    resolve.add_argument("--incident-id", required=True)
    resolve.add_argument(
        "--disposition",
        choices=["resolved-local", "candidate", "blocked", "not-actionable"],
        required=True,
    )
    resolve.add_argument("--resolution", required=True)
    resolve.add_argument("--verification", action="append", default=[])
    resolve.set_defaults(func=command_resolve)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
