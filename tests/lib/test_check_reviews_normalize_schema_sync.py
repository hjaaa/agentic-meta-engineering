"""F-001 schema-sync 回归测试：_NORMALIZE_TASK_FIELDS ⊆ schema.required_fields。

当 context/team/engineering-spec/task-frontmatter-schema.yaml 新增 dev 期演进字段，
而 _NORMALIZE_TASK_FIELDS 白名单未同步更新时，此测试会 fail，提示工程师补全白名单。

来源：requirements/REQ-2026-013/artifacts/detailed-design.md §4.1
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

# 注入 scripts/lib 到 path（与 test_check_reviews_r001_phase_typo 一致）
_LIB_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from check_reviews import _NORMALIZE_TASK_FIELDS  # noqa: E402


def test_normalize_whitelist_matches_schema_evolving_fields():
    """schema 加新 dev 期演进字段而白名单未同步 → fail。

    断言：_NORMALIZE_TASK_FIELDS ⊆ schema.required_fields
    （所有需要 normalize 的字段必须在 schema 中有声明，确保白名单不引用幻影字段）。
    """
    schema_path = "context/team/engineering-spec/task-frontmatter-schema.yaml"
    with open(schema_path, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    required = set(schema["required_fields"])
    assert _NORMALIZE_TASK_FIELDS.issubset(required), (
        f"_NORMALIZE_TASK_FIELDS={_NORMALIZE_TASK_FIELDS} 不是 schema.required_fields 子集"
        f"（schema.required_fields={required}）。"
        "请检查 task-frontmatter-schema.yaml 是否新增了 dev 期演进字段但 _NORMALIZE_TASK_FIELDS 未同步。"
    )
