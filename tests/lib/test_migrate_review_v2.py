"""migrate_review_v2 单测：干跑产出、scan_old_verdicts 发现旧 verdict、--apply 安全约束。

验收要求：
  - scan_old_verdicts 能正确识别 conclusion ∈ 旧枚举的 verdict
  - render_dry_run_report 输出包含 path :: conclusion :: 建议 的单行格式
  - apply_rename 不引入 decision=approved（D-002 强制重签约束）
  - apply_rename 把 approved → looks_clean，human_signoff 置 null

来源：requirements/REQ-2026-003/artifacts/detailed-design.md §F-001.4
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_LIB_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import migrate_review_v2 as mv  # noqa: E402


# ---------- 辅助函数 ----------

def _write_verdict(tmp_path: Path, req_id: str, filename: str, conclusion: str, **extra) -> Path:
    """在 tmp_path/requirements/<req_id>/reviews/ 写入一个 verdict JSON。"""
    reviews_dir = tmp_path / "requirements" / req_id / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "review_id": f"REV-{req_id}-definition-001",
        "conclusion": conclusion,
        "score": 80,
        "dimensions": {},
        "required_fixes": [],
        **extra,
    }
    f = reviews_dir / filename
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f


# ---------- scan_old_verdicts ----------

def test_scan_finds_approved_verdict(tmp_path):
    """given_verdict_conclusion_approved_when_scan_then_found。"""
    _write_verdict(tmp_path, "REQ-2026-001", "definition-001.json", "approved")
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    assert len(items) == 1
    assert items[0].conclusion == "approved"


def test_scan_finds_needs_revision_verdict(tmp_path):
    """given_verdict_conclusion_needs_revision_when_scan_then_found。"""
    _write_verdict(tmp_path, "REQ-2026-001", "definition-001.json", "needs_revision")
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    assert len(items) == 1
    assert items[0].conclusion == "needs_revision"


def test_scan_finds_rejected_verdict(tmp_path):
    """given_verdict_conclusion_rejected_when_scan_then_found。"""
    _write_verdict(tmp_path, "REQ-2026-001", "definition-001.json", "rejected")
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    assert len(items) == 1
    assert items[0].conclusion == "rejected"


def test_scan_skips_new_enum_verdicts(tmp_path):
    """given_verdict_conclusion_looks_clean_when_scan_then_not_found（新枚举不纳入）。"""
    _write_verdict(tmp_path, "REQ-2026-001", "definition-001.json", "looks_clean")
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    assert len(items) == 0


def test_scan_finds_multiple_old_verdicts(tmp_path):
    """given_3_verdicts_2_old_when_scan_then_found_2。"""
    _write_verdict(tmp_path, "REQ-2026-001", "definition-001.json", "approved")
    _write_verdict(tmp_path, "REQ-2026-001", "definition-002.json", "needs_revision")
    _write_verdict(tmp_path, "REQ-2026-001", "definition-003.json", "looks_clean")
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    assert len(items) == 2
    conclusions = {item.conclusion for item in items}
    assert conclusions == {"approved", "needs_revision"}


def test_scan_returns_empty_when_no_old_verdicts(tmp_path):
    """given_no_old_verdicts_when_scan_then_empty_list。"""
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    assert items == []


def test_scan_item_has_correct_path_and_data(tmp_path):
    """scan_old_verdicts 返回的 OldVerdict 含正确的 path 和 data。"""
    f = _write_verdict(tmp_path, "REQ-2026-001", "definition-001.json", "approved")
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    assert len(items) == 1
    assert items[0].path == f
    assert items[0].data["conclusion"] == "approved"


# ---------- render_dry_run_report ----------

def test_render_dry_run_contains_path_conclusion_advice(tmp_path):
    """render_dry_run_report 每行包含 path :: conclusion :: 建议。"""
    f = _write_verdict(tmp_path, "REQ-2026-001", "definition-001.json", "approved")
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    report = mv.render_dry_run_report(items)

    # 至少有一行包含文件名和 conclusion
    assert "definition-001.json" in report
    assert "approved" in report
    assert "::" in report


def test_render_dry_run_approved_says_can_migrate(tmp_path):
    """render_dry_run_report 对 approved 显示可平移提示。"""
    _write_verdict(tmp_path, "REQ-2026-001", "definition-001.json", "approved")
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    report = mv.render_dry_run_report(items)
    # 可平移提示（中文提示）
    assert "可平移" in report or "looks_clean" in report


def test_render_dry_run_needs_revision_says_resign(tmp_path):
    """render_dry_run_report 对 needs_revision 显示建议重签提示。"""
    _write_verdict(tmp_path, "REQ-2026-001", "definition-001.json", "needs_revision")
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    report = mv.render_dry_run_report(items)
    assert "重签" in report or "needs_attention" in report or "blocked" in report


def test_render_dry_run_empty_when_no_items():
    """render_dry_run_report 无条目时返回无需迁移提示。"""
    report = mv.render_dry_run_report([])
    assert "无需迁移" in report or "未发现" in report


# ---------- apply_rename ----------

def test_apply_rename_approved_to_looks_clean(tmp_path):
    """given_approved_verdict_when_apply_then_conclusion_becomes_looks_clean。"""
    f = _write_verdict(tmp_path, "REQ-2026-001", "definition-001.json", "approved")
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    count = mv.apply_rename(items)

    assert count == 1
    result = json.loads(f.read_text(encoding="utf-8"))
    assert result["conclusion"] == "looks_clean"


def test_apply_rename_does_not_write_decision_approved(tmp_path):
    """D-002: apply_rename 不引入 decision=approved（强制重签约束）。"""
    f = _write_verdict(tmp_path, "REQ-2026-001", "definition-001.json", "approved",
                       human_signoff={"decision": "approved", "source": "cli-tty",
                                      "signed_at": "2026-01-01T00:00:00Z",
                                      "signed_by": "user@example.com"})
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    mv.apply_rename(items)

    result = json.loads(f.read_text(encoding="utf-8"))
    # human_signoff 必须被清空（不能保留 decision=approved）
    assert result.get("human_signoff") is None, (
        f"human_signoff 未被清空，实际：{result.get('human_signoff')}"
    )
    # 也不能新增 decision=approved 字段
    assert result.get("decision") != "approved"


def test_apply_rename_clears_human_signoff(tmp_path):
    """apply_rename 将 human_signoff 置为 null（强制重签）。"""
    f = _write_verdict(tmp_path, "REQ-2026-001", "definition-001.json", "approved",
                       human_signoff={"decision": "approved", "source": "cli-tty",
                                      "signed_at": "2026-01-01T00:00:00Z",
                                      "signed_by": "user@example.com"})
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    mv.apply_rename(items)

    result = json.loads(f.read_text(encoding="utf-8"))
    assert result["human_signoff"] is None


def test_apply_rename_preserves_non_approved_conclusion(tmp_path):
    """apply_rename 不修改 needs_revision（无直接映射，保留原值待人工处理）。"""
    f = _write_verdict(tmp_path, "REQ-2026-001", "definition-001.json", "needs_revision")
    items = mv.scan_old_verdicts(tmp_path / "requirements")
    mv.apply_rename(items)

    result = json.loads(f.read_text(encoding="utf-8"))
    # needs_revision 保留不变（no RENAME_MAP entry）
    assert result["conclusion"] == "needs_revision"


def test_apply_rename_returns_zero_when_no_items():
    """apply_rename 无条目时返回 0。"""
    count = mv.apply_rename([])
    assert count == 0
