"""F-006 · worktree 配置块的加载与枚举值识别测试。

验证：
- workflow_loader 能识别并透传顶层 worktree 字段
- policy 枚举值（auto / never / require / current）全识别
- 标准 8 阶段 workflow 的 worktree 配置块被正确加载
"""
from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from workflow_loader import load_workflow  # noqa: E402


STANDARD_8PHASE = REPO_ROOT / ".claude" / "workflows" / "requirement" / "standard-8phase.yaml"


def test_should_load_worktree_block_from_standard_8phase():
    """标准 8 阶段 workflow 应包含顶层 worktree 配置块。"""
    result = load_workflow(STANDARD_8PHASE)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow is not None
    assert "worktree" in result.workflow, "standard-8phase.yaml 缺少 worktree 块"
    wt = result.workflow["worktree"]
    assert isinstance(wt, dict), f"worktree 必须是 mapping，实际 {type(wt).__name__}"


def test_worktree_block_has_all_required_fields():
    """worktree 块必须含 5 个字段：enabled / policy / location / setup.baseline.command / setup.baseline.required。"""
    result = load_workflow(STANDARD_8PHASE)
    assert result.report.errors == 0, result.report.render()
    wt = result.workflow["worktree"]

    # 5 个必填字段
    assert "enabled" in wt, "worktree 缺少 enabled"
    assert "policy" in wt, "worktree 缺少 policy"
    assert "location" in wt, "worktree 缺少 location"
    assert "setup" in wt, "worktree 缺少 setup"

    # setup.baseline 的两个字段
    assert isinstance(wt["setup"], dict), "setup 必须是 mapping"
    assert "baseline" in wt["setup"], "setup 缺少 baseline"
    baseline = wt["setup"]["baseline"]
    assert isinstance(baseline, dict), "baseline 必须是 mapping"
    assert "command" in baseline, "baseline 缺少 command"
    assert "required" in baseline, "baseline 缺少 required"


def test_worktree_enabled_field_is_boolean():
    """enabled 字段应为布尔值。"""
    result = load_workflow(STANDARD_8PHASE)
    wt = result.workflow["worktree"]
    assert isinstance(wt["enabled"], bool), f"enabled 应为 bool，实际 {type(wt['enabled']).__name__}"


def test_worktree_policy_default_is_auto():
    """standard-8phase.yaml 中 policy 应默认为 'auto'。"""
    result = load_workflow(STANDARD_8PHASE)
    wt = result.workflow["worktree"]
    assert wt["policy"] == "auto", f"policy 应为 'auto'，实际 {wt['policy']!r}"


def test_worktree_policy_enum_auto(tmp_path):
    """policy='auto' 应被认可。"""
    yaml_path = tmp_path / "wf-policy-auto.yaml"
    yaml_path.write_text(
        "name: test-auto\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: sonnet\n"
        "worktree:\n"
        "  enabled: true\n"
        "  policy: auto\n"
        "  location: .worktrees\n"
        "  setup:\n"
        "    baseline:\n"
        "      command: make test\n"
        "      required: true\n"
        "nodes:\n"
        "  - id: x\n    bash: 'echo done'\n",
        encoding="utf-8",
    )
    result = load_workflow(yaml_path)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow["worktree"]["policy"] == "auto"


def test_worktree_policy_enum_never(tmp_path):
    """policy='never' 应被认可。"""
    yaml_path = tmp_path / "wf-policy-never.yaml"
    yaml_path.write_text(
        "name: test-never\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: sonnet\n"
        "worktree:\n"
        "  enabled: false\n"
        "  policy: never\n"
        "  location: .worktrees\n"
        "  setup:\n"
        "    baseline:\n"
        "      command: make test\n"
        "      required: false\n"
        "nodes:\n"
        "  - id: y\n    bash: 'echo done'\n",
        encoding="utf-8",
    )
    result = load_workflow(yaml_path)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow["worktree"]["policy"] == "never"


def test_worktree_policy_enum_require(tmp_path):
    """policy='require' 应被认可。"""
    yaml_path = tmp_path / "wf-policy-require.yaml"
    yaml_path.write_text(
        "name: test-require\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: sonnet\n"
        "worktree:\n"
        "  enabled: true\n"
        "  policy: require\n"
        "  location: .worktrees\n"
        "  setup:\n"
        "    baseline:\n"
        "      command: make gates-validate\n"
        "      required: true\n"
        "nodes:\n"
        "  - id: z\n    bash: 'echo done'\n",
        encoding="utf-8",
    )
    result = load_workflow(yaml_path)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow["worktree"]["policy"] == "require"


def test_worktree_policy_enum_current(tmp_path):
    """policy='current' 应被认可。"""
    yaml_path = tmp_path / "wf-policy-current.yaml"
    yaml_path.write_text(
        "name: test-current\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: sonnet\n"
        "worktree:\n"
        "  enabled: true\n"
        "  policy: current\n"
        "  location: .worktrees\n"
        "  setup:\n"
        "    baseline:\n"
        "      command: make test\n"
        "      required: true\n"
        "nodes:\n"
        "  - id: w\n    bash: 'echo done'\n",
        encoding="utf-8",
    )
    result = load_workflow(yaml_path)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow["worktree"]["policy"] == "current"


def test_worktree_location_is_string():
    """location 字段应为字符串路径。"""
    result = load_workflow(STANDARD_8PHASE)
    wt = result.workflow["worktree"]
    assert isinstance(wt["location"], str), f"location 应为 str，实际 {type(wt['location']).__name__}"
    assert wt["location"] == ".worktrees"


def test_worktree_setup_baseline_command_is_string():
    """setup.baseline.command 应为字符串。"""
    result = load_workflow(STANDARD_8PHASE)
    cmd = result.workflow["worktree"]["setup"]["baseline"]["command"]
    assert isinstance(cmd, str), f"command 应为 str，实际 {type(cmd).__name__}"


def test_worktree_setup_baseline_required_is_boolean():
    """setup.baseline.required 应为布尔值。"""
    result = load_workflow(STANDARD_8PHASE)
    req = result.workflow["worktree"]["setup"]["baseline"]["required"]
    assert isinstance(req, bool), f"required 应为 bool，实际 {type(req).__name__}"


def test_existing_workflow_tests_still_pass():
    """确保追加 worktree 块不破坏现有的 standard-8phase 节点加载。"""
    result = load_workflow(STANDARD_8PHASE)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow is not None
    assert result.workflow["name"] == "standard-8phase"
    assert result.workflow["version"] == 1
    assert result.workflow["category"] == "requirement"
    # 确保 nodes 块仍然正常加载（第一个节点应是 bootstrap-validate）
    assert len(result.workflow["nodes"]) > 0
    first_node = result.workflow["nodes"][0]
    assert first_node["id"] == "bootstrap-validate"
