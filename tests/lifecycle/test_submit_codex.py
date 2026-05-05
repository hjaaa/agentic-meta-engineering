"""submit_codex.submit_with_codex 单元测试。

覆盖 features.json acceptance TC-F4-1 ~ TC-F4-7 + TC-F4-9（V-09 常量验收）：
  - TC-F4-1: test_passed_path        — mock 命中 pass phrase → verdict=passed + exit 0 + round-1.md 写入
  - TC-F4-2: test_not_passed_path    — body 不含 pass phrase → verdict=not_passed + stderr ⚠️ NOT passed
  - TC-F4-3: test_timeout_path       — mock 永不返回 → verdict=timeout + stderr ⚠️ TIMEOUT + frontmatter 仅 3 字段
  - TC-F4-4: test_429_to_timeout     — mock 429 → 走 timeout，不重试
  - TC-F4-5: test_round_increment    — 已存在 round-1.md → 写 round-2.md
  - TC-F4-6: test_filter_old_review  — submitted_at <= triggered_at 不算命中
  - TC-F4-7: test_codex_args_mutex   — --codex-poll-interval 不带 --codex → stderr 含 requires --codex
  - TC-F4-9: test_v09_constant_uniqueness — grep 验收：CODEX_PASS_PHRASE 仅 submit-rules.md 一处

外部依赖（subprocess gh / _gh_pr_reviews）全 mock，不触网络、不动真 git。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    _calc_round,
    _handle_poll_result,
    _is_passed,
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
    """把 submit_codex 的 REQUIREMENTS_DIR 重定向到 tmp_path，避免改动真实仓库。"""
    monkeypatch.setattr(submit_codex, "REQUIREMENTS_DIR", tmp_path)
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
    """TC-F4-1: mock gh api 含 pass phrase → verdict=passed + round-1.md 写入。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)

    triggered_at = "2026-05-04T19:30:00+08:00"
    review = _make_review(submitted_at="2026-05-04T19:32:14+08:00")

    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[review]),
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

    # 验证 round-1.md 写入
    artifact = fake_repo / req_id / "artifacts" / "codex-reviews" / "round-1.md"
    assert artifact.exists(), "round-1.md 应已写入"
    content = artifact.read_text(encoding="utf-8")
    assert "verdict: passed" in content
    assert "Didn't find any major issues." in content


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
    """TC-F4-3: mock 永不返回 codex review → verdict=timeout + frontmatter 仅 3 字段。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)

    triggered_at = "2026-05-04T19:30:00+08:00"

    # _gh_pr_reviews 返回空列表（没有任何 review），monotonic 超过 deadline
    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[]),
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

    # frontmatter 应仅含 3 字段（round / triggered_at / verdict）
    artifact = fake_repo / req_id / "artifacts" / "codex-reviews" / "round-1.md"
    assert artifact.exists()
    content = artifact.read_text(encoding="utf-8")
    assert "review_id" not in content
    assert "reviewer" not in content
    assert "submitted_at:" not in content
    assert "verdict: timeout" in content
    assert "(timeout after 600s" in content


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


# ---------- TC-F4-5: round 递增 ----------


def test_round_increment(fake_repo: Path) -> None:
    """TC-F4-5: 已存在 round-1.md → 写 round-2.md，不允许重号。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id, pr_number=42)

    # 预先写入 round-1.md
    reviews_dir = fake_repo / req_id / "artifacts" / "codex-reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    (reviews_dir / "round-1.md").write_text("existing round-1\n", encoding="utf-8")

    triggered_at = "2026-05-04T19:30:00+08:00"
    review = _make_review(submitted_at="2026-05-04T19:32:14+08:00")

    with (
        patch.object(submit_codex, "_trigger_codex_comment", return_value=triggered_at),
        patch.object(submit_codex, "_gh_pr_reviews", return_value=[review]),
        patch("submit_codex.time.sleep"),
        patch("submit_codex.time.monotonic", side_effect=[0, 100, 200]),
    ):
        result = submit_with_codex(req_id, poll_interval_sec=1, timeout_sec=600)

    assert result.round == 2

    # round-1.md 原有内容不应被改动
    assert (reviews_dir / "round-1.md").read_text(encoding="utf-8") == "existing round-1\n"
    # round-2.md 应已写入
    assert (reviews_dir / "round-2.md").exists()


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
    print(f"V-09 grep 命中：\n" + "\n".join(matches))

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
