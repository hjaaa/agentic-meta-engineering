"""
TC-F10-* 测试套件：验证 /requirement:* 别名兼容期 deprecation 文案 + 路由规则。

测试本质是验证 .md 文件文本内容 + Skill 入口的路由声明，
不执行实际 slash command——命令文件不是 Python 可执行脚本。
"""
import subprocess
from pathlib import Path

# ─── 固定路径 ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
CMD_DIR = REPO_ROOT / ".claude" / "commands" / "requirement"

# 9 个命令文件
ALL_CMDS = ["new", "continue", "save", "status", "list", "rollback", "next", "submit", "archive"]

# 6 个转发别名（A 类）
FORWARDING_CMDS = ["new", "continue", "save", "status", "list", "rollback"]

# 3 个例外保留（B 类）
EXCEPTION_CMDS = ["next", "submit", "archive"]

# A 类命令 → 目标 /workflow:*
FORWARD_TARGETS = {
    "new": "workflow:run",
    "continue": "workflow:continue",
    "save": "workflow:save",
    "status": "workflow:status",
    "list": "workflow:list",
    "rollback": "workflow:rollback",
}

# A 类命令 → ARGUMENTS 透传规则关键字
FORWARD_ARGS_KEYWORDS = {
    "new": ["$@", "拼空格"],
    "continue": ["$1", "直传"],
    "save": ["$@", "拼空格"],
    "status": ["$1", "直传"],
    "list": ["flag 直传"],
    "rollback": ["$1", "直传"],
}


def _read_cmd(name: str) -> str:
    """读取命令文件完整内容（含 frontmatter）。"""
    path = CMD_DIR / f"{name}.md"
    assert path.exists(), f"命令文件不存在：{path}"
    return path.read_text(encoding="utf-8")


# ─── TC-F10-1 ────────────────────────────────────────────────────────────────
def test_9_aliases_emit_deprecation():
    """
    TC-F10-1：9 个命令文件各含 [DEPRECATION] 字串 + 「截至 2026-08-08」字面量。
    - next.md 用 [DEPRECATION-NEXT]（不是 [DEPRECATION] 后跟转发内容）
    - 所有 9 个文件必须包含「截至 2026-08-08」字面量
    """
    for name in ALL_CMDS:
        content = _read_cmd(name)

        # 所有 9 个文件都必须含「截至 2026-08-08」字面量
        assert "截至 2026-08-08" in content, (
            f"{name}.md 缺少「截至 2026-08-08」字面量"
        )

        if name == "next":
            # next 用 [DEPRECATION-NEXT] 例外文案
            assert "[DEPRECATION-NEXT]" in content, (
                "next.md 应含 [DEPRECATION-NEXT] 而非标准 [DEPRECATION]"
            )
        else:
            # 其余 8 个用标准 [DEPRECATION]
            assert "[DEPRECATION]" in content, (
                f"{name}.md 缺少 [DEPRECATION] 标志"
            )


# ─── TC-F10-2 ────────────────────────────────────────────────────────────────
def test_arguments_forwarding():
    """
    TC-F10-2：6 个转发别名（new/continue/save/status/list/rollback）
    .md 文件应声明目标 /workflow:<target> + ARGUMENTS 透传规则关键字。
    """
    for name in FORWARDING_CMDS:
        content = _read_cmd(name)
        target = FORWARD_TARGETS[name]

        # 含目标 workflow 路由声明
        assert target in content, (
            f"{name}.md 缺少转发目标声明「{target}」"
        )

        # 含 ARGUMENTS 透传规则关键字（任一匹配即可）
        keywords = FORWARD_ARGS_KEYWORDS[name]
        matched = any(kw in content for kw in keywords)
        assert matched, (
            f"{name}.md 缺少 ARGUMENTS 透传规则关键字（期望任一：{keywords}）"
        )


# ─── TC-F10-3 ────────────────────────────────────────────────────────────────
def test_next_exception_kept_legacy():
    """
    TC-F10-3：/requirement:next 不转发到 /workflow:*，
    保留旧实现（调用 managing-requirement-lifecycle 的 phase-transition 子动作），
    .md 文件正文含 [DEPRECATION-NEXT] 例外文案。
    """
    content = _read_cmd("next")

    # 不含「→ /workflow:next」转发声明
    assert "→ /workflow:next" not in content, (
        "next.md 不应含「→ /workflow:next」转发声明（D-009 例外：不转发）"
    )

    # 含 [DEPRECATION-NEXT] 例外文案
    assert "[DEPRECATION-NEXT]" in content, (
        "next.md 应含 [DEPRECATION-NEXT] 例外文案"
    )

    # 含旧实现调用声明——Skill managing-requirement-lifecycle
    assert "managing-requirement-lifecycle" in content, (
        "next.md 应声明调用 Skill `managing-requirement-lifecycle`"
    )

    # 含 phase-transition 子动作声明
    assert "phase-transition" in content, (
        "next.md 应声明调用 phase-transition 子动作"
    )


# ─── TC-F10-4 ────────────────────────────────────────────────────────────────
def test_submit_archive_kept_legacy():
    """
    TC-F10-4：/requirement:submit / /requirement:archive 走独立旧实现 + 不转发；
    新引擎语义由 standard-8phase yaml 节点承载。
    """
    submit_content = _read_cmd("submit")
    archive_content = _read_cmd("archive")

    # submit 不含转发声明
    assert "→ /workflow:submit" not in submit_content, (
        "submit.md 不应含「→ /workflow:submit」转发声明"
    )

    # archive 不含转发声明
    assert "→ /workflow:archive" not in archive_content, (
        "archive.md 不应含「→ /workflow:archive」转发声明"
    )

    # submit 含「保留旧实现」声明
    assert "保留旧实现" in submit_content, (
        "submit.md 应含「保留旧实现」声明"
    )

    # submit 含新引擎节点声明（pr-submit）
    assert "pr-submit" in submit_content, (
        "submit.md 应含 standard-8phase yaml pr-submit 节点声明"
    )

    # archive 含「保留旧实现」声明
    assert "保留旧实现" in archive_content, (
        "archive.md 应含「保留旧实现」声明"
    )

    # archive 含新引擎节点声明（archive-finalize）
    assert "archive-finalize" in archive_content, (
        "archive.md 应含 archive-finalize 节点承载声明"
    )


# ─── TC-F10-5（辅助验证，也作为独立测试用例）────────────────────────────────
def test_deadline_literal_grep_coverage():
    """
    TC-F10-5 对应逻辑：subprocess grep 验证 9 个 .md 文件均含「截至 2026-08-08」。
    命中行数 ≥ 9，且涉及全部 9 个文件。
    """
    result = subprocess.run(
        ["grep", "-rn", "截至 2026-08-08", str(CMD_DIR)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]

    # 至少 9 行匹配
    assert len(lines) >= 9, (
        f"grep「截至 2026-08-08」命中 {len(lines)} 行，期望 ≥ 9 行\n{result.stdout}"
    )

    # 验证涉及全部 9 个文件
    matched_files = set()
    for line in lines:
        for name in ALL_CMDS:
            if f"{name}.md" in line:
                matched_files.add(name)

    missing = set(ALL_CMDS) - matched_files
    assert not missing, (
        f"以下命令文件缺少「截至 2026-08-08」字面量：{missing}"
    )
