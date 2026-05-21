"""`/workflow:continue` 读 process.txt 末位事件用于人/AI 恢复上下文。

覆盖范围：

  TC-PR-1  `_read_recent_process_entries`：文件不存在 → 返空列表
  TC-PR-2  `_read_recent_process_entries`：文件空 / 全空白行 → 返空列表
  TC-PR-3  `_read_recent_process_entries`：< N 行 → 全部返回，按文件顺序
  TC-PR-4  `_read_recent_process_entries`：≥ N 行 → 仅返末 N 行
  TC-PR-5  `_read_recent_process_entries`：OSError → 空列表（fail-open）

  TC-PR-6  `_print_resume_summary`：无内容 → 不打印（静默）
  TC-PR-7  `_print_resume_summary`：有内容 → 按格式打 stderr + state/current_node 行
  TC-PR-8  `_print_resume_summary`：末位含 `save:` → 该行用 ★ 前缀高亮
  TC-PR-9  `_print_resume_summary`：末位含全角 `save：` → 同样高亮（双冒号兼容）

外部依赖（process.txt 读 IO）用 tmp_path / monkeypatch；不动真实需求目录。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import workflow_continue as wc  # noqa: E402
from run_state import RunState  # noqa: E402


# ============================================================================
# Fixture：tmp 需求目录
# ============================================================================


@pytest.fixture
def req_dir(tmp_path: Path) -> Path:
    """生成 tmp 需求目录（不预写 process.txt，由各用例按需写）。"""
    return tmp_path


@pytest.fixture
def fake_run_state() -> "RunState":
    """构造一个最小 RunState 实例（state=running + current_node=foo）。"""
    return RunState(
        run_id="20260519-test",
        state="running",
        current_node="dev-feature-loop",
    )


# ============================================================================
# TC-PR-1 · 文件不存在 → 空列表
# ============================================================================


def test_read_recent_returns_empty_when_file_missing(req_dir: Path):
    """process.txt 缺失时返空列表（fail-open）。"""
    assert wc._read_recent_process_entries(req_dir) == []


# ============================================================================
# TC-PR-2 · 文件空 / 全空白行 → 空列表
# ============================================================================


def test_read_recent_returns_empty_when_file_blank(req_dir: Path):
    """文件全空白行（含 \\n 与 \\t 与空格）不算事件。"""
    (req_dir / "process.txt").write_text("\n\n   \n\t\n", encoding="utf-8")
    assert wc._read_recent_process_entries(req_dir) == []


# ============================================================================
# TC-PR-3 · < N 行：全部返回
# ============================================================================


def test_read_recent_returns_all_when_below_n(req_dir: Path):
    """3 行 < default last_n=10 → 全部返回，按文件顺序。"""
    content = (
        "2026-05-19 10:00:00 [definition] phase-transition: bootstrap → definition\n"
        "2026-05-19 11:00:00 [tech-research] phase-transition: definition → tech-research\n"
        "2026-05-19 12:00:00 [outline-design] phase-transition: tech-research → outline-design\n"
    )
    (req_dir / "process.txt").write_text(content, encoding="utf-8")

    result = wc._read_recent_process_entries(req_dir)

    assert len(result) == 3
    assert "definition → tech-research" in result[1]
    assert "tech-research → outline-design" in result[2]


# ============================================================================
# TC-PR-4 · ≥ N 行：仅返末 N 行
# ============================================================================


def test_read_recent_returns_only_last_n(req_dir: Path):
    """15 行 > last_n=10 → 仅返末 10，且为后 10 行（不是前 10）。"""
    lines = [f"2026-05-19 {i:02d}:00:00 [dev] event-{i}" for i in range(15)]
    (req_dir / "process.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = wc._read_recent_process_entries(req_dir, last_n=10)

    assert len(result) == 10
    assert "event-14" in result[-1]   # 末位
    assert "event-5" in result[0]     # 末 10 的首位 = 第 6 条（idx=5）


# ============================================================================
# TC-PR-5 · OSError → 空列表（fail-open）
# ============================================================================


def test_read_recent_returns_empty_on_oserror(req_dir: Path, monkeypatch):
    """read_text 抛 OSError（如权限拒绝）时不挡主流程，返空列表。"""
    (req_dir / "process.txt").write_text("2026-05-19 10:00:00 [dev] x", encoding="utf-8")

    def _raise(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", _raise)
    assert wc._read_recent_process_entries(req_dir) == []


# ============================================================================
# TC-PR-6 · _print_resume_summary 无内容 → 不打印
# ============================================================================


def test_print_summary_silent_when_empty(req_dir: Path, fake_run_state, capsys):
    """process.txt 不存在 → _print_resume_summary 完全静默（不打 stderr / stdout）。"""
    wc._print_resume_summary(req_dir, fake_run_state)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# ============================================================================
# TC-PR-7 · _print_resume_summary 正常打印（stderr）
# ============================================================================


def test_print_summary_prints_to_stderr_with_state_line(req_dir: Path, fake_run_state, capsys):
    """有内容时打印末 N 条 + state/current_node 收尾行；走 stderr 不污染 stdout。"""
    content = (
        "2026-05-19 10:00:00 [dev] F-001 完成\n"
        "2026-05-19 11:00:00 [dev] F-002 完成\n"
    )
    (req_dir / "process.txt").write_text(content, encoding="utf-8")

    wc._print_resume_summary(req_dir, fake_run_state)
    captured = capsys.readouterr()

    assert captured.out == ""             # 不污染 stdout
    assert "上次会话语义快照" in captured.err
    assert "F-001 完成" in captured.err
    assert "F-002 完成" in captured.err
    assert "state=running" in captured.err
    assert "current_node=dev-feature-loop" in captured.err


# ============================================================================
# TC-PR-8 · 末位 `save:` 高亮（半角冒号）
# ============================================================================


def test_print_summary_highlights_last_save_entry_halfwidth(req_dir: Path, fake_run_state, capsys):
    """末位含 `save:` 标识时该行打 ★ 前缀；其他行用空格前缀。"""
    content = (
        "2026-05-19 10:00:00 [dev] F-001 完成\n"
        "2026-05-19 11:00:00 [dev] save: 4/13 done; 下一个 F-005\n"
    )
    (req_dir / "process.txt").write_text(content, encoding="utf-8")

    wc._print_resume_summary(req_dir, fake_run_state)
    err_lines = capsys.readouterr().err.splitlines()

    starred = [line for line in err_lines if line.startswith("  ★ ")]
    plain = [line for line in err_lines if line.startswith("    2026-05-19")]
    assert len(starred) == 1, f"应有且仅有 1 行 ★ 高亮，实际：{starred}"
    assert "save: 4/13 done" in starred[0]
    assert len(plain) == 1
    assert "F-001 完成" in plain[0]


# ============================================================================
# TC-PR-9 · 末位 `save：`（全角冒号）也高亮
# ============================================================================


def test_print_summary_highlights_last_save_entry_fullwidth(req_dir: Path, fake_run_state, capsys):
    """半 / 全角冒号都识别（既有 save 事件两种写法都用过）。"""
    content = (
        "2026-05-19 10:00:00 [dev] F-001 完成\n"
        "2026-05-19 11:00:00 [dev] save：4/13 done; 下一个 F-005\n"
    )
    (req_dir / "process.txt").write_text(content, encoding="utf-8")

    wc._print_resume_summary(req_dir, fake_run_state)
    err_lines = capsys.readouterr().err.splitlines()

    starred = [line for line in err_lines if line.startswith("  ★ ")]
    assert len(starred) == 1
    assert "save：4/13 done" in starred[0]
