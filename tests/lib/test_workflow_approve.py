"""TC-F9-5 · workflow_approve.py isatty fail-closed 单测。

验证 scripts/lib/workflow_approve.py 在 stdin 非 tty 时：
- exit code = 2
- stderr 含中文拒绝文案

注意：本文件路径 tests/lib/test_workflow_approve.py 不在 F-009 task.md
frontmatter touches 内（touches 仅列 tests/hooks/）。touches_guard 会软记
1 条 violation 到 F-009.receipt.json——这是预期行为（TC-F9-5 验收要求
本文件位于 tests/lib/）。主 Agent 决策是否扩 touches。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_APPROVE_PY = REPO_ROOT / "scripts" / "lib" / "workflow_approve.py"


def test_isatty_fail_closed() -> None:
    """TC-F9-5: stdin 非 tty 时 workflow_approve.py 应 exit 2 + stderr 中文文案。

    subprocess 喂空 stdin（非 tty）调 workflow_approve.py，
    断言 exit 2 + stderr 非空且含中文拒绝说明。
    """
    proc = subprocess.run(
        [sys.executable, str(WORKFLOW_APPROVE_PY)],
        input="",           # 喂空 stdin → isatty() 返回 False
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )

    assert proc.returncode == 2, (
        f"TC-F9-5: 期望 exit 2（isatty fail-closed），实际 {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )

    assert proc.stderr.strip(), (
        "TC-F9-5: 非 tty 时应输出错误信息到 stderr，实际 stderr 为空"
    )

    # 验证中文拒绝文案存在（与 workflow_state_validator.check_tty_for_approval 对齐）
    # 允许文案来自 check_tty_for_approval 或直接写的 isatty 块，含中文字符即可
    stderr_text = proc.stderr
    has_chinese = any(
        "一" <= ch <= "鿿"  # CJK 统一汉字基本区
        for ch in stderr_text
    )
    assert has_chinese, (
        f"TC-F9-5: stderr 应含中文拒绝文案，实际 stderr={stderr_text!r}"
    )
