"""check-signoff.sh wrapper 集成测试。

验收要求：
  - fixture 1：human_signoff.decision=approved → returncode 0
  - fixture 2：无 human_signoff 字段 → returncode 1

来源：requirements/REQ-2026-003/artifacts/detailed-design.md §F-004.4 / §F-004.9 TC-B8/TC-B11
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

# 仓库根目录（tests/integration/../../ = 仓库根）
_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER = _REPO_ROOT / "scripts" / "check-signoff.sh"


def _write_fixture(tmp_path: Path, filename: str, verdict: dict) -> Path:
    """在 tmp_path 写入 verdict JSON，返回文件路径。"""
    fixture_path = tmp_path / filename
    fixture_path.write_text(json.dumps(verdict, ensure_ascii=False), encoding="utf-8")
    return fixture_path


@pytest.fixture()
def signed_verdict(tmp_path: Path) -> Path:
    """已签字 verdict：human_signoff.decision=approved。"""
    return _write_fixture(tmp_path, "signed.json", {
        "schema_version": "1.0",
        "review_id": "REV-REQ-2099-TEST-definition-001",
        "requirement_id": "REQ-2099-TEST",
        "phase": "definition",
        "conclusion": "looks_clean",
        "human_signoff": {
            "decision": "approved",
            "signed_at": "2026-04-30T14:00:00+0800",
            "signed_by": "dev@example.com",
            "source": "cli-tty",
        },
    })


@pytest.fixture()
def unsigned_verdict(tmp_path: Path) -> Path:
    """未签字 verdict：无 human_signoff 字段（模拟旧 schema）。"""
    return _write_fixture(tmp_path, "unsigned.json", {
        "schema_version": "1.0",
        "review_id": "REV-REQ-2099-TEST-definition-002",
        "requirement_id": "REQ-2099-TEST",
        "phase": "definition",
        "conclusion": "looks_clean",
        # 故意不含 human_signoff
    })


def _run_wrapper(verdict_path: Path) -> subprocess.CompletedProcess:
    """执行 check-signoff.sh，从仓库根目录运行以保证 sys.path 正确。"""
    return subprocess.run(
        ["bash", str(_WRAPPER), str(verdict_path)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),  # 必须从仓库根运行，sys.path.insert("scripts/lib") 依赖此路径
    )


class TestCheckSignoffWrapper:
    """check-signoff.sh wrapper 集成测试套件。"""

    def test_signed_verdict_returns_exit_code_0(self, signed_verdict: Path) -> None:
        """已签字 verdict：wrapper 退出码 0（已签）。"""
        result = _run_wrapper(signed_verdict)
        assert result.returncode == 0, (
            f"已签字 verdict 应返回退出码 0，实际 {result.returncode}。"
            f"\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_unsigned_verdict_returns_exit_code_1(self, unsigned_verdict: Path) -> None:
        """未签字 verdict（无 human_signoff）：wrapper 退出码 1（未签）。"""
        result = _run_wrapper(unsigned_verdict)
        assert result.returncode == 1, (
            f"未签字 verdict 应返回退出码 1，实际 {result.returncode}。"
            f"\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_approved_trivial_returns_exit_code_0(self, tmp_path: Path) -> None:
        """decision=approved-trivial 等价于 approved，wrapper 退出码 0。"""
        verdict_path = _write_fixture(tmp_path, "trivial.json", {
            "schema_version": "1.0",
            "review_id": "REV-REQ-2099-TEST-definition-003",
            "requirement_id": "REQ-2099-TEST",
            "phase": "definition",
            "conclusion": "looks_clean",
            "human_signoff": {
                "decision": "approved-trivial",
                "signed_at": "2026-04-30T14:00:00+0800",
                "signed_by": "dev@example.com",
                "source": "cli-tty",
            },
        })
        result = _run_wrapper(verdict_path)
        assert result.returncode == 0, (
            f"approved-trivial verdict 应返回退出码 0，实际 {result.returncode}"
        )

    def test_rejected_decision_returns_exit_code_1(self, tmp_path: Path) -> None:
        """decision=rejected：wrapper 退出码 1（未通过 sign-off）。"""
        verdict_path = _write_fixture(tmp_path, "rejected.json", {
            "schema_version": "1.0",
            "review_id": "REV-REQ-2099-TEST-definition-004",
            "requirement_id": "REQ-2099-TEST",
            "phase": "definition",
            "conclusion": "blocked",
            "human_signoff": {
                "decision": "rejected",
                "signed_at": "2026-04-30T14:00:00+0800",
                "signed_by": "dev@example.com",
                "source": "cli-tty",
            },
        })
        result = _run_wrapper(verdict_path)
        assert result.returncode == 1, (
            f"rejected decision 应返回退出码 1，实际 {result.returncode}"
        )

    def test_wrapper_is_executable(self) -> None:
        """check-signoff.sh 必须具有可执行权限。"""
        assert _WRAPPER.exists(), f"wrapper 脚本不存在：{_WRAPPER}"
        assert _WRAPPER.stat().st_mode & 0o111, "wrapper 脚本缺少可执行权限"
