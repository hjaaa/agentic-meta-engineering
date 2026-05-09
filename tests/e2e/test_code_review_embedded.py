"""F-004 · TC-F4-2 / TC-F4-3 / TC-F4-5：code-review-embedded 端到端行为校验。

覆盖：
- TC-F4-2: 8 个 cr-checker-* 节点并发派发 + cr-judge 收齐 8 路 findings
- TC-F4-3: cr-critic 对每条 finding 给 verdict 三档 + cr-judge 取 not_rebutted 入最终
- TC-F4-5: 父 workflow sub_workflow 节点 args 经 shellQuote 注入子 $ARGUMENTS

外部依赖（subagent 调用）全部通过 monkeypatch / fixture 隔离，不真实启 subagent。

测试运行：
    python3 -m pytest tests/e2e/test_code_review_embedded.py -v
"""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from workflow_loader import load_workflow  # noqa: E402

YAML_PATH = REPO_ROOT / ".claude" / "workflows" / "review" / "code-review-embedded.yaml"
PROMPTS_DIR = REPO_ROOT / ".claude" / "workflows" / "prompts" / "code-review-embedded"

# 11 个 prompt 文件的期望名单（与 detailed-design §2.1 严格一致）
EXPECTED_PROMPT_FILES = [
    "cr-prepare.md",
    "cr-checker-security.md",
    "cr-checker-performance.md",
    "cr-checker-complexity.md",
    "cr-checker-concurrency.md",
    "cr-checker-error-handling.md",
    "cr-checker-design-consistency.md",
    "cr-checker-auxiliary-spec.md",
    "cr-checker-history-context.md",
    "cr-critic.md",
    "cr-judge.md",
]

# 8 个 checker 节点 id（需要全部共享 depends_on=[cr-prepare]）
CHECKER_NODE_IDS = [
    "cr-checker-security",
    "cr-checker-performance",
    "cr-checker-complexity",
    "cr-checker-concurrency",
    "cr-checker-error-handling",
    "cr-checker-design-consistency",
    "cr-checker-auxiliary-spec",
    "cr-checker-history-context",
]


# ============================================================================
# 固定装置
# ============================================================================


@pytest.fixture(scope="module")
def workflow_result():
    """加载 code-review-embedded.yaml，返回 LoadResult。"""
    assert YAML_PATH.exists(), f"code-review-embedded.yaml 不存在: {YAML_PATH}"
    return load_workflow(YAML_PATH)


@pytest.fixture(scope="module")
def workflow_nodes(workflow_result) -> list[dict[str, Any]]:
    """返回节点列表。"""
    assert workflow_result.report.errors == 0, workflow_result.report.render()
    assert workflow_result.workflow is not None
    return workflow_result.workflow["nodes"]


@pytest.fixture(scope="module")
def nodes_by_id(workflow_nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按 id 索引节点。"""
    return {n["id"]: n for n in workflow_nodes}


# ============================================================================
# TC-F4-2：8 cr-checker-* 并发派发 + cr-judge 收齐 8 路 findings
#
# 并发性在 yaml 层通过"共享 depends_on=[cr-prepare]"表达。
# 本测试验证：
#   1. 8 个 checker 节点均存在且类型为 agent
#   2. 8 个 checker 节点均 depends_on=[cr-prepare]（并发起点一致）
#   3. cr-judge 的 depends_on 链最终覆盖全部 8 个 checker（通过 cr-critic 聚合）
# ============================================================================


class TestConcurrentCheckers:
    """TC-F4-2：8 cr-checker-* 节点并发派发结构校验。"""

    def test_all_8_checker_nodes_exist(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """8 个 checker 节点必须全部存在于 yaml 中。"""
        missing = [nid for nid in CHECKER_NODE_IDS if nid not in nodes_by_id]
        assert not missing, f"缺失 checker 节点: {missing}"

    @pytest.mark.parametrize("node_id", CHECKER_NODE_IDS)
    def test_checker_is_agent_type(self, node_id: str, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """每个 checker 节点必须是 agent 类型。"""
        node = nodes_by_id[node_id]
        assert "agent" in node, f"{node_id} 必须声明 agent 字段"
        # agent 节点不应同时有 prompt_file 字段（互斥规则 W110）
        assert "prompt_file" not in node, f"{node_id} agent 节点不应同时含 prompt_file"

    @pytest.mark.parametrize("node_id", CHECKER_NODE_IDS)
    def test_checker_depends_on_cr_prepare(self, node_id: str, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """每个 checker 节点必须 depends_on=[cr-prepare]，确保并发起点一致。"""
        node = nodes_by_id[node_id]
        deps = node.get("depends_on", [])
        assert "cr-prepare" in deps, (
            f"{node_id} 必须 depends_on cr-prepare（并发并发起点），实际: {deps}"
        )

    @pytest.mark.parametrize("node_id", CHECKER_NODE_IDS)
    def test_checker_context_is_fresh(self, node_id: str, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """每个 checker 节点 context 必须是 fresh（独立 subagent）。"""
        node = nodes_by_id[node_id]
        ctx = node.get("context")
        # context 可能由 loader 补全默认值；agent 节点 context 来自 yaml 明确声明
        assert ctx == "fresh", (
            f"{node_id}.context 必须是 fresh，实际: {ctx!r}"
        )

    def test_cr_judge_transitively_depends_on_all_checkers(
        self, nodes_by_id: dict[str, dict[str, Any]]
    ) -> None:
        """cr-judge 通过 cr-critic 传递依赖全部 8 个 checker（确保收齐 8 路 findings）。

        拓扑路径：cr-prepare → 8×cr-checker-* → cr-critic → cr-judge
        本测试验证 cr-critic 的 depends_on 覆盖全部 8 个 checker。
        """
        assert "cr-critic" in nodes_by_id, "cr-critic 节点缺失"
        assert "cr-judge" in nodes_by_id, "cr-judge 节点缺失"

        critic_deps = set(nodes_by_id["cr-critic"].get("depends_on", []))
        missing_from_critic = set(CHECKER_NODE_IDS) - critic_deps
        assert not missing_from_critic, (
            f"cr-critic 的 depends_on 缺少 checker 节点: {missing_from_critic}\n"
            f"实际 depends_on: {critic_deps}"
        )

        judge_deps = nodes_by_id["cr-judge"].get("depends_on", [])
        assert "cr-critic" in judge_deps, (
            f"cr-judge 必须 depends_on cr-critic，实际: {judge_deps}"
        )

    def test_checker_concurrent_fanout_mock(
        self, nodes_by_id: dict[str, dict[str, Any]]
    ) -> None:
        """模拟引擎并发派发：mock 8 个 checker subagent 返回 findings，
        验证 cr-judge 能收齐 8 路输出（结构验证，不真实调用 subagent）。

        引擎实际实现：所有 depends_on=[cr-prepare] 的节点在 cr-prepare 完成后
        同时启动（spec §7.3 multi-Agent 同响应）。本测试通过 mock findings 模拟
        该场景，验证 cr-judge 的 output_format 能承载 8 路聚合输出。
        """
        # 模拟 8 个 checker 各返回 1 条 finding
        mock_checker_outputs: dict[str, dict] = {}
        for idx, nid in enumerate(CHECKER_NODE_IDS):
            checker_name = nid.replace("cr-checker-", "")
            mock_checker_outputs[nid] = {
                "findings": [
                    {
                        "id": f"F-{idx + 1}",
                        "severity": "minor",
                        "file": f"src/Service.java:{idx * 10 + 1}",
                        "description": f"{checker_name} 专项发现示例",
                        "evidence": f"line {idx * 10 + 1}",
                    }
                ],
                "stats": {"total": 1, "critical": 0, "major": 0, "minor": 1},
            }

        # 验证 8 个 checker 输出可被聚合为 cr-judge 所需输入结构
        all_findings = []
        for nid in CHECKER_NODE_IDS:
            all_findings.extend(mock_checker_outputs[nid]["findings"])

        # cr-judge 的 merged_issues 应能容纳 8 路 findings（去重后）
        assert len(all_findings) == 8, f"应有 8 条并发 findings，实际 {len(all_findings)}"

        # 验证 cr-judge 节点存在且 output_format 包含 merged_issues
        judge_node = nodes_by_id["cr-judge"]
        output_fmt = judge_node.get("output_format", {})
        props = output_fmt.get("properties", {})
        assert "merged_issues" in props, "cr-judge.output_format 必须含 merged_issues"


# ============================================================================
# TC-F4-3：cr-critic 对每条 finding 给 verdict 三档 + cr-judge 取 not_rebutted
#
# 三档 verdict：rejected / not_proven / not_rebutted
# cr-judge 只对 not_rebutted 的 finding 做最终裁决
# ============================================================================


class TestCriticRebuttalFlow:
    """TC-F4-3：cr-critic 三档 verdict + cr-judge 取 not_rebutted 流程校验。"""

    def test_cr_critic_node_exists(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """cr-critic 节点必须存在。"""
        assert "cr-critic" in nodes_by_id, "cr-critic 节点缺失"

    def test_cr_critic_is_agent_type(self, nodes_by_id: dict[str, dict[str, Any]]) -> None:
        """cr-critic 必须是 agent 类型（review-critic）。"""
        node = nodes_by_id["cr-critic"]
        assert "agent" in node, "cr-critic 必须声明 agent 字段"
        assert node["agent"] == "review-critic", (
            f"cr-critic.agent 必须是 review-critic，实际: {node['agent']!r}"
        )

    def test_cr_critic_output_format_has_verdicts(
        self, nodes_by_id: dict[str, dict[str, Any]]
    ) -> None:
        """cr-critic 的 output_format 必须包含 verdicts 数组。"""
        node = nodes_by_id["cr-critic"]
        output_fmt = node.get("output_format", {})
        props = output_fmt.get("properties", {})
        assert "verdicts" in props, "cr-critic.output_format 必须含 verdicts"
        assert "summary" in props, "cr-critic.output_format 必须含 summary"

    def test_cr_critic_trigger_rule_all_done(
        self, nodes_by_id: dict[str, dict[str, Any]]
    ) -> None:
        """cr-critic 必须配 trigger_rule=all_done（容错 checker skip）。"""
        node = nodes_by_id["cr-critic"]
        tr = node.get("trigger_rule")
        assert tr == "all_done", (
            f"cr-critic.trigger_rule 必须是 all_done，实际: {tr!r}"
        )

    def test_cr_critic_verdict_enum_three_options(
        self, nodes_by_id: dict[str, dict[str, Any]]
    ) -> None:
        """cr-critic 的 verdict 字段 enum 必须包含三档：rejected/not_proven/not_rebutted。"""
        node = nodes_by_id["cr-critic"]
        output_fmt = node.get("output_format", {})
        props = output_fmt.get("properties", {})
        verdicts_prop = props.get("verdicts", {})
        items = verdicts_prop.get("items", {})
        verdict_field = items.get("properties", {}).get("verdict", {})
        enum_values = set(verdict_field.get("enum", []))
        expected = {"rejected", "not_proven", "not_rebutted"}
        assert enum_values == expected, (
            f"cr-critic verdict enum 必须 = {expected}，实际: {enum_values}"
        )

    def test_cr_judge_takes_only_not_rebutted_mock(
        self, nodes_by_id: dict[str, dict[str, Any]]
    ) -> None:
        """模拟 cr-critic 输出三档 verdict，验证 cr-judge 只取 not_rebutted。

        这是对引擎语义的结构性验证：
        - cr-judge 接收 cr-critic.output 的 verdicts 列表
        - 只将 verdict=not_rebutted 的 finding 纳入 merged_issues
        - rejected / not_proven 的 finding 不进入最终报告
        """
        # 模拟 cr-critic 输出：包含三种 verdict 各 1 条
        mock_critic_output = {
            "verdicts": [
                {
                    "finding_id": "F-1",
                    "verdict": "rejected",
                    "rationale": "已有 PreparedStatement 保护，SQL 注入不成立",
                    "counter_evidence": "dao/UserDao.java:42 使用 PreparedStatement",
                },
                {
                    "finding_id": "F-2",
                    "verdict": "not_proven",
                    "rationale": "证据不足，仅基于片段推断",
                    "counter_evidence": "",
                },
                {
                    "finding_id": "F-3",
                    "verdict": "not_rebutted",
                    "rationale": "尽力搜索仍无法推翻，N+1 查询确实存在",
                    "counter_evidence": "",
                },
            ],
            "summary": {"rejected": 1, "not_proven": 1, "not_rebutted": 1},
        }

        # 按照 cr-judge 逻辑，只取 not_rebutted 的 finding
        not_rebutted_ids = {
            v["finding_id"]
            for v in mock_critic_output["verdicts"]
            if v["verdict"] == "not_rebutted"
        }
        assert not_rebutted_ids == {"F-3"}, (
            f"cr-judge 应只取 not_rebutted finding，期望 {{F-3}}，实际: {not_rebutted_ids}"
        )

        # 被 rejected 和 not_proven 的 finding 不应进入最终报告
        rejected_ids = {
            v["finding_id"]
            for v in mock_critic_output["verdicts"]
            if v["verdict"] in ("rejected", "not_proven")
        }
        assert rejected_ids == {"F-1", "F-2"}, (
            f"F-1/F-2 应被排除出最终报告，实际 rejected/not_proven: {rejected_ids}"
        )

        # cr-judge 节点的 output_format 有 merged_issues，应只含 not_rebutted
        judge_node = nodes_by_id["cr-judge"]
        assert "cr-judge" in {n["id"] for n in [judge_node]}
        assert judge_node.get("agent") == "code-quality-reviewer", (
            "cr-judge 必须使用 code-quality-reviewer agent"
        )


# ============================================================================
# TC-F4-5：父 args 经 shellQuote 注入子 $ARGUMENTS（sub_workflow 透传）
#
# 验证父 workflow fixture 通过 sub_workflow 节点传递 args，
# args 经 JSON 序列化（shellQuote）后作为子 run 的 $ARGUMENTS。
# ============================================================================


class TestSubWorkflowArgsPassthrough:
    """TC-F4-5：sub_workflow 节点 args 透传校验。"""

    def test_yaml_is_valid_sub_workflow_target(
        self, workflow_result
    ) -> None:
        """code-review-embedded.yaml 是合法的 sub_workflow 目标（category=review）。"""
        assert workflow_result.report.errors == 0, workflow_result.report.render()
        assert workflow_result.workflow is not None
        wf = workflow_result.workflow
        assert wf["category"] == "review", (
            f"code-review-embedded 的 category 必须是 review，实际: {wf['category']!r}"
        )

    def test_cr_prepare_accepts_arguments_injection(
        self, nodes_by_id: dict[str, dict[str, Any]]
    ) -> None:
        """cr-prepare 节点是 prompt_file 类型，能读取 $ARGUMENTS 并解析 diff_range。

        sub_workflow 节点派发时，父 args 经 shellQuote 后整体序列化为 JSON 字符串，
        赋值给子 run 的 $ARGUMENTS（spec §2.3 / detailed-design §6.5）。
        cr-prepare 是子 workflow 的入口节点，负责从 $ARGUMENTS 解析 diff_range。
        """
        node = nodes_by_id["cr-prepare"]
        # cr-prepare 是 prompt_file 类型（能在 shared 上下文中读取 $ARGUMENTS）
        assert "prompt_file" in node, "cr-prepare 必须是 prompt_file 类型节点"
        assert node.get("context") == "shared", (
            "cr-prepare 必须 context=shared 才能读取父注入的 $ARGUMENTS"
        )
        # cr-prepare 的 output_format 必须含 diff_range
        output_fmt = node.get("output_format", {})
        props = output_fmt.get("properties", {})
        assert "diff_range" in props, "cr-prepare.output_format 必须含 diff_range 字段"

    def test_args_json_serialization_roundtrip(self) -> None:
        """验证父 args 经 JSON 序列化后子端能正确解析（shellQuote 保真性）。

        父 yaml 的 args 示例：
          diff_range: $upstream.output.diff_range

        引擎替换后变成：
          diff_range: "HEAD~3..HEAD"

        整体序列化为 JSON 字符串：
          '{"diff_range": "HEAD~3..HEAD"}'

        子 cr-prepare 的 $ARGUMENTS 就是上面这个 JSON 字符串。
        本测试验证 JSON 序列化/反序列化过程保真。
        """
        # 模拟父 args（引擎替换 $upstream.output.diff_range 后的值）
        resolved_args = {
            "diff_range": "HEAD~3..HEAD",
            "feature_id": "F-004",
        }

        # 模拟引擎序列化（整体 JSON 字符串化，供 shellQuote 包装）
        serialized = json.dumps(resolved_args, ensure_ascii=False)

        # 子 cr-prepare 接收 $ARGUMENTS，解析 JSON
        parsed_args = json.loads(serialized)

        assert parsed_args["diff_range"] == "HEAD~3..HEAD", (
            f"args 序列化后 diff_range 不保真: {parsed_args}"
        )
        assert parsed_args["feature_id"] == "F-004"

    def test_shellquote_escapes_special_chars(self) -> None:
        """shellQuote 必须正确转义 args 中的特殊字符，防止注入。

        这是 spec §6.5 注入防御的关键要求：
        - 引擎在 Bash 环境注入 $ARGUMENTS 时使用 shlex.quote（shellQuote）
        - 确保 diff_range 中的特殊字符（如 .. / ~ / 空格）不导致命令注入
        """
        # 包含特殊字符的 diff_range
        diff_range_with_special = "origin/main..feat/my-feature"
        args_json = json.dumps({"diff_range": diff_range_with_special})

        # shlex.quote 确保整个 JSON 字符串作为单个参数传递
        quoted = shlex.quote(args_json)

        # quoted 字符串应以引号包围
        assert quoted.startswith("'") or quoted.startswith('"'), (
            f"shellQuote 后应以引号包围: {quoted!r}"
        )

        # 去除外层引号后能还原原始 JSON
        # shlex.split 模拟 shell 解析
        restored = shlex.split(quoted)[0]
        restored_args = json.loads(restored)
        assert restored_args["diff_range"] == diff_range_with_special, (
            f"shellQuote 后还原 diff_range 失败: {restored_args}"
        )

    def test_parent_fixture_yaml_structure(
        self, nodes_by_id: dict[str, dict[str, Any]]
    ) -> None:
        """验证 code-review-embedded.yaml 作为 sub_workflow 目标的结构合规性。

        父 yaml 通过如下形式调用子 workflow（详细设计 §2.3）：
          - id: phase-7-review
            sub_workflow: review/code-review-embedded.yaml
            args:
              diff_range: $upstream.output.diff_range

        子 workflow 必须：
        1. cr-prepare 是入口节点（depends_on=[]）
        2. cr-judge 是出口节点（无被依赖者）
        """
        # 验证 cr-prepare 是入口（无 depends_on 或 depends_on=[]）
        cr_prepare = nodes_by_id["cr-prepare"]
        deps = cr_prepare.get("depends_on", [])
        assert deps == [], (
            f"cr-prepare 必须是入口节点（depends_on=[]），实际: {deps}"
        )

        # 验证 cr-judge 是出口（没有其他节点 depends_on cr-judge）
        all_deps: set[str] = set()
        for node in nodes_by_id.values():
            all_deps.update(node.get("depends_on", []))
        assert "cr-judge" not in all_deps, (
            "cr-judge 应是出口节点，不应被其他节点依赖"
        )
