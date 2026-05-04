"""F-004 / TC-FG4-3 argparse 双 dest + DEPRECATED stderr 测试。

覆盖：
  - --bypass-review-blockers='X' → args.force_with_blockers == 'X'，无 deprecation 提示
  - --force-with-blockers='X' → args.force_with_blockers == 'X' + stderr 含 DEPRECATED 字串
  - 同 dest 在 Python 3.11 / 3.12 各跑一次（argparse 双 add_argument 同 dest 兼容性）

参考：tests/gates/test_run_force_with_blockers.py 已有 reason 校验测试，本文件只关心
alias / deprecation。
"""
from __future__ import annotations

import sys

import pytest

import tests.gates.test_run_force_with_blockers as _bootstrap  # noqa: F401

import run as runner_mod


# ====================== argparse 双 dest 解析 ======================


def test_bypass_review_blockers_sets_force_with_blockers_dest():
    args = runner_mod.parse_args([
        "--trigger=submit", "--req=REQ-2099-001",
        "--bypass-review-blockers=新名 reason",
    ])
    assert args.force_with_blockers == "新名 reason"


def test_force_with_blockers_old_name_sets_same_dest():
    args = runner_mod.parse_args([
        "--trigger=submit", "--req=REQ-2099-001",
        "--force-with-blockers=旧名 reason",
    ])
    assert args.force_with_blockers == "旧名 reason"


def test_target_arg_parsed():
    args = runner_mod.parse_args([
        "--trigger=submit", "--req=REQ-2099-001", "--target=main",
    ])
    assert args.target == "main"


def test_target_default_none_when_absent():
    args = runner_mod.parse_args(["--trigger=submit", "--req=REQ-2099-001"])
    assert args.target is None


# ====================== TC-FG4-3：DEPRECATED stderr ======================


def test_deprecation_warning_when_old_name_used(capsys):
    """TC-FG4-3：--force-with-blockers='旧' → stderr 含
    `[DEPRECATED] use --bypass-review-blockers instead, removed at 2026-11-01`。
    """
    runner_mod.main([
        "--trigger=submit",
        "--req=REQ-2099-001",
        "--force-with-blockers=旧",
    ])
    captured = capsys.readouterr()
    assert "[DEPRECATED] use --bypass-review-blockers instead, removed at 2026-11-01" in captured.err


def test_no_deprecation_when_new_name_used(capsys):
    runner_mod.main([
        "--trigger=submit",
        "--req=REQ-2099-001",
        "--bypass-review-blockers=新",
    ])
    captured = capsys.readouterr()
    assert "DEPRECATED" not in captured.err


def test_no_deprecation_when_neither_provided(capsys):
    runner_mod.main(["--trigger=submit", "--req=REQ-2099-001"])
    captured = capsys.readouterr()
    assert "DEPRECATED" not in captured.err


# ====================== Python 3.11 / 3.12 兼容性 ======================


@pytest.mark.skipif(
    sys.version_info[:2] not in ((3, 11), (3, 12)),
    reason="argparse 双 dest 兼容性仅在 Python 3.11 / 3.12 验证（验收清单第 6 条）；"
    f"当前 {sys.version_info.major}.{sys.version_info.minor} 跳过",
)
def test_argparse_double_dest_python_311_312():
    """验收清单第 6 条：argparse 双 add_argument 同 dest 在 Python 3.11 / 3.12 各跑一次。"""
    args = runner_mod.parse_args([
        "--trigger=submit", "--req=REQ-2099-001",
        "--bypass-review-blockers=A",
    ])
    assert args.force_with_blockers == "A"

    args2 = runner_mod.parse_args([
        "--trigger=submit", "--req=REQ-2099-001",
        "--force-with-blockers=B",
    ])
    assert args2.force_with_blockers == "B"
