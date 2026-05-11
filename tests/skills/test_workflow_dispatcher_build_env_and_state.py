"""F-005 · workflow_dispatcher.py 单测——_build_env + RunState.loop_counters。

覆盖范围：
  TC-D7  _build_env：6 个基础变量 + 已完成节点 output 引用
  TC-D8  RunState.loop_counters：喂入 loop 事件，断言计数器值

外部依赖（文件 IO）使用 tmp_path；无网络调用。
pytest 命名规范：test_<场景>_<期望>（CLAUDE.md §7）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ---------- 路径注入 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import RunState  # noqa: E402
from workflow_dispatcher import _build_env  # noqa: E402


# ============================================================================
# Fixture
# ============================================================================

@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    """模拟 requirements/<id>/ 目录（空目录即可）。"""
    d = tmp_path / "requirements" / "REQ-2026-010"
    d.mkdir(parents=True)
    return d


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
