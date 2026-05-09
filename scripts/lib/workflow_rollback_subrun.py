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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # F-7：避免循环导入 / 仅类型注解使用（运行期延迟从 workflow_rollback 导入）
    from workflow_rollback import SubRunArchive

logger = logging.getLogger(__name__)


def _discover_by_target_id(
    target_id: str,
    repo_root: Path,
) -> list[Path]:
    """策略 1：target_id 显式指定时的精确匹配。"""
    for base in [repo_root / "runs", repo_root / "requirements"]:
        candidate = base / target_id
        if candidate.is_dir():
            _check_path_traversal(candidate, base)
            return [candidate]
    return []


def _discover_by_prefix(
    run_dir: Path,
    repo_root: Path,
) -> list[Path]:
    """策略 3：精确前缀匹配 run_id-（兜底，仅当直挂目录未命中时使用）。

    精确前缀匹配（run_dir.name + "-"），避免短 run_id 误匹配。
    """
    prefix = run_dir.name + "-"
    found: list[Path] = []
    for base in [repo_root / "runs", repo_root / "requirements"]:
        if not base.is_dir():
            continue
        for child_dir in sorted(base.iterdir()):
            if not child_dir.is_dir():
                continue
            if child_dir.name.startswith(prefix):
                _check_path_traversal(child_dir, base)
                found.append(child_dir)
    return found


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

    参数：
        run_dir     — 父 run 目录
        nodes_after — to_node 之后的节点 ID 列表（已过滤 sub_workflow 类型时使用）
        repo_root   — repo 根路径
        node_map    — 节点 id → 节点定义的映射
        target_id   — 可选：精确指定子 run id

    返回：子 run 目录绝对路径列表（去重）
    rev5 重构：策略 1 / 策略 3 抽 helper，主体 CC 13 → ≤ 10。
    """
    if target_id:
        return _discover_by_target_id(target_id, repo_root)

    seen: set[Path] = set()
    result: list[Path] = []

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

    # 策略 3：兜底走精确前缀匹配
    for child_dir in _discover_by_prefix(run_dir, repo_root):
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


def _has_parent_rolled_back(jsonl_path: Path) -> bool:
    """检查 jsonl 是否已含 parent_rolled_back 事件（续跑幂等检查）。

    H-8 修复：mv 后 append 前先检查，避免续跑重复追加 parent_rolled_back 事件。
    """
    if not jsonl_path.exists():
        return False
    try:
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            if '"type": "parent_rolled_back"' in line or '"type":"parent_rolled_back"' in line:
                return True
    except OSError:
        pass
    return False


def _archive_sub_run(
    child_run_dir: Path,
    sub_runs_archive_dir: Path,
    run_id: str,
) -> "SubRunArchive":
    """把子 run 整目录 mv 到 sub_runs_archive_dir/<child_run_id>/。

    G-4 修复：先 mv 整目录，再往归档后的 jsonl 追加 parent_rolled_back 事件。
    H-8 修复：append 前先做幂等检查，续跑路径不重复追加 parent_rolled_back 事件。
    mv 是幂等的（dest 已存在时 shutil.move 报错，由调用方处理）；append 不幂等，故需检查。
    """
    from run_state import append_event
    from workflow_rollback import RollbackError, SubRunArchive

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
    # H-8：append 前幂等检查——续跑时 parent_rolled_back 已存在则跳过
    archived_jsonl = dest / "run-state.jsonl"
    if not _has_parent_rolled_back(archived_jsonl):
        try:
            append_event(archived_jsonl, {
                "type": "parent_rolled_back",
                "run_id": child_run_id,
                "data": {"parent_run_id": run_id},
            })
        except Exception as exc:
            logger.error(
                "append parent_rolled_back to %s 失败：%s", archived_jsonl, exc,
            )
            # 不抛 RollbackError；mv 已成功，审计事件缺失走告警

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
