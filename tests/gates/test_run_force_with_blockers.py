"""scripts/gates/run.py --force-with-blockers 校验的单元测试。

覆盖 F-004 round-2 Block 3 要求：
  1. reason 非空 + 短 → pass（exit 0）
  2. reason 空 → exit 1
  3. reason 1025 字符 → exit 1
  4. reason 含 \\x00 / \\x07 → exit 1
  5. reason 含 \\t / \\n → pass（allow-list）
  6. registry.yaml triggers=[submit, phase-transition] 后
     phase-transition 触发不再越权（集成验证）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATES_DIR = _REPO_ROOT / "scripts" / "gates"
if str(_GATES_DIR) not in sys.path:
    sys.path.insert(0, str(_GATES_DIR))

import run as runner_mod  # noqa: E402


# ====================== 辅助 ======================


def _run_main(argv: list[str], monkeypatch) -> int:
    """调用 runner_mod.main()，隔离 sys.argv 和 sys.exit。"""
    monkeypatch.setattr(sys, "argv", ["run.py"] + argv)
    return runner_mod.main()


# ====================== reason 格式校验测试 ======================


def test_force_with_blockers_valid_reason(monkeypatch, tmp_path, capsys):
    """reason 非空且合法 → 不因格式校验返回 1（进入后续 gate 逻辑）。

    此处只验证 main() 不因 reason 格式校验 return 1；
    后续 gate 执行可能因没有真实 req 而 return 2，均可接受。
    """
    result = _run_main(
        ["--trigger=submit", "--force-with-blockers=临时绕过：已有 Jira 跟进"],
        monkeypatch,
    )
    # 格式校验通过，进入 gate 阶段（可能 return 0 或 2，但不应是 1）
    captured = capsys.readouterr()
    assert "reason 长度" not in captured.err
    assert "控制字符" not in captured.err
    assert "非空 reason" not in captured.err


def test_force_with_blockers_empty_reason(monkeypatch, capsys):
    """reason 为空字符串 → exit 1 + 错误提示。"""
    result = _run_main(
        ["--trigger=submit", "--force-with-blockers= "],
        monkeypatch,
    )
    assert result == 1
    captured = capsys.readouterr()
    assert "非空 reason" in captured.err


def test_force_with_blockers_reason_too_long(monkeypatch, capsys):
    """reason 超 1024 字符 → exit 1 + 错误提示。"""
    long_reason = "A" * 1025
    result = _run_main(
        ["--trigger=submit", f"--force-with-blockers={long_reason}"],
        monkeypatch,
    )
    assert result == 1
    captured = capsys.readouterr()
    assert "超过上限 1024" in captured.err


def test_force_with_blockers_reason_exactly_1024(monkeypatch, capsys):
    """reason 恰好 1024 字符 → 不因长度校验返回 1。"""
    reason_1024 = "B" * 1024
    result = _run_main(
        ["--trigger=submit", f"--force-with-blockers={reason_1024}"],
        monkeypatch,
    )
    captured = capsys.readouterr()
    assert "超过上限 1024" not in captured.err


def test_force_with_blockers_reason_control_char_null(monkeypatch, capsys):
    """reason 含 \\x00（NUL 控制字符）→ exit 1 + 错误提示。"""
    bad_reason = "临时绕过\x00恶意内容"
    result = _run_main(
        ["--trigger=submit", f"--force-with-blockers={bad_reason}"],
        monkeypatch,
    )
    assert result == 1
    captured = capsys.readouterr()
    assert "控制字符" in captured.err


def test_force_with_blockers_reason_control_char_bel(monkeypatch, capsys):
    """reason 含 \\x07（BEL 响铃字符）→ exit 1 + 错误提示。"""
    bad_reason = "原因\x07bell"
    result = _run_main(
        ["--trigger=submit", f"--force-with-blockers={bad_reason}"],
        monkeypatch,
    )
    assert result == 1
    captured = capsys.readouterr()
    assert "控制字符" in captured.err


def test_force_with_blockers_reason_tab_newline_allowed(monkeypatch, capsys):
    """reason 含 \\t 和 \\n（allow-list）→ 不因控制字符校验返回 1。"""
    reason_with_whitespace = "原因：\t多行\n说明"
    result = _run_main(
        ["--trigger=submit", f"--force-with-blockers={reason_with_whitespace}"],
        monkeypatch,
    )
    captured = capsys.readouterr()
    assert "控制字符" not in captured.err


# ====================== 集成验证：phase-transition 不越权 ======================


def test_registry_phase_transition_in_triggers():
    """registry.yaml 中 force-with-blockers.triggers 包含 phase-transition。

    F-1 选边：phase-transition 已加入 triggers，不再越权。
    """
    import yaml  # noqa: PLC0415（本地 import 避免模块级影响）

    registry_path = _GATES_DIR / "registry.yaml"
    with registry_path.open("r", encoding="utf-8") as f:
        registry = yaml.safe_load(f)

    escape_hatches = registry.get("escape_hatches", [])
    fbw = next((e for e in escape_hatches if e.get("id") == "force-with-blockers"), None)
    assert fbw is not None, "registry.yaml 缺少 force-with-blockers 定义"
    triggers = fbw.get("triggers", [])
    assert "phase-transition" in triggers, (
        f"force-with-blockers.triggers 应包含 phase-transition，实际: {triggers}"
    )
    assert "submit" in triggers, (
        f"force-with-blockers.triggers 应包含 submit，实际: {triggers}"
    )
