"""touches_guard.py receipt.json 并发 RMW 回归测试（修复 review-001 F-4 / plan.md ADR D-012）。

覆盖：
  TL-RC-001 N 进程并发 _record_violation → 全部 N 条 violation 都落盘，无 RMW 覆盖丢失
  TL-RC-002 并发跑完后 receipt.json 必须可解析（无半写 JSON 垃圾）

设计来源：
  仿 tests/lib/test_dispatch_state.py TL-006 的 multiprocessing 模式（threading 受 GIL
  串行化掩盖锁竞争 → 必须用真进程触发并发）。
"""
from __future__ import annotations

import importlib.util
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_PATH = _REPO_ROOT / ".claude" / "hooks" / "touches_guard.py"


def _load_touches_guard():
    """从 .claude/hooks/touches_guard.py 路径加载模块（非 package 路径）。"""
    spec = importlib.util.spec_from_file_location("touches_guard", _HOOK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {_HOOK_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def touches_guard():
    """主进程内加载 touches_guard 模块（仅供内省断言；子进程独立加载）。"""
    return _load_touches_guard()


@pytest.fixture
def receipt_path(tmp_path: Path) -> Path:
    """独立 receipt.json 路径；不预创建，由 _flock_receipt_file 首访问建空骨架。"""
    return tmp_path / "F-099.receipt.json"


# ---------- 子进程入口：模块顶层定义（spawn 模式下需 pickle 友好） ----------


def _writer_proc(
    receipt_path_str: str, idx: int, barrier_path: str, result_q: mp.Queue
) -> None:
    """子进程：等 barrier 出现后立刻调 _record_violation 写一条唯一 entry。

    spawn 模式下 sys.modules 不继承父进程，子进程独立加载 touches_guard 模块。
    """
    while not Path(barrier_path).exists():
        time.sleep(0.01)
    try:
        spec = importlib.util.spec_from_file_location("touches_guard", _HOOK_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"子进程无法加载 {_HOOK_PATH}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod._record_violation(
            Path(receipt_path_str),
            "F-099",
            f"path/{idx}.py",
            "Edit",
        )
        result_q.put(("ok", idx))
    except Exception as exc:  # noqa: BLE001
        result_q.put(("err", f"{type(exc).__name__}:{exc}"))


# ---------- TL-RC-001 ----------


def test_TL_RC_001_concurrent_record_violation_no_loss(
    receipt_path: Path, tmp_path: Path
) -> None:
    """N 进程并发 _record_violation：所有 N 条 violation 都落盘不丢失。

    旧实现（atomic rename + 无锁 RMW）下：两进程各 base 旧版后互相覆盖，至少 1 条丢失；
    新实现（_flock_receipt_file LOCK_EX）下：所有 N 条串行写入，无丢失（修复 review-001 F-4）。
    """
    N = 8
    barrier = tmp_path / "barrier"
    q: mp.Queue = mp.Queue()
    procs = [
        mp.Process(
            target=_writer_proc,
            args=(str(receipt_path), i, str(barrier), q),
        )
        for i in range(N)
    ]
    for p in procs:
        p.start()

    # 同时发令（最大化竞争窗口）
    barrier.write_text("go")
    for p in procs:
        p.join(timeout=30)
    for p in procs:
        assert not p.is_alive(), f"子进程 {p.pid} 30s 内未完成（疑似锁死）"

    # 消费结果队列（防僵死 + 验证子进程结果）
    results = [q.get(timeout=2) for _ in range(N)]
    statuses = [r[0] for r in results]
    assert all(s == "ok" for s in statuses), (
        f"全部进程必须成功（锁内串行不应超时）：{results}"
    )

    # 校验：receipt.touches_violations[] 必须恰好 N 条且路径集合完整
    assert receipt_path.exists()
    data = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data.get("feature_id") == "F-099"
    assert data.get("schema_version") == "1.0"
    violations = data.get("touches_violations", [])
    assert len(violations) == N, (
        f"期望 {N} 条 violation（无 RMW 覆盖丢失），实际 {len(violations)}"
    )
    paths = {v.get("path") for v in violations}
    assert paths == {f"path/{i}.py" for i in range(N)}, (
        f"路径集合不完整 → 存在丢失的 violation：{paths}"
    )


# ---------- TL-RC-002 ----------


def test_TL_RC_002_concurrent_record_violation_json_intact(
    receipt_path: Path, tmp_path: Path
) -> None:
    """并发跑完后 receipt.json 必须可解析（无半写 JSON 垃圾）。"""
    N = 4
    barrier = tmp_path / "barrier"
    q: mp.Queue = mp.Queue()
    procs = [
        mp.Process(
            target=_writer_proc,
            args=(str(receipt_path), i, str(barrier), q),
        )
        for i in range(N)
    ]
    for p in procs:
        p.start()
    barrier.write_text("go")
    for p in procs:
        p.join(timeout=15)

    # 消费 queue 防僵死
    [q.get(timeout=2) for _ in range(N)]

    # JSON 完整性校验
    text = receipt_path.read_text(encoding="utf-8")
    data = json.loads(text)  # 解析失败即 fail（半写垃圾）
    assert isinstance(data, dict)
    assert "touches_violations" in data
    assert isinstance(data["touches_violations"], list)


# ---------- TL-RC-003 单进程功能基线（确认锁不影响顺序写入） ----------


def test_TL_RC_003_sequential_record_violation_baseline(
    receipt_path: Path, touches_guard
) -> None:
    """单进程顺序两次 _record_violation：两条 violation 都在；锁不影响顺序写入。"""
    touches_guard._record_violation(receipt_path, "F-099", "a.py", "Edit")
    touches_guard._record_violation(receipt_path, "F-099", "b.py", "Write")

    data = json.loads(receipt_path.read_text(encoding="utf-8"))
    violations = data["touches_violations"]
    assert len(violations) == 2
    assert {v["path"] for v in violations} == {"a.py", "b.py"}
    assert {v["tool"] for v in violations} == {"Edit", "Write"}
