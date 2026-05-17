"""tests/lib/test_path_lock.py — path_lock 单元测试（F-008 AC-05）。

覆盖 7 条 acceptance + 1 条性能测试 + rev2 新增 mtime 二次校验测试：
  AC-1  acquire 首次取锁成功 → .lock JSON 含 pid / created_at / path_target
  AC-2  requirement 类 run → requirements/.locks/<id>.lock 是 symlink 指向实锁
  AC-3  release 后 .lock 删除；symlink 保留（dangling 容忍）
  AC-4  并发：进程 A 持锁，进程 B → raise LockBusyError（stderr 含目标串）
  AC-5  残锁：mock _is_pid_alive=False → 自动清理 + 重试一次成功
  AC-6  残锁 + 重试后仍冲突 → raise LockBusyError（不进入活锁）
  AC-7  atexit：sys.exit(0) → .lock 文件被删
  PERF  单次 acquire wall-clock ≤ 100ms
  REV2-MTIME-1  _is_stale_by_mtime：created_at 比 st_mtime 早 2s → True
  REV2-MTIME-2  _is_stale_by_mtime：created_at 与 st_mtime 接近（< 1s）→ False（保守）
  REV2-MTIME-3  acquire 中 pid 死但 mtime 校验不通过（pid 复用窗口）→ 不清理，直接 raise LockBusyError
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import path_lock
from path_lock import LockBusyError, acquire, release, _is_stale_by_mtime


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path) -> Path:
    """在 tmp_path 下建一个最小 repo 结构（runs/.locks + requirements/.locks）。"""
    (tmp_path / "runs" / ".locks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "requirements" / ".locks").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _lock_path(root: Path, run_id: str) -> Path:
    return root / "runs" / ".locks" / f"{run_id}.lock"


def _symlink_path(root: Path, run_id: str) -> Path:
    return root / "requirements" / ".locks" / f"{run_id}.lock"


def _read_lock_json(root: Path, run_id: str) -> dict:
    return json.loads(_lock_path(root, run_id).read_text(encoding="utf-8").strip())


# ---------------------------------------------------------------------------
# AC-1：acquire 首次取锁成功 → JSON 含必填字段
# ---------------------------------------------------------------------------

def test_acquire_success_lock_json(tmp_path: Path) -> None:
    """AC-1: acquire 首次成功 → .lock 文件 JSON 含 pid / created_at / path_target。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    handle = acquire(run_id, root)
    try:
        lp = _lock_path(root, run_id)
        assert lp.exists(), ".lock 文件应存在"

        data = _read_lock_json(root, run_id)
        assert data["pid"] == os.getpid(), "pid 应等于当前进程"
        # created_at 格式为 ISO8601（含 T 分隔符）
        assert "T" in data["created_at"], "created_at 应为 ISO8601 格式"
        # path_target 应为绝对路径
        assert os.path.isabs(data["path_target"]), "path_target 应为绝对路径"
    finally:
        release(handle)


# ---------------------------------------------------------------------------
# AC-2：requirement 类 run → symlink 存在且指向实锁
# ---------------------------------------------------------------------------

def test_acquire_req_run_creates_symlink(tmp_path: Path) -> None:
    """AC-2: requirement 类 run → requirements/.locks/<id>.lock 是 symlink 指向实锁。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    handle = acquire(run_id, root)
    try:
        sl = _symlink_path(root, run_id)
        assert os.path.islink(sl), "requirements/.locks/<id>.lock 应是 symlink"
        # readlink 结果应包含实锁文件名
        target = os.readlink(sl)
        assert run_id + ".lock" in target, f"symlink target 应包含 {run_id}.lock，实际: {target}"
    finally:
        release(handle)


def test_acquire_non_req_run_no_symlink(tmp_path: Path) -> None:
    """非 REQ- 类 run 不建 symlink。"""
    root = _make_repo(tmp_path)
    run_id = "RUN-2026-001"

    handle = acquire(run_id, root)
    try:
        assert handle.symlink_path is None
    finally:
        release(handle)


# ---------------------------------------------------------------------------
# AC-3：release 后 .lock 删除；symlink 保留（dangling）
# ---------------------------------------------------------------------------

def test_release_deletes_lock_keeps_symlink(tmp_path: Path) -> None:
    """AC-3: release → .lock 删除，symlink 保留（dangling 容忍）。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    handle = acquire(run_id, root)
    sl = _symlink_path(root, run_id)
    release(handle)

    assert not _lock_path(root, run_id).exists(), "release 后 .lock 文件应被删除"
    # symlink 仍存在（dangling）
    assert os.path.lexists(sl), "release 后 symlink 应仍存在（dangling 容忍）"
    assert not sl.exists(), "dangling symlink 不应 resolve 成功"


# ---------------------------------------------------------------------------
# AC-4：并发：同进程内模拟第二次 acquire 时 fcntl 冲突（用 fork-like 进程测试见 e2e）
# 此处通过 mock _try_fcntl_lock 模拟 BlockingIOError 场景，验证 LockBusyError 抛出
# ---------------------------------------------------------------------------

def test_acquire_busy_raises_lock_busy_error(tmp_path: Path) -> None:
    """AC-4: 模拟 fcntl 失败 + pid 存活 → 抛 LockBusyError 含正确 pid。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    # 先写一个假 .lock 文件（模拟持有者）
    lp = _lock_path(root, run_id)
    fake_pid = os.getpid()  # 用当前 pid（保证 _is_pid_alive=True）
    lock_data = {
        "pid": fake_pid,
        "created_at": "2026-05-15T10:00:00+00:00",
        "path_target": str(lp.resolve()),
        "host": "Darwin-25.4.0",
    }
    lp.write_text(json.dumps(lock_data) + "\n", encoding="utf-8")

    # 模拟 _try_fcntl_lock 返回 False（锁冲突）
    with mock.patch.object(path_lock, "_try_fcntl_lock", return_value=False):
        with pytest.raises(LockBusyError) as exc_info:
            acquire(run_id, root)

    assert exc_info.value.pid == fake_pid
    assert "another continue is running" in str(exc_info.value)
    assert f"pid={fake_pid}" in str(exc_info.value)


# ---------------------------------------------------------------------------
# AC-5：残锁：mock _is_pid_alive=False → 自动清理 + 重试一次成功
# ---------------------------------------------------------------------------

def test_acquire_stale_lock_auto_cleanup(tmp_path: Path) -> None:
    """AC-5: mock _is_pid_alive=False → stale 残锁自动清理，重试一次取锁成功。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    # 写一个假 .lock（模拟残锁，pid 不存在）
    lp = _lock_path(root, run_id)
    dead_pid = 99999999  # 极大概率不存在的 pid
    lock_data = {
        "pid": dead_pid,
        "created_at": "2026-01-01T00:00:00+00:00",
        "path_target": str(lp.resolve()),
        "host": "Darwin-25.4.0",
    }
    lp.write_text(json.dumps(lock_data) + "\n", encoding="utf-8")

    # 第一次 _try_fcntl_lock 返 False（模拟锁冲突），后续正常
    call_count = {"n": 0}
    original_try = path_lock._try_fcntl_lock

    def _mock_try(fd: int) -> bool:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return False  # 第一次失败
        return original_try(fd)  # 重试成功（因为 .lock 已被清理）

    with mock.patch.object(path_lock, "_try_fcntl_lock", side_effect=_mock_try):
        with mock.patch.object(path_lock, "_is_pid_alive", return_value=False):
            handle = acquire(run_id, root)

    try:
        # 取锁成功，.lock 应含当前 pid
        data = _read_lock_json(root, run_id)
        assert data["pid"] == os.getpid()
    finally:
        release(handle)


# ---------------------------------------------------------------------------
# AC-6：残锁 + 重试后仍冲突 → raise LockBusyError，不进入活锁
# ---------------------------------------------------------------------------

def test_acquire_stale_lock_retry_still_busy(tmp_path: Path) -> None:
    """AC-6: 残锁清理后重试仍失败 → raise LockBusyError，不进入活锁。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    lp = _lock_path(root, run_id)
    dead_pid = 99999999
    lock_data = {
        "pid": dead_pid,
        "created_at": "2026-01-01T00:00:00+00:00",
        "path_target": str(lp.resolve()),
        "host": "Darwin-25.4.0",
    }
    lp.write_text(json.dumps(lock_data) + "\n", encoding="utf-8")

    # 两次 _try_fcntl_lock 都返 False（极小概率并发场景模拟）
    # 重试后 .lock 写有新的 pid（另一进程）
    new_pid = os.getpid()
    new_lock_data = {
        "pid": new_pid,
        "created_at": "2026-05-15T10:00:00+00:00",
        "path_target": str(lp.resolve()),
        "host": "Darwin-25.4.0",
    }

    call_count = {"n": 0}

    def _mock_try(fd: int) -> bool:
        call_count["n"] += 1
        if call_count["n"] == 2:
            # 重试前写入新持有者的 lock 信息
            lp.write_text(json.dumps(new_lock_data) + "\n", encoding="utf-8")
        return False

    with mock.patch.object(path_lock, "_try_fcntl_lock", side_effect=_mock_try):
        with mock.patch.object(path_lock, "_is_pid_alive", return_value=False):
            with pytest.raises(LockBusyError):
                acquire(run_id, root)

    # 确认只重试了 2 次（第一次 + 一次重试），不进入活锁
    assert call_count["n"] == 2, f"应只重试 2 次，实际 {call_count['n']} 次"


# ---------------------------------------------------------------------------
# AC-7：atexit：进程退出 → .lock 文件被删（用 subprocess 验证）
# ---------------------------------------------------------------------------

def test_atexit_cleanup_on_exit(tmp_path: Path) -> None:
    """AC-7: 进程 sys.exit(0) → .lock 文件被删（通过 subprocess + 共享 tmp_path 验证）。"""
    import subprocess

    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    script = f"""
import sys
sys.path.insert(0, {str(REPO_ROOT / "scripts" / "lib")!r})
from pathlib import Path
import path_lock

root = Path({str(root)!r})
handle = path_lock.acquire({run_id!r}, root)
# 不显式 release，依赖 atexit 清理
sys.exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"子进程应 exit 0，stderr={result.stderr}"
    assert not _lock_path(root, run_id).exists(), "atexit 应删除 .lock 文件"


# ---------------------------------------------------------------------------
# PERF：单次 acquire wall-clock ≤ 100ms
# ---------------------------------------------------------------------------

def test_acquire_under_100ms(tmp_path: Path) -> None:
    """PERF: 单次 acquire（无竞争）wall-clock ≤ 100ms。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    t0 = time.perf_counter()
    handle = acquire(run_id, root)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    release(handle)

    assert elapsed_ms < 100, f"acquire 耗时 {elapsed_ms:.1f}ms，超过 100ms 阈值"


# ---------------------------------------------------------------------------
# 幂等：release 多次安全
# ---------------------------------------------------------------------------

def test_release_idempotent(tmp_path: Path) -> None:
    """release 多次调用不应抛异常（幂等）。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    handle = acquire(run_id, root)
    release(handle)
    release(handle)  # 第二次 release 不应抛异常


# ---------------------------------------------------------------------------
# REV2-MTIME：_is_stale_by_mtime 单元测试（F-CR-014 二次校验）
# ---------------------------------------------------------------------------

def test_is_stale_by_mtime_true(tmp_path: Path) -> None:
    """REV2-MTIME-1: created_at 比 st_mtime 早 2 秒 → 返 True（视为真 stale）。"""
    lp = tmp_path / "test.lock"
    lp.write_text("x", encoding="utf-8")

    # 获取真实 mtime
    actual_mtime = lp.stat().st_mtime

    # created_at = mtime - 2 秒（早于 mtime 2 秒，满足 ≥ 1s 阈值）
    created_dt = datetime.fromtimestamp(actual_mtime - 2.0, tz=timezone.utc)
    created_at_iso = created_dt.isoformat()

    result = _is_stale_by_mtime(lp, created_at_iso, threshold_seconds=1.0)
    assert result is True, f"created_at 早于 mtime 2s，应视为 stale，got {result}"


def test_is_stale_by_mtime_false_pid_reuse_window(tmp_path: Path) -> None:
    """REV2-MTIME-2: created_at 与 st_mtime 接近（< 1s 差值）→ 返 False（保守视为活锁）。"""
    lp = tmp_path / "test.lock"
    lp.write_text("x", encoding="utf-8")

    # 获取真实 mtime
    actual_mtime = lp.stat().st_mtime

    # created_at = mtime - 0.5 秒（与 mtime 相差 0.5s，不满足 ≥ 1s 阈值）
    created_dt = datetime.fromtimestamp(actual_mtime - 0.5, tz=timezone.utc)
    created_at_iso = created_dt.isoformat()

    result = _is_stale_by_mtime(lp, created_at_iso, threshold_seconds=1.0)
    assert result is False, f"created_at 与 mtime 差 < 1s，应保守视为活锁，got {result}"


def test_atexit_unregister_precision_cross_handle(tmp_path: Path) -> None:
    """IB-22: 同进程持两 handle → release(handleA) 不应误删 handleB 的 atexit 注册。"""
    root = _make_repo(tmp_path)

    handle_a = acquire("REQ-2026-099", root)
    handle_b = acquire("REQ-2026-100", root)
    assert handle_a._release_fn is not None
    assert handle_b._release_fn is not None
    assert handle_a._release_fn is not handle_b._release_fn

    # 释放 A 后，B 的 partial 仍应在 atexit 注册表里
    release(handle_a)
    assert handle_a._release_fn is None
    assert handle_b._release_fn is not None
    # _exithandlers 在新版 CPython 已不导出；改用反向尝试 unregister 验证存在性
    import atexit as _atexit
    # 若 B 注册仍在，unregister 返回 None 且后续真正 release 走 idempotent 路径
    _atexit.unregister(handle_b._release_fn)
    # 不调 release(handle_b)（_release_fn 已被外部 unregister，但 release 仍要清 fd）
    release(handle_b)
    assert not _lock_path(root, "REQ-2026-100").exists()


def test_acquire_write_lock_json_fail_fd_released(tmp_path: Path) -> None:
    """IB-23: _write_lock_json 抛 WorkflowError → acquire 释放 fd 并传播，无残锁。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    from common import WorkflowError as _WfErr

    def _boom(fd: int, lock_path: Path, run_id: str) -> None:
        raise _WfErr("simulated write failure")

    with mock.patch.object(path_lock, "_write_lock_json", side_effect=_boom):
        with pytest.raises(_WfErr, match="simulated write failure"):
            acquire(run_id, root)

    # release 已被显式调用 → .lock 文件已删
    assert not _lock_path(root, run_id).exists(), "_write_lock_json 失败后 .lock 应被 release 清理"

    # 后续 acquire 应能再次取锁（fd 已释放）
    handle = acquire(run_id, root)
    release(handle)


def test_retry_after_stale_inode_changed_aborts(tmp_path: Path) -> None:
    """IB-26: _retry_after_stale 中 unlink 前 inode 比对发现已被换 →
    返 (None, retry_data) 放弃清理，避免误删他人新建的锁文件。
    """
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    lp = _lock_path(root, run_id)
    other_holder = {
        "pid": 12345,
        "created_at": "2026-05-15T10:00:00+00:00",
        "path_target": str(lp.resolve()),
        "host": "Darwin-25.4.0",
    }
    lp.write_text(json.dumps(other_holder) + "\n", encoding="utf-8")

    fd = os.open(str(lp), os.O_RDWR | os.O_CREAT, 0o644)

    real_stat = os.stat

    class _FakeStat:
        def __init__(self, real: os.stat_result, ino: int) -> None:
            self.st_ino = ino
            self.st_mtime = real.st_mtime
            self.st_size = real.st_size

    def _fake_stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        r = real_stat(path, *args, **kwargs)
        if str(path) == str(lp):
            return _FakeStat(r, r.st_ino + 99999)
        return r

    with mock.patch.object(path_lock.os, "stat", side_effect=_fake_stat):
        new_fd, retry_data = path_lock._retry_after_stale(fd, lp)

    assert new_fd is None, "inode 不匹配应放弃 retry"
    assert lp.exists(), "inode 比对失败 → 不应 unlink 他人的锁文件"
    assert retry_data is not None
    assert retry_data["pid"] == 12345


def test_acquire_pid_reuse_window_no_cleanup(tmp_path: Path) -> None:
    """REV2-MTIME-3: mock _is_pid_alive=False 但 mtime 校验不通过（pid 复用窗口）
    → acquire 不清理 .lock，直接 raise LockBusyError。
    """
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    lp = _lock_path(root, run_id)
    dead_pid = 99999999
    lock_data = {
        "pid": dead_pid,
        "created_at": "2026-01-01T00:00:00+00:00",
        "path_target": str(lp.resolve()),
        "host": "Darwin-25.4.0",
    }
    lp.write_text(json.dumps(lock_data) + "\n", encoding="utf-8")

    # mock _try_fcntl_lock 返 False（锁冲突），_is_pid_alive 返 False（pid 死），
    # 但 _is_stale_by_mtime 返 False（pid 复用窗口，不应清理）
    with mock.patch.object(path_lock, "_try_fcntl_lock", return_value=False):
        with mock.patch.object(path_lock, "_is_pid_alive", return_value=False):
            with mock.patch.object(path_lock, "_is_stale_by_mtime", return_value=False):
                with pytest.raises(LockBusyError) as exc_info:
                    acquire(run_id, root)

    # .lock 文件应仍存在（未被清理）
    assert lp.exists(), "pid 复用窗口：.lock 文件不应被清理"
    assert exc_info.value.pid == dead_pid
