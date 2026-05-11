"""F-005 · workflow_dispatcher.py 单测。

覆盖范围：
  TC-D1  DispatchOutcome：7 个枚举值齐全（Literal 不可在运行时枚举，改为语义检验）
  TC-D2  DispatchResult：4 字段默认值正确
  TC-D3  7 类节点 stub 派发——各类 1 个 case（含节点 dict 含对应键时正确路由）
  TC-D4  approval stub：写 approval_pending 事件 + substitute_vars 替换 prompt
  TC-D5  未知节点类型 → dispatch_node 写 node_failed + 返回 outcome="failed"
  TC-D6  dispatch_node 异常路径：stub 抛异常验证 except 兜底
  TC-D7  _build_env：6 个基础变量 + 已完成节点 output 引用
  TC-D8  RunState.loop_counters：喂入 loop 事件，断言计数器值
  TC-D9  dispatch_node：进入时必写 node_started 事件

外部依赖（文件 IO）使用 tmp_path；无网络调用。
pytest 命名规范：test_<场景>_<期望>（CLAUDE.md §7）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------- 路径注入 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import RunState, read_events, append_event  # noqa: E402
from workflow_dispatcher import (  # noqa: E402
    DispatchResult,
    _build_env,
    _dispatch_agent_node,
    _dispatch_approval_node,
    _dispatch_bash_node,
    _dispatch_loop_node,
    _dispatch_prompt_node,
    _dispatch_skill_node,
    _dispatch_sub_workflow_node,
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


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    """模拟 requirements/<id>/ 目录（空目录即可）。"""
    d = tmp_path / "requirements" / "REQ-2026-010"
    d.mkdir(parents=True)
    return d


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
    """skill 键存在时，派发到 _dispatch_skill_node → outcome=completed。"""
    node = _node("skill")
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


def test_dispatch_node_loop_returns_completed(jsonl_path, base_run_state, tmp_path):
    """loop 键存在时，派发到 _dispatch_loop_node → outcome=completed。"""
    node = _node("loop")
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)
    assert result.outcome == "completed"


def test_dispatch_node_sub_workflow_returns_completed(jsonl_path, base_run_state, tmp_path):
    """sub_workflow 键存在时，派发到 _dispatch_sub_workflow_node → outcome=completed。"""
    node = _node("sub_workflow")
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)
    assert result.outcome == "completed"


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
# TC-D7 · _build_env：6 个基础变量 + completed 节点 output 引用
# ============================================================================

def test_build_env_six_base_variables(run_dir, tmp_path):
    """_build_env 返回 dict 中包含 6 个基础变量，值与 RunState 对应。"""
    rs = RunState(run_id="REQ-2026-010", arguments="hello world")
    env = _build_env(rs, run_dir, tmp_path)

    assert env["RUN_ID"] == "REQ-2026-010"
    assert env["RUN_DIR"] == str(run_dir)
    assert env["META_PATH"] == str(run_dir / "meta.yaml")
    assert env["ARTIFACTS_DIR"] == str(run_dir / "artifacts")
    assert env["ARGUMENTS"] == "hello world"
    assert env["BRANCH_NAME"] == "feat/req-2026-010"


def test_build_env_branch_name_derivation(run_dir, tmp_path):
    """BRANCH_NAME 由 run_id 去 REQ- 前缀转小写得到。"""
    rs = RunState(run_id="REQ-2099-001")
    env = _build_env(rs, run_dir, tmp_path)
    assert env["BRANCH_NAME"] == "feat/req-2099-001"


def test_build_env_arguments_none_defaults_to_empty(run_dir, tmp_path):
    """arguments 为 None 时，ARGUMENTS 环境变量应为空字符串而非 "None"。"""
    rs = RunState(run_id="REQ-2026-010", arguments=None)
    env = _build_env(rs, run_dir, tmp_path)
    assert env["ARGUMENTS"] == ""


def test_build_env_node_outputs_injected(run_dir, tmp_path):
    """已完成节点的 output 以 '<nodeId>.output' 格式注入 env。"""
    rs = RunState(run_id="REQ-2026-010")
    rs.node_outputs["init-req"] = {
        "output": "some output text",
        "state": "completed",
        "data": {},
    }
    rs.node_outputs["plan-task"] = {
        "output": "",
        "state": "completed",
        "data": {},
    }

    env = _build_env(rs, run_dir, tmp_path)
    assert env["init-req.output"] == "some output text"
    assert env["plan-task.output"] == ""


def test_build_env_node_output_non_string_serialized_as_json(run_dir, tmp_path):
    """节点 output 为非字符串时（如 dict/list），应 JSON 序列化后注入。"""
    rs = RunState(run_id="REQ-2026-010")
    rs.node_outputs["data-node"] = {
        "output": {"key": "value"},
        "state": "completed",
        "data": {},
    }

    env = _build_env(rs, run_dir, tmp_path)
    assert env["data-node.output"] == json.dumps({"key": "value"}, ensure_ascii=False)


# ============================================================================
# TC-D8 · RunState.loop_counters 反扫重建
# ============================================================================

def test_run_state_loop_counters_default_empty():
    """RunState 初始化时 loop_counters 应为空 dict。"""
    rs = RunState()
    assert rs.loop_counters == {}


def test_rebuild_loop_counters_from_started_event():
    """喂入 loop_iteration_started 事件后，loop_counters 更新为对应迭代编号。"""
    events = [
        {
            "type": "workflow_started",
            "run_id": "REQ-2026-010",
            "data": {"workflow_name": "test"},
        },
        {
            "type": "loop_iteration_started",
            "node_id": "loop-node",
            "ts": "2026-01-01T00:00:00Z",
            "data": {"iteration": 1},
        },
    ]
    rs = RunState.rebuild(events, run_id="REQ-2026-010")
    assert rs.loop_counters["loop-node"] == 1


def test_rebuild_loop_counters_updated_on_completed_event():
    """loop_iteration_completed 事件同样更新 loop_counters。"""
    events = [
        {"type": "workflow_started", "run_id": "REQ-2026-010", "data": {"workflow_name": "t"}},
        {
            "type": "loop_iteration_started",
            "node_id": "loop-a",
            "ts": "2026-01-01T00:00:00Z",
            "data": {"iteration": 1},
        },
        {
            "type": "loop_iteration_completed",
            "node_id": "loop-a",
            "ts": "2026-01-01T00:01:00Z",
            "data": {"iteration": 1},
        },
    ]
    rs = RunState.rebuild(events, run_id="REQ-2026-010")
    assert rs.loop_counters["loop-a"] == 1


def test_rebuild_loop_counters_multiple_iterations():
    """多次迭代时，loop_counters 更新为最新的 iteration 编号。"""
    events = [
        {"type": "workflow_started", "run_id": "REQ-2026-010", "data": {"workflow_name": "t"}},
        {
            "type": "loop_iteration_started",
            "node_id": "loop-x",
            "ts": "2026-01-01T00:00:00Z",
            "data": {"iteration": 1},
        },
        {
            "type": "loop_iteration_completed",
            "node_id": "loop-x",
            "ts": "2026-01-01T00:01:00Z",
            "data": {"iteration": 1},
        },
        {
            "type": "loop_iteration_started",
            "node_id": "loop-x",
            "ts": "2026-01-01T00:02:00Z",
            "data": {"iteration": 2},
        },
        {
            "type": "loop_iteration_completed",
            "node_id": "loop-x",
            "ts": "2026-01-01T00:03:00Z",
            "data": {"iteration": 2},
        },
        {
            "type": "loop_iteration_started",
            "node_id": "loop-x",
            "ts": "2026-01-01T00:04:00Z",
            "data": {"iteration": 3},
        },
    ]
    rs = RunState.rebuild(events, run_id="REQ-2026-010")
    assert rs.loop_counters["loop-x"] == 3


def test_rebuild_loop_counters_multiple_loop_nodes():
    """不同 loop 节点的计数器相互独立。"""
    events = [
        {"type": "workflow_started", "run_id": "REQ-2026-010", "data": {"workflow_name": "t"}},
        {
            "type": "loop_iteration_started",
            "node_id": "loop-a",
            "ts": "2026-01-01T00:00:00Z",
            "data": {"iteration": 2},
        },
        {
            "type": "loop_iteration_started",
            "node_id": "loop-b",
            "ts": "2026-01-01T00:01:00Z",
            "data": {"iteration": 5},
        },
    ]
    rs = RunState.rebuild(events, run_id="REQ-2026-010")
    assert rs.loop_counters["loop-a"] == 2
    assert rs.loop_counters["loop-b"] == 5


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
