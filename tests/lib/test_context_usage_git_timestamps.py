"""F-008 · fetch_git_timestamps 测试（主路径 + 异常回退）。

覆盖：
  6. 主路径：git log 解析，返回 first/last commit_at 与 source="git_log"
  7. 时区统一：UTC，microsecond=0
  8. 回退路径：subprocess 失败 → source="fs_mtime", first_commit_at=None
  9. git 缺失：FileNotFoundError → 同回退路径
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))

from context_usage_report import (  # noqa: E402
    GitTimestamp,
    KnowledgeFile,
    fetch_git_timestamps,
)


def test_fetch_git_timestamps_main_path(git_repo: Path) -> None:
    """主路径：git log 成功解析，返回 first/last commit 时间戳，source='git_log'。"""
    foo_stat = (git_repo / "context" / "team" / "foo.md").stat()
    bar_stat = (git_repo / "context" / "team" / "bar.md").stat()

    files = [
        KnowledgeFile(
            path=git_repo / "context" / "team" / "foo.md",
            rel_path="context/team/foo.md",
            kind="team",
            size_bytes=foo_stat.st_size,
            fs_mtime=datetime.fromtimestamp(
                int(foo_stat.st_mtime), tz=timezone.utc
            ),
        ),
        KnowledgeFile(
            path=git_repo / "context" / "team" / "bar.md",
            rel_path="context/team/bar.md",
            kind="team",
            size_bytes=bar_stat.st_size,
            fs_mtime=datetime.fromtimestamp(
                int(bar_stat.st_mtime), tz=timezone.utc
            ),
        ),
    ]

    result, warnings = fetch_git_timestamps(
        files,
        since_days=90,
        repo_root=git_repo,
    )

    assert isinstance(result, dict)
    assert "context/team/foo.md" in result
    assert "context/team/bar.md" in result
    assert warnings == []

    # foo.md：两次提交（首次 5-01，最后 5-10）
    foo_ts = result["context/team/foo.md"]
    assert isinstance(foo_ts, GitTimestamp)
    assert foo_ts.source == "git_log"
    assert foo_ts.first_commit_at is not None
    assert foo_ts.last_commit_at is not None
    assert foo_ts.first_commit_at.tzinfo == timezone.utc
    assert foo_ts.last_commit_at.tzinfo == timezone.utc
    assert foo_ts.first_commit_at.day == 1
    assert foo_ts.last_commit_at.day == 10

    # bar.md：仅一次提交（5-10）
    bar_ts = result["context/team/bar.md"]
    assert bar_ts.source == "git_log"
    assert bar_ts.first_commit_at is not None
    assert bar_ts.last_commit_at is not None
    assert bar_ts.first_commit_at == bar_ts.last_commit_at
    assert bar_ts.first_commit_at.day == 10

    # 时区统一与精度：microsecond 应为 0
    assert foo_ts.first_commit_at.microsecond == 0
    assert foo_ts.last_commit_at.microsecond == 0
    assert bar_ts.first_commit_at.microsecond == 0
    assert bar_ts.last_commit_at.microsecond == 0


def test_fetch_git_timestamps_timezone_utc(git_repo: Path) -> None:
    """验证时区统一为 UTC，秒精度（microsecond=0）。"""
    files = [
        KnowledgeFile(
            path=git_repo / "context" / "team" / "foo.md",
            rel_path="context/team/foo.md",
            kind="team",
            size_bytes=100,
            fs_mtime=datetime.now(tz=timezone.utc).replace(microsecond=0),
        ),
    ]

    result, _ = fetch_git_timestamps(files, since_days=90, repo_root=git_repo)
    ts = result["context/team/foo.md"]

    if ts.first_commit_at is not None:
        assert ts.first_commit_at.tzinfo == timezone.utc
        assert ts.first_commit_at.microsecond == 0
    if ts.last_commit_at is not None:
        assert ts.last_commit_at.tzinfo == timezone.utc
        assert ts.last_commit_at.microsecond == 0


@patch("context_usage_report.subprocess.run")
def test_fetch_git_timestamps_subprocess_failure(mock_run: MagicMock) -> None:
    """异常回退：subprocess 抛 CalledProcessError → source='fs_mtime', first=None。"""
    mock_run.side_effect = subprocess.CalledProcessError(1, "git log")

    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    files = [
        KnowledgeFile(
            path=Path("/fake/context/team/foo.md"),
            rel_path="context/team/foo.md",
            kind="team",
            size_bytes=100,
            fs_mtime=now,
        ),
    ]

    result, warnings = fetch_git_timestamps(
        files,
        since_days=90,
        repo_root=Path("/fake"),
    )

    assert "context/team/foo.md" in result
    ts = result["context/team/foo.md"]
    assert ts.source == "fs_mtime"
    assert ts.first_commit_at is None
    assert ts.last_commit_at == now

    assert len(warnings) == 1
    assert "git log 失败" in warnings[0]
    assert "CalledProcessError" in warnings[0]


@patch("context_usage_report.subprocess.run")
def test_fetch_git_timestamps_git_missing(mock_run: MagicMock) -> None:
    """异常回退：FileNotFoundError（git 缺失）→ source='fs_mtime'。"""
    mock_run.side_effect = FileNotFoundError("git not found")

    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    files = [
        KnowledgeFile(
            path=Path("/fake/context/team/foo.md"),
            rel_path="context/team/foo.md",
            kind="team",
            size_bytes=100,
            fs_mtime=now,
        ),
    ]

    result, warnings = fetch_git_timestamps(
        files,
        since_days=90,
        repo_root=Path("/fake"),
    )

    ts = result["context/team/foo.md"]
    assert ts.source == "fs_mtime"
    assert ts.first_commit_at is None
    assert ts.last_commit_at == now
    assert len(warnings) == 1
    assert "git log 失败" in warnings[0]
    assert "FileNotFoundError" in warnings[0]


@patch("context_usage_report.subprocess.run")
def test_fetch_git_timestamps_oserror(mock_run: MagicMock) -> None:
    """异常回退：OSError → source='fs_mtime'。"""
    mock_run.side_effect = OSError("Permission denied")

    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    files = [
        KnowledgeFile(
            path=Path("/fake/context/team/foo.md"),
            rel_path="context/team/foo.md",
            kind="team",
            size_bytes=100,
            fs_mtime=now,
        ),
    ]

    result, warnings = fetch_git_timestamps(
        files,
        since_days=90,
        repo_root=Path("/fake"),
    )

    ts = result["context/team/foo.md"]
    assert ts.source == "fs_mtime"
    assert ts.first_commit_at is None
    assert ts.last_commit_at == now
    assert len(warnings) == 1
    assert "git log 失败" in warnings[0] or "OSError" in warnings[0], (
        f"OSError warning 文本不符: {warnings[0]}"
    )


@patch("context_usage_report.subprocess.run")
def test_fetch_git_timestamps_timeout(mock_run: MagicMock) -> None:
    """异常回退：subprocess.TimeoutExpired → source='fs_mtime', warnings 标记超时。

    F-008 rev2 修复：subprocess.run 加 timeout=30s，避免大仓库 / git 卡死时无限阻塞。
    """
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="git log", timeout=30)

    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    files = [
        KnowledgeFile(
            path=Path("/fake/context/team/foo.md"),
            rel_path="context/team/foo.md",
            kind="team",
            size_bytes=100,
            fs_mtime=now,
        ),
    ]

    result, warnings = fetch_git_timestamps(
        files,
        since_days=90,
        repo_root=Path("/fake"),
    )

    ts = result["context/team/foo.md"]
    assert ts.source == "fs_mtime"
    assert ts.first_commit_at is None
    assert ts.last_commit_at == now
    assert len(warnings) == 1
    assert "git log 超时" in warnings[0]
    assert "30s" in warnings[0]


def test_fetch_git_timestamps_empty_files() -> None:
    """边界情况：空文件列表 → 返回空 dict + 空 warnings。"""
    result, warnings = fetch_git_timestamps(
        [],
        since_days=90,
        repo_root=Path.cwd(),
    )
    assert result == {}
    assert warnings == []


def test_fetch_git_timestamps_default_repo_root() -> None:
    """repo_root 缺省为 Path.cwd()。"""
    files = []
    result, warnings = fetch_git_timestamps(files, since_days=90)
    assert result == {}
    assert warnings == []
