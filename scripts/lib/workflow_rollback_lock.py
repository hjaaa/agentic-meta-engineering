"""workflow_rollback 锁工具模块（F-007）。

提供双层锁实现 + 续跑助手 + 续跑元数据读写：
- _acquire_flock: 仅获取 fcntl.flock（LOCK_EX|LOCK_NB），返回 fd
- _find_in_progress_archive: 扫描残留 .in_progress 目录（续跑检测）
- _validate_resume_meta: 续跑时校验 .meta.json 中 to_node 与传入一致
- _unlink_in_progress: 删除 .in_progress 标记（失败仅 logger.error）
- _release_with_unlink: flock 释放 + .in_progress 清理统一封装
- _write_meta_json / _read_meta_json: .archived/<ts>/.meta.json 持久化（M-3）
- _now_iso8601: UTC ISO8601 时间戳（_write_meta_json 辅助）

详细设计：requirements/REQ-2026-009/artifacts/detailed-design.md §6.4
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# 延迟导入以避免循环：异常类从主模块导入
def _get_exceptions():
    """惰性获取循环依赖异常类，避免 lock 子模块 import workflow_rollback 主模块时的循环。"""
    from workflow_rollback import ConcurrentRollbackError, RollbackInProgressError
    return ConcurrentRollbackError, RollbackInProgressError


def _acquire_flock(lock_path: Path) -> Any:
    """获取 fcntl.flock（LOCK_EX|LOCK_NB），返回 lock_fd 文件对象。

    失败（锁被占用）→ 抛 ConcurrentRollbackError。
    调用方负责 try/finally 释放（fcntl.flock(lock_fd, LOCK_UN) + lock_fd.close()）。

    H-2 修复：lock_fd 在 try 块外 open，flock 失败时在 except 内显式 close，
    防止 OSError 分支下 fd 泄漏。
    """
    ConcurrentRollbackError, _ = _get_exceptions()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(str(lock_path), "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        lock_fd.close()
        raise ConcurrentRollbackError(
            f"run_id 正在被其他进程 rollback（{lock_path}）"
        ) from exc
    return lock_fd


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


def _validate_resume_meta(meta: dict[str, Any] | None, to_node: str) -> str:
    """验证续跑时 .meta.json 中记录的 to_node 与调用方传入的 to_node 是否一致。

    三分支：
    - meta 为 None：.meta.json 缺失，fallback 到调用方 to_node（记 warning）
    - meta_to_node ≠ to_node：不一致 → 抛 RollbackResumeMismatchError
    - meta_to_node == to_node（或 None）：返回最终有效 to_node

    H-6 helper：抽出，将 _resume_in_progress 的 meta 验证三分支集中到此。
    F-21 重构：从 workflow_rollback.py 下沉至本锁子模块。
    """
    # 惰性导入异常以避免主模块循环依赖
    from workflow_rollback import RollbackResumeMismatchError

    if meta is None:
        # 由调用方 logger.warning；这里仅返回 fallback 值
        return to_node
    meta_to_node = meta.get("to_node")
    if meta_to_node is not None and meta_to_node != to_node:
        raise RollbackResumeMismatchError(
            f"续跑 to_node 不一致：.meta.json 记录 {meta_to_node!r}，"
            f"调用方传入 {to_node!r}；请使用 {meta_to_node!r} 续跑"
        )
    return meta_to_node if meta_to_node is not None else to_node


def _unlink_in_progress(in_progress_path: Path) -> None:
    """删除 .in_progress 标记；失败仅 logger.error 不抛，让原始异常继续传播。

    F-15 helper：消 _execute_with_in_progress 内联 6 行冗余，与 _release_with_unlink 共用。
    """
    try:
        if in_progress_path.exists():
            in_progress_path.unlink()
    except OSError as exc:
        logger.error(
            ".in_progress 删除失败（path=%s）：%s — 需手动清理或等待下次 rollback 续跑兜底",
            in_progress_path, exc,
        )


def _release_with_unlink(lock_fd: Any, in_progress_path: Path) -> None:
    """获取/释放 flock + 删除 .in_progress 标记的统一封装。

    unlink 由 _unlink_in_progress 独立处理可被 _execute_with_in_progress 复用；
    本函数串联两职责（先 unlink，后 flock 释放）。

    H-6 helper / H-1a + H-1b 修复 / F-15 拆分：
    - 先调 _unlink_in_progress（失败 logger.error 不抛）
    - 再 fcntl.flock(LOCK_UN) + lock_fd.close()
    - 让原始异常继续传播
    F-21 重构：从 workflow_rollback.py 下沉至本锁子模块。
    """
    _unlink_in_progress(in_progress_path)
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    lock_fd.close()


# F-15 重构（rev6）：续跑元数据读写从主模块下沉
# 与锁/标记同一职责域；主模块通过 from workflow_rollback_lock import 调用


def _now_iso8601() -> str:
    """返回当前 UTC ISO8601 时间戳。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_meta_json(archive_root: Path, run_id: str, to_node: str) -> None:
    """写 .archived/<ts>/.meta.json（atomic: tmp fsync → os.replace），持久化续跑上下文。

    H-7 修复：os.replace 失败时清理孤儿 .meta.json.tmp，防止残留临时文件。
    """
    meta = {"run_id": run_id, "to_node": to_node, "started_at": _now_iso8601()}
    meta_path = archive_root / ".meta.json"
    tmp_path = archive_root / ".meta.json.tmp"
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.replace(tmp_path, meta_path)  # POSIX 原子 rename
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as ue:
            # F-16：tmp 清理失败（仅 logger.warning，让原 OSError 继续传播）
            logger.warning(".meta.json.tmp 清理失败（path=%s）：%s", tmp_path, ue)
        raise


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
