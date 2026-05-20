"""tests for scripts/lib/context_usage_report.py（F-004 + F-008 验收测试）。

覆盖：
  F-004：ContextInventory.scan 的 5 条验收标准
    1. scan 返回 list[KnowledgeFile]，5 字段齐全（path / rel_path / kind / size_bytes / fs_mtime）
    2. kind 字段：team / project 按 rel_path 第二段判定
    3. ignore_patterns 生效（`**/draft/**` → draft 目录被排除）
    4. INDEX.md 自身被排除
    5. context_dir 不存在 → FileNotFoundError

  F-008：fetch_git_timestamps 的主路径与异常回退
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

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))

from context_usage_report import (  # noqa: E402
    ContextInventory,
    GitTimestamp,
    KnowledgeFile,
    fetch_git_timestamps,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """造一棵最小可用 context/ 树。

    布局（rel_path）：
      context/INDEX.md                          ← 入口（应被剔除）
      context/team/foo.md                       ← team kind
      context/team/draft/wip.md                 ← draft 目录（测试 ignore）
      context/project/myproj/INDEX.md           ← 子 INDEX（应被剔除）
      context/project/myproj/bar.md             ← project kind
    """
    ctx = tmp_path / "context"
    (ctx / "team").mkdir(parents=True)
    (ctx / "team" / "draft").mkdir()
    (ctx / "project" / "myproj").mkdir(parents=True)

    (ctx / "INDEX.md").write_text("# root index\n", encoding="utf-8")
    (ctx / "team" / "foo.md").write_text("# foo\n", encoding="utf-8")
    (ctx / "team" / "draft" / "wip.md").write_text("# wip\n", encoding="utf-8")
    (ctx / "project" / "myproj" / "INDEX.md").write_text("# proj idx\n", encoding="utf-8")
    (ctx / "project" / "myproj" / "bar.md").write_text("# bar\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# AC-1 · scan 返回 KnowledgeFile，5 字段完整
# ---------------------------------------------------------------------------


def test_scan_returns_knowledge_files_with_full_fields(fake_repo: Path) -> None:
    """所有字段非空且类型正确，path 是绝对路径，rel_path 是 POSIX 相对路径。"""
    inv = ContextInventory(
        context_dir=fake_repo / "context",
        ignore_patterns=[],
        repo_root=fake_repo,
    )

    files = inv.scan()
    assert files, "至少应扫到 1 个非 INDEX 的 md"
    for kf in files:
        assert isinstance(kf, KnowledgeFile)
        assert kf.path.is_absolute()
        assert kf.path.exists()
        assert kf.rel_path.startswith("context/")
        assert "/" in kf.rel_path  # POSIX 风格
        assert kf.kind in ("team", "project")
        assert kf.size_bytes >= 0
        assert isinstance(kf.fs_mtime, datetime)


# ---------------------------------------------------------------------------
# AC-2 · kind 按 rel_path 第二段判定
# ---------------------------------------------------------------------------


def test_scan_kind_distinguishes_team_and_project(fake_repo: Path) -> None:
    """context/team/foo.md → team；context/project/myproj/bar.md → project。"""
    inv = ContextInventory(
        context_dir=fake_repo / "context",
        ignore_patterns=[],
        repo_root=fake_repo,
    )
    by_rel = {kf.rel_path: kf.kind for kf in inv.scan()}

    assert by_rel.get("context/team/foo.md") == "team"
    assert by_rel.get("context/team/draft/wip.md") == "team"  # 嵌套也按第二段
    assert by_rel.get("context/project/myproj/bar.md") == "project"


# ---------------------------------------------------------------------------
# AC-3 · ignore_patterns 生效
# ---------------------------------------------------------------------------


def test_scan_ignore_patterns_excludes_draft(fake_repo: Path) -> None:
    """ignore=`**/draft/**` 应过滤 context/team/draft/wip.md。"""
    inv = ContextInventory(
        context_dir=fake_repo / "context",
        ignore_patterns=["**/draft/**"],
        repo_root=fake_repo,
    )
    rel_paths = {kf.rel_path for kf in inv.scan()}

    assert "context/team/draft/wip.md" not in rel_paths
    # 非 draft 文件仍在
    assert "context/team/foo.md" in rel_paths
    assert "context/project/myproj/bar.md" in rel_paths


# ---------------------------------------------------------------------------
# AC-4 · INDEX.md 自身被排除
# ---------------------------------------------------------------------------


def test_scan_excludes_index_md(fake_repo: Path) -> None:
    """两层 INDEX.md（context/INDEX.md, context/project/myproj/INDEX.md）都不返回。"""
    inv = ContextInventory(
        context_dir=fake_repo / "context",
        ignore_patterns=[],
        repo_root=fake_repo,
    )
    rel_paths = {kf.rel_path for kf in inv.scan()}

    assert not any(p.endswith("INDEX.md") for p in rel_paths), (
        f"INDEX.md 不应出现在结果里，实际：{rel_paths}"
    )


# ---------------------------------------------------------------------------
# AC-5 · context_dir 不存在 → FileNotFoundError
# ---------------------------------------------------------------------------


def test_init_raises_when_context_dir_missing(tmp_path: Path) -> None:
    """目录不存在时 __init__ 立即抛 FileNotFoundError，不延迟到 scan。"""
    with pytest.raises(FileNotFoundError):
        ContextInventory(
            context_dir=tmp_path / "missing",
            ignore_patterns=[],
            repo_root=tmp_path,
        )


# ---------------------------------------------------------------------------
# 幂等性 · 多次调用返回等价结果（detailed-design.md §组件 1 幂等约定）
# ---------------------------------------------------------------------------


def test_scan_is_idempotent(fake_repo: Path) -> None:
    """连续两次 scan 在 fs 不变的前提下返回字段值相同的列表。"""
    inv = ContextInventory(
        context_dir=fake_repo / "context",
        ignore_patterns=[],
        repo_root=fake_repo,
    )
    first = inv.scan()
    second = inv.scan()
    assert [kf.rel_path for kf in first] == [kf.rel_path for kf in second]
    assert [kf.kind for kf in first] == [kf.kind for kf in second]
    assert [kf.size_bytes for kf in first] == [kf.size_bytes for kf in second]


# ---------------------------------------------------------------------------
# F-008 · fetch_git_timestamps 测试（主路径 + 异常回退）
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """造一个真实 git 仓库，包含 context/team/*.md，多个 commit。

    布局：
      context/team/foo.md    ← commit 1, 2
      context/team/bar.md    ← commit 2
    """
    import os

    # 初始化 git 仓库
    repo = tmp_path
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # 创建 context 目录
    ctx = repo / "context" / "team"
    ctx.mkdir(parents=True)

    # Commit 1：创建 foo.md（时间戳固定便于测试）
    foo_path = ctx / "foo.md"
    foo_path.write_text("# Foo\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "context/team/foo.md"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    env1 = os.environ.copy()
    env1["GIT_COMMITTER_DATE"] = "2026-05-01T10:00:00+00:00"
    env1["GIT_AUTHOR_DATE"] = "2026-05-01T10:00:00+00:00"
    subprocess.run(
        ["git", "commit", "-m", "Add foo.md"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env1,
    )

    # Commit 2：修改 foo.md + 创建 bar.md
    foo_path.write_text("# Foo\nUpdated\n", encoding="utf-8")
    bar_path = ctx / "bar.md"
    bar_path.write_text("# Bar\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "context/team/foo.md", "context/team/bar.md"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    env2 = os.environ.copy()
    env2["GIT_COMMITTER_DATE"] = "2026-05-10T15:30:00+00:00"
    env2["GIT_AUTHOR_DATE"] = "2026-05-10T15:30:00+00:00"
    subprocess.run(
        ["git", "commit", "-m", "Update foo, add bar"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env2,
    )

    return repo


def test_fetch_git_timestamps_main_path(git_repo: Path) -> None:
    """主路径：git log 成功解析，返回 first/last commit 时间戳，source='git_log'。"""
    # 构造 KnowledgeFile 对象
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

    # 验证返回结构
    assert isinstance(result, dict)
    assert "context/team/foo.md" in result
    assert "context/team/bar.md" in result
    assert warnings == []

    # 验证 foo.md：两次提交（首次 5-01，最后 5-10）
    foo_ts = result["context/team/foo.md"]
    assert isinstance(foo_ts, GitTimestamp)
    assert foo_ts.source == "git_log"
    assert foo_ts.first_commit_at is not None
    assert foo_ts.last_commit_at is not None
    assert foo_ts.first_commit_at.tzinfo == timezone.utc
    assert foo_ts.last_commit_at.tzinfo == timezone.utc
    # first_commit_at 应是 5-01，last_commit_at 应是 5-10
    assert foo_ts.first_commit_at.day == 1
    assert foo_ts.last_commit_at.day == 10

    # 验证 bar.md：仅一次提交（5-10）
    bar_ts = result["context/team/bar.md"]
    assert bar_ts.source == "git_log"
    assert bar_ts.first_commit_at is not None
    assert bar_ts.last_commit_at is not None
    assert bar_ts.first_commit_at == bar_ts.last_commit_at
    assert bar_ts.first_commit_at.day == 10

    # 验证时区统一与精度：microsecond 应为 0
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

    # 验证回退
    assert "context/team/foo.md" in result
    ts = result["context/team/foo.md"]
    assert ts.source == "fs_mtime"
    assert ts.first_commit_at is None
    assert ts.last_commit_at == now

    # 验证 warnings
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
    # 调用时不指定 repo_root，应使用 Path.cwd()，不报错
    result, warnings = fetch_git_timestamps(files, since_days=90)
    assert result == {}
    assert warnings == []
