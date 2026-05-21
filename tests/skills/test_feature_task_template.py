"""feature-task.md.tmpl 渲染与派发 prompt 首行格式测试（TC-F7 / TT-001~005）。

覆盖范围：
  TT-001  touches 非空数组 → frontmatter 正确序列化
  TT-002  touches 空数组   → frontmatter `touches: []`，prompt 含"未声明 touches"
  TT-003  缺 touches 字段  → helper 抛 ValueError，不静默写 null
  TT-004  派发 prompt 首行 → 严格 `feature_id: <fid>`（无前缀无后缀）
  TT-005  dispatch_precheck.parse_feature_id 反向解析 → 命中 fid

注意：task-context-builder/SKILL.md 不在 F-007 touches 范围内，故渲染 helper
放在本测试模块内，不修改 task-context-builder SKILL 文档。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import yaml

# ---------- 路径 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TMPL_PATH = (
    _REPO_ROOT
    / ".claude"
    / "skills"
    / "feature-lifecycle-manager"
    / "templates"
    / "feature-task.md.tmpl"
)

# dispatch_precheck.py 在 .claude/hooks/ 下；sys.path 动态插入避免全局污染
_HOOKS_DIR = _REPO_ROOT / ".claude" / "hooks"


# ---------- 渲染 helper（仅本模块使用，不修改 task-context-builder SKILL） ----------

def _render_task_md(features_entry: dict) -> str:
    """从 features.json 单条目渲染 task.md 内容。

    通过替换 feature-task.md.tmpl 中的占位符生成最终文件内容。
    强约束：features_entry 必须包含 touches 字段（否则 ValueError），
    防止静默写入 null（来源：detail-design §8.1 / D-005 #3）。

    参数：features_entry — features.json 中单个 feature 的 dict。
    返回：填充后的 task.md 完整字符串。
    异常：ValueError — features_entry 缺 touches 字段；
          FileNotFoundError — 模板文件不存在。
    """
    if "touches" not in features_entry:
        raise ValueError(
            f"features_entry 缺 touches 字段（feature_id={features_entry.get('id', '?')}）；"
            "必须显式设置（空数组写 []，不允许 null / 缺字段）"
        )

    tmpl = _TMPL_PATH.read_text(encoding="utf-8")

    fid = features_entry.get("id", "F-???")
    title = features_entry.get("title", "")
    complexity = features_entry.get("complexity", "medium")
    depends_on = features_entry.get("depends_on_features") or []
    touches: List[str] = features_entry.get("touches") or []

    # yaml.safe_dump 序列化：flow_style=True → 内联数组格式 `[...]`；
    # 去掉末尾换行符，与 frontmatter 单行对齐。
    depends_on_yaml = yaml.safe_dump(depends_on, default_flow_style=True).rstrip("\n")
    touches_yaml = yaml.safe_dump(touches, default_flow_style=True).rstrip("\n")

    # ISO8601 占位符用固定字符串替换（测试场景不需要真实时间）
    iso_placeholder = "2026-01-01 00:00:00"

    rendered = (
        tmpl
        .replace("__FEATURE_ID__", fid)
        .replace("__TITLE__", title)
        .replace("__COMPLEXITY__", complexity)
        .replace("__DEPENDS_ON__", depends_on_yaml)
        .replace("__TOUCHES__", touches_yaml)
        .replace("__ISO8601__", iso_placeholder)
    )
    return rendered


def _render_dispatch_prompt(
    fid: str,
    req_id: str = "REQ-2026-008",
    title: str = "测试 feature",
    touches: Optional[List[str]] = None,
) -> str:
    """渲染 subagent 派发 prompt，首行严格为 `feature_id: <fid>`。

    首行独占格式是派发链硬约束（D-005 #3 / D-007）：
    dispatch_precheck.py 使用 `^feature_id:\\s*(F-\\d{{3}})\\s*$` MULTILINE 解析，
    任何前缀都导致 parse_feature_id 返回 None → fail-open → 校验形同虚设。

    参数：
      fid     — feature_id，如 "F-007"。
      req_id  — 需求 ID，用于分支名。
      title   — feature 标题。
      touches — touches 列表；None 或空 → prompt 写"未声明 touches"说明。
    返回：完整 dispatch prompt 字符串。
    """
    branch = req_id.lower().replace("req-", "req-")
    if touches:
        touches_section = "\n".join(f"  - {t}" for t in touches)
    else:
        touches_section = (
            "未声明 touches，保守处理：仅改与本 feature 直接相关的文件；"
            "任何越界写入会被 touches_guard.py 软记入 receipt"
        )

    return (
        f"feature_id: {fid}\n"
        f"你是 feat/{branch} 分支上的 feature 实现者。当前任务 {fid} · {title}。\n"
        f"\n"
        f"## 触及范围\n"
        f"\n"
        f"{touches_section}\n"
    )


# ---------- 导入 dispatch_precheck.parse_feature_id ----------

def _import_parse_feature_id():
    """动态导入 dispatch_precheck.parse_feature_id。

    dispatch_precheck.py 依赖 scripts.lib.dispatch_state（import 在运行时发生），
    但 parse_feature_id 本身无此依赖，可单独导入测试。
    若导入失败则 pytest.skip（不阻断其他用例）。
    """
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    if str(_HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(_HOOKS_DIR))
    try:
        import importlib
        mod = importlib.import_module("dispatch_precheck")
        return mod.parse_feature_id
    except ImportError as e:
        pytest.skip(f"无法导入 dispatch_precheck：{e}")


# ============================================================
# TT-001: touches 非空 → frontmatter 正确序列化
# ============================================================

def test_tt_001_touches_non_empty_in_frontmatter():
    """given_touches_list_when_render_task_md_then_frontmatter_contains_touches_yaml。"""
    entry: Dict[str, Any] = {
        "id": "F-007",
        "title": "测试 feature",
        "complexity": "medium",
        "depends_on_features": [],
        "touches": [".claude/hooks/x.py"],
    }
    rendered = _render_task_md(entry)

    # 提取 frontmatter（--- 之间）
    fm_text = _extract_frontmatter_text(rendered)
    fm = yaml.safe_load(fm_text)

    assert isinstance(fm, dict), "frontmatter 必须是 dict"
    assert "touches" in fm, "frontmatter 必须含 touches 字段"
    # 值等价：yaml 解析后与原列表相同
    assert fm["touches"] == [".claude/hooks/x.py"], (
        f"touches 值不匹配，期望 ['.claude/hooks/x.py']，实际={fm['touches']!r}"
    )


# ============================================================
# TT-002: touches 空数组 → frontmatter `touches: []`，prompt 含"未声明"
# ============================================================

@pytest.mark.parametrize("touches_val", [[], None])
def test_tt_002_touches_empty_in_frontmatter_and_prompt(touches_val):
    """given_empty_touches_when_render_then_frontmatter_touches_empty_and_prompt_notes_undeclared。"""
    entry: Dict[str, Any] = {
        "id": "F-007",
        "title": "测试 feature",
        "complexity": "low",
        "depends_on_features": [],
        "touches": touches_val if touches_val is not None else [],
    }
    # None 转 [] 仍有 touches 键 → 不 raise ValueError
    if touches_val is None:
        entry["touches"] = []

    rendered = _render_task_md(entry)
    fm_text = _extract_frontmatter_text(rendered)
    fm = yaml.safe_load(fm_text)

    assert fm.get("touches") == [], (
        f"touches 空时期望 []，实际={fm.get('touches')!r}"
    )

    # 派发 prompt 场景：空 touches → prompt 含"未声明"
    prompt = _render_dispatch_prompt("F-007", touches=[])
    assert "未声明 touches" in prompt, (
        f"空 touches 时 prompt 应含'未声明 touches'说明，实际={prompt!r}"
    )


# ============================================================
# TT-003: 缺 touches 字段 → helper 抛 ValueError
# ============================================================

def test_tt_003_missing_touches_raises_value_error():
    """given_entry_without_touches_key_when_render_then_ValueError_raised。"""
    entry: Dict[str, Any] = {
        "id": "F-007",
        "title": "测试 feature",
        "complexity": "medium",
        # 故意不传 touches 键
    }
    with pytest.raises(ValueError, match="缺 touches 字段"):
        _render_task_md(entry)


# ============================================================
# TT-004: 派发 prompt 首行严格 `feature_id: <fid>`
# ============================================================

@pytest.mark.parametrize("fid", ["F-001", "F-007", "F-099"])
def test_tt_004_dispatch_prompt_first_line_strict_feature_id(fid):
    """given_fid_when_render_dispatch_prompt_then_first_line_is_exactly_feature_id_colon_fid。"""
    prompt = _render_dispatch_prompt(fid)
    first_line = prompt.splitlines()[0]

    # 首行必须严格匹配 `feature_id: F-xxx`，无前缀无后缀
    assert first_line == f"feature_id: {fid}", (
        f"派发 prompt 首行格式错误：期望 'feature_id: {fid}'，实际={first_line!r}\n"
        "红线：dispatch_precheck.py 使用 `^feature_id:\\s*(F-\\d{{3}})\\s*$` MULTILINE 解析，"
        "任何前缀/后缀导致 parse_feature_id 返回 None → fail-open（D-005 #3 / D-007）"
    )

    # 进一步确认首行无任何注释前缀
    assert not first_line.startswith("#"), "首行不能以 # 开头"
    assert ":" in first_line and first_line.index(":") > 0, "首行格式应为 key: value"


# ============================================================
# TT-005: dispatch_precheck.parse_feature_id 反向解析 prompt 输出
# ============================================================

def test_tt_005_parse_feature_id_roundtrip():
    """given_dispatch_prompt_when_parse_feature_id_then_returns_correct_fid。"""
    parse_feature_id = _import_parse_feature_id()

    for fid in ["F-001", "F-007"]:
        prompt = _render_dispatch_prompt(fid)
        result = parse_feature_id(prompt)
        assert result == fid, (
            f"parse_feature_id 应解析出 {fid!r}，实际={result!r}\n"
            f"prompt 首 5 行：{prompt.splitlines()[:5]}"
        )

    # 验证非法格式（首行非 feature_id: ...）被 parse_feature_id 正确拒绝
    bad_prompt = "# feature_id: F-007\n你是 subagent..."
    assert parse_feature_id(bad_prompt) is None, (
        "首行有 # 前缀时 parse_feature_id 应返回 None（dispatch_precheck regex 拒绝）"
    )

    bad_prompt2 = "DISPATCH: feature_id: F-007\n..."
    assert parse_feature_id(bad_prompt2) is None, (
        "feature_id 嵌入其他内容时 parse_feature_id 应返回 None"
    )


# ============================================================
# 辅助：frontmatter 提取
# ============================================================

def _extract_frontmatter_text(content: str) -> str:
    """提取 --- 包裹的 frontmatter 文本（不含 --- 分隔行）。

    若 frontmatter 不完整则 raise ValueError，让测试明确失败而非静默。
    """
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"文档首行不是 ---，无法提取 frontmatter：{lines[:3]}")
    fm_lines: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            return "\n".join(fm_lines)
        fm_lines.append(line)
    raise ValueError("frontmatter 未找到关闭的 --- 行")


# ============================================================
# TT-006: feature-task.md.tmpl 渲染产物含 schema_version: "1.0"（Bug-11）
# ============================================================

def test_tt_006_schema_version_present_in_frontmatter():
    """given_template_when_render_then_frontmatter_contains_schema_version_1_0。

    task-frontmatter-schema.yaml required_fields 含 schema_version；
    模板必须输出 schema_version: "1.0" 字段以通过 check_task_frontmatter.py。
    """
    entry: Dict[str, Any] = {
        "id": "F-001",
        "title": "feat",
        "complexity": "light",
        "depends_on_features": [],
        "touches": ["scripts/lib/x.py"],
    }
    rendered = _render_task_md(entry)
    fm = yaml.safe_load(_extract_frontmatter_text(rendered))
    assert isinstance(fm, dict)
    assert "schema_version" in fm, "frontmatter 必须含 schema_version"
    assert str(fm["schema_version"]) == "1.0", (
        f"schema_version 必须为 '1.0'，实际={fm['schema_version']!r}"
    )
