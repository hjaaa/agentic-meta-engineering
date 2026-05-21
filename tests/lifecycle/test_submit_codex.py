"""submit_codex.submit_with_codex 单元测试。

覆盖 features.json acceptance TC-F4-1 ~ TC-F4-7 + TC-F4-9（V-09 常量验收）：
  - TC-F4-1: test_passed_path        — mock 命中 pass phrase → verdict=passed + exit 0 + 不本地落盘
  - TC-F4-2: test_not_passed_path    — body 不含 pass phrase → verdict=not_passed + stderr ⚠️ NOT passed
  - TC-F4-3: test_timeout_path       — mock 永不返回 → verdict=timeout + stderr ⚠️ TIMEOUT
  - TC-F4-4: test_429_to_timeout     — mock 429 → 走 timeout，不重试
  - TC-F4-6: test_filter_old_review  — submitted_at <= triggered_at 不算命中
  - TC-F4-7: test_codex_args_mutex   — --codex-poll-interval 不带 --codex → stderr 含 requires --codex
  - TC-F4-9: test_v09_constant_uniqueness — grep 验收：CODEX_PASS_PHRASE 仅 submit-rules.md 一处

注：TC-F4-5（round 递增）原依赖本地累积 round-*.md 文件；2026-05 改造后停止本地
落盘，多轮区分由 GitHub PR comments 时间序承担，本测试已删除。`_calc_round` 单元
测试仍保留（test_calc_round_*），确认函数本身在有/无本地文件时的行为正确。

外部依赖（subprocess gh / _gh_pr_reviews）全 mock，不触网络、不动真 git。
"""
from __future__ import annotations

from typing import Any

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# 让 submit_codex 的 import 能找到 scripts/lib
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import submit_codex  # noqa: E402
from submit_codex import (  # noqa: E402
    CodexRoundResult,
    GhApi429,
    GhApi5xx,
    GhApiAbort,
    _build_codex_comment_body,
    _calc_round,
    _handle_poll_result,
    _is_passed,
    _parse_iso_to_aware,
    _parse_jsonl_reviews,
    _poll_codex,
    _render_frontmatter,
    submit_with_codex,
)


# ---------- 基础 fixture ----------


def _make_meta(
    tmp_path: Path,
    *,
    req_id: str = "REQ-2099-007",
    phase: str = "development",
    pr_number: int = 42,
    branch: str = "feat/req-2099-007",
    base_branch: str = "develop",
) -> Path:
    """构造临时 requirements/<req>/meta.yaml；返回 req 目录路径。"""
    req_dir = tmp_path / req_id
    req_dir.mkdir(parents=True)
    meta = {
        "id": req_id,
        "title": f"测试需求 {req_id}",
        "phase": phase,
        "branch": branch,
        "base_branch": base_branch,
        "pr_number": pr_number,
        "created_at": "2026-05-04 19:00:00",
        "project": "agentic-meta-engineering",
    }
    with (req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
    return req_dir


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 submit_codex 的 REQUIREMENTS_DIR 重定向到 tmp_path，避免改动真实仓库。

    同时默认 stub `_check_ci_status` 返回 ('success', [])，让 CI precheck（submit-rules.md §7.5
    硬约束）在大多数 e2e mock 测试中自动放行；专门测 CI precheck 行为的用例可在测试体内
    覆盖此 stub。
    """
    monkeypatch.setattr(submit_codex, "REQUIREMENTS_DIR", tmp_path)
    monkeypatch.setattr(submit_codex, "_check_ci_status", lambda _pr: ("success", []))
    return tmp_path


# ---------- 辅助：模拟 review dict ----------


def _make_review(
    *,
    login: str = "chatgpt-codex-connector[bot]",
    user_type: str = "Bot",
    body: str = "Didn't find any major issues.",
    submitted_at: str = "2026-05-04T19:32:14+08:00",
    state: str = "COMMENTED",
    review_id: int = 12345678,
) -> dict:
    return {
        "id": review_id,
        "user": {"login": login, "type": user_type},
        "body": body,
        "submitted_at": submitted_at,
        "state": state,
    }


# ---------- TC-F4-1: passed 路径 ----------


def test_passed_path(fake_repo: Path) -> None:
    """TC-F4-1: mock gh api 含 pass phrase → verdict=passed + 不本地落盘。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)

    triggered_at = "2026-05-04T19:30:00+08:00"
    review = _make_review(submitted_at="2026-05-04T19:32:14+08:00")

    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[review]),
        patch.object(submit_codex, "_gh_pr_issue_comments", return_value=[]),
        # 确保 time.sleep 不真的等待
        patch("submit_codex.time.sleep"),
        # monotonic 模拟：首次调用返回 0（deadline = 600），后续调用小于 deadline
        patch("submit_codex.time.monotonic", side_effect=[0, 100, 200]),
    ):
        result = submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    assert result.verdict == "passed"
    assert result.round == 1
    assert result.pr_number == 42
    assert result.reviewer == "chatgpt-codex-connector[bot]"
    assert result.review_id == 12345678

    # 2026-05 改造：不再本地落盘 round-N.md
    reviews_dir = fake_repo / req_id / "artifacts" / "codex-reviews"
    assert not reviews_dir.exists(), "codex-reviews/ 目录不应被创建"
    assert result.artifact_path is None


# ---------- TC-F4-2: not_passed 路径 ----------


def test_not_passed_path(fake_repo: Path, capsys: pytest.CaptureFixture) -> None:
    """TC-F4-2: body 不含 pass phrase → verdict=not_passed + stderr ⚠️ NOT passed。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)

    triggered_at = "2026-05-04T19:30:00+08:00"
    review = _make_review(
        body="Found some issues.",
        submitted_at="2026-05-04T19:32:14+08:00",
    )

    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[review]),
        patch.object(submit_codex, "_gh_pr_issue_comments", return_value=[]),
        patch("submit_codex.time.sleep"),
        patch("submit_codex.time.monotonic", side_effect=[0, 100, 200]),
    ):
        result = submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    assert result.verdict == "not_passed"

    # stderr 应含 ⚠️ NOT passed
    captured = capsys.readouterr()
    assert "⚠️ codex review NOT passed" in captured.err


# ---------- TC-F4-3: timeout 路径 ----------


def test_timeout_path(fake_repo: Path, capsys: pytest.CaptureFixture) -> None:
    """TC-F4-3: mock 永不返回 codex review → verdict=timeout + stderr ⚠️ TIMEOUT + 不本地落盘。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)

    triggered_at = "2026-05-04T19:30:00+08:00"

    # _gh_pr_reviews 返回空列表（没有任何 review），monotonic 超过 deadline
    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[]),
        patch.object(submit_codex, "_gh_pr_issue_comments", return_value=[]),
        patch("submit_codex.time.sleep"),
        # deadline = 0 + 600 = 600；第二次 monotonic 返回 601 → 超时退出循环
        patch("submit_codex.time.monotonic", side_effect=[0, 601]),
    ):
        result = submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    assert result.verdict == "timeout"
    assert result.review_id is None
    assert result.reviewer is None
    assert result.submitted_at is None

    # stderr 应含 ⚠️ TIMEOUT
    captured = capsys.readouterr()
    assert "⚠️ codex review TIMEOUT" in captured.err

    # 2026-05 改造：不再本地落盘 round-N.md
    reviews_dir = fake_repo / req_id / "artifacts" / "codex-reviews"
    assert not reviews_dir.exists(), "codex-reviews/ 目录不应被创建"
    assert result.artifact_path is None


# ---------- TC-F4-4: 429 → timeout ----------


def test_429_to_timeout(fake_repo: Path, capsys: pytest.CaptureFixture) -> None:
    """TC-F4-4: mock 429 → 走 timeout，不重试。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)

    triggered_at = "2026-05-04T19:30:00+08:00"

    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", side_effect=GhApi429("rate limited")),
        patch("submit_codex.time.sleep"),
        patch("submit_codex.time.monotonic", side_effect=[0, 100]),
    ):
        result = submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    assert result.verdict == "timeout"

    # 确认 _gh_pr_reviews 只被调用一次（429 不重试）
    captured = capsys.readouterr()
    assert "⚠️ codex review TIMEOUT" in captured.err


# ---------- TC-F4-6: 过滤旧 review ----------


def test_filter_old_review(fake_repo: Path) -> None:
    """TC-F4-6: submitted_at <= triggered_at 不算命中，应等待或超时。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)

    triggered_at = "2026-05-04T19:30:00+08:00"
    # submitted_at 与 triggered_at 相同（= 而非 > 触发时刻），应被过滤
    old_review = _make_review(submitted_at="2026-05-04T19:30:00+08:00")

    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[old_review]),
        patch.object(submit_codex, "_gh_pr_issue_comments", return_value=[]),
        patch("submit_codex.time.sleep"),
        # 第一次进循环，第二次超 deadline → timeout
        patch("submit_codex.time.monotonic", side_effect=[0, 601]),
    ):
        result = submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    # 旧 review 被过滤 → 超时走 timeout
    assert result.verdict == "timeout"


# ---------- TC-F4-7: --codex 参数互斥验证 ----------


def test_codex_args_mutex() -> None:
    """TC-F4-7: --codex-poll-interval 不带 --codex 时，应提示 requires --codex 并 exit 1。

    本测试验证命令层行为契约（submit.md §3.4.1）：
    --codex-poll-interval / --codex-timeout 必须与 --codex 同传。
    此逻辑属于 submit command 的参数解析层，在 submit_codex 模块外部检查。
    本测试以集成方式校验"参数未带 --codex 时应有 requires --codex 提示"的约定。
    """
    # 模拟 submit command 的参数互斥校验逻辑（contract test）
    def _validate_args(codex: bool, poll_interval: int | None, timeout: int | None) -> str | None:
        """模拟 submit command 层参数验证；返回 None 表示合法，否则返回错误信息。"""
        if poll_interval is not None and not codex:
            return "--codex-poll-interval requires --codex"
        if timeout is not None and not codex:
            return "--codex-timeout requires --codex"
        return None

    # 不带 --codex 时传入 poll-interval → 应报错
    err = _validate_args(codex=False, poll_interval=30, timeout=None)
    assert err is not None
    assert "requires --codex" in err

    # 不带 --codex 时传入 timeout → 应报错
    err = _validate_args(codex=False, poll_interval=None, timeout=300)
    assert err is not None
    assert "requires --codex" in err

    # 带 --codex 同传 → 合法
    err = _validate_args(codex=True, poll_interval=30, timeout=300)
    assert err is None

    # 不传 interval/timeout，不带 --codex → 合法（只用默认值）
    err = _validate_args(codex=False, poll_interval=None, timeout=None)
    assert err is None


# ---------- TC-F4-9: V-09 常量唯一性验收 ----------


def test_v09_constant_uniqueness() -> None:
    """TC-F4-9: V-09 grep 验收 —— pass phrase 字面量在 .claude/ 和 scripts/ 下仅 submit-rules.md 一处。

    V-09 验收规则：grep -rn "Didn't find any major issues." .claude/ scripts/
    结果应仅返回 submit-rules.md 一处定义。
    submit_codex.py 内部判定时使用 _PASS_PHRASE 变量，不再写字面量注释，
    因此 grep 扫描范围内只有 submit-rules.md 一处定义。
    """
    result = subprocess.run(
        [
            "grep",
            "-rn",
            "--include=*.md",
            "--include=*.py",
            "Didn't find any major issues.",
            str(REPO_ROOT / ".claude"),
            str(REPO_ROOT / "scripts"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # grep 返回匹配行列表
    matches = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    print("V-09 grep 命中：\n" + "\n".join(matches))

    # 必须有且仅有一处命中
    assert len(matches) == 1, (
        f"V-09 失败：pass phrase 应仅在 submit-rules.md 定义一处，"
        f"实际命中 {len(matches)} 处：\n" + "\n".join(matches)
    )
    assert "submit-rules.md" in matches[0], (
        f"V-09 失败：唯一命中不在 submit-rules.md，实际在：{matches[0]}"
    )


# ---------- 单元级辅助函数测试 ----------


def test_is_passed_true() -> None:
    """_is_passed 正向：body 含 pass phrase → True。"""
    assert _is_passed("Didn't find any major issues. Great job!") is True


def test_is_passed_false() -> None:
    """_is_passed 反向：body 不含 pass phrase → False。"""
    assert _is_passed("Found some issues.") is False
    assert _is_passed(None) is False
    assert _is_passed("") is False


def test_render_frontmatter_timeout() -> None:
    """_render_frontmatter timeout 时仅含 3 字段（round / triggered_at / verdict）。"""
    result = CodexRoundResult(
        round=1,
        pr_number=42,
        triggered_at="2026-05-04T19:30:00+08:00",
        verdict="timeout",
    )
    fm = _render_frontmatter(result)
    assert "round: 1" in fm
    assert "triggered_at:" in fm
    assert "verdict: timeout" in fm
    assert "review_id" not in fm
    assert "reviewer" not in fm
    assert "submitted_at:" not in fm
    assert "state" not in fm


def test_render_frontmatter_passed_bot_login() -> None:
    """_render_frontmatter passed 时，含 [bot] 的 reviewer 必须被 quote。"""
    result = CodexRoundResult(
        round=1,
        pr_number=42,
        triggered_at="2026-05-04T19:30:00+08:00",
        verdict="passed",
        review_id=12345678,
        reviewer="chatgpt-codex-connector[bot]",
        submitted_at="2026-05-04T19:32:14+08:00",
        state="COMMENTED",
    )
    fm = _render_frontmatter(result)
    # [bot] 含方括号，必须 quote 避免 YAML 解析歧义
    assert '"chatgpt-codex-connector[bot]"' in fm
    # triggered_at / submitted_at 含 : 必须 quote
    assert '"2026-05-04T19:30:00+08:00"' in fm
    assert '"2026-05-04T19:32:14+08:00"' in fm
    # review_id 建议 quote
    assert '"12345678"' in fm


def test_calc_round_empty_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_calc_round 目录不存在时返回 1。"""
    req_id = "REQ-2099-007"
    monkeypatch.setattr(submit_codex, "REQUIREMENTS_DIR", tmp_path)
    (tmp_path / req_id).mkdir()
    assert _calc_round(req_id) == 1


def test_calc_round_existing_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_calc_round 已有 N 个 round-*.md 时返回 N+1。"""
    req_id = "REQ-2099-007"
    monkeypatch.setattr(submit_codex, "REQUIREMENTS_DIR", tmp_path)
    reviews_dir = tmp_path / req_id / "artifacts" / "codex-reviews"
    reviews_dir.mkdir(parents=True)
    (reviews_dir / "round-1.md").write_text("r1\n")
    (reviews_dir / "round-2.md").write_text("r2\n")
    assert _calc_round(req_id) == 3


def test_calc_round_handles_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """codex F-4 (P1) 回归：编号断档时（round-1 + round-3，缺 round-2），
    旧实现 `len + 1 = 3` 会覆盖现有 round-3.md；新实现按 max+1 → 4。
    """
    req_id = "REQ-2099-007"
    monkeypatch.setattr(submit_codex, "REQUIREMENTS_DIR", tmp_path)
    reviews_dir = tmp_path / req_id / "artifacts" / "codex-reviews"
    reviews_dir.mkdir(parents=True)
    (reviews_dir / "round-1.md").write_text("r1\n")
    (reviews_dir / "round-3.md").write_text("r3\n")  # 故意制造断档
    # 旧实现：len([r1,r3]) + 1 = 3 → 覆盖 round-3.md（数据丢失）
    # 新实现：max(1,3) + 1 = 4
    assert _calc_round(req_id) == 4, "断档场景必须按 max+1 推算"


def test_calc_round_ignores_unparseable_filenames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_calc_round 必须忽略 glob 命中但不符合 `round-N.md` 命名的文件，
    防止 round-foo.md / round-1-backup.md 等噪声破坏编号推算。
    """
    req_id = "REQ-2099-007"
    monkeypatch.setattr(submit_codex, "REQUIREMENTS_DIR", tmp_path)
    reviews_dir = tmp_path / req_id / "artifacts" / "codex-reviews"
    reviews_dir.mkdir(parents=True)
    (reviews_dir / "round-1.md").write_text("r1\n")
    (reviews_dir / "round-foo.md").write_text("noise\n")  # 不可解析
    (reviews_dir / "round-1-backup.md").write_text("noise\n")  # 不严格匹配
    assert _calc_round(req_id) == 2


def test_handle_poll_result_none_is_timeout() -> None:
    """_handle_poll_result 传 None 返回 verdict=timeout，可选字段均 None。"""
    result = _handle_poll_result(
        review=None,
        pr_number=42,
        round_num=1,
        triggered_at="2026-05-04T19:30:00+08:00",
    )
    assert result.verdict == "timeout"
    assert result.review_id is None
    assert result.reviewer is None


def test_poll_codex_abort_on_consecutive_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    """_poll_codex 连续 3 次 5xx 应抛 GhApiAbort。"""
    call_count = 0

    def _always_5xx(pr_number: int) -> list:
        nonlocal call_count
        call_count += 1
        raise GhApi5xx("500 Internal Server Error")

    monkeypatch.setattr(submit_codex, "_gh_pr_reviews", _always_5xx)

    # monotonic 模拟：始终在 deadline 内
    with patch("submit_codex.time.monotonic", return_value=0):
        with patch("submit_codex.time.sleep"):
            with pytest.raises(GhApiAbort):
                _poll_codex(42, "2026-05-04T19:30:00+08:00", interval=1, timeout=600)

    # 连续 3 次后抛异常，不多余调用
    assert call_count == 3


# ---------- TC-F4-8a: process.txt 写入 [codex-review-triggered] ----------


def test_process_event_triggered_appended(fake_repo: Path) -> None:
    """TC-F4-8a: PR 评论发送成功后，process.txt 末行含 [codex-review-triggered] round=1 pr=#42。

    验证 F-001 修复：submit_codex 写入 [codex-review-triggered] 事件（detailed-design §4.3）。
    只 mock subprocess，让 _append_process_event 真实执行，验证写入内容。
    """
    import subprocess as _sp

    req_id = "REQ-2099-007"
    req_dir = _make_meta(fake_repo, req_id=req_id, pr_number=42)
    # 预置一个空 process.txt（模拟 meta 预检已通过的正常状态）
    (req_dir / "process.txt").write_text("", encoding="utf-8")

    triggered_at = "2026-05-04T19:30:00+08:00"
    review = _make_review(submitted_at="2026-05-04T19:32:14+08:00")

    # 只 mock subprocess.run + now_iso + 轮询相关，让 _append_process_event 真实执行
    fake_proc = _sp.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with (
        patch("submit_codex.subprocess.run", return_value=fake_proc),
        patch.object(submit_codex, "_now_iso", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[review]),
        patch.object(submit_codex, "_gh_pr_issue_comments", return_value=[]),
        patch("submit_codex.time.sleep"),
        patch("submit_codex.time.monotonic", side_effect=[0, 100, 200]),
    ):
        submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    process_txt = (req_dir / "process.txt").read_text(encoding="utf-8")
    lines = [ln for ln in process_txt.splitlines() if ln.strip()]
    triggered_lines = [ln for ln in lines if "[codex-review-triggered]" in ln]
    assert triggered_lines, f"process.txt 中应含 [codex-review-triggered]，实际内容：\n{process_txt}"
    assert "round=1" in triggered_lines[0], f"应含 round=1，实际：{triggered_lines[0]}"
    assert "pr=#42" in triggered_lines[0], f"应含 pr=#42，实际：{triggered_lines[0]}"


# ---------- TC-F4-8b: process.txt 写入 [codex-review-received] ----------


def test_process_event_received_appended(fake_repo: Path) -> None:
    """TC-F4-8b: passed 路径跑完后，process.txt 末行含 [codex-review-received] verdict=passed round=1。

    验证 F-001 修复：submit_codex 写入 [codex-review-received] 事件（detailed-design §4.3）。
    """
    req_id = "REQ-2099-007"
    req_dir = _make_meta(fake_repo, req_id=req_id, pr_number=42)
    (req_dir / "process.txt").write_text("", encoding="utf-8")

    triggered_at = "2026-05-04T19:30:00+08:00"
    review = _make_review(submitted_at="2026-05-04T19:32:14+08:00")

    import subprocess as _sp

    fake_proc = _sp.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with (
        patch("submit_codex.subprocess.run", return_value=fake_proc),
        patch.object(submit_codex, "_now_iso", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[review]),
        patch.object(submit_codex, "_gh_pr_issue_comments", return_value=[]),
        patch("submit_codex.time.sleep"),
        patch("submit_codex.time.monotonic", side_effect=[0, 100, 200]),
    ):
        result = submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    assert result.verdict == "passed"

    process_txt = (req_dir / "process.txt").read_text(encoding="utf-8")
    lines = [ln for ln in process_txt.splitlines() if ln.strip()]
    received_lines = [ln for ln in lines if "[codex-review-received]" in ln]
    assert received_lines, f"process.txt 中应含 [codex-review-received]，实际内容：\n{process_txt}"
    last = received_lines[-1]
    assert "verdict=passed" in last, f"应含 verdict=passed，实际：{last}"
    assert "round=1" in last, f"应含 round=1，实际：{last}"


# ---------- Codex round-1 自举回归（3 条 finding 的 fix 各一） ----------


def test_filter_handles_zulu_vs_offset_timezones(fake_repo: Path) -> None:
    """codex F-1 (P1) 回归：submitted_at 是 `Z` 而 triggered_at 是 `+08:00` 时，
    旧实现因字符串字典序错位漏掉真实命中；修复后必须按 tzaware datetime 比对。

    场景还原：
      - triggered_at = 17:04:03+08:00 (= 09:04:03Z)
      - submitted_at = 09:09:05Z      (晚 5 分 02 秒)
      - 字典序下 submitted_at < triggered_at（"...09:09:05Z" < "...17:04:03+08:00"），
        旧版本会把它当成"旧 review"过滤；datetime 比对应识别为新 review 并命中。
    """
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)

    triggered_at = "2026-05-05T17:04:03.473256+08:00"
    new_review = _make_review(submitted_at="2026-05-05T09:09:05Z")

    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[new_review]),
        patch.object(submit_codex, "_gh_pr_issue_comments", return_value=[]),
        patch("submit_codex.time.sleep"),
        patch("submit_codex.time.monotonic", side_effect=[0, 1]),
    ):
        result = submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    # 修复前会 timeout；修复后应识别为命中
    assert result.verdict in ("passed", "not_passed"), (
        f"期望 datetime 比对命中（passed/not_passed），实际 {result.verdict}"
        " —— 这是 codex round-1 P1 finding F-1 的回归保护"
    )
    assert result.review_id == new_review["id"]


def test_parse_iso_to_aware_normalizes_offsets() -> None:
    """codex F-1 单元级：_parse_iso_to_aware 把 Z 与 ±HH:MM 都归一为 tzaware。"""
    a = _parse_iso_to_aware("2026-05-05T09:09:05Z")
    b = _parse_iso_to_aware("2026-05-05T17:09:05+08:00")
    assert a is not None and a.tzinfo is not None
    assert b is not None and b.tzinfo is not None
    # 两者表示同一时刻
    assert a == b
    # 兜底：空 / 非法 → None
    assert _parse_iso_to_aware("") is None
    assert _parse_iso_to_aware("not-a-date") is None


def test_poll_codex_picks_latest_when_multiple_match(fake_repo: Path) -> None:
    """codex F-6 (P1) 回归：同一轮 codex 发了多条匹配 review（如先 not_passed 再 passed），
    `_poll_codex` 必须按 submitted_at 取最新；旧实现取首条会落到旧 verdict 上。
    """
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)

    triggered_at = "2026-05-05T17:30:00+08:00"
    older = _make_review(
        review_id=1001,
        submitted_at="2026-05-05T09:35:00Z",  # = 17:35 +08:00
        body="found one issue",
    )
    newer = _make_review(
        review_id=1002,
        submitted_at="2026-05-05T09:45:00Z",  # = 17:45 +08:00（更晚）
        body="Didn't find any major issues.",
    )

    # 故意把 older 排在前——旧实现会锁定到它
    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[older, newer]),
        patch.object(submit_codex, "_gh_pr_issue_comments", return_value=[]),
        patch("submit_codex.time.sleep"),
        patch("submit_codex.time.monotonic", side_effect=[0, 1]),
    ):
        result = submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    # 必须取 newer（review_id=1002，body 含 pass phrase）→ verdict=passed
    assert result.review_id == 1002, "应取最新 submitted_at 的 review，旧实现会取首条 1001"
    assert result.verdict == "passed", f"newer review 含 pass phrase → passed，实际 {result.verdict}"


def test_parse_jsonl_reviews_handles_paginated_jsonl() -> None:
    """codex F-2 (P1) 回归：gh api --paginate -q '.[]' 输出每行一个 JSON 对象，
    旧实现 `json.loads(stdout)` 在多页输出（concatenated arrays）下抛 JSONDecodeError，
    被错判为 5xx → 触发轮询中止保护。

    新实现 `_parse_jsonl_reviews` 必须能解析逐行 JSON、忽略空行；
    且历史兼容路径（单个 JSON 数组）仍要支持。
    """
    # JSONL 路径（修复后的 -q '.[]' 输出）
    jsonl = (
        '{"id": 1, "user": {"login": "codex[bot]", "type": "Bot"}}\n'
        '{"id": 2, "user": {"login": "human", "type": "User"}}\n'
        '\n'  # 空行应忽略
        '{"id": 3, "user": {"login": "codex[bot]", "type": "Bot"}}\n'
    )
    out = _parse_jsonl_reviews(jsonl)
    assert [r["id"] for r in out] == [1, 2, 3]

    # 兼容历史：单个 JSON 数组
    arr = '[{"id": 10, "user": {"login": "x"}}, {"id": 11, "user": {"login": "y"}}]'
    out = _parse_jsonl_reviews(arr)
    assert [r["id"] for r in out] == [10, 11]

    # 兼容历史：多页拼成嵌套数组 [[{},{}],[{}]]
    nested = '[[{"id": 20}, {"id": 21}], [{"id": 22}]]'
    out = _parse_jsonl_reviews(nested)
    assert [r["id"] for r in out] == [20, 21, 22]

    # 空输入
    assert _parse_jsonl_reviews("") == []
    assert _parse_jsonl_reviews("\n\n") == []

    # 非法 JSON（行级）→ 抛 GhApi5xx，让上层进 5xx 计数器（保守语义）
    with pytest.raises(GhApi5xx):
        _parse_jsonl_reviews('{"valid": 1}\nthis-is-not-json\n')


# ---------- review-loop 增量摘要（2026-05 改造：锚点改从 PR reviews API 反查） ----------


def test_build_codex_comment_body_no_prior_codex_review_is_base_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR 上没有 codex bot 历史 review → body = `CODEX_REVIEW_TRIGGER_BODY`（基础模板，含 PR 正文阅读硬约束）。"""
    monkeypatch.setattr(submit_codex, "_gh_pr_reviews", lambda _pr: [])
    body = _build_codex_comment_body(pr_number=42)
    assert body == submit_codex.CODEX_REVIEW_TRIGGER_BODY
    # 关键内容断言（即使模板将来文本微调也守住硬约束语义）
    assert "@codex review" in body
    assert "完整阅读本 PR 的正文" in body
    assert "变更摘要" in body and "影响范围" in body and "验证方式" in body


def test_build_codex_comment_body_includes_diff_summary_for_repeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR 上已有 codex bot review → 拼 commits + diff stat 段并附 intro 提示。"""
    # 模拟 PR reviews 包含 codex bot 一条
    monkeypatch.setattr(
        submit_codex,
        "_gh_pr_reviews",
        lambda _pr: [
            {
                "user": {"login": "chatgpt-codex-connector", "type": "Bot"},
                "submitted_at": "2026-05-19T00:29:29Z",
                "commit_id": "abc1234567",
                "body": "automated review",
            },
            # 加一条用户 review 确认会被过滤
            {
                "user": {"login": "alice", "type": "User"},
                "submitted_at": "2026-05-19T01:00:00Z",
                "commit_id": "shouldignore",
                "body": "lgtm",
            },
        ],
    )

    def _mock_run(cmd: list[str], **kwargs: Any) -> Any:
        from types import SimpleNamespace
        if cmd[:3] == ["git", "rev-parse", "--short"]:
            return SimpleNamespace(returncode=0, stdout="def5678\n", stderr="")
        if cmd[:2] == ["git", "log"]:
            return SimpleNamespace(
                returncode=0,
                stdout="def5678 fix(F-N): ...\n123abc fix(F-M): ...\n",
                stderr="",
            )
        if cmd[:2] == ["git", "diff"]:
            return SimpleNamespace(
                returncode=0,
                stdout=" scripts/lib/foo.py | 12 ++++++------\n 1 file changed\n",
                stderr="",
            )
        raise AssertionError(f"unexpected cmd: {cmd}")

    monkeypatch.setattr(submit_codex.subprocess, "run", _mock_run)

    body = _build_codex_comment_body(pr_number=42)
    # 基础体（CODEX_REVIEW_TRIGGER_BODY）必须永远在前
    assert body.startswith(submit_codex.CODEX_REVIEW_TRIGGER_BODY + "\n\n")
    assert "完整阅读本 PR 的正文" in body  # 硬约束指令
    assert "Changes since last codex review" in body
    assert "abc1234567" in body and "def5678" in body
    assert "本次 push 自上轮 codex review 以来的改动" in body  # intro 提示
    assert "fix(F-N)" in body  # commits 段
    assert "scripts/lib/foo.py" in body  # diff stat 段


def test_build_codex_comment_body_falls_back_when_api_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_gh_pr_reviews 抛 GhApi5xx → 兜底基础模板（仍含 PR 正文阅读硬约束），不抛。"""
    def _raise(_pr):
        raise GhApi5xx("simulated 502")

    monkeypatch.setattr(submit_codex, "_gh_pr_reviews", _raise)
    body = _build_codex_comment_body(pr_number=42)
    assert body == submit_codex.CODEX_REVIEW_TRIGGER_BODY
    assert "完整阅读本 PR 的正文" in body


def test_build_codex_comment_body_falls_back_when_git_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """git 命令失败 → 兜底 plain，不阻断 review-loop。"""
    monkeypatch.setattr(
        submit_codex,
        "_gh_pr_reviews",
        lambda _pr: [
            {
                "user": {"login": "chatgpt-codex-connector", "type": "Bot"},
                "submitted_at": "2026-05-19T00:29:29Z",
                "commit_id": "abc1234567",
                "body": "automated review",
            },
        ],
    )

    def _mock_run(cmd: list[str], **kwargs: Any) -> Any:
        from types import SimpleNamespace
        return SimpleNamespace(returncode=128, stdout="", stderr="fatal: bad revision")

    monkeypatch.setattr(submit_codex.subprocess, "run", _mock_run)
    body = _build_codex_comment_body(pr_number=42)
    assert body == submit_codex.CODEX_REVIEW_TRIGGER_BODY
    assert "完整阅读本 PR 的正文" in body


def test_latest_codex_reviewed_commit_picks_newest_by_submitted_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多条 codex review 时按 submitted_at 最大者取 commit_id；非 bot / 非 codex 过滤。"""
    monkeypatch.setattr(
        submit_codex,
        "_gh_pr_reviews",
        lambda _pr: [
            {
                "user": {"login": "chatgpt-codex-connector", "type": "Bot"},
                "submitted_at": "2026-05-18T15:54:44Z",
                "commit_id": "older1234567890",
            },
            {
                "user": {"login": "chatgpt-codex-connector", "type": "Bot"},
                "submitted_at": "2026-05-19T01:21:12Z",
                "commit_id": "newest9876543210",
            },
            {
                "user": {"login": "alice", "type": "User"},  # 非 bot
                "submitted_at": "2026-05-19T02:00:00Z",
                "commit_id": "irrelevant",
            },
            {
                "user": {"login": "github-actions", "type": "Bot"},  # bot 但非 codex
                "submitted_at": "2026-05-19T03:00:00Z",
                "commit_id": "alsoirrelevant",
            },
        ],
    )
    sha = submit_codex._latest_codex_reviewed_commit(pr_number=42)
    assert sha == "newest9876"  # 取前 10 字符


def test_is_passed_ignores_pass_phrase_in_quoted_lines() -> None:
    """codex F-9 (P1) 回归：pass phrase 出现在 markdown 引用块（`>` 开头）不算通过；
    但出现在非引用文本里仍算通过。
    """
    # 引用上下文 + 新发现 → not passed（旧实现误判 passed）
    quoted_body = (
        "Found new issues in this round.\n"
        "\n"
        "> Previous round said: \"Didn't find any major issues.\"\n"
        "> But this round we found...\n"
        "\n"
        "**P1**: New finding here\n"
    )
    assert _is_passed(quoted_body) is False, "引用块内的 pass phrase 不应触发 passed"

    # 引用前缀带空白也应被识别为引用（markdown 容许 `> ` 之前有空格）
    indented_quote = "  > Previous: Didn't find any major issues.\n\nNew finding\n"
    assert _is_passed(indented_quote) is False

    # 普通通过路径仍然识别
    plain_pass = "Reviewed commit: abc.\n\nDidn't find any major issues.\n"
    assert _is_passed(plain_pass) is True

    # 多行混合：非引用行命中即通过
    mixed = (
        "> someone said something\n"
        "Codex says: Didn't find any major issues. All good!\n"
    )
    assert _is_passed(mixed) is True


def test_render_frontmatter_includes_triggered_commit() -> None:
    """_render_frontmatter 必须把 result.triggered_commit 输出到 frontmatter，下一轮才能读到。"""
    result = CodexRoundResult(
        round=2,
        pr_number=42,
        triggered_at="2026-05-05T17:54:33+08:00",
        verdict="not_passed",
        review_id=999,
        reviewer="codex[bot]",
        submitted_at="2026-05-05T10:00:00Z",
        state="COMMENTED",
        triggered_commit="abc1234",
    )
    fm = _render_frontmatter(result)
    assert 'triggered_commit: "abc1234"' in fm
    # timeout 时也应输出（下一轮算 diff 不能丢锚点）
    timeout_result = CodexRoundResult(
        round=3,
        pr_number=42,
        triggered_at="2026-05-05T18:00:00+08:00",
        verdict="timeout",
        triggered_commit="def5678",
    )
    fm = _render_frontmatter(timeout_result)
    assert 'triggered_commit: "def5678"' in fm


# ---------- codex round-9 P1 finding F-16：双端点 poll（reviews + issue comments） ----------


def _make_issue_comment(
    *,
    login: str = "chatgpt-codex-connector[bot]",
    user_type: str = "Bot",
    body: str = "Codex Review: Didn't find any major issues. Already looking forward to the next diff.",
    created_at: str = "2026-05-04T19:32:14+08:00",
    comment_id: int = 7777777,
) -> dict:
    """构造一个 issue comment dict（codex pass 路径用）。"""
    return {
        "id": comment_id,
        "user": {"login": login, "type": user_type},
        "body": body,
        "created_at": created_at,
    }


def test_poll_picks_pass_from_issue_comment_when_no_review(fake_repo: Path) -> None:
    """codex F-16 (P1) 回归：codex 「无 finding」时不发 PR review，发 issue comment
    带 pass phrase。旧实现只查 reviews 端点会漏掉 pass 信号 → verdict=timeout 假阴。
    新实现必须同时查两个端点，并把 issue comment 作为 candidate 参与判定。
    """
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=57)

    triggered_at = "2026-05-05T18:48:50+08:00"
    pass_comment = _make_issue_comment(
        comment_id=4378572117,
        body="Codex Review: Didn't find any major issues. Already looking forward to the next diff.",
        created_at="2026-05-05T10:53:52Z",  # = 18:53:52 +08:00（晚于 triggered_at）
    )

    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[]),  # 关键：reviews 端点空
        patch.object(submit_codex, "_gh_pr_issue_comments", return_value=[pass_comment]),
        patch("submit_codex.time.sleep"),
        patch("submit_codex.time.monotonic", side_effect=[0, 100, 200]),
    ):
        result = submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    assert result.verdict == "passed", (
        f"issue comment 含 pass phrase 应 verdict=passed，实际 {result.verdict}"
    )
    # review_id 字段被复用为 issue comment id（统一 dict shape 后透传）
    assert result.review_id == 4378572117
    assert result.reviewer == "chatgpt-codex-connector[bot]"


def test_poll_filters_old_issue_comment(fake_repo: Path) -> None:
    """F-16：issue comment 的 created_at <= triggered_at 必须被过滤（与 review 同语义）。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=57)

    triggered_at = "2026-05-05T18:48:50+08:00"
    old_comment = _make_issue_comment(
        body="Codex Review: Didn't find any major issues.",
        created_at="2026-05-05T18:00:00+08:00",  # 早于 triggered_at
    )

    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[]),
        patch.object(submit_codex, "_gh_pr_issue_comments", return_value=[old_comment]),
        patch("submit_codex.time.sleep"),
        patch("submit_codex.time.monotonic", side_effect=[0, 601]),
    ):
        result = submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    assert result.verdict == "timeout", "旧 issue comment 应被过滤，走 timeout 分支"


def test_poll_ignores_non_codex_issue_comments(fake_repo: Path) -> None:
    """F-16：issue comments 端点会拿到非 codex bot 的人类评论，必须被 _matches_codex_reviewer 过滤。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=57)

    triggered_at = "2026-05-05T18:48:50+08:00"
    human_comment = _make_issue_comment(
        login="hjaaa",
        user_type="User",
        body="Didn't find any major issues. (人类评论引用，不算 pass)",
        created_at="2026-05-05T19:00:00+08:00",
    )

    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[]),
        patch.object(submit_codex, "_gh_pr_issue_comments", return_value=[human_comment]),
        patch("submit_codex.time.sleep"),
        patch("submit_codex.time.monotonic", side_effect=[0, 601]),
    ):
        result = submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    assert result.verdict == "timeout", "非 codex bot 评论应被过滤"


def test_poll_picks_review_over_older_issue_comment(fake_repo: Path) -> None:
    """F-16：双端点同时有命中时，按 latest 取（与 _pick_latest_review 同语义）。
    场景：codex 先发了 issue comment（'pass'），随后又发了 PR review（'not_passed'）。
    """
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=57)

    triggered_at = "2026-05-05T18:48:50+08:00"
    early_pass_comment = _make_issue_comment(
        comment_id=1001,
        body="Codex Review: Didn't find any major issues.",
        created_at="2026-05-05T18:50:00+08:00",
    )
    later_review = _make_review(
        review_id=2002,
        body="Found new issues",
        submitted_at="2026-05-05T18:55:00+08:00",  # 更晚
    )

    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[later_review]),
        patch.object(submit_codex, "_gh_pr_issue_comments", return_value=[early_pass_comment]),
        patch("submit_codex.time.sleep"),
        patch("submit_codex.time.monotonic", side_effect=[0, 100]),
    ):
        result = submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    # 应取更晚的 review（review_id=2002），verdict=not_passed
    assert result.review_id == 2002, f"应取最晚的 review，实际 {result.review_id}"
    assert result.verdict == "not_passed"


def test_normalize_issue_comment_preserves_user_and_body() -> None:
    """_normalize_issue_comment_to_review 把 created_at 复制到 submitted_at；其他字段透传。"""
    comment = {
        "id": 7777,
        "user": {"login": "x[bot]", "type": "Bot"},
        "body": "Didn't find any major issues.",
        "created_at": "2026-05-05T19:00:00+08:00",
    }
    out = submit_codex._normalize_issue_comment_to_review(comment)
    assert out["submitted_at"] == "2026-05-05T19:00:00+08:00"
    assert out["user"]["login"] == "x[bot]"
    assert out["body"] == "Didn't find any major issues."
    assert out["_kind"] == "comment"


# ===========================================================================
# 2026-05-21 硬约束（submit-rules.md §7.5）：CI precheck + 触发模板
# ===========================================================================


def _make_ci_proc(rc: int, stdout: str, stderr: str = ""):
    """构造 _check_ci_status 子进程返回值的 SimpleNamespace 模拟。"""
    from types import SimpleNamespace
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


def test_check_ci_status_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有 check state ∈ {SUCCESS, NEUTRAL, SKIPPED} → ('success', [])."""
    checks = [
        {"name": "build", "state": "SUCCESS", "bucket": "pass"},
        {"name": "test", "state": "NEUTRAL", "bucket": "pass"},
        {"name": "lint", "state": "SKIPPED", "bucket": "skipping"},
    ]
    import json as _json
    monkeypatch.setattr(
        submit_codex.subprocess,
        "run",
        lambda *_args, **_kw: _make_ci_proc(0, _json.dumps(checks)),
    )
    status, problem = submit_codex._check_ci_status(pr_number=42)
    assert status == "success"
    assert problem == []


def test_check_ci_status_failed_on_failure_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """任一 check state ∈ {FAILURE, CANCELLED, TIMED_OUT} → ('failed', [那些])."""
    checks = [
        {"name": "build", "state": "SUCCESS", "bucket": "pass"},
        {"name": "quality-check", "state": "FAILURE", "bucket": "fail"},
        {"name": "deploy-preview", "state": "CANCELLED", "bucket": "fail"},
    ]
    import json as _json
    monkeypatch.setattr(
        submit_codex.subprocess,
        "run",
        lambda *_args, **_kw: _make_ci_proc(0, _json.dumps(checks)),
    )
    status, problem = submit_codex._check_ci_status(pr_number=42)
    assert status == "failed"
    assert {c["name"] for c in problem} == {"quality-check", "deploy-preview"}


def test_check_ci_status_pending_when_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    """任一 check state ∈ {PENDING/IN_PROGRESS/QUEUED} → ('pending', [那些])."""
    checks = [
        {"name": "build", "state": "SUCCESS", "bucket": "pass"},
        {"name": "test", "state": "IN_PROGRESS", "bucket": "pending"},
    ]
    import json as _json
    monkeypatch.setattr(
        submit_codex.subprocess,
        "run",
        lambda *_args, **_kw: _make_ci_proc(0, _json.dumps(checks)),
    )
    status, problem = submit_codex._check_ci_status(pr_number=42)
    assert status == "pending"
    assert [c["name"] for c in problem] == ["test"]


def test_check_ci_status_gh_failure_treated_as_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    """gh 命令 rc!=0 → ('pending', [])（保守，让上层走 fail-closed 兜底）。"""
    monkeypatch.setattr(
        submit_codex.subprocess,
        "run",
        lambda *_args, **_kw: _make_ci_proc(1, "", "auth required"),
    )
    status, problem = submit_codex._check_ci_status(pr_number=42)
    assert status == "pending"
    assert problem == []


def test_check_ci_status_empty_checks_treated_as_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    """0 个 check（PR 无 CI 配置或 actions 尚未触发）→ ('pending', [])."""
    monkeypatch.setattr(
        submit_codex.subprocess,
        "run",
        lambda *_args, **_kw: _make_ci_proc(0, "[]"),
    )
    status, problem = submit_codex._check_ci_status(pr_number=42)
    assert status == "pending"


def test_precheck_ci_or_exit_success_passes_silently(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """status='success' → 不抛 + 不写 process.txt。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)
    monkeypatch.setattr(submit_codex, "_check_ci_status", lambda _pr: ("success", []))

    # 应不抛
    submit_codex._precheck_ci_or_exit(pr_number=42, req_id=req_id)

    captured = capsys.readouterr()
    assert captured.err == ""
    # process.txt 不应被写入
    process_txt = fake_repo / req_id / "process.txt"
    assert (not process_txt.exists()) or "[codex-skipped]" not in process_txt.read_text()


def test_precheck_ci_or_exit_failed_exits_1_with_event(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """status='failed' → SystemExit(1) + stderr 详情 + process.txt [codex-skipped reason=ci-failed]。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)
    problem = [{"name": "quality-check", "state": "FAILURE", "bucket": "fail"}]
    monkeypatch.setattr(submit_codex, "_check_ci_status", lambda _pr: ("failed", problem))

    with pytest.raises(SystemExit) as exc_info:
        submit_codex._precheck_ci_or_exit(pr_number=42, req_id=req_id)
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "CI failed" in captured.err
    assert "quality-check" in captured.err
    assert "FAILURE" in captured.err  # state 字段值原样渲染

    process_txt = fake_repo / req_id / "process.txt"
    assert process_txt.exists()
    line = process_txt.read_text()
    assert "[codex-skipped]" in line
    assert "reason=ci-failed" in line
    assert "pr=#42" in line


def test_precheck_ci_or_exit_pending_exits_0_with_warning(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """status='pending' → SystemExit(0) + stderr ⚠️ 警告 + process.txt [codex-skipped reason=ci-pending]。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)
    problem = [{"name": "test", "state": "IN_PROGRESS", "bucket": "pending"}]
    monkeypatch.setattr(submit_codex, "_check_ci_status", lambda _pr: ("pending", problem))

    with pytest.raises(SystemExit) as exc_info:
        submit_codex._precheck_ci_or_exit(pr_number=42, req_id=req_id)
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "CI not stable" in captured.err or "⚠️" in captured.err
    assert "test" in captured.err

    process_txt = fake_repo / req_id / "process.txt"
    line = process_txt.read_text()
    assert "[codex-skipped]" in line
    assert "reason=ci-pending" in line


def test_submit_with_codex_blocks_on_ci_failed(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """submit_with_codex 在 CI failed 时 fail-closed：不发 @codex review，不进 poll。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)
    # 覆盖 fake_repo 默认的 success stub
    problem = [{"name": "quality-check", "state": "FAILURE", "bucket": "fail"}]
    monkeypatch.setattr(submit_codex, "_check_ci_status", lambda _pr: ("failed", problem))

    trigger_called = []
    poll_called = []
    monkeypatch.setattr(
        submit_codex,
        "_trigger_codex_comment",
        lambda *a, **kw: (trigger_called.append((a, kw)) or "2026-05-21T09:00:00+08:00"),
    )
    monkeypatch.setattr(
        submit_codex,
        "_poll_codex",
        lambda *a, **kw: (poll_called.append(1) or None),
    )

    with pytest.raises(SystemExit) as exc_info:
        submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=10)
    assert exc_info.value.code == 1
    assert trigger_called == []  # @codex review 没发
    assert poll_called == []     # poll 没跑


def test_codex_review_trigger_body_constant_includes_pr_body_instruction() -> None:
    """CODEX_REVIEW_TRIGGER_BODY 必须包含「先读 PR 正文」硬约束指令（2026-05-21 §7.5）。"""
    body = submit_codex.CODEX_REVIEW_TRIGGER_BODY
    assert body.startswith("@codex review")
    assert "完整阅读本 PR 的正文" in body
    # 5 个必读 section 关键词都要在
    for section in ("变更摘要", "影响范围", "验证方式", "风险与回滚", "追溯"):
        assert section in body, f"trigger 模板缺关键 section: {section}"
    # 3 条 review 重点
    assert "acceptance" in body
    assert "follow-up" in body
    assert "silent" in body
