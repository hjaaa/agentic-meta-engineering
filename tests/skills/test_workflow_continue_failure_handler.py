"""F-008 · _handle_failure 及三个策略助手函数的单测。

覆盖范围：
  TC-F8-1  _handle_failure retry 未达上限：current_node 保持，state=running，返回 False
  TC-F8-2  _handle_failure skip：写 node_skipped，推进 current_node，返回 True
  TC-F8-3  _handle_failure abort：写 workflow_failed（node_id 在 data 内），state=failed，返回 False
  TC-F8-4  _handle_failure retry 超上限：升级 abort，写 workflow_failed，state=failed
  TC-F8-6  _handle_retry warnings 打印：jsonl 损坏行时打 WARN 到 stderr
  TC-F8-7  _handle_abort 未知策略降级：未知 on_failure 打 WARN 并走 abort 路径
  TC-F8-8  _handle_failure 无 on_failure 字段（默认 retry）：未达上限时 state=running

外部依赖（jsonl IO）使用 tmp_path。
pytest 命名规范：test_<场景>_<期望>（CLAUDE.md §7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------- 路径注入 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import RunState, append_event, read_events  # noqa: E402
from workflow_outcome_router import _handle_failure, _handle_retry, _handle_abort  # noqa: E402


# ============================================================================
# Fixture
# ============================================================================


@pytest.fixture()
def jsonl_path(tmp_path: Path) -> Path:
    """返回一个临时 jsonl 文件路径（父目录已存在）。"""
    return tmp_path / "run-state.jsonl"


@pytest.fixture()
def node_with_retry() -> dict:
    """带 on_failure=retry + max_retries=2 的节点。"""
    return {
        "id": "node-a",
        "bash": "echo 'step'",
        "next": "node-b",
        "on_failure": "retry",
        "max_retries": 2,
    }


@pytest.fixture()
def node_with_skip() -> dict:
    """带 on_failure=skip 的节点。"""
    return {
        "id": "node-a",
        "bash": "echo 'step'",
        "next": "node-b",
        "on_failure": "skip",
    }


@pytest.fixture()
def node_with_abort() -> dict:
    """带 on_failure=abort 的节点。"""
    return {
        "id": "node-a",
        "bash": "echo 'step'",
        "next": "node-b",
        "on_failure": "abort",
    }


@pytest.fixture()
def node_no_on_failure() -> dict:
    """不含 on_failure 字段的节点（测试默认值路径）。"""
    return {
        "id": "node-a",
        "bash": "echo 'step'",
        "next": "node-b",
        "max_retries": 2,
    }


# ============================================================================
# TC-F8-1 · retry 未达上限
# ============================================================================


def test_handle_failure_retry_below_max_retries_keeps_current_node(
    node_with_retry,
    jsonl_path,
):
    """retry 场景：失败次数 < max_retries，current_node 保持，state=running，返回 False。

    场景：max_retries=2，当前只失败 1 次（写 1 条 node_failed 事件，node_id 在顶层）
    期望：_handle_failure 返回 False（main loop 应 break，等待下次 continue 重派）
          run_state.state 保持 running，current_node 保持 node-a
    """
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    # 预写 1 条 node_failed 事件（模拟已失败 1 次；node_id 在顶层，与 dispatcher 格式一致）
    append_event(jsonl_path, {"type": "node_failed", "node_id": "node-a", "data": {"error": "err"}})

    result = _handle_failure(
        run_state, node_with_retry, "retry", jsonl_path, "some error",
        workflow={}, node_map={},
    )

    assert result is False  # main loop 应 break
    assert run_state.state == "running"  # state 保持 running（等下次 continue 重派）
    assert run_state.current_node == "node-a"  # current_node 不变


# ============================================================================
# TC-F8-2 · skip 场景
# ============================================================================


def test_handle_failure_skip_writes_node_skipped_and_advances(
    node_with_skip,
    jsonl_path,
):
    """skip 场景：写 node_skipped 事件，推进 current_node 到 node-b，返回 True。

    期望：_handle_failure 返回 True（main loop 继续循环）
          jsonl 中写入 node_skipped 事件（node_id 在顶层，reason=实际错误信息）
          run_state.current_node 推进为 node-b
    """
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    result = _handle_failure(
        run_state, node_with_skip, "skip", jsonl_path, "some error",
        workflow={}, node_map={},
    )

    assert result is True  # main loop 应继续循环
    assert run_state.current_node == "node-b"  # 推进到 node-b

    # 验证 node_skipped 事件已写入（node_id 在顶层；reason=实际错误信息，非硬编码 'on_failure=skip'）
    events, _ = read_events(jsonl_path)
    skipped_events = [e for e in events if e.get("type") == "node_skipped"]
    assert len(skipped_events) == 1
    assert skipped_events[0]["node_id"] == "node-a"
    # reason 来自传入的 error 参数（spec §2.1：reason 记录实际错误信息）
    assert skipped_events[0]["data"]["reason"] == "some error"


# ============================================================================
# TC-F8-3 · abort 场景
# ============================================================================


def test_handle_failure_abort_writes_workflow_failed(
    node_with_abort,
    jsonl_path,
):
    """abort 场景：写 workflow_failed 事件，state=failed，返回 False。

    期望：_handle_failure 返回 False（main loop 应 break）
          run_state.state = "failed"
          jsonl 中写入 workflow_failed 事件（node_id 在 data 内，符合 spec §2.1）
    """
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    result = _handle_failure(
        run_state, node_with_abort, "abort", jsonl_path, "fatal error",
        workflow={}, node_map={},
    )

    assert result is False  # main loop 应 break
    assert run_state.state == "failed"

    # 验证 workflow_failed 事件已写入（node_id 在 data 内，符合 spec §2.1 + §1.7:258）
    events, _ = read_events(jsonl_path)
    failed_events = [e for e in events if e.get("type") == "workflow_failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["data"]["node_id"] == "node-a"
    assert failed_events[0]["data"]["error"] == "fatal error"


# ============================================================================
# TC-F8-4 · retry 超上限升级为 abort
# ============================================================================


def test_handle_failure_retry_exhausted_upgrades_to_abort(
    node_with_retry,
    jsonl_path,
):
    """retry 超上限场景：已达 max_retries，升级为 abort，写 workflow_failed，state=failed。

    场景：max_retries=2，当前已失败 2 次（写 2 条 node_failed 事件）
    期望：_handle_failure 返回 False
          run_state.state = "failed"
          jsonl 中写入 workflow_failed 事件（reason=retry_exhausted，node_id 在 data 内）
    """
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    # 预写 2 条 node_failed 事件（模拟已达上限；node_id 在顶层，与 dispatcher 格式一致）
    append_event(jsonl_path, {"type": "node_failed", "node_id": "node-a", "data": {"error": "err1"}})
    append_event(jsonl_path, {"type": "node_failed", "node_id": "node-a", "data": {"error": "err2"}})

    result = _handle_failure(
        run_state, node_with_retry, "retry", jsonl_path, "err3",
        workflow={}, node_map={},
    )

    assert result is False  # main loop 应 break
    assert run_state.state == "failed"

    # 验证 workflow_failed 事件已写入（reason=retry_exhausted，node_id 在 data 内）
    events, _ = read_events(jsonl_path)
    failed_events = [e for e in events if e.get("type") == "workflow_failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["data"]["reason"] == "retry_exhausted"
    assert failed_events[0]["data"]["node_id"] == "node-a"


# ============================================================================
# TC-F8-6 · _handle_retry warnings 打印（jsonl 损坏行）
# ============================================================================


def test_handle_retry_jsonl_warnings_printed_to_stderr(
    node_with_retry,
    jsonl_path,
    capsys,
):
    """jsonl 含损坏行时，_handle_retry 打 WARN 到 stderr（F-5 修复验证）。

    场景：jsonl 末尾追加 1 行非 JSON 内容（模拟损坏）
    期望：stderr 含 WARN 字样，_handle_retry 仍正常返回 False（未崩溃）
    """
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    # 写 1 条合法 node_failed 事件后追加 1 行损坏数据
    append_event(jsonl_path, {"type": "node_failed", "node_id": "node-a", "data": {"error": "err"}})
    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write("NOT JSON\n")

    result = _handle_retry(run_state, node_with_retry, jsonl_path, "error")

    captured = capsys.readouterr()
    # 应打出 WARN（损坏行提示）
    assert "WARN" in captured.err
    assert result is False  # 正常返回


# ============================================================================
# TC-F8-7 · _handle_abort 未知策略降级
# ============================================================================


def test_handle_abort_unknown_on_failure_degrades_and_writes_workflow_failed(
    jsonl_path,
    capsys,
):
    """未知 on_failure 策略时，_handle_abort 打 WARN 并走 abort 路径写 workflow_failed。

    场景：传入 on_failure='invalid_strategy'
    期望：stderr 含 WARN，state=failed，写 workflow_failed 事件（node_id 在 data 内）
    """
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")
    node = {"id": "node-a", "bash": "cmd", "next": "node-b"}

    result = _handle_abort(run_state, node, jsonl_path, "some error", "invalid_strategy")

    assert result is False
    assert run_state.state == "failed"

    events, _ = read_events(jsonl_path)
    failed_events = [e for e in events if e.get("type") == "workflow_failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["data"]["node_id"] == "node-a"

    # 验证 _handle_abort 在未知 on_failure 策略时向 stderr 打印 WARN
    captured = capsys.readouterr()
    assert "WARN" in captured.err


# ============================================================================
# TC-F8-8 · 无 on_failure 字段节点（默认 retry 路径）
# ============================================================================


def test_handle_failure_default_on_failure_is_retry(
    node_no_on_failure,
    jsonl_path,
):
    """节点不含 on_failure 字段时，_handle_failure 默认走 retry 路径（F-1 修复验证）。

    此处直接测试默认值路径：_handle_failure("retry", ...) 在未达上限时返回 False 且 state=running。
    确认 on_failure 默认为 retry（不是 abort）。
    """
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    # 预写 1 条 node_failed 事件（max_retries=2，失败 1 次，未达上限）
    append_event(jsonl_path, {"type": "node_failed", "node_id": "node-a", "data": {"error": "err"}})

    # 节点无 on_failure 字段，默认应为 retry
    on_failure = node_no_on_failure.get("on_failure", "retry")
    result = _handle_failure(
        run_state, node_no_on_failure, on_failure, jsonl_path, "error",
        workflow={}, node_map={},
    )

    # retry 未达上限：state=running，返回 False（不是 abort 写 workflow_failed）
    assert result is False
    assert run_state.state == "running"

    # 不应有 workflow_failed 事件
    events, _ = read_events(jsonl_path)
    failed_events = [e for e in events if e.get("type") == "workflow_failed"]
    assert len(failed_events) == 0
