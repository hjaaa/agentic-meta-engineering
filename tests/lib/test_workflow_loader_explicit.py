"""F-004 · workflow_loader `_expand_implicit_depends_on` 加 `depends_on_explicit` 标记位。

覆盖 acceptance：
- 全显式 depends_on yaml → workflow['depends_on_explicit'] == True
- 任一节点缺省 depends_on → workflow['depends_on_explicit'] == False（loader 仍补 [prev_id]）
- 首节点缺省 depends_on=[] 不算"隐式"（all_explicit 不变）

对应 detail-design §3.4.1 / ADR D-006 / AC-01。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from workflow_loader import load_workflow  # noqa: E402


# ============================================================================
# helper：在 tmp_path 写最小合法 yaml
# ============================================================================

def _write_yaml(tmp_path: Path, body: str) -> Path:
    """body 不含顶层名头部，本 helper 自动拼。"""
    path = tmp_path / "wf.yaml"
    path.write_text(body, encoding="utf-8")
    return path


_HEAD = (
    "name: test-wf\nversion: 1\ncategory: assist\n"
    "provider: claude\nmodel: sonnet\n"
)


# ============================================================================
# AC：全显式 → depends_on_explicit == True
# ============================================================================

def test_全节点显式depends_on_标记为True(tmp_path):
    """全部非首节点显式声明 depends_on → workflow['depends_on_explicit'] == True。"""
    yaml_body = _HEAD + (
        "nodes:\n"
        "  - id: a\n"
        "    bash: 'echo a'\n"
        "    depends_on: []\n"
        "  - id: b\n"
        "    bash: 'echo b'\n"
        "    depends_on: [a]\n"
        "  - id: c\n"
        "    bash: 'echo c'\n"
        "    depends_on: [b]\n"
    )
    path = _write_yaml(tmp_path, yaml_body)
    result = load_workflow(path)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow["depends_on_explicit"] is True, (
        f"期望 True，实际 {result.workflow.get('depends_on_explicit')!r}"
    )


def test_首节点缺省depends_on不算隐式(tmp_path):
    """首节点缺省 depends_on=[] 不算"隐式"——只要其余非首节点全显式，all_explicit 仍 True。"""
    yaml_body = _HEAD + (
        "nodes:\n"
        "  - id: a\n"
        "    bash: 'echo a'\n"               # 首节点缺省 depends_on
        "  - id: b\n"
        "    bash: 'echo b'\n"
        "    depends_on: [a]\n"
    )
    path = _write_yaml(tmp_path, yaml_body)
    result = load_workflow(path)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow["depends_on_explicit"] is True, (
        f"首节点缺省不算隐式，期望 True；实际 {result.workflow.get('depends_on_explicit')!r}"
    )
    # 首节点 depends_on 仍被补成 []
    assert result.workflow["nodes"][0]["depends_on"] == []


def test_非首节点缺省depends_on标记为False(tmp_path):
    """任一非首节点缺省 depends_on → workflow['depends_on_explicit'] == False。

    且 loader 仍补 [prev_id]（兼容退化运行）。
    """
    yaml_body = _HEAD + (
        "nodes:\n"
        "  - id: a\n"
        "    bash: 'echo a'\n"
        "  - id: b\n"
        "    bash: 'echo b'\n"           # 非首节点缺省 depends_on
        "  - id: c\n"
        "    bash: 'echo c'\n"
        "    depends_on: [b]\n"
    )
    path = _write_yaml(tmp_path, yaml_body)
    result = load_workflow(path)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow["depends_on_explicit"] is False, (
        f"非首节点缺省，期望 False；实际 {result.workflow.get('depends_on_explicit')!r}"
    )
    # loader 仍把 b.depends_on 补为 [a]
    nodes = {n["id"]: n for n in result.workflow["nodes"]}
    assert nodes["b"]["depends_on"] == ["a"], (
        f"非首节点缺省 depends_on 应补 [prev_id=a]，实际 {nodes['b']['depends_on']!r}"
    )


# ============================================================================
# 真实仓库 yaml：standard-8phase.yaml 应是 explicit=True（全节点显式）
# ============================================================================

def test_standard_8phase_yaml_为explicit(tmp_path):
    """真实 `.claude/workflows/requirement/standard-8phase.yaml` 全节点显式 → True。"""
    yaml_path = REPO_ROOT / ".claude" / "workflows" / "requirement" / "standard-8phase.yaml"
    if not yaml_path.exists():
        # 不存在时跳过（CI 受限环境）；不构成失败
        return
    result = load_workflow(yaml_path)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow["depends_on_explicit"] is True, (
        f"standard-8phase 全节点显式 depends_on，期望 True；"
        f"实际 {result.workflow.get('depends_on_explicit')!r}"
    )
