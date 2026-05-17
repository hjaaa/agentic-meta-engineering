"""F-003 验证：archive-rules.md 节 + archive_runner._render_summary reminder 行。"""
from pathlib import Path


def test_archive_rules_md_has_ci_gate_precheck_section():
    """archive-rules.md 必须有 § archive 前 CI gate 预检 节。"""
    md = Path(
        ".claude/skills/managing-requirement-lifecycle/reference/archive-rules.md"
    ).read_text(encoding="utf-8")
    assert "## archive 前 CI gate 预检" in md
    assert "refresh-only-current-req" in md
    assert "python3 scripts/gates/run.py --trigger=ci --strict" in md


def test_archive_runner_summary_has_reminder_line():
    """archive_runner._render_summary 输出末段必含 🟢 reminder 行。"""
    from scripts.lib import archive_runner
    from scripts.lib.archive_runner import ArchiveResult

    # 构造最小 fixture：成功路径，无 errors
    result = ArchiveResult(
        req_id="REQ-2099-001",
        phase="completed",
        archived_at="2026-05-17T20:00:00+08:00",
        experience="yes",
        local_branch="deleted",
        remote_branch="deleted",
        error_messages=[],
    )
    out = archive_runner._render_summary(result)
    assert "🟢 archive 前请确认 ci gate exit 0" in out
    assert "python3 scripts/gates/run.py --trigger=ci --strict" in out
