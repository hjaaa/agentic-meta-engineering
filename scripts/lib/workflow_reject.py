"""workflow reject 命令入口（F-005 / F-006）。

/workflow:reject <reason>

人类专属动作：isatty 兜底 + hook 拦截（D-006）。reason 最短 8 字符。

F-006（AC-03b/c）：reject CLI 反扫 jsonl 计算 attempt，按 yaml on_reject.max_attempts
（缺省 D-009 默认 3）分两支原子写：
  - attempt < max → [approval_rejected(attempt=N), approval_repair_started(attempt=N)]
    state 派生 awaiting_claude_action（rebuild 由 approval_repair_started 触发）
  - attempt == max → [approval_rejected, node_failed(approval_attempts_exhausted), workflow_failed]
    state 派生 failed

reason 字段走 append_events_with_manifest 的 manifest fallback：batch ≥4KB 才触发外置，
单字段 ≥3500 入选（D-014 v6 P2 二段语义）。

详细设计 §1.2.7 + §3.2.2。
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from append_events import PayloadTooLargeError, append_events_with_manifest  # noqa: E402
from common import REPO_ROOT, WorkflowError, infer_run_id_from_branch  # noqa: E402
from run_state import RunState, _resolve_run_dir, read_events  # noqa: E402
from workflow_loader import load_workflow  # noqa: E402
from workflow_state_validator import check_tty_for_approval, validate_state_for_cmd  # noqa: E402

_REASON_MIN_LEN = 8
# F-006：reason 上限提至 8KB——manifest fallback 的 large_field_paths 由 append_events
# 内部按 ≥3500 入选外置，CLI 层无需提前截断（截断会破坏审计完整性）。
_REASON_MAX_LEN = 8192
DEFAULT_APPROVAL_MAX_ATTEMPTS = 3  # D-009


def _load_workflow_node(
    run_state: RunState, node_id: str, run_dir: Path, root: Path
) -> dict[str, Any]:
    """按 run_state.workflow_name 取节点定义；找不到时返回空 dict。

    查找优先级（与 workflow_continue._load_workflow_for_run 同模式）：
      1. 约定路径 `.claude/workflows/requirement/<name>.yaml`
      2. 降级读 `meta.yaml.template_path`
      3. 上述都失败 → 返回 {}（caller 走 D-009 默认）

    设计取舍：reject 是兜底通道，绝不能因 yaml loader 抽风把 CLI 拒掉——
    宁可走 D-009 默认 max_attempts=3，也不能让用户 reject 失败。
    """
    workflow_name = run_state.workflow_name
    if not workflow_name:
        return {}
    workflow_path = root / ".claude" / "workflows" / "requirement" / f"{workflow_name}.yaml"
    if not workflow_path.exists():
        meta_path = run_dir / "meta.yaml"
        if meta_path.exists():
            try:
                meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
                rel_path = meta.get("template_path") or meta.get("workflow_template_path")
                if rel_path:
                    workflow_path = root / rel_path
            except (OSError, yaml.YAMLError) as exc:
                logging.warning("reject 读 meta.yaml 降级 workflow_path 失败：%s", exc)
                return {}
    if not workflow_path.exists():
        return {}

    result = load_workflow(workflow_path)
    if result.report.errors or not result.workflow:
        logging.warning("reject 加载 workflow 失败 workflow=%s", workflow_name)
        return {}
    for node in result.workflow.get("nodes") or []:
        if isinstance(node, dict) and node.get("id") == node_id:
            return node
    return {}


def _build_reject_events(
    run_id: str,
    node_id: str,
    reason: str,
    current_attempt: int,
    max_attempts: int,
) -> list[dict[str, Any]]:
    """按 attempt vs max_attempts 决定写哪一支事件序列。

    - attempt < max → 2 事件：approval_rejected + approval_repair_started
    - attempt == max → 3 事件：approval_rejected + node_failed + workflow_failed
    """
    if current_attempt < max_attempts:
        return [
            {
                "type": "approval_rejected",
                "run_id": run_id,
                "node_id": node_id,
                "data": {"reason": reason, "attempt": current_attempt},
            },
            {
                "type": "approval_repair_started",
                "run_id": run_id,
                "node_id": node_id,
                "data": {
                    "attempt": current_attempt,
                    "max_attempts": max_attempts,
                    "prompt_ref": "approval.on_reject.prompt",
                },
            },
        ]
    return [
        {
            "type": "approval_rejected",
            "run_id": run_id,
            "node_id": node_id,
            "data": {"reason": reason, "attempt": current_attempt},
        },
        {
            "type": "node_failed",
            "run_id": run_id,
            "node_id": node_id,
            "data": {
                "reason": "approval_attempts_exhausted",
                "attempt": current_attempt,
            },
        },
        {
            "type": "workflow_failed",
            "run_id": run_id,
            "data": {
                "reason": "approval_attempts_exhausted",
                "node_id": node_id,
            },
        },
    ]


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

    # 反扫 jsonl 统计 prior_rejects
    prior_rejects = sum(
        1 for e in events
        if e.get("type") == "approval_rejected" and e.get("node_id") == node_id
    )
    current_attempt = prior_rejects + 1

    # 取 max_attempts：yaml override > D-009 默认
    node_def = _load_workflow_node(run_state, node_id, run_dir, root)
    approval_cfg = (node_def.get("approval") or {}) if isinstance(node_def, dict) else {}
    on_reject_cfg = (approval_cfg.get("on_reject") or {}) if isinstance(approval_cfg, dict) else {}
    max_attempts_raw = on_reject_cfg.get("max_attempts") if isinstance(on_reject_cfg, dict) else None
    max_attempts = int(max_attempts_raw) if isinstance(max_attempts_raw, int) and max_attempts_raw >= 1 else DEFAULT_APPROVAL_MAX_ATTEMPTS

    events_to_write = _build_reject_events(
        run_id=run_id,
        node_id=node_id,
        reason=reason,
        current_attempt=current_attempt,
        max_attempts=max_attempts,
    )

    try:
        append_events_with_manifest(
            jsonl_path,
            events_to_write,
            large_field_paths=[("data", "reason")],
            run_dir=run_dir,
        )
    except PayloadTooLargeError as exc:
        print(
            f"ERROR: reject payload 超出 4KB 上限且 manifest 落盘失败：{exc}",
            file=sys.stderr,
        )
        return 1
    except WorkflowError as exc:
        print(f"ERROR: 写 reject 事件失败：{exc}", file=sys.stderr)
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if current_attempt < max_attempts:
        print(f"Rejected {node_id!r} at {ts} (attempt {current_attempt}/{max_attempts})")
        print(f"  run_id: {run_id}")
        print("  on_reject 路径：approval_repair_started → 等 Claude 修复后回 approval_pending")
    else:
        print(f"Rejected {node_id!r} at {ts} (attempt {current_attempt}/{max_attempts}) → 达上限")
        print(f"  run_id: {run_id}")
        print("  状态机：approval_pending → failed (approval_attempts_exhausted)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:] if len(sys.argv) > 1 else []))
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
