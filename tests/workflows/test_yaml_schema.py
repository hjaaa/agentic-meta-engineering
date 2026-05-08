"""F-001 · TC-F1-5：loader 接受真实 workflow yaml。

覆盖：
- standard-8phase.yaml 必须无错通过 loader
- code-review-embedded.yaml 不存在时跳过该断言（属 F-004 范围）

测试运行：
    python3 -m pytest tests/workflows/test_yaml_schema.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from workflow_loader import load_workflow  # noqa: E402

WORKFLOWS_DIR = REPO_ROOT / ".claude" / "workflows"


def test_standard_8phase_yaml_is_loadable():
    target = WORKFLOWS_DIR / "requirement" / "standard-8phase.yaml"
    if not target.exists():
        pytest.fail(f"standard-8phase.yaml 不存在: {target}")
    result = load_workflow(target)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow["name"] == "standard-8phase"
    assert result.workflow["category"] == "requirement"
    assert len(result.workflow["nodes"]) >= 30, "节点数应 ≥ 30（spec 锁定 ~38）"


def test_code_review_embedded_yaml_is_loadable_if_present():
    """code-review-embedded.yaml 是 F-004 产物；F-001 阶段不存在，跳过。"""
    target = WORKFLOWS_DIR / "code-review-embedded.yaml"
    alternates = list(WORKFLOWS_DIR.rglob("code-review-embedded.yaml"))
    if not target.exists() and not alternates:
        pytest.skip("code-review-embedded.yaml 由 F-004 提供，本 feature 阶段未就绪")
    yaml_path = target if target.exists() else alternates[0]
    result = load_workflow(yaml_path)
    assert result.report.errors == 0, result.report.render()
