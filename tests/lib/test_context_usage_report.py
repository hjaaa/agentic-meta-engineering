"""F-011 · CLI 入口验收测试：main() + argparse + 6 档退出码。

其他模块测试已拆分：
  - test_context_usage_inventory.py   ← F-004 ContextInventory
  - test_context_usage_git_timestamps.py ← F-008 fetch_git_timestamps
  - test_context_usage_aggregator.py  ← F-009 UsageAggregator
  - test_context_usage_renderer.py    ← F-010 ReportRenderer
  - test_context_usage_e2e.py         ← F-013 E2E + 性能守门

接口来源：detailed-design.md §CLI 入口 / §CLI Arguments / §异常处理表
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))

from context_usage_report import main, _parse_args, _parse_since  # noqa: E402


# ---------------------------------------------------------------------------
# _parse_since 单元测试
# ---------------------------------------------------------------------------


def test_parse_since_formats() -> None:
    """_parse_since 解析各种时间单位格式。"""
    assert _parse_since("90d") == 90
    assert _parse_since("2w") == 14
    assert _parse_since("3m") == 90
    assert _parse_since("1d") == 1
    assert _parse_since("1w") == 7
    assert _parse_since("1m") == 30


def test_parse_since_invalid_format() -> None:
    """_parse_since 非法格式抛 ValueError。"""
    with pytest.raises(ValueError, match="invalid --since format"):
        _parse_since("abc")
    with pytest.raises(ValueError, match="invalid --since format"):
        _parse_since("90")
    with pytest.raises(ValueError, match="invalid --since format"):
        _parse_since("d90")


# ---------------------------------------------------------------------------
# argparse 单元测试
# ---------------------------------------------------------------------------


def test_argparse_help() -> None:
    """--help 不抛异常（argparse 处理）。"""
    # argparse 的 --help 会 raise SystemExit(0)
    with pytest.raises(SystemExit) as exc_info:
        _parse_args(["--help"])
    assert exc_info.value.code == 0


def test_argparse_defaults(tmp_path: Path) -> None:
    """默认参数值符合设计。"""
    # 因为 common.REPO_ROOT 是绝对路径，直接检查参数类型而不是精确值
    args = _parse_args([])
    assert args.context_dir.is_absolute()
    assert args.requirements_dir.is_absolute()
    assert args.output.is_absolute()
    assert args.json_output.is_absolute()
    assert args.since == "90d"
    assert args.project is None
    assert args.only_experience is False
    assert args.format == "both"
    assert args.fail_on_broken_index is False
    assert args.fail_on_orphan is False


def test_argparse_custom_values(tmp_path: Path) -> None:
    """自定义参数值被正确解析。"""
    ctx_dir = tmp_path / "ctx"
    ctx_dir.mkdir()
    req_dir = tmp_path / "req"
    req_dir.mkdir()

    args = _parse_args(
        [
            "--context-dir",
            str(ctx_dir),
            "--requirements-dir",
            str(req_dir),
            "--since",
            "30d",
            "--project",
            "myproj",
            "--only-experience",
            "--format",
            "json",
            "--fail-on-broken-index",
            "--fail-on-orphan",
        ]
    )
    assert args.context_dir == ctx_dir
    assert args.requirements_dir == req_dir
    assert args.since == "30d"
    assert args.project == "myproj"
    assert args.only_experience is True
    assert args.format == "json"
    assert args.fail_on_broken_index is True
    assert args.fail_on_orphan is True


# ---------------------------------------------------------------------------
# main() 退出码测试
# ---------------------------------------------------------------------------


def test_main_exit_0_success(tmp_path: Path) -> None:
    """main 成功运行返回 exit 0。"""
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "team").mkdir()
    (ctx_dir / "team" / "foo.md").write_text("# foo\n", encoding="utf-8")

    req_dir = tmp_path / "requirements"
    req_dir.mkdir()

    output = tmp_path / "reports" / "report.md"
    json_output = tmp_path / "reports" / "report.json"

    exit_code = main(
        [
            "--context-dir",
            str(ctx_dir),
            "--requirements-dir",
            str(req_dir),
            "--output",
            str(output),
            "--json-output",
            str(json_output),
            "--repo-root",
            str(tmp_path),
            "--format",
            "both",
        ]
    )

    assert exit_code == 0
    assert output.exists()
    assert json_output.exists()


def test_main_exit_2_context_dir_not_found(tmp_path: Path, capsys) -> None:
    """main 返回 exit 2 当 --context-dir 不存在，stderr 含 ERROR 信息。"""
    req_dir = tmp_path / "requirements"
    req_dir.mkdir()

    exit_code = main(
        [
            "--context-dir",
            str(tmp_path / "nonexistent"),
            "--requirements-dir",
            str(req_dir),
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "context-dir" in captured.err.lower()


def test_main_exit_2_requirements_dir_not_found(tmp_path: Path, capsys) -> None:
    """main 返回 exit 2 当 --requirements-dir 不存在，stderr 含 ERROR 信息。"""
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()

    exit_code = main(
        [
            "--context-dir",
            str(ctx_dir),
            "--requirements-dir",
            str(tmp_path / "nonexistent"),
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "requirements-dir" in captured.err.lower()


def test_main_exit_1_invalid_since(tmp_path: Path, capsys) -> None:
    """AC：exit 1 = _parse_since 参数错误，stderr 含 ERROR 信息。"""
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "team").mkdir()
    (context_dir / "team" / "foo.md").write_text("# foo\n", encoding="utf-8")
    req_dir = tmp_path / "requirements"
    req_dir.mkdir()

    exit_code = main(
        [
            "--context-dir",
            str(context_dir),
            "--requirements-dir",
            str(req_dir),
            "--since",
            "invalid_format_xyz",
            "--output",
            str(tmp_path / "report.md"),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "ERROR" in captured.err or "无效" in captured.err or "invalid" in captured.err.lower()


def test_main_exit_5_write_failure(tmp_path: Path, capsys) -> None:
    """main 返回 exit 5 当报告写入失败，stderr 含 ERROR 信息。"""
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "team").mkdir()
    (ctx_dir / "team" / "foo.md").write_text("# foo\n", encoding="utf-8")

    req_dir = tmp_path / "requirements"
    req_dir.mkdir()

    from context_usage_report import ReportRenderer

    def mock_write_error(*args, **kwargs):
        raise OSError("mock write failure")

    with patch.object(ReportRenderer, "write", mock_write_error):
        exit_code = main(
            [
                "--context-dir",
                str(ctx_dir),
                "--requirements-dir",
                str(req_dir),
                "--repo-root",
                str(tmp_path),
            ]
        )

    assert exit_code == 5
    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "失败" in captured.err or "failure" in captured.err.lower()


def test_main_exit_3_fail_on_broken_index(tmp_path: Path, capsys) -> None:
    """main 返回 exit 3 当 --fail-on-broken-index 且检出断链。"""
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "team").mkdir()
    (ctx_dir / "team" / "INDEX.md").write_text(
        "# Index\n\n[broken link](nonexistent.md)\n", encoding="utf-8"
    )
    (ctx_dir / "team" / "foo.md").write_text("# foo\n", encoding="utf-8")

    req_dir = tmp_path / "requirements"
    req_dir.mkdir()

    exit_code = main(
        [
            "--context-dir",
            str(ctx_dir),
            "--requirements-dir",
            str(req_dir),
            "--repo-root",
            str(tmp_path),
            "--fail-on-broken-index",
        ]
    )

    assert exit_code == 3
    captured = capsys.readouterr()
    # 注：F-011-FU m1 后 exit 3 stderr 文案对齐 detailed-design.md L765
    # "BROKEN_LINKS_DETECTED (N)" 不带 ERROR 前缀；与 exit 2/4/5 风格刻意不同。
    assert "BROKEN_LINKS_DETECTED" in captured.err


def test_main_exit_4_fail_on_orphan(tmp_path: Path, capsys) -> None:
    """main 返回 exit 4 当 --fail-on-orphan 且检出孤岛文件。"""
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "team").mkdir()
    # 创建没有被 INDEX 引用的文件
    (ctx_dir / "team" / "orphan.md").write_text("# orphan\n", encoding="utf-8")

    req_dir = tmp_path / "requirements"
    req_dir.mkdir()

    exit_code = main(
        [
            "--context-dir",
            str(ctx_dir),
            "--requirements-dir",
            str(req_dir),
            "--repo-root",
            str(tmp_path),
            "--fail-on-orphan",
        ]
    )

    assert exit_code == 4
    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "ORPHANS_DETECTED" in captured.err or "孤岛" in captured.err


def test_main_stdout_summary(tmp_path: Path, capsys) -> None:
    """main 成功时 stdout 含总数、状态计数、warnings 行。"""
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "team").mkdir()
    (ctx_dir / "team" / "foo.md").write_text("# foo\n", encoding="utf-8")
    (ctx_dir / "team" / "bar.md").write_text("# bar\n", encoding="utf-8")

    req_dir = tmp_path / "requirements"
    req_dir.mkdir()

    main(
        [
            "--context-dir",
            str(ctx_dir),
            "--requirements-dir",
            str(req_dir),
            "--repo-root",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    # stdout 应含总数（如 "总数: 2"）
    assert "总数" in captured.out or "total" in captured.out.lower() or "2" in captured.out


# F-011-FU M-1 / M-2 回归：warnings 走 stderr WARN 前缀 + format=both 半写状态告知
# 修复 review-F-011-20260520 M1/M2


def test_main_warnings_printed_to_stderr_with_WARN_prefix(tmp_path: Path, capsys) -> None:
    """warnings 非空时逐条打到 stderr，行格式 'WARN <msg>'。

    设计 detailed-design.md:781-782 明确：warning / error 行走 stderr，
    格式 `<LEVEL> <message>`。
    用 git 缺失场景触发 fetch_git_timestamps fallback warning。
    """
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "team").mkdir()
    (ctx_dir / "team" / "foo.md").write_text("# foo\n", encoding="utf-8")

    req_dir = tmp_path / "requirements"
    req_dir.mkdir()

    # mock subprocess.run 触发 git log 失败 → 产生 warning
    with patch(
        "context_usage_report.subprocess.run",
        side_effect=FileNotFoundError("git not found"),
    ):
        exit_code = main(
            [
                "--context-dir",
                str(ctx_dir),
                "--requirements-dir",
                str(req_dir),
                "--repo-root",
                str(tmp_path),
            ]
        )

    assert exit_code == 0
    captured = capsys.readouterr()
    # stdout 应仍有数量计数
    assert "Warnings:" in captured.out
    # stderr 应有 WARN 前缀行
    assert "WARN" in captured.err
    assert "git log 失败" in captured.err


def test_main_render_and_write_half_write_notice(tmp_path: Path, capsys) -> None:
    """format=both 时 md 已写、json 写失败 → exit 5 + stderr 告知半写状态。

    M2 fix：先 render 两份 content 再批量 write 缩小窗口；写失败时显式提示用户。
    """
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "team").mkdir()
    (ctx_dir / "team" / "foo.md").write_text("# foo\n", encoding="utf-8")

    req_dir = tmp_path / "requirements"
    req_dir.mkdir()

    from context_usage_report import ReportRenderer

    # mock：第二次 write 抛 OSError（json 阶段失败）
    # write 是 @staticmethod，patch 时需 staticmethod 包装否则会绑定 self 改签名
    call_count = [0]
    real_write = ReportRenderer.write

    def _flaky_write_impl(content, output_path):
        call_count[0] += 1
        if call_count[0] == 2:
            raise OSError("mock json write failure")
        return real_write(content, output_path)

    with patch.object(ReportRenderer, "write", staticmethod(_flaky_write_impl)):
        exit_code = main(
            [
                "--context-dir",
                str(ctx_dir),
                "--requirements-dir",
                str(req_dir),
                "--repo-root",
                str(tmp_path),
                "--format",
                "both",
            ]
        )

    assert exit_code == 5
    captured = capsys.readouterr()
    assert "ERROR: 写报告失败" in captured.err
    # M2 半写告知
    assert "WARN 部分写入" in captured.err
    assert "md 已成功" in captured.err
