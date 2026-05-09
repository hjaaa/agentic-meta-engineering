"""workflow rollback 命令入口（F-005）。

/workflow:rollback <to-node>

状态校验 + 调用 rollback_run（F-010 落地前为占位 ImportError）。

详细设计 §1.2.8。
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError  # noqa: E402
from run_state import RunState, _resolve_run_dir, read_events  # noqa: E402
from workflow_state_validator import validate_state_for_cmd  # noqa: E402


def main(args: list[str], repo_root: Path | None = None) -> int:
    """rollback 命令主入口。

    参数：
        args      — [to_node]（必填）
        repo_root — 注入 repo 根路径（测试用）

    返回：exit code（0 成功，1 失败）
    """
    root = repo_root or REPO_ROOT

    if not args:
        print(
            "ERROR: /workflow:rollback 需要 <to-node> 参数",
            file=sys.stderr,
        )
        return 1

    to_node = args[0]

    # 推断 run_id
    run_id = _infer_run_id(root)
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
        validate_state_for_cmd("rollback", run_id, run_state.state)
    except WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # 调 rollback_run（F-010 落地前为占位）
    try:
        from workflow_rollback import rollback_run  # type: ignore  # noqa: F401
        rc = rollback_run(run_id, to_node, run_dir)
        return rc if isinstance(rc, int) else 0
    except ImportError:
        print(
            f"ERROR: rollback_run 未落地（待 F-010 实现 workflow_rollback.py）",
            file=sys.stderr,
        )
        print(
            f"状态校验已通过：run_id={run_id!r} state={run_state.state!r} to_node={to_node!r}",
            file=sys.stderr,
        )
        return 1


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
