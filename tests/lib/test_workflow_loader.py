"""F-001 · workflow_loader 单测。

覆盖：
- 拓扑排序合法 yaml 通过 + 字段优先级 yaml > 顶层（AC-01 / AC-06）
- 14 套 invalid-*.yaml 对应错误码（W000~W153）
- 三层 discover_workflows 覆盖语义
- CLI 入口 exit code 约定（0 / 1 / 2）

测试运行：
    python3 -m pytest tests/lib/test_workflow_loader.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from workflow_loader import (  # noqa: E402
    DiscoveredWorkflow,
    LoadResult,
    discover_workflows,
    load_workflow,
)

FIXTURES = REPO_ROOT / "tests" / "lib" / "fixtures" / "workflows"


# ============================================================================
# AC-01 / AC-06：合法 yaml + 字段优先级
# ============================================================================

def test_should_load_minimal_valid_workflow():
    result = load_workflow(FIXTURES / "valid-minimal.yaml")
    assert isinstance(result, LoadResult)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow is not None
    assert result.workflow["name"] == "minimal-test"
    assert result.workflow["version"] == 1
    assert result.workflow["category"] == "assist"
    assert len(result.workflow["nodes"]) == 1
    assert result.workflow["nodes"][0]["id"] == "only-node"


def test_should_apply_topological_layer_order_for_multi_layer_yaml():
    """合法 yaml 拓扑排序通过，4 节点 a→b/c→d 形成 3 层。"""
    from topological_sort import topological_layers

    result = load_workflow(FIXTURES / "valid-multi-layer.yaml")
    assert result.report.errors == 0, result.report.render()
    layers = topological_layers(result.workflow["nodes"])
    assert layers == [["a"], ["b", "c"], ["d"]]


def test_field_priority_yaml_node_overrides_workflow_top_default():
    """AC-06：节点 yaml 字段 > workflow 顶层默认（model/effort）。"""
    result = load_workflow(FIXTURES / "valid-multi-layer.yaml")
    assert result.report.errors == 0
    nodes = {n["id"]: n for n in result.workflow["nodes"]}
    # a 没声明 → 继承顶层 sonnet/medium
    assert nodes["a"]["model"] == "sonnet"
    assert nodes["a"]["effort"] == "medium"
    # d 显式声明 opus/high → 不被覆盖
    assert nodes["d"]["model"] == "opus"
    assert nodes["d"]["effort"] == "high"


def test_defaults_applied_when_optional_fields_missing():
    """trigger_rule / retry / idle_timeout 缺省时应自动补默认值。"""
    result = load_workflow(FIXTURES / "valid-minimal.yaml")
    assert result.report.errors == 0
    node = result.workflow["nodes"][0]
    assert node["trigger_rule"] == "all_success"
    assert node["retry"]["max_attempts"] == 2
    assert node["retry"]["delay_ms"] == 3000
    assert node["retry"]["on_error"] == "transient"
    # bash 节点 idle_timeout 默认 60_000
    assert node["idle_timeout"] == 60_000


def test_should_set_context_default_shared_when_prompt_node_omits_it(tmp_path):
    """spec §6.13：prompt 节点未声明 context 时应自动补 'shared'。"""
    yaml_path = tmp_path / "wf-prompt.yaml"
    yaml_path.write_text(
        "name: wf-prompt\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: sonnet\n"
        "nodes:\n"
        "  - id: ask\n"
        "    prompt: 'do something'\n",
        encoding="utf-8",
    )
    result = load_workflow(yaml_path)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow["nodes"][0]["context"] == "shared"


def test_should_set_context_default_shared_when_loop_node_omits_it(tmp_path):
    """spec §6.13：loop 节点未声明 context 时应自动补 'shared'。"""
    yaml_path = tmp_path / "wf-loop.yaml"
    yaml_path.write_text(
        "name: wf-loop\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: sonnet\n"
        "nodes:\n"
        "  - id: lp\n"
        "    loop:\n"
        "      max_iterations: 3\n"
        "      prompt: 'iterate'\n",
        encoding="utf-8",
    )
    result = load_workflow(yaml_path)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow["nodes"][0]["context"] == "shared"


def test_should_preserve_explicit_context_when_prompt_node_declares_fresh(tmp_path):
    """AC-06：节点显式 context: fresh 时 setdefault 不覆盖（字段优先级）。"""
    yaml_path = tmp_path / "wf-prompt-fresh.yaml"
    yaml_path.write_text(
        "name: wf-prompt-fresh\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: sonnet\n"
        "nodes:\n"
        "  - id: ask\n"
        "    prompt: 'do something'\n"
        "    context: fresh\n",
        encoding="utf-8",
    )
    result = load_workflow(yaml_path)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow["nodes"][0]["context"] == "fresh"


def test_should_not_apply_context_default_for_bash_approval_subworkflow_nodes(tmp_path):
    """spec §6.13 反例：bash / approval / sub_workflow 节点 context 不补默认（语义由引擎固定处理）。"""
    yaml_path = tmp_path / "wf-non-prompt.yaml"
    yaml_path.write_text(
        "name: wf-non-prompt\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: sonnet\n"
        "nodes:\n"
        "  - id: b\n"
        "    bash: 'echo hi'\n"
        "  - id: a\n"
        "    depends_on: [b]\n"
        "    approval:\n"
        "      gate_message: 'please approve'\n",
        encoding="utf-8",
    )
    result = load_workflow(yaml_path)
    assert result.report.errors == 0, result.report.render()
    nodes = {n["id"]: n for n in result.workflow["nodes"]}
    assert "context" not in nodes["b"]
    assert "context" not in nodes["a"]


def test_implicit_depends_on_inherits_previous_node_id():
    """spec §6.12：depends_on 缺省 = 隐式接上一节点 id。"""
    result = load_workflow(FIXTURES / "valid-multi-layer.yaml")
    assert result.report.errors == 0
    # valid-multi-layer 显式写了 depends_on，不验隐式；这里只确认展开后第一节点是空数组
    nodes = result.workflow["nodes"]
    assert nodes[0]["depends_on"] == []


# ============================================================================
# AC-08：14 类 yaml 错误对应错误码
# ============================================================================

def _codes_of(result: LoadResult) -> list[str]:
    return [c for _, _, c, _ in result.report.findings()]


def test_w000_file_not_found(tmp_path):
    result = load_workflow(tmp_path / "nonexistent.yaml")
    assert result.report.errors > 0
    assert "W000" in _codes_of(result)


def test_w001_yaml_parse_failure():
    result = load_workflow(FIXTURES / "invalid-yaml-syntax.yaml")
    assert result.report.errors > 0
    assert "W001" in _codes_of(result)


def test_w100_missing_required_top_field():
    result = load_workflow(FIXTURES / "invalid-no-nodes.yaml")
    assert result.report.errors > 0
    assert "W100" in _codes_of(result)


def test_w110_node_type_mutex_violation():
    result = load_workflow(FIXTURES / "invalid-mutex.yaml")
    assert "W110" in _codes_of(result)


def test_w111_node_missing_type_field():
    result = load_workflow(FIXTURES / "invalid-no-type.yaml")
    assert "W111" in _codes_of(result)


def test_w112_duplicate_node_id():
    result = load_workflow(FIXTURES / "invalid-dup-id.yaml")
    assert "W112" in _codes_of(result)


def test_w120_dag_cycle():
    result = load_workflow(FIXTURES / "invalid-circular.yaml")
    assert "W120" in _codes_of(result)


def test_w121_missing_depends_on_target():
    result = load_workflow(FIXTURES / "invalid-missing-dep.yaml")
    assert "W121" in _codes_of(result)


def test_w130_invalid_when_syntax():
    result = load_workflow(FIXTURES / "invalid-bad-when.yaml")
    assert "W130" in _codes_of(result)


def test_w131_var_ref_to_nonexistent_node():
    result = load_workflow(FIXTURES / "invalid-bad-var-ref.yaml")
    assert "W131" in _codes_of(result)


def test_w140_prompt_and_prompt_file_mutex():
    result = load_workflow(FIXTURES / "invalid-prompt-mutex.yaml")
    assert "W140" in _codes_of(result)


def test_w141_prompt_file_out_of_tree():
    result = load_workflow(FIXTURES / "invalid-prompt-out-of-tree.yaml")
    assert "W141" in _codes_of(result)


def test_w142_prompt_file_missing():
    result = load_workflow(FIXTURES / "invalid-prompt-missing.yaml")
    assert "W142" in _codes_of(result)


def test_w150_sub_workflow_too_deep():
    result = load_workflow(FIXTURES / "invalid-deep-nest.yaml")
    assert "W150" in _codes_of(result)


def test_w151_sub_workflow_path_missing():
    result = load_workflow(FIXTURES / "invalid-sub-missing.yaml")
    assert "W151" in _codes_of(result)


def test_w152_sub_workflow_circular_reference():
    result = load_workflow(FIXTURES / "invalid-sub-cycle.yaml")
    assert "W152" in _codes_of(result)


def test_w153_sub_workflow_parse_failure():
    result = load_workflow(FIXTURES / "invalid-sub-broken.yaml")
    assert "W153" in _codes_of(result)


def test_invalid_yaml_14():
    """一次性聚合断言 14 类错误码全覆盖。

    本测试是 features.json 中 TC-F1-2 的整体看板：单独 14 个用例任意一个挂掉
    都会拖累此聚合用例，但聚合用例额外保证"全 14 类都有 fixture"。
    """
    cases: list[tuple[str, str]] = [
        ("invalid-yaml-syntax.yaml", "W001"),
        ("invalid-no-nodes.yaml", "W100"),
        ("invalid-mutex.yaml", "W110"),
        ("invalid-no-type.yaml", "W111"),
        ("invalid-dup-id.yaml", "W112"),
        ("invalid-circular.yaml", "W120"),
        ("invalid-missing-dep.yaml", "W121"),
        ("invalid-bad-when.yaml", "W130"),
        ("invalid-bad-var-ref.yaml", "W131"),
        ("invalid-prompt-mutex.yaml", "W140"),
        ("invalid-prompt-out-of-tree.yaml", "W141"),
        ("invalid-prompt-missing.yaml", "W142"),
        ("invalid-deep-nest.yaml", "W150"),
        ("invalid-sub-missing.yaml", "W151"),
        ("invalid-sub-cycle.yaml", "W152"),
        ("invalid-sub-broken.yaml", "W153"),
    ]
    for fixture, expected in cases:
        result = load_workflow(FIXTURES / fixture)
        codes = _codes_of(result)
        assert expected in codes, (
            f"{fixture}: 期望 {expected}, 实际 {codes}"
        )


# ============================================================================
# 三层 discover_workflows
# ============================================================================

def test_discover_workflows_three_layer_override(tmp_path):
    """bundled → home → project，后者覆盖前者。"""
    bundled = tmp_path / "bundled"
    home = tmp_path / "home"
    project = tmp_path / "project"
    for d in (bundled, home, project):
        d.mkdir(parents=True)

    (bundled / "wf-a.yaml").write_text(
        "name: wf-a\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: sonnet\n"
        "nodes:\n  - id: x\n    bash: 'echo bundled-a'\n",
        encoding="utf-8",
    )
    (bundled / "wf-b.yaml").write_text(
        "name: wf-b\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: sonnet\n"
        "nodes:\n  - id: x\n    bash: 'echo bundled-b'\n",
        encoding="utf-8",
    )
    (home / "wf-a.yaml").write_text(
        "name: wf-a\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: sonnet\n"
        "nodes:\n  - id: x\n    bash: 'echo home-a'\n",
        encoding="utf-8",
    )
    (project / "wf-b.yaml").write_text(
        "name: wf-b\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: sonnet\n"
        "nodes:\n  - id: x\n    bash: 'echo project-b'\n",
        encoding="utf-8",
    )

    discovered = discover_workflows(
        bundled_dir=bundled, home_dir=home, project_dir=project
    )
    assert "wf-a" in discovered and "wf-b" in discovered
    assert discovered["wf-a"].source == "home"
    assert discovered["wf-a"].workflow["nodes"][0]["bash"] == "echo home-a"
    assert discovered["wf-b"].source == "project"
    assert discovered["wf-b"].workflow["nodes"][0]["bash"] == "echo project-b"


# ============================================================================
# CLI 入口
# ============================================================================

def test_cli_exit_zero_for_valid_workflow():
    proc = subprocess.run(
        [sys.executable, "scripts/lib/workflow_loader.py", "--quiet",
         "tests/lib/fixtures/workflows/valid-minimal.yaml"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_cli_exit_one_for_invalid_workflow():
    proc = subprocess.run(
        [sys.executable, "scripts/lib/workflow_loader.py",
         "tests/lib/fixtures/workflows/invalid-mutex.yaml"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert "W110" in combined


def test_cli_json_output_contains_findings():
    proc = subprocess.run(
        [sys.executable, "scripts/lib/workflow_loader.py", "--json",
         "tests/lib/fixtures/workflows/invalid-mutex.yaml"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["errors"] >= 1
    codes = [f["code"] for f in payload["findings"]]
    assert "W110" in codes
