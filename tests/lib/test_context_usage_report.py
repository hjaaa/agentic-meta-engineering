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


# ---------------------------------------------------------------------------
# F-009 · UsageAggregator 测试
# ---------------------------------------------------------------------------

from context_usage_report import (  # noqa: E402
    AppliedEvidence,
    IndexGraphResult,
    KnowledgeStatus,
    ReferenceEvidence,
    UsageAggregator,
)

# ---------------------------------------------------------------------------
# 辅助工厂函数
# ---------------------------------------------------------------------------


def _make_file(rel_path: str, kind: str = "team") -> KnowledgeFile:
    """创建最小可用 KnowledgeFile。"""
    from pathlib import Path

    return KnowledgeFile(
        path=Path(f"/fake/{rel_path}"),
        rel_path=rel_path,
        kind=kind,  # type: ignore[arg-type]
        size_bytes=100,
        fs_mtime=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _make_index_result(
    indexed_by: dict | None = None,
    broken_links: list | None = None,
    orphans: list | None = None,
) -> IndexGraphResult:
    return IndexGraphResult(
        indexed_by=indexed_by or {},
        broken_links=broken_links or [],
        orphans=orphans or [],
    )


def _make_ref(
    target: str,
    source: str = "requirements/req/process.txt",
    line: int = 1,
    kind: str = "raw_path",
    context_line: str = "",
) -> ReferenceEvidence:
    return ReferenceEvidence(
        target=target,
        source=source,
        line=line,
        kind=kind,  # type: ignore[arg-type]
        context_line=context_line,
    )


def _make_applied(ref: ReferenceEvidence) -> AppliedEvidence:
    return AppliedEvidence(
        reference=ref,
        rule="window_hit",
        matched_keyword="按照",
        section_heading="## 设计",
    )


def _make_aggregator(
    inventory: list,
    indexed_by: dict | None = None,
    references: list | None = None,
    applied: list | None = None,
    git_timestamps: dict | None = None,
    now: datetime | None = None,
) -> UsageAggregator:
    return UsageAggregator(
        inventory=inventory,
        index_result=_make_index_result(indexed_by=indexed_by),
        references=references or [],
        applied=applied or [],
        git_timestamps=git_timestamps or {},
        now=now or datetime(2026, 5, 20, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# TC-1 ~ TC-8：状态机矩阵（详见 detailed-design.md L908-917）
# ---------------------------------------------------------------------------


def test_tc1_orphan() -> None:
    """TC-1：indexed=False, ref=0 → orphan。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/a.md")
    agg = _make_aggregator([file], indexed_by={}, now=now)
    summaries = agg.aggregate()
    assert len(summaries) == 1
    assert summaries[0].status == KnowledgeStatus.ORPHAN


def test_tc2_needs_review() -> None:
    """TC-2：indexed=False, ref=2, last_ref=5天前 → needs_review。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/b.md")
    last_commit = datetime(2026, 5, 15, tzinfo=timezone.utc)  # 5天前
    ref1 = _make_ref("context/team/b.md", source="requirements/r1/doc.md", line=1)
    ref2 = _make_ref("context/team/b.md", source="requirements/r1/doc.md", line=2)
    ts = GitTimestamp(
        first_commit_at=last_commit,
        last_commit_at=last_commit,
        source="git_log",
    )
    agg = _make_aggregator(
        [file],
        indexed_by={},  # not indexed
        references=[ref1, ref2],
        git_timestamps={"requirements/r1/doc.md": ts},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.NEEDS_REVIEW


def test_tc3_visible_unused() -> None:
    """TC-3：indexed=True, ref=0 → visible_unused。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/c.md")
    agg = _make_aggregator(
        [file],
        indexed_by={"context/team/c.md": ["context/INDEX.md"]},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.VISIBLE_UNUSED


def test_tc4_high_value() -> None:
    """TC-4：indexed=True, ref=3, applied=1, last_ref=10天前 → high_value。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/d.md")
    last_commit = datetime(2026, 5, 10, tzinfo=timezone.utc)  # 10天前
    refs = [
        _make_ref("context/team/d.md", source="requirements/r1/doc.md", line=i)
        for i in range(1, 4)
    ]
    applied = [_make_applied(refs[0])]
    ts = GitTimestamp(first_commit_at=last_commit, last_commit_at=last_commit, source="git_log")
    agg = _make_aggregator(
        [file],
        indexed_by={"context/team/d.md": ["context/INDEX.md"]},
        references=refs,
        applied=applied,
        git_timestamps={"requirements/r1/doc.md": ts},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.HIGH_VALUE


def test_tc5_high_value_over_stale() -> None:
    """TC-5：同时满足 high_value 与 stale 条件 → high_value（优先级高于 stale）。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/e.md")
    last_commit = datetime(2026, 1, 21, tzinfo=timezone.utc)  # 约119天前（>90天）
    refs = [
        _make_ref("context/team/e.md", source="requirements/r1/doc.md", line=i)
        for i in range(1, 6)
    ]
    applied = [_make_applied(refs[0]), _make_applied(refs[1])]
    ts = GitTimestamp(first_commit_at=last_commit, last_commit_at=last_commit, source="git_log")
    agg = _make_aggregator(
        [file],
        indexed_by={"context/team/e.md": ["context/INDEX.md"]},
        references=refs,
        applied=applied,
        git_timestamps={"requirements/r1/doc.md": ts},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.HIGH_VALUE


def test_tc6_stale_candidate() -> None:
    """TC-6：indexed=True, ref=2, applied=0, last_ref=100天前 → stale_candidate。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/f.md")
    last_commit = datetime(2026, 2, 9, tzinfo=timezone.utc)  # 100天前
    refs = [
        _make_ref("context/team/f.md", source="requirements/r1/doc.md", line=i)
        for i in range(1, 3)
    ]
    ts = GitTimestamp(first_commit_at=last_commit, last_commit_at=last_commit, source="git_log")
    agg = _make_aggregator(
        [file],
        indexed_by={"context/team/f.md": ["context/INDEX.md"]},
        references=refs,
        git_timestamps={"requirements/r1/doc.md": ts},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.STALE_CANDIDATE


def test_tc7_active() -> None:
    """TC-7：indexed=True, ref=2, applied=0, last_ref=10天前 → active。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/g.md")
    last_commit = datetime(2026, 5, 10, tzinfo=timezone.utc)  # 10天前
    refs = [
        _make_ref("context/team/g.md", source="requirements/r1/doc.md", line=i)
        for i in range(1, 3)
    ]
    ts = GitTimestamp(first_commit_at=last_commit, last_commit_at=last_commit, source="git_log")
    agg = _make_aggregator(
        [file],
        indexed_by={"context/team/g.md": ["context/INDEX.md"]},
        references=refs,
        git_timestamps={"requirements/r1/doc.md": ts},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.ACTIVE


def test_tc8_active_applied_but_ref_insufficient() -> None:
    """TC-8：indexed=True, ref=1, applied=1, last_ref=10天前 → active（applied有但ref不足3）。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/h.md")
    last_commit = datetime(2026, 5, 10, tzinfo=timezone.utc)  # 10天前
    ref = _make_ref("context/team/h.md", source="requirements/r1/doc.md", line=1)
    applied = [_make_applied(ref)]
    ts = GitTimestamp(first_commit_at=last_commit, last_commit_at=last_commit, source="git_log")
    agg = _make_aggregator(
        [file],
        indexed_by={"context/team/h.md": ["context/INDEX.md"]},
        references=[ref],
        applied=applied,
        git_timestamps={"requirements/r1/doc.md": ts},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.ACTIVE


# ---------------------------------------------------------------------------
# _compute_score 子项边界测试
# ---------------------------------------------------------------------------


def test_score_indexed_zero_and_two() -> None:
    """indexed=False → indexed_score=0；indexed=True → indexed_score=2。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    agg = _make_aggregator([], now=now)
    s_false = {"indexed": False, "reference_count": 0, "applied_signal_count": 0, "last_referenced_at": None}
    s_true = {"indexed": True, "reference_count": 0, "applied_signal_count": 0, "last_referenced_at": None}
    assert agg._compute_score(s_false, now) == 0
    assert agg._compute_score(s_true, now) == 2


def test_score_reference_count_cap() -> None:
    """reference_score = min(count*3, 30)：count=0/1/10/11。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    agg = _make_aggregator([], now=now)
    base = {"indexed": False, "applied_signal_count": 0, "last_referenced_at": None}
    assert agg._compute_score({**base, "reference_count": 0}, now) == 0
    assert agg._compute_score({**base, "reference_count": 1}, now) == 3
    assert agg._compute_score({**base, "reference_count": 10}, now) == 30
    assert agg._compute_score({**base, "reference_count": 11}, now) == 30  # cap


def test_score_applied_signal_count_cap() -> None:
    """applied_score = min(count*8, 40)：count=0/1/5/6。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    agg = _make_aggregator([], now=now)
    base = {"indexed": False, "reference_count": 0, "last_referenced_at": None}
    assert agg._compute_score({**base, "applied_signal_count": 0}, now) == 0
    assert agg._compute_score({**base, "applied_signal_count": 1}, now) == 8
    assert agg._compute_score({**base, "applied_signal_count": 5}, now) == 40
    assert agg._compute_score({**base, "applied_signal_count": 6}, now) == 40  # cap


def test_score_recency_boundaries() -> None:
    """recency_score 边界：None/30天/31天/90天/91天 → 0/10/5/5/0。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    agg = _make_aggregator([], now=now)
    base = {"indexed": False, "reference_count": 0, "applied_signal_count": 0}

    # last_referenced_at = None → 0
    assert agg._compute_score({**base, "last_referenced_at": None}, now) == 0

    # 30天前（刚好 <= 30） → 10
    ref_30d = datetime(2026, 4, 20, tzinfo=timezone.utc)  # 30天前
    assert agg._compute_score({**base, "last_referenced_at": ref_30d}, now) == 10

    # 31天前（> 30，<= 90） → 5
    ref_31d = datetime(2026, 4, 19, tzinfo=timezone.utc)  # 31天前
    assert agg._compute_score({**base, "last_referenced_at": ref_31d}, now) == 5

    # 90天前（刚好 <= 90） → 5
    ref_90d = datetime(2026, 2, 19, tzinfo=timezone.utc)  # 90天前
    assert agg._compute_score({**base, "last_referenced_at": ref_90d}, now) == 5

    # 91天前（> 90） → 0
    ref_91d = datetime(2026, 2, 18, tzinfo=timezone.utc)  # 91天前
    assert agg._compute_score({**base, "last_referenced_at": ref_91d}, now) == 0


def test_score_max_all_caps() -> None:
    """四子项全满时总分 = 82。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    agg = _make_aggregator([], now=now)
    ref_1d = datetime(2026, 5, 19, tzinfo=timezone.utc)
    s = {
        "indexed": True,
        "reference_count": 11,  # reference_score = 30（cap）
        "applied_signal_count": 6,  # applied_score = 40（cap）
        "last_referenced_at": ref_1d,  # recency = 10（30D）
    }
    assert agg._compute_score(s, now) == 82


# ---------------------------------------------------------------------------
# aggregate() 整链路冒烟测试
# ---------------------------------------------------------------------------


def test_aggregate_full_pipeline() -> None:
    """整链路冒烟：2个文件，验证长度/字段串联/时间戳/score范围/排序。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)

    file_a = _make_file("context/team/a.md")
    file_b = _make_file("context/team/b.md")

    # a 被 INDEX 挂载
    indexed_by = {"context/team/a.md": ["context/INDEX.md"]}

    # a 有 2 条引用（来自不同文件）
    ref_a1 = _make_ref("context/team/a.md", source="requirements/r1/doc1.md", line=5)
    ref_a2 = _make_ref("context/team/a.md", source="requirements/r2/doc2.md", line=10)
    # a 有 1 条 applied
    applied_a = _make_applied(ref_a1)

    # b 无引用、无 INDEX
    ts_r1 = GitTimestamp(
        first_commit_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        last_commit_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        source="git_log",
    )
    ts_r2 = GitTimestamp(
        first_commit_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        last_commit_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        source="git_log",
    )
    ts_a = GitTimestamp(
        first_commit_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_commit_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
        source="git_log",
    )

    agg = UsageAggregator(
        inventory=[file_a, file_b],
        index_result=_make_index_result(indexed_by=indexed_by),
        references=[ref_a1, ref_a2],
        applied=[applied_a],
        git_timestamps={
            "requirements/r1/doc1.md": ts_r1,
            "requirements/r2/doc2.md": ts_r2,
            "context/team/a.md": ts_a,
        },
        now=now,
    )
    summaries = agg.aggregate()

    # 输出长度 == len(inventory)
    assert len(summaries) == 2

    # 找到各 summary
    summary_a = next(s for s in summaries if s.path == "context/team/a.md")
    summary_b = next(s for s in summaries if s.path == "context/team/b.md")

    # a 字段验证
    assert summary_a.indexed is True
    assert summary_a.index_paths == ["context/INDEX.md"]
    assert summary_a.reference_count == 2
    assert summary_a.applied_signal_count == 1

    # last_referenced_at = max(ts_r1.last, ts_r2.last) = 2026-05-15
    assert summary_a.last_referenced_at == datetime(2026, 5, 15, tzinfo=timezone.utc)
    # first_referenced_at = min(ts_r1.first, ts_r2.first) = 2026-02-01
    assert summary_a.first_referenced_at == datetime(2026, 2, 1, tzinfo=timezone.utc)

    # last_modified_at 来自 git_timestamps
    assert summary_a.last_modified_at == datetime(2026, 5, 18, tzinfo=timezone.utc)
    assert summary_a.last_modified_at_source == "git_log"

    # score 在 [0, 82]
    assert 0 <= summary_a.score <= 82
    assert 0 <= summary_b.score <= 82

    # reference_evidences 按 (source, line) 升序
    assert summary_a.reference_evidences == sorted(
        [ref_a1, ref_a2], key=lambda e: (e.source, e.line)
    )
    # applied_evidences 非空
    assert len(summary_a.applied_evidences) == 1

    # b 是 orphan
    assert summary_b.status == KnowledgeStatus.ORPHAN

    # 按 score 降序排列（a 分高应在前）
    assert summaries[0].score >= summaries[1].score


def test_aggregate_last_modified_fallback_fs_mtime() -> None:
    """git_timestamps 无该文件条目时，last_modified_at 回退到 fs_mtime。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    fs_mtime = datetime(2026, 3, 15, tzinfo=timezone.utc)
    file = KnowledgeFile(
        path=Path("/fake/context/team/z.md"),
        rel_path="context/team/z.md",
        kind="team",
        size_bytes=50,
        fs_mtime=fs_mtime,
    )
    agg = _make_aggregator([file], git_timestamps={}, now=now)
    summaries = agg.aggregate()
    assert summaries[0].last_modified_at == fs_mtime
    assert summaries[0].last_modified_at_source == "fs_mtime"


def test_aggregate_output_length_equals_inventory() -> None:
    """输出长度恒等于 inventory 长度（含空 inventory）。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    agg_empty = _make_aggregator([], now=now)
    assert agg_empty.aggregate() == []

    files = [_make_file(f"context/team/f{i}.md") for i in range(5)]
    agg = _make_aggregator(files, now=now)
    assert len(agg.aggregate()) == 5


# ---------------------------------------------------------------------------
# now 注入测试：同一数据 + 不同 now → recency_score 不同
# ---------------------------------------------------------------------------


def test_aggregate_now_injection_changes_recency() -> None:
    """now 注入：同一 last_referenced_at，传不同 now，recency_score 不同。"""
    file = _make_file("context/team/x.md")
    last_commit = datetime(2026, 4, 20, tzinfo=timezone.utc)  # 固定引用时间

    ref = _make_ref("context/team/x.md", source="requirements/r1/doc.md", line=1)
    ts_ref = GitTimestamp(
        first_commit_at=last_commit,
        last_commit_at=last_commit,
        source="git_log",
    )

    def get_score(now: datetime) -> int:
        agg = UsageAggregator(
            inventory=[file],
            index_result=_make_index_result(),
            references=[ref],
            applied=[],
            git_timestamps={"requirements/r1/doc.md": ts_ref},
            now=now,
        )
        return agg.aggregate()[0].score

    # now = 2026-05-20 → delta = 30天 → recency=10
    score_30d = get_score(datetime(2026, 5, 20, tzinfo=timezone.utc))
    # now = 2026-06-20 → delta = 61天 → recency=5
    score_61d = get_score(datetime(2026, 6, 20, tzinfo=timezone.utc))
    # now = 2026-07-21 → delta = 92天 → recency=0
    score_92d = get_score(datetime(2026, 7, 21, tzinfo=timezone.utc))

    assert score_30d > score_61d > score_92d
