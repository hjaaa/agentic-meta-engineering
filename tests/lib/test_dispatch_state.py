"""dispatch_state.py 单元测试（F-004 / detail-design §3.5）。

覆盖 TL-001 ~ TL-010：
  - TL-001 read_state 文件不存在 → None
  - TL-002 read 到 JSON 非 object → ValueError
  - TL-003 write 缺 schema_version → AssertionError
  - TL-004 write current_feature=F-002 缺 acquired_at → AssertionError
  - TL-005 write 完后 read 等价（round-trip）
  - TL-006 并发 2 进程 write_state → 后写者要么成功要么 timeout，绝不交错半写
  - TL-007 clear_state 空闲态文件 → 保留 schema_version + req_id，current_feature=null
  - TL-008 flock_state_file 锁泄漏路径（fd 异常关闭）→ 下次取锁立刻成功
  - TL-009 TOCTOU 回归：A 在 with 块内未释放锁前，B 调 read_state 必须 timeout
  - TL-010 dispatch_precheck.py 模拟单 with 块内 read+三校验+write → 单原子动作

并发测试用 multiprocessing 模拟（避免 threading 因 GIL 串行化掩盖锁问题）。
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

import pytest

# 把 repo root 加到 sys.path，便于 import scripts.lib.dispatch_state
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.lib import dispatch_state  # noqa: E402
from scripts.lib.dispatch_state import (  # noqa: E402
    LOCK_TIMEOUT_S,
    SUPPORTED_SCHEMA_VERSION,
    clear_state,
    flock_state_file,
    read_state,
    write_state,
)


# ---------- fixture ----------

@pytest.fixture
def req_dir(tmp_path: Path) -> Path:
    """提供独立 req_dir：tmp_path/REQ-2099-001。"""
    d = tmp_path / "REQ-2099-001"
    d.mkdir(parents=True)
    return d


def _make_state(current_feature: str | None = None) -> dispatch_state.DispatchState:
    """构造合法 DispatchState；current_feature 非 null 时补齐 acquired_at/pid。"""
    s: dispatch_state.DispatchState = {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "req_id": "REQ-2099-001",
        "current_feature": current_feature,
    }
    if current_feature is not None:
        s["acquired_at"] = "2026-05-06T15:00:00+08:00"
        s["acquired_by_pid"] = os.getpid()
    return s


# ---------- TL-001 ----------

def test_TL_001_read_state_file_not_exist_returns_none(req_dir: Path) -> None:
    """文件不存在直接 None；不副作用建空骨架。"""
    state_path = req_dir / dispatch_state.STATE_FILE_NAME
    assert not state_path.exists()
    assert read_state(req_dir) is None
    # L2 read 路径快速分支不应建空骨架
    assert not state_path.exists()


# ---------- TL-002 ----------

def test_TL_002_read_non_object_raises_value_error(req_dir: Path) -> None:
    """read 到 JSON 顶层不是 object → ValueError。"""
    state_path = req_dir / dispatch_state.STATE_FILE_NAME
    state_path.write_text('["array", "is", "wrong"]', encoding="utf-8")
    with pytest.raises(ValueError, match="must be object"):
        read_state(req_dir)


def test_TL_002b_read_invalid_json_raises_value_error(req_dir: Path) -> None:
    """JSON 解析失败 → ValueError（同一异常类型，hook 层 fail-open 兜底统一）。"""
    state_path = req_dir / dispatch_state.STATE_FILE_NAME
    state_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON 解析失败"):
        read_state(req_dir)


# ---------- TL-003 ----------

def test_TL_003_write_missing_schema_version_raises_assertion(req_dir: Path) -> None:
    """write_state 缺 schema_version → AssertionError。"""
    bad: dict = {"req_id": "REQ-2099-001", "current_feature": None}
    with pytest.raises(AssertionError, match="schema_version"):
        write_state(req_dir, bad)  # type: ignore[arg-type]


def test_TL_003b_write_wrong_schema_version_raises_assertion(req_dir: Path) -> None:
    """schema_version 非 1.0 → AssertionError。"""
    bad: dict = {"schema_version": "2.0", "req_id": "REQ-2099-001", "current_feature": None}
    with pytest.raises(AssertionError):
        write_state(req_dir, bad)  # type: ignore[arg-type]


# ---------- TL-004 ----------

def test_TL_004_write_active_state_missing_acquired_at_raises_assertion(req_dir: Path) -> None:
    """current_feature 非 null 时缺 acquired_at → AssertionError。"""
    bad: dict = {
        "schema_version": "1.0",
        "req_id": "REQ-2099-001",
        "current_feature": "F-002",
        # 缺 acquired_at / acquired_by_pid
    }
    with pytest.raises(AssertionError, match="acquired_at"):
        write_state(req_dir, bad)  # type: ignore[arg-type]


def test_TL_004b_write_active_state_missing_pid_raises_assertion(req_dir: Path) -> None:
    """current_feature 非 null 时缺 acquired_by_pid → AssertionError。"""
    bad: dict = {
        "schema_version": "1.0",
        "req_id": "REQ-2099-001",
        "current_feature": "F-002",
        "acquired_at": "2026-05-06T15:00:00+08:00",
        # 缺 acquired_by_pid
    }
    with pytest.raises(AssertionError, match="acquired_by_pid"):
        write_state(req_dir, bad)  # type: ignore[arg-type]


# ---------- TL-005 ----------

def test_TL_005_write_then_read_roundtrip(req_dir: Path) -> None:
    """write → read round-trip 等价。"""
    state = _make_state(current_feature="F-002")
    write_state(req_dir, state)
    got = read_state(req_dir)
    assert got is not None
    assert got["schema_version"] == "1.0"
    assert got["req_id"] == "REQ-2099-001"
    assert got["current_feature"] == "F-002"
    assert got["acquired_at"] == "2026-05-06T15:00:00+08:00"
    assert got["acquired_by_pid"] == os.getpid()


def test_TL_005b_write_idle_state_roundtrip(req_dir: Path) -> None:
    """idle 态（current_feature=null）round-trip。"""
    state = _make_state(current_feature=None)
    write_state(req_dir, state)
    got = read_state(req_dir)
    assert got is not None
    assert got["current_feature"] is None
    assert "acquired_at" not in got
    assert "acquired_by_pid" not in got


# ---------- TL-006 ----------

def _writer_proc(req_dir_str: str, fid: str, barrier_path: str, result_q: mp.Queue) -> None:
    """子进程：等 barrier 信号后立刻调 write_state。"""
    # 等待 barrier 文件出现（父进程发令后再起跑，最大化竞争窗口）
    while not Path(barrier_path).exists():
        time.sleep(0.01)
    try:
        from scripts.lib.dispatch_state import write_state as _w
        s = {
            "schema_version": "1.0",
            "req_id": "REQ-2099-001",
            "current_feature": fid,
            "acquired_at": "2026-05-06T15:00:00+08:00",
            "acquired_by_pid": os.getpid(),
        }
        _w(Path(req_dir_str), s)  # type: ignore[arg-type]
        result_q.put(("ok", fid))
    except Exception as e:  # noqa: BLE001
        result_q.put(("err", f"{type(e).__name__}:{e}"))


def test_TL_006_concurrent_write_no_interleave(req_dir: Path, tmp_path: Path) -> None:
    """并发 2 进程 write_state：后写者要么成功要么 timeout，文件绝不出现交错半写。

    校验点：最终 JSON 完整可解析；current_feature ∈ {F-001, F-002}（不会是混合垃圾）。
    """
    barrier = tmp_path / "barrier"
    q: mp.Queue = mp.Queue()
    p1 = mp.Process(target=_writer_proc, args=(str(req_dir), "F-001", str(barrier), q))
    p2 = mp.Process(target=_writer_proc, args=(str(req_dir), "F-002", str(barrier), q))
    p1.start()
    p2.start()
    # 同时发令
    barrier.write_text("go")
    p1.join(timeout=15)
    p2.join(timeout=15)
    assert not p1.is_alive() and not p2.is_alive()

    # 最终文件必须可解析的合法 JSON
    state_path = req_dir / dispatch_state.STATE_FILE_NAME
    assert state_path.exists()
    final = json.loads(state_path.read_text(encoding="utf-8"))
    assert final["schema_version"] == "1.0"
    assert final["current_feature"] in ("F-001", "F-002")  # 必为某一胜出者完整写入


# ---------- TL-007 ----------

def test_TL_007_clear_state_idle_keeps_schema_and_req_id(req_dir: Path) -> None:
    """clear_state 空闲态：保留 schema_version + req_id，current_feature=null。"""
    # 先 write 一个 active 态
    write_state(req_dir, _make_state(current_feature="F-002"))
    clear_state(req_dir)
    got = read_state(req_dir)
    assert got is not None
    assert got["schema_version"] == "1.0"
    assert got["req_id"] == "REQ-2099-001"
    assert got["current_feature"] is None
    assert "acquired_at" not in got
    assert "acquired_by_pid" not in got


def test_TL_007b_clear_state_idempotent(req_dir: Path) -> None:
    """clear_state 重复调用幂等。"""
    clear_state(req_dir)  # 文件不存在场景
    clear_state(req_dir)  # 已 idle 场景
    got = read_state(req_dir)
    assert got is not None
    assert got["current_feature"] is None


# ---------- TL-008 ----------

def test_TL_008_lock_release_after_with_block(req_dir: Path) -> None:
    """flock_state_file with 块退出后锁释放；下次取锁立刻成功（无阻塞）。"""
    with flock_state_file(req_dir) as fh:
        fh.write(_make_state(current_feature="F-002"))
    # with 块退出，锁释放
    start = time.monotonic()
    with flock_state_file(req_dir) as fh:
        s = fh.read()
        assert s is not None
    elapsed = time.monotonic() - start
    # 应远小于 LOCK_TIMEOUT_S；给 1s 充裕余量
    assert elapsed < 1.0


def test_TL_008b_lock_release_on_exception(req_dir: Path) -> None:
    """with 块内抛异常也保证释放锁。"""
    write_state(req_dir, _make_state(current_feature=None))

    class _Trigger(RuntimeError):
        pass

    with pytest.raises(_Trigger):
        with flock_state_file(req_dir) as fh:
            _ = fh.read()
            raise _Trigger("simulated")

    # 异常退出后锁应已释放，下次取锁立刻成功
    start = time.monotonic()
    with flock_state_file(req_dir) as fh:
        _ = fh.read()
    elapsed = time.monotonic() - start
    assert elapsed < 1.0


# ---------- TL-009 ----------

def _hold_lock_proc(req_dir_str: str, hold_seconds: float, ready_path: str) -> None:
    """子进程：取 L1 锁后 sleep hold_seconds 再释放（模拟 with 块内未结束）。"""
    from scripts.lib.dispatch_state import flock_state_file as _flock
    with _flock(Path(req_dir_str)):
        Path(ready_path).write_text("locked")
        time.sleep(hold_seconds)


def test_TL_009_TOCTOU_regression_read_state_blocks_during_with(
    req_dir: Path, tmp_path: Path
) -> None:
    """TOCTOU 回归：进程 A 在 with 块内未释放锁前，进程 B 调 read_state 必须 timeout。

    证明 L1 with 块的锁不会在 yield 期间被错误释放；
    L2 read_state 在锁竞争场景下走 TimeoutError 路径而非读到中间状态。
    """
    ready = tmp_path / "locked"
    # A 持锁 LOCK_TIMEOUT_S + 1s（比 B 的 5s deadline 长）
    hold_s = LOCK_TIMEOUT_S + 1.0
    p_a = mp.Process(target=_hold_lock_proc, args=(str(req_dir), hold_s, str(ready)))
    p_a.start()
    try:
        # 等 A 拿到锁
        deadline = time.monotonic() + 5.0
        while not ready.exists():
            if time.monotonic() > deadline:
                raise AssertionError("A 进程未在 5s 内取到锁，环境异常")
            time.sleep(0.05)

        # B 调 read_state；A 还持锁 → B 必须 TimeoutError
        with pytest.raises(TimeoutError, match="flock timeout"):
            read_state(req_dir)
    finally:
        p_a.join(timeout=hold_s + 5.0)
        if p_a.is_alive():
            p_a.terminate()
            p_a.join()


# ---------- TL-010 ----------

def test_TL_010_single_with_block_atomic_read_check_write(req_dir: Path) -> None:
    """模拟 dispatch_precheck.py 单 with 块内 read+三校验+write → 单原子动作。

    校验点：with 块内多次 read/write 不会取第二把锁（不应抛 TimeoutError 自己锁自己）；
    最终 state 反映 write 结果。
    """
    # 预置 idle 态
    write_state(req_dir, _make_state(current_feature=None))

    # 模拟 dispatch_precheck 的校验链
    with flock_state_file(req_dir) as fh:
        cur = fh.read()
        assert cur is not None
        assert cur["current_feature"] is None  # 校验 B-3 通过

        # 业务校验：status / depends_on / current_feature ...（这里跳过具体逻辑）
        # 通过后写入新状态
        new_state = _make_state(current_feature="F-002")
        fh.write(new_state)

        # 再 read 一次确认锁内可重入读
        re_read = fh.read()
        assert re_read is not None
        assert re_read["current_feature"] == "F-002"

    # with 块退出，锁释放；外部 read 看到最终状态
    final = read_state(req_dir)
    assert final is not None
    assert final["current_feature"] == "F-002"
    assert final["acquired_by_pid"] == os.getpid()
