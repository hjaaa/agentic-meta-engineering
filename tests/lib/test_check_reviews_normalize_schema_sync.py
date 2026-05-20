"""F-001 schema-sync 回归测试：_NORMALIZE_TASK_FIELDS ⊆ schema 已知字段（fields 段 keys）。

防护方向（单向）：白名单不引用 schema 不存在的"幻影字段"。若有人误把
`statys` 这种拼写错误或已废弃字段塞进 _NORMALIZE_TASK_FIELDS，此测试 fail。

**契约调整（20260519-context-usage-report follow-up）**：
原契约 `_NORMALIZE_TASK_FIELDS ⊆ schema.required_fields` 过严——`review_report` 是
dev 期演进字段（done 时填），但因兼容历史 task.md 未列入 `required_fields`，导致
白名单加入 `review_report` 时测试失败。新契约改为：
`_NORMALIZE_TASK_FIELDS ⊆ schema.fields.keys()`——只要字段在 fields 段下有声明
即可，不强求 required。

**不防**反向：schema 新增 dev 期演进字段但白名单漏更新（codex round-3 P2 指出）。
此方向无法在测试层自动检测，因为 schema 不显式标记"哪些字段属于 dev evolving"
（D-007 ADR 评估后认为：在 schema 中加 dev_evolving_fields 子集会让 hot-path
check_reviews 必须 load yaml，且引入两文件解耦风险，得不偿失）。责任落在
**D-007 ADR 的 contractual obligation**——评审 schema 升级 PR 时必须人工查白名单
同步，由 `_NORMALIZE_TASK_FIELDS = {"status", "updated_at", "review_report"}` 旁
注释 `# 来源：task-frontmatter-schema.yaml` 触发 reviewer 检查清单。

来源：requirements/REQ-2026-013/artifacts/detailed-design.md §4.1 +
      requirements/REQ-2026-013/notes.md (D-007 ADR) +
      requirements/20260519-context-usage-report/notes.md (review_report follow-up)
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]

# 注入 scripts/lib 到 path（与 test_check_reviews_r001_phase_typo 一致）
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from check_reviews import _NORMALIZE_TASK_FIELDS  # noqa: E402


def test_normalize_whitelist_matches_schema_known_fields():
    """断言：_NORMALIZE_TASK_FIELDS ⊆ schema.fields.keys()（单向）。

    防"白名单引用幻影字段"。**不防**"schema 加新 evolving 字段漏白名单"——
    见模块 docstring 中 codex round-3 P2 + D-007 ADR 的责任划分。

    契约范围：fields 段下所有声明字段（含 required=false 的 dev 期演进字段如
    review_report），不再强求 required_fields 子集。
    """
    schema_path = _REPO_ROOT / "context" / "team" / "engineering-spec" / "task-frontmatter-schema.yaml"
    with open(schema_path, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    known_fields = set(schema["fields"].keys())
    assert _NORMALIZE_TASK_FIELDS.issubset(known_fields), (
        f"_NORMALIZE_TASK_FIELDS={_NORMALIZE_TASK_FIELDS} 不是 schema.fields 已知字段子集"
        f"（schema.fields={known_fields}）。"
        "请检查 task-frontmatter-schema.yaml 是否定义了对应字段。"
    )
