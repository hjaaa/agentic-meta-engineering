"""F-004 benchmark：routing.py 在 50/200/2000 文件 diff 下的 P95 延迟。

CI 不强制（@pytest.mark.benchmark；CI 默认 `-m "not benchmark"` 跳过）。
本地跑：`pytest tests/benchmarks/test_routing_perf.py --benchmark-json=out.json -v`

B1: trivial-only 50 文件 → P95 < 100ms
B2: mixed 200 文件 → P95 < 200ms
B3: large 2000 文件 mixed → P95 < 200ms（边界，对应 requirement.md:73 上限）
"""
from __future__ import annotations

from typing import Any

import pytest

from scripts.lib.code_review_routing import (
    _build_plan,
    _load_yaml,
    _validate_schema,
    ROUTING_YAML_PATH,
    RoutingConfig,
)
# _compile_specs 通过 _build_plan 内部间接覆盖；不直接 import 避免 lint 误报


@pytest.fixture(scope="module")
def routing_config() -> RoutingConfig:
    """复用真 routing.yaml；冷启动单次加载放在 module fixture。"""
    try:
        return _validate_schema(_load_yaml(ROUTING_YAML_PATH))
    except Exception as exc:
        pytest.fail(f"routing.yaml 加载失败：{exc}（路径：{ROUTING_YAML_PATH}）")


@pytest.mark.benchmark
class TestRoutingPerf:
    def should_handle_trivial_only_50_files_under_100ms(
        self, benchmark: Any, routing_config: RoutingConfig
    ) -> None:
        """B1: 50 文件全 .md，trivial-only 路径，P95 < 100ms（含 yaml 加载冷启动等价）。

        全部为 .md，命中 trivial_whitelist 的 **/*.md 规则，
        不命中任何 must/suggest，plan.trivial_only 应为 True。
        """
        files = [f"docs/notes-{i}.md" for i in range(50)]
        result = benchmark(_build_plan, files, routing_config)
        # 断言：50 个 .md 文件应全部 trivial
        assert result.trivial_only is True, f"期望 trivial_only=True，实际 {result.trivial_only!r}"
        assert result.files_total == 50, f"期望 files_total=50，实际 {result.files_total}"
        assert result.files_trivial == 50, f"期望 files_trivial=50，实际 {result.files_trivial}"

    def should_handle_mixed_200_files_under_200ms(
        self, benchmark: Any, routing_config: RoutingConfig
    ) -> None:
        """B2: 200 文件混合，P95 < 200ms。

        文件组成：
          - 50 个 docs/*.md（trivial）
          - 命中 must Q1-1 的 scripts/lib/save_review.py
          - 命中 must Q1-2 的 scripts/gates/run.py
          - 命中 must Q1-3 的 .claude/commands/code-review.md
          - 命中 must Q1-4 的 .claude/skills/foo/SKILL.md
          - 145 个普通 src/*.py（灰色——不命中 must/suggest/trivial 白名单）
          合计 200 文件
        """
        files = (
            [f"docs/d{i}.md" for i in range(50)]          # trivial
            + ["scripts/lib/save_review.py"]               # must Q1-1
            + ["scripts/gates/run.py"]                     # must Q1-2
            + [".claude/commands/code-review.md"]          # must Q1-3
            + [".claude/skills/foo/SKILL.md"]              # must Q1-4
            + [f"src/feature-{i}/main.py" for i in range(146)]  # 灰色（50+4+146=200）
        )
        assert len(files) == 200, f"期望 200 文件，实际 {len(files)}"
        result = benchmark(_build_plan, files, routing_config)
        # 200 文件混合时 trivial_only=False（有 must 命中）
        assert result.trivial_only is False, f"期望 trivial_only=False，实际 {result.trivial_only!r}"
        # must_checkers 至少含 security-checker（save_review.py + gates 命中）
        assert "security-checker" in result.must_checkers, (
            f"期望 must_checkers 含 security-checker，实际 {result.must_checkers!r}"
        )

    def should_handle_large_2000_files_under_200ms(
        self, benchmark: Any, routing_config: RoutingConfig
    ) -> None:
        """B3: 2000 文件混合，P95 < 200ms（边界，对应 requirement.md:73 上限）。

        文件组成：
          - 500 个 docs/*.md（trivial）
          - 50 个 scripts/gates/g*.py（must Q1-2）
          - 50 个 .claude/skills/s*/SKILL.md（must Q1-4）
          - 1400 个 src/m*/file*.py（灰色，不命中任何规则）
          合计 2000 文件
        """
        files = (
            [f"docs/d{i}.md" for i in range(500)]
            + [f"scripts/gates/g{i}.py" for i in range(50)]
            + [f".claude/skills/s{i}/SKILL.md" for i in range(50)]
            + [f"src/m{i}/file{j}.py" for i in range(140) for j in range(10)]
        )
        assert len(files) == 2000, f"期望 2000 文件，实际 {len(files)}"
        result = benchmark(_build_plan, files, routing_config)
        # 有 must 命中（gates + SKILL.md），trivial_only=False
        assert result.trivial_only is False, f"期望 trivial_only=False，实际 {result.trivial_only!r}"
        assert result.files_total == 2000, f"期望 files_total=2000，实际 {result.files_total}"
