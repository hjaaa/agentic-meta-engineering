"""tests/lib/test_audit_flush.py：audit_flush.py 单元测试。

F-004 §4.3 / TC-F4-5 验收测试覆盖：
  - normal flush：队列有日志 → JSON 追加 + .log 归档到 .queue.done
  - queue 目录缺失：静默返回 0
  - 单 .log 解析失败（损坏行）：跳过该行，不影响其他行
  - entry 分桶正确：runner / submit / pre-tool-use-guard 各自落到对应文件
  - archive 到 .queue.done 而非删除（不丢数据）
  - 同名文件 dup<N> 命名
  - --dry-run 不动文件
  - main 永不抛异常（任何异常均被 swallow）

隔离策略：使用 tmp_path + monkeypatch 替换 _QUEUE_DIR / _AUDIT_DIR / _QUEUE_DONE_DIR。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pytest

# 确保 scripts/lib 在 sys.path 中
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import audit_flush


# ====================== Fixture：隔离 audit_flush 的路径常量 ======================

@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """把 audit_flush 的三个路径常量替换到 tmp_path 下。"""
    queue_dir = tmp_path / "audit" / ".queue"
    audit_dir = tmp_path / "audit"
    queue_done_dir = tmp_path / "audit" / ".queue.done"
    queue_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(audit_flush, "_QUEUE_DIR", queue_dir)
    monkeypatch.setattr(audit_flush, "_AUDIT_DIR", audit_dir)
    monkeypatch.setattr(audit_flush, "_QUEUE_DONE_DIR", queue_done_dir)
    return queue_dir, audit_dir, queue_done_dir


# ====================== 辅助函数 ======================

def _write_log(queue_dir: Path, filename: str, lines: list[str]) -> Path:
    """写 .log 文件到 queue_dir。"""
    log_file = queue_dir / filename
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log_file


def _make_log_line(
    ts: str = "2026-05-04T10:00:00+08:00",
    cwd: str = "/repo",
    event: str = "BYPASS used: test-reason",
    entry: str = "runner",
) -> str:
    return f"{ts} {cwd} {event} @ entry={entry}"


# ====================== TC：queue 目录缺失静默 ======================


def test_queue_missing_exits_zero(tmp_path, monkeypatch):
    """given_no_queue_dir_when_main_then_returns_0_silently."""
    missing = tmp_path / "no-such-dir" / ".queue"
    monkeypatch.setattr(audit_flush, "_QUEUE_DIR", missing)
    monkeypatch.setattr(audit_flush, "_AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(audit_flush, "_QUEUE_DONE_DIR", tmp_path / "audit" / ".queue.done")
    rc = audit_flush.main([])
    assert rc == 0


# ====================== TC：normal flush ======================


def test_normal_flush_writes_json_and_archives(isolated_dirs):
    """given_queue_with_log_when_main_then_json_written_and_log_archived."""
    queue_dir, audit_dir, queue_done_dir = isolated_dirs
    log_line = _make_log_line(entry="runner")
    _write_log(queue_dir, "2026-05-04.log", [log_line])

    rc = audit_flush.main([])
    assert rc == 0

    # JSON 应被写入
    yyyy_mm = "2026-05"
    expected_json = audit_dir / yyyy_mm / "runner-2026-05-04.json"
    assert expected_json.exists(), f"Expected {expected_json} to exist"
    content = expected_json.read_text(encoding="utf-8")
    assert log_line in content

    # .log 应被 mv 到 .queue.done
    archived = queue_done_dir / "2026-05-04" / "2026-05-04.log"
    today_str = date.today().strftime("%Y-%m-%d")
    done_today = queue_done_dir / today_str / "2026-05-04.log"
    assert done_today.exists(), f"Expected log archived to .queue.done/{today_str}/"


# ====================== TC：entry 分桶正确 ======================


def test_entry_bucketing_correct(isolated_dirs):
    """given_mixed_entries_when_flush_then_each_entry_has_own_json_file."""
    queue_dir, audit_dir, queue_done_dir = isolated_dirs
    lines = [
        _make_log_line(entry="runner"),
        _make_log_line(entry="trigger:submit"),
        _make_log_line(entry="pre-tool-use-guard"),
    ]
    _write_log(queue_dir, "2026-05-04.log", lines)

    audit_flush.main([])

    yyyy_mm = "2026-05"
    assert (audit_dir / yyyy_mm / "runner-2026-05-04.json").exists()
    assert (audit_dir / yyyy_mm / "trigger:submit-2026-05-04.json").exists()
    assert (audit_dir / yyyy_mm / "pre-tool-use-guard-2026-05-04.json").exists()


# ====================== TC：archive 到 .queue.done 不删除 ======================


def test_archive_to_queue_done_not_deleted(isolated_dirs):
    """given_processed_log_when_archive_then_file_in_queue_done_not_deleted."""
    queue_dir, audit_dir, queue_done_dir = isolated_dirs
    log_line = _make_log_line(entry="runner")
    _write_log(queue_dir, "2026-05-04.log", [log_line])

    audit_flush.main([])

    # 原始 .queue 文件应已被移走
    assert not (queue_dir / "2026-05-04.log").exists(), "log should be moved, not deleted"

    # .queue.done 下应有该文件
    today_str = date.today().strftime("%Y-%m-%d")
    done_dir = queue_done_dir / today_str
    moved_files = list(done_dir.glob("*.log*"))
    assert len(moved_files) >= 1, f"Expected archived file in {done_dir}, found: {moved_files}"


# ====================== TC：同名文件 dup<N> 命名 ======================


def test_archive_duplicate_naming(isolated_dirs):
    """given_two_logs_with_same_name_when_archive_then_second_gets_dup1_suffix."""
    queue_dir, audit_dir, queue_done_dir = isolated_dirs
    log_line = _make_log_line(entry="runner")

    # 先 flush 第一个
    _write_log(queue_dir, "2026-05-04.log", [log_line])
    audit_flush.main([])

    today_str = date.today().strftime("%Y-%m-%d")
    done_dir = queue_done_dir / today_str

    # 放回同名文件，模拟第二次 flush 同日志名
    _write_log(queue_dir, "2026-05-04.log", [log_line])
    audit_flush.main([])

    # 期望有 .dup1.log
    dup_files = list(done_dir.glob("*.dup*.log"))
    assert len(dup_files) >= 1, f"Expected at least one .dup*.log file in {done_dir}"


# ====================== TC：单 .log 解析失败行跳过 ======================


def test_corrupt_line_skipped(isolated_dirs):
    """given_corrupt_line_in_log_when_flush_then_corrupt_line_skipped_valid_ok."""
    queue_dir, audit_dir, queue_done_dir = isolated_dirs
    valid_line = _make_log_line(entry="runner")
    corrupt_line = "THIS IS NOT A VALID LOG LINE"
    _write_log(queue_dir, "2026-05-04.log", [corrupt_line, valid_line])

    rc = audit_flush.main([])
    assert rc == 0

    # 有效行应仍被写入
    yyyy_mm = "2026-05"
    expected_json = audit_dir / yyyy_mm / "runner-2026-05-04.json"
    assert expected_json.exists()
    content = expected_json.read_text(encoding="utf-8")
    assert valid_line in content


# ====================== TC：queue 为空（无 .log 文件）时静默 ======================


def test_empty_queue_exits_zero(isolated_dirs):
    """given_empty_queue_dir_when_main_then_returns_0_silently."""
    queue_dir, audit_dir, queue_done_dir = isolated_dirs
    rc = audit_flush.main([])
    assert rc == 0


# ====================== TC：_parse_lines rsplit 兼容 event 含 @ entry= ======================


def test_parse_lines_rsplit_compatibility(tmp_path):
    """given_event_containing_at_entry_literal_when_parse_then_correct_entry_extracted."""
    log_file = tmp_path / "test.log"
    # event 段本身含 '@ entry=' 字面量
    tricky_line = '2026-05-04T10:00:00+08:00 /repo audit {"x":"@ entry=fake"} @ entry=runner'
    log_file.write_text(tricky_line + "\n", encoding="utf-8")

    records = audit_flush._parse_lines(log_file)
    assert len(records) == 1
    assert records[0]["entry"] == "runner"


# ====================== TC：--dry-run 不动文件 ======================


def test_dry_run_no_file_changes(isolated_dirs, capsys):
    """given_dry_run_when_main_then_no_files_moved_or_written."""
    queue_dir, audit_dir, queue_done_dir = isolated_dirs
    log_line = _make_log_line(entry="runner")
    log_file = _write_log(queue_dir, "2026-05-04.log", [log_line])

    rc = audit_flush.main(["--dry-run"])
    assert rc == 0

    # log 文件不应被移走
    assert log_file.exists(), "dry-run should not move log files"

    # JSON 文件不应被创建
    yyyy_mm = "2026-05"
    assert not (audit_dir / yyyy_mm / "runner-2026-05-04.json").exists()


# ====================== TC：main 任何异常均被 swallow ======================


def test_main_never_raises(monkeypatch):
    """given_internal_exception_when_main_then_returns_0_never_raises."""
    def boom(*a, **kw):
        raise RuntimeError("intentional test explosion")

    monkeypatch.setattr(audit_flush, "_dispatch", boom)
    rc = audit_flush.main([])
    assert rc == 0


# ====================== TC：同日多次 flush 走 append ======================


def test_same_day_multiple_flushes_append(isolated_dirs):
    """given_two_flushes_same_day_when_flush_then_json_has_both_records（append，不覆盖）。"""
    queue_dir, audit_dir, queue_done_dir = isolated_dirs

    line1 = _make_log_line(ts="2026-05-04T10:00:00+08:00", event="event-1", entry="runner")
    line2 = _make_log_line(ts="2026-05-04T11:00:00+08:00", event="event-2", entry="runner")

    # 第一次 flush
    _write_log(queue_dir, "2026-05-04-a.log", [line1])
    audit_flush.main([])

    # 第二次 flush
    _write_log(queue_dir, "2026-05-04-b.log", [line2])
    audit_flush.main([])

    yyyy_mm = "2026-05"
    expected_json = audit_dir / yyyy_mm / "runner-2026-05-04.json"
    assert expected_json.exists()
    content = expected_json.read_text(encoding="utf-8")
    assert "event-1" in content
    assert "event-2" in content
