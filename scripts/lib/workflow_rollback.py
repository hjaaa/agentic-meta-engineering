"""workflow rollback 命令（F-007）。

公开 API：
    rollback_run(run_id, to_node, target_id=None, repo_root=None) → RollbackResult

功能：
- 拓扑序找产物路径集合 → shutil.move 到 .archived/<ts>/
- 父 run 跨 sub_workflow 节点时，递归 mv 子 run 整目录
- 写 .in_progress atomic 标记保护中断
- 截断 jsonl 尾部 mv 为 <archived>/run-state.jsonl.tail
- 双层锁：§6.4 顺序 = flock → mkdir → O_EXCL，flock 先行
- .archived/<ts>/.meta.json 持久化 run_id/to_node/started_at，续跑读取

本文件保留：公开 API + dataclass + 异常 + CLI 入口
子模块职责：
  workflow_rollback_lock.py     — 双层锁 _acquire/_release/_find_in_progress
  workflow_rollback_archive.py  — _collect/_move/_truncate_jsonl
  workflow_rollback_subrun.py   — _discover_sub_runs + _archive_sub_run
  workflow_rollback_topology.py — yaml 加载 / 拓扑工具

详细设计：requirements/REQ-2026-009/artifacts/detailed-design.md §6.1~§6.7
"""
from __future__ import annotations

import fcntl
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError  # noqa: E402
from run_state import RunState, _resolve_run_dir, read_events  # noqa: E402

logger = logging.getLogger(__name__)

# 数据结构


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


# 异常体系

class RollbackError(WorkflowError):
    """Rollback 通用基类异常。

    本类直接用于参数校验失败 / 资源清理失败等无独立子类语义的场景；
    具体的失败子类见 RunStateNotFoundError / TargetNodeNotFoundError /
    TargetNodeNotUpstreamError / ConcurrentRollbackError /
    RollbackInProgressError / RollbackResumeMismatchError。
    """


class RunStateNotFoundError(RollbackError):
    """run_id 在两条路径都查不到 run 目录。"""


class TargetNodeNotFoundError(RollbackError):
    """to_node 不在 run 对应 yaml 节点 ID 集合。"""


class TargetNodeNotUpstreamError(RollbackError):
    """to_node 不是当前节点的拓扑上游（或就是当前节点本身）。"""


class ConcurrentRollbackError(RollbackError):
    """runs/<id>/.rollback.lock 已被持有（fcntl.flock 失败）。"""


class RollbackInProgressError(RollbackError):
    """.archived/<ts>/.in_progress 残留（中断未续跑前禁止新 rollback）。"""


class RollbackResumeMismatchError(RollbackError):
    """.meta.json 中记录的 to_node 与调用方传入的 to_node 不一致。"""


# 内部工具：时间戳

def _make_archive_ts() -> str:
    """生成 ISO8601 东八区时间戳，如 2026-05-08T17:00:00+0800。"""
    east8 = timezone(timedelta(hours=8))
    return datetime.now(east8).strftime("%Y-%m-%dT%H:%M:%S+0800")


# F-15 重构（rev6）：_read_meta_json + _write_meta_json + _now_iso8601
# 下沉至 workflow_rollback_lock.py（语义相符——续跑元数据读写与锁/标记同一职责域）；
# 主模块 import 它们以保持公开函数签名不变。


# 内部：校验链 + archive 准备

def _resolve_and_validate(
    run_id: str,
    to_node: str,
    root: Path,
) -> tuple[Path, list[dict[str, Any]], RunState, list[dict[str, Any]]]:
    """步骤 1-5：校验 run_id/to_node，读 jsonl 状态，校验拓扑上游。返回 (run_dir, nodes, run_state, events)。"""
    from workflow_rollback_topology import (
        _all_node_ids,
        _load_nodes,
        _validate_to_node_is_upstream,
    )

    if not re.fullmatch(r"[A-Za-z0-9_\-]+", run_id):
        raise RollbackError(f"run_id 包含非法字符（只允许 [A-Za-z0-9_\\-]）：{run_id!r}")

    try:
        run_dir = _resolve_run_dir(run_id, root)
    except WorkflowError as exc:
        raise RunStateNotFoundError(f"run_id={run_id!r} 不存在：{exc}") from exc

    nodes = _load_nodes(run_dir)
    all_ids = _all_node_ids(nodes)
    if to_node not in all_ids:
        raise TargetNodeNotFoundError(
            f"to_node={to_node!r} 不在 workflow 节点集合 {sorted(all_ids)}"
        )

    # M-12：传 events 给后续调用方，避免双读 jsonl
    jsonl_path = run_dir / "run-state.jsonl"
    events, warnings = read_events(jsonl_path)
    run_state = RunState.rebuild(events, run_id=run_id, warnings=warnings)

    _validate_to_node_is_upstream(nodes, run_state.current_node, to_node, run_state)
    return run_dir, nodes, run_state, events


def _setup_archive(run_dir: Path) -> tuple[Path, str]:
    """生成时间戳 + 创建 archive 目录（持锁后调用，符合 §6.4 flock → mkdir → O_EXCL）。"""
    archive_ts = _make_archive_ts()
    archive_root = run_dir / ".archived" / archive_ts
    archive_root.mkdir(parents=True, exist_ok=True)
    return archive_root, archive_ts


# 内部：执行层

def _execute_rollback(
    run_dir: Path,
    archive_root: Path,
    archive_ts: str,
    nodes: list[dict[str, Any]],
    run_state: RunState,
    to_node: str,
    run_id: str,
    target_id: Optional[str],
    root: Path,
    start_ms: float,
    events: list[dict[str, Any]] | None = None,
) -> RollbackResult:
    """执行实际的 rollback 操作（持锁期间调用）。"""
    from workflow_rollback_archive import (
        _collect_artifacts_to_archive,
        _move_artifacts,
        _truncate_jsonl_to_tail,
    )
    from workflow_rollback_subrun import _archive_sub_run, _discover_sub_runs
    from workflow_rollback_topology import _get_ordered_node_ids

    ordered = _get_ordered_node_ids(nodes)

    # mv jsonl tail（M-12：传入已解析的 events，避免双读）
    jsonl_path = run_dir / "run-state.jsonl"
    tail_path, _ = _truncate_jsonl_to_tail(jsonl_path, archive_root, to_node, ordered, events)

    # 收集 + mv 产物
    artifacts = _collect_artifacts_to_archive(run_dir, nodes, run_state, to_node)
    moved = _move_artifacts(artifacts, archive_root)

    # 跨父子 mv 子 run（F1 场景）
    to_pos = ordered.index(to_node) if to_node in ordered else -1
    nodes_after = ordered[to_pos + 1:] if to_pos >= 0 else []
    node_map = _build_node_map(nodes)
    child_dirs = _discover_sub_runs(run_dir, nodes_after, root, node_map, target_id)
    sub_runs_archive_dir = archive_root / "sub_runs"
    moved_sub_runs = [
        _archive_sub_run(child_dir, sub_runs_archive_dir, run_id)
        for child_dir in child_dirs
    ]

    duration_ms = int((time.monotonic() - start_ms) * 1000)
    return RollbackResult(
        run_id=run_id,
        archive_ts=archive_ts,
        archive_root=archive_root,
        moved_artifacts=moved,
        moved_sub_runs=moved_sub_runs,
        truncated_jsonl_tail=tail_path,
        new_current_node=to_node,
        duration_ms=duration_ms,
        partial=False,
    )


def _build_node_map(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """构造 nid -> node 字典；过滤非 dict 或缺 id 的项。

    F-20 helper：在 _resume_in_progress / _execute_rollback 中统一构造，
    把 dict comprehension + isinstance/含 id 过滤集中到一处。
    """
    return {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}


def _consume_residual_new(jsonl_path: Path) -> None:
    """续跑兜底 archive 端三步原子化的中间态：检测残留 .new 并 os.replace 收尾。

    F-2 修复（rev6）：archive 端顺序 = .new 写完 → tail 写完 → os.replace(.new, jsonl)。
    KI 落第 2 步完成后第 3 步前：tail 已存在 + .new 仍在 + jsonl 未截断。
    此时若 _resume_in_progress 仅判 tail_path.exists() 会跳过整个 truncate
    → .new 永不消费、jsonl 永不截断、下游误认节点完成。
    抽出独立 helper 既隔离 F-2 修复语义，也降 _resume_in_progress 主体 CC。

    Args:
        jsonl_path: 主 jsonl 路径（archive_root/run-state.jsonl 或 sub run 同名）

    Returns:
        None。无 .new 残留时直接返回；否则 os.replace(.new, jsonl) 收尾。

    Raises:
        RollbackError: os.replace 失败时包装抛出（含 new_path / jsonl_path 上下文）
    """
    new_path = jsonl_path.with_suffix(jsonl_path.suffix + ".new")
    if new_path.exists():
        logger.warning(
            "检测到残留 .new（archive 端 KI 落第 2 步），os.replace 续跑：%s → %s",
            new_path, jsonl_path,
        )
        try:
            os.replace(str(new_path), str(jsonl_path))
        except OSError as exc:
            raise RollbackError(
                f"residual .new 收尾失败（new_path={new_path}, jsonl_path={jsonl_path}）：{exc}"
            ) from exc


def _resume_in_progress(
    run_dir: Path,
    stale_archive_dir: Path,
    to_node: str,
    nodes: list[dict[str, Any]],
    run_state: RunState,
    run_id: str,
    repo_root: Path,
) -> RollbackResult:
    """续跑：持锁后读 .meta.json 验证 to_node，完成剩余 mv，删 .in_progress，返回 partial=True。

    H-6 重构：CC 从 14 降至 ≤ 10，抽出 _validate_resume_meta + _release_with_unlink helpers。
    F-20 重构：_build_node_map 抽 helper，CC 从 12 → 9。
    F-21 重构：_validate_resume_meta + _release_with_unlink 下沉至 _lock 子模块。
    F-23 重构：成功路径调 _release_with_unlink（含 unlink + flock 释放）；
    异常路径只释放 flock 不删 .in_progress（保留供下次启动续跑兜底）。
    """
    from workflow_rollback_archive import (
        _collect_artifacts_to_archive,
        _move_artifacts,
        _truncate_jsonl_to_tail,
    )
    from workflow_rollback_lock import (
        _acquire_flock,
        _read_meta_json,
        _release_with_unlink,
        _validate_resume_meta,
    )
    from workflow_rollback_subrun import _archive_sub_run, _discover_sub_runs
    from workflow_rollback_topology import _get_ordered_node_ids

    start_ms = time.monotonic()
    in_prog = stale_archive_dir / ".in_progress"

    # G-1 修复：先 acquire flock，再读 .meta.json（持锁后读，防并发覆盖）
    lock_fd = _acquire_flock(run_dir / ".rollback.lock")
    try:
        meta = _read_meta_json(stale_archive_dir)
        if meta is None:
            logger.warning(
                "续跑：.meta.json 缺失（run_id=%s, archive=%s），fallback 到调用方 to_node=%s",
                run_id, stale_archive_dir, to_node,
            )
        to_node = _validate_resume_meta(meta, to_node)

        archive_root = stale_archive_dir
        artifacts = _collect_artifacts_to_archive(run_dir, nodes, run_state, to_node)
        moved = _move_artifacts([a for a in artifacts if a.exists()], archive_root)

        jsonl_path = run_dir / "run-state.jsonl"
        tail_path = archive_root / "run-state.jsonl.tail"
        ordered = _get_ordered_node_ids(nodes)
        _consume_residual_new(jsonl_path)
        if not tail_path.exists():
            tail_path, _ = _truncate_jsonl_to_tail(jsonl_path, archive_root, to_node, ordered)

        to_pos = ordered.index(to_node) if to_node in ordered else -1
        nodes_after = ordered[to_pos + 1:] if to_pos >= 0 else []
        node_map = _build_node_map(nodes)
        child_dirs = _discover_sub_runs(run_dir, nodes_after, repo_root, node_map)
        sub_runs_archive_dir = archive_root / "sub_runs"
        sub_runs_done = [
            _archive_sub_run(child_dir, sub_runs_archive_dir, run_id)
            for child_dir in child_dirs
            if child_dir.is_dir()
        ]

        archive_ts = archive_root.name
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        logger.info(
            "rollback 续跑完成（run_id=%s, to_node=%s, archive_ts=%s, duration_ms=%d）",
            run_id, to_node, archive_ts, duration_ms,
        )
        result = RollbackResult(
            run_id=run_id,
            archive_ts=archive_ts,
            archive_root=archive_root,
            moved_artifacts=moved,
            moved_sub_runs=sub_runs_done,
            truncated_jsonl_tail=tail_path,
            new_current_node=to_node,
            duration_ms=duration_ms,
            partial=True,
        )
        # F-23：成功路径删 .in_progress + 释放 flock（KI/SIGINT 中途异常会跳过此处，
        # .in_progress 保留供下次启动 _find_in_progress_archive 续跑兜底）
        _release_with_unlink(lock_fd, in_prog)
        return result
    except BaseException:
        # 异常路径：仅释放 flock，不删 .in_progress
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            lock_fd.close()
        raise


def _execute_with_in_progress(
    in_progress_path: Path,
    run_dir: Path,
    archive_root: Path,
    archive_ts: str,
    nodes: list[dict[str, Any]],
    run_state: RunState,
    to_node: str,
    run_id: str,
    target_id: Optional[str],
    root: Path,
    start_ms: float,
    events: list[dict[str, Any]] | None,
) -> RollbackResult:
    """合并 .in_progress 文件管理 + _execute_rollback 调用（G-12 提取）。

    G-1：_write_meta_json 在成功路径调用；异常时由外层 rollback_run finally 释放 flock，
    .in_progress 保留供续跑兜底（F-23 修正：unlink 仅在 mv 完成后调用，
    KI/SIGINT 异常时跳过）。
    F-15 重构：unlink 内联 6 行替换为 _unlink_in_progress helper（与 _release_with_unlink 共用）。
    F-23 重构：unlink 从 finally 挪到 try 块成功路径（KI/SIGINT 中途异常 → .in_progress
    保留，对齐 detailed-design §6.4 line 859 伪码"mv 完成后删标记"的语义）。
    """
    from workflow_rollback_lock import _unlink_in_progress, _write_meta_json

    _write_meta_json(archive_root, run_id, to_node)
    result = _execute_rollback(
        run_dir=run_dir, archive_root=archive_root, archive_ts=archive_ts,
        nodes=nodes, run_state=run_state, to_node=to_node,
        run_id=run_id, target_id=target_id, root=root,
        start_ms=start_ms, events=events,
    )
    # 仅成功路径走到这里删 .in_progress；任何中途异常（mv 失败 / KI / SIGINT）
    # 跳过 unlink，下次 rollback_run 启动时由 _find_in_progress_archive 检测并续跑
    _unlink_in_progress(in_progress_path)
    return result


# 公开 API

def rollback_run(
    run_id: str,
    to_node: str,
    target_id: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> RollbackResult:
    """把 run_id 从当前节点回滚到 to_node。

    repo_root: testability hatch；生产为 None 时用 REPO_ROOT。
    target_id: 跨父子 rollback 时精确指定子 run id；缺省自动级联所有子 run。
    异常见各 RollbackError 子类 docstring。
    """
    from workflow_rollback_lock import _acquire_flock, _find_in_progress_archive

    start_ms = time.monotonic()
    root = repo_root or REPO_ROOT

    if target_id is not None and not re.fullmatch(r"[A-Za-z0-9_\-]+", target_id):
        raise RollbackError(f"target_id 包含非法字符（只允许 [A-Za-z0-9_\\-]）：{target_id!r}")
    # F-13：to_node 公开 API 入口校验（与 run_id / target_id 对称，堵日志注入路径）
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", to_node):
        raise RollbackError(f"to_node 包含非法字符（只允许 [A-Za-z0-9_\\-]）：{to_node!r}")

    logger.info("rollback_run 开始（run_id=%s, to_node=%s）", run_id, to_node)
    run_dir, nodes, run_state, events = _resolve_and_validate(run_id, to_node, root)

    stale_archive = _find_in_progress_archive(run_dir)
    if stale_archive is not None:
        logger.info("检测到 .in_progress 残留（run_id=%s, archive=%s），执行续跑", run_id, stale_archive)
        return _resume_in_progress(run_dir, stale_archive, to_node, nodes, run_state, run_id, root)

    # §6.4 锁顺序：flock → mkdir → O_EXCL
    lock_fd = _acquire_flock(run_dir / ".rollback.lock")
    try:
        archive_root, archive_ts = _setup_archive(run_dir)
        in_progress_path = archive_root / ".in_progress"
        try:
            in_prog_fd = os.open(str(in_progress_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except OSError as exc:
            raise RollbackInProgressError(
                f".in_progress 标记已存在（{in_progress_path}），"
                f"可能是上次崩溃残留；请重新调用 rollback_run 续跑"
            ) from exc
        os.close(in_prog_fd)
        result = _execute_with_in_progress(
            in_progress_path=in_progress_path, run_dir=run_dir,
            archive_root=archive_root, archive_ts=archive_ts,
            nodes=nodes, run_state=run_state, to_node=to_node,
            run_id=run_id, target_id=target_id, root=root,
            start_ms=start_ms, events=events,
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    logger.info(
        "rollback_run 完成（run_id=%s, to_node=%s, archive_ts=%s, duration_ms=%d）",
        run_id, to_node, archive_ts, result.duration_ms,
    )
    return result


# CLI 入口

def main(args: list[str] | None = None, repo_root: Path | None = None) -> int:
    """CLI 入口：python3 scripts/lib/workflow_rollback.py <run_id> <to_node> [--target-id=<id>]。"""
    import argparse

    parser = argparse.ArgumentParser(description="回滚 workflow run 到指定节点")
    parser.add_argument("run_id", help="目标 run id")
    parser.add_argument("to_node", help="回滚到的节点 id（必须是上游节点）")
    parser.add_argument("--target-id", dest="target_id", default=None,
                        help="指定子 run id（跨父子场景）")
    parsed = parser.parse_args(args or sys.argv[1:])

    for name, value in [("run_id", parsed.run_id), ("to_node", parsed.to_node)]:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", value):
            print(f"ERROR: {name} 包含非法字符：{value!r}", file=sys.stderr)
            return 1
    if parsed.target_id is not None and not re.fullmatch(r"[A-Za-z0-9_\-]+", parsed.target_id):
        print(f"ERROR: target_id 包含非法字符：{parsed.target_id!r}", file=sys.stderr)
        return 1

    try:
        result = rollback_run(
            parsed.run_id, parsed.to_node,
            target_id=parsed.target_id, repo_root=repo_root,
        )
        print("✓ rollback 完成")
        print(f"  run_id:          {result.run_id}")
        print(f"  archive_ts:      {result.archive_ts}")
        print(f"  archive_root:    {result.archive_root}")
        print(f"  moved_artifacts: {len(result.moved_artifacts)} 个")
        print(f"  moved_sub_runs:  {len(result.moved_sub_runs)} 个子 run")
        print(f"  new_current_node: {result.new_current_node}")
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
