"""save_review.py signoff 子命令测试 + subparser 兼容性回归。

测试范围：
  (a) 兼容性回归：旧调用 'python3 save_review.py --req X --phase Y --reviewer Z'
      （无 cmd）走 save 路径等价
  (b) 新调用 'python3 save_review.py save --req X --phase Y --reviewer Z' 走 save
  (c) signoff 子命令：写 human_signoff + CR-1~CR-8 全跑 + process.txt append
  (d) _resolve_verdict_path 单测：REV-ID 反推路径
  (e) D-003 深防御第三层：非 tty stdin 直调 signoff 子命令 → 退出码 2

实现说明：
  - (a)(b) 用 monkeypatch mock _run_save/_run_signoff 验证路由
  - (c) 函数级单测，直接调 _run_signoff(args)，monkeypatch sys.stdin 为 tty
  - (e) subprocess 跑 save_review.py signoff，stdin=PIPE 非 tty → 退出码 2
  - 不引入任何 env var 旁路（FAKE_TTY 等已被 D-003 红线封禁）
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_LIB = _REPO_ROOT / "scripts" / "lib"

if str(_SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_LIB))

import save_review as sr  # noqa: E402
import signoff as _signoff  # noqa: E402  # F-012 rev2 拆模块：REQUIREMENTS_DIR 需同步 patch
from unittest.mock import patch


class _FakeTTY:
    """模拟 tty 的最小 stdin stub：isatty() 返回 True。

    用于函数级单测时绕过 D-003 深防御第三层的 tty 校验，
    使单测聚焦于签字业务逻辑而非 tty 机制本身。
    """

    def isatty(self) -> bool:
        return True


# ════════════════════════════════════════════════════════
# _resolve_verdict_path 单测
# ════════════════════════════════════════════════════════

class TestResolveVerdictPath:
    """_resolve_verdict_path(rev_id) 反推路径单测。

    F-012 rev3 M-5：_resolve_verdict_path 改返回 tuple[Path | None, str]，
    测试同步更新解包方式。
    """

    def test_definition_phase(self):
        """given_definition_rev_id_when_resolve_then_correct_path。"""
        path, reason = sr._resolve_verdict_path("REV-REQ-2026-003-definition-001")
        assert path is not None
        assert path.name == "definition-001.json"
        assert "REQ-2026-003" in str(path)

    def test_code_phase_with_feature_id(self):
        """given_code_phase_rev_id_with_feature_when_resolve_then_correct_path。"""
        path, reason = sr._resolve_verdict_path("REV-REQ-2026-003-code-F-001-001")
        assert path is not None
        assert path.name == "code-F-001-001.json"

    def test_invalid_format_returns_none(self):
        """given_invalid_rev_id_when_resolve_then_none。"""
        path, reason = sr._resolve_verdict_path("INVALID-ID")
        assert path is None
        assert reason == "invalid REV-ID format"
        path2, reason2 = sr._resolve_verdict_path("")
        assert path2 is None
        path3, reason3 = sr._resolve_verdict_path("REV-")
        assert path3 is None

    def test_outline_design_phase(self):
        """given_outline_design_rev_id_when_resolve_then_correct_path。"""
        path, reason = sr._resolve_verdict_path("REV-REQ-2026-003-outline-design-002")
        assert path is not None
        assert path.name == "outline-design-002.json"


# ════════════════════════════════════════════════════════
# (a) 兼容性回归：旧调用（无 cmd）走 save 路径
# ════════════════════════════════════════════════════════

def test_compat_no_subcommand_routes_to_save(monkeypatch):
    """given_no_subcommand_when_parse_args_then_cmd_none_and_runs_save_path。

    模拟旧调用：python3 save_review.py --req X --phase Y --reviewer Z
    验证 cmd=None 时路由到 _run_save（不是 _run_signoff）。
    """
    # 直接 mock sys.argv 并调 main()
    test_argv = ["save_review.py", "--req", "REQ-2099-001", "--phase", "definition",
                 "--reviewer", "requirement-quality-reviewer"]

    save_called: list[bool] = []
    signoff_called: list[bool] = []

    def fake_run_save(args):
        save_called.append(True)
        return 0

    def fake_run_signoff(args):
        signoff_called.append(True)
        return 0

    monkeypatch.setattr(sr, "_run_save", fake_run_save)
    monkeypatch.setattr(sr, "_run_signoff", fake_run_signoff)
    monkeypatch.setattr(sys, "argv", test_argv)

    rc = sr.main()

    assert rc == 0, f"期望 returncode=0，实际={rc}"
    assert save_called == [True], "期望 _run_save 被调用"
    assert signoff_called == [], "期望 _run_signoff 不被调用"


# ════════════════════════════════════════════════════════
# (b) 新调用：'save' 子命令显式走 save 路径
# ════════════════════════════════════════════════════════

def test_explicit_save_subcommand_routes_to_save(monkeypatch):
    """given_save_subcommand_when_main_called_then_runs_save_path。"""
    test_argv = ["save_review.py", "save", "--req", "REQ-2099-001",
                 "--phase", "definition", "--reviewer", "requirement-quality-reviewer"]

    save_called: list[bool] = []

    def fake_run_save(args):
        save_called.append(True)
        return 0

    monkeypatch.setattr(sr, "_run_save", fake_run_save)
    monkeypatch.setattr(sys, "argv", test_argv)

    rc = sr.main()

    assert rc == 0
    assert save_called == [True], "期望 _run_save 被调用"


# ════════════════════════════════════════════════════════
# (c) signoff 子命令：写 human_signoff + CR 全跑 + process.txt append
# ════════════════════════════════════════════════════════

def _make_valid_verdict() -> dict:
    """构造符合 F-001 schema 的合法 verdict（无 human_signoff）。"""
    return {
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


def test_signoff_subcommand_writes_human_signoff_and_appends_process_txt(tmp_path, monkeypatch):
    """given_valid_verdict_when_signoff_then_human_signoff_written_and_process_txt_appended。"""
    # 准备目录结构
    req_dir = tmp_path / "requirements" / "REQ-2099-001"
    reviews_dir = req_dir / "reviews"
    reviews_dir.mkdir(parents=True)
    process_txt = req_dir / "process.txt"
    process_txt.write_text("existing line\n", encoding="utf-8")

    verdict = _make_valid_verdict()
    verdict_path = reviews_dir / "definition-001.json"
    verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")

    # mock REQUIREMENTS_DIR 指向 tmp_path（同步 patch save_review + signoff，F-012 rev2 拆模块后 signoff 有自己的 REQUIREMENTS_DIR）
    monkeypatch.setattr(sr, "REQUIREMENTS_DIR", tmp_path / "requirements")
    monkeypatch.setattr(_signoff, "REQUIREMENTS_DIR", tmp_path / "requirements")
    # D-003 第三层 tty 校验：函数级单测模拟 tty，使测试聚焦签字业务逻辑
    monkeypatch.setattr(sys, "stdin", _FakeTTY())

    # 构造 args（模拟 argparse 解析的结果）
    # F-012 后 _run_signoff 接受 trivial 字段；显式传 False（与 --decision 互斥）
    args = argparse.Namespace(
        rev_id="REV-REQ-2099-001-definition-001",
        decision="approved",
        trivial=False,
        signed_by="dev@example.com",
        signed_at="2026-04-30T10:30:00+08:00",
        source="cli-tty",
    )

    rc = sr._run_signoff(args)

    assert rc == 0, f"期望 returncode=0，实际={rc}"

    # 验证 human_signoff 写入
    with verdict_path.open("r", encoding="utf-8") as f:
        updated = json.load(f)
    sig_field = updated.get("human_signoff", {})
    assert sig_field.get("decision") == "approved"
    assert sig_field.get("signed_by") == "dev@example.com"
    assert sig_field.get("signed_at") == "2026-04-30T10:30:00+08:00"
    assert sig_field.get("source") == "cli-tty"

    # 验证 process.txt 有 [signoff] 事件追加
    content = process_txt.read_text(encoding="utf-8")
    assert "[signoff]" in content, f"期望 process.txt 含 [signoff]，实际：{content!r}"
    assert "REV-REQ-2099-001-definition-001" in content
    assert "approved" in content
    assert "dev@example.com" in content
    assert content.startswith("existing line\n"), "期望保留原有 process.txt 内容（追加而非覆盖）"


def test_signoff_subcommand_rejects_already_signed(tmp_path, monkeypatch):
    """given_already_signed_verdict_when_signoff_then_returncode_5。"""
    req_dir = tmp_path / "requirements" / "REQ-2099-001"
    reviews_dir = req_dir / "reviews"
    reviews_dir.mkdir(parents=True)

    verdict = _make_valid_verdict()
    verdict["human_signoff"] = {
        "decision": "approved",
        "signed_by": "prev@example.com",
        "signed_at": "2026-04-29T10:00:00+08:00",
        "source": "cli-tty",
    }
    verdict_path = reviews_dir / "definition-001.json"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    monkeypatch.setattr(sr, "REQUIREMENTS_DIR", tmp_path / "requirements")
    monkeypatch.setattr(_signoff, "REQUIREMENTS_DIR", tmp_path / "requirements")
    # D-003 第三层 tty 校验：函数级单测模拟 tty
    monkeypatch.setattr(sys, "stdin", _FakeTTY())

    args = argparse.Namespace(
        rev_id="REV-REQ-2099-001-definition-001",
        decision="approved",
        trivial=False,
        signed_by="dev@example.com",
        signed_at="2026-04-30T10:30:00+08:00",
        source="cli-tty",
    )

    rc = sr._run_signoff(args)
    assert rc == 5, f"期望 returncode=5，实际={rc}"


def test_signoff_subcommand_rejects_nonexistent_rev_id(monkeypatch):
    """given_nonexistent_rev_id_when_signoff_then_returncode_4。"""
    # D-003 第三层 tty 校验：函数级单测模拟 tty，聚焦"verdict 不存在"业务逻辑
    monkeypatch.setattr(sys, "stdin", _FakeTTY())
    args = argparse.Namespace(
        rev_id="REV-REQ-9999-001-definition-999",
        decision="approved",
        trivial=False,
        signed_by="dev@example.com",
        signed_at="2026-04-30T10:30:00+08:00",
        source="cli-tty",
    )
    rc = sr._run_signoff(args)
    assert rc == 4, f"期望 returncode=4，实际={rc}"


def test_signoff_subcommand_rejects_verdict_with_cr_violation(tmp_path, monkeypatch):
    """given_verdict_with_cr_violation_when_signoff_then_returncode_1。

    CR-4：score < 70 时签字通过，sign-off 会触发 CR-4（已签字 + score < 70）。
    注意：实际 CR-4 检查在写入 human_signoff 后、CR 全量重跑时触发。
    """
    req_dir = tmp_path / "requirements" / "REQ-2099-001"
    reviews_dir = req_dir / "reviews"
    reviews_dir.mkdir(parents=True)

    # score=50 + conclusion=needs_attention（CR-4 不触发，但 CR-4 写入 human_signoff 后 is_signed_off=True + score<70）
    # 实际测试：score=50 + conclusion=looks_clean → CR-4 会触发
    verdict = _make_valid_verdict()
    verdict["score"] = 50
    verdict["conclusion"] = "looks_clean"  # CR-3/CR-4 会冲突，保证 CR 检查失败
    verdict_path = reviews_dir / "definition-001.json"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    monkeypatch.setattr(sr, "REQUIREMENTS_DIR", tmp_path / "requirements")
    monkeypatch.setattr(_signoff, "REQUIREMENTS_DIR", tmp_path / "requirements")
    # D-003 第三层 tty 校验：函数级单测模拟 tty，使测试聚焦 CR 校验业务逻辑
    monkeypatch.setattr(sys, "stdin", _FakeTTY())

    args = argparse.Namespace(
        rev_id="REV-REQ-2099-001-definition-001",
        decision="approved",
        trivial=False,
        signed_by="dev@example.com",
        signed_at="2026-04-30T10:30:00+08:00",
        source="cli-tty",
    )

    rc = sr._run_signoff(args)
    # score=50 + conclusion=looks_clean 触发 CR-4，签字被拒
    assert rc == 1, f"期望 returncode=1（CR 校验失败），实际={rc}"


def test_should_detect_develop_when_origin_head_points_develop():
    """given_origin_head_points_develop_when_detect_default_base_then_returns_develop。

    F-012 rev3 新增：验证 _detect_default_base 能正确从 git symbolic-ref 推导 develop。
    """
    # 重置缓存，防 fixture 间污染（F-012 rev4 N-3）
    _signoff._reset_default_base_cache()

    # mock subprocess.run：git symbolic-ref 返回 "origin/develop"
    fake_symbolic_ref_result = subprocess.CompletedProcess(
        args=["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        returncode=0,
        stdout="origin/develop\n",
        stderr="",
    )

    with patch("signoff.subprocess.run", return_value=fake_symbolic_ref_result) as mock_run:
        result = _signoff._detect_default_base()

    assert result == "develop", f"期望 'develop'，实际={result!r}"
    # 验证只调用了一次 git symbolic-ref（无需走 fallback）
    assert mock_run.call_count == 1
    call_args = mock_run.call_args
    assert "symbolic-ref" in call_args[0][0]


def test_should_use_cached_value_on_repeat_call():
    """given_cached_detect_default_base_when_called_twice_then_subprocess_called_once。

    F-012 rev4 新增：验证模块级缓存生效，第二次调用不重新 fork 进程（N-3）。
    """
    # 重置缓存，确保干净起点
    _signoff._reset_default_base_cache()

    fake_result = subprocess.CompletedProcess(
        args=["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        returncode=0,
        stdout="origin/develop\n",
        stderr="",
    )

    with patch("signoff.subprocess.run", return_value=fake_result) as mock_run:
        first = _signoff._detect_default_base()
        second = _signoff._detect_default_base()

    assert first == "develop"
    assert second == "develop"
    # 第二次调用命中缓存，subprocess.run 只应被调用 1 次
    assert mock_run.call_count == 1, (
        f"期望 subprocess.run 只调用 1 次（缓存命中），实际={mock_run.call_count}"
    )
    # 收尾：重置缓存避免污染后续 fixture
    _signoff._reset_default_base_cache()


def test_signoff_subcommand_non_tty_stdin_returns_rc2():
    """given_non_tty_stdin_when_signoff_then_returncode_2_e2e。

    D-003 深防御第三层端到端验证：subprocess 直调 save_review.py signoff，
    stdin=PIPE 即非 tty，期望退出 2 + stderr 含 'stdin not a tty'。
    防 AI 绕过 Command + Skill 两层 tty 校验直接调本入口完成代签。
    """
    cmd = [
        sys.executable,
        str(_SCRIPTS_LIB / "save_review.py"),
        "signoff",
        "--rev-id", "REV-REQ-2099-001-definition-001",
        "--decision", "approved",
        "--signed-by", "test@test.com",
        "--signed-at", "2026-04-30T03:00:00+08:00",
    ]
    proc = subprocess.run(cmd, input="", capture_output=True, text=True)
    assert proc.returncode == 2, f"期望 returncode=2，实际={proc.returncode}\nstderr={proc.stderr}"
    assert "stdin not a tty" in proc.stderr, f"stderr 缺关键串：{proc.stderr}"
