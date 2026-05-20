"""context_usage_git — F-008 git 时间戳查询组件。

负责：
  - GitTimestamp 数据载体 (frozen dataclass)
  - _parse_git_log_output: 解析 git log 原始输出 → {path: (first_dt, last_dt)}
  - _build_timestamp_result: 把解析结果与 KnowledgeFile 列表合并 → dict[str, GitTimestamp]

注意：fetch_git_timestamps 公开函数定义在 context_usage_report.py，以保持
测试 @patch("context_usage_report.subprocess.run") 的 patch 路径有效。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))


@dataclass(frozen=True)
class GitTimestamp:
    """git log 查询结果或 fs_mtime 回退的时间戳载体。

    三字段对应 detailed-design.md §数据结构（F-008）；frozen 便于放进 set/dict。
    """

    first_commit_at: datetime | None   # 文件首次提交（UTC，秒精度）；空仓/shallow → None
    last_commit_at: datetime | None    # 最近一次 commit（UTC，秒精度）
    source: Literal["git_log", "fs_mtime"]  # 数据来源


def _parse_git_log_output(output: str) -> dict[str, tuple[datetime, datetime]]:
    """解析 git log 原始输出，返回 {path: (first_dt, last_dt)}。

    git log 格式（newest-first）：
      hash|ISO8601
      (blank line)
      file1
      file2
      ...

    first_dt = 最早一次 commit 时间；last_dt = 最新一次 commit 时间。
    """
    timestamps: dict[str, tuple[datetime, datetime]] = {}

    if not output.strip():
        return timestamps

    lines = output.split("\n")
    current_commit_time: datetime | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if "|" in stripped:
            # 新 commit header（格式：hash|ISO8601）
            try:
                ts_str = stripped.split("|", 1)[1]
                current_commit_time = (
                    datetime.fromisoformat(ts_str)
                    .astimezone(timezone.utc)
                    .replace(microsecond=0)
                )
            except (ValueError, IndexError):
                current_commit_time = None
        elif current_commit_time is not None:
            # 文件路径：关联到当前 commit_time
            path = stripped
            if path not in timestamps:
                # git log newest-first，第一次见到是 last_commit_at
                timestamps[path] = (current_commit_time, current_commit_time)
            else:
                # 再次见到：更新 first_commit_at，保留已有 last_commit_at
                _, last = timestamps[path]
                timestamps[path] = (current_commit_time, last)

    return timestamps


def _build_timestamp_result(
    files: list,  # list[KnowledgeFile]
    ts_dict: dict[str, tuple[datetime, datetime]],
    fallback_source: Literal["fs_mtime"] = "fs_mtime",
) -> dict[str, GitTimestamp]:
    """根据解析结果和文件列表构造 {rel_path: GitTimestamp}。

    命中 ts_dict 的文件 source="git_log"；未命中的用 fs_mtime 回退。
    """
    result: dict[str, GitTimestamp] = {}
    for f in files:
        if f.rel_path in ts_dict:
            first, last = ts_dict[f.rel_path]
            result[f.rel_path] = GitTimestamp(
                first_commit_at=first,
                last_commit_at=last,
                source="git_log",
            )
        else:
            result[f.rel_path] = GitTimestamp(
                first_commit_at=None,
                last_commit_at=f.fs_mtime,
                source=fallback_source,
            )
    return result


