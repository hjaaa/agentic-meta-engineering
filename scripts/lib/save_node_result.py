"""save_node_result.py — 写 outcome 事件的唯一入口（D-001 独立模块）。

CLI 形态：
    python3 scripts/lib/save_node_result.py \\
      --run <run_id> \\
      --node <node_id> \\
      --kind {skill_result|approval_repair} \\
      --output <json-string-or-@file> \\
      [--attempt <int>]   # approval_repair 时必填

退出码语义：
  0 — 写入成功
  1 — 业务错误（入参非法 / WorkflowError / attempt 缺失或不一致 / output 解析失败 / run_id 不存在）
  2 — fail-closed 拒绝（state ≠ awaiting_claude_action；或节点身份/末位事件不匹配）

三道 fail-closed 闸（详细设计 §3.1）：
  第 1 道：run_state.state != "awaiting_claude_action" → exit 2 E-NODE-RESULT-001
  第 2 道：RunState 字段 + jsonl 末位节点级事件双向交叉校验 → exit 2 E-NODE-RESULT-002/003/004
  第 3 道（仅 approval_repair）：attempt 缺失或不一致 → exit 1

错误码表（E-NODE-RESULT-NNN）：
  E-NODE-RESULT-001 — state != awaiting_claude_action（exit 2）
  E-NODE-RESULT-002 — RunState 字段 current_node/pending_approval 不匹配（exit 2）
  E-NODE-RESULT-003 — jsonl 末位节点级事件类型不匹配（exit 2）
  E-NODE-RESULT-004 — jsonl 末位节点级事件 node_id 不匹配（exit 2）
  E-NODE-RESULT-005 — --output 参数解析失败（JSON parse error 或文件读取失败）（exit 1）
  E-NODE-RESULT-006 — --output 解析结果不是 JSON object（exit 1）
  E-NODE-RESULT-007 — --attempt 参数缺失（approval_repair 必填）（exit 1）
  E-NODE-RESULT-008 — --attempt 值与 approval_repair_started.data.attempt 不一致（exit 1）
  E-NODE-RESULT-099 — 通用兜底（WorkflowError / 未预期异常）（exit 1）

ADR D-012：不与 save_review.py 共用 helper。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from append_events import append_events_with_manifest  # noqa: E402
from common import REPO_ROOT, WorkflowError  # noqa: E402
from run_state import RunState, _resolve_run_dir, read_events  # noqa: E402

# 节点级事件类型集合，用于末位节点级事件反扫
_NODE_LEVEL_EVENTS: frozenset[str] = frozenset({
    "node_ready",
    "approval_repair_started",
    "node_completed",
    "approval_repair_completed",
    "node_failed",
})

# kind → 期望的末位节点级事件类型
_KIND_EXPECTED_TAIL: dict[str, str] = {
    "skill_result": "node_ready",
    "approval_repair": "approval_repair_started",
    "loop_iteration": "node_ready",  # Bug-14：interactive loop 同样在 node_ready 后回写
}

# kind → 写入的目标事件类型
_KIND_WRITE_EVENT: dict[str, str] = {
    "skill_result": "node_completed",
    "approval_repair": "approval_repair_completed",
    "loop_iteration": "loop_iteration_completed",
}

# Bug-14：interactive loop iteration 合法 outcome 枚举
_VALID_LOOP_OUTCOMES: frozenset[str] = frozenset({"continue", "all_done"})


def _parse_output(output_raw: str) -> dict[str, Any]:
    """解析 --output 参数：裸 JSON 字符串或 @<file> 引用。

    Args:
        output_raw: CLI 传入的 --output 值（JSON 字符串或 "@文件路径"）。

    Returns:
        解析后的 dict。

    Raises:
        SystemExit(1): 解析失败时打印 stderr 并退出。
    """
    try:
        if output_raw.startswith("@"):
            file_path = Path(output_raw[1:])
            content = file_path.read_text(encoding="utf-8")
        else:
            content = output_raw
        result = json.loads(content)
    except Exception as exc:
        print(f"ERROR [E-NODE-RESULT-005]: output 解析失败: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(result, dict):
        print("ERROR [E-NODE-RESULT-006]: output 必须是 JSON object", file=sys.stderr)
        sys.exit(1)
    return result


def _find_tail_node_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """反扫 events，返回最后一条 type ∈ _NODE_LEVEL_EVENTS 的事件；无则返回 None。

    Args:
        events: 已解析的事件列表（按时间序）。

    Returns:
        最后一条节点级事件 dict，或 None。
    """
    for evt in reversed(events):
        if evt.get("type") in _NODE_LEVEL_EVENTS:
            return evt
    return None


def _check_state_or_fail(run_state: RunState) -> None:
    """第 1 道闸：state 必须 == 'awaiting_claude_action'。

    Args:
        run_state: rebuild 后的 RunState。

    Raises:
        SystemExit(2): state 不匹配时打印 stderr E-NODE-RESULT-001 并退出。
    """
    if run_state.state != "awaiting_claude_action":
        print(
            f"ERROR [E-NODE-RESULT-001]: state={run_state.state!r} != 'awaiting_claude_action'; "
            "拒绝写入 outcome 事件",
            file=sys.stderr,
        )
        sys.exit(2)


def _check_node_match_or_fail(
    run_state: RunState,
    node_id: str,
    kind: str,
    events: list[dict[str, Any]],
) -> None:
    """第 2 道闸：RunState 字段 + jsonl 末位节点级事件双向交叉校验。

    (2a) RunState 字段匹配：
      - skill_result   → run_state.current_node == node_id
      - approval_repair → run_state.pending_approval == node_id

    (2b) jsonl 末位节点级事件类型 + node_id 严格匹配：
      - kind=skill_result   期望末位 == node_ready，否则 E-NODE-RESULT-003
      - kind=approval_repair 期望末位 == approval_repair_started，否则 E-NODE-RESULT-003
      - 类型对了但 node_id 不匹配 → E-NODE-RESULT-004

    Args:
        run_state: rebuild 后的 RunState。
        node_id:   CLI 传入的 --node 值。
        kind:      CLI 传入的 --kind 值（skill_result / approval_repair）。
        events:    已解析的事件列表。

    Raises:
        SystemExit(2): 任一校验失败时打印 stderr 对应错误码并退出。
    """
    # (2a) RunState 字段匹配
    if kind in ("skill_result", "loop_iteration"):
        actual = run_state.current_node
        field_name = "current_node"
    else:
        actual = run_state.pending_approval
        field_name = "pending_approval"

    if actual != node_id:
        print(
            f"ERROR [E-NODE-RESULT-002]: {field_name} 不匹配；"
            f"expected={node_id!r}, actual={actual!r}",
            file=sys.stderr,
        )
        sys.exit(2)

    # (2b) jsonl 末位节点级事件校验
    tail_evt = _find_tail_node_event(events)
    expected_tail_type = _KIND_EXPECTED_TAIL[kind]
    actual_tail_type = tail_evt.get("type") if tail_evt else None

    if actual_tail_type != expected_tail_type:
        print(
            f"ERROR [E-NODE-RESULT-003]: 末位节点级事件类型不匹配；"
            f"expected={expected_tail_type!r}, actual={actual_tail_type!r}",
            file=sys.stderr,
        )
        sys.exit(2)

    tail_node_id = tail_evt.get("node_id") if tail_evt else None
    if tail_node_id != node_id:
        print(
            f"ERROR [E-NODE-RESULT-004]: 末位节点级事件 node_id 不匹配；"
            f"expected={node_id!r}, actual={tail_node_id!r}",
            file=sys.stderr,
        )
        sys.exit(2)


def _check_attempt_or_fail(
    attempt: int | None,
    events: list[dict[str, Any]],
    node_id: str,
) -> None:
    """第 3 道闸（仅 approval_repair）：attempt 存在性与值一致性校验。

    Args:
        attempt: CLI 传入的 --attempt 值（None 表示未传）。
        events:  已解析的事件列表。
        node_id: CLI 传入的 --node 值（用于定位最近 approval_repair_started）。

    Raises:
        SystemExit(1): attempt 缺失或不一致时打印 stderr 并退出。
    """
    if attempt is None:
        print(
            "ERROR [E-NODE-RESULT-007]: attempt required for --kind=approval_repair",
            file=sys.stderr,
        )
        sys.exit(1)

    # 找最近 approval_repair_started 的 attempt 值
    expected_attempt: int | None = None
    for evt in reversed(events):
        if evt.get("type") == "approval_repair_started" and evt.get("node_id") == node_id:
            expected_attempt = evt.get("data", {}).get("attempt")
            break

    if expected_attempt is not None and attempt != expected_attempt:
        print(
            f"ERROR [E-NODE-RESULT-008]: attempt mismatch: expected {expected_attempt}, got {attempt}",
            file=sys.stderr,
        )
        sys.exit(1)


def _handle_skill_result(
    run_state: RunState,
    node_id: str,
    output: dict[str, Any],
    events: list[dict[str, Any]],
    jsonl_path: Path,
    run_dir: Path,
) -> int:
    """处理 kind=skill_result：通过三道闸后写 node_completed 事件。

    Args:
        run_state:  rebuild 后的 RunState。
        node_id:    CLI 传入的 --node 值。
        output:     解析后的 output dict。
        events:     已解析的事件列表。
        jsonl_path: run-state.jsonl 路径。
        run_dir:    run 目录（manifest fallback 根）。

    Returns:
        退出码 0（成功）。
    """
    _check_state_or_fail(run_state)
    _check_node_match_or_fail(run_state, node_id, "skill_result", events)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    event: dict[str, Any] = {
        "type": "node_completed",
        "node_id": node_id,
        "ts": ts,
        "data": {"output": output},
    }
    append_events_with_manifest(
        jsonl_path,
        [event],
        large_field_paths=[("data", "output")],
        run_dir=run_dir,
    )
    return 0


def _handle_loop_iteration(
    run_state: RunState,
    node_id: str,
    output: dict[str, Any],
    events: list[dict[str, Any]],
    jsonl_path: Path,
    run_dir: Path,
) -> int:
    """处理 kind=loop_iteration（Bug-14）：通过三道闸后写 loop_iteration_completed。

    output 必含 "outcome" ∈ {"continue", "all_done"}：
    - continue：写 loop_iteration_completed{iteration, outcome:continue}
                  + loop_counter_advanced{new_value:iter+1}
    - all_done：写 loop_iteration_completed{iteration, outcome:all_done}
                  （终止动作由 dispatcher 下一轮派发时写 loop_completed + node_completed）

    iteration 从末位 node_ready 事件 data.loop_iteration 反扫得到（dispatcher 写入）。
    """
    _check_state_or_fail(run_state)
    _check_node_match_or_fail(run_state, node_id, "loop_iteration", events)

    outcome = output.get("outcome")
    if outcome not in _VALID_LOOP_OUTCOMES:
        print(
            f"ERROR [E-NODE-RESULT-006]: --kind=loop_iteration 的 output.outcome 必须是 "
            f"{sorted(_VALID_LOOP_OUTCOMES)} 之一，实际 {outcome!r}",
            file=sys.stderr,
        )
        return 1

    # 反扫最近 node_ready{node_id} 拿当前 loop_iteration
    iteration: int | None = None
    for evt in reversed(events):
        if evt.get("type") == "node_ready" and evt.get("node_id") == node_id:
            iteration = (evt.get("data") or {}).get("loop_iteration")
            break
    if not isinstance(iteration, int):
        print(
            f"ERROR [E-NODE-RESULT-099]: 末位 node_ready 缺 data.loop_iteration "
            f"(node_id={node_id!r})；无法确定当前迭代号",
            file=sys.stderr,
        )
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    completed_event: dict[str, Any] = {
        "type": "loop_iteration_completed",
        "node_id": node_id,
        "ts": ts,
        "data": {"iteration": iteration, "outcome": outcome, "output": output},
    }
    events_to_write: list[dict[str, Any]] = [completed_event]

    if outcome == "continue":
        events_to_write.append({
            "type": "loop_counter_advanced",
            "node_id": node_id,
            "ts": ts,
            "data": {"new_value": iteration + 1},
        })

    append_events_with_manifest(
        jsonl_path,
        events_to_write,
        large_field_paths=[("data", "output")],
        run_dir=run_dir,
    )
    return 0


def _handle_approval_repair(
    run_state: RunState,
    node_id: str,
    output: dict[str, Any],
    attempt: int | None,
    events: list[dict[str, Any]],
    jsonl_path: Path,
    run_dir: Path,
) -> int:
    """处理 kind=approval_repair：通过三道闸后写 approval_repair_completed 事件。

    Args:
        run_state:  rebuild 后的 RunState。
        node_id:    CLI 传入的 --node 值。
        output:     解析后的 output dict。
        attempt:    CLI 传入的 --attempt 值（None 表示未传）。
        events:     已解析的事件列表。
        jsonl_path: run-state.jsonl 路径。
        run_dir:    run 目录（manifest fallback 根）。

    Returns:
        退出码 0（成功）。
    """
    _check_state_or_fail(run_state)
    _check_attempt_or_fail(attempt, events, node_id)
    _check_node_match_or_fail(run_state, node_id, "approval_repair", events)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    event: dict[str, Any] = {
        "type": "approval_repair_completed",
        "node_id": node_id,
        "ts": ts,
        "data": {"attempt": attempt, "output": output},
    }
    append_events_with_manifest(
        jsonl_path,
        [event],
        large_field_paths=[("data", "output")],
        run_dir=run_dir,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """save_node_result CLI 主入口。

    Args:
        argv: 命令行参数列表（None 时使用 sys.argv[1:]）。

    Returns:
        退出码（0 / 1 / 2）。

    Raises:
        WorkflowError: 内部 workflow 错误（由顶层 except 捕获并返回 1）。
    """
    parser = argparse.ArgumentParser(
        description="写 outcome 事件到 run-state.jsonl（唯一入口）",
    )
    parser.add_argument("--run", required=True, help="run_id（REQ-xxx / RUN-xxx）")
    parser.add_argument("--node", required=True, help="node_id")
    parser.add_argument(
        "--kind",
        required=True,
        choices=["skill_result", "approval_repair", "loop_iteration"],
        help="outcome 类型（loop_iteration 用于 interactive loop 节点回写，Bug-14）",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="输出 JSON 字符串，或 @<file> 引用文件",
    )
    parser.add_argument(
        "--attempt",
        type=int,
        default=None,
        help="approval_repair 时必填：与 approval_repair_started 对齐的 attempt 编号",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="仓库根目录（测试注入用）",
    )

    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else REPO_ROOT

    try:
        run_dir = _resolve_run_dir(args.run, repo_root)
    except WorkflowError as exc:
        print(f"ERROR [E-NODE-RESULT-099]: {exc}", file=sys.stderr)
        return 1

    output = _parse_output(args.output)

    try:
        jsonl_path = run_dir / "run-state.jsonl"
        events, _warnings = read_events(jsonl_path)
        run_state = RunState.rebuild(events, run_id=args.run, warnings=_warnings)

        if args.kind == "skill_result":
            return _handle_skill_result(
                run_state, args.node, output, events, jsonl_path, run_dir
            )
        elif args.kind == "loop_iteration":
            return _handle_loop_iteration(
                run_state, args.node, output, events, jsonl_path, run_dir
            )
        else:
            return _handle_approval_repair(
                run_state, args.node, output, args.attempt, events, jsonl_path, run_dir
            )
    except WorkflowError as exc:
        print(f"ERROR [E-NODE-RESULT-099]: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR [E-NODE-RESULT-099]: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
