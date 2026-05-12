"""F-005 · workflow_dispatcher.py 单测——派发核心路径。

覆盖范围：
  TC-D1  DispatchOutcome：7 个枚举值齐全（Literal 不可在运行时枚举，改为语义检验）
  TC-D2  DispatchResult：4 字段默认值正确
  TC-D3  7 类节点 stub 派发——各类 1 个 case（含节点 dict 含对应键时正确路由）
  TC-D4  approval stub：写 approval_pending 事件 + substitute_vars 替换 prompt
  TC-D5  未知节点类型 → dispatch_node 写 node_failed + 返回 outcome="failed"
  TC-D6  dispatch_node 异常路径：stub 抛异常验证 except 兜底
  TC-D9  dispatch_node：进入时必写 node_started 事件

外部依赖（文件 IO）使用 tmp_path；无网络调用。
pytest 命名规范：test_<场景>_<期望>（CLAUDE.md §7）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------- 路径注入 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import RunState, read_events  # noqa: E402
from workflow_dispatcher import (  # noqa: E402
    DispatchResult,
    _dispatch_approval_node,
    dispatch_node,
)


# ============================================================================
# Fixture
# ============================================================================

@pytest.fixture()
def jsonl_path(tmp_path: Path) -> Path:
    """返回一个临时 jsonl 文件路径（父目录已存在）。"""
    return tmp_path / "run-state.jsonl"


@pytest.fixture()
def base_run_state() -> RunState:
    """最小化 RunState，run_id + arguments。"""
    return RunState(run_id="REQ-2026-010", arguments="test-arg")


# ============================================================================
# TC-D1 · DispatchOutcome 7 个枚举值可用
# ============================================================================

def test_dispatch_outcome_all_seven_values_are_valid():
    """DispatchOutcome 的 7 个合法字符串都能作为 DispatchResult.outcome 赋值，
    且赋值后不抛异常（Literal 是静态类型，运行时仅做值层面验证）。"""
    valid_outcomes = [
        "completed",
        "approval_pending",
        "failed",
        "loop_continue",
        "loop_done",
        "sub_workflow_pending",
        "sub_workflow_done",
    ]
    for outcome in valid_outcomes:
        result = DispatchResult(outcome=outcome)  # type: ignore[arg-type]
        assert result.outcome == outcome, f"outcome={outcome!r} 赋值后读取失败"


# ============================================================================
# TC-D2 · DispatchResult 4 字段默认值
# ============================================================================

def test_dispatch_result_default_fields():
    """DispatchResult 仅传 outcome 时，其余字段为 None。"""
    result = DispatchResult(outcome="completed")
    assert result.outcome == "completed"
    assert result.output is None
    assert result.error is None
    assert result.next_node_hint is None


def test_dispatch_result_all_fields():
    """DispatchResult 4 个字段均可独立赋值。"""
    result = DispatchResult(
        outcome="failed",
        output="some output",
        error="err msg",
        next_node_hint="next-node",
    )
    assert result.output == "some output"
    assert result.error == "err msg"
    assert result.next_node_hint == "next-node"


# ============================================================================
# TC-D3 · 7 类节点 stub 正确派发
# ============================================================================

def _node(type_key: str, **extra) -> dict:
    """快速构造含 id 和指定 type key 的 node dict。"""
    return {"id": f"test-{type_key}", type_key: {}, **extra}


def test_dispatch_node_agent_returns_completed(jsonl_path, base_run_state, tmp_path):
    """agent 键存在时，派发到 _dispatch_agent_node → outcome=completed。"""
    node = _node("agent")
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)
    assert result.outcome == "completed"


def test_dispatch_node_skill_returns_completed(jsonl_path, base_run_state, tmp_path):
    """skill 键存在（且有合法 skill 名）时，派发到 _dispatch_skill_node → outcome=completed。"""
    # 真实实现要求 node["skill"] 为非空字符串；空值会抛 WorkflowError → outcome=failed
    node = {"id": "test-skill", "skill": "my-skill"}
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)
    assert result.outcome == "completed"


def test_dispatch_node_prompt_returns_completed(jsonl_path, base_run_state, tmp_path):
    """prompt 键存在时，派发到 _dispatch_prompt_node → outcome=completed。"""
    node = _node("prompt")
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)
    assert result.outcome == "completed"


def test_dispatch_node_bash_returns_completed(jsonl_path, base_run_state, tmp_path):
    """bash 键存在时，派发到 _dispatch_bash_node → outcome=completed。"""
    node = _node("bash")
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)
    assert result.outcome == "completed"


def test_dispatch_node_loop_default_returns_loop_done(jsonl_path, base_run_state, tmp_path):
    """loop 键存在且 max_iterations 默认为 1 时，首次迭代后 outcome=loop_done（F-011）。

    `_node("loop")` 产出空 `loop: {}` dict，max_iterations 缺省视为 1；
    current_iteration=0 + 1 >= 1 触发 loop_done 分支（workflow_dispatcher.py:399）。
    """
    node = _node("loop")
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)
    assert result.outcome == "loop_done"


def test_dispatch_node_sub_workflow_missing_template_returns_failed(jsonl_path, base_run_state, tmp_path):
    """sub_workflow 键存在但缺 template 字段时，_dispatch_sub_workflow_node 抛 WorkflowError，
    被 dispatch_node 入口的 except 兜底为 outcome=failed（workflow_dispatcher.py:425）。
    """
    node = _node("sub_workflow")
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)
    assert result.outcome == "failed"


# ============================================================================
# TC-D4 · approval stub：写事件 + substitute_vars
# ============================================================================

def test_dispatch_node_approval_writes_event_and_substitutes_prompt(jsonl_path, base_run_state, tmp_path):
    """approval 节点 stub 必须：
    1. 对 approval.prompt 执行 substitute_vars 替换（含环境变量）
    2. 写 approval_pending 事件，data.prompt 等于替换后文本
    3. 返回 outcome="approval_pending"
    """
    node = {
        "id": "approve-1",
        "approval": {"prompt": "请审批 $RUN_ID"},
    }
    env = {"RUN_ID": "REQ-2026-010"}
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, env, jsonl_path)

    assert result.outcome == "approval_pending"

    # 读取 jsonl，找到 approval_pending 事件
    events, _ = read_events(jsonl_path)
    approval_events = [e for e in events if e.get("type") == "approval_pending"]
    assert len(approval_events) == 1, "期望恰好 1 条 approval_pending 事件"
    assert approval_events[0]["data"]["prompt"] == "请审批 REQ-2026-010"


def test_dispatch_approval_node_stub_writes_event_with_prompt(tmp_path):
    """直接调用 _dispatch_approval_node：$ENV_VAR 替换 + 事件写入。"""
    jsonl_path = tmp_path / "run-state.jsonl"
    node = {"id": "gate", "approval": {"prompt": "Approve $ARGUMENTS?"}}
    env = {"ARGUMENTS": "feature-x"}
    rs = RunState(run_id="REQ-TEST-001")
    result = _dispatch_approval_node(node, env, rs, jsonl_path)

    assert result.outcome == "approval_pending"
    events, _ = read_events(jsonl_path)
    ap = [e for e in events if e.get("type") == "approval_pending"]
    assert ap[0]["data"]["prompt"] == "Approve feature-x?"


def test_dispatch_approval_node_resolves_node_output_field(tmp_path):
    """TC-D4 扩展：$<nodeId>.output.field 通过 run_state.node_outputs 解析，不渲染为空串。

    这是 F-10 修复的核心场景：standard-8phase.yaml 中 approval prompt 引用上游节点输出字段，
    如 $req-quality-review.output.verdict；修复前传 None 导致引用全部解析为空字符串。
    """
    jsonl_path = tmp_path / "run-state.jsonl"
    rs = RunState(run_id="REQ-TEST-001")
    rs.node_outputs["upstream"] = {
        "output": '{"verdict": "approved"}',
        "state": "completed",
        "data": {},
    }
    node = {
        "id": "approve-gate",
        "approval": {"prompt": "verdict=$upstream.output.verdict"},
    }
    env: dict = {}
    result = _dispatch_approval_node(node, env, rs, jsonl_path)

    assert result.outcome == "approval_pending"
    events, _ = read_events(jsonl_path)
    ap = [e for e in events if e.get("type") == "approval_pending"]
    assert len(ap) == 1
    # 修复前为空串 "verdict="，修复后应解析为字段值
    assert ap[0]["data"]["prompt"] == "verdict=approved"


def test_dispatch_approval_node_env_and_node_output_combined(tmp_path):
    """TC-D4 扩展：同一 prompt 中同时包含 $ENV_VAR 和 $<nodeId>.output.field，两者均正确替换。"""
    jsonl_path = tmp_path / "run-state.jsonl"
    rs = RunState(run_id="REQ-TEST-002")
    rs.node_outputs["tech-assess"] = {
        "output": '{"feasibility": "yes"}',
        "state": "completed",
        "data": {},
    }
    node = {
        "id": "final-approve",
        "approval": {
            "prompt": "RUN=$RUN_ID feasibility=$tech-assess.output.feasibility"
        },
    }
    env = {"RUN_ID": "REQ-TEST-002"}
    result = _dispatch_approval_node(node, env, rs, jsonl_path)

    assert result.outcome == "approval_pending"
    events, _ = read_events(jsonl_path)
    ap = [e for e in events if e.get("type") == "approval_pending"]
    assert ap[0]["data"]["prompt"] == "RUN=REQ-TEST-002 feasibility=yes"


# ============================================================================
# TC-D5 · 未知节点类型 → node_failed + outcome=failed
# ============================================================================

def test_dispatch_node_unknown_type_returns_failed(jsonl_path, base_run_state, tmp_path):
    """node dict 没有任何已知 type key 时：
    - dispatch_node 写 node_failed 事件
    - 返回 DispatchResult(outcome="failed")
    """
    node = {"id": "mystery", "unknown_key": "value"}
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)

    assert result.outcome == "failed"
    assert result.error  # 应包含错误描述

    events, _ = read_events(jsonl_path)
    failed_events = [e for e in events if e.get("type") == "node_failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["node_id"] == "mystery"


# ============================================================================
# TC-D6 · dispatch_node 异常兜底
# ============================================================================

def test_dispatch_node_exception_in_stub_returns_failed(jsonl_path, base_run_state, tmp_path):
    """当 stub 内部抛出异常时，dispatch_node 捕获异常、写 node_failed 事件并返回 failed。"""
    node = {"id": "exploding", "agent": {}}

    def _exploding_stub(*_args, **_kwargs):
        raise RuntimeError("stub 爆炸了")

    with patch("workflow_dispatcher._dispatch_agent_node", side_effect=_exploding_stub):
        result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)

    assert result.outcome == "failed"
    assert "stub 爆炸了" in (result.error or "")

    events, _ = read_events(jsonl_path)
    failed_events = [e for e in events if e.get("type") == "node_failed"]
    assert len(failed_events) == 1
    assert "stub 爆炸了" in failed_events[0]["data"]["error"]


# ============================================================================
# TC-D9 · dispatch_node 进入时必写 node_started 事件
# ============================================================================

def test_dispatch_node_writes_node_started_before_dispatch(jsonl_path, base_run_state, tmp_path):
    """dispatch_node 调用时，无论节点类型，进入即写 node_started 事件。"""
    node = {"id": "check-start", "prompt": "hello"}
    dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)

    events, _ = read_events(jsonl_path)
    started_events = [e for e in events if e.get("type") == "node_started"]
    assert len(started_events) == 1
    assert started_events[0]["node_id"] == "check-start"


def test_dispatch_node_writes_node_started_even_on_unknown_type(jsonl_path, base_run_state, tmp_path):
    """即使未知节点类型，node_started 也必须先写入（然后 node_failed 跟随）。"""
    node = {"id": "mystery-2", "no_such_key": True}
    dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)

    events, _ = read_events(jsonl_path)
    types = [e.get("type") for e in events]
    # node_started 必须出现在 node_failed 之前
    assert "node_started" in types
    assert "node_failed" in types
    assert types.index("node_started") < types.index("node_failed")
