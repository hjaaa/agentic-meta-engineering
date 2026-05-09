"""workflow reject 命令入口（F-005）。

/workflow:reject <reason>

人类专属动作：isatty 兜底 + hook 拦截（D-006）。reason 最短 8 字符。

详细设计 §1.2.7。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError, infer_run_id_from_branch  # noqa: E402
from run_state import RunState, _resolve_run_dir, append_event, read_events  # noqa: E402
from workflow_state_validator import check_tty_for_approval, validate_state_for_cmd  # noqa: E402

_REASON_MIN_LEN = 8
_REASON_MAX_LEN = 200  # 与 workflow_save.py _NOTE_MAX_LEN=200 对称


def main(args: list[str], repo_root: Path | None = None) -> int:
    """reject 命令主入口。

    参数：
        args      — [reason tokens...]（必填，≥ 8 字符）
        repo_root — 注入 repo 根路径（测试用）

    返回：exit code（0 成功，1 业务错误，2 非 tty）
    """
    root = repo_root or REPO_ROOT

    # 第一道：isatty 兜底校验（fail-closed）
    check_tty_for_approval("reject")

    if not args:
        print(
            f"ERROR: /workflow:reject 需要 <reason> 参数（最短 {_REASON_MIN_LEN} 字符）",
            file=sys.stderr,
        )
        return 1

    reason = (" ".join(args).strip())[:_REASON_MAX_LEN]
    if len(reason) < _REASON_MIN_LEN:
        print(
            f"ERROR: reason 太短（{len(reason)} 字符），最短 {_REASON_MIN_LEN} 字符",
            file=sys.stderr,
        )
        return 1

    # 推断 run_id
    run_id = infer_run_id_from_branch(root)
    if not run_id:
        print("ERROR: 无法推断 run_id；请切到 feat/req-<id> 分支", file=sys.stderr)
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
        validate_state_for_cmd("reject", run_id, run_state.state)
    except WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    node_id = run_state.pending_approval or "unknown_node"

    try:
        append_event(jsonl_path, {
            "type": "approval_rejected",
            "run_id": run_id,
            "node_id": node_id,
            "data": {"reason": reason},
        })
    except WorkflowError as exc:
        print(f"ERROR: 写 approval_rejected 事件失败：{exc}", file=sys.stderr)
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"Rejected {node_id!r} at {ts}: {reason}")
    print(f"  run_id: {run_id}")
    print(f"  on_reject 路径由 main loop（F-006）处理")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
