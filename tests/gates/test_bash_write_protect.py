"""F-003 H5 · GATE-BASH-WRITE-PROTECT plugin 单测。

来源：detailed-design.md §3.3（行 306-379）。

测试矩阵：
  1. 8+ 类 shell 写法均命中正则（parametrize）
  2. 父进程链白名单（mock subprocess）
  3. env 双轨白名单（CLAUDE_GATES_BYPASS=1 + REASON）
  4. 缺 reason 时 FAIL code=BYPASS-NO-REASON
  5. 非 Bash 工具 → SKIP
  6. 非保护路径 / 读操作 → PASS
  7. SAVE_REVIEW_PID env 优先白名单
"""
from __future__ import annotations

import pytest

from plugins.base import Decision, GateContext
from plugins import bash_write_protect as plugin_mod


def _make_ctx(command: str = "", tool_name: str = "Bash", env: dict | None = None) -> GateContext:
    return GateContext(
        trigger="pre-tool-use",
        extra={"tool_name": tool_name, "command": command},
        env=env or {},
    )


# ====================== fail：8 类写法均命中 ======================


_PROTECTED = "requirements/REQ-2026-002/reviews/foo.json"


@pytest.mark.parametrize(
    "label,command",
    [
        ("redirect_gt",      f"echo x > {_PROTECTED}"),
        ("redirect_gtgt",    f"echo x >> {_PROTECTED}"),
        ("tee",              f"echo x | tee {_PROTECTED}"),
        ("tee_dash_a",       f"echo x | tee -a {_PROTECTED}"),
        ("mv",               f"mv tmp.json {_PROTECTED}"),
        ("cp",               f"cp tmp.json {_PROTECTED}"),
        ("python_open_w",    f"python3 -c \"open('{_PROTECTED}','w').write(x)\""),
        ("python_open_a",    f"python3 -c \"open('{_PROTECTED}','a').write(x)\""),
        ("python_open_wb",   f"python3 -c \"open('{_PROTECTED}','wb').write(x)\""),
        ("heredoc",          f"cat <<EOF > {_PROTECTED}\\nfoo\\nEOF"),
        ("printf_redirect",  f"printf '%s' data > {_PROTECTED}"),
        ("dd_of",            f"dd if=/dev/null of={_PROTECTED}"),
    ],
)
def test_should_fail_when_bash_command_writes_reviews_json(label, command, monkeypatch):
    """given_8_shell_write_forms_when_run_then_fail_with_bash_write。

    mock 父进程链返回非白名单 comm，避免误中 save-review.sh 白名单。
    F-005 round-2：_caller_is_save_review_sh 签名升级为 (self, ctx)。
    """
    # 强制父进程链识别失败（不是 save-review.sh）
    monkeypatch.setattr(
        plugin_mod.BashWriteProtectGate,
        "_caller_is_save_review_sh",
        lambda self, ctx: False,
    )
    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx(command=command)
    report = gate.run(ctx)
    assert report.decision == Decision.FAIL, f"{label} 未命中正则"
    assert report.code == "BASH-WRITE"


# ====================== pass：父进程链白名单 ======================


def test_should_pass_when_caller_is_save_review_sh(monkeypatch):
    """given_caller_chain_contains_save_review_sh_when_run_then_pass。"""
    monkeypatch.setattr(
        plugin_mod.BashWriteProtectGate,
        "_caller_is_save_review_sh",
        lambda self, ctx: True,
    )
    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx(command=f"echo x > {_PROTECTED}")
    report = gate.run(ctx)
    assert report.decision == Decision.PASS
    assert report.vars["whitelisted"] == "save-review.sh"


def test_caller_chain_walks_up_to_save_review_sh(monkeypatch):
    """given_save_review_sh_in_grandparent_when_walk_then_match（端到端 mock subprocess）。

    模拟 ps 返回链：第一层非白名单 → 第二层 save-review.sh → 命中。
    F-028 round-2：合并为单次 ps -o comm=,ppid=，每步 yield (comm, ppid)。
    """
    # 单次 ps -o comm=,ppid= 输出形如 "comm   ppid"
    fixtures_iter = iter([
        b"bash 200\n",
        b"save-review.sh 1\n",
    ])

    def _fake_check_output(cmd, *args, **kwargs):
        return next(fixtures_iter)

    monkeypatch.setattr(plugin_mod.os, "getppid", lambda: 100)
    monkeypatch.setattr(plugin_mod.subprocess, "check_output", _fake_check_output)

    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx()
    assert gate._caller_is_save_review_sh(ctx) is True


def test_caller_chain_returns_false_when_not_in_chain(monkeypatch):
    """given_no_save_review_sh_in_chain_when_walk_then_false。"""
    fixtures_iter = iter([
        b"bash 200\n",
        b"zsh 1\n",
    ])

    def _fake_check_output(cmd, *args, **kwargs):
        return next(fixtures_iter)

    monkeypatch.setattr(plugin_mod.os, "getppid", lambda: 100)
    monkeypatch.setattr(plugin_mod.subprocess, "check_output", _fake_check_output)

    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx()
    assert gate._caller_is_save_review_sh(ctx) is False


def test_caller_chain_swallows_subprocess_errors(monkeypatch):
    """given_subprocess_error_when_walk_then_returns_false（保守拒绝，不抛）。"""
    import subprocess as real_subprocess

    def _raise(*args, **kwargs):
        raise real_subprocess.CalledProcessError(1, "ps")

    monkeypatch.setattr(plugin_mod.os, "getppid", lambda: 100)
    monkeypatch.setattr(plugin_mod.subprocess, "check_output", _raise)
    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx()
    assert gate._caller_is_save_review_sh(ctx) is False


def test_caller_chain_pass_via_save_review_pid_env(monkeypatch):
    """given_SAVE_REVIEW_PID_matches_chain_pid_when_walk_then_pass（F-005 round-2 优先源）。"""
    # ppid 链：100 → 200 → 1，SAVE_REVIEW_PID=200 → 第二步命中
    fixtures_iter = iter([
        b"bash 200\n",
        b"random-name 1\n",  # 即使 comm 不匹配，PID 比对也命中
    ])

    def _fake_check_output(cmd, *args, **kwargs):
        return next(fixtures_iter)

    monkeypatch.setattr(plugin_mod.os, "getppid", lambda: 100)
    monkeypatch.setattr(plugin_mod.subprocess, "check_output", _fake_check_output)

    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx(env={"SAVE_REVIEW_PID": "200"})
    assert gate._caller_is_save_review_sh(ctx) is True


def test_caller_chain_rejects_endswith_spoofing(monkeypatch):
    """given_evil_save_review_sh_in_chain_when_walk_then_false（F-005 round-2 防伪造）。"""
    fixtures_iter = iter([
        b"evil-save-review.sh 1\n",
    ])

    def _fake_check_output(cmd, *args, **kwargs):
        return next(fixtures_iter)

    monkeypatch.setattr(plugin_mod.os, "getppid", lambda: 100)
    monkeypatch.setattr(plugin_mod.subprocess, "check_output", _fake_check_output)
    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx()
    # endswith 时代会误判 True；现在严格 == 比对，必须 False
    assert gate._caller_is_save_review_sh(ctx) is False


# ====================== pass：env 双轨白名单 ======================


def test_should_pass_when_env_bypass_with_reason(monkeypatch):
    """given_env_bypass_1_with_reason_when_run_then_pass。"""
    monkeypatch.setattr(
        plugin_mod.BashWriteProtectGate,
        "_caller_is_save_review_sh",
        lambda self, ctx: False,
    )
    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx(
        command=f"echo x > {_PROTECTED}",
        env={"CLAUDE_GATES_BYPASS": "1", "CLAUDE_GATES_BYPASS_REASON": "hotfix-2026-04"},
    )
    report = gate.run(ctx)
    assert report.decision == Decision.PASS
    assert report.vars["whitelisted"] == "env-bypass"
    assert report.vars["reason"] == "hotfix-2026-04"


# ====================== fail：env bypass 无 reason ======================


def test_should_fail_when_env_bypass_without_reason(monkeypatch):
    """given_env_bypass_1_without_reason_when_run_then_fail_bypass_no_reason。"""
    monkeypatch.setattr(
        plugin_mod.BashWriteProtectGate,
        "_caller_is_save_review_sh",
        lambda self, ctx: False,
    )
    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx(
        command=f"echo x > {_PROTECTED}",
        env={"CLAUDE_GATES_BYPASS": "1"},
    )
    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "BYPASS-NO-REASON"


def test_should_fail_when_env_bypass_with_blank_reason(monkeypatch):
    """given_env_bypass_1_with_whitespace_reason_when_run_then_fail_bypass_no_reason。"""
    monkeypatch.setattr(
        plugin_mod.BashWriteProtectGate,
        "_caller_is_save_review_sh",
        lambda self, ctx: False,
    )
    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx(
        command=f"echo x > {_PROTECTED}",
        env={"CLAUDE_GATES_BYPASS": "1", "CLAUDE_GATES_BYPASS_REASON": "   "},
    )
    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "BYPASS-NO-REASON"


# ====================== skip：非 Bash / 非 pre-tool-use ======================


def test_should_skip_when_tool_is_not_bash():
    """given_tool_edit_when_precheck_then_skip。"""
    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx(tool_name="Edit", command="ignored")
    skip = gate.precheck(ctx)
    assert skip is not None
    # F-034 round-2：Skip reason 中文化
    assert "Bash" in skip.reason


def test_should_skip_when_trigger_is_not_pre_tool_use():
    """given_trigger_ci_when_precheck_then_skip。"""
    gate = plugin_mod.BashWriteProtectGate()
    ctx = GateContext(trigger="ci", extra={"tool_name": "Bash", "command": "ignored"})
    skip = gate.precheck(ctx)
    assert skip is not None


# ====================== pass：非保护路径 / 读操作 ======================


def test_should_pass_when_command_is_read():
    """given_cat_reviews_json_when_run_then_pass（读不写）."""
    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx(command=f"cat {_PROTECTED}")
    report = gate.run(ctx)
    assert report.decision == Decision.PASS


def test_should_pass_when_writing_meta_yaml():
    """given_write_meta_yaml_when_run_then_pass（不在保护路径）."""
    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx(command="echo x > requirements/REQ-2026-002/meta.yaml")
    report = gate.run(ctx)
    assert report.decision == Decision.PASS


def test_should_pass_when_command_empty():
    """given_empty_command_when_run_then_pass。"""
    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx(command="")
    report = gate.run(ctx)
    assert report.decision == Decision.PASS
