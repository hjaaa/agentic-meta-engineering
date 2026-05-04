"""tests/gates/test_audit_async.py：write_audit 异步化（subprocess 调 audit_async.sh）测试。

F-004 §4.2 验收测试：
  - write_audit 正常调用时通过 subprocess 调用 audit_append_async
  - audit/.queue 只读时（chmod 0555）失败被静默 swallow，不阻断
  - write_audit 返回 Path 类型（向后兼容）
  - subprocess 调用次数与原同步版一致（每次调用 write_audit 对应一次 subprocess.run）
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# tests/gates/conftest.py 已注入 scripts/gates 到 sys.path
import audit


# ====================== 构造最小 audit dict ======================

def _make_audit_dict(trigger: str = "ci") -> dict:
    return {
        "schema_version": "1.0",
        "trigger": trigger,
        "timestamp": "2026-05-04 10:00:00",
        "actor": "test-actor",
        "requirement_id": "REQ-TEST",
        "from_phase": "dev",
        "to_phase": "test",
        "passed": [],
        "bypassed": [],
        "failed": [],
        "skipped": [],
        "escape_used": None,
        "rollback_failed": False,
        "exit_code": 0,
    }


# ====================== TC-F4-4：write_audit 调 subprocess ======================


def test_write_audit_calls_subprocess_once():
    """given_valid_audit_dict_when_write_audit_then_subprocess_run_called_once."""
    audit_dict = _make_audit_dict("ci")
    with patch("audit.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = audit.write_audit(audit_dict)
        assert mock_run.call_count == 1, (
            f"Expected subprocess.run called once, got {mock_run.call_count}"
        )


def test_write_audit_returns_path():
    """given_write_audit_when_called_then_returns_Path_instance（向后兼容）。"""
    audit_dict = _make_audit_dict("submit")
    with patch("audit.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = audit.write_audit(audit_dict)
        assert isinstance(result, Path), f"Expected Path, got {type(result)}"


def test_write_audit_subprocess_contains_audit_json():
    """given_audit_dict_when_write_audit_then_subprocess_cmd_contains_json_payload."""
    audit_dict = _make_audit_dict("ci")
    with patch("audit.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        audit.write_audit(audit_dict)
        assert mock_run.called
        call_args = mock_run.call_args
        # 验证命令包含 audit JSON 内容的关键字段
        cmd_str = str(call_args)
        assert "runner" in cmd_str, "entry='runner' 应在 subprocess 命令中"


def test_write_audit_bash_cmd_json_is_first_arg():
    """given_audit_dict_when_write_audit_then_bash_cmd_has_json_as_dollar1_not_audit_prefix.

    验证 F-004 bugfix：bash 命令展开后 $1 是 JSON 本身，不含 'audit ' 前缀。
    bash_cmd 应该是：audit_append_async '{JSON}' 'runner'
    而非旧的错误格式：audit_append_async audit '{JSON}' runner
    """
    audit_dict = _make_audit_dict("ci")
    with patch("audit.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        audit.write_audit(audit_dict)
        assert mock_run.called
        call_args = mock_run.call_args
        # 取 bash -c 后面的命令字符串
        bash_cmd = call_args[0][0][2]  # args[0] = ["bash", "-c", "<cmd>"]
        # 断言：不含 "audit_append_async audit " 这个错误格式
        assert "audit_append_async audit " not in bash_cmd, (
            "bash 命令不应包含 'audit' 前缀参数（旧错误格式）"
        )
        # 断言：命令中包含 schema_version（JSON 本身是 $1）
        assert "schema_version" in bash_cmd, "JSON payload 应作为 $1 出现在命令中"
        # 断言：'runner' 作为 $2 出现（加了单引号的形式）
        assert "'runner'" in bash_cmd, "entry name 'runner' 应加单引号作为 $2"


def test_write_audit_bash_cmd_json_parseable():
    """given_audit_dict_when_write_audit_then_bash_cmd_contains_parseable_json_payload.

    验证 bash 命令中提取出的 JSON 片段可以 json.loads 解析。
    格式期望：audit_append_async '<JSON>' 'runner'
    """
    audit_dict = _make_audit_dict("ci")
    with patch("audit.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        audit.write_audit(audit_dict)
        assert mock_run.called
        bash_cmd = mock_run.call_args[0][0][2]  # ["bash", "-c", "<cmd>"]
        # 提取 audit_append_async 后的第一个 shlex quoted 参数（即 JSON）
        import shlex
        tokens = shlex.split(bash_cmd.split("&&", 1)[-1].strip())
        # tokens[0] = "audit_append_async", tokens[1] = <JSON>, tokens[2] = "runner"
        assert tokens[0] == "audit_append_async"
        json_payload = tokens[1]
        parsed = json.loads(json_payload)
        assert parsed["schema_version"] == "1.0"
        assert parsed["trigger"] == "ci"
        assert tokens[2] == "runner", f"第三个 token 期望 'runner'，实际 {tokens[2]!r}"


def test_write_audit_subprocess_timeout_is_2():
    """given_write_audit_when_subprocess_called_then_timeout_is_2（防卡住）。"""
    audit_dict = _make_audit_dict("ci")
    with patch("audit.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        audit.write_audit(audit_dict)
        assert mock_run.called
        kwargs = mock_run.call_args.kwargs
        assert kwargs.get("timeout") == 2, (
            f"Expected timeout=2, got {kwargs.get('timeout')}"
        )


# ====================== TC-F4-2：audit 失败被 swallow ======================


def test_write_audit_subprocess_failure_silent():
    """given_subprocess_raises_when_write_audit_then_swallow_no_exception（D-005 best-effort）。"""
    audit_dict = _make_audit_dict("ci")
    with patch("audit.subprocess.run", side_effect=OSError("permission denied")):
        # 不应抛任何异常
        result = audit.write_audit(audit_dict)
        assert isinstance(result, Path)


def test_write_audit_subprocess_timeout_silent():
    """given_subprocess_timeout_when_write_audit_then_swallow（防止 gate 流程被卡住）。"""
    import subprocess
    audit_dict = _make_audit_dict("ci")
    with patch("audit.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="bash", timeout=2)):
        result = audit.write_audit(audit_dict)
        assert isinstance(result, Path)


def test_write_audit_multiple_calls_each_subprocess():
    """given_multiple_write_audit_calls_when_executed_then_subprocess_called_same_count."""
    audit_dict = _make_audit_dict("ci")
    with patch("audit.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        audit.write_audit(audit_dict)
        audit.write_audit(audit_dict)
        audit.write_audit(audit_dict)
        assert mock_run.call_count == 3, (
            f"Expected 3 subprocess calls for 3 write_audit calls, got {mock_run.call_count}"
        )


# ====================== _validate_bypass_reason ======================


def test_validate_bypass_reason_none_returns_none():
    """given_None_reason_when_validate_then_returns_None（不 bypass）。"""
    assert audit._validate_bypass_reason(None) is None


def test_validate_bypass_reason_short_returns_none():
    """given_short_reason_when_validate_then_returns_None（< 8 chars）。"""
    assert audit._validate_bypass_reason("abc") is None


def test_validate_bypass_reason_whitespace_only_returns_none():
    """given_whitespace_only_reason_when_validate_then_returns_None。"""
    assert audit._validate_bypass_reason("   ") is None


def test_validate_bypass_reason_valid_returns_cleaned():
    """given_valid_reason_when_validate_then_returns_cleaned_string。"""
    result = audit._validate_bypass_reason("fix-some-issue-here")
    assert result == "fix-some-issue-here"


def test_validate_bypass_reason_newline_escaped():
    """given_reason_with_newline_when_validate_then_newline_replaced_with_space。"""
    result = audit._validate_bypass_reason("fix\nFAKE_ENTRY")
    assert result is not None
    assert "\n" not in result
    assert "fix FAKE_ENTRY" == result


def test_validate_bypass_reason_cr_escaped():
    """given_reason_with_cr_when_validate_then_cr_replaced_with_space。"""
    result = audit._validate_bypass_reason("fix\rFAKE_ENTRY")
    assert result is not None
    assert "\r" not in result
