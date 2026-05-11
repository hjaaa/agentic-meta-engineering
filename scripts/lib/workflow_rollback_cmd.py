"""workflow rollback 命令入口（F-005）。

/workflow:rollback <to-node>

状态校验 + 调用 rollback_run（F-010 落地前为占位 ImportError）。

详细设计 §1.2.8。

注：本文件名使用 _cmd 后缀，是为了避免与 F-010 落地的 workflow_rollback.py
（workflow_rollback 模块本体）同名冲突。F-005 只负责命令入口层，
实际 rollback 逻辑由 F-010 的 workflow_rollback.py 提供。
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError, infer_run_id_from_branch  # noqa: E402
from run_state import RunState, _resolve_run_dir, read_events  # noqa: E402
from workflow_state_validator import validate_state_for_cmd  # noqa: E402

# rollback_run 公开 API 签名（workflow_rollback.py:402）：
#   rollback_run(run_id, to_node, target_id=None, repo_root=None)
# 历史 bug：早期版本把 run_dir 当 target_id 传，进入正则校验时 TypeError。
# 这里命令层只需 (run_id, to_node, repo_root=root)；target_id 缺省由
# rollback_run 内部按规则自动级联子 run。


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
        validate_state_for_cmd("rollback", run_id, run_state.state)
    except WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # 调 rollback_run（公开 API 签名：run_id, to_node, target_id=None, repo_root=None）
    try:
        from workflow_rollback import rollback_run  # type: ignore
        rc = rollback_run(run_id, to_node, repo_root=root)
        return rc if isinstance(rc, int) else 0
    except ImportError:
        # 功能未实现（F-010 待落地）：exit 1 与状态拒绝同档，
        # 但语义不同——这里是"功能未实现"而非"状态不满足"
        print(
            "ERROR: rollback 功能未实现（待 F-010 实现 workflow_rollback.py）",
            file=sys.stderr,
        )
        print(
            f"状态校验已通过，功能占位中：run_id={run_id!r} state={run_state.state!r} to_node={to_node!r}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:] if len(sys.argv) > 1 else []))
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
