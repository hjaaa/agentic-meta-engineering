"""F-001 · TC-F1-5：loader 接受真实 workflow yaml。
F-003 · TC-F3-1：38 节点解析 + 拓扑序合法 + 每个 prompt_file 路径真实存在。

覆盖：
- standard-8phase.yaml 必须无错通过 loader
- code-review-embedded.yaml 不存在时跳过该断言（属 F-004 范围）
- TC-F3-1（F-003 新增）：38 节点 + 拓扑合法 + prompt_file 文件真实存在

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
PROMPTS_DIR = REPO_ROOT / ".claude" / "workflows" / "prompts"


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


# ============================================================================
# TC-F3-1（F-003 新增）：38 节点解析 + 拓扑序合法 + prompt_file 文件真实存在
# ============================================================================


def test_standard_8phase_loadable():
    """TC-F3-1：standard-8phase.yaml 38 节点解析 + 拓扑序合法 + prompt_file 路径真实存在。

    1. 节点数 = 38（F-003 目标）
    2. loader 无错（包含 DAG 拓扑合法性 + prompt_file 存在性校验）
    3. 所有 prompt_file 引用路径在文件系统上真实存在（含 loop.prompt_file）
    """
    target = WORKFLOWS_DIR / "requirement" / "standard-8phase.yaml"
    if not target.exists():
        pytest.fail(f"standard-8phase.yaml 不存在: {target}")

    result = load_workflow(target)

    # 1) loader 无错（含 DAG + prompt_file 路径校验）
    assert result.report.errors == 0, (
        f"standard-8phase.yaml loader 报错:\n{result.report.render()}"
    )
    assert result.workflow is not None

    # 2) 节点数精确 = 38
    nodes = result.workflow["nodes"]
    assert len(nodes) == 38, (
        f"standard-8phase.yaml 节点数应为 38，实际为 {len(nodes)}"
    )

    # 3) 所有 prompt_file 路径在文件系统上真实存在
    #    loader 已做 W142 校验，此处再次断言确保测试层可见
    missing_prompt_files: list[str] = []
    for node in nodes:
        for pf_value in [
            node.get("prompt_file"),
            (node.get("loop") or {}).get("prompt_file") if isinstance(node.get("loop"), dict) else None,
        ]:
            if not pf_value or not isinstance(pf_value, str):
                continue
            # 解析路径（与 loader._resolve_prompt_file 保持一致）
            cleaned = pf_value
            if cleaned.startswith("prompts/"):
                cleaned = cleaned[len("prompts/"):]
            resolved = (PROMPTS_DIR / cleaned).resolve()
            if not resolved.exists():
                missing_prompt_files.append(pf_value)

    assert not missing_prompt_files, (
        f"以下 prompt_file 路径不存在:\n"
        + "\n".join(f"  {p}" for p in missing_prompt_files)
    )
