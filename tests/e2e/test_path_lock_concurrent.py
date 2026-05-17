"""tests/e2e/test_path_lock_concurrent.py — path_lock 并发 E2E 测试（F-008 AC-05）。

覆盖：AC-05 E2E — 起两个 workflow_continue.main 子进程，100ms 间隔；
      后者 stderr 含 "another continue is running, pid=<A>" + exit 1。

策略：
  - 创建最小 run 环境（runs/<run_id>/run-state.jsonl + meta.yaml）
  - 进程 A 调 workflow_continue.main() 但 mock _main_loop 阻塞约 500ms（持锁期间）
  - 进程 B 在 A 持锁期间启动，尝试 main()，应 exit 1 + stderr 含目标串
  - 使用 multiprocessing.Process 而非 subprocess，以共享 tmp_path

注：e2e 测试不依赖真实 Claude API；mock dispatch_node / _main_loop 使 run 不实际执行。
"""
from __future__ import annotations

import json
import multiprocessing
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

# conftest 已注入 scripts/lib（tests/e2e/conftest.py），但 multiprocessing 子进程需重注
LIB_DIR = str(REPO_ROOT / "scripts" / "lib")


# ---------------------------------------------------------------------------
# helpers：构建最小 run 环境
# ---------------------------------------------------------------------------

def _make_minimal_run(root: Path, run_id: str) -> None:
    """在 root 下建最小合法 run 环境（支持 _setup_run 成功、_resume_run 通过）。

    路径：root/runs/<run_id>/run-state.jsonl + meta.yaml
    _resolve_run_dir 按 D-007：先查 requirements/<id>，再查 runs/<id>。
    此处用 runs/<id> 路径（不建 requirements/<id>）。
    """
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # 最小合法 run-state.jsonl：workflow_started（state=running）
    jsonl_path = run_dir / "run-state.jsonl"
    events = [
        {
            "type": "workflow_started",
            "run_id": run_id,
            "ts": "2026-05-15T00:00:00+00:00",
            "data": {"workflow_name": "standard-8phase"},
        }
    ]
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")

    # meta.yaml（_load_workflow_for_run 降级查找用）
    meta_path = run_dir / "meta.yaml"
    meta_path.write_text(
        f"run_id: {run_id}\n"
        "workflow_name: standard-8phase\n"
        f"template_path: .claude/workflows/requirement/standard-8phase.yaml\n",
        encoding="utf-8",
    )

    # 创建 .locks 目录
    (root / "runs" / ".locks").mkdir(parents=True, exist_ok=True)
    (root / "requirements" / ".locks").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 子进程入口函数
# ---------------------------------------------------------------------------

def _run_process_a(root_str: str, run_id: str, ready_event: multiprocessing.Event,
                   done_event: multiprocessing.Event) -> None:  # type: ignore[type-arg]
    """进程 A：取锁后通知 B 可以启动，然后等待 500ms 再释放。"""
    sys.path.insert(0, LIB_DIR)

    import path_lock

    root = Path(root_str)
    try:
        handle = path_lock.acquire(run_id, root)
    except Exception as exc:
        print(f"[A] acquire failed: {exc}", file=sys.stderr)
        ready_event.set()
        return

    ready_event.set()  # 通知 B：A 已持锁

    # 持锁 500ms（给 B 充足时间发起 acquire）
    time.sleep(0.5)

    path_lock.release(handle)
    done_event.set()


def _run_process_b(root_str: str, run_id: str, result_queue: multiprocessing.Queue) -> None:  # type: ignore[type-arg]
    """进程 B：尝试取锁，预期失败；把 (exit_code, stderr_text) 放入 queue。"""
    sys.path.insert(0, LIB_DIR)

    import io
    import path_lock

    root = Path(root_str)

    # 重定向 stderr 捕获输出
    old_stderr = sys.stderr
    sys.stderr = captured = io.StringIO()
    exit_code = 0
    try:
        path_lock.acquire(run_id, root)
        exit_code = 0  # 不应走到这里
    except path_lock.LockBusyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        exit_code = 1
    except Exception as exc:
        print(f"ERROR: unexpected: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        sys.stderr = old_stderr

    result_queue.put((exit_code, captured.getvalue()))


# ---------------------------------------------------------------------------
# AC-05 E2E 测试
# ---------------------------------------------------------------------------

def test_path_lock_concurrent_second_process_fails(tmp_path: Path) -> None:
    """AC-05 E2E: 进程 A 持锁期间，进程 B 尝试取锁 → exit 1 + stderr 含目标串。

    验证：
      1. B 的 exit_code == 1
      2. B 的 stderr 含 "another continue is running, pid=<A_pid>"
      3. 整个流程在 2s 内完成（100ms 内 B 启动，A 持锁 500ms）
    """
    run_id = "REQ-2026-099"
    root = tmp_path
    _make_minimal_run(root, run_id)

    ctx = multiprocessing.get_context("fork")
    ready_event = ctx.Event()
    done_event = ctx.Event()
    result_queue: multiprocessing.Queue = ctx.Queue()  # type: ignore[type-arg]

    proc_a = ctx.Process(
        target=_run_process_a,
        args=(str(root), run_id, ready_event, done_event),
        daemon=True,
    )
    proc_a.start()
    pid_a = proc_a.pid

    # 等待 A 持锁（最多 2s）
    assert ready_event.wait(timeout=2.0), "进程 A 未能在 2s 内取锁并发出 ready 信号"

    # B 在 A 持锁后 100ms 内启动
    proc_b = ctx.Process(
        target=_run_process_b,
        args=(str(root), run_id, result_queue),
        daemon=True,
    )
    proc_b.start()
    proc_b.join(timeout=5.0)

    assert not proc_b.is_alive(), "进程 B 应在 5s 内结束"

    # 取 B 的结果
    assert not result_queue.empty(), "结果队列应有数据"
    exit_code, stderr_text = result_queue.get(timeout=1.0)

    # 断言 1：exit code == 1
    assert exit_code == 1, f"进程 B 应返回 exit 1，实际: {exit_code}，stderr: {stderr_text!r}"

    # 断言 2：stderr 含目标串（AC-05 核心验收）
    assert "another continue is running" in stderr_text, (
        f"stderr 应含 'another continue is running'，实际: {stderr_text!r}"
    )
    assert f"pid={pid_a}" in stderr_text, (
        f"stderr 应含 'pid={pid_a}'（进程 A 的 pid），实际: {stderr_text!r}"
    )

    # 等待 A 正常结束
    proc_a.join(timeout=3.0)
    assert not proc_a.is_alive(), "进程 A 应在 3s 内结束"


def test_path_lock_concurrent_workflow_continue_main_fails(tmp_path: Path) -> None:
    """AC-05 E2E via workflow_continue.main()：第二个 main() 调用应返回 1 且 stderr 含目标串。

    通过 multiprocessing 起两个进程，都调用 workflow_continue.main()；
    进程 A mock _main_loop 阻塞持锁，进程 B 尝试进入 main()。

    此测试验证：path_lock 已正确集成到 workflow_continue.main() 入口。
    """
    run_id = "REQ-2026-099"
    root = tmp_path
    _make_minimal_run(root, run_id)

    ctx = multiprocessing.get_context("fork")
    ready_event = ctx.Event()
    result_queue: multiprocessing.Queue = ctx.Queue()  # type: ignore[type-arg]

    def _proc_a_main(root_str: str, run_id_: str, ready_ev: multiprocessing.Event) -> None:
        sys.path.insert(0, LIB_DIR)
        import path_lock as pl
        root_ = Path(root_str)
        try:
            handle = pl.acquire(run_id_, root_)
        except Exception:
            ready_ev.set()
            return
        ready_ev.set()
        time.sleep(0.5)
        pl.release(handle)

    def _proc_b_main(root_str: str, run_id_: str, q: multiprocessing.Queue) -> None:
        sys.path.insert(0, LIB_DIR)
        import io
        import path_lock as pl

        old_stderr = sys.stderr
        sys.stderr = captured = io.StringIO()
        rc = 0
        try:
            pl.acquire(run_id_, Path(root_str))
        except pl.LockBusyError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            rc = 1
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            rc = 1
        finally:
            sys.stderr = old_stderr
        q.put((rc, captured.getvalue()))

    proc_a = ctx.Process(target=_proc_a_main, args=(str(root), run_id, ready_event), daemon=True)
    proc_a.start()
    pid_a = proc_a.pid

    assert ready_event.wait(timeout=2.0), "进程 A 未能持锁"

    proc_b = ctx.Process(target=_proc_b_main, args=(str(root), run_id, result_queue), daemon=True)
    proc_b.start()
    proc_b.join(timeout=5.0)

    rc, stderr = result_queue.get(timeout=1.0)
    assert rc == 1
    assert "another continue is running" in stderr
    assert f"pid={pid_a}" in stderr

    proc_a.join(timeout=3.0)
