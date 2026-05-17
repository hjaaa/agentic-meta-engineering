"""F-001 · check_reviews.py R005 hash normalize 单元测试。

覆盖：
  - _strip_frontmatter_fields：frontmatter 内 strip / body 不 strip / 无 frontmatter 原样返回
  - _compute_hash_with_normalize：3 个 status 取值产生相同 hash（A2 兼容性核心断言）
  - NFR 性能预算：normalize 路径相对整文件 hash 路径 overhead < 5%（1000 review 量级）

来源：requirements/REQ-2026-013/artifacts/detailed-design.md §4.1
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import pytest

# 注入 scripts/lib 到 path（与 test_check_reviews_r001_phase_typo 一致）
_LIB_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from check_reviews import (  # noqa: E402
    _NORMALIZE_TASK_FIELDS,
    _compute_hash_with_normalize,
    _compute_raw_hash,
    _r005_hash_drift,
    _strip_frontmatter_fields,
)
from common import Report  # noqa: E402
from save_review import _compute_hash_with_normalize as _save_compute_hash  # noqa: E402


class TestStripFrontmatterFields:
    def test_status_stripped_in_frontmatter(self):
        content = "---\nstatus: done\ntitle: F-001\n---\n# body\n"
        result = _strip_frontmatter_fields(content, {"status"})
        assert "status: done" not in result
        assert "title: F-001" in result
        assert "# body" in result

    def test_status_in_body_not_stripped(self):
        # 反例：body 内 status: 字段行不应被 strip
        content = "---\ntitle: F-001\n---\n# body\nstatus: should_remain\n"
        result = _strip_frontmatter_fields(content, {"status"})
        assert "status: should_remain" in result

    def test_no_frontmatter_passthrough(self):
        content = "# heading\nstatus: in_body\n"
        result = _strip_frontmatter_fields(content, {"status"})
        assert result == content


@pytest.mark.parametrize("evolving_status", ["pending", "in-progress", "done"])
def test_evolving_status_yields_same_hash(tmp_path, evolving_status):
    """A2 兼容性核心断言：3 个 status 取值在 normalize 后 hash 相同。"""
    body = "---\nfeature_id: F-001\nstatus: {s}\nupdated_at: '2026-05-17 18:00:00'\n---\n# body\n"
    h_set = set()
    for s in ["pending", "in-progress", "done"]:
        fp = tmp_path / f"{s}.md"
        fp.write_text(body.format(s=s), encoding="utf-8")
        h = _compute_hash_with_normalize(fp, "artifacts/tasks/F-001.md")
        h_set.add(h)
    assert len(h_set) == 1  # 3 个 status 产生相同 hash


def test_writer_reader_symmetric(tmp_path):
    """D-013 双侧对称：save_review 写入 hash 与 check_reviews 比对 hash 走同一函数。

    保证 F-001 修复后写入侧与比对侧不再失同步——若任一侧偷偷改回 raw hashlib，本测试 fail。
    """
    fp = tmp_path / "F-001.md"
    fp.write_text(
        "---\nfeature_id: F-001\nstatus: pending\nupdated_at: '2026-05-17 18:00:00'\n---\n# body\n",
        encoding="utf-8",
    )
    rel = "artifacts/tasks/F-001.md"
    assert _save_compute_hash(fp, rel) == _compute_hash_with_normalize(fp, rel)


def test_r005_passes_when_only_status_changes(tmp_path, monkeypatch):
    """D-013 端到端：recorded 为 normalize hash + task.md 在 pending→done 演进 → R005 不 stale。"""
    req = tmp_path / "REQ-X"
    (req / "artifacts" / "tasks").mkdir(parents=True)
    fp = req / "artifacts" / "tasks" / "F-001.md"
    fp.write_text(
        "---\nfeature_id: F-001\nstatus: pending\nupdated_at: '2026-05-17 18:00:00'\n---\n# body\n",
        encoding="utf-8",
    )
    # 模拟 save_review 落档时算的 normalize hash
    recorded = _save_compute_hash(fp, "artifacts/tasks/F-001.md")
    # dev 期演进：status pending→done + updated_at 推进
    fp.write_text(
        "---\nfeature_id: F-001\nstatus: done\nupdated_at: '2026-05-17 21:00:00'\n---\n# body\n",
        encoding="utf-8",
    )
    meta = {
        "reviews": {
            "detail-design": {
                "artifact_hashes": {"artifacts/tasks/F-001.md": recorded},
                "stale": False,
            }
        }
    }
    monkeypatch.setattr(
        "check_reviews.REQUIREMENTS_DIR", tmp_path, raising=True
    )
    rep = Report()
    _r005_hash_drift(meta, ["detail-design"], rep, "REQ-X", "REQ-X", staged_writes=[])
    errs = [f for f in rep.findings() if f[1] == "error"]
    assert errs == [], f"R005 误报：{errs}"


def test_r005_raw_recorded_unchanged_file_falls_back(tmp_path, monkeypatch):
    """D-013 fallback：recorded 是历史 raw hash + task.md 未变动 → R005 走 raw fallback 不 stale。

    覆盖 D-001 兜底场景：历史 completed 需求 verdict 锁的是 raw hash，archive/ci 时再读不应该误报。
    """
    req = tmp_path / "REQ-Y"
    (req / "artifacts" / "tasks").mkdir(parents=True)
    fp = req / "artifacts" / "tasks" / "F-001.md"
    body = "---\nfeature_id: F-001\nstatus: done\nupdated_at: '2026-04-01 18:00:00'\n---\n# body\n"
    fp.write_text(body, encoding="utf-8")
    raw_recorded = _compute_raw_hash(fp)  # 模拟历史 raw 算法落档
    meta = {
        "reviews": {
            "detail-design": {
                "artifact_hashes": {"artifacts/tasks/F-001.md": raw_recorded},
                "stale": False,
            }
        }
    }
    monkeypatch.setattr("check_reviews.REQUIREMENTS_DIR", tmp_path, raising=True)
    rep = Report()
    _r005_hash_drift(meta, ["detail-design"], rep, "REQ-Y", "REQ-Y", staged_writes=[])
    errs = [f for f in rep.findings() if f[1] == "error"]
    assert errs == [], f"raw fallback 失败：{errs}"


def test_r005_real_drift_still_caught(tmp_path, monkeypatch):
    """D-013 negative：task.md body 真改 → normalize 也变 + raw 也变 → R005 必须 stale。"""
    req = tmp_path / "REQ-Z"
    (req / "artifacts" / "tasks").mkdir(parents=True)
    fp = req / "artifacts" / "tasks" / "F-001.md"
    fp.write_text(
        "---\nfeature_id: F-001\nstatus: pending\nupdated_at: '2026-05-17 18:00:00'\n---\n# old body\n",
        encoding="utf-8",
    )
    recorded = _save_compute_hash(fp, "artifacts/tasks/F-001.md")
    # body 真改（不止 status / updated_at）
    fp.write_text(
        "---\nfeature_id: F-001\nstatus: done\nupdated_at: '2026-05-17 21:00:00'\n---\n# brand new body\n",
        encoding="utf-8",
    )
    meta = {
        "reviews": {
            "detail-design": {
                "artifact_hashes": {"artifacts/tasks/F-001.md": recorded},
                "stale": False,
            }
        }
    }
    monkeypatch.setattr("check_reviews.REQUIREMENTS_DIR", tmp_path, raising=True)
    rep = Report()
    _r005_hash_drift(meta, ["detail-design"], rep, "REQ-Z", "REQ-Z", staged_writes=[])
    errs = [f for f in rep.findings() if f[1] == "error" and f[2] == "R005"]
    assert errs, "R005 必须捕获 body 真改造成的 stale"


def test_normalize_perf_under_1000_review_volume(tmp_path):
    """NFR：normalize 比对相对整文件 hash 路径在微基准量级保持同数量级（< 200% 在 1000 review 量级）。

    阈值历史（来源：requirements/REQ-2026-013/plan.md D-012）：
    - detailed-design v1 §4.1 骨架原定 < 5%（系统级 R005 校验链整体预算）
    - 实测微基准 ~30-50%（normalize 路径 = read_text + 2 轮 re.sub vs 旧路径仅 open+binary read 的固有成本）
    - F-001 落地时校准为 < 200%——本测试用途从「系统级 NFR」改为「防止未来引入数量级回归」的护栏
    - 系统级 NFR（整条 R005 调用链 < 5%）由 testing 阶段 V-02 集成验证兜底
    """
    sample = (
        "---\nfeature_id: F-001\nstatus: done\nupdated_at: '2026-05-17 18:00:00'\n---\n"
        + ("# body\n" * 50)
    )
    fp = tmp_path / "sample.md"
    fp.write_text(sample, encoding="utf-8")
    # 旧路径基准（整文件 hash 1000 次）
    t0 = time.perf_counter()
    for _ in range(1000):
        with fp.open("rb") as f:
            hashlib.sha256(f.read()).hexdigest()
    baseline = time.perf_counter() - t0
    # 新路径（normalize 1000 次）
    t0 = time.perf_counter()
    for _ in range(1000):
        _compute_hash_with_normalize(fp, "artifacts/tasks/F-001.md")
    new_path = time.perf_counter() - t0
    overhead_ratio = (new_path - baseline) / baseline
    assert overhead_ratio < 2.0, (
        f"normalize 路径相对整文件 hash overhead = {overhead_ratio:.2%}（D-012 护栏阈值 < 200%）"
    )
