"""F-003 · TC-F3-3 / TC-F3-4 / TC-F3-5：末端 3 节点结构与逻辑校验。

覆盖：
- TC-F3-3: pr-submit 节点存在 + 字段结构合法（Bug-20 修复后由 bash 改为 prompt 节点；
  由 main agent 调 canonical /requirement:submit）
- TC-F3-4: pr-merged-gate 节点存在 + approval 子结构合法（gate_message / depends_on）
- TC-F3-5: archive-finalize 节点存在 + bash 包含归档字段写入 + depends_on 合法

外部命令（gh / yq / git push）全部通过 mock 隔离，不发起真实系统调用。
approval 节点不依赖 tty，只做结构断言。

测试运行：
    python3 -m pytest tests/e2e/test_standard_8phase_terminal_nodes.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from workflow_loader import load_workflow  # noqa: E402

YAML_PATH = REPO_ROOT / ".claude" / "workflows" / "requirement" / "standard-8phase.yaml"

# ============================================================================
# 固定装置
# ============================================================================


@pytest.fixture(scope="module")
def workflow_nodes() -> list[dict[str, Any]]:
    """加载 standard-8phase.yaml，返回节点列表。"""
    result = load_workflow(YAML_PATH)
    if result.report.errors != 0:
        pytest.fail(result.report.render())
    if result.workflow is None:
        pytest.fail("workflow_loader 返回 workflow=None，yaml 可能为空或结构异常")
    return result.workflow["nodes"]


@pytest.fixture(scope="module")
def nodes_by_id(workflow_nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按 id 索引节点，方便快速查找。"""
    return {n["id"]: n for n in workflow_nodes}


# ============================================================================
# TC-F3-3：pr-submit 节点
# ============================================================================


class TestPrSubmitNode:
    """TC-F3-3：pr-submit 节点存在 + prompt/depends_on/output_format 合法。

    Bug-20 修复后由 bash 节点改为 prompt 节点：bash 引用的 PR_TITLE / PR_BODY_FILE /
    BASE_BRANCH / DRAFT_FLAG 四个 env 变量从未被 workflow_dispatcher 注入，必败；
    改为 prompt 节点让 main agent 调 canonical /requirement:submit 完成提交。
    """

    def test_node_exists(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """pr-submit 节点必须存在于 yaml 中。"""
        assert "pr-submit" in nodes_by_id, "pr-submit 节点缺失"

    def test_node_type_is_prompt(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """pr-submit 是 prompt 节点（Bug-20 修复后由 bash 改造）。"""
        node = nodes_by_id["pr-submit"]
        assert "prompt" in node, "pr-submit 必须声明 prompt 字段"
        # prompt 节点不允许同时有 bash / skill / agent 等字段
        for exclusive_field in ("bash", "prompt_file", "skill", "agent", "approval", "loop"):
            assert exclusive_field not in node, (
                f"pr-submit prompt 节点不应含 {exclusive_field!r}"
            )

    def test_prompt_invokes_requirement_submit(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """prompt 内容必须指示 main agent 调 /requirement:submit。"""
        prompt = nodes_by_id["pr-submit"]["prompt"]
        assert "/requirement:submit" in prompt, "pr-submit prompt 必须提到 /requirement:submit"

    def test_prompt_mentions_codex_default(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """Fix 3 联动：prompt 应反映 --codex 默认开启 + --no-codex 关闭的语义。"""
        prompt = nodes_by_id["pr-submit"]["prompt"]
        assert "--codex" in prompt, "pr-submit prompt 应说明 codex 默认行为"

    def test_prompt_mentions_save_node_result(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """prompt 必须指示 main agent 调 save_node_result 写 node_completed 推进 workflow。"""
        prompt = nodes_by_id["pr-submit"]["prompt"]
        assert "save_node_result" in prompt, (
            "pr-submit prompt 必须指示用 save_node_result 写 node_completed"
        )
        assert "pr_url" in prompt, "prompt 必须包含 pr_url 字段名"

    def test_depends_on_test_final_confirm(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """pr-submit 必须依赖 test-final-confirm。"""
        node = nodes_by_id["pr-submit"]
        deps = node.get("depends_on", [])
        assert "test-final-confirm" in deps, (
            f"pr-submit 必须 depends_on test-final-confirm，实际: {deps}"
        )

    def test_output_format_has_pr_url(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """output_format 必须声明 pr_url 属性。"""
        node = nodes_by_id["pr-submit"]
        output_format = node.get("output_format")
        assert output_format is not None, "pr-submit 缺少 output_format"
        props = output_format.get("properties", {})
        assert "pr_url" in props, "pr-submit.output_format.properties 必须含 pr_url"
        assert props["pr_url"].get("type") == "string", "pr_url 类型必须是 string"

    def test_output_format_required_pr_url(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """prompt 节点必须把 pr_url 标为 required（main agent 必须返回该字段）。"""
        node = nodes_by_id["pr-submit"]
        required = node.get("output_format", {}).get("required", [])
        assert "pr_url" in required, (
            f"prompt 节点的 output_format.required 必须含 pr_url，实际: {required}"
        )


# ============================================================================
# TC-F3-4：pr-merged-gate 节点
# ============================================================================


class TestPrMergedGateNode:
    """TC-F3-4：pr-merged-gate 节点存在 + approval 子结构合法。"""

    def test_node_exists(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """pr-merged-gate 节点必须存在。"""
        assert "pr-merged-gate" in nodes_by_id, "pr-merged-gate 节点缺失"

    def test_node_type_is_approval(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """pr-merged-gate 是 approval 节点。"""
        node = nodes_by_id["pr-merged-gate"]
        assert "approval" in node, "pr-merged-gate 必须声明 approval 字段"

    def test_approval_has_gate_message(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """approval 子结构必须含 gate_message 或 message。"""
        approval = nodes_by_id["pr-merged-gate"]["approval"]
        has_message = "gate_message" in approval or "message" in approval
        assert has_message, "pr-merged-gate.approval 必须含 gate_message 或 message"

    def test_gate_message_mentions_merge(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """gate_message 内容应与 PR 合并确认相关。"""
        approval = nodes_by_id["pr-merged-gate"]["approval"]
        gate_msg = approval.get("gate_message", approval.get("message", ""))
        # 消息应包含"合并"或 "merge" 等关键词
        assert any(kw in gate_msg.lower() for kw in ("合并", "merge", "pr", "approve", "归档")), (
            f"gate_message 内容与 PR 合并无关: {gate_msg!r}"
        )

    def test_depends_on_pr_submit(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """pr-merged-gate 必须依赖 pr-submit。"""
        deps = nodes_by_id["pr-merged-gate"].get("depends_on", [])
        assert "pr-submit" in deps, (
            f"pr-merged-gate 必须 depends_on pr-submit，实际: {deps}"
        )

    def test_approval_no_exclusive_fields(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """approval 节点不应同时含 bash / prompt 等互斥字段。"""
        node = nodes_by_id["pr-merged-gate"]
        for exclusive_field in ("bash", "prompt", "prompt_file", "skill", "agent", "loop"):
            assert exclusive_field not in node, (
                f"pr-merged-gate approval 节点不应含 {exclusive_field!r}"
            )


# ============================================================================
# TC-F3-5：archive-finalize 节点
# ============================================================================


class TestArchiveFinalizeNode:
    """TC-F3-5：archive-finalize 节点存在 + bash 含归档字段 + depends_on 合法。"""

    def test_node_exists(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """archive-finalize 节点必须存在。"""
        assert "archive-finalize" in nodes_by_id, "archive-finalize 节点缺失"

    def test_node_type_is_bash(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """archive-finalize 是 bash 节点。"""
        node = nodes_by_id["archive-finalize"]
        assert "bash" in node, "archive-finalize 必须声明 bash 字段"

    def test_bash_writes_archived_at(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """bash 必须写 archived_at 字段到 meta.yaml。"""
        bash_script = nodes_by_id["archive-finalize"]["bash"]
        assert "archived_at" in bash_script, "archive-finalize bash 必须写 archived_at"

    def test_bash_writes_outcome_shipped(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """bash 必须写 outcome = shipped 到 meta.yaml。"""
        bash_script = nodes_by_id["archive-finalize"]["bash"]
        assert "outcome" in bash_script, "archive-finalize bash 必须写 outcome"
        assert "shipped" in bash_script, "archive-finalize bash 必须把 outcome 设为 shipped"

    def test_bash_writes_phase_completed(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """bash 必须写 phase = completed 到 meta.yaml。"""
        bash_script = nodes_by_id["archive-finalize"]["bash"]
        assert "phase" in bash_script, "archive-finalize bash 必须写 phase"
        assert "completed" in bash_script, "archive-finalize bash 必须把 phase 设为 completed"

    def test_bash_writes_workflow_status(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """bash 必须写 workflow_status = completed。"""
        bash_script = nodes_by_id["archive-finalize"]["bash"]
        assert "workflow_status" in bash_script, "archive-finalize bash 必须写 workflow_status"

    def test_bash_writes_completed_at(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """bash 必须写 completed_at 字段到 meta.yaml。"""
        bash_script = nodes_by_id["archive-finalize"]["bash"]
        assert "completed_at" in bash_script, "archive-finalize bash 必须写 completed_at"

    def test_bash_uses_yq(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """bash 必须用 yq 写入 meta.yaml（不允许直接 echo 覆盖）。"""
        bash_script = nodes_by_id["archive-finalize"]["bash"]
        assert "yq" in bash_script, "archive-finalize bash 必须用 yq 写入 meta.yaml"

    def test_depends_on_pr_merged_gate(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """archive-finalize 必须依赖 pr-merged-gate。"""
        deps = nodes_by_id["archive-finalize"].get("depends_on", [])
        assert "pr-merged-gate" in deps, (
            f"archive-finalize 必须 depends_on pr-merged-gate，实际: {deps}"
        )

    def test_archive_finalize_is_last_node(self, workflow_nodes: list[dict[str, Any]]) -> None:
        """archive-finalize 是 yaml 定义的最后一个节点（拓扑末端）。"""
        last_node_id = workflow_nodes[-1]["id"]
        assert last_node_id == "archive-finalize", (
            f"archive-finalize 应为末端节点，实际末端为: {last_node_id!r}"
        )

    def test_old_nodes_removed(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """确认 workflow-mark-completed 和 workflow-summary 已被移除。"""
        assert "workflow-mark-completed" not in nodes_by_id, (
            "workflow-mark-completed 应已被 archive-finalize 替换"
        )
        assert "workflow-summary" not in nodes_by_id, (
            "workflow-summary 应已删除"
        )


# ============================================================================
# 整体节点数断言
# ============================================================================


def test_total_node_count(workflow_nodes: list[dict[str, Any]]) -> None:
    """TC-F3-3/4/5 前提：yaml 总节点数 = 38。"""
    assert len(workflow_nodes) == 38, (
        f"standard-8phase.yaml 节点数应为 38，实际为 {len(workflow_nodes)}"
    )


def test_terminal_nodes_in_order(workflow_nodes: list[dict[str, Any]]) -> None:
    """末端 3 节点顺序必须为 pr-submit → pr-merged-gate → archive-finalize。"""
    last_three = [n["id"] for n in workflow_nodes[-3:]]
    assert last_three == ["pr-submit", "pr-merged-gate", "archive-finalize"], (
        f"末端 3 节点顺序不对：{last_three}"
    )


# ============================================================================
# Acceptance 入口 wrapper（TC-F3-3/4/5 模块级函数，对应 features.json acceptance 路径）
# 保留上方 27 个类内测试不变；wrapper 仅做关键断言委托。
# ============================================================================


def test_pr_submit_node(nodes_by_id: dict[str, dict[str, Any]]) -> None:
    """Acceptance TC-F3-3 入口：委托给 TestPrSubmitNode 关键断言（Bug-20 修复后语义更新）。"""
    node = nodes_by_id.get("pr-submit")
    assert node is not None, "pr-submit 节点缺失"
    assert "prompt" in node, "pr-submit 必须为 prompt 类型（Bug-20 修复后从 bash 改造）"
    assert "bash" not in node, "pr-submit 不应再有 bash 字段（已迁移到 prompt）"
    assert "/requirement:submit" in node["prompt"]
    assert "save_node_result" in node["prompt"]
    assert "pr_url" in node["prompt"]


def test_pr_merged_gate_approval(nodes_by_id: dict[str, dict[str, Any]]) -> None:
    """Acceptance TC-F3-4 入口：委托给 TestPrMergedGateNode 关键断言。"""
    node = nodes_by_id.get("pr-merged-gate")
    assert node is not None
    assert "approval" in node
    assert node["approval"].get("gate_message", "").strip() != ""


def test_archive_finalize_node(nodes_by_id: dict[str, dict[str, Any]]) -> None:
    """Acceptance TC-F3-5 入口：委托给 TestArchiveFinalizeNode 关键断言。"""
    node = nodes_by_id.get("archive-finalize")
    assert node is not None
    assert "bash" in node
    assert "archived_at" in node["bash"]
    assert "outcome" in node["bash"]
    assert "归档完成" in node["bash"]
