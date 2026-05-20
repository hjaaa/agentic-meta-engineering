"""共用 pytest fixtures，供 tests/lib/test_context_usage_*.py 各模块使用。

工厂函数（非 fixture）在 _context_usage_helpers.py 中定义，各模块按需 import。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))


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


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """造一个真实 git 仓库，包含 context/team/*.md，多个 commit。

    布局：
      context/team/foo.md    ← commit 1, 2
      context/team/bar.md    ← commit 2
    """
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

    ctx = repo / "context" / "team"
    ctx.mkdir(parents=True)

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
