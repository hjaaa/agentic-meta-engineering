"""F-013 · workflow_loader 7 字段白名单 schema 校验测试（AC-10）。

覆盖 acceptance #1-4 + 边界：
  #1  allowed_tools=['Read','Edit'] → 通过 schema
  #2  allowed_tools=42（非 list）→ W100 error
  #3  idle_timeout='30s'（非 int|null）→ W100 error
  #4  output_format={...}（dict）→ 通过 schema
  边界：list 含非 str 元素 → W100 error
  边界：空 list → 通过 schema
  边界：idle_timeout=None（null）→ W100 error（既有逻辑：None 不是正整数）
  边界：output_format=None → 通过 schema（None 允许）

测试运行：
    python3 -m pytest tests/lib/test_workflow_loader_runparams.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

from workflow_loader import load_workflow  # noqa: E402


# ============================================================================
# 辅助：构造最小合法 workflow yaml 文本（含单个节点）
# ============================================================================

def _make_yaml(node_extra: dict) -> str:
    """构造带单个 bash 节点的最小合法 workflow yaml，并注入 node_extra 字段到该节点。

    必须包含顶层必填字段：name / version / category / nodes（loader TOP_REQUIRED）。
    """
    node = {
        "id": "test-node",
        "bash": "echo ok",
    }
    node.update(node_extra)
    workflow = {
        "name": "test-wf",
        "version": 1,
        "category": "assist",
        "nodes": [node],
    }
    return yaml.dump(workflow, allow_unicode=True)


def _has_w100_error(tmp_path: Path, node_extra: dict) -> bool:
    """加载含 node_extra 的 workflow，返回是否有 W100 error（schema 校验失败）。

    Report._findings 为 (file, severity, code, message) tuple 列表。
    """
    yaml_file = tmp_path / "test.yaml"
    yaml_file.write_text(_make_yaml(node_extra), encoding="utf-8")
    result = load_workflow(yaml_file)
    return any(
        sev == "error" and code == "W100"
        for (_, sev, code, _) in result.report.findings()
    )


def _no_errors(tmp_path: Path, node_extra: dict) -> bool:
    """加载含 node_extra 的 workflow，返回是否无任何 error。"""
    yaml_file = tmp_path / "test.yaml"
    yaml_file.write_text(_make_yaml(node_extra), encoding="utf-8")
    result = load_workflow(yaml_file)
    return result.report.errors == 0


# ============================================================================
# acceptance #1：allowed_tools=['Read','Edit'] → 通过 schema
# ============================================================================

def test_allowed_tools_valid_list_passes(tmp_path: Path) -> None:
    """AC-10 acceptance #1：allowed_tools 为合法 list[str] → 无 schema error。"""
    assert _no_errors(tmp_path, {"allowed_tools": ["Read", "Edit"]}), (
        "allowed_tools=['Read','Edit'] 应通过 schema 校验，实际有 error"
    )


# ============================================================================
# acceptance #2：allowed_tools=42（非 list）→ W100 error
# ============================================================================

def test_allowed_tools_non_list_triggers_w100(tmp_path: Path) -> None:
    """AC-10 acceptance #2：allowed_tools 为非 list（整数 42）→ W100 error。"""
    assert _has_w100_error(tmp_path, {"allowed_tools": 42}), (
        "allowed_tools=42 应触发 W100，实际未触发"
    )


# ============================================================================
# acceptance #3：idle_timeout='30s'（非 int|null）→ W100 error
# ============================================================================

def test_idle_timeout_string_triggers_w100(tmp_path: Path) -> None:
    """AC-10 acceptance #3：idle_timeout 为字符串 '30s'（非正整数）→ W100 error。"""
    assert _has_w100_error(tmp_path, {"idle_timeout": "30s"}), (
        "idle_timeout='30s' 应触发 W100，实际未触发"
    )


# ============================================================================
# acceptance #4：output_format={...}（dict）→ 通过 schema
# ============================================================================

def test_output_format_dict_passes(tmp_path: Path) -> None:
    """AC-10 acceptance #4：output_format 为 dict → 无 schema error。"""
    assert _no_errors(tmp_path, {"output_format": {"type": "json"}}), (
        "output_format={type: json} 应通过 schema 校验，实际有 error"
    )


# ============================================================================
# 边界：list 含非 str 元素 → W100
# ============================================================================

def test_allowed_tools_non_str_element_triggers_w100(tmp_path: Path) -> None:
    """list 元素含非 str（整数 99）→ W100 error。"""
    assert _has_w100_error(tmp_path, {"allowed_tools": ["Read", 99]}), (
        "allowed_tools 含非 str 元素应触发 W100，实际未触发"
    )


def test_denied_tools_non_str_element_triggers_w100(tmp_path: Path) -> None:
    """denied_tools 含非 str 元素 → W100 error。"""
    assert _has_w100_error(tmp_path, {"denied_tools": [True]}), (
        "denied_tools 含非 str 元素应触发 W100，实际未触发"
    )


# ============================================================================
# 边界：空 list → 通过 schema
# ============================================================================

def test_allowed_tools_empty_list_passes(tmp_path: Path) -> None:
    """allowed_tools=[] 空 list → 通过 schema（无需元素）。"""
    assert _no_errors(tmp_path, {"allowed_tools": []}), (
        "allowed_tools=[] 应通过 schema 校验，实际有 error"
    )


def test_all_list_fields_empty_pass(tmp_path: Path) -> None:
    """5 个 list 字段全为空 list → 通过 schema。"""
    assert _no_errors(tmp_path, {
        "allowed_tools": [],
        "denied_tools": [],
        "mcp": [],
        "skills": [],
        "agents": [],
    }), "5 个 list 字段均为空 list 时应通过 schema 校验，实际有 error"


# ============================================================================
# 边界：idle_timeout=None（yaml null）→ 通过 schema（int|null 均合法）
# ============================================================================

def test_idle_timeout_null_is_valid(tmp_path: Path) -> None:
    """idle_timeout=null（yaml null → Python None）→ 通过 schema。

    detailed-design.md §3.4.2：idle_timeout 类型为 int|null；null 表示沿用
    NODE_TYPE_DEFAULT_TIMEOUT_MS 中的节点类型默认值。
    """
    assert _no_errors(tmp_path, {"idle_timeout": None}), (
        "idle_timeout=null 应通过 schema 校验（int|null 均合法），实际有 error"
    )


# ============================================================================
# 边界：output_format=None → 通过 schema（None 允许）
# ============================================================================

def test_output_format_none_passes(tmp_path: Path) -> None:
    """output_format=null（None）→ 通过 schema（dict|null 均合法）。"""
    assert _no_errors(tmp_path, {"output_format": None}), (
        "output_format=null 应通过 schema 校验，实际有 error"
    )


# ============================================================================
# 其余 list[str] 字段（denied_tools / mcp / skills / agents）非 list → W100
# ============================================================================

@pytest.mark.parametrize("field_name", ["denied_tools", "mcp", "skills", "agents"])
def test_list_field_non_list_triggers_w100(tmp_path: Path, field_name: str) -> None:
    """list[str] 字段（denied_tools/mcp/skills/agents）设为非 list → W100。"""
    assert _has_w100_error(tmp_path, {field_name: "not-a-list"}), (
        f"{field_name}='not-a-list' 应触发 W100，实际未触发"
    )
