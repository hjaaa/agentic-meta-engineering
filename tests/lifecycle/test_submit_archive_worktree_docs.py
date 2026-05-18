"""F-009 验证：submit.md / archive.md / SKILL.md worktree 文档同步。

验收：
1. submit.md 含 "worktree retained at" + "use /requirement:archive to clean up" 字面量
2. archive.md 含 "owner=workflow" + "路径白名单" + "主仓根" 字面量
3. archive.md H2 接口签名段未被改造改动
4. SKILL.md 含对 archive.md 的交叉链接

testing 阶段 regression cleanup：路径锚定改为 REPO_ROOT，消除 cwd 依赖
（全量 pytest 时 tests/lib/test_routing_e2e.sh 切 cwd 不复原触发 FileNotFoundError）。
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_submit_md_contains_worktree_retained_phrase():
    """submit.md 必须含 'worktree retained at' + 'use /requirement:archive to clean up' 字面量。"""
    text = (REPO_ROOT / ".claude/commands/requirement/submit.md").read_text(encoding="utf-8")
    assert "worktree retained at" in text, "Missing 'worktree retained at' in submit.md"
    assert "use /requirement:archive to clean up" in text, "Missing 'use /requirement:archive to clean up' in submit.md"


def test_archive_md_contains_triple_protection_phrases():
    """archive.md 必须含 owner=workflow / 路径白名单 / 主仓根 三条字面量。"""
    text = (REPO_ROOT / ".claude/commands/requirement/archive.md").read_text(encoding="utf-8")
    assert "owner=workflow" in text, "Missing 'owner=workflow' in archive.md"
    assert "路径白名单" in text, "Missing '路径白名单' in archive.md"
    assert "主仓根" in text, "Missing '主仓根' in archive.md"


def test_archive_md_cli_signature_unchanged():
    """archive.md H2 接口签名段必须保留改造前的全部 baseline 标题。"""
    text = (REPO_ROOT / ".claude/commands/requirement/archive.md").read_text(encoding="utf-8")

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
    """SKILL.md 必须含对 archive.md 的交叉链接字面量。"""
    text = (REPO_ROOT / ".claude/skills/managing-requirement-lifecycle/SKILL.md").read_text(encoding="utf-8")
    assert "archive.md" in text, "Missing 'archive.md' cross-link in SKILL.md"
