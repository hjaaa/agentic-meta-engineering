"""workflow status 命令入口（F-005 + F-009）。

/workflow:status [<run-id>] [--verbose]

只读展示父子树（spec §6.4）。不写 jsonl，不改 meta。
--verbose：额外输出节点分类（ready/running/blocked/awaiting/done）+ stale 检测（D-002/D-010/D-011）。

详细设计 §1.2.4 / §3.7 / §5.2。
"""
from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError, infer_run_id_from_branch  # noqa: E402
from run_state import RunState, _resolve_run_dir, read_events, SUCCESS_TERMINAL  # noqa: E402

# ---------------------------------------------------------------------------
# F-009 常量：stale 阈值（env 覆盖，非整数 fallback 30）
# ---------------------------------------------------------------------------
try:
    STALE_THRESHOLD_MINUTES: int = int(os.environ.get("CLAUDE_WORKFLOW_STALE_MINUTES", "30"))
except (ValueError, TypeError):
    STALE_THRESHOLD_MINUTES = 30


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

    # 递归子 run（扫 run_dir/sub_runs/<node_id>/，目录名即子 run id）
    sub_runs_dir = run_dir / "sub_runs"
    if sub_runs_dir.is_dir():
        for sub_run_dir in sorted(sub_runs_dir.iterdir()):
            if not sub_run_dir.is_dir():
                continue
            sub_run_id = sub_run_dir.name  # 目录名即子 run id（与 rollback_subrun 约定一致）
            sub_events, sub_warnings = read_events(sub_run_dir / "run-state.jsonl")
            sub_state = RunState.rebuild(sub_events, run_id=sub_run_id, warnings=sub_warnings)
            lines.append(f"{prefix}  └─ 子 run:")
            lines.append(_render_status(sub_state, sub_run_dir, indent + 2))

    return "\n".join(lines)


def _is_stale(last_event_ts: str | None, threshold_min: int) -> bool:
    """判断 last_event_ts 是否已超过 threshold_min 分钟（D-010 stale 检测）。

    Args:
        last_event_ts: ISO 8601 时间戳字符串，或 None。
        threshold_min: 超时阈值（分钟）。

    Returns:
        True 若 now - last_event_ts >= threshold_min；ts 为 None 或解析失败返回 False。
    """
    if not last_event_ts:
        return False
    try:
        last = datetime.datetime.fromisoformat(
            last_event_ts.replace("Z", "+00:00")
        )
    except (ValueError, AttributeError):
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    age_min = (now - last).total_seconds() / 60
    return age_min >= threshold_min


def _classify_nodes(
    run_state: RunState,
    workflow: dict,
    run_dir: Path,
) -> dict:
    """将 workflow 节点按状态分类（D-002 树形分类）。

    Args:
        run_state: 当前重建后的 RunState。
        workflow:  workflow yaml dict（需含 nodes 列表）。
        run_dir:   run 目录路径，用于反扫 jsonl 确定 awaiting kind。

    Returns:
        dict with keys: done, running, awaiting, ready, blocked, failed
        每个值为 list of dict（节点信息）。
    """
    from workflow_scheduler import _ready_nodes  # noqa: E402

    node_outputs = run_state.node_outputs
    current = run_state.current_node
    run_state_str = run_state.state

    # done / failed 集合
    done_ids: set[str] = set()
    failed_ids: set[str] = set()
    for nid, entry in node_outputs.items():
        s = (entry or {}).get("state")
        if s in SUCCESS_TERMINAL:
            done_ids.add(nid)
        elif s == "failed":
            failed_ids.add(nid)

    # running
    running_ids: set[str] = set()
    if run_state_str == "running" and current:
        running_ids.add(current)

    # awaiting — 反扫末位事件确定 kind
    awaiting_nodes: list[dict] = []
    if run_state_str == "awaiting_claude_action" and current:
        kind = _infer_awaiting_kind(run_dir)
        awaiting_nodes.append({"id": current, "kind": kind})

    awaiting_ids = {n["id"] for n in awaiting_nodes}

    # ready
    ready_ids: set[str] = set()
    try:
        ready_ids = set(_ready_nodes(run_state, workflow))
    except Exception:  # workflow 格式异常时 fail-soft
        ready_ids = set()

    # blocked = 所有已知节点，去掉 done / failed / running / awaiting / ready
    all_node_ids: list[str] = [
        n["id"] for n in (workflow.get("nodes") or [])
        if isinstance(n, dict) and n.get("id")
    ]
    seen: set[str] = done_ids | failed_ids | running_ids | awaiting_ids | ready_ids

    blocked_nodes: list[dict] = []
    for node in (workflow.get("nodes") or []):
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        if not nid or nid in seen:
            continue
        reason, extra = _blocked_reason(nid, node, run_state, done_ids, running_ids)
        blocked_nodes.append({"id": nid, "reason": reason, "extra": extra})

    return {
        "done": [{"id": nid} for nid in sorted(done_ids)],
        "failed": [{"id": nid} for nid in sorted(failed_ids)],
        "running": [{"id": nid} for nid in sorted(running_ids)],
        "awaiting": awaiting_nodes,
        "ready": [{"id": nid} for nid in sorted(ready_ids)],
        "blocked": blocked_nodes,
    }


def _infer_awaiting_kind(run_dir: Path) -> str:
    """反扫 run-state.jsonl 末位相关事件，确定 awaiting 节点的 kind。

    Args:
        run_dir: run 目录路径。

    Returns:
        'skill_result' 或 'approval_repair'（默认 'skill_result'）。
    """
    jsonl_path = run_dir / "run-state.jsonl"
    events, _ = read_events(jsonl_path)
    # 逆序找首条 node_ready 或 approval_repair_started
    for evt in reversed(events):
        ev_type = evt.get("type")
        if ev_type == "node_ready":
            return "skill_result"
        if ev_type == "approval_repair_started":
            return "approval_repair"
    return "skill_result"


def _blocked_reason(
    nid: str,
    node: dict,
    run_state: RunState,
    done_ids: set[str],
    running_ids: set[str],
) -> tuple[str, str]:
    """确定 blocked 节点的 reason 及附加说明字符串。

    Args:
        nid:       节点 id。
        node:      workflow nodes 列表中该节点的 dict。
        run_state: 当前 RunState。
        done_ids:  已成功完成节点 id 集合（SUCCESS_TERMINAL）。
        running_ids: 当前 running 节点 id 集合。

    Returns:
        (reason, extra): reason ∈ {incomplete_dispatch, awaiting_deps, awaiting_claude_action}
                          extra 为附加说明字符串（可为空）。
    """
    node_outputs = run_state.node_outputs
    existing = node_outputs.get(nid)
    if existing and existing.get("state") == "running" and nid not in running_ids:
        # node_started 有记录（state=running），但不是 current_node → incomplete_dispatch
        return "incomplete_dispatch", f"node: {nid}"

    deps: list[str] = node.get("depends_on") or []
    unmet = [d for d in deps if d not in done_ids]
    if unmet:
        return "awaiting_deps", f"deps: {unmet}"

    if run_state.state == "awaiting_claude_action":
        return "awaiting_claude_action", ""

    return "awaiting_deps", ""


def _render_status_verbose(
    run_state: RunState,
    run_dir: Path,
    workflow: dict | None,
) -> str:
    """在既有 _render_status 基础上叠加 verbose 段（D-002 树形 + D-010 stale）。

    Args:
        run_state: 当前重建后的 RunState。
        run_dir:   run 目录路径。
        workflow:  workflow yaml dict；None 时节点分类段跳过（fail-soft）。

    Returns:
        完整 verbose status 字符串。
    """
    base = _render_status(run_state, run_dir)
    lines = [base]

    # heartbeat / stale
    ts = run_state.last_event_ts
    if ts:
        try:
            last = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            last = None
        if last:
            now = datetime.datetime.now(datetime.timezone.utc)
            age_min = int((now - last).total_seconds() / 60)
            if _is_stale(ts, STALE_THRESHOLD_MINUTES):
                lines.append(
                    f"  WARN: stale heartbeat (age={age_min}min"
                    f" ≥ {STALE_THRESHOLD_MINUTES}min threshold)"
                )

    # 节点分类（workflow 加载失败时 fail-soft 跳过）
    if workflow is None:
        return "\n".join(lines)

    try:
        classes = _classify_nodes(run_state, workflow, run_dir)
    except Exception:
        return "\n".join(lines)

    def _fmt_node_list(nodes: list[dict], cat: str) -> str:
        if not nodes:
            return "(none)"
        parts: list[str] = []
        for n in nodes:
            nid = n["id"]
            if cat == "blocked":
                reason = n.get("reason", "")
                extra = n.get("extra", "")
                if extra:
                    parts.append(f"{nid} ({reason}: {extra})")
                else:
                    parts.append(f"{nid} ({reason})")
            elif cat == "awaiting":
                kind = n.get("kind", "skill_result")
                parts.append(f"{nid} (kind={kind})")
            else:
                parts.append(nid)
        return ", ".join(parts)

    for cat, label in [
        ("ready", "ready"),
        ("running", "running"),
        ("awaiting", "awaiting"),
        ("blocked", "blocked"),
        ("done", "done"),
    ]:
        nodes = classes[cat]
        count = len(nodes)
        body = _fmt_node_list(nodes, cat)
        lines.append(f"{label} ({count}):   {body}")

    return "\n".join(lines)


def main(args: list[str], repo_root: Path | None = None) -> int:
    """status 命令主入口。

    Args:
        args:      命令行参数列表，格式 [run_id?] [--verbose]（可选）。
        repo_root: 注入 repo 根路径（测试用）。

    Returns:
        exit code（0 成功，1 失败）。
    """
    root = repo_root or REPO_ROOT

    # 解析 --verbose flag
    verbose = "--verbose" in args
    positional = [a for a in args if a != "--verbose"]

    run_id = positional[0] if positional else None
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

    # AC-08: jsonl 读取失败 → stderr + exit 1
    unreadable = [w for w in run_state.warnings if "jsonl 读取失败" in w]
    if unreadable:
        for w in unreadable:
            print(f"ERROR: jsonl unreadable: {w}", file=sys.stderr)
        return 1

    # status 对所有已存在 run 有效，无额外 state 限制
    if not verbose:
        print(_render_status(run_state, run_dir))
        return 0

    # --verbose 模式：加载 workflow（fail-soft）
    workflow: dict | None = None
    try:
        from workflow_continue import _load_workflow_for_run  # noqa: E402
        workflow = _load_workflow_for_run(run_state, run_dir, root)
    except Exception:
        pass  # fail-soft：渲染基础段，跳过节点分类

    print(_render_status_verbose(run_state, run_dir, workflow))
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
