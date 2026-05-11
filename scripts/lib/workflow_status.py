"""workflow status 命令入口（F-005）。

/workflow:status [<run-id>]

只读展示父子树（spec §6.4）。不写 jsonl，不改 meta。

详细设计 §1.2.4。
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError, infer_run_id_from_branch  # noqa: E402
from run_state import RunState, _resolve_run_dir, read_events  # noqa: E402


def _render_status(run_state: RunState, run_dir: Path, indent: int = 0) -> str:
    """格式化 run status，含子 run 嵌套缩进（spec §6.4）。"""
    prefix = "  " * indent
    lines = [
        f"{prefix}run_id:       {run_state.run_id}",
        f"{prefix}state:        {run_state.state}",
        f"{prefix}current_node: {run_state.current_node or '(none)'}",
    ]
    completed = list(run_state.node_outputs.keys())
    lines.append(f"{prefix}completed ({len(completed)}): {', '.join(completed) or '(none)'}")

    if run_state.pending_approval:
        lines.append(f"{prefix}pending_approval: {run_state.pending_approval}")

    if run_state.warnings:
        lines.append(f"{prefix}warnings:")
        for w in run_state.warnings:
            lines.append(f"{prefix}  WARN: {w}")

    # 递归子 run（扫 run_dir/nodes/*/run_id）
    nodes_dir = run_dir / "nodes"
    if nodes_dir.is_dir():
        for node_dir in sorted(nodes_dir.iterdir()):
            sub_run_id_file = node_dir / "run_id"
            if sub_run_id_file.is_file():
                sub_run_id = sub_run_id_file.read_text().strip()
                try:
                    sub_dir = _resolve_run_dir(sub_run_id, run_dir.parent.parent)
                    sub_jsonl = sub_dir / "run-state.jsonl"
                    sub_events, sub_warnings = read_events(sub_jsonl)
                    sub_state = RunState.rebuild(sub_events, run_id=sub_run_id, warnings=sub_warnings)
                    lines.append(f"{prefix}  └─ 子 run:")
                    lines.append(_render_status(sub_state, sub_dir, indent + 2))
                except WorkflowError as exc:
                    lines.append(f"{prefix}  └─ 子 run {sub_run_id!r} 解析失败: {exc}")

    return "\n".join(lines)


def main(args: list[str], repo_root: Path | None = None) -> int:
    """status 命令主入口。

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
        # 列出候选
        _print_candidates(root)
        return 1

    try:
        run_dir = _resolve_run_dir(run_id, root)
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        _print_candidates(root)
        return 1

    jsonl_path = run_dir / "run-state.jsonl"
    events, warnings = read_events(jsonl_path)
    run_state = RunState.rebuild(events, run_id=run_id, warnings=warnings)

    # status 对所有已存在 run 有效，无额外 state 限制
    print(_render_status(run_state, run_dir))
    return 0


def _print_candidates(repo_root: Path) -> None:
    """打印候选 run 列表（D-002 双轨期）。"""
    candidates: list[str] = []
    for base_dir in [repo_root / "requirements", repo_root / "runs"]:
        if base_dir.is_dir():
            for d in sorted(base_dir.iterdir()):
                if d.is_dir() and (d / "run-state.jsonl").exists():
                    candidates.append(d.name)
    if candidates:
        print(f"可用 run：{', '.join(candidates)}", file=sys.stderr)
    else:
        print("未找到任何 workflow run", file=sys.stderr)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:] if len(sys.argv) > 1 else []))
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
