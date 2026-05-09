"""workflow save 命令入口（F-005）。

/workflow:save [<note>]

追加 workflow_paused（代表保存检查点）jsonl 事件。

详细设计 §1.2.3。

注意：spec `save` 事件类型不在 VALID_EVENT_TYPES 白名单（F-001 版本未扩展）。
本模块用 `workflow_paused` 作为保存事件代理，等 F-001 扩展白名单后迁移。
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError  # noqa: E402
from run_state import RunState, _resolve_run_dir, append_event, read_events  # noqa: E402
from workflow_state_validator import validate_state_for_cmd  # noqa: E402

# save 对应的 jsonl 事件类型（workflow_paused 是白名单内事件，用作保存检查点代理）
_SAVE_EVENT_TYPE = "workflow_paused"

_NOTE_MAX_LEN = 200


def main(args: list[str], repo_root: Path | None = None) -> int:
    """save 命令主入口。

    参数：
        args      — [note tokens...]（可选）
        repo_root — 注入 repo 根路径（测试用）

    返回：exit code（0 成功，1 失败）
    """
    root = repo_root or REPO_ROOT

    note = " ".join(args).replace("\n", " ")[:_NOTE_MAX_LEN]

    # 推断 run_id
    run_id = _infer_run_id(root)
    if not run_id:
        print(
            "ERROR: 无法推断当前 run_id；请先 /workflow:run 或切到 feat/req-<id> 分支",
            file=sys.stderr,
        )
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
        validate_state_for_cmd("save", run_id, run_state.state)
    except WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        event: dict = {"type": _SAVE_EVENT_TYPE, "run_id": run_id}
        if note:
            event["data"] = {"note": note}
        append_event(jsonl_path, event)
    except WorkflowError as exc:
        print(f"ERROR: 写 jsonl 事件失败：{exc}", file=sys.stderr)
        return 1

    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    current = run_state.current_node or "(none)"
    note_summary = f"，note：{note[:50]}" if note else ""
    print(f"已保存 {ts}，当前节点：{current}{note_summary}")
    return 0


def _infer_run_id(repo_root: Path) -> str | None:
    """从当前 git 分支推断 run_id。"""
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
