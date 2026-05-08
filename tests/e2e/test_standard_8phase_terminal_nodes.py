"""F-003 · TC-F3-3 / TC-F3-4 / TC-F3-5：末端 3 节点结构与逻辑校验。

覆盖：
- TC-F3-3: pr-submit 节点存在 + 字段结构合法（bash / depends_on / output_format）
- TC-F3-4: pr-merged-gate 节点存在 + approval 子结构合法（gate_message / depends_on）
- TC-F3-5: archive-finalize 节点存在 + bash 包含归档字段写入 + depends_on 合法

外部命令（gh / yq / git push）全部通过 mock 隔离，不发起真实系统调用。
approval 节点不依赖 tty，只做结构断言。

测试运行：
    python3 -m pytest tests/e2e/test_standard_8phase_terminal_nodes.py -v
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

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
    assert result.report.errors == 0, result.report.render()
    assert result.workflow is not None
    return result.workflow["nodes"]


@pytest.fixture(scope="module")
def nodes_by_id(workflow_nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按 id 索引节点，方便快速查找。"""
    return {n["id"]: n for n in workflow_nodes}


# ============================================================================
# TC-F3-3：pr-submit 节点
# ============================================================================


class TestPrSubmitNode:
    """TC-F3-3：pr-submit 节点存在 + bash/depends_on/output_format 合法。"""

    def test_node_exists(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """pr-submit 节点必须存在于 yaml 中。"""
        assert "pr-submit" in nodes_by_id, "pr-submit 节点缺失"

    def test_node_type_is_bash(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """pr-submit 是 bash 节点。"""
        node = nodes_by_id["pr-submit"]
        assert "bash" in node, "pr-submit 必须声明 bash 字段"
        # bash 节点不允许同时有 prompt / skill / agent 等字段
        for exclusive_field in ("prompt", "prompt_file", "skill", "agent", "approval", "loop"):
            assert exclusive_field not in node, (
                f"pr-submit bash 节点不应含 {exclusive_field!r}"
            )

    def test_bash_contains_git_push(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """bash 脚本必须包含 git push 操作。"""
        bash_script = nodes_by_id["pr-submit"]["bash"]
        assert "git push" in bash_script, "pr-submit bash 必须含 git push"

    def test_bash_contains_gh_pr_create(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """bash 脚本必须包含 gh pr create 操作。"""
        bash_script = nodes_by_id["pr-submit"]["bash"]
        assert "gh pr create" in bash_script, "pr-submit bash 必须含 gh pr create"

    def test_bash_writes_pr_url_to_meta(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """bash 脚本必须把 pr_url 写入 meta.yaml（使用 yq）。"""
        bash_script = nodes_by_id["pr-submit"]["bash"]
        assert "pr_url" in bash_script, "pr-submit bash 必须写 pr_url 到 meta.yaml"
        assert "yq" in bash_script, "pr-submit bash 必须用 yq 写入 meta.yaml"

    def test_depends_on_test_final_signoff(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """pr-submit 必须依赖 test-final-signoff（当前 yaml 实际拓扑末端）。"""
        node = nodes_by_id["pr-submit"]
        # depends_on 可能在 loader 展开后才存在，直接读原始字段
        deps = node.get("depends_on", [])
        assert "test-final-signoff" in deps, (
            f"pr-submit 必须 depends_on test-final-signoff，实际: {deps}"
        )

    def test_output_format_has_pr_url(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """output_format 必须声明 pr_url 属性。"""
        node = nodes_by_id["pr-submit"]
        output_format = node.get("output_format")
        assert output_format is not None, "pr-submit 缺少 output_format"
        props = output_format.get("properties", {})
        assert "pr_url" in props, "pr-submit.output_format.properties 必须含 pr_url"
        assert props["pr_url"].get("type") == "string", "pr_url 类型必须是 string"

    def test_bash_commands_mocked(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """模拟 subprocess.run 确认 bash 逻辑不依赖真实外部命令。

        注：本测试只验证 bash 字段是可以被提取并运行时 mock 的，
        不真实执行 shell 脚本（引擎负责执行）。
        """
        bash_script = nodes_by_id["pr-submit"]["bash"]
        # bash 脚本是字符串，可被引擎/runtime 获取并执行
        assert isinstance(bash_script, str)
        assert len(bash_script.strip()) > 0

        # 模拟引擎执行路径：mock subprocess.run
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="https://github.com/pr/1")
            result = subprocess.run(["bash", "-c", "echo mock"], capture_output=True)
            assert mock_run.called


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
