"""F-008 沙盒 e2e — V-05：features-schema / task-frontmatter / receipt-schema 校验失败（TC-F8-4）。

验收点（detail-design.md §5.4 + §4.2）：
  - features.json complexity="giant"（不在 enum）→ check_features.py exit 1
  - features.json schema_version="0.9"（不在 SUPPORTED）→ check_features.py exit 1
  - task.md status="invalid_value"（不在 enum）→ check_task_frontmatter.py exit 1
  - task.md 缺 touches 字段 → check_task_frontmatter.py exit 1
  - receipt.json status="DONE_WITH_CONCERNS" 但 concerns=[] → check_receipt.py exit 1
  - 三件套 schema_version=2.0（schema 文件自损模拟）→ exit 2（不在本测试范围）

实现策略：
  - tmp_path 沙盒（fixtures 文件就地建）
  - subprocess.run python3 scripts/lib/check_<X>.py 真实跑（CLI 入口）
  - 反向 case 验证合法 fixture 时 exit 0（保证沙盒构造正确）

参考：tests/lib/test_check_features.py / test_check_task_frontmatter.py / test_check_receipt.py。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHECK_FEATURES = _REPO_ROOT / "scripts" / "lib" / "check_features.py"
_CHECK_TASK = _REPO_ROOT / "scripts" / "lib" / "check_task_frontmatter.py"
_CHECK_RECEIPT = _REPO_ROOT / "scripts" / "lib" / "check_receipt.py"


def _valid_features_data(req_id: str = "REQ-2099-030") -> dict:
    """合法 features.json data（schema_version 1.0，单 feature 必填字段全齐）。"""
    return {
        "schema_version": "1.0",
        "requirement_id": req_id,
        "features": [
            {
                "id": "F-001",
                "title": "feature 一",
                "description": "描述",
                "modules": ["m"],
                "depends_on": [],
                "depends_on_features": [],
                "complexity": "trivial",
                "touches": ["a/b/c"],
                "acceptance": ["AC-1"],
            },
        ],
    }


def _write_json(path: Path, data: dict) -> None:
    """工具：写 JSON（建父目录）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_task_md(path: Path, frontmatter: dict, drop_keys: tuple[str, ...] = ()) -> None:
    """写 task.md：frontmatter dict 序列化为 YAML 块。drop_keys 为故意删除的字段（构造 fail）。"""
    fm = {k: v for k, v in frontmatter.items() if k not in drop_keys}
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        elif isinstance(v, str):
            lines.append(f"{k}: \"{v}\"")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _run_check(script: Path, target: Path) -> subprocess.CompletedProcess:
    """以 subprocess 跑 check_<X>.py CLI；returncode 0/1/2 即接口契约。"""
    return subprocess.run(
        ["python3", str(script), str(target)],
        capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=30,
    )


# ---------- V-05 features.json 数据违规 → exit 1 ----------


def test_v05_features_complexity_giant_fails(tmp_path: Path) -> None:
    """V-05 case A：features.json complexity="giant"（不在 enum）→ check_features.py exit 1。"""
    data = _valid_features_data()
    data["features"][0]["complexity"] = "giant"  # 越界枚举
    fpath = tmp_path / "features.json"
    _write_json(fpath, data)

    proc = _run_check(_CHECK_FEATURES, fpath)
    assert proc.returncode == 1, (
        f"complexity=giant 应 exit 1，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )
    assert "complexity" in proc.stderr.lower() or "giant" in proc.stderr, (
        f"stderr 应含错误字段提示，实际：{proc.stderr!r}"
    )


def test_v05_features_unsupported_schema_version_fails(tmp_path: Path) -> None:
    """V-05 case B：features.json schema_version="0.9"（不在 SUPPORTED）→ exit 1。"""
    data = _valid_features_data()
    data["schema_version"] = "0.9"
    fpath = tmp_path / "features.json"
    _write_json(fpath, data)

    proc = _run_check(_CHECK_FEATURES, fpath)
    assert proc.returncode == 1, (
        f"schema_version=0.9 应 exit 1，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )
    assert "schema_version" in proc.stderr or "0.9" in proc.stderr, (
        f"stderr 应含 schema_version 错误：{proc.stderr!r}"
    )


def test_v05_features_missing_required_field_fails(tmp_path: Path) -> None:
    """V-05 补充：feature 缺 required 字段（如 depends_on_features）→ exit 1。"""
    data = _valid_features_data()
    del data["features"][0]["depends_on_features"]
    fpath = tmp_path / "features.json"
    _write_json(fpath, data)

    proc = _run_check(_CHECK_FEATURES, fpath)
    assert proc.returncode == 1, (
        f"缺 required 字段应 exit 1，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


def test_v05_features_valid_passes(tmp_path: Path) -> None:
    """sanity：合法 features.json → exit 0（防止沙盒构造错误误判）。"""
    fpath = tmp_path / "features.json"
    _write_json(fpath, _valid_features_data())

    proc = _run_check(_CHECK_FEATURES, fpath)
    assert proc.returncode == 0, (
        f"合法 features.json 应 exit 0，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


# ---------- V-05 task.md frontmatter 数据违规 → exit 1 ----------


def _valid_task_frontmatter() -> dict:
    """合法 task frontmatter dict（schema-yaml required_fields 全齐）。"""
    return {
        "schema_version": "1.0",
        "feature_id": "F-001",
        "title": "任务一",
        "status": "pending",
        "complexity": "trivial",
        "depends_on": [],
        "touches": [],
        "created_at": "2026-05-06 10:00:00",
        "updated_at": "2026-05-06 10:00:00",
    }


def test_v05_task_md_invalid_status_fails(tmp_path: Path) -> None:
    """V-05 case C：task.md status="invalid_value"（不在 enum）→ exit 1。"""
    fm = _valid_task_frontmatter()
    fm["status"] = "invalid_value"
    fpath = tmp_path / "F-001.md"
    _write_task_md(fpath, fm)

    proc = _run_check(_CHECK_TASK, fpath)
    assert proc.returncode == 1, (
        f"task.md status=invalid_value 应 exit 1，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )
    assert "status" in proc.stderr.lower(), f"stderr 应含 status 错误：{proc.stderr!r}"


def test_v05_task_md_missing_touches_fails(tmp_path: Path) -> None:
    """V-05 case D：task.md 缺 touches 字段（required_fields）→ exit 1。"""
    fm = _valid_task_frontmatter()
    fpath = tmp_path / "F-001.md"
    _write_task_md(fpath, fm, drop_keys=("touches",))

    proc = _run_check(_CHECK_TASK, fpath)
    assert proc.returncode == 1, (
        f"缺 touches 字段应 exit 1，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


def test_v05_task_md_missing_status_fails(tmp_path: Path) -> None:
    """V-05 case E：task.md 缺 status 字段（required_fields source-of-truth）→ exit 1。"""
    fm = _valid_task_frontmatter()
    fpath = tmp_path / "F-002.md"
    _write_task_md(fpath, fm, drop_keys=("status",))

    proc = _run_check(_CHECK_TASK, fpath)
    assert proc.returncode == 1, (
        f"缺 status 字段应 exit 1，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


def test_v05_task_md_invalid_complexity_fails(tmp_path: Path) -> None:
    """V-05 补充：task.md complexity="huge"（不在 enum）→ exit 1。"""
    fm = _valid_task_frontmatter()
    fm["complexity"] = "huge"
    fpath = tmp_path / "F-003.md"
    _write_task_md(fpath, fm)

    proc = _run_check(_CHECK_TASK, fpath)
    assert proc.returncode == 1, (
        f"complexity=huge 应 exit 1，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


def test_v05_task_md_valid_passes(tmp_path: Path) -> None:
    """sanity：合法 task.md → exit 0。"""
    fm = _valid_task_frontmatter()
    fpath = tmp_path / "F-004.md"
    _write_task_md(fpath, fm)

    proc = _run_check(_CHECK_TASK, fpath)
    assert proc.returncode == 0, (
        f"合法 task.md 应 exit 0，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


# ---------- V-05 receipt.json 数据违规 → exit 1（schema 三件套覆盖完整性）----------


def _valid_receipt_data(status: str = "DONE") -> dict:
    """合法 receipt.json data。"""
    concerns = [] if status == "DONE" else ["sandbox 已知疑虑"]
    return {
        "schema_version": "1.0",
        "feature_id": "F-001",
        "status": status,
        "commit_sha": "HEAD",
        "files_changed": [],
        "test_summary": "测试通过",
        "touches_violations": [],
        "concerns": concerns,
        "missing_context": "",
        "block_reason": "",
        "timestamp": "2026-05-06T10:00:00+08:00",
    }


def test_v05_receipt_done_with_concerns_empty_concerns_fails(tmp_path: Path) -> None:
    """V-05 补充：receipt.status=DONE_WITH_CONCERNS 但 concerns=[]（conditional_required 违反）→ exit 1。"""
    data = _valid_receipt_data("DONE_WITH_CONCERNS")
    data["concerns"] = []  # 违反 conditional_required.non_empty
    fpath = tmp_path / "F-001.receipt.json"
    _write_json(fpath, data)

    proc = _run_check(_CHECK_RECEIPT, fpath)
    assert proc.returncode == 1, (
        f"DONE_WITH_CONCERNS + concerns=[] 应 exit 1，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


def test_v05_receipt_invalid_status_fails(tmp_path: Path) -> None:
    """V-05 补充：receipt.status="OK"（不在 enum）→ exit 1。"""
    data = _valid_receipt_data()
    data["status"] = "OK"
    fpath = tmp_path / "F-001.receipt.json"
    _write_json(fpath, data)

    proc = _run_check(_CHECK_RECEIPT, fpath)
    assert proc.returncode == 1, (
        f"receipt.status=OK 应 exit 1，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


def test_v05_receipt_valid_passes(tmp_path: Path) -> None:
    """sanity：合法 receipt.json → exit 0。"""
    fpath = tmp_path / "F-002.receipt.json"
    _write_json(fpath, _valid_receipt_data("DONE"))

    proc = _run_check(_CHECK_RECEIPT, fpath)
    assert proc.returncode == 0, (
        f"合法 receipt.json 应 exit 0，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )
