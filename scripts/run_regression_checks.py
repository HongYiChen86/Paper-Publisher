#!/usr/bin/env python3
"""Run deterministic regression checks for package validation and learning records."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


SKILL_ROOT = Path(__file__).resolve().parent.parent


def load_validator():
    path = SKILL_ROOT / "scripts" / "validate_publish_package.py"
    spec = importlib.util.spec_from_file_location("xhs_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_package(root: Path, validator, size: tuple[int, int] = (1242, 1656)) -> tuple[Path, dict]:
    media = []
    for index in range(1, 5):
        path = root / f"{index:02d}.png"
        Image.new("RGB", size, "white").save(path, "PNG")
        media.append({"order": index, "path": str(path), "ratio": "3:4"})
    payload = {
        "schema_version": 2,
        "platform": "xiaohongshu",
        "content_type": "image",
        "package_fingerprint": "",
        "source": {"paper_pdf": "paper.pdf", "paper_title": "Test", "selection_file": "selection.md"},
        "media": media,
        "form": {
            "title": "论文速读测试",
            "body": "用于回归验证。",
            "topics": ["论文速读"],
            "publish_mode": "draft",
            "scheduled_at": None,
            "timezone": "Asia/Shanghai",
            "visibility": "public",
            "originality": {"enabled": False, "rights_confirmed": False, "basis": "paper commentary"},
            "collection": {"enabled": True, "name": "论文分享"},
        },
        "safety": {"final_submit_authorized": False},
    }
    payload["package_fingerprint"] = validator.fingerprint(payload)
    package = root / "publish_package.json"
    package.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return package, payload


def main() -> int:
    validator = load_validator()
    checks: list[str] = []
    runtime = subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / "check_runtime.py")],
        check=False, capture_output=True, text=True,
    )
    runtime_result = json.loads(runtime.stdout)
    assert runtime.returncode == 0 and runtime_result["ok"], runtime_result
    checks.append("runtime_dependencies_available")
    with tempfile.TemporaryDirectory(prefix="xhs-skill-regression-") as raw:
        root = Path(raw)
        package, payload = make_package(root, validator)
        errors, _, _ = validator.validate(payload, package)
        assert not errors, errors
        checks.append("valid_package")

        missing_collection_payload = json.loads(json.dumps(payload))
        missing_collection_payload["form"].pop("collection")
        missing_collection_payload["package_fingerprint"] = validator.fingerprint(missing_collection_payload)
        errors, _, _ = validator.validate(missing_collection_payload, package)
        assert any("form.collection" in error for error in errors), errors
        checks.append("collection_required")

        source_payload = json.loads(json.dumps(payload))
        source_payload["media_mode"] = "source_pages"
        for index, item in enumerate(source_payload["media"], start=1):
            item.update({"ratio": "original", "presentation": "source_page", "source_page": index})
        source_payload["package_fingerprint"] = validator.fingerprint(source_payload)
        errors, _, _ = validator.validate(source_payload, package)
        assert not errors, errors
        checks.append("source_pages_package_allowed")

        wrong_root = root / "wrong-ratio"
        wrong_root.mkdir()
        wrong_package, wrong_payload = make_package(wrong_root, validator, (1000, 1000))
        errors, _, _ = validator.validate(wrong_payload, wrong_package)
        assert any("must be 3:4" in error for error in errors), errors
        checks.append("wrong_ratio_rejected")

        oversized = Path(payload["media"][0]["path"])
        with oversized.open("r+b") as handle:
            handle.truncate(validator.MAX_UPLOAD_BYTES + 1)
        payload["package_fingerprint"] = validator.fingerprint(payload)
        errors, _, _ = validator.validate(payload, package)
        assert any("exceeds 32 MiB" in error for error in errors), errors
        checks.append("oversized_asset_rejected")

        state = {
            "schema_version": 1,
            "platform": "xiaohongshu",
            "package_fingerprint": payload["package_fingerprint"],
            "status": "BLOCKED",
            "phase": "preflight",
            "learning": {"incident_count": 0, "last_incident_id": None},
        }
        (root / "publish_state.json").write_text(json.dumps(state), encoding="utf-8")
        recorder = SKILL_ROOT / "scripts" / "record_improvement.py"
        result = subprocess.run(
            [
                sys.executable, str(recorder), "record", "--outbox", str(root),
                "--stage", "prepare", "--code", "DEPENDENCY_MISSING", "--category", "runtime",
                "--expected", "required modules available", "--observed", "token=should-redact missing module",
                "--evidence", "runtime preflight", "--local-fix", "select or repair runtime",
            ],
            check=True, capture_output=True, text=True,
        )
        incident_id = json.loads(result.stdout)["incident_id"]
        log_text = (root / "learning" / "incidents.jsonl").read_text(encoding="utf-8")
        assert incident_id in log_text and "should-redact" not in log_text
        checks.append("incident_recorded_and_redacted")

        registry = root / "learned-rules.json"
        subprocess.run(
            [
                sys.executable, str(recorder), "promote", "--outbox", str(root),
                "--incident-id", incident_id, "--root-cause", "missing runtime dependency",
                "--fix-summary", "check dependencies before paper parsing",
                "--changed-file", "scripts/check_runtime.py",
                "--verification", "regression fixture passed", "--registry", str(registry),
            ],
            check=True, capture_output=True, text=True,
        )
        promoted = json.loads(registry.read_text(encoding="utf-8"))
        assert promoted["rules"][0]["source_incident"] == incident_id
        checks.append("verified_fix_promoted")

        local_result = subprocess.run(
            [
                sys.executable, str(recorder), "record", "--outbox", str(root),
                "--stage", "prepare", "--code", "CARD_VISUAL_QA_FAILED", "--category", "asset",
                "--expected", "clean crop", "--observed", "stray source text",
                "--local-fix", "adjust crop",
            ],
            check=True, capture_output=True, text=True,
        )
        local_id = json.loads(local_result.stdout)["incident_id"]
        subprocess.run(
            [
                sys.executable, str(recorder), "resolve", "--outbox", str(root),
                "--incident-id", local_id, "--disposition", "resolved-local",
                "--resolution", "crop adjusted", "--verification", "visual QA passed",
            ],
            check=True, capture_output=True, text=True,
        )
        assert '"event": "incident_resolved"' in (root / "learning" / "incidents.jsonl").read_text(encoding="utf-8")
        checks.append("local_incident_resolved")

        source_content = {
            "source": {"paper_pdf": "paper.pdf", "paper_title": "Test", "selection_file": "selection.md"},
            "post": {"title": "原页模式测试", "body": "正文", "topics": ["论文速读"]},
            "publish": {
                "mode": "draft", "scheduled_at": None, "timezone": "Asia/Shanghai", "visibility": "public",
                "originality": {"enabled": False, "rights_confirmed": False, "basis": "paper commentary"},
            },
            "source_pages": [
                {"order": index, "path": payload["media"][index - 1]["path"], "source_page": index}
                for index in range(1, 5)
            ],
        }
        source_content_path = root / "source-content.json"
        source_content_path.write_text(json.dumps(source_content, ensure_ascii=False), encoding="utf-8")
        source_out = root / "source-out"
        subprocess.run(
            [
                sys.executable, str(SKILL_ROOT / "scripts" / "create_source_page_package.py"),
                "--content", str(source_content_path), "--output", str(source_out),
            ],
            check=True, capture_output=True, text=True,
        )
        source_package = json.loads((source_out / "publish_package.json").read_text(encoding="utf-8"))
        original_bytes = Path(source_content["source_pages"][0]["path"]).read_bytes()
        copied_bytes = Path(source_package["media"][0]["path"]).read_bytes()
        assert source_package["media_mode"] == "source_pages"
        assert hashlib.sha256(original_bytes).digest() == hashlib.sha256(copied_bytes).digest()
        checks.append("source_pages_copied_without_pixel_edits")

        staged = subprocess.run(
            [
                sys.executable, str(SKILL_ROOT / "scripts" / "stage_upload_media.py"),
                str(source_out / "publish_package.json"), "--root", str(root / "ascii-stage"),
            ],
            check=True, capture_output=True, text=True,
        )
        staged_payload = json.loads(staged.stdout)
        assert staged_payload["ok"] and len(staged_payload["files"]) == 4
        assert all(Path(item["staged"]).is_file() for item in staged_payload["files"])
        assert all(hashlib.sha256(Path(item["source"]).read_bytes()).hexdigest() == item["sha256"] for item in staged_payload["files"])
        checks.append("upload_media_staged_at_ascii_paths_without_byte_changes")

        preview_state = source_out / "publish_state.json"
        state_recorder = SKILL_ROOT / "scripts" / "record_publish_state.py"
        blocked_upload = subprocess.run(
            [
                sys.executable, str(state_recorder), str(preview_state),
                "--package", str(source_out / "publish_package.json"),
                "--phase", "upload", "--status", "STARTED",
            ],
            check=False, capture_output=True, text=True,
        )
        assert blocked_upload.returncode != 0 and "CONTENT_CONFIRMATION_REQUIRED" in blocked_upload.stderr
        subprocess.run(
            [
                sys.executable, str(state_recorder), str(preview_state),
                "--package", str(source_out / "publish_package.json"),
                "--phase", "preview", "--status", "CONFIRMED",
                "--gates-json", '{"contentConfirmed": true}',
                "--evidence-json", '{"confirmation_scope": "current package preview"}',
            ],
            check=True, capture_output=True, text=True,
        )
        allowed_upload = subprocess.run(
            [
                sys.executable, str(state_recorder), str(preview_state),
                "--package", str(source_out / "publish_package.json"),
                "--phase", "upload", "--status", "STARTED",
            ],
            check=False, capture_output=True, text=True,
        )
        assert allowed_upload.returncode == 0, allowed_upload.stderr
        checks.append("content_confirmation_required_before_upload")

        state_backup = preview_state.with_name("publish_state.backup.json")
        assert state_backup.is_file()
        preview_state.write_text("{broken state", encoding="utf-8")
        recovered = subprocess.run(
            [
                sys.executable, str(state_recorder), str(preview_state),
                "--package", str(source_out / "publish_package.json"),
                "--phase", "inspect", "--status", "STARTED",
            ],
            check=False, capture_output=True, text=True,
        )
        assert recovered.returncode == 10, recovered.stderr
        recovered_state = json.loads(preview_state.read_text(encoding="utf-8"))
        assert recovered_state["status"] == "STATE_RECOVERED_REQUIRES_INSPECT"
        assert recovered_state["gates"].get("contentConfirmed") is True
        assert any(source_out.glob("publish_state.corrupt-*.json"))
        checks.append("corrupt_state_recovers_matching_backup_and_requires_inspect")

        content_spec_text = (SKILL_ROOT / "references" / "content-spec.md").read_text(encoding="utf-8")
        required_preview_fields = [
            "标题：{最终标题}",
            "关键词：#{关键词1} #{关键词2}",
            "内容（将完整填写到小红书）",
            "目标动作：{保存草稿/立即发布/定时发布",
            "AWAITING_CONTENT_CONFIRMATION",
        ]
        assert all(field in content_spec_text for field in required_preview_fields)
        assert "{emoji}{会议/年份}｜{论文核心问题、反差发现或一句结论}" in content_spec_text
        assert "`大模型`、`Agent`、`深度学习`、`科研绘图`、`多模态人工智能`、`计算机视觉`" in content_spec_text
        checks.append("emoji_copy_and_full_confirmation_card_contract")

        publishing_contract = (SKILL_ROOT / "references" / "xiaohongshu-publishing.md").read_text(encoding="utf-8")
        assert "点击 promise 与 chooser 等待并发推进" in publishing_contract
        assert '不能依赖 `getByRole("textbox").nth(...)`' in publishing_contract
        assert '唯一可见的 `div[contenteditable="true"]`' in publishing_contract
        assert "COLLECTION_NOT_FOUND" in publishing_contract
        assert "ORIGINALITY_RIGHTS_REQUIRED" in publishing_contract
        checks.append("concurrent_filechooser_and_stable_form_locators_contract")

        assert "dependency-aware bounded batching" in publishing_contract
        assert "每批最多 2-3 个写动作" in publishing_contract
        assert "所有话题在最终 `verify` 中一次性核验为真实实体" in publishing_contract
        assert "只补齐页面中缺失的字段" in publishing_contract
        assert "常规点击和输入使用 3-5 秒短超时" in publishing_contract
        assert "不要在常规点击、输入之间插入固定等待" in publishing_contract
        assert "达到条件立即继续" in publishing_contract
        assert "单次浏览器控制调用只处理一个动态话题" in publishing_contract
        assert "DOM-CUA 直接通道" in publishing_contract
        assert "上一话题没有回读为真实实体时，下一话题不得开始" in publishing_contract
        assert "不用于 `setFiles`、删除、最终发布/定时发布" in publishing_contract
        assert "一个调度器、一个 UI 串行队列、一次最终独立验收" in publishing_contract
        assert "xhs-publish-btn" in publishing_contract
        assert "图文笔记(n)" in publishing_contract
        assert "DRAFT_SAVE_UNVERIFIED" in publishing_contract
        state_recorder_text = state_recorder.read_text(encoding="utf-8")
        assert '"collection", "originality"' in state_recorder_text
        helper_text = (SKILL_ROOT / "scripts" / "xhs_browser_batch.mjs").read_text(encoding="utf-8")
        assert "export function exactVisibleNodeId" in helper_text
        assert "export async function clickExactVisibleNode" in helper_text
        assert "export async function typeAtCurrentFocus" in helper_text
        checks.append("dependency_aware_bounded_form_batching_contract")

    print(json.dumps({"ok": True, "checks": checks}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
