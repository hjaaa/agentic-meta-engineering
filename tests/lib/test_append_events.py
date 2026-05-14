"""tests for scripts/lib/append_events.py（F-001 验收测试）。

覆盖：
  AC-1  3 事件 payload < 4KB → 单次 LOCK_EX 写 jsonl，顺序一致
  AC-2  5KB payload → raise PayloadTooLargeError，jsonl 无副作用
  AC-3  reject reason 5KB 走 append_events_with_manifest → manifest + index + ref
  AC-4  manifest tmp 写失败 → 不写 jsonl，raise OSError
  AC-5  event type 不在 VALID_EVENT_TYPES → raise WorkflowError
  AC-6  多进程并发 append → index.txt 含 2 行不交错
  AC-7  v6 反向回归：单字段 3.6KB 但 batch < 4KB → 直写不落 manifest
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# 将 scripts/lib 加入 path，与既有测试保持一致
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))

from append_events import (
    MAX_BATCH_PAYLOAD_BYTES,
    MAX_INLINE_FIELD_BYTES,
    PayloadTooLargeError,
    append_events,
    append_events_with_manifest,
)
from common import WorkflowError


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _make_event(ev_type: str = "node_started", extra: dict | None = None) -> dict:
    """构造最小合法 event。"""
    ev: dict[str, Any] = {"type": ev_type, "ts": "2026-01-01T00:00:00Z"}
    if extra:
        ev.update(extra)
    return ev


def _read_jsonl(path: Path) -> list[dict]:
    lines = [l.strip() for l in path.read_text().splitlines() if l.strip()]
    return [json.loads(l) for l in lines]


# ---------------------------------------------------------------------------
# AC-1：3 事件 payload < 4KB → 单次写 jsonl，顺序一致
# ---------------------------------------------------------------------------

def test_ac1_three_events_written_in_order(tmp_path: Path) -> None:
    jsonl = tmp_path / "run.jsonl"
    events = [
        _make_event("node_started"),
        _make_event("node_completed"),
        _make_event("save"),
    ]
    # 确认 payload < 4KB
    blob = "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"
    assert len(blob.encode()) < MAX_BATCH_PAYLOAD_BYTES

    append_events(jsonl, events)

    rows = _read_jsonl(jsonl)
    assert len(rows) == 3
    assert [r["type"] for r in rows] == ["node_started", "node_completed", "save"]


def test_ac1_auto_stamp_ts(tmp_path: Path) -> None:
    """缺 ts 字段时自动补 ISO8601 UTC。"""
    jsonl = tmp_path / "run.jsonl"
    ev = {"type": "node_started"}
    append_events(jsonl, [ev])
    rows = _read_jsonl(jsonl)
    assert "ts" in rows[0]
    assert rows[0]["ts"].endswith("Z")


def test_ac1_parent_dir_autocreate(tmp_path: Path) -> None:
    """父目录不存在时自动创建。"""
    jsonl = tmp_path / "a" / "b" / "run.jsonl"
    append_events(jsonl, [_make_event()])
    assert jsonl.exists()


def test_ac1_empty_list_noop(tmp_path: Path) -> None:
    """空 list → 不创建文件，直接返回。"""
    jsonl = tmp_path / "run.jsonl"
    append_events(jsonl, [])
    assert not jsonl.exists()


# ---------------------------------------------------------------------------
# AC-2：5KB payload → raise PayloadTooLargeError，jsonl 无副作用
# ---------------------------------------------------------------------------

def test_ac2_payload_too_large_raises_and_no_file(tmp_path: Path) -> None:
    jsonl = tmp_path / "run.jsonl"
    big_data = "x" * 5000
    ev = _make_event("node_started", {"data": big_data})

    with pytest.raises(PayloadTooLargeError) as exc_info:
        append_events(jsonl, [ev])

    assert exc_info.value.size >= MAX_BATCH_PAYLOAD_BYTES
    # jsonl 不应被创建（写之前就拒绝）
    assert not jsonl.exists()


def test_ac2_payload_too_large_existing_file_unchanged(tmp_path: Path) -> None:
    """jsonl 已存在时，超限写入不污染已有内容。"""
    jsonl = tmp_path / "run.jsonl"
    # 先写一个合法事件
    append_events(jsonl, [_make_event("save")])
    original = jsonl.read_bytes()

    big_data = "x" * 5000
    ev = _make_event("node_started", {"data": big_data})
    with pytest.raises(PayloadTooLargeError):
        append_events(jsonl, [ev])

    assert jsonl.read_bytes() == original


# ---------------------------------------------------------------------------
# AC-3：reject reason 5KB 走 manifest → manifest 文件 + index + jsonl ref
# ---------------------------------------------------------------------------

def test_ac3_manifest_written_for_large_reason(tmp_path: Path) -> None:
    jsonl = tmp_path / "run.jsonl"
    run_dir = tmp_path / "run"
    reason = "r" * 5000  # > MAX_INLINE_FIELD_BYTES(3500)

    ev = _make_event("approval_rejected", {"data": {"reason": reason}})

    append_events_with_manifest(
        jsonl, [ev], large_field_paths=[("data", "reason")], run_dir=run_dir
    )

    # jsonl 应存在
    assert jsonl.exists()
    rows = _read_jsonl(jsonl)
    assert len(rows) == 1
    row = rows[0]

    # 原字段删除，reason_ref 存在
    assert "reason" not in row.get("data", {})
    ref = row["data"]["reason_ref"]
    assert "path" in ref and "size" in ref and "sha256" in ref

    # manifest 文件存在且内容 sha256 匹配
    manifest_file = run_dir / ref["path"]
    assert manifest_file.exists()
    content = manifest_file.read_bytes()
    assert hashlib.sha256(content).hexdigest() == ref["sha256"]
    assert len(content) == ref["size"]

    # index.txt 追加了一行
    index = run_dir / "manifest" / "index.txt"
    assert index.exists()
    lines = [l for l in index.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    parts = lines[0].split()
    assert parts[2] == ref["sha256"]


# ---------------------------------------------------------------------------
# AC-4：manifest tmp 写失败 → 不写 jsonl，raise OSError
# ---------------------------------------------------------------------------

def test_ac4_manifest_write_failure_no_jsonl(tmp_path: Path) -> None:
    jsonl = tmp_path / "run.jsonl"
    run_dir = tmp_path / "run"
    reason = "r" * 5000

    ev = _make_event("approval_rejected", {"data": {"reason": reason}})

    with mock.patch("os.fsync", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            append_events_with_manifest(
                jsonl, [ev], large_field_paths=[("data", "reason")], run_dir=run_dir
            )

    # jsonl 不应被写入
    assert not jsonl.exists()


def test_ac4_os_replace_failure_no_jsonl(tmp_path: Path) -> None:
    jsonl = tmp_path / "run.jsonl"
    run_dir = tmp_path / "run"
    reason = "r" * 5000

    ev = _make_event("approval_rejected", {"data": {"reason": reason}})

    with mock.patch("os.replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError, match="replace failed"):
            append_events_with_manifest(
                jsonl, [ev], large_field_paths=[("data", "reason")], run_dir=run_dir
            )

    assert not jsonl.exists()


# ---------------------------------------------------------------------------
# AC-5：event type 不在 VALID_EVENT_TYPES → raise WorkflowError
# ---------------------------------------------------------------------------

def test_ac5_invalid_event_type_raises(tmp_path: Path) -> None:
    jsonl = tmp_path / "run.jsonl"
    ev = {"type": "not_a_valid_type", "ts": "2026-01-01T00:00:00Z"}

    with pytest.raises(WorkflowError, match="不在白名单"):
        append_events(jsonl, [ev])


def test_ac5_invalid_type_in_manifest_path(tmp_path: Path) -> None:
    """append_events_with_manifest 也应拒绝非白名单 type。"""
    jsonl = tmp_path / "run.jsonl"
    run_dir = tmp_path / "run"
    ev = {"type": "unknown_type", "data": {"reason": "x" * 5000}}

    with pytest.raises(WorkflowError, match="不在白名单"):
        append_events_with_manifest(
            jsonl, [ev], large_field_paths=[("data", "reason")], run_dir=run_dir
        )


def test_ac5_non_dict_event_raises(tmp_path: Path) -> None:
    jsonl = tmp_path / "run.jsonl"

    with pytest.raises(WorkflowError, match="event 必须是 dict"):
        append_events(jsonl, ["not_a_dict"])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# AC-6：多进程并发写 index.txt → 2 行不交错，sha256 一致
# ---------------------------------------------------------------------------

def _worker_append_manifest(
    jsonl_path_str: str,
    run_dir_str: str,
    reason: str,
) -> None:
    """子进程入口：写一个带大 reason 的 approval_rejected 事件。"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))
    from append_events import append_events_with_manifest

    jsonl = Path(jsonl_path_str)
    run_dir = Path(run_dir_str)
    ev = {
        "type": "approval_rejected",
        "ts": "2026-01-01T00:00:00Z",
        "data": {"reason": reason},
    }
    append_events_with_manifest(
        jsonl, [ev], large_field_paths=[("data", "reason")], run_dir=run_dir
    )


def test_ac6_concurrent_index_append(tmp_path: Path) -> None:
    jsonl = tmp_path / "run.jsonl"
    run_dir = tmp_path / "run"
    reason = "r" * 5000  # 5KB > MAX_INLINE_FIELD_BYTES

    p1 = multiprocessing.Process(
        target=_worker_append_manifest,
        args=(str(jsonl), str(run_dir), reason),
    )
    p2 = multiprocessing.Process(
        target=_worker_append_manifest,
        args=(str(jsonl), str(run_dir), reason),
    )
    p1.start()
    p2.start()
    p1.join(timeout=30)
    p2.join(timeout=30)

    assert p1.exitcode == 0, f"Process 1 failed with code {p1.exitcode}"
    assert p2.exitcode == 0, f"Process 2 failed with code {p2.exitcode}"

    # index.txt 应含 2 行
    index = run_dir / "manifest" / "index.txt"
    assert index.exists()
    lines = [l for l in index.read_text().splitlines() if l.strip()]
    assert len(lines) == 2, f"Expected 2 lines in index.txt, got: {lines}"

    # 验证每行的 sha256 与对应 manifest 文件一致
    for line in lines:
        parts = line.split()
        event_id, field_dotted, sha256_hex, size_str = parts[0], parts[1], parts[2], parts[3]
        manifest_file = run_dir / "manifest" / f"{event_id}.txt"
        assert manifest_file.exists(), f"manifest file missing: {manifest_file}"
        content = manifest_file.read_bytes()
        assert hashlib.sha256(content).hexdigest() == sha256_hex

    # jsonl 应含 2 行
    rows = _read_jsonl(jsonl)
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# AC-7：v6 P2 反向回归 — 单字段 3.6KB 但 batch < 4KB → 直写不落 manifest
# ---------------------------------------------------------------------------

def test_ac7_small_batch_no_manifest_even_if_large_field(tmp_path: Path) -> None:
    jsonl = tmp_path / "run.jsonl"
    run_dir = tmp_path / "run"

    # 构造单字段 3.6KB（> MAX_INLINE_FIELD_BYTES=3500），但 batch < 4KB
    field_value = "a" * 3600  # 3600 bytes > 3500
    ev = _make_event("approval_rejected", {"data": {"reason": field_value}})

    # 验证 batch < 4KB
    blob = json.dumps(ev, ensure_ascii=False) + "\n"
    assert len(blob.encode()) < MAX_BATCH_PAYLOAD_BYTES, "test setup: batch should be < 4KB"

    append_events_with_manifest(
        jsonl, [ev], large_field_paths=[("data", "reason")], run_dir=run_dir
    )

    # manifest 目录不应有新文件（AC-7 核心断言）
    manifest_dir = run_dir / "manifest"
    if manifest_dir.exists():
        manifest_files = [f for f in manifest_dir.iterdir() if f.name != "index.txt"]
        assert len(manifest_files) == 0, f"Unexpected manifest files: {manifest_files}"

    # jsonl 应直写，字段保留 inline
    assert jsonl.exists()
    rows = _read_jsonl(jsonl)
    assert len(rows) == 1
    row = rows[0]
    assert row["data"]["reason"] == field_value  # inline 字段完整保留
    assert "reason_ref" not in row.get("data", {})


# ---------------------------------------------------------------------------
# 边界：path tuple 不存在时跳过（不报错）
# ---------------------------------------------------------------------------

def test_missing_path_tuple_skipped(tmp_path: Path) -> None:
    """large_field_paths 中指向不存在字段时，跳过而非报错。"""
    jsonl = tmp_path / "run.jsonl"
    run_dir = tmp_path / "run"

    # 构造一个 batch < 4KB 的事件，large_field_paths 指向不存在字段 → 不报错，直写 jsonl
    ev = _make_event("approval_rejected", {"data": {"reason": "small payload"}})

    append_events_with_manifest(
        jsonl, [ev], large_field_paths=[("data", "nonexistent")], run_dir=run_dir
    )

    # 无报错，jsonl 正常写入
    assert jsonl.exists()
    rows = _read_jsonl(jsonl)
    assert len(rows) == 1

    # 没有 manifest 文件产生（不存在的 path 被跳过）
    manifest_dir = run_dir / "manifest"
    if manifest_dir.exists():
        txt_files = list(manifest_dir.glob("*.txt"))
        assert len(txt_files) == 0, f"Unexpected manifest files: {txt_files}"


def test_missing_nested_path_skipped(tmp_path: Path) -> None:
    """nested path tuple 指向不存在的嵌套字段时，跳过而非 KeyError。"""
    jsonl = tmp_path / "run.jsonl"
    run_dir = tmp_path / "run"

    # batch ≥ 4KB，但 large_field_paths 指向不存在的嵌套 key → 被跳过 → 仍超限 PayloadTooLargeError
    big_payload = "x" * 5000
    ev = _make_event("approval_rejected", {"data": {"reason": big_payload}})

    # ("data", "nonexistent") 不存在，跳过，reason 未被外置，batch 仍超限
    with pytest.raises(PayloadTooLargeError):
        append_events_with_manifest(
            jsonl, [ev], large_field_paths=[("data", "nonexistent")], run_dir=run_dir
        )

    # jsonl 不应被写入
    assert not jsonl.exists()
