"""workflow_rollback 锁工具模块（F-007）。

提供双层锁实现 + 续跑助手：
- _acquire_flock: 仅获取 fcntl.flock（LOCK_EX|LOCK_NB），返回 fd
- _acquire_dual_lock: flock + O_EXCL .in_progress（首次 rollback）
- _release_dual_lock: 释放 flock（内部使用）
- _find_in_progress_archive: 扫描残留 .in_progress 目录（续跑检测）
- _validate_resume_meta: 续跑时校验 .meta.json 中 to_node 与传入一致
- _unlink_in_progress: 删除 .in_progress 标记（失败仅 logger.error）
- _release_with_unlink: flock 释放 + .in_progress 清理统一封装

详细设计：requirements/REQ-2026-009/artifacts/detailed-design.md §6.4
"""
from __future__ import annotations

import fcntl
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# 延迟导入以避免循环：异常类从主模块导入
def _get_exceptions():
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


def _acquire_dual_lock(
    lock_path: Path,
    in_progress_path: Path,
) -> tuple[Any, int]:
    """获取双层锁：先 flock，再 O_EXCL 原子创建 .in_progress。

    返回：(lock_fd_obj, in_progress_fd)
    调用方负责 try/finally 释放（见 _release_dual_lock）。

    层 1：flock 解决并发互斥（失败 → ConcurrentRollbackError）
    层 2：O_EXCL 原子创建 .in_progress 解决崩溃后中间状态识别
    （失败 = .in_progress 已存在 → RollbackInProgressError，触发续跑）
    """
    ConcurrentRollbackError, RollbackInProgressError = _get_exceptions()

    # 层 1：先获取 flock（§6.4：flock 在 mkdir 之前）
    lock_fd = _acquire_flock(lock_path)

    # 层 2：O_EXCL 原子创建 .in_progress（.in_progress 所在 archive_root 由调用方已 mkdir）
    in_progress_path.parent.mkdir(parents=True, exist_ok=True)
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


def _release_dual_lock(lock_fd: Any) -> None:
    """释放 flock（lock_fd）。

    注意：.in_progress 的 unlink 由调用方在 finally 中处理（M-2 修复）。
    此函数仅负责 flock 释放，确保 lock_fd 一定关闭。
    """
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        lock_fd.close()


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
