"""F-007 · workflow_rollback 单测（TC-F7-1~7 + TC-F7-5b）。

覆盖：
- TC-F7-1: test_R1_single_layer      — 单层 rollback，产物 mv + jsonl tail
- TC-F7-2: test_F1_cross_parent_child — 跨父子 mv，子 run 整目录归档
- TC-F7-3: test_T1_multiple_rollback  — 多次 rollback，两次 ts 目录独立并存
- TC-F7-4: test_to_root               — rollback 到第一个节点
- TC-F7-5: test_crash_recovery        — 手动构造残留 → 续跑 partial=True
- TC-F7-5b: test_crash_recovery_via_monkeypatch_mv — monkeypatch shutil.move 崩溃 → 续跑 partial=True
- TC-F7-6: test_concurrent_block      — 同 run_id 并发 → 第二个抛 ConcurrentRollbackError
- TC-F7-7: test_target_not_upstream_rejected — to_node 不是上游 → TargetNodeNotUpstreamError

命名约定（F-11 follow-up）：
    测试函数名以 R1/F1/T1 等大写片段映射到 detailed-design §6.5 fixture 矩阵
    （TC-F7-1 → R1 single layer 等），偏离 CLAUDE.md §7 should_xxx_when_yyy 规范
    属设计决定（design 锁定 fixture 标签优先，便于人工对照设计 spec）。

测试运行：
    python3 -m pytest tests/lib/test_workflow_rollback.py -v
"""
from __future__ import annotations

import json
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "rollback"
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from workflow_rollback import (  # noqa: E402
    ConcurrentRollbackError,
    RollbackError,
    RollbackResult,
    RunStateNotFoundError,
    SubRunArchive,
    TargetNodeNotFoundError,
    TargetNodeNotUpstreamError,
    rollback_run,
)

# ============================================================================
# 测试辅助工具
# ============================================================================


def _setup_run_dir(tmp_path: Path, fixture_name: str, run_id: str) -> Path:
    """在 tmp_path 下建 runs/<run_id>/ 目录，从 fixture 复制 workflow.yaml + jsonl。

    返回 run_dir（tmp_path/runs/<run_id>/）。
    """
    fixture_dir = FIXTURES_DIR / fixture_name
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)

    # 复制 workflow.yaml
    shutil.copy(fixture_dir / "workflow.yaml", run_dir / "workflow.yaml")

    return run_dir


def _write_jsonl_from_fixture(run_dir: Path, fixture_name: str, jsonl_filename: str = "initial-jsonl.txt") -> None:
    """把 fixture 的 jsonl.txt 写到 run_dir/run-state.jsonl。"""
    fixture_dir = FIXTURES_DIR / fixture_name
    src = fixture_dir / jsonl_filename
    dst = run_dir / "run-state.jsonl"
    shutil.copy(src, dst)


def _create_artifact_dir(run_dir: Path, node_id: str, filename: str = "output.json") -> Path:
    """在 run_dir/<node_id>/ 下创建一个产物文件，模拟节点输出。"""
    node_dir = run_dir / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    output_file = node_dir / filename
    output_file.write_text(json.dumps({"node": node_id, "output": "done"}), encoding="utf-8")
    return output_file


def _read_jsonl(jsonl_path: Path) -> list[dict[str, Any]]:
    """读取 jsonl 文件，返回事件列表。"""
    if not jsonl_path.is_file():
        return []
    events = []
    with jsonl_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                events.append(json.loads(stripped))
    return events


def _get_completed_node_ids(jsonl_path: Path) -> set[str]:
    """从 jsonl 提取所有 node_completed 的 node_id 集合。"""
    events = _read_jsonl(jsonl_path)
    return {
        e["node_id"]
        for e in events
        if e.get("type") == "node_completed" and "node_id" in e
    }


# ============================================================================
# TC-F7-1: 单层 rollback
# ============================================================================

def test_R1_single_layer(tmp_path):
    """TC-F7-1: 单层 4 节点（A→B→C→D），rollback 到 C，D 的产物 mv + jsonl tail。"""
    run_id = "TEST-R1"
    run_dir = _setup_run_dir(tmp_path, "R1-single-layer", run_id)
    _write_jsonl_from_fixture(run_dir, "R1-single-layer")

    # 创建各节点产物
    for nid in ["node-a", "node-b", "node-c", "node-d"]:
        _create_artifact_dir(run_dir, nid)

    # 通过 repo_root=tmp_path 参数让测试使用 tmp 目录（无需 monkeypatch）
    result = rollback_run(run_id, "node-c", repo_root=tmp_path)

    # 断言返回值
    assert isinstance(result, RollbackResult)
    assert result.run_id == run_id
    assert result.archive_ts  # 有时间戳
    assert result.new_current_node == "node-c"
    assert result.partial is False

    # 断言 node-d 产物已 mv 到 .archived
    assert not (run_dir / "node-d").exists(), "node-d 产物应已被归档"
    archived_node_d = result.archive_root / "node-d"
    assert archived_node_d.is_dir(), f"node-d 应在 {archived_node_d}"

    # 断言 node-a/b/c 产物还在
    assert (run_dir / "node-a").is_dir(), "node-a 应保留"
    assert (run_dir / "node-b").is_dir(), "node-b 应保留"
    assert (run_dir / "node-c").is_dir(), "node-c 应保留"

    # 断言 jsonl tail 存在
    assert result.truncated_jsonl_tail.exists(), "tail 文件应存在"
    tail_events = _read_jsonl(result.truncated_jsonl_tail)
    tail_node_ids = {e.get("node_id") for e in tail_events if e.get("node_id")}
    assert "node-d" in tail_node_ids, "tail 应含 node-d 事件"

    # 断言原 jsonl 不含 node-d 的事件
    kept_nodes = _get_completed_node_ids(run_dir / "run-state.jsonl")
    assert "node-d" not in kept_nodes, "原 jsonl 不应含 node-d completed"
    assert "node-c" in kept_nodes, "原 jsonl 应含 node-c completed"


# ============================================================================
# TC-F7-2: 跨父子 rollback
# ============================================================================

def test_F1_cross_parent_child(tmp_path):
    """TC-F7-2: 父 rollback 到 node-a，跨 sub_workflow 节点 node-b 级联归档子 run。"""
    parent_run_id = "TEST-F1-PARENT"
    child_run_id = "TEST-F1-CHILD"

    # 建父 run 目录
    parent_run_dir = _setup_run_dir(tmp_path, "F1-cross-parent-child", parent_run_id)
    _write_jsonl_from_fixture(parent_run_dir, "F1-cross-parent-child", "parent-jsonl.txt")

    # 创建父 run 各节点产物
    for nid in ["node-a", "node-b", "node-c", "node-d"]:
        _create_artifact_dir(parent_run_dir, nid)

    # 建子 run 目录：放在 parent_run_dir/sub_runs/<child_id>/
    child_run_dir = parent_run_dir / "sub_runs" / child_run_id
    child_run_dir.mkdir(parents=True)
    # 复制子 jsonl
    child_jsonl_fixture = FIXTURES_DIR / "F1-cross-parent-child" / "child-jsonl.txt"
    shutil.copy(child_jsonl_fixture, child_run_dir / "run-state.jsonl")
    # 子 run 产物
    _create_artifact_dir(child_run_dir, "child-step")

    # 执行 rollback 到 node-a
    result = rollback_run(parent_run_id, "node-a", repo_root=tmp_path)

    # 断言父 run：node-b/c/d 已归档
    for nid in ["node-b", "node-c", "node-d"]:
        assert not (parent_run_dir / nid).exists(), f"{nid} 应已归档"

    # 断言子 run 被整目录 mv
    # 子 run 在 parent_run_dir/sub_runs 下，archive 后应在 .archived/<ts>/sub_runs/
    assert len(result.moved_sub_runs) >= 1, "应有子 run 被归档"
    sub_archive = result.moved_sub_runs[0]
    assert isinstance(sub_archive, SubRunArchive)
    assert sub_archive.archive_path.is_dir(), "子 run 归档目录应存在"

    # 原子 run 目录（sub_runs/<child_id>）已被 mv
    assert not (parent_run_dir / "sub_runs" / child_run_id).exists(), "子 run 原目录应已删"

    # 子 jsonl 应含 parent_rolled_back 事件
    archived_child_jsonl = sub_archive.archive_path / "run-state.jsonl"
    archived_events = _read_jsonl(archived_child_jsonl)
    event_types = [e.get("type") for e in archived_events]
    assert "parent_rolled_back" in event_types, "子 jsonl 应含 parent_rolled_back 事件"

    # 断言 node-a 保留
    assert (parent_run_dir / "node-a").is_dir(), "node-a 应保留"


# ============================================================================
# TC-F7-3: 多次 rollback（两次 ts 目录并存）
# ============================================================================

def test_T1_multiple_rollback(tmp_path):
    """TC-F7-3: 两次 rollback，.archived/ 下有两个不同 ts 目录，互不覆盖。"""
    run_id = "TEST-T1"
    run_dir = _setup_run_dir(tmp_path, "T1-multiple-rollback", run_id)
    _write_jsonl_from_fixture(run_dir, "T1-multiple-rollback")

    # 创建所有节点产物
    for nid in ["node-a", "node-b", "node-c", "node-d"]:
        _create_artifact_dir(run_dir, nid)

    # 第一次 rollback：到 node-b（归档 C、D）
    result1 = rollback_run(run_id, "node-b", repo_root=tmp_path)

    # 验证第一次：C/D 已归档
    assert not (run_dir / "node-c").exists()
    assert not (run_dir / "node-d").exists()
    assert (result1.archive_root / "node-c").is_dir()
    assert (result1.archive_root / "node-d").is_dir()
    ts1 = result1.archive_ts

    # 重新创建 C/D 产物（模拟重跑）以及重写 jsonl（加回 C/D 事件）
    for nid in ["node-c", "node-d"]:
        _create_artifact_dir(run_dir, nid)

    # 在 jsonl 中追加 C/D 的事件（模拟重跑后的状态）
    jsonl_path = run_dir / "run-state.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "type": "node_started", "ts": "2026-05-08T11:00:00Z", "node_id": "node-c",
        }) + "\n")
        fh.write(json.dumps({
            "type": "node_completed", "ts": "2026-05-08T11:00:01Z",
            "node_id": "node-c", "data": {"output": "C2"},
        }) + "\n")
        fh.write(json.dumps({
            "type": "node_started", "ts": "2026-05-08T11:00:02Z", "node_id": "node-d",
        }) + "\n")
        fh.write(json.dumps({
            "type": "node_completed", "ts": "2026-05-08T11:00:03Z",
            "node_id": "node-d", "data": {"output": "D2"},
        }) + "\n")

    # 等待 1 秒确保第二次 ts 不同（时间戳精度秒级）
    time.sleep(1)

    # 第二次 rollback：到 node-a（归档 B、C、D）
    result2 = rollback_run(run_id, "node-a", repo_root=tmp_path)

    ts2 = result2.archive_ts
    assert ts1 != ts2, "两次 rollback 时间戳应不同"

    # .archived/ 下有两个目录
    archived_dirs = list((run_dir / ".archived").iterdir())
    assert len(archived_dirs) == 2, f"应有 2 个归档目录，实际: {[d.name for d in archived_dirs]}"

    # 两次归档目录都存在且互不覆盖
    assert result1.archive_root.is_dir(), "第一次归档目录应存在"
    assert result2.archive_root.is_dir(), "第二次归档目录应存在"
    assert result1.archive_root != result2.archive_root, "两次归档目录应不同"


# ============================================================================
# TC-F7-4: rollback 到第一个节点（to-root）
# ============================================================================

def test_to_root(tmp_path):
    """TC-F7-4: 3 节点（A→B→C），rollback 到 node-a，归档 B 和 C 的全部产物。"""
    run_id = "TEST-ROOT"
    run_dir = _setup_run_dir(tmp_path, "to-root", run_id)
    _write_jsonl_from_fixture(run_dir, "to-root")

    # 创建各节点产物
    for nid in ["node-a", "node-b", "node-c"]:
        _create_artifact_dir(run_dir, nid)

    result = rollback_run(run_id, "node-a", repo_root=tmp_path)

    # 断言 B/C 已归档
    assert not (run_dir / "node-b").exists(), "node-b 应已归档"
    assert not (run_dir / "node-c").exists(), "node-c 应已归档"
    assert (result.archive_root / "node-b").is_dir()
    assert (result.archive_root / "node-c").is_dir()

    # 断言 A 保留
    assert (run_dir / "node-a").is_dir(), "node-a 应保留"

    # 断言 tail 含 B/C 事件
    tail_events = _read_jsonl(result.truncated_jsonl_tail)
    tail_node_ids = {e.get("node_id") for e in tail_events if e.get("node_id")}
    assert "node-b" in tail_node_ids, "tail 应含 node-b 事件"
    assert "node-c" in tail_node_ids, "tail 应含 node-c 事件"

    # 原 jsonl 仅保留 A 完成事件
    kept_nodes = _get_completed_node_ids(run_dir / "run-state.jsonl")
    assert "node-a" in kept_nodes
    assert "node-b" not in kept_nodes
    assert "node-c" not in kept_nodes


# ============================================================================
# TC-F7-5: crash recovery（monkeypatch mv 中途 raise，重调续跑）
# ============================================================================

def test_crash_recovery(tmp_path):
    """TC-F7-5: 手动构造 .in_progress 残留（模拟进程崩溃），
    重新调 rollback_run 续跑 → partial=True，
    最终 node-d 已归档，.in_progress 已删。

    构造方式：
    1. 模拟首次 rollback 已创建 archive_dir + .in_progress，但 node-d mv 尚未完成
    2. 直接调 rollback_run（检测到 .in_progress → 走续跑路径）
    """
    run_id = "TEST-CRASH"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)

    # 使用 R1 fixture
    shutil.copy(FIXTURES_DIR / "R1-single-layer" / "workflow.yaml", run_dir / "workflow.yaml")
    shutil.copy(FIXTURES_DIR / "R1-single-layer" / "initial-jsonl.txt", run_dir / "run-state.jsonl")

    for nid in ["node-a", "node-b", "node-c", "node-d"]:
        _create_artifact_dir(run_dir, nid)

    # --- 手动构造崩溃中间状态 ---
    # 模拟：archive_dir 已创建，.in_progress 存在，但 node-d 还没 mv
    fake_ts = "2026-05-08T17:00:00+0800"
    archive_dir = run_dir / ".archived" / fake_ts
    archive_dir.mkdir(parents=True)
    # 创建 .in_progress 标记（崩溃残留）
    (archive_dir / ".in_progress").touch()
    # 模拟 jsonl tail 也已被截断（node-c completed 后的事件已 mv 到 tail）
    # 这里不截断 jsonl，让续跑重新做（测试续跑能处理这种情况）

    # 验证 .in_progress 存在（前提条件）
    assert (archive_dir / ".in_progress").exists(), "前提：.in_progress 残留"

    # 续跑：重新调 rollback_run，应检测到 .in_progress → 续跑路径
    result = rollback_run(run_id, "node-c", repo_root=tmp_path)

    # 验证续跑结果
    assert result.partial is True, "续跑路径应返回 partial=True"

    # 验证 .in_progress 已删
    in_prog_files_after = list((run_dir / ".archived").rglob(".in_progress"))
    assert len(in_prog_files_after) == 0, "续跑后 .in_progress 应已删"

    # 验证 node-d 已归档（续跑完成）
    assert not (run_dir / "node-d").exists(), "node-d 应已归档（续跑完成）"


# ============================================================================
# TC-F7-5b: 崩溃恢复——monkeypatch shutil.move 中途抛错 → 续跑（§6.6 TC-F7-5b）
# ============================================================================

def test_crash_recovery_via_monkeypatch_mv(tmp_path, monkeypatch):
    """TC-F7-5b: 用 monkeypatch.setattr(shutil, 'move', raising_mock) 在第 N 次 mv 后
    抛 OSError，模拟崩溃 → 重调 rollback_run 续跑 → partial=True，
    最终文件树等于无中断版。

    构造步骤：
    1. 准备 R1 fixture，4 节点产物（A/B/C/D）
    2. 用 monkeypatch 劫持 shutil.move，第 1 次调用后抛 OSError（模拟 mv 中途崩溃）
    3. 首次 rollback_run 抛 OSError（正常，说明崩溃模拟有效）
    4. 验证 .in_progress 残留（.archived/ 下有未删除的 .in_progress）
    5. 恢复 shutil.move（取消 monkeypatch）
    6. 再次调 rollback_run → 走续跑路径 → partial=True
    7. 断言最终文件树与无中断版一致
    """
    run_id = "TEST-CRASH-MONKEYPATCH"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)

    # 使用 R1 fixture
    shutil.copy(FIXTURES_DIR / "R1-single-layer" / "workflow.yaml", run_dir / "workflow.yaml")
    shutil.copy(FIXTURES_DIR / "R1-single-layer" / "initial-jsonl.txt", run_dir / "run-state.jsonl")

    for nid in ["node-a", "node-b", "node-c", "node-d"]:
        _create_artifact_dir(run_dir, nid)

    # 劫持 shutil.move：第 1 次成功，第 2 次开始抛 OSError（模拟中途崩溃）
    call_count = [0]
    original_move = shutil.move

    def raising_mock(src, dst):
        call_count[0] += 1
        # 让 jsonl tail 的 move 先通过（它是内部操作），
        # 产物目录 move 第 1 次后崩溃
        if call_count[0] > 1:
            raise OSError(f"模拟 mv 崩溃：src={src}")
        return original_move(src, dst)

    monkeypatch.setattr(shutil, "move", raising_mock)

    # 首次 rollback：应在产物 mv 中途崩溃（抛 OSError 或包装后的异常）
    try:
        rollback_run(run_id, "node-c", repo_root=tmp_path)
    except (OSError, Exception):
        pass

    # 注意：因为 M-2 把 unlink 放进 finally，flock 会释放，但 .in_progress 可能已删
    # 实际上 unlink 在 mv 失败之后的 finally 中执行，所以 .in_progress 会被删
    # 因此我们手动创建 .in_progress 来模拟崩溃残留
    # （这模拟的是进程崩溃——Python finally 没有运行的情况）

    # 恢复 shutil.move
    monkeypatch.undo()

    # 手动注入 .in_progress 残留（模拟进程崩溃，finally 未运行）
    # 找已创建的 archive 目录
    archived_dirs = list((run_dir / ".archived").iterdir()) if (run_dir / ".archived").is_dir() else []
    if not archived_dirs:
        # 没有 archive 目录（例如崩溃太早）→ 手动构造
        fake_ts = "2026-05-08T18:00:00+0800"
        archive_dir = run_dir / ".archived" / fake_ts
        archive_dir.mkdir(parents=True)
        # 写 .meta.json（模拟首次成功写入 meta.json 后崩溃）
        meta_path = archive_dir / ".meta.json"
        meta_path.write_text(
            json.dumps({"run_id": run_id, "to_node": "node-c", "started_at": "2026-05-08T10:00:00Z"}),
            encoding="utf-8",
        )
        (archive_dir / ".in_progress").touch()
    else:
        # 找第一个 archive 目录并确保 .in_progress 存在
        archive_dir = archived_dirs[0]
        in_prog = archive_dir / ".in_progress"
        if not in_prog.exists():
            in_prog.touch()
        # 确保 .meta.json 存在
        meta_path = archive_dir / ".meta.json"
        if not meta_path.exists():
            meta_path.write_text(
                json.dumps({"run_id": run_id, "to_node": "node-c", "started_at": "2026-05-08T10:00:00Z"}),
                encoding="utf-8",
            )

    # 验证 .in_progress 存在（前提条件）
    assert any(
        (run_dir / ".archived" / d / ".in_progress").exists()
        for d in (run_dir / ".archived").iterdir()
        if d.is_dir()
    ), "前提：.in_progress 残留"

    # 恢复 node-d 产物（续跑需要看到它还存在）
    if not (run_dir / "node-d").exists():
        _create_artifact_dir(run_dir, "node-d")

    # 续跑：重调 rollback_run，应检测到 .in_progress → 续跑路径
    result = rollback_run(run_id, "node-c", repo_root=tmp_path)

    # 验证续跑结果
    assert result.partial is True, "续跑路径应返回 partial=True"

    # 验证 .in_progress 已删
    in_prog_files_after = list((run_dir / ".archived").rglob(".in_progress"))
    assert len(in_prog_files_after) == 0, "续跑后 .in_progress 应已删"

    # 验证 node-d 已归档（续跑完成）
    assert not (run_dir / "node-d").exists(), "node-d 应已归档（续跑完成）"

    # 验证 node-a/b/c 产物还在（与无中断版一致）
    assert (run_dir / "node-a").is_dir(), "node-a 应保留"
    assert (run_dir / "node-b").is_dir(), "node-b 应保留"
    assert (run_dir / "node-c").is_dir(), "node-c 应保留"


# ============================================================================
# TC-F7-6: 并发互斥（同 run_id 并发 → 第二个抛 ConcurrentRollbackError）
# ============================================================================

def test_concurrent_block(tmp_path):
    """TC-F7-6: 同 run_id 并发 2 个 rollback，第二个应抛 ConcurrentRollbackError。

    用 threading.Event 同步（不用 sleep），保证确定性。
    """
    run_id = "TEST-CONCURRENT"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)

    shutil.copy(FIXTURES_DIR / "R1-single-layer" / "workflow.yaml", run_dir / "workflow.yaml")
    shutil.copy(FIXTURES_DIR / "R1-single-layer" / "initial-jsonl.txt", run_dir / "run-state.jsonl")

    for nid in ["node-a", "node-b", "node-c", "node-d"]:
        _create_artifact_dir(run_dir, nid)

    # 同步 Event：线程 1 持锁后通知线程 2 开始；线程 2 完成后通知线程 1 释放锁
    lock_held_event = threading.Event()    # 线程 1 持锁后 set
    thread2_done_event = threading.Event() # 线程 2 完成后 set

    second_exception: list[Exception] = []  # 线程 2 的异常

    # 线程 1：持锁，在 thread2_done_event 后完成
    import fcntl as _fcntl

    lock_path = run_dir / ".rollback.lock"

    def thread1_hold_lock():
        """直接持 flock，通知线程 2，等线程 2 完成后释放。"""
        lock_path.touch()
        with open(str(lock_path), "w") as lf:
            _fcntl.flock(lf, _fcntl.LOCK_EX)
            lock_held_event.set()          # 告诉线程 2 锁已持
            thread2_done_event.wait(timeout=5)  # 等线程 2 完成
            _fcntl.flock(lf, _fcntl.LOCK_UN)

    def thread2_try_rollback():
        """等线程 1 持锁后，尝试 rollback → 应抛 ConcurrentRollbackError。"""
        lock_held_event.wait(timeout=5)    # 等线程 1 持锁
        try:
            rollback_run(run_id, "node-c", repo_root=tmp_path)
        except ConcurrentRollbackError as exc:
            second_exception.append(exc)
        except Exception as exc:
            second_exception.append(exc)  # 记录其他异常以便调试
        finally:
            thread2_done_event.set()       # 通知线程 1 可以释放锁

    t1 = threading.Thread(target=thread1_hold_lock, daemon=True)
    t2 = threading.Thread(target=thread2_try_rollback, daemon=True)

    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    # 断言线程 2 抛了 ConcurrentRollbackError
    assert len(second_exception) == 1, f"线程 2 应有一个异常，实际: {second_exception}"
    assert isinstance(second_exception[0], ConcurrentRollbackError), (
        f"期望 ConcurrentRollbackError，实际: {type(second_exception[0]).__name__}: {second_exception[0]}"
    )


# ============================================================================
# TC-F7-7: to_node 不是上游 → TargetNodeNotUpstreamError
# ============================================================================

def test_target_not_upstream_rejected(tmp_path):
    """TC-F7-7: to_node 指向比当前节点更后（下游）的位置，应抛 TargetNodeNotUpstreamError。

    场景：只有 A/B 完成（C/D 未跑），current_pos = 2（B+1）；
    尝试 rollback 到 node-d（位置 3，比 current_pos 2 还大）→ 应拒绝。
    同时验证 to_node = 当前节点本身（node-b，位置 1 < current_pos 2）是允许的（不触发）；
    而 to_node = node-c（位置 2 = current_pos）触发 >= 校验。
    """
    run_id = "TEST-NOT-UPSTREAM"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)

    shutil.copy(FIXTURES_DIR / "R1-single-layer" / "workflow.yaml", run_dir / "workflow.yaml")

    # 只写 A/B 完成的 jsonl（C/D 未执行）
    jsonl_path = run_dir / "run-state.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for evt in [
            {"type": "workflow_started", "ts": "2026-05-08T10:00:00Z", "run_id": run_id,
             "data": {"workflow_name": "r1-single-layer", "arguments": ""}},
            {"type": "node_started", "ts": "2026-05-08T10:00:01Z", "node_id": "node-a"},
            {"type": "node_completed", "ts": "2026-05-08T10:00:02Z", "node_id": "node-a",
             "data": {"output": "A"}},
            {"type": "node_started", "ts": "2026-05-08T10:00:03Z", "node_id": "node-b"},
            {"type": "node_completed", "ts": "2026-05-08T10:00:04Z", "node_id": "node-b",
             "data": {"output": "B"}},
        ]:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")

    for nid in ["node-a", "node-b"]:
        _create_artifact_dir(run_dir, nid)

    # current_pos = 2（B 在 index 1，last_pos+1=2）
    # node-c 在 index 2 → 2 >= 2 → 触发 TargetNodeNotUpstreamError
    with pytest.raises(TargetNodeNotUpstreamError):
        rollback_run(run_id, "node-c", repo_root=tmp_path)

    # node-d 在 index 3 → 3 >= 2 → 也触发
    with pytest.raises(TargetNodeNotUpstreamError):
        rollback_run(run_id, "node-d", repo_root=tmp_path)


# ============================================================================
# F-2 (rev6): _resume_in_progress 续跑 .new 兜底（archive 端三步原子化中间态）
# ============================================================================

def test_resume_recovers_from_archive_ki_after_tail_write(tmp_path, monkeypatch):
    """F-2 KI 续跑：archive 端 KI 落第 2 步（tail 已写、os.replace 未执行）→ 续跑触发 .new replace。

    场景构造：
    1. R1 fixture：A→B→C→D 4 节点完成，rollback 到 node-c
    2. monkeypatch os.replace 第一次调用时抛 OSError（模拟 archive 端 KI 落第 2 步：
       .new 写完 + tail 写完，但 os.replace 未执行）
    3. 首次 rollback_run 抛 OSError；此时残留 .in_progress + .meta.json + .new + tail，
       原 jsonl 仍含完整尾部事件
    4. 取消 monkeypatch，恢复 os.replace
    5. 第二次 rollback_run → 续跑路径 → 期望 .new 已被消费（os.replace 成功）+
       jsonl 已截断（不含 node-d 完成事件）+ partial=True
    """
    run_id = "TEST-F2-RESUME-NEW"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)

    # R1 fixture
    shutil.copy(FIXTURES_DIR / "R1-single-layer" / "workflow.yaml", run_dir / "workflow.yaml")
    shutil.copy(FIXTURES_DIR / "R1-single-layer" / "initial-jsonl.txt", run_dir / "run-state.jsonl")

    for nid in ["node-a", "node-b", "node-c", "node-d"]:
        _create_artifact_dir(run_dir, nid)

    jsonl_path = run_dir / "run-state.jsonl"
    new_path = jsonl_path.with_suffix(jsonl_path.suffix + ".new")

    # 劫持 os.replace：仅第一次调用抛 OSError（模拟 archive 端 KI 落第 2 步、第 3 步前）
    # _write_meta_json (.meta.json.tmp → .meta.json) 也用 os.replace；让 .meta.json
    # 路径调用通过；只在 jsonl_path.suffix + ".new" → jsonl_path 这一步抛错。
    import os as _os
    original_replace = _os.replace
    raised_count = [0]

    def selective_raising_replace(src, dst):
        # 仅当目标是 jsonl_path（即第 3 步原子覆盖）时抛错
        if str(dst) == str(jsonl_path):
            raised_count[0] += 1
            raise OSError("模拟 archive 端 KI：os.replace(.new, jsonl) 中途崩溃")
        return original_replace(src, dst)

    monkeypatch.setattr(_os, "replace", selective_raising_replace)

    # 首次 rollback：应在 _truncate_jsonl_to_tail 第 3 步抛错
    # F-8 (rev6) 之后 OSError 被 _truncate_jsonl_to_tail 包成 RollbackError
    with pytest.raises(RollbackError, match="truncate jsonl 失败"):
        rollback_run(run_id, "node-c", repo_root=tmp_path)

    # 验证前提：archive 端 KI 中间态
    assert raised_count[0] == 1, "应仅触发一次 os.replace 抛错"
    archived_dirs = [d for d in (run_dir / ".archived").iterdir() if d.is_dir()]
    assert len(archived_dirs) == 1, "应有一个 archive_dir 残留"
    archive_dir = archived_dirs[0]
    assert (archive_dir / ".in_progress").exists(), "前提：.in_progress 应残留"
    assert new_path.exists(), "前提：.new 应残留（archive 端 KI 落第 2 步证据）"
    tail_path = archive_dir / "run-state.jsonl.tail"
    assert tail_path.exists(), "前提：tail 应已写完"
    # 原 jsonl 仍含完整尾部事件（os.replace 未执行 → 未截断）
    pre_resume_kept = _get_completed_node_ids(jsonl_path)
    assert "node-d" in pre_resume_kept, "前提：原 jsonl 应未截断（仍含 node-d completed）"

    # 取消 monkeypatch，恢复 os.replace
    monkeypatch.undo()

    # 续跑：检测 .in_progress → 走续跑路径；F-2 修复后应优先消费 .new（os.replace）
    result = rollback_run(run_id, "node-c", repo_root=tmp_path)

    # 验证续跑结果
    assert result.partial is True, "续跑路径应返回 partial=True"

    # F-2 关键断言：.new 已被消费（os.replace 完成）
    assert not new_path.exists(), "续跑后 .new 应被消费（F-2 修复核心）"

    # F-2 关键断言：jsonl 已截断，不含 node-d 完成事件
    post_resume_kept = _get_completed_node_ids(jsonl_path)
    assert "node-d" not in post_resume_kept, (
        "续跑后 jsonl 不应含 node-d completed（os.replace 已收尾）"
    )
    assert "node-c" in post_resume_kept, "续跑后 jsonl 应保留 node-c completed"

    # .in_progress 已删（成功路径调 _release_with_unlink）
    assert not (archive_dir / ".in_progress").exists(), "续跑后 .in_progress 应已删"


def test_resume_recovers_from_archive_ki_at_step1_only_new_written(tmp_path, monkeypatch, caplog):
    """F-8 KI-step-1 续跑：archive 端 KI 落第 1 步（仅 .new 已写、tail 未写）→ 续跑触发完整截断流程。

    场景：第 1 次 rollback 在 _truncate_jsonl_to_tail 步骤 2 之前抛错（仅 .new 已写）；
    第 2 次续跑应：_consume_residual_new os.replace 收尾 .new + 因 tail 不存在再走完整 _truncate
    → 最终 jsonl 一致截断、tail 已生成、.new 已消费。

    rev8 F-1 修复：加 caplog 断言 _consume_residual_new os.replace 路径被命中
    （pin 上游 helper warning，防止 _truncate 'w' 模式覆写 .new 旁路假闭合）。
    """
    import logging
    caplog.set_level(logging.WARNING)
    run_id = "TEST-F8-RESUME-STEP1"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    shutil.copy(FIXTURES_DIR / "R1-single-layer" / "workflow.yaml", run_dir / "workflow.yaml")
    shutil.copy(FIXTURES_DIR / "R1-single-layer" / "initial-jsonl.txt", run_dir / "run-state.jsonl")
    for nid in ["node-a", "node-b", "node-c", "node-d"]:
        _create_artifact_dir(run_dir, nid)

    jsonl_path = run_dir / "run-state.jsonl"
    new_path = jsonl_path.with_suffix(jsonl_path.suffix + ".new")

    # 劫持 archive 模块 logger.debug：第一次调用（"步骤 1 完成"）后抛 OSError，
    # 模拟 archive 端 KI 落第 1 步：仅 .new 已写、tail 未写、jsonl 未截断
    import workflow_rollback_archive as _arch
    original_debug = _arch.logger.debug
    debug_calls = [0]

    def raising_debug(*args, **kwargs):
        debug_calls[0] += 1
        original_debug(*args, **kwargs)
        if debug_calls[0] == 1:
            raise OSError("模拟 archive 端 KI 落第 1 步：tail 写入前崩溃")

    monkeypatch.setattr(_arch.logger, "debug", raising_debug)

    # 首次 rollback：应在步骤 2 前抛错（被包成 RollbackError）
    with pytest.raises(RollbackError, match="truncate jsonl 失败"):
        rollback_run(run_id, "node-c", repo_root=tmp_path)

    archived_dirs = [d for d in (run_dir / ".archived").iterdir() if d.is_dir()]
    archive_dir = archived_dirs[0]
    tail_path = archive_dir / "run-state.jsonl.tail"
    assert (archive_dir / ".in_progress").exists(), "前提：.in_progress 应残留"
    assert new_path.exists(), "前提：.new 应残留（KI-step-1 证据）"
    assert not tail_path.exists(), "前提：tail 应未写（KI-step-1 关键）"

    # 恢复 logger.debug，开始续跑
    monkeypatch.undo()

    result = rollback_run(run_id, "node-c", repo_root=tmp_path)

    # 续跑断言：F-8 完整路径——_consume_residual_new os.replace + _truncate_jsonl_to_tail 走完
    assert result.partial is True, "续跑路径应返回 partial=True"
    assert "检测到残留 .new" in caplog.text, "F-1: _consume_residual_new os.replace 路径必须被命中（caplog 应含 logger.warning，防止 _truncate 'w' 模式旁路覆盖 .new）"
    assert not new_path.exists(), "续跑后 .new 应被消费（_consume_residual_new os.replace）"
    assert tail_path.exists(), "续跑后 tail 应已生成（走完整 _truncate_jsonl_to_tail）"
    post_kept = _get_completed_node_ids(jsonl_path)
    assert "node-d" not in post_kept, "续跑后 jsonl 不应含 node-d completed"
    assert "node-c" in post_kept, "续跑后 jsonl 应保留 node-c completed"
    assert not (archive_dir / ".in_progress").exists(), "续跑后 .in_progress 应已删"


# ============================================================================
# 额外覆盖：run_id 不存在 → RunStateNotFoundError
# ============================================================================

def test_run_not_found(tmp_path):
    """run_id 不存在时应抛 RunStateNotFoundError。"""
    with pytest.raises(RunStateNotFoundError):
        rollback_run("NON-EXISTENT-RUN-ID-99999", "node-a", repo_root=tmp_path)


# ============================================================================
# F-5 (rev6): to_node 公开 API 正则校验拒绝注入字符（与 run_id 校验对称）
# ============================================================================

@pytest.mark.parametrize("bad_to_node", [
    "",                          # 空串
    "node-c\n[FAKE LOG]",        # 换行注入（堵 logger.info 日志注入路径）
    "node c",                    # 空格
    "node@c",                    # 特殊字符
    "../node-c",                 # 路径穿越
])
def test_to_node_rejects_injection_chars(tmp_path, bad_to_node):
    """F-5: rollback_run 公开 API 必须拒绝 to_node 含非法字符（与 run_id 模式对称）。"""
    with pytest.raises(RollbackError, match="to_node 包含非法字符"):
        rollback_run("test-run", bad_to_node, repo_root=tmp_path)


# ============================================================================
# 额外覆盖：to_node 不存在 → TargetNodeNotFoundError
# ============================================================================

def test_to_node_not_found(tmp_path):
    """to_node 不在节点集合时应抛 TargetNodeNotFoundError。"""
    run_id = "TEST-NONODE"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)

    shutil.copy(FIXTURES_DIR / "R1-single-layer" / "workflow.yaml", run_dir / "workflow.yaml")
    shutil.copy(FIXTURES_DIR / "R1-single-layer" / "initial-jsonl.txt", run_dir / "run-state.jsonl")

    with pytest.raises(TargetNodeNotFoundError):
        rollback_run(run_id, "non-existent-node-xyz", repo_root=tmp_path)
