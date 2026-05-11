"""workflow_rollback 产物归档工具模块（F-007）。

提供：
- _collect_artifacts_to_archive: 收集需要归档的产物路径列表
- _move_artifacts: 执行产物 mv
- _truncate_jsonl_to_tail: jsonl 截断 + tail 归档

详细设计：requirements/REQ-2026-009/artifacts/detailed-design.md §6.5
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _collect_artifacts_to_archive(
    run_dir: Path,
    nodes: list[dict[str, Any]],
    run_state: Any,
    to_node: str,
) -> list[Path]:
    """收集需要 mv 到 .archived 的产物文件列表。

    策略：to_node 之后（不含 to_node）所有已完成节点的产物目录/文件。
    """
    from workflow_rollback_topology import _get_ordered_node_ids
    ordered = _get_ordered_node_ids(nodes)
    to_pos = ordered.index(to_node) if to_node in ordered else -1

    artifacts: list[Path] = []
    # 找 to_node 之后的节点（含当前运行中的）
    nodes_to_archive = ordered[to_pos + 1:] if to_pos >= 0 else []

    for nid in nodes_to_archive:
        # 节点对应的产物目录
        node_dir = run_dir / nid
        if node_dir.is_dir():
            artifacts.append(node_dir)
        # 节点直接产物文件（output.json 等扁平文件）
        for f in run_dir.glob(f"{nid}.*"):
            if f.is_file() and f not in artifacts:
                artifacts.append(f)

    return artifacts


def _move_artifacts(
    artifacts: list[Path],
    archive_root: Path,
) -> list[Path]:
    """把产物列表 mv 到 archive_root 下（保持相对路径结构）。

    返回已成功 mv 的路径列表。
    """
    moved: list[Path] = []
    for src in artifacts:
        if not src.exists():
            logger.debug("跳过已不存在的产物路径：%s", src)
            continue
        dest = archive_root / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved.append(src)
        logger.debug("mv artifact: %s → %s", src, dest)
    return moved


def _truncate_jsonl_to_tail(
    jsonl_path: Path,
    archive_root: Path,
    to_node: str,
    ordered_nodes: list[str],
    events: list[dict[str, Any]] | None = None,
) -> tuple[Path, list[Any]]:
    """把 jsonl 中 to_node 完成之后的事件 mv 到 archive_root/run-state.jsonl.tail。

    参数：
        jsonl_path    — 原始 jsonl 文件路径
        archive_root  — 归档根目录
        to_node       — 截断基准节点（保留其 node_completed 及之前的事件）
        ordered_nodes — 拓扑排序节点 ID 列表
        events        — 可选：已解析的事件列表（不为 None 时跳过重读，避免双读 jsonl）

    返回：(tail_path, kept_events)
    - tail_path：归档的 tail 文件绝对路径
    - kept_events：保留在原 jsonl 中的事件列表（to_node 完成处及之前）
    """
    from run_state import read_events

    if not jsonl_path.is_file():
        # jsonl 不存在时建空 tail
        tail_path = archive_root / "run-state.jsonl.tail"
        tail_path.touch()
        return tail_path, []

    if events is None:
        events, _ = read_events(jsonl_path)

    # 找 to_node 的 node_completed 事件位置（最后一次出现）
    cut_idx = _find_jsonl_cut_index(events, to_node)

    kept = events[:cut_idx]
    tail = events[cut_idx:]

    tail_path = archive_root / "run-state.jsonl.tail"
    tail_path.parent.mkdir(parents=True, exist_ok=True)

    # F-24 三步原子化（消"两个文件同时含尾部事件"中间态）：
    # 1) 先写 <jsonl>.new（截短后内容）
    # 2) 写 tail_path（归档尾部事件）
    # 3) os.replace(<jsonl>.new, jsonl) 原子覆盖
    # KI 落 1 → 仅 .new 残留，续跑可清理；落 2 → tail 与 .new 共存，续跑用 .new；
    # 落 3 → 原子完成。任意中间态都不会出现"两个文件同时含尾部事件"。
    # F-8 (rev6)：三步加 logger.debug + 包 RollbackError，运维可观察 jsonl_path / archive_root 上下文。
    from workflow_rollback import RollbackError  # 惰性 import 避免循环依赖

    new_path = jsonl_path.with_suffix(jsonl_path.suffix + ".new")
    try:
        with new_path.open("w", encoding="utf-8") as fh:
            for evt in kept:
                fh.write(json.dumps(evt, ensure_ascii=False) + "\n")
        logger.debug("truncate 步骤 1 完成（new_path=%s）", new_path)

        with tail_path.open("w", encoding="utf-8") as fh:
            for evt in tail:
                fh.write(json.dumps(evt, ensure_ascii=False) + "\n")
        logger.debug("truncate 步骤 2 完成（tail_path=%s）", tail_path)

        os.replace(str(new_path), str(jsonl_path))
        logger.debug("truncate 步骤 3 完成（jsonl=%s）", jsonl_path)
    except OSError as exc:
        raise RollbackError(
            f"truncate jsonl 失败（jsonl_path={jsonl_path}，archive_root={archive_root}）：{exc}"
        ) from exc
    return tail_path, kept


def _find_jsonl_cut_index(events: list[dict[str, Any]], to_node: str) -> int:
    """找 to_node 的 node_completed 事件之后的第一个位置（即截断点）。

    若找不到 to_node 的 node_completed，则截断点 = 0（全部 mv 为 tail）。
    """
    cut_idx = 0
    for i, evt in enumerate(events):
        if evt.get("type") == "node_completed" and evt.get("node_id") == to_node:
            cut_idx = i + 1  # 保留到 node_completed 本身（含）
    return cut_idx
