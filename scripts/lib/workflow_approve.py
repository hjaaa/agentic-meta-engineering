"""workflow approve 命令入口（F-005）。

/workflow:approve

人类专属动作：isatty 兜底 + hook 拦截（D-006）。

详细设计 §1.2.6。
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError  # noqa: E402
from run_state import RunState, _resolve_run_dir, append_event, read_events  # noqa: E402
from workflow_state_validator import check_tty_for_approval, validate_state_for_cmd  # noqa: E402


def main(args: list[str], repo_root: Path | None = None) -> int:
    """approve 命令主入口。

    参数：
        args      — []（approve 无参数）
        repo_root — 注入 repo 根路径（测试用）

    返回：exit code（0 成功，1 状态错，2 非 tty）
    """
    root = repo_root or REPO_ROOT

    # 第一道：isatty 兜底校验（fail-closed）
    # check_tty_for_approval 在非 tty 时调 sys.exit(2)
    check_tty_for_approval("approve")

    # 推断 run_id
    run_id = _infer_run_id(root)
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
        validate_state_for_cmd("approve", run_id, run_state.state)
    except WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    node_id = run_state.pending_approval or "unknown_node"

    try:
        append_event(jsonl_path, {
            "type": "approval_approved",
            "run_id": run_id,
            "node_id": node_id,
        })
    except WorkflowError as exc:
        print(f"ERROR: 写 approval_approved 事件失败：{exc}", file=sys.stderr)
        return 1

    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"Approved {node_id!r} at {ts}")
    print(f"  run_id: {run_id}")
    print(f"  状态机：approval_pending → running")
    return 0


def _infer_run_id(repo_root: Path) -> str | None:
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=str(repo_root), timeout=5,
        )
        branch = result.stdout.strip()
        if branch.startswith("feat/req-"):
            return branch[len("feat/req-"):]
    except Exception:
        pass
    return None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
