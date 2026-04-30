"""signoff Command 测试（TC-B1 / TC-B2 / TC-B5 / TC-B6 / TC-B7）。

测试范围：
  TC-B1  tty + 普通 sign-off（函数级单测 + mock）：verdict.human_signoff 全字段填充
  TC-B2  非 tty → returncode 2，stderr 含 'stdin not a tty'（subprocess 断端到端）
  TC-B5  --trivial + 含 .py diff → returncode 3，stderr 'non-doc files detected'
  TC-B6  已签 verdict → returncode 5，stderr 'already signed'
  TC-B7  不存在 REV-ID → returncode 4，stderr 'verdict ... not found'

实现说明：
  - TC-B1（tty 正向场景）：函数级单测，monkeypatch mock _check_tty / git 调用
    直接调 _run_signoff_skill()，不依赖 env var 旁路
  - TC-B2/B5/B6/B7（端到端拒收）：subprocess 跑入口脚本，stdin=PIPE 自动为非 tty，
    其中 TC-B5/B6/B7 需要 mock tty=True，故也用函数级单测 + monkeypatch
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_LIB = _REPO_ROOT / "scripts" / "lib"
_SCRIPT = _SCRIPTS_LIB / "code_review_signoff.py"

if str(_SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_LIB))

import code_review_signoff as sig  # noqa: E402


# ════════════════════════════════════════════════════════
# TC-B1：tty + 普通 sign-off → human_signoff 全字段填充
# ════════════════════════════════════════════════════════

def test_tc_b1_signoff_writes_human_signoff_fields(tmp_path, monkeypatch):
    """given_tty_when_valid_rev_id_then_human_signoff_all_fields_written_and_returncode_0。"""
    # 准备一个合法的 verdict 文件（无 human_signoff）
    verdict = {
        "schema_version": "1.0",
        "review_id": "REV-REQ-2099-001-definition-001",
        "requirement_id": "REQ-2099-001",
        "phase": "definition",
        "reviewer": "requirement-quality-reviewer",
        "reviewed_at": "2026-04-30 10:00:00",
        "reviewed_commit": "abc1234",
        "reviewed_artifacts": [],
        "conclusion": "looks_clean",
        "score": 88,
        "dimensions": {},
        "required_fixes": [],
        "suggestions": [],
        "scope": None,
        "supersedes": None,
    }

    # 建立 requirements/REQ-2099-001/reviews/ 目录
    req_dir = tmp_path / "requirements" / "REQ-2099-001"
    reviews_dir = req_dir / "reviews"
    reviews_dir.mkdir(parents=True)
    # 写入 process.txt（供 append 测试）
    process_txt = req_dir / "process.txt"
    process_txt.write_text("", encoding="utf-8")

    verdict_path = reviews_dir / "definition-001.json"
    verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")

    rev_id = "REV-REQ-2099-001-definition-001"

    # mock：tty=True，git email，时间戳，_resolve_verdict_path，_call_save_review_signoff
    monkeypatch.setattr(sig, "_check_tty", lambda: True)
    monkeypatch.setattr(sig, "_get_git_email", lambda: "test@example.com")
    monkeypatch.setattr(sig, "_get_iso8601_now", lambda: "2026-04-30T10:00:00+08:00")
    monkeypatch.setattr(sig, "_resolve_verdict_path", lambda _: verdict_path)

    # mock _call_save_review_signoff：实际写入 human_signoff 字段并返回 0
    def fake_call(rev_id, decision, signed_by, signed_at, source="cli-tty"):
        with verdict_path.open("r", encoding="utf-8") as f:
            v = json.load(f)
        v["human_signoff"] = {
            "decision": decision,
            "signed_by": signed_by,
            "signed_at": signed_at,
            "source": source,
        }
        verdict_path.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    monkeypatch.setattr(sig, "_call_save_review_signoff", fake_call)

    rc = sig._run_signoff_skill(rev_id, "approved", False)

    assert rc == 0, f"期望 returncode=0，实际={rc}"

    # 验证 human_signoff 字段已写入
    with verdict_path.open("r", encoding="utf-8") as f:
        updated = json.load(f)
    sig_field = updated.get("human_signoff", {})
    assert sig_field.get("decision") == "approved", f"decision 期望 approved，实际={sig_field}"
    assert sig_field.get("signed_by") == "test@example.com", f"signed_by 不匹配：{sig_field}"
    assert sig_field.get("signed_at") == "2026-04-30T10:00:00+08:00", f"signed_at 不匹配：{sig_field}"
    assert sig_field.get("source") == "cli-tty", f"source 期望 cli-tty，实际={sig_field}"


# ════════════════════════════════════════════════════════
# TC-B2：非 tty stdin → returncode 2（subprocess 端到端）
# ════════════════════════════════════════════════════════

def test_tc_b2_non_tty_returns_rc2():
    """given_non_tty_stdin_when_signoff_then_returncode_2_and_stderr_contains_not_a_tty。"""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--rev-id", "REV-XXX", "--decision", "approved"],
        input="",
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 2, (
        f"期望 returncode=2，实际={result.returncode}\nstderr={result.stderr}"
    )
    assert "stdin not a tty" in result.stderr, (
        f"期望 stderr 含 'stdin not a tty'，实际={result.stderr!r}"
    )


# ════════════════════════════════════════════════════════
# TC-B5：--trivial + 含 .py diff → returncode 3
# ════════════════════════════════════════════════════════

def test_tc_b5_trivial_with_non_doc_files_returns_rc3(monkeypatch):
    """given_tty_and_trivial_when_diff_contains_py_then_returncode_3_and_non_doc_detected。"""
    monkeypatch.setattr(sig, "_check_tty", lambda: True)
    monkeypatch.setattr(sig, "_get_trivial_diff_paths", lambda: ["src/foo.py", "README.md"])

    # 用假 verdict 路径避免文件查找失败（trivial 路径失败前就 return 3）
    monkeypatch.setattr(sig, "_resolve_verdict_path", lambda _: Path("/nonexistent/verdict.json"))

    with mock.patch("sys.stderr") as mock_stderr:
        rc = sig._run_signoff_skill("REV-XXX", None, trivial=True)

    assert rc == 3, f"期望 returncode=3，实际={rc}"


def test_tc_b5_trivial_non_doc_stderr_contains_keyword(monkeypatch, capsys):
    """given_trivial_non_doc_files_when_run_then_stderr_contains_non_doc_files_detected。"""
    monkeypatch.setattr(sig, "_check_tty", lambda: True)
    monkeypatch.setattr(sig, "_get_trivial_diff_paths", lambda: ["src/bar.py"])

    sig._run_signoff_skill("REV-XXX", None, trivial=True)

    captured = capsys.readouterr()
    assert "non-doc files detected" in captured.err, (
        f"期望 stderr 含 'non-doc files detected'，实际={captured.err!r}"
    )


# ════════════════════════════════════════════════════════
# TC-B6：已签 verdict → returncode 5
# ════════════════════════════════════════════════════════

def test_tc_b6_already_signed_returns_rc5(tmp_path, monkeypatch):
    """given_tty_when_verdict_already_signed_then_returncode_5_and_already_signed_in_stderr。"""
    # 创建一个已签字的 verdict
    verdict = {
        "conclusion": "looks_clean",
        "human_signoff": {
            "decision": "approved",
            "signed_by": "prev@example.com",
            "signed_at": "2026-04-29T10:00:00+08:00",
            "source": "cli-tty",
        },
    }
    verdict_path = tmp_path / "definition-001.json"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    monkeypatch.setattr(sig, "_check_tty", lambda: True)
    monkeypatch.setattr(sig, "_resolve_verdict_path", lambda _: verdict_path)

    rc = sig._run_signoff_skill("REV-REQ-2099-001-definition-001", "approved", False)

    assert rc == 5, f"期望 returncode=5，实际={rc}"


def test_tc_b6_already_signed_stderr_contains_keyword(tmp_path, monkeypatch, capsys):
    """given_already_signed_when_run_then_stderr_contains_already_signed。"""
    verdict = {
        "conclusion": "looks_clean",
        "human_signoff": {
            "decision": "approved",
            "signed_by": "prev@example.com",
            "signed_at": "2026-04-29T10:00:00+08:00",
            "source": "cli-tty",
        },
    }
    verdict_path = tmp_path / "definition-001.json"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    monkeypatch.setattr(sig, "_check_tty", lambda: True)
    monkeypatch.setattr(sig, "_resolve_verdict_path", lambda _: verdict_path)

    sig._run_signoff_skill("REV-REQ-2099-001-definition-001", "approved", False)

    captured = capsys.readouterr()
    assert "already signed" in captured.err, (
        f"期望 stderr 含 'already signed'，实际={captured.err!r}"
    )


# ════════════════════════════════════════════════════════
# TC-B7：不存在 REV-ID → returncode 4（subprocess 端到端）
# ════════════════════════════════════════════════════════

def test_tc_b7_nonexistent_rev_id_returns_rc4():
    """given_non_tty_when_nonexistent_rev_id_then_returncode_4_and_not_found_in_stderr。

    注意：非 tty stdin 会先触发退出码 2（tty 校验在文件查找之前）。
    此 TC 用函数级单测 mock tty=True 来验证 verdict 查找的退出码 4。
    """
    # 需要 tty=True 才能到达文件查找逻辑——用函数级单测
    pass  # 见下方 test_tc_b7_verdict_not_found_rc4_unit


def test_tc_b7_verdict_not_found_rc4_unit(monkeypatch, capsys):
    """given_tty_when_rev_id_not_found_then_returncode_4_and_not_found_in_stderr（函数级）。"""
    monkeypatch.setattr(sig, "_check_tty", lambda: True)
    monkeypatch.setattr(sig, "_get_git_email", lambda: "test@example.com")

    # 使用一个不存在路径
    monkeypatch.setattr(sig, "_resolve_verdict_path", lambda _: Path("/nonexistent/does_not_exist.json"))

    rc = sig._run_signoff_skill("REV-NONEXISTENT-001", "approved", False)

    assert rc == 4, f"期望 returncode=4，实际={rc}"
    captured = capsys.readouterr()
    assert "not found" in captured.err, (
        f"期望 stderr 含 'not found'，实际={captured.err!r}"
    )
