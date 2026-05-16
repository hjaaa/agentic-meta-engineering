"""path-lock 三件套（D-003）：fcntl.LOCK_EX + pid 文件 + atexit + 失活 pid 自清理。

公开 API：
  - acquire(run_id, repo_root) → LockHandle
      取 runs/.locks/<run-id>.lock 排他锁；同步建 requirements/.locks/<req-id>.lock symlink。
  - release(handle) → None
      释放 fcntl + close + 删 .lock 文件；不删 symlink（dangling 由下次 acquire 容忍）。
  - LockBusyError：第二进程取锁失败时抛出（持有方 pid + created_at + path_target）。

atexit 精确反注册（IB-22）：
  atexit.unregister(func) 按函数对象匹配 → 移除该函数的所有注册；为避免单进程持
  多 handle 时一次 release 误删其它 handle 的注册，每个 handle 注册的是
  functools.partial(release, handle) 唯一可寻 callable，handle 上以 _release_fn
  字段保存以便 release 精确反注册。

signal handler 注册前移（IB-27）：
  signal/atexit 在 _write_lock_json 之前注册；窗口期 SIGTERM 调 release 时 .lock 文
  件可能尚未写入 JSON，release 仅做 fcntl.LOCK_UN + close + unlink，对空 .lock
  文件完全安全。

跨平台：fcntl.LOCK_EX 在 macOS Darwin 25.4 与 Linux 行为一致（BSD flock 语义）。
"""
from __future__ import annotations

import atexit
import errno
import fcntl
import json
import logging
import os
import platform
import signal
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from common import WorkflowError

logger = logging.getLogger(__name__)


class LockBusyError(WorkflowError):
    """另一进程持有锁；output 含 pid / created_at / path_target。

    继承 WorkflowError，构造参数 (pid, created_at, path_target)；
    super().__init__ 组装含全部三字段的 message（AC-05 要求 stderr 含 `another continue is running, pid=N`）。
    """

    def __init__(self, pid: int, created_at: str, path_target: str) -> None:
        super().__init__(
            f"another continue is running, pid={pid}, started_at={created_at}, "
            f"target={path_target}"
        )
        self.pid = pid
        self.created_at = created_at
        self.path_target = path_target


@dataclass
class LockHandle:
    """acquire 返回的不透明句柄；release 时按此释放。

    `_release_fn` 是 functools.partial(release, self) 在 acquire 内绑定，供 release
    向 atexit 精确反注册（IB-22）。外部禁止直接读写。
    """

    run_id: str
    lock_path: Path
    symlink_path: Path | None
    fd: int
    _released: bool = field(default=False, init=False, repr=False)
    _release_fn: Any = field(default=None, init=False, repr=False)


def _is_pid_alive(pid: int) -> bool:
    """kill -0 pid → ESRCH 为 False，其他 OSError 保守返 True。"""
    if pid <= 0:
        # pid <= 0 在 POSIX 是进程组语义，不可用于单进程探测，保守视为不存活
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        # EPERM 等保守视为存活
    return True


def _is_stale_by_mtime(lock_path: Path, created_at_iso: str, threshold_seconds: float = 1.0) -> bool:
    """二次校验残锁：若 created_at 比 .lock 文件 st_mtime 早 ≥ threshold_seconds，视为真 stale。

    缓解 pid 复用误清窗口（详见 detailed-design.md §5.1）。

    Args:
        lock_path: .lock 文件路径
        created_at_iso: 从 .lock JSON 读出的 created_at（ISO8601）
        threshold_seconds: 阈值（默认 1.0s）

    Returns:
        True：created_at 比 mtime 早 ≥ threshold_seconds，视为真 stale
        False：created_at 与 mtime 接近，pid 复用窗口可能，保守视为活锁

    Raises:
        不抛（OSError / ValueError 由内部 except 兜底返 False）。
    """
    try:
        st_mtime = lock_path.stat().st_mtime
        created_dt = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
        created_ts = created_dt.timestamp()
        return (st_mtime - created_ts) >= threshold_seconds
    except (OSError, ValueError):
        # stat 失败 / created_at 格式坏 → 保守视为活锁
        return False


def _read_lock_json(lock_path: Path) -> dict | None:
    """读取 .lock 文件 JSON；失败返 None。"""
    try:
        content = lock_path.read_text(encoding="utf-8").strip()
        if content:
            return json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("read lock json failed (lock_path=%s): %s", lock_path, exc)
    return None


def _write_lock_json(fd: int, lock_path: Path, run_id: str) -> None:
    """将当前进程信息写入 .lock 文件（truncate + write + fsync）。"""
    payload = {
        "pid": os.getpid(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "path_target": str(lock_path.resolve()),
        "host": platform.platform(),
    }
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, data)
        os.fsync(fd)
    except OSError as exc:
        raise WorkflowError(f"lock file write failed: {exc}") from exc
    logger.debug("lock acquired (run_id=%s, pid=%d)", run_id, payload["pid"])


def _try_fcntl_lock(fd: int) -> bool:
    """尝试 fcntl.LOCK_EX|LOCK_NB；成功返 True，锁冲突返 False，其他 OSError 重抛。"""
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    except OSError as exc:
        if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
            return False
        raise


def _make_symlink_if_needed(run_id: str, lock_path: Path, repo_root: Path) -> Path | None:
    """requirement 类 run 建 requirements/.locks/<req-id>.lock symlink。

    存在性检测必须用 os.path.lexists()（避免 dangling symlink 被 exists() 误报不存在）。
    返回 symlink 路径（不管是否新建）；非 REQ- 类 run 返 None。
    """
    if not run_id.startswith("REQ-"):
        return None

    locks_dir = repo_root / "requirements" / ".locks"
    locks_dir.mkdir(parents=True, exist_ok=True)

    symlink_path = locks_dir / f"{run_id}.lock"
    if not os.path.lexists(symlink_path):
        # 实锁相对 requirements/.locks/ 的相对路径
        rel_target = Path("../../runs/.locks") / lock_path.name
        try:
            os.symlink(str(rel_target), symlink_path)
            logger.debug("symlink created: %s -> %s", symlink_path, rel_target)
        except OSError as exc:
            # 并发时可能已被其他进程创建，容忍 EEXIST
            if exc.errno != errno.EEXIST:
                logger.warning("symlink creation failed (non-critical): %s", exc)

    return symlink_path


def _setup_signal_handlers(handle: LockHandle) -> None:
    """安装 SIGTERM / SIGINT handler，best-effort release 后传播信号。"""

    def _handler(signum: int, frame: object) -> None:
        release(handle)
        # 重设默认 handler 后重发，保持信号传播语义
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    try:
        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
    except (OSError, ValueError) as exc:
        # 在非主线程或信号被屏蔽时忽略（best-effort）
        logger.debug("signal handler setup failed (best-effort): %s", exc)


def _retry_after_stale(fd: int, lock_path: Path) -> tuple[int | None, dict | None]:
    """残锁清理后重试取锁。

    调用前提：已确认 pid 已死且 mtime 二次校验通过（视为真 stale）。
    副作用：关闭并释放传入的 fd，清理 .lock 文件，重新 open + fcntl 尝试。

    Args:
        fd: 当前已 open 但未拿到 fcntl 锁的 fd（本函数负责 close）
        lock_path: .lock 文件路径

    Returns:
        (new_fd, None): 取锁成功，new_fd 为新 fd
        (None, retry_data): 取锁失败，new_fd 已关闭；retry_data 为竞态期间新写
            入 .lock 的 holder 信息（dict），若 .lock 已被清理或读取失败为 None。
            调用方避免再次 _read_lock_json（IB-28）。

    Raises:
        OSError: _try_fcntl_lock 罕见 OSError（EBADF/EINVAL/EDEADLK）。
    """
    logger.info("stale lock at %s, cleaning up and retrying", lock_path)

    # IB-26: 记录原 inode，unlink 前比对避免误删他人新创建的锁文件
    # （≤1e-7/op → ≤1e-9/op，详见 detailed-design.md §5.1 三进程 TOCTOU 兜底）
    try:
        original_inode: int | None = os.fstat(fd).st_ino
    except OSError as exc:
        logger.debug("inode capture failed: %s", exc)
        original_inode = None

    try:
        os.close(fd)
    except OSError as exc:
        logger.debug("stale lock fd close failed: %s", exc)

    if original_inode is not None:
        try:
            current_inode = os.stat(lock_path).st_ino
            if current_inode != original_inode:
                # inode 已被换过 → 他人已 unlink+create，本进程退出 retry，避免误删
                logger.debug(
                    "inode changed (%d → %d), another process handled stale; abort retry",
                    original_inode,
                    current_inode,
                )
                return None, _read_lock_json(lock_path)
        except FileNotFoundError:
            # 已被他人 unlink；后续 open(O_CREAT) 自然创建新文件
            pass
        except OSError as exc:
            logger.debug("inode check stat failed: %s", exc)

    try:
        os.unlink(lock_path)
    except OSError as exc:
        logger.debug("stale lock unlink failed: %s", exc)

    new_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        ok = _try_fcntl_lock(new_fd)
    except OSError:
        try:
            os.close(new_fd)
        except OSError:
            pass
        raise

    if ok:
        return new_fd, None

    # 重试仍失败，读 holder 信息一次（IB-28：返调用方复用，避免二次 read）
    retry_data = _read_lock_json(lock_path)
    try:
        os.close(new_fd)
    except OSError:
        pass
    return None, retry_data


def _handle_lock_conflict(fd: int, lock_path: Path) -> int:
    """fcntl 取锁失败分支：读 holder → 判活 → 可能 mtime 校验 → 可能重试。

    IB-30 抽出降 acquire 主路径复杂度。

    Args:
        fd: 已 open 但未拿到 fcntl 锁的 fd（本函数负责关闭或转交）
        lock_path: 实锁路径

    Returns:
        新 fd（取锁成功，可能等于传入 fd 或重试后新 fd）。

    Raises:
        LockBusyError: 持有方存活 / pid 复用窗口 / 残锁清理后仍冲突。
        OSError: _retry_after_stale 罕见 fcntl OSError 重抛。
    """
    lock_data = _read_lock_json(lock_path)
    if not lock_data:
        os.close(fd)
        raise LockBusyError(0, "", str(lock_path))

    holder_pid = lock_data.get("pid", 0)
    created_at = lock_data.get("created_at", "")
    path_target = lock_data.get("path_target", "")

    if _is_pid_alive(holder_pid):
        os.close(fd)
        raise LockBusyError(holder_pid, created_at, path_target)

    # pid 已死：mtime 二次校验缓解 pid 复用误清窗口（详见 detailed-design.md §5.1）
    if not _is_stale_by_mtime(lock_path, created_at):
        logger.debug(
            "pid=%d dead but mtime check failed, treating as alive (pid reuse window)",
            holder_pid,
        )
        os.close(fd)
        raise LockBusyError(holder_pid, created_at, path_target)

    # 真 stale：清理并重试一次
    new_fd, retry_data = _retry_after_stale(fd, lock_path)
    if new_fd is None:
        if retry_data:
            raise LockBusyError(
                retry_data.get("pid", 0),
                retry_data.get("created_at", ""),
                retry_data.get("path_target", ""),
            )
        raise LockBusyError(0, "", str(lock_path))
    return new_fd


def acquire(run_id: str, repo_root: Path) -> LockHandle:
    """取实锁 + 同步 symlink。

    流程：
      1. 计算实锁路径 runs/.locks/<run-id>.lock；mkdir -p
      2. open(O_RDWR|O_CREAT, 0o644) + fcntl.LOCK_EX|LOCK_NB
      3. 失败 → 委派 `_handle_lock_conflict`（读 holder / 判活 / mtime / 残锁重试）
      4. 成功 → 注册 atexit + signal handler，再写 JSON 元数据（_write_lock_json 失败显式 release）
      5. requirement 类（run_id.startswith("REQ-")）→ 建 symlink

    Raises:
        LockBusyError: 持有者活着或残锁清理后仍冲突。
        OSError: 锁文件 IO 失败。
    """
    locks_dir = repo_root / "runs" / ".locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = locks_dir / f"{run_id}.lock"

    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        ok = _try_fcntl_lock(fd)
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        raise

    if not ok:
        fd = _handle_lock_conflict(fd, lock_path)

    # 取锁成功（fcntl 已持锁），先建 handle 并注册 cleanup —— SIGTERM 窗口前移（IB-27）
    handle = LockHandle(
        run_id=run_id,
        lock_path=lock_path,
        symlink_path=None,
        fd=fd,
    )
    handle._release_fn = partial(release, handle)
    atexit.register(handle._release_fn)
    _setup_signal_handlers(handle)

    # 写入 JSON 元数据（可能失败）；失败显式 release 后再传播 —— fd 兜底（IB-23）
    try:
        _write_lock_json(fd, lock_path, run_id)
    except WorkflowError:
        release(handle)
        raise

    handle.symlink_path = _make_symlink_if_needed(run_id, lock_path, repo_root)
    return handle


def release(handle: LockHandle) -> None:
    """释放锁：fcntl.LOCK_UN + close + 删 .lock 文件（不删 symlink，dangling 容忍）。

    幂等：多次调用安全（_released 标志保护）。
    LOCK_UN 包 try/except OSError: pass（参考 IB-03 既有惯例）。
    atexit 反注册按 functools.partial 对象精确匹配（IB-22），不影响其它 handle。
    """
    if handle._released:
        return
    handle._released = True
    if handle._release_fn is not None:
        atexit.unregister(handle._release_fn)
        handle._release_fn = None

    try:
        fcntl.flock(handle.fd, fcntl.LOCK_UN)
    except OSError:
        pass

    try:
        os.close(handle.fd)
    except OSError:
        pass

    try:
        os.unlink(handle.lock_path)
        logger.debug("lock released (run_id=%s)", handle.run_id)
    except OSError as exc:
        if exc.errno != errno.ENOENT:
            logger.debug("lock file unlink failed (non-critical): %s", exc)
    # 不删 symlink（dangling 容忍）
