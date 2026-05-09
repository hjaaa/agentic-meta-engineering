"""workflow continue 命令入口（F-005）。

/workflow:continue [<run-id>]

反扫 jsonl 重建 RunState，做状态校验，进 main loop stub（F-006 实现完整 loop）。

详细设计 §1.2.2。
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError, infer_run_id_from_branch  # noqa: E402
from run_state import RunState, _resolve_run_dir, append_event, read_events  # noqa: E402
from workflow_state_validator import validate_state_for_cmd  # noqa: E402


def _main_loop_stub(run_state: RunState) -> None:
    """main loop 占位（F-006 落地完整实现）。

    仅打印当前状态，不执行节点。
    """
    print(f"[main loop stub] run_id={run_state.run_id} state={run_state.state}")
    print(f"  current_node: {run_state.current_node or '(none)'}")
    completed = list(run_state.node_outputs.keys())
    print(f"  completed ({len(completed)}): {', '.join(completed) or '(none)'}")
    if run_state.pending_approval:
        print(f"  pending_approval: {run_state.pending_approval}")
    if run_state.warnings:
        for w in run_state.warnings:
            print(f"  WARN: {w}")
    print("  [F-006 待落地：节点执行 / main loop 完整实现]")


def main(args: list[str], repo_root: Path | None = None) -> int:
    """continue 命令主入口。

    参数：
        args      — [run_id?]（可选）
        repo_root — 注入 repo 根路径（测试用）

    返回：exit code（0 成功，1 失败）
    """
    root = repo_root or REPO_ROOT

    run_id = args[0] if args else None
    if not run_id:
        run_id = infer_run_id_from_branch(root)
    if not run_id:
        print(
            "ERROR: 无法推断 run_id\n"
            "请提供 run_id 或确保当前分支为 feat/req-<id> 格式",
            file=sys.stderr,
        )
        return 1

    # D-007 双路径解析
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
        validate_state_for_cmd("continue", run_id, run_state.state)
    except WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # 写 run_resumed 事件（详细设计 §1.2.2 + skill continue.md 步骤 5）
    # run_resumed 不映射 WORKFLOW_EVENT_TO_STATE，保持原 state 语义不变
    try:
        append_event(jsonl_path, {
            "type": "run_resumed",
            "run_id": run_id,
        })
    except WorkflowError as exc:
        print(f"WARN: 写 run_resumed 事件失败：{exc}", file=sys.stderr)
        # 不阻断续跑流程，仅 warn

    print(f"恢复 workflow run {run_id!r}（state={run_state.state}）")
    _main_loop_stub(run_state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
