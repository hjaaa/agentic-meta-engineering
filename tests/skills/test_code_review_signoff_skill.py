"""code-review-signoff Skill 测试（TC-B3 / TC-B4 / TC-B5 trivial 单测）。

F-012 重构后，code_review_signoff.py 已被删除；卡点 B 唯一入口为：
  python3 scripts/lib/save_review.py signoff --rev-id <REV-ID> [--decision <v>] [--trivial]

测试范围：
  TC-B3  非 tty 直调 Skill（绕过 Command）→ 退出码 2（深防御命中）
  TC-B4  --trivial + 全 .md diff → decision=approved-trivial，退出 0
  TC-B5  _check_trivial_paths 纯函数单测：含 .py → non_doc_paths 非空

实现说明：
  - TC-B3（端到端非 tty）：subprocess 跑 save_review.py signoff，stdin=PIPE 自动非 tty
  - TC-B4（trivial 通过）：函数级单测 mock tty + git diff
  - TC-B5 trivial 纯函数：直接调 _check_trivial_paths()，无需 tty 或文件

禁止任何 FAKE_TTY / DRY_RUN_TTY env var 旁路（D-003 红线）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_LIB = _REPO_ROOT / "scripts" / "lib"
_SCRIPT = _SCRIPTS_LIB / "save_review.py"

if str(_SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_LIB))

import signoff as sig  # noqa: E402  # F-012 rev2 拆模块后，signoff 函数迁入 signoff.py


def _make_args(
    rev_id: str,
    decision: str | None = None,
    trivial: bool = False,
    signed_by: str | None = None,
    signed_at: str | None = None,
) -> argparse.Namespace:
    """构造 _run_signoff 期望的 Namespace。"""
    return argparse.Namespace(
        rev_id=rev_id,
        decision=decision,
        trivial=trivial,
        signed_by=signed_by,
        signed_at=signed_at,
        source="cli-tty",
    )


# ════════════════════════════════════════════════════════
# TC-B3：非 tty 直调 Skill（subprocess）→ 退出码 2（深防御）
# ════════════════════════════════════════════════════════

def test_tc_b3_non_tty_direct_skill_call_returns_rc2():
    """given_non_tty_when_skill_called_directly_bypassing_command_then_returncode_2。

    验证：save_review.py signoff 的 tty 校验在 stdin 非 tty 时生效（深防御）。
    使用 subprocess.run + stdin=PIPE 确保 stdin 真正为非 tty。
    """
    import subprocess
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "signoff", "--rev-id", "REV-XXX", "--decision", "approved"],
        input="",
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 2, (
        f"期望 returncode=2（深防御命中），实际={result.returncode}\n"
        f"stderr={result.stderr}"
    )
    assert "stdin not a tty" in result.stderr, (
        f"期望 stderr 含 'stdin not a tty'，实际={result.stderr!r}"
    )


# ════════════════════════════════════════════════════════
# TC-B4：--trivial + 全 .md diff → decision=approved-trivial，退出 0
# ════════════════════════════════════════════════════════

def test_tc_b4_trivial_all_md_files_returns_approved_trivial(tmp_path, monkeypatch):
    """given_tty_and_trivial_when_diff_all_md_then_decision_approved_trivial_and_rc_0。"""
    import json

    # 准备假 verdict 文件（无 human_signoff）+ 完整 schema 字段以通过 CR 校验
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
        "score": 90,
        "dimensions": {},
        "required_fixes": [],
        "suggestions": [],
        "scope": None,
        "supersedes": None,
        "human_signoff": None,
    }
    # 建立临时 requirements/REQ-2099-001/reviews/ + process.txt
    req_dir = tmp_path / "requirements" / "REQ-2099-001"
    reviews_dir = req_dir / "reviews"
    reviews_dir.mkdir(parents=True)
    (req_dir / "process.txt").write_text("", encoding="utf-8")
    verdict_path = reviews_dir / "definition-001.json"
    verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")

    # mock tty、diff、email、时间、路径、REQUIREMENTS_DIR
    monkeypatch.setattr(sig.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sig, "_get_trivial_diff_paths", lambda: ["README.md", "docs/guide.md", "notes.txt"])
    monkeypatch.setattr(sig, "_get_git_email", lambda: "test@example.com")
    monkeypatch.setattr(sig, "_get_iso8601_now", lambda: "2026-04-30T10:00:00+08:00")
    monkeypatch.setattr(sig, "_resolve_verdict_path", lambda _: verdict_path)
    monkeypatch.setattr(sig, "REQUIREMENTS_DIR", tmp_path / "requirements")

    rc = sig._run_signoff(_make_args("REV-REQ-2099-001-definition-001", trivial=True))

    assert rc == 0, f"期望 returncode=0，实际={rc}"
    # 验证写入文件的 decision 是 approved-trivial
    with verdict_path.open("r", encoding="utf-8") as f:
        updated = json.load(f)
    assert updated["human_signoff"]["decision"] == "approved-trivial", (
        f"期望 decision=approved-trivial，实际={updated['human_signoff']}"
    )


# ════════════════════════════════════════════════════════
# TC-B5：_check_trivial_paths 纯函数单测
# ════════════════════════════════════════════════════════

def test_tc_b5_check_trivial_paths_all_doc_files():
    """given_only_md_txt_doc_paths_when_check_trivial_then_all_doc_is_true。"""
    paths = ["README.md", "docs/api.md", "CHANGELOG.txt", "docs/subdir/note.md"]
    all_doc, non_doc = sig._check_trivial_paths(paths)
    assert all_doc is True, f"期望 all_doc=True，non_doc={non_doc}"
    assert non_doc == [], f"期望 non_doc 为空，实际={non_doc}"


def test_tc_b5_check_trivial_paths_contains_py():
    """given_diff_contains_py_when_check_trivial_then_all_doc_is_false_and_non_doc_contains_py。"""
    paths = ["README.md", "src/foo.py", "docs/guide.md"]
    all_doc, non_doc = sig._check_trivial_paths(paths)
    assert all_doc is False, "期望 all_doc=False（含 .py 文件）"
    assert "src/foo.py" in non_doc, f"期望 non_doc 含 src/foo.py，实际={non_doc}"


def test_tc_b5_check_trivial_paths_contains_yaml():
    """given_diff_contains_yaml_when_check_trivial_then_all_doc_is_false。"""
    paths = ["config.yaml", "README.md"]
    all_doc, non_doc = sig._check_trivial_paths(paths)
    assert all_doc is False, "期望 all_doc=False（含 .yaml 文件）"
    assert "config.yaml" in non_doc


def test_tc_b5_check_trivial_paths_empty_list():
    """given_empty_diff_when_check_trivial_then_all_doc_is_true。"""
    all_doc, non_doc = sig._check_trivial_paths([])
    assert all_doc is True, "期望空列表时 all_doc=True"
    assert non_doc == []


def test_tc_b5_check_trivial_paths_docs_subdir():
    """given_docs_subdir_files_when_check_trivial_then_all_doc_is_true。"""
    paths = ["docs/zh/README.md", "docs/en/api.md"]
    all_doc, non_doc = sig._check_trivial_paths(paths)
    assert all_doc is True, f"期望 docs/** 全通过，non_doc={non_doc}"
