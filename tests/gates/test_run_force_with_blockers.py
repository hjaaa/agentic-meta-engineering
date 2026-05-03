"""scripts/gates/run.py --force-with-blockers 校验的单元测试。

覆盖 F-004 round-2 Block 3 要求：
  1. reason 非空 + 短 → pass（exit 0）
  2. reason 空 → exit 2（F-004 round-3：CLI 入参非法归 2）
  3. reason 1025 字符 → exit 2
  4. reason 含 \\x00 / \\x07 → exit 2
  5. reason 含 \\t / \\n → pass（allow-list）
  6. registry.yaml triggers=[submit, phase-transition] 后
     phase-transition 触发不再越权（集成验证）

覆盖 F-004 round-3 新增要求：
  7. _validate_force_reason(None) → None（未传参数场景）
  8. _validate_force_reason 合法 reason → None（校验通过）
  9. _validate_force_reason 非法 reason → 返回具体错误消息字符串
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
    """reason 为空字符串 → exit 2（CLI 入参非法）+ 错误提示。"""
    result = _run_main(
        ["--trigger=submit", "--force-with-blockers= "],
        monkeypatch,
    )
    assert result == 2
    captured = capsys.readouterr()
    assert "非空 reason" in captured.err


def test_force_with_blockers_reason_too_long(monkeypatch, capsys):
    """reason 超 1024 字符 → exit 2（CLI 入参非法）+ 错误提示。"""
    long_reason = "A" * 1025
    result = _run_main(
        ["--trigger=submit", f"--force-with-blockers={long_reason}"],
        monkeypatch,
    )
    assert result == 2
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
    """reason 含 \\x00（NUL 控制字符）→ exit 2（CLI 入参非法）+ 错误提示。"""
    bad_reason = "临时绕过\x00恶意内容"
    result = _run_main(
        ["--trigger=submit", f"--force-with-blockers={bad_reason}"],
        monkeypatch,
    )
    assert result == 2
    captured = capsys.readouterr()
    assert "控制字符" in captured.err


def test_force_with_blockers_reason_control_char_bel(monkeypatch, capsys):
    """reason 含 \\x07（BEL 响铃字符）→ exit 2（CLI 入参非法）+ 错误提示。"""
    bad_reason = "原因\x07bell"
    result = _run_main(
        ["--trigger=submit", f"--force-with-blockers={bad_reason}"],
        monkeypatch,
    )
    assert result == 2
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


# ====================== _validate_force_reason 函数单测（F-004 round-3 G-1） ======================


def test_validate_force_reason_none_returns_none():
    """_validate_force_reason(None) 应返回 None（未传参数，无需校验）。"""
    result = runner_mod._validate_force_reason(None)
    assert result is None


def test_validate_force_reason_valid_returns_none():
    """合法 reason 应返回 None（校验全通过）。"""
    result = runner_mod._validate_force_reason("临时绕过：已有 Jira 跟进")
    assert result is None


def test_validate_force_reason_empty_returns_error_message():
    """reason 为纯空白时应返回以 '--force-with-blockers 必须提供非空 reason' 开头的错误消息。"""
    result = runner_mod._validate_force_reason("   ")
    assert result is not None
    assert "非空 reason" in result


def test_validate_force_reason_too_long_returns_error_message():
    """reason 超过 1024 字符时应返回含 '超过上限 1024' 的错误消息。"""
    long_reason = "x" * 1025
    result = runner_mod._validate_force_reason(long_reason)
    assert result is not None
    assert "超过上限 1024" in result


def test_validate_force_reason_exactly_1024_returns_none():
    """reason 恰好 1024 字符时应返回 None（边界值通过）。"""
    reason_1024 = "y" * 1024
    result = runner_mod._validate_force_reason(reason_1024)
    assert result is None


def test_validate_force_reason_control_char_returns_error_message():
    """reason 含 \\x00 控制字符时应返回含 '控制字符' 的错误消息。"""
    bad_reason = "绕过原因\x00注入"
    result = runner_mod._validate_force_reason(bad_reason)
    assert result is not None
    assert "控制字符" in result


def test_validate_force_reason_tab_newline_allowed():
    """reason 含 \\t 和 \\n（allow-list）时应返回 None（不视为控制字符）。"""
    reason_with_whitespace = "原因：\t制表符\n换行符"
    result = runner_mod._validate_force_reason(reason_with_whitespace)
    assert result is None


# ====================== G-3 资源清理断言（F-004 round-3） ======================


def test_force_escape_hatch_cleans_snapshots_and_staged_writes(monkeypatch, tmp_path):
    """G-3：force-with-blockers 命中时清理 .bak 快照 + 清空 staged_writes。

    F-004（FG-004）升级：命中条件改为「失败 gate.tags ∩ escape.skips_gates_with_tag ≠ ∅」。
    本测试用 GATE-REVIEW-VERDICT（registry.yaml 真实有 tags=[review-verdict]）+ 传 mock
    registry_data，确保 tag 命中走 force_used=True 路径，验证资源清理仍然生效。
    """
    from unittest.mock import MagicMock

    bak_file = tmp_path / "meta.yaml.bak"
    bak_file.write_text("backup content")
    fake_snapshots = {str(tmp_path / "meta.yaml"): bak_file}

    from plugins.base import GateContext
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2099-001",
        cli_flags={"force_with_blockers": "紧急绕过：Jira-1234 跟进"},
        meta={},
        extra={},
        changed_files=[],
        env={},
    )
    ctx.staged_writes.append(("meta.yaml", "some_key", "some_value"))

    gate_fail = MagicMock()
    gate_fail.report.gate_id = "GATE-REVIEW-VERDICT"

    # F-004：传 registry_data 让 tag 命中（review-verdict ∩ skips_gates_with_tag）
    fake_registry = {
        "gates": [{"id": "GATE-REVIEW-VERDICT", "tags": ["review-verdict"]}],
        "escape_hatches": [
            {"id": "force-with-blockers", "skips_gates_with_tag": ["review-verdict"]}
        ],
    }

    force_used, rollback_failed = runner_mod._handle_escape_hatch(
        ctx, gate_fail, executed=[], snapshots=fake_snapshots,
        registry_data=fake_registry,
    )

    assert force_used is True
    assert rollback_failed is False
    assert not bak_file.exists(), ".bak 快照文件应被 _cleanup_snapshots 删除"
    assert len(ctx.staged_writes) == 0, "ctx.staged_writes 应被 clear() 清空"
