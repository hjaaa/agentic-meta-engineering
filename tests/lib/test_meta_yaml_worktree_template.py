"""F-008 · meta.yaml.tmpl worktree 段渲染测试。

覆盖 features.json F-008 的 AC1~AC5：
  AC1 渲染后文本含 worktree: 顶层 key + 12 字段名字面量
  AC2 yaml.safe_load 不抛 + worktree 段含 12 字段（baseline/cleanup 嵌套结构）
  AC3 cleanup.policy 默认 'owned-only'（OD-3 硬编码）
  AC4 cleanup.removed_at 默认 ''（P1-4 canonical unset = 空串）
  AC5 enabled 默认 false（yaml bool，非字符串）

注意：测试用 REQ-2099-NNN 格式（Sandbox REQ ID 规范），
      只调 _render_meta_yaml 返回字符串，不落盘，无需建 requirements/ 目录。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

# ---------- 路径注入 ----------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from unittest.mock import patch

import workflow_bootstrap as wb  # noqa: E402


def _render(req_id: str, title: str, branch: str, base_branch: str) -> str:
    """调 _render_meta_yaml，patch REPO_ROOT 指向真实模板目录。"""
    with patch("workflow_bootstrap.REPO_ROOT", _REPO_ROOT):
        return wb._render_meta_yaml(req_id, title, branch, base_branch)


# ============================================================================
# AC1：渲染后文本含 worktree: 顶层 key + 12 字段名字面量
# ============================================================================

def test_rendered_meta_yaml_contains_worktree_section():
    """渲染后 meta.yaml 文本含 'worktree:' 顶层 key + 全部 12 字段名字面量。"""
    rendered = _render("REQ-2099-001", "test", "feat/req-2099-001", "develop")
    assert "worktree:" in rendered, "顶层 worktree: key 缺失"
    expected_fields = [
        "enabled",
        "owner",
        "path",
        "absolute_path",
        "branch",
        "base_branch",
        "created_at",
        "command",
        "status",
        "completed_at",
        "policy",
        "removed_at",
    ]
    for f in expected_fields:
        assert f in rendered, f"字段 {f} 缺失"


# ============================================================================
# AC2：yaml.safe_load 不抛 + worktree 段含 12 字段（baseline/cleanup 嵌套结构）
# ============================================================================

def test_rendered_meta_yaml_safe_load_succeeds():
    """渲染后 yaml.safe_load 不抛 + worktree 段含 12 字段（baseline/cleanup 嵌套结构）。"""
    rendered = _render("REQ-2099-002", "test2", "feat/req-2099-002", "develop")
    data = yaml.safe_load(rendered)
    wt = data["worktree"]
    # 顶层 6 字段
    assert "enabled" in wt
    assert "owner" in wt
    assert "path" in wt
    assert "absolute_path" in wt
    assert "branch" in wt
    assert "base_branch" in wt
    assert "created_at" in wt
    # baseline 嵌套 3 字段
    assert "baseline" in wt
    assert "command" in wt["baseline"]
    assert "status" in wt["baseline"]
    assert "completed_at" in wt["baseline"]
    # cleanup 嵌套 2 字段
    assert "cleanup" in wt
    assert "policy" in wt["cleanup"]
    assert "removed_at" in wt["cleanup"]


# ============================================================================
# AC3：cleanup.policy 默认 'owned-only'（OD-3 硬编码）
# ============================================================================

def test_rendered_meta_yaml_cleanup_policy_defaults_to_owned_only():
    """OD-3：cleanup.policy 默认 'owned-only' 硬编码，不含占位符。"""
    rendered = _render("REQ-2099-003", "test3", "feat/req-2099-003", "develop")
    data = yaml.safe_load(rendered)
    assert data["worktree"]["cleanup"]["policy"] == "owned-only"


# ============================================================================
# AC4：cleanup.removed_at 默认 ''（P1-4 canonical unset = 空串）
# ============================================================================

def test_rendered_meta_yaml_cleanup_removed_at_defaults_to_empty_string():
    """P1-4：cleanup.removed_at 默认 canonical unset = 空串。"""
    rendered = _render("REQ-2099-004", "test4", "feat/req-2099-004", "develop")
    data = yaml.safe_load(rendered)
    assert data["worktree"]["cleanup"]["removed_at"] == ""


# ============================================================================
# AC5：enabled 默认 false（yaml bool，非字符串）
# ============================================================================

def test_rendered_meta_yaml_enabled_is_yaml_bool_false():
    """F-008 阶段 enabled 默认 false（yaml bool，非字符串 'false'）。"""
    rendered = _render("REQ-2099-005", "test5", "feat/req-2099-005", "develop")
    data = yaml.safe_load(rendered)
    assert data["worktree"]["enabled"] is False, (
        f"enabled 应为 yaml bool False，实际：{data['worktree']['enabled']!r}"
    )


# ============================================================================
# 额外：branch / base_branch 占位符正确替换
# ============================================================================

def test_rendered_meta_yaml_worktree_branch_matches_input():
    """worktree.branch 应与传入 branch 参数一致（与流程组 branch 字段对齐）。"""
    rendered = _render("REQ-2099-006", "test6", "feat/req-2099-006", "main")
    data = yaml.safe_load(rendered)
    assert data["worktree"]["branch"] == "feat/req-2099-006"
    assert data["worktree"]["base_branch"] == "main"
