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
        # F-005 round-3 新增 4 条 alt（关闭 round-2 实测遗漏形态）
        ("sponge",           f"echo x | sponge {_PROTECTED}"),
        ("rsync",            f"rsync --inplace tmp.json {_PROTECTED}"),
        ("install",          f"install -m 644 tmp.json {_PROTECTED}"),
        ("pathlib_write_text", f"python3 -c \"from pathlib import Path; Path('{_PROTECTED}').write_text('x')\""),
        ("pathlib_write_bytes", f"python3 -c \"from pathlib import Path; Path('{_PROTECTED}').write_bytes(b'x')\""),
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


def test_should_return_false_when_save_review_pid_missing(monkeypatch):
    """given_no_save_review_pid_env_when_caller_check_then_false。

    F-012 round-3：comm 字符串 fallback 已删除，SAVE_REVIEW_PID 缺失即直接 false，
    不再尝试遍历父进程链匹配 comm == 'save-review.sh'。
    """

    # 即使 ps 链返回 save-review.sh 也不命中，因为 SAVE_REVIEW_PID 没设
    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("SAVE_REVIEW_PID 缺失时不应调用 ps")

    monkeypatch.setattr(plugin_mod.os, "getppid", lambda: 100)
    monkeypatch.setattr(plugin_mod.subprocess, "check_output", _should_not_be_called)

    gate = plugin_mod.BashWriteProtectGate()
    ctx = _make_ctx()  # env={} → SAVE_REVIEW_PID 未设
    assert gate._caller_is_save_review_sh(ctx) is False


def test_caller_chain_returns_false_when_not_in_chain(monkeypatch):
    """given_save_review_pid_set_but_no_match_in_chain_when_walk_then_false。"""
    fixtures_iter = iter([
        b"bash 200\n",
        b"zsh 1\n",
    ])

    def _fake_check_output(cmd, *args, **kwargs):
        return next(fixtures_iter)

    monkeypatch.setattr(plugin_mod.os, "getppid", lambda: 100)
    monkeypatch.setattr(plugin_mod.subprocess, "check_output", _fake_check_output)

    gate = plugin_mod.BashWriteProtectGate()
    # SAVE_REVIEW_PID=999（链中 200 / 1 都不匹配）
    ctx = _make_ctx(env={"SAVE_REVIEW_PID": "999"})
    assert gate._caller_is_save_review_sh(ctx) is False


def test_caller_chain_swallows_subprocess_errors(monkeypatch):
    """given_subprocess_error_when_walk_then_returns_false（保守拒绝，不抛）。"""
    import subprocess as real_subprocess

    def _raise(*args, **kwargs):
        raise real_subprocess.CalledProcessError(1, "ps")

    monkeypatch.setattr(plugin_mod.os, "getppid", lambda: 100)
    monkeypatch.setattr(plugin_mod.subprocess, "check_output", _raise)
    gate = plugin_mod.BashWriteProtectGate()
    # 必须设 SAVE_REVIEW_PID 才会进入 _walk_ppid_chain，否则 short-circuit return False
    ctx = _make_ctx(env={"SAVE_REVIEW_PID": "200"})
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
    """given_evil_save_review_sh_in_chain_when_walk_then_false（F-005 round-2 防伪造，F-012 round-3 仍生效）。

    F-012 round-3 删除 comm 字符串 fallback 后，evil-save-review.sh 仍无法绕过：
    SAVE_REVIEW_PID 才是唯一通道，外部进程伪造 comm 字符串完全无效。
    """
    fixtures_iter = iter([
        b"evil-save-review.sh 1\n",
    ])

    def _fake_check_output(cmd, *args, **kwargs):
        return next(fixtures_iter)

    monkeypatch.setattr(plugin_mod.os, "getppid", lambda: 100)
    monkeypatch.setattr(plugin_mod.subprocess, "check_output", _fake_check_output)
    gate = plugin_mod.BashWriteProtectGate()
    # SAVE_REVIEW_PID 设为 999（链中 1 不匹配）→ 必为 False；伪造 comm 完全无效
    ctx = _make_ctx(env={"SAVE_REVIEW_PID": "999"})
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
