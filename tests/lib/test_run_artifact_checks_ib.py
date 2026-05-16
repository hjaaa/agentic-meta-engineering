"""F-CR-004 · _check_schema OSError 宽化回归测试（IB-B3 hardening）。

覆盖：
- TC-FCR004-1：subprocess.run 抛 PermissionError（OSError 子类）→ run_artifact_checks 返回 failures 含错误描述
- TC-FCR004-2：subprocess.run 抛 FileNotFoundError → 行为不变（原有捕获路径保持）
- TC-FCR004-3：subprocess.run 抛 TimeoutExpired → 行为不变（原有捕获路径保持）

测试运行：
    python3 -m pytest tests/lib/test_run_artifact_checks_ib.py -v
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

from run_artifact_checks import run_artifact_checks  # noqa: E402


# ============================================================================
# TC-FCR004-1：PermissionError（OSError 子类）被捕获，归入 failures
# ============================================================================

def test_check_schema_permission_error_captured(tmp_path: Path) -> None:
    """F-CR-004：PermissionError 应被 _check_schema 捕获，加入 failures 而非向上穿透。

    修复前 except (FileNotFoundError, subprocess.TimeoutExpired) 无法捕获 PermissionError，
    会向上逃逸；修复后 except (OSError, subprocess.TimeoutExpired) 覆盖所有 OSError 子类。
    """
    # 构造一个带 schema_check 项的 spec（脚本路径任意，因为会被 mock 拦截）
    spec = {
        "schema_check": [
            {"script": "scripts/lib/check_meta.py", "args": ["some/file.yaml"], "expected_exit_code": 0}
        ]
    }

    with patch("subprocess.run", side_effect=PermissionError("Permission denied: check_meta.py")):
        failures = run_artifact_checks(spec, cwd=tmp_path)

    assert len(failures) == 1, f"期望 1 条 failure，实际 {failures}"
    assert "PermissionError" in failures[0] or "Permission denied" in failures[0], (
        f"failure 消息应含错误信息，实际：{failures[0]!r}"
    )


# ============================================================================
# TC-FCR004-2：FileNotFoundError 行为不变（原有路径保持兼容）
# ============================================================================

def test_check_schema_file_not_found_still_captured(tmp_path: Path) -> None:
    """F-CR-004 兼容性：FileNotFoundError 仍应被捕获（OSError 的子类，修改后仍覆盖）。"""
    spec = {
        "schema_check": [
            {"script": "no_such_script.py", "args": [], "expected_exit_code": 0}
        ]
    }

    with patch("subprocess.run", side_effect=FileNotFoundError("no_such_script.py")):
        failures = run_artifact_checks(spec, cwd=tmp_path)

    assert len(failures) == 1, f"期望 1 条 failure，实际 {failures}"


# ============================================================================
# TC-FCR004-3：TimeoutExpired 行为不变
# ============================================================================

def test_check_schema_timeout_still_captured(tmp_path: Path) -> None:
    """F-CR-004 兼容性：TimeoutExpired 仍应被捕获（仍在 except 列表中）。"""
    spec = {
        "schema_check": [
            {"script": "scripts/lib/slow_script.py", "args": [], "expected_exit_code": 0}
        ]
    }
    timeout_exc = subprocess.TimeoutExpired(cmd=["scripts/lib/slow_script.py"], timeout=120)

    with patch("subprocess.run", side_effect=timeout_exc):
        failures = run_artifact_checks(spec, cwd=tmp_path)

    assert len(failures) == 1, f"期望 1 条 failure，实际 {failures}"
