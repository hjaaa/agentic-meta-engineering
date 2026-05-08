"""F-002 · 8 种节点类型互斥 / 嵌套深度 / 变量注入单测。

覆盖：
- TC-F2-1：8 种节点类型字段两两互斥（W110，参数化覆盖 4+ 对组合）
- TC-F2-2：sub_workflow 嵌套深度 > 2 触发 W150；深度 = 2 边界值通过
- TC-F2-3：sub_workflow args 经 shellQuote 透传，特殊字符 round-trip 一致
- TC-F2-4：loop 节点 $LOOP_OUTPUT / $LOOP_PREV_OUTPUT 注入语义（首轮空 / 二轮 PREV / bash 转义）

测试运行：
    python3 -m pytest tests/lib/test_node_types.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from substitute_vars import shell_quote, substitute_vars  # noqa: E402
from workflow_loader import load_workflow  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "workflows"


def _codes_of(result) -> set[str]:
    """提取 report.findings() 的错误码集合。"""
    return {f[2] for f in result.report.findings()}


def _w110_messages(result) -> list[str]:
    """提取所有 W110 finding 的消息文本，便于断言"两个字段名都出现"。"""
    return [f[3] for f in result.report.findings() if f[2] == "W110"]


# ============================================================================
# TC-F2-1：8 种节点类型字段两两互斥（W110 / AC-07）
# ============================================================================

@pytest.mark.parametrize(
    "fixture_name, expected_field_a, expected_field_b",
    [
        # 已有 fixture：skill + prompt
        ("invalid-mutex.yaml", "skill", "prompt"),
        # F-002 新增 fixtures，覆盖 NODE_TYPE_GROUPS 中四组互斥配对
        ("invalid-mutex-skill-bash.yaml", "skill", "bash"),
        ("invalid-mutex-agent-prompt.yaml", "agent", "prompt"),
        ("invalid-mutex-loop-approval.yaml", "loop", "approval"),
        ("invalid-mutex-sub-artifact.yaml", "sub_workflow", "artifact"),
    ],
)
def test_8_node_mutex(fixture_name, expected_field_a, expected_field_b):
    # TC-F2-1：节点同时声明两类型字段时，loader 必须输出 W110，且消息含两字段名
    result = load_workflow(FIXTURES / fixture_name)
    assert result.report.errors > 0, f"{fixture_name} 应被拒绝但未报错"
    assert "W110" in _codes_of(result), f"{fixture_name} 应触发 W110，实际 {_codes_of(result)}"
    messages = _w110_messages(result)
    assert messages, f"{fixture_name} 缺少 W110 finding 消息"
    combined = " | ".join(messages)
    assert expected_field_a in combined, (
        f"{fixture_name} W110 消息未提到 {expected_field_a!r}: {combined}"
    )
    assert expected_field_b in combined, (
        f"{fixture_name} W110 消息未提到 {expected_field_b!r}: {combined}"
    )


def test_8_node_mutex_covers_all_node_type_groups():
    # TC-F2-1 完整性围栏：fixture 集合必须覆盖 NODE_TYPE_FIELDS 全 9 个字段（含 prompt_file）
    # 防止后续新增节点类型时漏写互斥 fixture。
    from workflow_loader import NODE_TYPE_FIELDS  # 避免顶层导入污染其他用例

    fixture_files = [
        "invalid-mutex.yaml",
        "invalid-mutex-skill-bash.yaml",
        "invalid-mutex-agent-prompt.yaml",
        "invalid-mutex-loop-approval.yaml",
        "invalid-mutex-sub-artifact.yaml",
    ]
    seen_fields: set[str] = set()
    for fname in fixture_files:
        # 直接读 yaml 抽 fields，避免依赖 loader 内部状态
        import yaml

        with (FIXTURES / fname).open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        for node in raw.get("nodes") or []:
            for field in NODE_TYPE_FIELDS:
                if field in node:
                    seen_fields.add(field)
    # prompt_file 与 prompt 在引擎层等价，通过 prompt 即覆盖该组；剩余 8 字段必须全见过
    missing = set(NODE_TYPE_FIELDS) - seen_fields - {"prompt_file"}
    assert not missing, f"互斥 fixture 未覆盖字段: {sorted(missing)}"


# ============================================================================
# TC-F2-2：sub_workflow 嵌套深度（W150 / AC-07）
# ============================================================================

def test_nest_depth_limit_rejects_depth_3():
    # TC-F2-2：嵌套 3 层（root → l1 → l2）应触发 W150
    result = load_workflow(FIXTURES / "invalid-deep-nest.yaml")
    assert result.report.errors > 0
    codes = _codes_of(result)
    assert "W150" in codes, f"深度 3 应触发 W150，实际 {codes}"


def test_nest_depth_limit_accepts_depth_2_boundary():
    # TC-F2-2 边界：嵌套深度恰好 = 2 必须通过（不报 W150）
    result = load_workflow(FIXTURES / "valid-nest-depth-2.yaml")
    assert result.report.errors == 0, result.report.render()
    assert "W150" not in _codes_of(result)
    # workflow 解析成功后存在 sub_workflow 节点
    assert result.workflow is not None
    nodes = result.workflow["nodes"]
    assert any(n.get("sub_workflow") for n in nodes), "应有 sub_workflow 节点"


# ============================================================================
# TC-F2-3：sub_workflow args 经 shellQuote 透传（spec §6.4 / §6.5）
# ============================================================================

def _bash_echo_roundtrip(quoted: str) -> str:
    """用 bash -c 'echo <quoted>' 把已转义字面量解释回来，便于校验 round-trip。"""
    proc = subprocess.run(
        ["bash", "-c", f"echo {quoted}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.rstrip("\n")


@pytest.mark.parametrize(
    "raw_value",
    [
        "feature_id: F-001",
        "it's a 'tricky' \\path",  # 单引号 + 反斜杠
        'name="quoted" with $VAR and `cmd`',  # 双引号 / shell 元字符
        "中文 + emoji 🚀 + 单引号' 混合",
        "",  # 空字符串
        "; rm -rf /",  # 典型注入串（必须被原样保留为字面量，不被 shell 拆分）
    ],
)
def test_sub_workflow_args_round_trip_via_bash(raw_value):
    # TC-F2-3：substitute_vars 的 escape_for_bash 对 ARGUMENTS 注入做 shellQuote
    # 经 bash 解释后 stdout 与原文严格一致（含特殊字符与空字符串）。
    quoted = substitute_vars(
        "$ARGUMENTS",
        node_outputs=None,
        env={"ARGUMENTS": raw_value},
        escape_for_bash=True,
    )
    assert quoted.startswith("'") and quoted.endswith("'"), f"应被单引号包裹: {quoted!r}"
    echoed = _bash_echo_roundtrip(quoted)
    assert echoed == raw_value, (
        f"round-trip 不一致：\n  原文 = {raw_value!r}\n  echo 回 = {echoed!r}"
    )


def test_sub_workflow_args_node_output_list_serialized_as_json():
    # TC-F2-3：当 args 引用 $node.output（非 field）时，list / dict 走 JSON 序列化路径。
    # 这里直接验证 substitute_vars 对 dict 类型 output 字段的序列化行为。
    node_outputs = {
        "upstream": {
            # output 用 JSON 字符串模拟节点 stdout（spec §6.5：output 是 stdout 字符串）
            "output": json.dumps({"items": ["F-001", "F-002"], "count": 2}),
        }
    }
    # 取 .field 路径 → list 字段被 _serialize_for_substitution → JSON + shellQuote
    quoted = substitute_vars(
        "$upstream.output.items",
        node_outputs=node_outputs,
        env=None,
        escape_for_bash=True,
    )
    assert quoted.startswith("'") and quoted.endswith("'")
    echoed = _bash_echo_roundtrip(quoted)
    # echo 回来的应该是合法 JSON 数组，能解析回原值
    parsed = json.loads(echoed)
    assert parsed == ["F-001", "F-002"]


def test_sub_workflow_args_node_output_dict_serialized_as_json():
    # TC-F2-3：dict 字段同样走 JSON 序列化
    node_outputs = {
        "upstream": {"output": json.dumps({"meta": {"id": "F-001", "title": "测试"}})},
    }
    quoted = substitute_vars(
        "$upstream.output.meta",
        node_outputs=node_outputs,
        env=None,
        escape_for_bash=True,
    )
    echoed = _bash_echo_roundtrip(quoted)
    parsed = json.loads(echoed)
    assert parsed == {"id": "F-001", "title": "测试"}


def test_shell_quote_handles_embedded_single_quote():
    # 直接断言 shell_quote 对嵌入单引号的转义形态（'\\'' 序列）。
    # raw 字面量 = "a'b"  →  期望 quoted = "'a'\\''b'"
    quoted = shell_quote("a'b")
    assert quoted == "'a'\\''b'", quoted
    echoed = _bash_echo_roundtrip(quoted)
    assert echoed == "a'b"


# ============================================================================
# TC-F2-4：$LOOP_OUTPUT / $LOOP_PREV_OUTPUT 注入语义（spec §6.5）
# ============================================================================

def test_loop_output_first_iteration_is_empty_string():
    # TC-F2-4 (a)：首轮 $LOOP_OUTPUT 替换为空字符串（spec §2.5 / §6.5）
    # 引擎从 jsonl 反扫无 loop_iteration_completed 事件 → env 缺失 → substitute 走默认空串
    text = "echo loop=$LOOP_OUTPUT prev=$LOOP_PREV_OUTPUT done"
    rendered = substitute_vars(
        text,
        node_outputs=None,
        env={},  # 模拟首轮：env 完全没有 LOOP_OUTPUT / LOOP_PREV_OUTPUT
        escape_for_bash=False,
    )
    # 命名变量应消失为空字符串
    assert rendered == "echo loop= prev= done", rendered


def test_loop_output_second_iteration_prev_equals_last_stdout():
    # TC-F2-4 (b)：二轮 $LOOP_OUTPUT = 当前轮 stdout / $LOOP_PREV_OUTPUT = 上一轮 stdout
    env = {
        "LOOP_OUTPUT": "round-2-stdout",
        "LOOP_PREV_OUTPUT": "round-1-stdout",
    }
    rendered = substitute_vars(
        "current=$LOOP_OUTPUT prev=$LOOP_PREV_OUTPUT",
        node_outputs=None,
        env=env,
        escape_for_bash=False,
    )
    assert rendered == "current=round-2-stdout prev=round-1-stdout"


def test_loop_output_escape_for_bash_quotes_single_quote():
    # TC-F2-4 (c)：escape_for_bash=True 时 $LOOP_OUTPUT 中含单引号也能正确 round-trip
    tricky = "stdout with 'inner' quote"
    quoted = substitute_vars(
        "$LOOP_OUTPUT",
        node_outputs=None,
        env={"LOOP_OUTPUT": tricky},
        escape_for_bash=True,
    )
    echoed = _bash_echo_roundtrip(quoted)
    assert echoed == tricky
