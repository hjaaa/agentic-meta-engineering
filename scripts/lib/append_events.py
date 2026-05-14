"""批量原子事件追加 + 4KB 上限校验 + manifest-pointer fallback（D-014）。

公开 API：
  - append_events(jsonl_path, events) → None
      原子批量追加（单次 LOCK_EX + 单次 os.write），R-T03 根除。
      payload 累计 ≥ MAX_BATCH_PAYLOAD_BYTES → raise PayloadTooLargeError。
  - append_events_with_manifest(jsonl_path, events, large_field_paths, run_dir) → None
      payload 超限时，按 large_field_paths 将指定字段落 manifest 文件 + jsonl 仅留 ref。
  - PayloadTooLargeError：单事件或批量超 4KB 时抛出（manifest fallback 后仍超才抛）。

D-014 决策：
  - 4KB = POSIX PIPE_BUF 保守跨平台原子写边界
  - 3.5KB = MAX_INLINE_FIELD_BYTES（每字段 inline 上限）
  - 4KB - 3.5KB = 500 字节冗余（含 ts/run_id/type 等顶层字段）
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from common import WorkflowError
from run_state import VALID_EVENT_TYPES

MAX_BATCH_PAYLOAD_BYTES: int = 4096        # D-014 POSIX PIPE_BUF 保守边界
MAX_INLINE_FIELD_BYTES: int = 3500         # 单字段 inline 上限（manifest 触发阈）


class PayloadTooLargeError(WorkflowError):
    """单事件或批量序列化后 ≥ 4KB（D-014）。"""

    def __init__(self, size: int, limit: int = MAX_BATCH_PAYLOAD_BYTES) -> None:
        super().__init__(
            f"batch payload {size} bytes ≥ {limit} bytes (POSIX 原子写上限)"
        )
        self.size = size
        self.limit = limit


def _estimate_blob_bytes(events: list[dict[str, Any]]) -> bytes:
    """序列化 events 为 utf-8 blob（dry-run / 正式写共用同一序列化逻辑）。"""
    payloads = [json.dumps(e, ensure_ascii=False) for e in events]
    return ("\n".join(payloads) + "\n").encode("utf-8")


def _validate_and_stamp(events: list[dict[str, Any]]) -> None:
    """校验 event type 白名单；缺 ts 时自动补 ISO8601 UTC（in-place）。"""
    for event in events:
        if not isinstance(event, dict):
            raise WorkflowError("event 必须是 dict")
        ev_type = event.get("type")
        if not ev_type or ev_type not in VALID_EVENT_TYPES:
            raise WorkflowError(f"event type {ev_type!r} 不在白名单")
        if "ts" not in event:
            event["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_jsonl(jsonl_path: Path, blob_bytes: bytes) -> None:
    """单次 LOCK_EX + 单次 os.write 原子追加。父目录不存在时自动创建。"""
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(jsonl_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.write(fd, blob_bytes)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def append_events(jsonl_path: Path, events: list[dict[str, Any]]) -> None:
    """单次 LOCK_EX + 单次 os.write 写多条事件（R-T03 根除）。

    Raises:
        WorkflowError: events 中包含非白名单 type 或非 dict。
        PayloadTooLargeError: 拼接后字节数 ≥ MAX_BATCH_PAYLOAD_BYTES。
        OSError: 文件 IO 失败。
    """
    if not events:
        return
    _validate_and_stamp(events)
    blob_bytes = _estimate_blob_bytes(events)
    if len(blob_bytes) >= MAX_BATCH_PAYLOAD_BYTES:
        raise PayloadTooLargeError(len(blob_bytes))
    _atomic_write_jsonl(jsonl_path, blob_bytes)


def _get_nested(obj: dict[str, Any], path: tuple[str, ...]) -> Any | None:
    """按 path tuple 钻取嵌套字段值，任意层缺失返回 None。"""
    cur: Any = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _set_nested(obj: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """按 path tuple 设置嵌套字段（最后一层 key 写入 value）。"""
    cur: dict[str, Any] = obj
    for key in path[:-1]:
        cur = cur[key]
    cur[path[-1]] = value


def _del_nested(obj: dict[str, Any], path: tuple[str, ...]) -> None:
    """按 path tuple 删除嵌套字段（最后一层 key 删除）。"""
    cur: dict[str, Any] = obj
    for key in path[:-1]:
        cur = cur[key]
    cur.pop(path[-1], None)


def _persist_field_to_manifest(
    field_value: str,
    event_id: str,
    run_dir: Path,
) -> tuple[str, int, str]:
    """将字段值写入 manifest/<event_id>.txt（tmp + fsync + replace 原子语义）。

    Returns:
        (manifest_relative_path, size_bytes, sha256_hex)

    Raises:
        OSError: 写入、fsync 或 replace 失败时直接抛出，调用方不写 jsonl。
    """
    manifest_dir = run_dir / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{event_id}.txt"
    tmp_path = manifest_path.with_suffix(".tmp")

    field_bytes = field_value.encode("utf-8")
    sha256_hex = hashlib.sha256(field_bytes).hexdigest()
    size = len(field_bytes)

    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, field_bytes)
        os.fsync(fd)
    finally:
        os.close(fd)

    os.replace(str(tmp_path), str(manifest_path))

    return f"manifest/{event_id}.txt", size, sha256_hex


def _append_index_line(
    run_dir: Path,
    event_id: str,
    field_dotted: str,
    sha256_hex: str,
    size: int,
) -> None:
    """以 LOCK_EX 锁 index.txt fd 后追加一行（AC-6 多进程并发安全）。

    Raises:
        OSError: 文件 IO 失败。
    """
    index_path = run_dir / "manifest" / "index.txt"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{event_id} {field_dotted} {sha256_hex} {size}\n"
    fd = os.open(str(index_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def append_events_with_manifest(
    jsonl_path: Path,
    events: list[dict[str, Any]],
    large_field_paths: list[tuple[str, ...]],
    run_dir: Path,
) -> None:
    """payload 超限时按 large_field_paths 落 manifest（D-014 二段触发算法）。

    Args:
        large_field_paths: 形如 [("data", "reason")] 表示
            event["data"]["reason"] 字段允许被外置 manifest。

    流程（v6 修订，对抗 P2 反向回归）：
      1. dry-run 估算字节数
      2. 若 < 4KB → 直接 append_events 直写，不扫单字段，不落 manifest
      3. 若 ≥ 4KB → 扫描 large_field_paths，单字段 ≥ MAX_INLINE_FIELD_BYTES 外置
      4. 重新 dry-run；若仍 ≥ 4KB → raise PayloadTooLargeError
      5. 否则 append_events 直写

    Raises:
        PayloadTooLargeError: manifest fallback 后仍超 4KB
        OSError: manifest 文件写失败（不写 jsonl，原样抛出）
        WorkflowError: event type 不在白名单
    """
    if not events:
        return

    # 校验 + 补 ts（in-place，使后续 dry-run 序列化结果与最终写入一致）
    _validate_and_stamp(events)

    # 第一段 dry-run
    blob_bytes = _estimate_blob_bytes(events)
    if len(blob_bytes) < MAX_BATCH_PAYLOAD_BYTES:
        # 直写，不触碰 manifest（AC-7 二段触发关键）
        _atomic_write_jsonl(jsonl_path, blob_bytes)
        return

    # ≥ 4KB → 扫描 large_field_paths，外置大字段
    seq = 0
    for event in events:
        for path in large_field_paths:
            field_value = _get_nested(event, path)
            if field_value is None:
                continue
            field_str = str(field_value)
            if len(field_str.encode("utf-8")) < MAX_INLINE_FIELD_BYTES:
                continue

            # 生成唯一 event_id（ts + type + uuid，避免并发碰撞）
            ts_compact = event.get("ts", "").replace(":", "").replace("-", "")
            ev_type = event.get("type", "unknown")
            event_id = f"{ts_compact}-{ev_type}-{uuid4().hex[:8]}-{seq}"
            seq += 1

            # 写 manifest（tmp + fsync + replace）；任一失败直接抛 OSError，不写 jsonl
            rel_path, size, sha256_hex = _persist_field_to_manifest(
                field_str, event_id, run_dir
            )

            # 写 index.txt（LOCK_EX 保证并发原子，AC-6）
            field_dotted = ".".join(path)
            _append_index_line(run_dir, event_id, field_dotted, sha256_hex, size)

            # 替换原字段：删原字段 + 写 <name>_ref（以 acceptance #3 为准）
            _del_nested(event, path)
            ref_key = path[-1] + "_ref"
            parent_path = path[:-1]
            if parent_path:
                parent = _get_nested(event, parent_path)
                if isinstance(parent, dict):
                    parent[ref_key] = {
                        "path": rel_path,
                        "size": size,
                        "sha256": sha256_hex,
                    }
            else:
                event[ref_key] = {
                    "path": rel_path,
                    "size": size,
                    "sha256": sha256_hex,
                }

    # 第二段 dry-run
    blob_bytes = _estimate_blob_bytes(events)
    if len(blob_bytes) >= MAX_BATCH_PAYLOAD_BYTES:
        raise PayloadTooLargeError(len(blob_bytes))

    _atomic_write_jsonl(jsonl_path, blob_bytes)
