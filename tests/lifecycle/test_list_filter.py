"""list_requirements() 的过滤、互斥和排序测试。"""
from __future__ import annotations

import pytest
import yaml
from pathlib import Path

# 导入被测函数
import sys
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts" / "lib"))
from list_requirements import list_requirements


@pytest.fixture
def fake_requirements_dir(tmp_path: Path) -> Path:
    """构造临时 requirements 目录，包含 5 个假 meta.yaml。

    结构：
      - REQ-2026-001: phase=development, created_at=2026-04-20 10:00:00
      - REQ-2026-002: phase=testing, created_at=2026-04-21 09:00:00
      - REQ-2026-003: phase=completed, created_at=2026-04-22 11:00:00
      - REQ-2026-004: phase=definition, created_at=2026-04-23 08:00:00
      - REQ-2026-005: phase=completed, created_at=2026-04-19 15:00:00
    """
    fixtures = [
        ("REQ-2026-001", "development", "2026-04-20 10:00:00", "feat/req-2026-001"),
        ("REQ-2026-002", "testing", "2026-04-21 09:00:00", "feat/req-2026-002"),
        ("REQ-2026-003", "completed", "2026-04-22 11:00:00", "feat/req-2026-003"),
        ("REQ-2026-004", "definition", "2026-04-23 08:00:00", "feat/req-2026-004"),
        ("REQ-2026-005", "completed", "2026-04-19 15:00:00", "feat/req-2026-005"),
    ]

    for req_id, phase, created_at, branch in fixtures:
        req_dir = tmp_path / req_id
        req_dir.mkdir()
        meta = {
            "id": req_id,
            "title": f"需求 {req_id}",
            "phase": phase,
            "branch": branch,
            "created_at": created_at,
            "base_branch": "develop",
            "project": "agentic-meta-engineering",
            "services": ["service-a"],
            "feature_area": "core",
            "change_type": "feature",
            "affected_modules": ["module-x"],
        }
        meta_path = req_dir / "meta.yaml"
        with meta_path.open("w", encoding="utf-8") as f:
            yaml.dump(meta, f, allow_unicode=True)

    return tmp_path


def test_default_hides_completed(fake_requirements_dir: Path) -> None:
    """默认不传参时，隐藏 phase=completed 的需求。"""
    records = list_requirements(requirements_dir=fake_requirements_dir)

    # 应该有 3 条（REQ-001 development, REQ-002 testing, REQ-004 definition）
    assert len(records) == 3
    phases = {r["phase"] for r in records}
    assert phases == {"development", "testing", "definition"}
    assert "completed" not in phases

    # 验证倒序（按 created_at）
    # REQ-004: 2026-04-23 08:00:00 最新
    # REQ-002: 2026-04-21 09:00:00
    # REQ-001: 2026-04-20 10:00:00 最旧
    assert records[0]["id"] == "REQ-2026-004"
    assert records[1]["id"] == "REQ-2026-002"
    assert records[2]["id"] == "REQ-2026-001"


def test_all_includes_completed(fake_requirements_dir: Path) -> None:
    """--all=True 时，包含 phase=completed 的需求。"""
    records = list_requirements(all=True, requirements_dir=fake_requirements_dir)

    # 应该有 5 条全部
    assert len(records) == 5
    ids = {r["id"] for r in records}
    assert ids == {
        "REQ-2026-001",
        "REQ-2026-002",
        "REQ-2026-003",
        "REQ-2026-004",
        "REQ-2026-005",
    }

    # 验证倒序
    # REQ-004: 2026-04-23 08:00:00 最新
    # REQ-003: 2026-04-22 11:00:00
    # REQ-002: 2026-04-21 09:00:00
    # REQ-001: 2026-04-20 10:00:00
    # REQ-005: 2026-04-19 15:00:00 最旧
    assert records[0]["id"] == "REQ-2026-004"
    assert records[1]["id"] == "REQ-2026-003"
    assert records[2]["id"] == "REQ-2026-002"
    assert records[3]["id"] == "REQ-2026-001"
    assert records[4]["id"] == "REQ-2026-005"


def test_phase_filter(fake_requirements_dir: Path) -> None:
    """--phase='development' 时，仅留该阶段。"""
    records = list_requirements(phase="development", requirements_dir=fake_requirements_dir)

    # 应该只有 1 条（REQ-001）
    assert len(records) == 1
    assert records[0]["id"] == "REQ-2026-001"
    assert records[0]["phase"] == "development"

    # 测试另一个阶段
    records = list_requirements(phase="completed", requirements_dir=fake_requirements_dir)
    assert len(records) == 2
    phases = {r["phase"] for r in records}
    assert phases == {"completed"}
    # 倒序
    assert records[0]["id"] == "REQ-2026-003"
    assert records[1]["id"] == "REQ-2026-005"


def test_all_and_phase_mutex(fake_requirements_dir: Path) -> None:
    """--all 与 --phase 同时传入时，抛 ValueError 含 'mutually exclusive'。"""
    with pytest.raises(ValueError, match="mutually exclusive"):
        list_requirements(
            all=True,
            phase="development",
            requirements_dir=fake_requirements_dir,
        )


def test_phase_label_mapping(fake_requirements_dir: Path) -> None:
    """验证 phase_label 的中文映射正确。"""
    records = list_requirements(all=True, requirements_dir=fake_requirements_dir)

    # 找到每个阶段的记录，验证中文名
    by_phase = {r["phase"]: r["phase_label"] for r in records}
    assert by_phase.get("development") == "开发实施"
    assert by_phase.get("testing") == "测试验收"
    assert by_phase.get("completed") == "完成"
    assert by_phase.get("definition") == "需求定义"


def test_sort_handles_mixed_naive_and_aware_timestamps(tmp_path: Path) -> None:
    """codex F-3 (P2) 回归：仓库里同时存在 `YYYY-MM-DD HH:MM:SS`（naive）
    与 `...Z`（aware）格式时，旧实现在 records.sort 处会抛 TypeError，
    导致 /requirement:list 整命令崩溃。

    修复后两种格式都归一到 tzaware Asia/Shanghai，排序不抛异常。
    """
    fixtures = [
        # naive 格式（YYYY-MM-DD HH:MM:SS，新 spec 默认 Asia/Shanghai）
        ("REQ-2026-A01", "development", "2026-04-20 10:00:00"),
        # aware 格式（旧 ISO，UTC Z）
        ("REQ-2026-A02", "testing", "2026-04-21T01:00:00Z"),
        # 带 offset 的 ISO（兼容路径）
        ("REQ-2026-A03", "definition", "2026-04-22T11:00:00+08:00"),
    ]
    for req_id, phase, created_at in fixtures:
        req_dir = tmp_path / req_id
        req_dir.mkdir()
        meta = {
            "id": req_id,
            "title": f"需求 {req_id}",
            "phase": phase,
            "branch": f"feat/{req_id.lower()}",
            "created_at": created_at,
            "base_branch": "develop",
        }
        with (req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)

    # 不应抛 TypeError；返回的 list 按 created_at 倒序
    records = list_requirements(all=True, requirements_dir=tmp_path)
    assert len(records) == 3
    ids = [r["id"] for r in records]
    # 倒序：A03 (2026-04-22 11:00 +08:00) > A02 (2026-04-21 01:00 UTC = 09:00 +08:00) > A01 (2026-04-20 10:00 +08:00)
    assert ids == ["REQ-2026-A03", "REQ-2026-A02", "REQ-2026-A01"], (
        f"实际顺序：{ids} —— codex P2 finding F-3 的回归保护"
    )
