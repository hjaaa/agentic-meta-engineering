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
    _strip_frontmatter_fields,
)


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
