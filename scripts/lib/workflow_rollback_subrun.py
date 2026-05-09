"""workflow_rollback 子 run 归档工具模块（F-007）。

提供：
- _discover_sub_runs: 统一子 run 发现策略（首次/续跑共用）
- _archive_sub_run: 子 run 整目录 mv + parent_rolled_back 事件追加
- _count_jsonl_lines: 统计 jsonl 行数

详细设计：requirements/REQ-2026-009/artifacts/detailed-design.md §6.5 F1 场景
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _discover_sub_runs(
    run_dir: Path,
    nodes_after: list[str],
    repo_root: Path,
    node_map: dict[str, dict[str, Any]],
    target_id: str | None = None,
) -> list[Path]:
    """统一子 run 发现策略（首次/续跑共用）。

    发现优先级（§6.5 F1 / M-4 修复）：
    1. target_id 指定 → 精确匹配（跳过 sub_workflow 类型判断）
    2. run_dir/sub_runs/<node_id>/ 目录（子 run 直挂父 run 目录下）
    3. 精确前缀匹配 run_id-（在 repo_root/runs/ 或 repo_root/requirements/ 下）
       注意：精确前缀匹配（run_dir.name + "-"），避免短 run_id 误匹配

    参数：
        run_dir     — 父 run 目录
        nodes_after — to_node 之后的节点 ID 列表（已过滤 sub_workflow 类型时使用）
        repo_root   — repo 根路径
        node_map    — 节点 id → 节点定义的映射
        target_id   — 可选：精确指定子 run id

    返回：子 run 目录绝对路径列表（去重）
    """
    if target_id:
        # 策略 1：精确匹配 target_id
        for base in [repo_root / "runs", repo_root / "requirements"]:
            candidate = base / target_id
            if candidate.is_dir():
                _check_path_traversal(candidate, base)
                return [candidate]
        return []

    result: list[Path] = []
    seen: set[Path] = set()

    def _add(p: Path) -> None:
        if p not in seen:
            seen.add(p)
            result.append(p)

    # 策略 2：run_dir/sub_runs/<node_id>/ 直挂目录（支持任意子 run）
    sub_runs_dir = run_dir / "sub_runs"
    if sub_runs_dir.is_dir():
        for d in sorted(sub_runs_dir.iterdir()):
            if d.is_dir():
                _add(d)
        if result:
            return result

    # 策略 3：精确前缀匹配（只有直挂目录未找到时才走）
    prefix = run_dir.name + "-"
    for base in [repo_root / "runs", repo_root / "requirements"]:
        if not base.is_dir():
            continue
        for child_dir in sorted(base.iterdir()):
            if not child_dir.is_dir():
                continue
            if child_dir.name.startswith(prefix):
                _check_path_traversal(child_dir, base)
                _add(child_dir)

    return result


def _check_path_traversal(candidate: Path, base: Path) -> None:
    """校验 candidate 在 base 之下，防止路径穿越攻击。

    抛 RollbackError 如果路径不在 base 之内。
    """
    from workflow_rollback import RollbackError
    try:
        candidate.resolve().relative_to(base.resolve())
    except ValueError as exc:
        raise RollbackError(
            f"路径穿越检测失败：{candidate} 不在 {base} 目录下"
        ) from exc


def _archive_sub_run(
    child_run_dir: Path,
    sub_runs_archive_dir: Path,
    run_id: str,
) -> "SubRunArchive":
    """把子 run 整目录 mv 到 sub_runs_archive_dir/<child_run_id>/。

    G-4 修复：先 mv 整目录，再往归档后的 jsonl 追加 parent_rolled_back 事件。
    这样崩溃中点重跑时不会产生重复事件（mv 是幂等的，但 append 不是）。
    append_event 失败时抛 RollbackError。
    """
    from workflow_rollback import RollbackError, SubRunArchive
    from run_state import append_event

    child_run_id = child_run_dir.name

    # 先 mv 整目录（G-4：mv 先于 append，防止续跑产生双 parent_rolled_back 事件）
    sub_runs_archive_dir.mkdir(parents=True, exist_ok=True)
    dest = sub_runs_archive_dir / child_run_id
    try:
        shutil.move(str(child_run_dir), str(dest))
    except (OSError, shutil.Error) as exc:
        raise RollbackError(
            f"shutil.move {child_run_dir} → {dest} 失败：{exc}"
        ) from exc

    # mv 后写事件到归档后的子 jsonl（G-4：写归档后的路径）
    archived_jsonl = dest / "run-state.jsonl"
    try:
        append_event(archived_jsonl, {
            "type": "parent_rolled_back",
            "run_id": child_run_id,
            "data": {"parent_run_id": run_id},
        })
    except Exception as exc:
        raise RollbackError(
            f"append parent_rolled_back to {archived_jsonl} 失败：{exc}"
        ) from exc

    # 统计归档后 jsonl 行数（用于完整性断言）
    jsonl_event_count = _count_jsonl_lines(archived_jsonl)

    return SubRunArchive(
        child_run_id=child_run_id,
        archive_path=dest,
        jsonl_event_count=jsonl_event_count,
    )


def _count_jsonl_lines(jsonl_path: Path) -> int:
    """统计 jsonl 有效行数（不含空行）。"""
    if not jsonl_path.is_file():
        return 0
    count = 0
    with jsonl_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                count += 1
    return count
