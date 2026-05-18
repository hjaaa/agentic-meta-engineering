"""
Tests for F-009 worktree documentation sync across submit/archive/SKILL commands.

Acceptance criteria:
1. submit.md contains "worktree retained at" + "use /requirement:archive to clean up" literals
2. archive.md contains "owner=workflow" + "路径白名单" + "主仓根" literals
3. archive.md CLI signature (H2 headings) unchanged from baseline
4. SKILL.md contains cross-link to archive.md
"""

from pathlib import Path


def test_submit_md_contains_worktree_retained_phrase():
    """submit.md must contain 'worktree retained at' + 'use /requirement:archive to clean up' literals."""
    text = Path(".claude/commands/requirement/submit.md").read_text(encoding="utf-8")
    assert "worktree retained at" in text, "Missing 'worktree retained at' in submit.md"
    assert "use /requirement:archive to clean up" in text, "Missing 'use /requirement:archive to clean up' in submit.md"


def test_archive_md_contains_triple_protection_phrases():
    """archive.md must contain owner=workflow / 路径白名单 / 主仓根 literals."""
    text = Path(".claude/commands/requirement/archive.md").read_text(encoding="utf-8")
    assert "owner=workflow" in text, "Missing 'owner=workflow' in archive.md"
    assert "路径白名单" in text, "Missing '路径白名单' in archive.md"
    assert "主仓根" in text, "Missing '主仓根' in archive.md"


def test_archive_md_cli_signature_unchanged():
    """archive.md H2 headings must preserve original interface signature sections."""
    text = Path(".claude/commands/requirement/archive.md").read_text(encoding="utf-8")

    # Baseline H2 headings that must exist (CLI contract frozen)
    required_headings = [
        "## 用途",
        "## 何时跑（前置约束 — 主 Agent 必读）",
        "## 分支位置（主 Agent 必读）",
        "## 参数",
        "## 预检（5 项硬门禁，任一 fail → exit 1）",
        "## 委托",
        "## 三问串行（默认 N）",
        "## 终端反馈格式（spec §5.3 第 5 步）",
        "## 退出码",
        "## 错误降级矩阵",
    ]

    for heading in required_headings:
        assert heading in text, f"Missing baseline heading '{heading}' in archive.md (H2 signature broken)"


def test_skill_md_cross_link_to_archive_md():
    """SKILL.md must contain cross-link reference to archive.md."""
    text = Path(".claude/skills/managing-requirement-lifecycle/SKILL.md").read_text(encoding="utf-8")
    assert "archive.md" in text, "Missing 'archive.md' cross-link in SKILL.md"
