"""F-012 · launcher fuzzy 匹配单元测试。

覆盖：
- AC-09 acceptance #1：拼写错 'standar-8phase' → fuzzy hit 模板 'standard-8phase'（stderr NOTE）
- AC-09 acceptance #2：短名 'review-emb' → fuzzy hit 模板 'code-review-embedded'（stderr NOTE）
- AC-09 acceptance #3：≥10 词 fuzzy hit 词典通过
- fuzzy miss 路径：'xyz123' → exit 1 + 无 NOTE
- fuzzy 命中命令名 → 真正调用了正名命令的 main（mock 检测）
- fuzzy 命中模板名 → stderr NOTE + return 1（不派发）

测试运行：
    python3 -m pytest tests/lib/test_launcher_fuzzy.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

import workflow_command_dispatcher as wcd  # noqa: E402


# ============================================================================
# 辅助：测试 dispatch() 时捕获 stderr
# ============================================================================

def _dispatch(cmd: str, args: list[str] | None = None, capsys=None):
    """调 dispatch()，返回 (rc, stderr_text)。"""
    rc = wcd.dispatch(cmd, args or [])
    captured = capsys.readouterr() if capsys else None
    stderr = captured.err if captured else ""
    return rc, stderr


# ============================================================================
# acceptance #1：拼写错 'standar-8phase'（编辑距离=2）→ 命中模板，stderr NOTE，return 1
# ============================================================================

def test_fuzzy_typo_standard_8phase_template_hit(capsys):
    """'standar-8phase' → fuzzy 匹配到模板 'standard-8phase'；stderr 含 NOTE；return 1。"""
    rc, stderr = _dispatch("standar-8phase", [], capsys)
    assert rc == 1
    assert "NOTE" in stderr, f"stderr 应含 NOTE，实际：{stderr!r}"
    assert "standard-8phase" in stderr, f"stderr 应含 standard-8phase，实际：{stderr!r}"


# ============================================================================
# acceptance #2：短名 'review-emb' → 命中模板 'code-review-embedded'，stderr NOTE，return 1
# ============================================================================

def test_fuzzy_short_name_review_emb_template_hit(capsys):
    """'review-emb' → fuzzy 匹配到模板 'code-review-embedded'；stderr 含 NOTE；return 1。"""
    rc, stderr = _dispatch("review-emb", [], capsys)
    assert rc == 1
    assert "NOTE" in stderr, f"stderr 应含 NOTE，实际：{stderr!r}"
    assert "code-review-embedded" in stderr, f"stderr 应含 code-review-embedded，实际：{stderr!r}"


# ============================================================================
# acceptance #3：fuzzy 词典 ≥ 10 词
# ============================================================================

def test_fuzzy_dict_has_at_least_10_entries():
    """_FUZZY_CMDS + _FUZZY_TEMPLATES（模板别名 key 集）合并后总长 ≥ 10。"""
    total = len(wcd._FUZZY_CMDS) + len(wcd._FUZZY_TEMPLATES)
    assert total >= 10, f"fuzzy 词典总长 {total} < 10"


def test_fuzzy_dict_all_cmd_entries_can_hit():
    """_FUZZY_CMDS 中的每个词用自身查询时 fuzzy 应能命中（cutoff=0.6 自命中验证）。"""
    import difflib
    for word in wcd._FUZZY_CMDS:
        hits = difflib.get_close_matches(word, wcd._FUZZY_CMDS, n=1, cutoff=0.6)
        assert hits, f"词典词 {word!r} 无法被自己命中（cutoff=0.6），词典设计有误"


def test_fuzzy_template_aliases_map_to_canonical():
    """_FUZZY_TEMPLATE_ALIASES 每个 key 查询后应得到对应的 canonical value。"""
    for variant, canonical in wcd._FUZZY_TEMPLATE_ALIASES.items():
        matched, is_cmd = wcd._fuzzy_match(variant)
        assert not is_cmd, f"{variant!r} 不应被识别为命令"
        assert matched == canonical, (
            f"variant {variant!r} 期望命中 canonical {canonical!r}，实际 {matched!r}"
        )


# ============================================================================
# fuzzy miss 路径：完全无关字符串 → exit 1 + 无 NOTE
# ============================================================================

def test_fuzzy_miss_returns_exit1_no_note(capsys):
    """'xyz123' 无法匹配任何词典词 → exit 1，stderr 含 ERROR，无 NOTE。"""
    rc, stderr = _dispatch("xyz123", [], capsys)
    assert rc == 1
    assert "ERROR" in stderr, f"stderr 应含 ERROR，实际：{stderr!r}"
    assert "NOTE" not in stderr, f"fuzzy miss 路径不应含 NOTE，实际：{stderr!r}"


# ============================================================================
# fuzzy 命中命令名 → 真正调用了正名命令的 main
# ============================================================================

def test_fuzzy_command_hit_dispatches_to_correct_module(capsys):
    """'cancl' fuzzy 匹配到命令 'cancel' → 实际调用了 workflow_cancel.main。

    使用 mock 拦截 importlib.import_module，验证被调用模块名为 'workflow_cancel'。
    """
    mock_mod = MagicMock()
    mock_mod.main.return_value = 0

    with patch("importlib.import_module", return_value=mock_mod) as mock_import:
        rc = wcd.dispatch("cancl", [])

    assert rc == 0
    # importlib.import_module 应以 'workflow_cancel' 被调用
    called_modules = [call.args[0] for call in mock_import.call_args_list]
    assert "workflow_cancel" in called_modules, (
        f"期望 importlib.import_module('workflow_cancel')，实际调用：{called_modules}"
    )
    # stderr 应含 NOTE
    captured = capsys.readouterr()
    assert "NOTE" in captured.err, f"fuzzy 命中命令时 stderr 应含 NOTE，实际：{captured.err!r}"


# ============================================================================
# fuzzy 命中模板名分支：只校验 stderr NOTE + return 1（不真正派发）
# ============================================================================

def test_fuzzy_template_hit_does_not_dispatch(capsys):
    """命中模板名时：return 1（不调用任何命令 main），stderr 含 NOTE。"""
    with patch("importlib.import_module") as mock_import:
        rc = wcd.dispatch("standar-8phase", [])
        # 不应调用 importlib.import_module（即不派发命令）
        assert not mock_import.called, "命中模板名时不应 import 命令模块"

    assert rc == 1
    captured = capsys.readouterr()
    assert "NOTE" in captured.err


# ============================================================================
# 完全正常路径：合法命令直接派发（回归保护）
# ============================================================================

def test_valid_command_dispatches_without_fuzzy(capsys):
    """合法命令 'list' 直接派发，不走 fuzzy 路径，stderr 无 NOTE。"""
    mock_mod = MagicMock()
    mock_mod.main.return_value = 0

    with patch("importlib.import_module", return_value=mock_mod):
        rc = wcd.dispatch("list", [])

    assert rc == 0
    captured = capsys.readouterr()
    assert "NOTE" not in captured.err, "合法命令不应触发 NOTE"
