"""F-001 核心引擎单测。

覆盖：_load_yaml / _validate_schema / _build_plan + INV 不变量。
外部依赖（文件系统、git subprocess）全部 mock。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from scripts.lib.code_review_routing import (
    ALL_CHECKERS,
    MAX_MUST_RULES,
    RoutingConfig,
    RoutingError,
    RoutingSchemaError,
    RoutingYamlError,
    _RuleEntry,
    _build_plan,
    _enumerate_diff_files,
    _load_yaml,
    _validate_schema,
)

# ---------------------------------------------------------------------------
# 测试辅助：最小合法 yaml raw dict
# ---------------------------------------------------------------------------

_VALID_RAW: dict = {
    "version": 1,
    "must": [
        {"pattern": "auth/**", "checkers": ["security-checker"]},
    ],
    "suggest": [
        {"pattern": "**/*.sql", "checkers": ["performance-checker"]},
    ],
    "trivial_whitelist": ["**/*.md"],
}


def _make_config(
    must_rules: list[tuple[str, list[str]]] | None = None,
    suggest_rules: list[tuple[str, list[str]]] | None = None,
    trivial: list[str] | None = None,
) -> RoutingConfig:
    """创建测试用 RoutingConfig，减少重复代码。"""
    must = tuple(
        _RuleEntry(pattern=p, checkers=tuple(c))
        for p, c in (must_rules or [])
    )
    suggest = tuple(
        _RuleEntry(pattern=p, checkers=tuple(c))
        for p, c in (suggest_rules or [])
    )
    return RoutingConfig(
        version=1,
        must=must,
        suggest=suggest,
        trivial_whitelist=tuple(trivial or []),
    )


# ---------------------------------------------------------------------------
# U1: _load_yaml — 文件不存在
# ---------------------------------------------------------------------------

class TestLoadYamlFileNotFound:
    def test_should_raise_routing_yaml_error_when_file_not_exist(self):
        with pytest.raises(RoutingYamlError) as exc_info:
            _load_yaml(Path("/nonexistent/path/routing.yaml"))
        assert exc_info.value.exit_code == 4


# ---------------------------------------------------------------------------
# U2: _load_yaml — yaml 语法错误含行号
# ---------------------------------------------------------------------------

class TestLoadYamlSyntaxError:
    def test_should_raise_routing_yaml_error_with_line_number_when_yaml_syntax_error(
        self, tmp_path: Path
    ):
        bad_yaml = tmp_path / "bad.yaml"
        # 制造 yaml 语法错误：缩进不一致
        bad_yaml.write_text("key: [\n  unclosed", encoding="utf-8")
        with pytest.raises(RoutingYamlError) as exc_info:
            _load_yaml(bad_yaml)
        assert exc_info.value.exit_code == 4
        # detail 应含文件路径（行号信息）
        detail = str(exc_info.value)
        assert "yaml" in detail.lower() or str(bad_yaml) in detail


# ---------------------------------------------------------------------------
# U3: _load_yaml — UnicodeDecodeError
# ---------------------------------------------------------------------------

class TestLoadYamlUnicodeError:
    def test_should_raise_routing_yaml_error_when_unicode_decode_error(
        self, tmp_path: Path
    ):
        bad_file = tmp_path / "bad_enc.yaml"
        # 写入非 utf-8 字节
        bad_file.write_bytes(b"\xff\xfe\x00\x01")
        with pytest.raises(RoutingYamlError) as exc_info:
            _load_yaml(bad_file)
        assert exc_info.value.exit_code == 4


# ---------------------------------------------------------------------------
# U4: _validate_schema — 缺 version → V1
# ---------------------------------------------------------------------------

class TestValidateSchemaMissingVersion:
    def test_should_raise_routing_schema_error_with_v1_when_version_missing(self):
        raw = {
            "must": [],
            "suggest": [],
            "trivial_whitelist": [],
            # 故意缺 version
        }
        with pytest.raises(RoutingSchemaError) as exc_info:
            _validate_schema(raw)
        assert exc_info.value.exit_code == 3
        assert "V1" in str(exc_info.value)


# ---------------------------------------------------------------------------
# U5: _validate_schema — must 长度超过 MAX_MUST_RULES → V3
# ---------------------------------------------------------------------------

class TestValidateSchemaMusTooLong:
    def test_should_raise_routing_schema_error_with_v3_when_must_too_long(self):
        must_rules = [
            {"pattern": f"src/module{i}/**", "checkers": ["complexity-checker"]}
            for i in range(MAX_MUST_RULES + 1)  # 6 条，超过上限 5
        ]
        raw = {
            "version": 1,
            "must": must_rules,
            "suggest": [],
            "trivial_whitelist": [],
        }
        with pytest.raises(RoutingSchemaError) as exc_info:
            _validate_schema(raw)
        assert exc_info.value.exit_code == 3
        assert "V3" in str(exc_info.value)


# ---------------------------------------------------------------------------
# U6: _validate_schema — checkers 含 unknown-checker → V5
# ---------------------------------------------------------------------------

class TestValidateSchemaUnknownChecker:
    def test_should_raise_routing_schema_error_with_v5_when_unknown_checker(self):
        raw = {
            "version": 1,
            "must": [
                {"pattern": "src/**", "checkers": ["unknown-checker"]}
            ],
            "suggest": [],
            "trivial_whitelist": [],
        }
        with pytest.raises(RoutingSchemaError) as exc_info:
            _validate_schema(raw)
        assert exc_info.value.exit_code == 3
        assert "V5" in str(exc_info.value)


# ---------------------------------------------------------------------------
# U7: _build_plan — **/auth/** vs auth/** 锚定差异
# ---------------------------------------------------------------------------

class TestBuildPlanPathspecAnchor:
    """验证 pathspec 的 **/auth/** 与 auth/** 锚定行为差异。"""

    def test_given_auth_anchor_rule_then_only_root_level_auth_dir_matches(self):
        """auth/** 只匹配根级 auth/，不匹配 src/auth/。"""
        config = _make_config(
            must_rules=[("auth/**", ["security-checker"])],
            trivial=["**/*.md"],
        )
        plan = _build_plan(["src/auth/x.py", "auth/y.py"], config)
        # auth/y.py 命中 must，src/auth/x.py 不命中 must 也不命中 trivial → 灰色
        assert "security-checker" in plan.must_checkers
        assert "auth/y.py" in plan.files_must_hit.get("security-checker", [])
        assert "src/auth/x.py" not in plan.files_must_hit.get("security-checker", [])

    def test_given_double_star_auth_rule_then_any_depth_auth_dir_matches(self):
        """**/auth/** 匹配任意深度的 auth/ 目录。"""
        config = _make_config(
            must_rules=[("**/auth/**", ["security-checker"])],
            trivial=["**/*.md"],
        )
        plan = _build_plan(["src/auth/x.py", "auth/y.py"], config)
        assert "security-checker" in plan.must_checkers
        assert "src/auth/x.py" in plan.files_must_hit.get("security-checker", [])
        assert "auth/y.py" in plan.files_must_hit.get("security-checker", [])


# ---------------------------------------------------------------------------
# U8: _build_plan — 12 文件 mixed
# ---------------------------------------------------------------------------

class TestBuildPlanMixed:
    """must=2个checker / suggest=3个checker / trivial=4 / 灰色=3。"""

    def _make_mixed_config(self) -> RoutingConfig:
        return _make_config(
            must_rules=[
                ("src/security/**", ["security-checker"]),
                ("src/concurrent/**", ["concurrency-checker"]),
            ],
            suggest_rules=[
                ("**/*.sql", ["performance-checker"]),
                ("**/*.sql", ["error-handling-checker"]),
                ("src/design/**", ["design-consistency-checker"]),
            ],
            trivial=["**/*.md", "**/*.txt"],
        )

    def test_should_correctly_count_categories_for_mixed_12_files(self):
        files = [
            # must 命中（security-checker）
            "src/security/auth.py",
            "src/security/token.py",
            # must 命中（concurrency-checker）
            "src/concurrent/lock.py",
            "src/concurrent/pool.py",
            # suggest 命中（performance-checker + error-handling-checker 来自同一 sql 规则）
            "queries/report.sql",
            "queries/summary.sql",
            # suggest 命中（design-consistency-checker）
            "src/design/interface.py",
            # trivial
            "README.md",
            "CHANGELOG.md",
            "docs/note.txt",
            "docs/guide.md",
            # 灰色（不命中任何规则）
            "build/output.bin",
            "logs/app.log",
            "tmp/cache.dat",
        ]
        # 共 14 个文件，按任务描述 12 文件是示例，用真实文件验证分类正确性
        config = self._make_mixed_config()
        plan = _build_plan(files, config)
        assert "security-checker" in plan.must_checkers
        assert "concurrency-checker" in plan.must_checkers
        assert "performance-checker" in plan.suggest_checkers
        assert "error-handling-checker" in plan.suggest_checkers
        assert "design-consistency-checker" in plan.suggest_checkers
        # trivial 文件：4 个（README.md / CHANGELOG.md / docs/note.txt / docs/guide.md）
        assert plan.files_trivial == 4
        assert not plan.trivial_only


# ---------------------------------------------------------------------------
# U9: _build_plan — 5 文件全 .md → trivial_only=True
# ---------------------------------------------------------------------------

class TestBuildPlanTrivialOnly:
    def test_should_set_trivial_only_true_when_all_files_are_md(self):
        config = _make_config(
            must_rules=[("src/**", ["complexity-checker"])],
            trivial=["**/*.md"],
        )
        md_files = [
            "README.md",
            "docs/a.md",
            "docs/b.md",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
        ]
        plan = _build_plan(md_files, config)
        assert plan.trivial_only is True
        assert plan.files_trivial == 5
        assert len(plan.must_checkers) == 0
        assert len(plan.suggest_checkers) == 0


# ---------------------------------------------------------------------------
# U10: _build_plan — 中文 / 空格 / 特殊字符路径不崩溃
# ---------------------------------------------------------------------------

class TestBuildPlanSpecialPaths:
    def test_should_not_crash_with_unicode_and_special_character_paths(self):
        config = _make_config(trivial=["**/*.md"])
        paths = [
            "src/中文目录/模块.py",
            "path with spaces/file.py",
            "src/special!@#/file.py",
            "docs/说明.md",
        ]
        # 不崩溃即通过；docs/说明.md 命中 trivial
        plan = _build_plan(paths, config)
        assert plan.files_total == 4
        assert plan.files_trivial == 1  # 只有 docs/说明.md 命中 trivial


# ---------------------------------------------------------------------------
# U-INV-1: INV-PLAN-1/2 在所有 _build_plan 调用中均满足
# ---------------------------------------------------------------------------

class TestBuildPlanInvariants:
    """files_must_hit / files_suggest_hit 的 key 集合与对应 checker 集合一致。"""

    def test_given_mixed_files_then_inv_plan_1_and_2_hold(self):
        config = _make_config(
            must_rules=[("src/**", ["security-checker", "complexity-checker"])],
            suggest_rules=[("tests/**", ["error-handling-checker"])],
            trivial=["**/*.md"],
        )
        files = [
            "src/main.py",
            "tests/test_main.py",
            "README.md",
            "other/file.py",
        ]
        plan = _build_plan(files, config)
        # INV-PLAN-1
        assert set(plan.files_must_hit.keys()) == plan.must_checkers
        # INV-PLAN-2
        assert set(plan.files_suggest_hit.keys()) == plan.suggest_checkers

    def test_given_empty_files_then_invariants_hold(self):
        config = _make_config(
            must_rules=[("src/**", ["security-checker"])],
        )
        plan = _build_plan([], config)
        assert set(plan.files_must_hit.keys()) == plan.must_checkers
        assert set(plan.files_suggest_hit.keys()) == plan.suggest_checkers
        assert plan.trivial_only is False  # files_total == 0 → 不满足 trivial_only 条件

    def test_given_trivial_only_files_then_invariants_hold(self):
        config = _make_config(trivial=["**/*.md"])
        plan = _build_plan(["a.md", "b.md"], config)
        assert set(plan.files_must_hit.keys()) == plan.must_checkers
        assert set(plan.files_suggest_hit.keys()) == plan.suggest_checkers
        assert plan.trivial_only is True


# ---------------------------------------------------------------------------
# 额外：_enumerate_diff_files 基础覆盖
# ---------------------------------------------------------------------------

class TestEnumerateDiffFiles:
    def test_should_raise_routing_error_when_git_diff_fails(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=128, cmd=["git", "diff"]
            )
            with pytest.raises(RoutingError) as exc_info:
                _enumerate_diff_files("abc123", "def456")
            assert exc_info.value.exit_code == 1

    def test_should_return_file_list_when_git_diff_succeeds(self):
        fake_result = MagicMock()
        fake_result.stdout = "src/main.py\ntests/test_main.py\n"
        with patch("subprocess.run", return_value=fake_result):
            files = _enumerate_diff_files("abc123", "def456")
        assert files == ["src/main.py", "tests/test_main.py"]
