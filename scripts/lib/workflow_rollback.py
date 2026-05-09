"""workflow rollback 命令（F-007）。

公开 API：
    rollback_run(run_id, to_node, target_id=None) → RollbackResult

功能：
- 拓扑序找产物路径集合 → shutil.move 到 .archived/<ts>/
- 父 run 跨 sub_workflow 节点时，递归 mv 子 run 整目录
- 写 .in_progress atomic 标记保护中断
- 截断 jsonl 尾部 mv 为 <archived>/run-state.jsonl.tail
- 双层锁：§6.4 顺序 = flock → mkdir → O_EXCL，flock 先行
- .archived/<ts>/.meta.json 持久化 run_id/to_node/started_at，续跑读取

详细设计：requirements/REQ-2026-009/artifacts/detailed-design.md §6.1~§6.7
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import yaml  # noqa: E402

from common import REPO_ROOT, WorkflowError  # noqa: E402
from run_state import (  # noqa: E402
    _resolve_run_dir,
    read_events,
    append_event,
    RunState,
)
from topological_sort import topological_layers  # noqa: E402

logger = logging.getLogger(__name__)

# ============================================================================
# 数据结构
# ============================================================================

@dataclass(frozen=True)
class SubRunArchive:
    """跨父子 mv 时的子 run 归档信息。"""

    child_run_id: str                        # 子 run id（释放后不复用）
    archive_path: Path                       # 父 .archived/<ts>/sub_runs/<child-id>/ 绝对路径
    jsonl_event_count: int                   # 子 jsonl 行数（用于断言完整性）


@dataclass(frozen=True)
class RollbackResult:
    """rollback_run() 返回值。"""

    run_id: str                              # 被回滚的 run id
    archive_ts: str                          # 归档目录时间戳（ISO8601 East 8）
    archive_root: Path                       # .archived/<ts>/ 绝对路径
    moved_artifacts: list[Path]              # 被 mv 的产物文件相对路径
    moved_sub_runs: list[SubRunArchive]      # 跨父子 mv 的子 run（F1 场景）
    truncated_jsonl_tail: Path               # <archived>/run-state.jsonl.tail
    new_current_node: str                    # rollback 后续跑起点（= to_node，从此节点重新执行）
    duration_ms: int                         # 操作耗时
    partial: bool = False                    # True = 续跑收尾路径（不是首次 rollback）


# ============================================================================
# 异常体系
# ============================================================================

class RollbackError(WorkflowError):
    """rollback 专用异常基类（不直接抛出）。"""


class RunStateNotFoundError(RollbackError):
    """run_id 在两条路径都查不到 run 目录。"""


class TargetNodeNotFoundError(RollbackError):
    """to_node 不在 run 对应 yaml 节点 ID 集合。"""


class TargetNodeNotUpstreamError(RollbackError):
    """to_node 不是当前节点的拓扑上游（或就是当前节点本身）。"""


class ConcurrentRollbackError(RollbackError):
    """runs/<id>/.rollback.lock 已被持有（fcntl.flock 失败）。"""


class RollbackInProgressError(RollbackError):
    """.archived/<ts>/.in_progress 残留且 ts ≠ 本次（中断未续跑前禁止新 rollback）。"""


class RollbackResumeMismatchError(RollbackError):
    """.meta.json 中记录的 to_node 与调用方传入的 to_node 不一致。"""


# IOError（标准异常）重抛，不在此定义

# ============================================================================
# 内部工具：东八区时间戳
# ============================================================================

def _make_archive_ts() -> str:
    """生成 ISO8601 东八区时间戳，如 2026-05-08T17:00:00+0800。"""
    east8 = timezone(timedelta(hours=8))
    return datetime.now(east8).strftime("%Y-%m-%dT%H:%M:%S+0800")


def _now_iso8601() -> str:
    """返回当前 UTC ISO8601 时间戳。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================================
# 内部工具：workflow yaml 加载与节点拓扑解析
# ============================================================================

def _find_workflow_yaml(run_dir: Path) -> Path:
    """从 run 目录找到 workflow.yaml。

    查找顺序：run_dir/workflow.yaml → run_dir/../*.yaml（兼容测试 fixture 和真实路径）。
    找不到则抛 TargetNodeNotFoundError（缺 yaml 等同于节点集合为空）。
    """
    # 优先 run_dir 内
    direct = run_dir / "workflow.yaml"
    if direct.is_file():
        return direct
    # 兼容：run_dir 同级（requirements/<id>/ 下的 workflow.yaml）
    sibling = run_dir.parent / "workflow.yaml"
    if sibling.is_file():
        return sibling
    # 向上两级（runs/<id>/ 场景）
    for candidate in run_dir.parents:
        c = candidate / "workflow.yaml"
        if c.is_file():
            return c
        if candidate == run_dir.parents[2]:  # 最多向上 3 层
            break
    raise TargetNodeNotFoundError(
        f"run_dir {run_dir} 未找到 workflow.yaml；无法校验 to_node"
    )


def _load_nodes(run_dir: Path) -> list[dict[str, Any]]:
    """加载 workflow.yaml 并返回 nodes 列表（已做 depends_on 展开）。

    rollback 只需要节点 ID 集合 + depends_on 拓扑结构，
    不需要深入校验 sub_workflow 路径/prompt_file 等运行时资源，
    因此直接用 yaml.safe_load 读取而不走 load_workflow 的严格校验。
    """
    yaml_path = _find_workflow_yaml(run_dir)
    try:
        with yaml_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except (yaml.YAMLError, OSError) as exc:
        raise TargetNodeNotFoundError(
            f"workflow.yaml 读取失败（{yaml_path}）：{exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise TargetNodeNotFoundError(
            f"workflow.yaml 顶层不是 mapping（{yaml_path}）"
        )

    nodes = raw.get("nodes") or []
    if not isinstance(nodes, list):
        raise TargetNodeNotFoundError(
            f"workflow.yaml nodes 不是列表（{yaml_path}）"
        )

    # 展开隐式 depends_on（缺省 = 接上一节点）
    _expand_implicit_depends_on(nodes)
    return nodes


def _expand_implicit_depends_on(nodes: list[dict[str, Any]]) -> None:
    """展开 depends_on 缺省规则：缺失时隐式接上一节点（spec §6.12）。

    在 workflow_loader._expand_implicit_depends_on 同逻辑，这里独立实现，
    避免导入 workflow_loader（后者有严格校验依赖）。
    """
    prev_id: str | None = None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if "depends_on" not in node:
            node["depends_on"] = [prev_id] if prev_id else []
        prev_id = node.get("id")


def _all_node_ids(nodes: list[dict[str, Any]]) -> set[str]:
    """从 nodes 提取所有节点 ID 集合。"""
    return {n["id"] for n in nodes if isinstance(n, dict) and "id" in n}


def _get_ordered_node_ids(nodes: list[dict[str, Any]]) -> list[str]:
    """返回拓扑排序后的节点 ID 平铺列表（前→后）。"""
    layers = topological_layers(nodes)
    return [nid for layer in layers for nid in layer]


def _validate_to_node_is_upstream(
    nodes: list[dict[str, Any]],
    current_node: str | None,
    to_node: str,
    run_state: "RunState",
) -> None:
    """校验 to_node 是 current_node 的拓扑上游（严格上游，不能是当前节点本身）。

    如果 current_node 为 None，使用 node_outputs 中最后完成的节点作为当前位置。
    """
    ordered = _get_ordered_node_ids(nodes)

    # 确定"当前"节点的位置（最后完成/运行中的节点）
    current_pos = _find_current_position(ordered, current_node, run_state)
    to_pos = ordered.index(to_node) if to_node in ordered else -1

    if to_pos < 0:
        # 已在 _validate_to_node_exists 中处理；这里兜底
        raise TargetNodeNotFoundError(f"to_node={to_node!r} 不在 workflow 节点列表")

    if to_pos >= current_pos:
        raise TargetNodeNotUpstreamError(
            f"to_node={to_node!r}（位置 {to_pos}）不是 current_node（位置 {current_pos}）的上游；"
            f"rollback 只能回到更早的节点"
        )


def _find_current_position(
    ordered: list[str],
    current_node: str | None,
    run_state: "RunState",
) -> int:
    """确定当前执行位置索引（在 ordered 中的位置）。

    优先用 current_node（正在运行中的节点），否则用 node_outputs 中最后完成的节点。
    """
    if current_node and current_node in ordered:
        return ordered.index(current_node)

    # 从 node_outputs 推断：找最后一个完成的节点
    last_pos = -1
    for nid, info in run_state.node_outputs.items():
        if nid in ordered:
            pos = ordered.index(nid)
            if pos > last_pos:
                last_pos = pos

    if last_pos < 0:
        # 无已完成节点；返回列表末尾（允许回滚到任意节点）
        return len(ordered)

    # 最后完成节点的下一个位置
    return last_pos + 1


# ============================================================================
# 内部工具：产物路径收集（委托给 workflow_rollback_archive）
# ============================================================================

def _collect_artifacts_to_archive(
    run_dir: Path,
    nodes: list[dict[str, Any]],
    run_state: "RunState",
    to_node: str,
) -> list[Path]:
    """收集需要 mv 到 .archived 的产物文件列表（委托给 archive 子模块）。"""
    from workflow_rollback_archive import _collect_artifacts_to_archive as _impl
    return _impl(run_dir, nodes, run_state, to_node)


def _move_artifacts(
    artifacts: list[Path],
    archive_root: Path,
) -> list[Path]:
    """把产物列表 mv 到 archive_root 下（委托给 archive 子模块）。"""
    from workflow_rollback_archive import _move_artifacts as _impl
    return _impl(artifacts, archive_root)


def _truncate_jsonl_to_tail(
    jsonl_path: Path,
    archive_root: Path,
    to_node: str,
    ordered_nodes: list[str],
    events: list[dict[str, Any]] | None = None,
) -> tuple[Path, list[Any]]:
    """jsonl 截断 + tail 归档（委托给 archive 子模块）。"""
    from workflow_rollback_archive import _truncate_jsonl_to_tail as _impl
    return _impl(jsonl_path, archive_root, to_node, ordered_nodes, events)


# ============================================================================
# 内部工具：双层锁（委托给 lock 子模块）
# ============================================================================

def _acquire_flock(lock_path: Path) -> Any:
    """获取 fcntl.flock（委托给 lock 子模块）。"""
    from workflow_rollback_lock import _acquire_flock as _impl
    return _impl(lock_path)


def _acquire_dual_lock(
    lock_path: Path,
    in_progress_path: Path,
) -> tuple[Any, int]:
    """获取双层锁（委托给 lock 子模块）。"""
    from workflow_rollback_lock import _acquire_dual_lock as _impl
    return _impl(lock_path, in_progress_path)


def _find_in_progress_archive(run_dir: Path) -> Path | None:
    """扫描续跑残留（委托给 lock 子模块）。"""
    from workflow_rollback_lock import _find_in_progress_archive as _impl
    return _impl(run_dir)


# ============================================================================
# 内部工具：子 run 归档（委托给 subrun 子模块）
# ============================================================================

def _discover_sub_runs(
    run_dir: Path,
    nodes_after: list[str],
    repo_root: Path,
    node_map: dict[str, dict[str, Any]],
    target_id: str | None = None,
) -> list[Path]:
    """统一子 run 发现策略（委托给 subrun 子模块）。"""
    from workflow_rollback_subrun import _discover_sub_runs as _impl
    return _impl(run_dir, nodes_after, repo_root, node_map, target_id)


def _archive_sub_run(
    child_run_dir: Path,
    sub_runs_archive_dir: Path,
    run_id: str,
) -> SubRunArchive:
    """子 run 整目录 mv（委托给 subrun 子模块）。"""
    from workflow_rollback_subrun import _archive_sub_run as _impl
    return _impl(child_run_dir, sub_runs_archive_dir, run_id)


# ============================================================================
# 内部工具：.meta.json 持久化（M-3）
# ============================================================================

def _write_meta_json(archive_root: Path, run_id: str, to_node: str) -> None:
    """写 .archived/<ts>/.meta.json，持久化续跑所需的上下文。

    字段：run_id / to_node / started_at（ISO8601 UTC）
    """
    meta = {
        "run_id": run_id,
        "to_node": to_node,
        "started_at": _now_iso8601(),
    }
    meta_path = archive_root / ".meta.json"
    with meta_path.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)


def _read_meta_json(archive_root: Path) -> dict[str, Any] | None:
    """读取 .archived/<ts>/.meta.json，返回 dict 或 None（文件不存在/损坏时）。"""
    meta_path = archive_root / ".meta.json"
    if not meta_path.is_file():
        return None
    try:
        with meta_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


# ============================================================================
# 内部：续跑收尾（crash-recovery）
# ============================================================================

def _resume_in_progress(
    run_dir: Path,
    stale_archive_dir: Path,
    to_node: str,
    nodes: list[dict[str, Any]],
    run_state: "RunState",
    run_id: str,
    repo_root: Path,
) -> RollbackResult:
    """拿锁续跑：完成上次崩溃遗留的 mv 操作，删 .in_progress，返回 partial=True 结果。

    策略：重新收集尚未 mv 的产物（原路径还存在的），再完成剩余 mv。
    续跑时优先从 .meta.json 读 to_node，不一致时抛 RollbackResumeMismatchError。
    """
    start_ms = time.monotonic()
    lock_path = run_dir / ".rollback.lock"
    in_prog = stale_archive_dir / ".in_progress"

    # 从 .meta.json 验证 to_node 一致性（M-3）
    meta = _read_meta_json(stale_archive_dir)
    if meta is not None:
        meta_to_node = meta.get("to_node")
        if meta_to_node is not None and meta_to_node != to_node:
            raise RollbackResumeMismatchError(
                f"续跑 to_node 不一致：.meta.json 记录 {meta_to_node!r}，"
                f"调用方传入 {to_node!r}；请使用 {meta_to_node!r} 续跑"
            )
        # 若 meta 有 to_node，使用它（保证续跑语义一致）
        if meta_to_node is not None:
            to_node = meta_to_node
    else:
        # .meta.json 缺失（兼容旧 .archived 目录）→ fallback 到调用方 to_node + 警告
        logger.warning(
            "续跑：.meta.json 缺失（run_id=%s, archive=%s），fallback 到调用方 to_node=%s",
            run_id, stale_archive_dir, to_node,
        )

    # 重新拿 flock（.in_progress 已存在，不走 O_EXCL 路径）
    try:
        lock_fd = open(str(lock_path), "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise ConcurrentRollbackError(
            f"续跑时锁已被占用（{lock_path}）：{exc}"
        ) from exc

    try:
        archive_root = stale_archive_dir
        # 收集尚未 mv 的产物（原路径还存在的）
        artifacts = _collect_artifacts_to_archive(run_dir, nodes, run_state, to_node)
        remaining = [a for a in artifacts if a.exists()]
        moved = _move_artifacts(remaining, archive_root)

        # 续跑中的 jsonl tail（如果 tail 文件还不存在则重新截断）
        jsonl_path = run_dir / "run-state.jsonl"
        tail_path = archive_root / "run-state.jsonl.tail"
        ordered = _get_ordered_node_ids(nodes)
        if not tail_path.exists():
            tail_path, _ = _truncate_jsonl_to_tail(jsonl_path, archive_root, to_node, ordered)

        # 子 run 续跑
        sub_runs_done = _archive_pending_sub_runs(
            run_dir, nodes, to_node, archive_root, run_id, repo_root
        )

        duration_ms = int((time.monotonic() - start_ms) * 1000)
        new_current_node = _determine_new_current_node(to_node)
        archive_ts = archive_root.name

        logger.info(
            "rollback 续跑完成（run_id=%s, to_node=%s, archive_ts=%s, duration_ms=%d）",
            run_id, to_node, archive_ts, duration_ms,
        )

        return RollbackResult(
            run_id=run_id,
            archive_ts=archive_ts,
            archive_root=archive_root,
            moved_artifacts=moved,
            moved_sub_runs=sub_runs_done,
            truncated_jsonl_tail=tail_path,
            new_current_node=new_current_node,
            duration_ms=duration_ms,
            partial=True,
        )
    finally:
        # M-2：unlink 进 finally 紧贴 flock 释放前；unlink 失败包装为 RollbackError
        try:
            if in_prog.exists():
                in_prog.unlink()
        except OSError as exc:
            raise RollbackError(
                f".in_progress 删除失败（{in_prog}）：{exc}"
            ) from exc
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()


def _archive_pending_sub_runs(
    run_dir: Path,
    nodes: list[dict[str, Any]],
    to_node: str,
    archive_root: Path,
    run_id: str,
    repo_root: Path,
) -> list[SubRunArchive]:
    """收集并归档尚未 mv 的子 run（续跑场景）。"""
    ordered = _get_ordered_node_ids(nodes)
    to_pos = ordered.index(to_node) if to_node in ordered else -1
    nodes_after = ordered[to_pos + 1:] if to_pos >= 0 else []
    node_map = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}

    sub_runs_archive_dir = archive_root / "sub_runs"
    archived: list[SubRunArchive] = []
    child_dirs = _discover_sub_runs(run_dir, nodes_after, repo_root, node_map)
    for child_dir in child_dirs:
        # 跳过已归档的（目录已不存在）
        if child_dir.is_dir():
            archived.append(
                _archive_sub_run(child_dir, sub_runs_archive_dir, run_id)
            )
    return archived


def _determine_new_current_node(to_node: str) -> str:
    """rollback 后续跑起点 = to_node 本身（重新从 to_node 开始执行）。

    M-14：删 nodes 参数（未使用），与 test_R1_single_layer 断言一致。
    """
    return to_node


# ============================================================================
# 内部：校验链 + archive 准备（M-10 提取）
# ============================================================================

def _resolve_and_validate(
    run_id: str,
    to_node: str,
    root: Path,
) -> tuple[Path, list[dict[str, Any]], RunState, list[dict[str, Any]]]:
    """步骤 1-5 校验链：解析 run 目录 → 加载节点 → 校验 to_node → 读状态 → 校验上游。

    返回：(run_dir, nodes, run_state, events)

    M-6：对 run_id 做 path-traversal 防护（格式校验）。
    """
    # M-6：校验 run_id 格式（仅允许 [A-Za-z0-9_\-]）
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", run_id):
        raise RollbackError(
            f"run_id 包含非法字符（只允许 [A-Za-z0-9_\\-]）：{run_id!r}"
        )

    # 步骤 1：解析 run 目录
    try:
        run_dir = _resolve_run_dir(run_id, root)
    except WorkflowError as exc:
        raise RunStateNotFoundError(
            f"run_id={run_id!r} 不存在：{exc}"
        ) from exc

    # 步骤 2：加载 workflow 节点
    nodes = _load_nodes(run_dir)
    all_ids = _all_node_ids(nodes)

    # 步骤 3：校验 to_node 存在
    if to_node not in all_ids:
        raise TargetNodeNotFoundError(
            f"to_node={to_node!r} 不在 workflow 节点集合 {sorted(all_ids)}"
        )

    # 步骤 4：读取当前运行状态（M-12：传 events 给后续调用方，避免双读 jsonl）
    jsonl_path = run_dir / "run-state.jsonl"
    events, warnings = read_events(jsonl_path)
    run_state = RunState.rebuild(events, run_id=run_id, warnings=warnings)

    # 步骤 5：校验 to_node 是上游
    _validate_to_node_is_upstream(nodes, run_state.current_node, to_node, run_state)

    return run_dir, nodes, run_state, events


def _setup_archive(run_dir: Path) -> tuple[Path, str]:
    """步骤 6-7：生成时间戳 + 创建 archive 目录（M-10 提取）。

    注意：lock 在 mkdir 之后获取（§6.4：flock → mkdir → O_EXCL 对外 API 是先 flock，
    但 mkdir archive_root 在 acquire_dual_lock 之前完成）。
    实际顺序：generate_ts → mkdir archive_root → acquire flock → O_EXCL in_progress。
    """
    archive_ts = _make_archive_ts()
    archive_root = run_dir / ".archived" / archive_ts
    archive_root.mkdir(parents=True, exist_ok=True)
    return archive_root, archive_ts


# ============================================================================
# 公开 API
# ============================================================================

def rollback_run(
    run_id: str,
    to_node: str,
    target_id: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> RollbackResult:
    """把 run_id 从当前节点回滚到 to_node。

    参数：
        run_id     — 目标 run id（兼容 requirements/<id>/ 与 runs/<id>/ 双路径）
        to_node    — yaml 节点 id；必须是当前节点的拓扑上游
        target_id  — 跨父子 rollback 时指定子 run id（可选）；
                     缺省时父 rollback 自动级联到所有匹配 sub_workflow 子 run
        repo_root  — 注入 repo 根路径（测试用）；None 时用 REPO_ROOT

    返回：RollbackResult

    异常：
        RunStateNotFoundError          — run_id 不存在
        TargetNodeNotFoundError        — to_node 不在节点集合
        TargetNodeNotUpstreamError     — to_node 不是当前位置的上游
        ConcurrentRollbackError        — 锁被占用
        RollbackInProgressError        — .in_progress 残留（触发续跑）
        RollbackResumeMismatchError    — 续跑 to_node 与 .meta.json 记录不一致
        IOError                        — 文件系统操作失败
    """
    start_ms = time.monotonic()
    root = repo_root or REPO_ROOT

    # M-6：校验 target_id 格式
    if target_id is not None and not re.fullmatch(r"[A-Za-z0-9_\-]+", target_id):
        raise RollbackError(
            f"target_id 包含非法字符（只允许 [A-Za-z0-9_\\-]）：{target_id!r}"
        )

    logger.info("rollback_run 开始（run_id=%s, to_node=%s）", run_id, to_node)

    # 步骤 1-5：校验链（M-10）
    run_dir, nodes, run_state, events = _resolve_and_validate(run_id, to_node, root)

    # 步骤 6：检测 .in_progress 残留（崩溃续跑）
    stale_archive = _find_in_progress_archive(run_dir)
    if stale_archive is not None:
        logger.info(
            "检测到 .in_progress 残留（run_id=%s, archive=%s），执行续跑",
            run_id, stale_archive,
        )
        return _resume_in_progress(
            run_dir, stale_archive, to_node, nodes, run_state, run_id, root
        )

    # 步骤 7-8（M-1 锁顺序 §6.4）：
    #   1. lock_path = run_dir/.rollback.lock
    #   2. lock_fd = _acquire_flock(lock_path)   ← 先 flock
    #   try:
    #       3. archive_ts = _make_archive_ts()
    #       4. archive_root = run_dir/.archived/<ts>
    #       5. archive_root.mkdir
    #       6. in_progress_path = archive_root/.in_progress
    #       7. in_prog_fd = O_EXCL(.in_progress)
    #       try: mv 主流程 ...
    #       finally: unlink(.in_progress) → flock 释放（M-2）

    lock_path = run_dir / ".rollback.lock"

    # M-1：先 acquire flock（§6.4 要求 flock → mkdir → O_EXCL）
    lock_fd = _acquire_flock(lock_path)
    try:
        # M-1：flock 之后再 mkdir
        archive_root, archive_ts = _setup_archive(run_dir)
        in_progress_path = archive_root / ".in_progress"

        # M-1：O_EXCL 创建 .in_progress
        try:
            in_prog_fd = os.open(
                str(in_progress_path),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
            )
        except OSError as exc:
            raise RollbackInProgressError(
                f".in_progress 标记已存在（{in_progress_path}），"
                f"可能是上次崩溃残留；请重新调用 rollback_run 续跑"
            ) from exc
        os.close(in_prog_fd)

        # M-3：写 .meta.json（在 .in_progress 创建后立刻写）
        _write_meta_json(archive_root, run_id, to_node)

        try:
            result = _execute_rollback(
                run_dir=run_dir,
                archive_root=archive_root,
                archive_ts=archive_ts,
                nodes=nodes,
                run_state=run_state,
                to_node=to_node,
                run_id=run_id,
                target_id=target_id,
                root=root,
                start_ms=start_ms,
                events=events,
            )
        finally:
            # M-2：unlink 放进 finally 紧贴 flock 释放前；失败包装为 RollbackError
            try:
                if in_progress_path.exists():
                    in_progress_path.unlink()
            except OSError as exc:
                raise RollbackError(
                    f".in_progress 删除失败（{in_progress_path}）：{exc}"
                ) from exc
    finally:
        # flock 一定释放
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    logger.info(
        "rollback_run 完成（run_id=%s, to_node=%s, archive_ts=%s, duration_ms=%d）",
        run_id, to_node, archive_ts, result.duration_ms,
    )
    return result


def _execute_rollback(
    run_dir: Path,
    archive_root: Path,
    archive_ts: str,
    nodes: list[dict[str, Any]],
    run_state: "RunState",
    to_node: str,
    run_id: str,
    target_id: Optional[str],
    root: Path,
    start_ms: float,
    events: list[dict[str, Any]] | None = None,
) -> RollbackResult:
    """执行实际的 rollback 操作（持锁期间调用）。"""
    ordered = _get_ordered_node_ids(nodes)

    # mv jsonl tail（M-12：传入已解析的 events，避免双读）
    jsonl_path = run_dir / "run-state.jsonl"
    tail_path, _ = _truncate_jsonl_to_tail(jsonl_path, archive_root, to_node, ordered, events)

    # 收集 + mv 产物
    artifacts = _collect_artifacts_to_archive(run_dir, nodes, run_state, to_node)
    moved = _move_artifacts(artifacts, archive_root)

    # 跨父子 mv 子 run（F1 场景）
    moved_sub_runs = _execute_sub_run_archive(
        run_dir, nodes, to_node, archive_root, run_id, target_id, root
    )

    duration_ms = int((time.monotonic() - start_ms) * 1000)
    new_current_node = _determine_new_current_node(to_node)

    return RollbackResult(
        run_id=run_id,
        archive_ts=archive_ts,
        archive_root=archive_root,
        moved_artifacts=moved,
        moved_sub_runs=moved_sub_runs,
        truncated_jsonl_tail=tail_path,
        new_current_node=new_current_node,
        duration_ms=duration_ms,
        partial=False,
    )


def _execute_sub_run_archive(
    run_dir: Path,
    nodes: list[dict[str, Any]],
    to_node: str,
    archive_root: Path,
    run_id: str,
    target_id: Optional[str],
    root: Path,
) -> list[SubRunArchive]:
    """执行子 run 整目录归档（F1 跨父子场景）。

    使用 _discover_sub_runs 统一发现策略（M-4）。
    """
    sub_runs_archive_dir = archive_root / "sub_runs"
    archived: list[SubRunArchive] = []

    ordered = _get_ordered_node_ids(nodes)
    to_pos = ordered.index(to_node) if to_node in ordered else -1
    nodes_after = ordered[to_pos + 1:] if to_pos >= 0 else []
    node_map = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}

    child_dirs = _discover_sub_runs(run_dir, nodes_after, root, node_map, target_id)
    for child_dir in child_dirs:
        archived.append(
            _archive_sub_run(child_dir, sub_runs_archive_dir, run_id)
        )

    return archived


# ============================================================================
# CLI
# ============================================================================

def main(args: list[str] | None = None, repo_root: Path | None = None) -> int:
    """CLI 入口：python3 scripts/lib/workflow_rollback.py <run_id> <to_node> [--target-id=<id>]。"""
    import argparse

    parser = argparse.ArgumentParser(description="回滚 workflow run 到指定节点")
    parser.add_argument("run_id", help="目标 run id")
    parser.add_argument("to_node", help="回滚到的节点 id（必须是上游节点）")
    parser.add_argument("--target-id", dest="target_id", default=None,
                        help="指定子 run id（跨父子场景）")
    parsed = parser.parse_args(args or sys.argv[1:])

    # M-6：CLI 层格式校验（run_id / target_id path-traversal defense）
    for name, value in [("run_id", parsed.run_id), ("to_node", parsed.to_node)]:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", value):
            print(f"ERROR: {name} 包含非法字符：{value!r}", file=sys.stderr)
            return 1
    if parsed.target_id is not None:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", parsed.target_id):
            print(f"ERROR: target_id 包含非法字符：{parsed.target_id!r}", file=sys.stderr)
            return 1

    try:
        result = rollback_run(
            parsed.run_id,
            parsed.to_node,
            target_id=parsed.target_id,
            repo_root=repo_root,
        )
        print(f"✓ rollback 完成")
        print(f"  run_id:          {result.run_id}")
        print(f"  archive_ts:      {result.archive_ts}")
        print(f"  archive_root:    {result.archive_root}")
        print(f"  moved_artifacts: {len(result.moved_artifacts)} 个")
        print(f"  moved_sub_runs:  {len(result.moved_sub_runs)} 个子 run")
        print(f"  new_current_node:{result.new_current_node}")
        print(f"  duration_ms:     {result.duration_ms}")
        if result.partial:
            print("  [续跑模式] 上次崩溃残留已续跑完成")
        return 0
    except RollbackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: IO 失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
