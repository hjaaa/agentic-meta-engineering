"""path-lock 三件套（D-003）：fcntl.LOCK_EX + pid 文件 + atexit + 失活 pid 自清理。

公开 API：
  - acquire(run_id, repo_root) → LockHandle
      取 runs/.locks/<run-id>.lock 排他锁；同步建 requirements/.locks/<req-id>.lock symlink。
  - release(handle) → None
      释放 fcntl + close + 删 .lock 文件；不删 symlink（dangling 由下次 acquire 容忍）。
  - LockBusyError：第二进程取锁失败时抛出（持有方 pid + created_at + path_target）。

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
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

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
    """acquire 返回的不透明句柄；release 时按此释放。"""

    run_id: str
    lock_path: Path
    symlink_path: Path | None
    fd: int
    _released: bool = field(default=False, init=False, repr=False)


def _is_pid_alive(pid: int) -> bool:
    """kill -0 pid → ESRCH 为 False，其他 OSError 保守返 True。"""
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        # EPERM 等保守视为存活
    return True


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
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, data)
    os.fsync(fd)
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


def acquire(run_id: str, repo_root: Path) -> LockHandle:
    """取实锁 + 同步 symlink。

    流程：
      1. 计算实锁路径 runs/.locks/<run-id>.lock；mkdir -p
      2. open(O_RDWR|O_CREAT, 0o644) + fcntl.LOCK_EX|LOCK_NB
      3. 失败 → 读 .lock 内 JSON（pid/created_at/path_target）→ kill -0 pid
            - ESRCH（pid 死）→ 自动清理 .lock 文件 + 重试一次（最多 1 次）
            - 否则 raise LockBusyError
      4. 成功 → 把 LockHandle 写入 .lock 文件（json.dumps + fsync）
      5. requirement 类（run_id.startswith("REQ-")）→ 建 symlink
      6. atexit + signal handler 注册 release

    Raises:
        LockBusyError: 持有者活着
        OSError: 锁文件 IO 失败
    """
    locks_dir = repo_root / "runs" / ".locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = locks_dir / f"{run_id}.lock"

    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)

    ok = _try_fcntl_lock(fd)
    if not ok:
        # 取锁失败：读当前锁持有者信息
        lock_data = _read_lock_json(lock_path)
        if lock_data:
            holder_pid = lock_data.get("pid", 0)
            created_at = lock_data.get("created_at", "")
            path_target = lock_data.get("path_target", "")
            if not _is_pid_alive(holder_pid):
                # 残锁：pid 已死，清理并重试一次（防活锁：只重试一次）
                logger.info("stale lock detected (pid=%d dead), cleaning up", holder_pid)
                try:
                    os.close(fd)
                    os.unlink(lock_path)
                except OSError as exc:
                    logger.debug("stale lock cleanup failed: %s", exc)

                # 重试一次
                fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
                ok = _try_fcntl_lock(fd)
                if not ok:
                    # 重试仍失败（极小概率：连续竞争）
                    retry_data = _read_lock_json(lock_path)
                    if retry_data:
                        raise LockBusyError(
                            retry_data.get("pid", 0),
                            retry_data.get("created_at", ""),
                            retry_data.get("path_target", ""),
                        )
                    os.close(fd)
                    raise LockBusyError(0, "", str(lock_path))
            else:
                os.close(fd)
                raise LockBusyError(holder_pid, created_at, path_target)
        else:
            os.close(fd)
            raise LockBusyError(0, "", str(lock_path))

    # 取锁成功，写入当前进程信息
    _write_lock_json(fd, lock_path, run_id)

    symlink_path = _make_symlink_if_needed(run_id, lock_path, repo_root)

    handle = LockHandle(
        run_id=run_id,
        lock_path=lock_path,
        symlink_path=symlink_path,
        fd=fd,
    )

    atexit.register(release, handle)
    _setup_signal_handlers(handle)

    return handle


def release(handle: LockHandle) -> None:
    """释放锁：fcntl.LOCK_UN + close + 删 .lock 文件（不删 symlink，dangling 容忍）。

    幂等：多次调用安全（_released 标志保护）。
    LOCK_UN 包 try/except OSError: pass（参考 IB-03 既有惯例）。
    """
    if handle._released:
        return
    handle._released = True

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
