"""workflow cancel 命令入口（F-005）。

/workflow:cancel

父 jsonl 写 cancel_requested 事件 + 30s 超时 TaskStop 兜底（D-005）。

详细设计 §1.2.9。
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError, infer_run_id_from_branch  # noqa: E402
from run_state import RunState, _resolve_run_dir, append_event, read_events  # noqa: E402
from workflow_state_validator import validate_state_for_cmd  # noqa: E402

_GRACEFUL_TIMEOUT_SECS = 30


def _handle_taskstop_failure(exc: Exception, jsonl_path: Path, run_id: str) -> None:
    """TaskStop 调用失败的降级处理：WARN + 写 cancel_taskstop_failed 审计事件。

    独立抽取以降低 main 的嵌套深度（G-5）。
    G-10：cancel_taskstop_failed 写失败时输出 stderr WARN，不再静默吞异常。
    """
    print(f"WARN: TaskStop 调用失败：{exc}", file=sys.stderr)
    # 写降级审计事件（不 exit 1；cancel 主流程已写 cancel_requested，命令整体成功）
    try:
        append_event(jsonl_path, {
            "type": "cancel_taskstop_failed",
            "run_id": run_id,
            "data": {"error": str(exc)},
        })
    except WorkflowError as exc2:
        # G-10：写降级事件也失败时，至少输出 WARN 到 stderr，不再静默 pass
        print(f"WARN: 写 cancel_taskstop_failed 事件也失败：{exc2}", file=sys.stderr)


def _task_stop_forceful(run_id: str) -> None:
    """TaskStop forceful 兜底（F-009 落地前为 stub）。

    F-009 实现时替换此函数为真实 Anthropic SDK TaskStop 调用。
    """
    # stub：抛 NotImplementedError 模拟 F-009 未落地
    raise NotImplementedError(f"TaskStop 未落地（待 F-009 实现）；run_id={run_id!r}")


def _wait_for_graceful_exit(run_dir: Path, timeout_secs: float) -> bool:
    """轮询等待 workflow_cancelled 事件（graceful 退出标志）。

    返回 True = graceful 成功，False = 超时。
    """
    deadline = time.monotonic() + timeout_secs
    jsonl_path = run_dir / "run-state.jsonl"
    while time.monotonic() < deadline:
        events, _ = read_events(jsonl_path)
        state = RunState.rebuild(events).state
        if state in ("cancelled", "completed", "failed"):
            return True
        time.sleep(1)
    return False


def main(args: list[str], repo_root: Path | None = None, _skip_wait: bool = False) -> int:
    """cancel 命令主入口。

    参数：
        args        — []（cancel 无参数）
        repo_root   — 注入 repo 根路径（测试用）
        _skip_wait  — 跳过 graceful 等待（测试用）

    返回：exit code（0 成功，1 状态错）
    """
    root = repo_root or REPO_ROOT

    # 推断 run_id
    run_id = infer_run_id_from_branch(root)
    if not run_id:
        print("ERROR: 无法推断 run_id", file=sys.stderr)
        return 1

    try:
        run_dir = _resolve_run_dir(run_id, root)
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    jsonl_path = run_dir / "run-state.jsonl"
    events, warnings = read_events(jsonl_path)
    run_state = RunState.rebuild(events, run_id=run_id, warnings=warnings)

    # 状态矩阵校验
    try:
        validate_state_for_cmd("cancel", run_id, run_state.state)
    except WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # 写 cancel_requested 事件
    try:
        append_event(jsonl_path, {
            "type": "cancel_requested",
            "run_id": run_id,
        })
    except WorkflowError as exc:
        print(f"ERROR: 写 cancel_requested 事件失败：{exc}", file=sys.stderr)
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"Cancel requested at {ts}; awaiting graceful exit (≤ {_GRACEFUL_TIMEOUT_SECS}s)")

    if not _skip_wait:
        graceful = _wait_for_graceful_exit(run_dir, _GRACEFUL_TIMEOUT_SECS)
    else:
        graceful = False  # 测试模式：跳过等待，直接走 TaskStop 路径

    if not graceful:
        # 30s 超时 → TaskStop forceful 兜底
        try:
            _task_stop_forceful(run_id)
        except Exception as exc:
            # cancel_taskstop_failed 专用事件（不映射 WORKFLOW_EVENT_TO_STATE，
            # 保持 cancel_requested 语义，state 不变为 failed）
            _handle_taskstop_failure(exc, jsonl_path, run_id)

    print(f"  run_id: {run_id}，cancel 信号已发送")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:] if len(sys.argv) > 1 else []))
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
