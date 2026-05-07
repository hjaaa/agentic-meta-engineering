"""GATE-TASK-FRONTMATTER plugin 单测（F-003）。

覆盖：
  - TC-F2-2 同构 case1: changed_files=[] → Skip（skip fixture）
  - TC-F2-2 同构 case2: changed_files 命中 task.md + 字段非法 → fail（fail fixture）
  - 自然过滤回归：trigger=ci 但 changed_files 不含 task.md → Skip
  - pass fixture: 合法 task.md → pass
  - skip fixture: task.md 不存在（被删）→ Skip
  - skip fixture: trigger 不在白名单 → Skip

隔离策略：
  - 使用 tmp_path 创建临时 task.md 文件
  - monkeypatch _REPO_ROOT 到 tmp_path，避免依赖真实 requirements/ 目录
  - task-frontmatter-schema.yaml 用真实文件（schema 已随 F-003 新建）
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from plugins.base import Decision, GateContext, Skip
from plugins import task_frontmatter as plugin_mod

# ---------- 常量 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------- 工具函数 ----------

def _write_task_md(path: Path, frontmatter: dict) -> None:
    """把 frontmatter dict 写成 task.md（--- 块格式）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_text = yaml.safe_dump(frontmatter, allow_unicode=True, default_flow_style=False)
    content = f"---\n{fm_text}---\n\n# Task body\n"
    path.write_text(content, encoding="utf-8")


def _valid_frontmatter(fid: str = "F-001") -> dict:
    """返回一份合法的 task.md frontmatter。"""
    return {
        "schema_version": "1.0",
        "feature_id": fid,
        "title": f"Feature {fid} 任务",
        "status": "pending",
        "complexity": "medium",
        "depends_on": [],
        "touches": [f"scripts/lib/check_{fid.lower()}.py"],
        "created_at": "2026-05-06 10:00:00",
        "updated_at": "2026-05-06 10:00:00",
    }


def _make_ctx(trigger: str, changed_files: list[str]) -> GateContext:
    """构造 GateContext。"""
    return GateContext(
        trigger=trigger,
        requirement_id="REQ-2099-001",
        changed_files=changed_files,
    )


# ======================== TC-F2-2 同构 case1: changed_files=[] → Skip ========================

def test_no_changed_files_is_skipped(tmp_path, monkeypatch):
    """TC-F2-2 同构 case1：changed_files=[] → Skip（skip fixture）。

    没有任何 changed_files 时，tasks/*.md glob 不命中 → Skip。
    """
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    gate = plugin_mod.TaskFrontmatterGate()
    ctx = _make_ctx("pre-commit", [])

    result = gate.precheck(ctx)
    assert isinstance(result, Skip), f"期望 Skip（无 changed_files），实际：{result}"
    assert "changed_files" in result.reason or "tasks" in result.reason.lower(), (
        f"Skip.reason 应说明 changed_files 不含 tasks/*.md，实际：{result.reason}"
    )


# ======================== TC-F2-2 同构 case2: 命中 task.md + 字段非法 → fail ========================

def test_invalid_task_md_fails(tmp_path, monkeypatch):
    """TC-F2-2 同构 case2：changed_files 命中 task.md + 文件字段非法 → fail（fail fixture）。

    status=invalid_value 不在枚举 → 校验失败 → gate 返回 FAIL。
    """
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    rel_path = "requirements/REQ-2099-001/artifacts/tasks/F-001.md"
    data = _valid_frontmatter("F-001")
    data["status"] = "invalid_value"  # 非法枚举值
    _write_task_md(tmp_path / rel_path, data)

    gate = plugin_mod.TaskFrontmatterGate()
    ctx = _make_ctx("pre-commit", [rel_path])

    # precheck 应通过（不 skip）
    skip = gate.precheck(ctx)
    assert skip is None, f"期望 precheck 不 skip，实际：{skip}"

    report = gate.run(ctx)
    assert report.decision == Decision.FAIL, f"期望 FAIL，实际：{report.decision}"
    assert report.code == "R-TASK-FRONTMATTER-INVALID"
    assert "task.md" in (report.message or "").lower() or rel_path in (report.message or "")


# ======================== 自然过滤回归：trigger=ci 但不含 task.md → Skip ========================

def test_ci_trigger_without_task_md_is_skipped(tmp_path, monkeypatch):
    """自然过滤回归：trigger=ci 但 changed_files 不含 tasks/*.md → Skip。

    即使 trigger=ci 在白名单，changed_files 不含 task.md glob 也 Skip。
    """
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    # changed_files 只包含 features.json，不含 tasks/*.md
    changed = ["requirements/REQ-2099-001/artifacts/features.json"]

    gate = plugin_mod.TaskFrontmatterGate()
    ctx = _make_ctx("ci", changed)

    result = gate.precheck(ctx)
    assert isinstance(result, Skip), f"期望 Skip（ci 但不含 task.md），实际：{result}"


# ======================== pass fixture: 合法 task.md → PASS ========================

def test_valid_task_md_passes(tmp_path, monkeypatch):
    """given_valid_task_md_when_run_then_pass（pass fixture）。"""
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    rel_path = "requirements/REQ-2099-001/artifacts/tasks/F-001.md"
    data = _valid_frontmatter("F-001")
    _write_task_md(tmp_path / rel_path, data)

    gate = plugin_mod.TaskFrontmatterGate()
    ctx = _make_ctx("pre-commit", [rel_path])

    skip = gate.precheck(ctx)
    assert skip is None, f"期望 precheck 不 skip，实际：{skip}"

    report = gate.run(ctx)
    assert report.decision == Decision.PASS, (
        f"期望 PASS，实际：{report.decision}，消息：{report.message}"
    )


# ======================== skip fixture: task.md 不存在（被删）→ Skip ========================

def test_nonexistent_task_md_is_skipped(tmp_path, monkeypatch):
    """given_task_md_deleted_when_precheck_then_skip（skip fixture）。

    changed_files 中有 task.md 路径，但文件已被删除 → Skip。
    """
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    rel_path = "requirements/REQ-2099-001/artifacts/tasks/F-001.md"
    # 不创建实际文件（模拟删除场景）

    gate = plugin_mod.TaskFrontmatterGate()
    ctx = _make_ctx("pre-commit", [rel_path])

    result = gate.precheck(ctx)
    assert isinstance(result, Skip), f"期望 Skip（文件不存在），实际：{result}"
    assert "不存在" in result.reason or "删除" in result.reason or "absent" in result.reason.lower(), (
        f"Skip.reason 应说明文件不存在，实际：{result.reason}"
    )


# ======================== skip fixture: trigger 不在白名单 → Skip ========================

def test_unknown_trigger_is_skipped(tmp_path, monkeypatch):
    """given_unknown_trigger_when_precheck_then_skip（skip fixture）。"""
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    rel_path = "requirements/REQ-2099-001/artifacts/tasks/F-001.md"
    data = _valid_frontmatter("F-001")
    _write_task_md(tmp_path / rel_path, data)

    gate = plugin_mod.TaskFrontmatterGate()
    ctx = _make_ctx("post-dev", [rel_path])  # post-dev 不在白名单

    result = gate.precheck(ctx)
    assert isinstance(result, Skip), f"期望 Skip（post-dev 不在 trigger 白名单），实际：{result}"


# ======================== fail fixture: 缺 schema_version（过渡期预期行为）→ fail ========================

def test_missing_schema_version_fails(tmp_path, monkeypatch):
    """given_task_md_missing_schema_version_when_run_then_fail。

    ADR（F-003）：schema_version 是 required 字段，缺失应 fail（不软兼容）。
    这是过渡期预期行为——F-007 派发模板改造后会统一注入 schema_version。
    """
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    rel_path = "requirements/REQ-2099-001/artifacts/tasks/F-001.md"
    data = _valid_frontmatter("F-001")
    del data["schema_version"]  # 模拟现有 task.md 无 schema_version
    _write_task_md(tmp_path / rel_path, data)

    gate = plugin_mod.TaskFrontmatterGate()
    ctx = _make_ctx("pre-commit", [rel_path])

    skip = gate.precheck(ctx)
    assert skip is None

    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.fix_hint is not None and len(report.fix_hint) > 0


# ======================== 多文件：一合法一非法 → fail ========================

def test_two_files_one_invalid_fails(tmp_path, monkeypatch):
    """given_two_task_md_one_invalid_when_run_then_fail。"""
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    rel_ok = "requirements/REQ-2099-001/artifacts/tasks/F-001.md"
    rel_bad = "requirements/REQ-2099-002/artifacts/tasks/F-002.md"

    _write_task_md(tmp_path / rel_ok, _valid_frontmatter("F-001"))

    bad_data = _valid_frontmatter("F-002")
    bad_data["complexity"] = "super"  # 非法枚举
    _write_task_md(tmp_path / rel_bad, bad_data)

    gate = plugin_mod.TaskFrontmatterGate()
    ctx = _make_ctx("ci", [rel_ok, rel_bad])

    skip = gate.precheck(ctx)
    assert skip is None

    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "R-TASK-FRONTMATTER-INVALID"
