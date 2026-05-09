"""workflow rollback 命令（F-007）。

公开 API：
    rollback_run(run_id, to_node, target_id=None) → RollbackResult

功能：
- 拓扑序找产物路径集合 → shutil.move 到 .archived/<ts>/
- 父 run 跨 sub_workflow 节点时，递归 mv 子 run 整目录
- 写 .in_progress atomic 标记保护中断
- 截断 jsonl 尾部 mv 为 <archived>/run-state.jsonl.tail
- 双层锁：fcntl.flock（advisory）+ os.O_EXCL（原子 .in_progress 标记）

详细设计：requirements/REQ-2026-009/artifacts/detailed-design.md §6.1~§6.7
"""
from __future__ import annotations

import fcntl
import logging
import os
import shutil
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
    new_current_node: str                    # rollback 后续跑起点（= to_node 的最近上游）
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


# IOError（标准异常）重抛，不在此定义

# ============================================================================
# 内部工具：东八区时间戳
# ============================================================================

def _make_archive_ts() -> str:
    """生成 ISO8601 东八区时间戳，如 2026-05-08T17:00:00+0800。"""
    east8 = timezone(timedelta(hours=8))
    return datetime.now(east8).strftime("%Y-%m-%dT%H:%M:%S+0800")


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
# 内部工具：产物路径收集
# ============================================================================

def _collect_artifacts_to_archive(
    run_dir: Path,
    nodes: list[dict[str, Any]],
    run_state: "RunState",
    to_node: str,
) -> list[Path]:
    """收集需要 mv 到 .archived 的产物文件列表。

    策略：to_node 之后（不含 to_node）所有已完成节点的产物目录/文件。
    """
    ordered = _get_ordered_node_ids(nodes)
    to_pos = ordered.index(to_node) if to_node in ordered else -1

    artifacts: list[Path] = []
    # 找 to_node 之后的节点（含当前运行中的）
    nodes_to_archive = ordered[to_pos + 1:] if to_pos >= 0 else []

    for nid in nodes_to_archive:
        # 节点对应的产物目录
        node_dir = run_dir / nid
        if node_dir.is_dir():
            artifacts.append(node_dir)
        # 节点直接产物文件（output.json 等扁平文件）
        for f in run_dir.glob(f"{nid}.*"):
            if f.is_file() and f not in artifacts:
                artifacts.append(f)

    return artifacts


def _collect_sub_run_ids(
    run_dir: Path,
    nodes: list[dict[str, Any]],
    to_node: str,
    repo_root: Path,
) -> list[str]:
    """收集需要级联 mv 的子 run id 列表（跨 sub_workflow 节点时触发）。

    判断依据：to_node 之后存在 sub_workflow 类型节点，且子 run 目录存在。
    """
    ordered = _get_ordered_node_ids(nodes)
    to_pos = ordered.index(to_node) if to_node in ordered else -1
    nodes_after = ordered[to_pos + 1:] if to_pos >= 0 else []

    # 找 sub_workflow 类型节点（在 to_node 之后）
    node_map = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}
    sub_run_ids: list[str] = []

    for nid in nodes_after:
        node_def = node_map.get(nid, {})
        if "sub_workflow" not in node_def:
            continue
        # 找匹配的子 run 目录
        for candidate_dir in [repo_root / "runs", repo_root / "requirements"]:
            if not candidate_dir.is_dir():
                continue
            for child_dir in candidate_dir.iterdir():
                if child_dir.is_dir() and child_dir.name not in sub_run_ids:
                    # 简单启发：子 run 目录内有 run-state.jsonl
                    child_jsonl = child_dir / "run-state.jsonl"
                    if child_jsonl.is_file():
                        # 检查是否引用了父 run（通过 parent_id 字段）
                        # 此处用目录命名约定：<parent_run_id>-<node_id>-<suffix>
                        if run_dir.name in child_dir.name or nid in child_dir.name:
                            sub_run_ids.append(child_dir.name)

    return sub_run_ids


# ============================================================================
# 内部工具：jsonl tail 处理
# ============================================================================

def _truncate_jsonl_to_tail(
    jsonl_path: Path,
    archive_root: Path,
    to_node: str,
    ordered_nodes: list[str],
) -> tuple[Path, list[Any]]:
    """把 jsonl 中 to_node 完成之后的事件 mv 到 archive_root/run-state.jsonl.tail。

    返回：(tail_path, kept_events)
    - tail_path：归档的 tail 文件绝对路径
    - kept_events：保留在原 jsonl 中的事件列表（to_node 完成处及之前）
    """
    if not jsonl_path.is_file():
        # jsonl 不存在时建空 tail
        tail_path = archive_root / "run-state.jsonl.tail"
        tail_path.touch()
        return tail_path, []

    events, _ = read_events(jsonl_path)

    # 找 to_node 的 node_completed 事件位置（最后一次出现）
    cut_idx = _find_jsonl_cut_index(events, to_node)

    kept = events[:cut_idx]
    tail = events[cut_idx:]

    # 先写 tail 文件
    tail_path = archive_root / "run-state.jsonl.tail"
    tail_path.parent.mkdir(parents=True, exist_ok=True)
    import json
    with tail_path.open("w", encoding="utf-8") as fh:
        for evt in tail:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")

    # 重写原 jsonl（只保留 kept 部分）
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for evt in kept:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")

    return tail_path, kept


def _find_jsonl_cut_index(events: list[dict[str, Any]], to_node: str) -> int:
    """找 to_node 的 node_completed 事件之后的第一个位置（即截断点）。

    若找不到 to_node 的 node_completed，则截断点 = 0（全部 mv 为 tail）。
    """
    cut_idx = 0
    for i, evt in enumerate(events):
        if evt.get("type") == "node_completed" and evt.get("node_id") == to_node:
            cut_idx = i + 1  # 保留到 node_completed 本身（含）
    return cut_idx


# ============================================================================
# 内部工具：双层锁
# ============================================================================

def _acquire_dual_lock(
    lock_path: Path,
    in_progress_path: Path,
) -> tuple[Any, int]:
    """获取双层锁：fcntl.flock（LOCK_EX|LOCK_NB） + os.O_EXCL 原子创建 .in_progress。

    返回：(lock_fd_obj, in_progress_fd)
    调用方负责 try/finally 释放。

    层 1：flock 解决并发互斥（失败 → ConcurrentRollbackError）
    层 2：O_EXCL 原子创建 .in_progress 解决崩溃后中间状态识别
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    in_progress_path.parent.mkdir(parents=True, exist_ok=True)

    # 层 1：flock（LOCK_EX|LOCK_NB）
    try:
        lock_fd = open(str(lock_path), "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        # 锁被占用 → ConcurrentRollbackError
        raise ConcurrentRollbackError(
            f"run_id 正在被其他进程 rollback（{lock_path}）：{exc}"
        ) from exc

    # 层 2：O_EXCL 原子创建 .in_progress
    try:
        in_prog_fd = os.open(
            str(in_progress_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o644,
        )
    except OSError as exc:
        # .in_progress 已存在（进程崩溃残留）→ 释放 flock，由续跑逻辑处理
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        raise RollbackInProgressError(
            f".in_progress 标记已存在（{in_progress_path}），"
            f"可能是上次崩溃残留；请重新调用 rollback_run 续跑"
        ) from exc

    return lock_fd, in_prog_fd


def _release_dual_lock(lock_fd: Any, in_progress_path: Path) -> None:
    """释放双层锁：删 .in_progress + 释放 flock。"""
    try:
        if in_progress_path.exists():
            in_progress_path.unlink()
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            lock_fd.close()


# ============================================================================
# 内部工具：续跑检测
# ============================================================================

def _find_in_progress_archive(run_dir: Path) -> Path | None:
    """扫描 run_dir/.archived/ 找带 .in_progress 标记的目录。

    返回带 .in_progress 的 archive_dir，或 None（无残留）。
    """
    archived_root = run_dir / ".archived"
    if not archived_root.is_dir():
        return None
    for ts_dir in sorted(archived_root.iterdir()):
        if not ts_dir.is_dir():
            continue
        if (ts_dir / ".in_progress").exists():
            return ts_dir
    return None


# ============================================================================
# 内部工具：子 run 归档（F1 跨父子）
# ============================================================================

def _archive_sub_run(
    child_run_dir: Path,
    sub_runs_archive_dir: Path,
    run_id: str,
) -> SubRunArchive:
    """把子 run 整目录 mv 到 sub_runs_archive_dir/<child_run_id>/。

    在 mv 前往子 jsonl 追加 parent_rolled_back 事件。
    """
    child_run_id = child_run_dir.name
    child_jsonl = child_run_dir / "run-state.jsonl"

    # 追加 parent_rolled_back 事件（F-002 定义的事件类型）
    try:
        append_event(child_jsonl, {
            "type": "parent_rolled_back",
            "run_id": child_run_id,
            "data": {"parent_run_id": run_id},
        })
    except (WorkflowError, OSError) as exc:
        logger.warning(
            "追加 parent_rolled_back 事件失败（run_id=%s, child=%s）：%s",
            run_id, child_run_id, exc,
        )

    # 统计 jsonl 行数（用于完整性断言）
    jsonl_event_count = _count_jsonl_lines(child_jsonl)

    # mv 子 run 整目录
    sub_runs_archive_dir.mkdir(parents=True, exist_ok=True)
    dest = sub_runs_archive_dir / child_run_id
    shutil.move(str(child_run_dir), str(dest))

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


# ============================================================================
# 内部：产物 mv 执行
# ============================================================================

def _move_artifacts(
    artifacts: list[Path],
    archive_root: Path,
) -> list[Path]:
    """把产物列表 mv 到 archive_root 下（保持相对路径结构）。

    返回已成功 mv 的路径列表。
    """
    moved: list[Path] = []
    for src in artifacts:
        if not src.exists():
            logger.debug("跳过已不存在的产物路径：%s", src)
            continue
        dest = archive_root / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved.append(src)
        logger.debug("mv artifact: %s → %s", src, dest)
    return moved


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
    """
    start_ms = time.monotonic()
    lock_path = run_dir / ".rollback.lock"

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

        # 删 .in_progress
        in_prog = archive_root / ".in_progress"
        if in_prog.exists():
            in_prog.unlink()

        duration_ms = int((time.monotonic() - start_ms) * 1000)
        # 续跑后的下一个节点 = to_node 的下一个（就是 to_node 本身，后续从 to_node 重启）
        new_current_node = _determine_new_current_node(nodes, to_node)
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
    sub_run_ids = _collect_sub_run_ids(run_dir, nodes, to_node, repo_root)
    sub_runs_archive_dir = archive_root / "sub_runs"
    archived: list[SubRunArchive] = []
    for child_id in sub_run_ids:
        for base in [repo_root / "runs", repo_root / "requirements"]:
            child_dir = base / child_id
            if child_dir.is_dir():
                archived.append(
                    _archive_sub_run(child_dir, sub_runs_archive_dir, run_id)
                )
                break
    return archived


def _determine_new_current_node(nodes: list[dict[str, Any]], to_node: str) -> str:
    """rollback 后续跑起点 = to_node 本身（重新从 to_node 开始执行）。"""
    # 设计约定：rollback 到 to_node 后，to_node 重新成为待执行节点
    return to_node


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
        IOError                        — 文件系统操作失败
    """
    start_ms = time.monotonic()

    root = repo_root or REPO_ROOT

    logger.info("rollback_run 开始（run_id=%s, to_node=%s）", run_id, to_node)

    # 1) 解析 run 目录
    try:
        run_dir = _resolve_run_dir(run_id, root)
    except WorkflowError as exc:
        raise RunStateNotFoundError(
            f"run_id={run_id!r} 不存在：{exc}"
        ) from exc

    # 2) 加载 workflow 节点
    nodes = _load_nodes(run_dir)
    all_ids = _all_node_ids(nodes)

    # 3) 校验 to_node 存在
    if to_node not in all_ids:
        raise TargetNodeNotFoundError(
            f"to_node={to_node!r} 不在 workflow 节点集合 {sorted(all_ids)}"
        )

    # 4) 读取当前运行状态
    jsonl_path = run_dir / "run-state.jsonl"
    events, warnings = read_events(jsonl_path)
    run_state = RunState.rebuild(events, run_id=run_id, warnings=warnings)

    # 5) 校验 to_node 是上游
    _validate_to_node_is_upstream(nodes, run_state.current_node, to_node, run_state)

    # 6) 检测 .in_progress 残留（崩溃续跑）
    stale_archive = _find_in_progress_archive(run_dir)
    if stale_archive is not None:
        logger.info(
            "检测到 .in_progress 残留（run_id=%s, archive=%s），执行续跑",
            run_id, stale_archive,
        )
        return _resume_in_progress(
            run_dir, stale_archive, to_node, nodes, run_state, run_id, root
        )

    # 7) 生成时间戳 + 创建 archive 目录
    archive_ts = _make_archive_ts()
    archive_root = run_dir / ".archived" / archive_ts
    archive_root.mkdir(parents=True, exist_ok=True)

    # 8) 双层锁
    lock_path = run_dir / ".rollback.lock"
    in_progress_path = archive_root / ".in_progress"

    lock_fd, in_prog_fd = _acquire_dual_lock(lock_path, in_progress_path)
    os.close(in_prog_fd)  # 文件已创建，fd 不再需要

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
        )
        # 9) mv 完成后删 .in_progress
        in_progress_path.unlink(missing_ok=True)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
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
) -> RollbackResult:
    """执行实际的 rollback 操作（持锁期间调用）。

    拆分到独立方法以控制 rollback_run 主函数行数。
    """
    ordered = _get_ordered_node_ids(nodes)

    # 10) mv jsonl tail
    jsonl_path = run_dir / "run-state.jsonl"
    tail_path, _ = _truncate_jsonl_to_tail(jsonl_path, archive_root, to_node, ordered)

    # 11) 收集 + mv 产物
    artifacts = _collect_artifacts_to_archive(run_dir, nodes, run_state, to_node)
    moved = _move_artifacts(artifacts, archive_root)

    # 12) 跨父子 mv 子 run（F1 场景）
    moved_sub_runs = _execute_sub_run_archive(
        run_dir, nodes, to_node, archive_root, run_id, target_id, root
    )

    duration_ms = int((time.monotonic() - start_ms) * 1000)
    new_current_node = _determine_new_current_node(nodes, to_node)

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

    target_id 指定时只归档该子 run；否则归档所有匹配子 run。
    """
    sub_runs_archive_dir = archive_root / "sub_runs"
    archived: list[SubRunArchive] = []

    # 找 to_node 之后的 sub_workflow 节点
    ordered = _get_ordered_node_ids(nodes)
    to_pos = ordered.index(to_node) if to_node in ordered else -1
    nodes_after = ordered[to_pos + 1:] if to_pos >= 0 else []
    node_map = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}

    for nid in nodes_after:
        node_def = node_map.get(nid, {})
        if "sub_workflow" not in node_def:
            continue

        # 搜索匹配的子 run 目录
        child_dirs = _find_matching_child_run_dirs(nid, run_dir, root, target_id)
        for child_dir in child_dirs:
            archived.append(
                _archive_sub_run(child_dir, sub_runs_archive_dir, run_id)
            )

    return archived


def _find_matching_child_run_dirs(
    node_id: str,
    run_dir: Path,
    root: Path,
    target_id: Optional[str],
) -> list[Path]:
    """找到与 node_id 对应的子 run 目录列表。

    匹配规则（按优先级）：
    1. target_id 指定 → 精确匹配
    2. 子 run 目录内 sub_runs/<node_id>/ 目录（由 run_dir 维护）
    3. sub-run 目录命名约定：run_dir.name + "-" + node_id 前缀
    """
    if target_id:
        # 精确匹配
        for base in [root / "runs", root / "requirements"]:
            candidate = base / target_id
            if candidate.is_dir():
                return [candidate]
        return []

    # 检查 run_dir/sub_runs/<node_id>/ 目录（子 run 目录直接挂在父下）
    sub_runs_dir = run_dir / "sub_runs"
    if sub_runs_dir.is_dir():
        matches = []
        for d in sub_runs_dir.iterdir():
            if d.is_dir():
                matches.append(d)
        if matches:
            return matches

    return []


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
