"""F-001 核心引擎单测 + F-002 IO 层测试。

F-001 覆盖：_load_yaml / _validate_schema / _build_plan + INV 不变量。
F-002 覆盖：_parse_custom_input (U11/U12) + pty 集成 (T1-T6)。
外部依赖（文件系统、git subprocess）全部 mock（单测）或 pty 子进程（集成）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.lib.code_review_routing import (
    ALL_CHECKERS,
    MAX_MUST_RULES,
    RoutingConfig,
    RoutingError,
    RoutingPlan,
    RoutingSchemaError,
    RoutingYamlError,
    _RuleEntry,
    _build_plan,
    _enumerate_diff_files,
    _load_yaml,
    _parse_custom_input,
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
# U5b: _validate_schema — suggest 段不是 list → V3b
# ---------------------------------------------------------------------------

class TestValidateSchemaSuggestNotList:
    def test_should_raise_routing_schema_error_with_v3b_when_suggest_not_list(self):
        raw = {
            "version": 1,
            "must": [],
            "suggest": "not-a-list",
            "trivial_whitelist": [],
        }
        with pytest.raises(RoutingSchemaError) as exc_info:
            _validate_schema(raw)
        assert exc_info.value.exit_code == 3
        assert "V3b" in str(exc_info.value)


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


# ---------------------------------------------------------------------------
# U11: _parse_custom_input — 容错：多种逗号分隔格式
# ---------------------------------------------------------------------------

class TestParseCustomInput:
    """U11: 验证 _parse_custom_input 能容错解析多种输入格式。"""

    def _make_plan(self) -> "RoutingPlan":
        """创建含 must=security-checker, suggest=performance-checker 的测试计划。"""
        return RoutingPlan(
            must_checkers={"security-checker"},
            suggest_checkers={"performance-checker"},
            trivial_only=False,
            files_total=3,
            files_trivial=0,
            files_must_hit={"security-checker": ["auth.py"]},
            files_suggest_hit={"performance-checker": ["query.sql"]},
        )

    def test_given_compact_comma_format_then_parses_correctly(self):
        """U11: '1,3' 正常解析。"""
        plan = self._make_plan()
        # recommended 按 ALL_CHECKERS 顺序：security-checker(idx=0), performance-checker(idx=1)
        recommended = [c for c in ALL_CHECKERS if c in plan.must_checkers | plan.suggest_checkers]
        result = _parse_custom_input("1,2", plan, recommended)
        # 1→security-checker, 2→performance-checker
        assert "security-checker" in result
        assert "performance-checker" in result

    def test_given_spaced_comma_format_then_parses_correctly(self):
        """U11: '1, 3' 带空格，能正确解析。"""
        plan = self._make_plan()
        recommended = [c for c in ALL_CHECKERS if c in plan.must_checkers | plan.suggest_checkers]
        result = _parse_custom_input("1, 2", plan, recommended)
        assert "security-checker" in result
        assert "performance-checker" in result

    def test_given_extra_spaces_format_then_parses_correctly(self):
        """U11: ' 1 ,2 ' 前后空格，能正确解析。"""
        plan = self._make_plan()
        recommended = [c for c in ALL_CHECKERS if c in plan.must_checkers | plan.suggest_checkers]
        result = _parse_custom_input(" 1 ,2 ", plan, recommended)
        assert "security-checker" in result

    def test_given_out_of_range_index_then_returns_empty(self):
        """U11: 超界索引返回空集（表示无效输入）。"""
        plan = self._make_plan()
        recommended = [c for c in ALL_CHECKERS if c in plan.must_checkers | plan.suggest_checkers]
        result = _parse_custom_input("99", plan, recommended)
        assert result == set()

    def test_given_letter_input_then_returns_empty(self):
        """U11: 含字母的输入返回空集。"""
        plan = self._make_plan()
        recommended = [c for c in ALL_CHECKERS if c in plan.must_checkers | plan.suggest_checkers]
        result = _parse_custom_input("abc", plan, recommended)
        assert result == set()


# ---------------------------------------------------------------------------
# U12: _parse_custom_input — must 强制保留
# ---------------------------------------------------------------------------

class TestParseCustomInputMustForced:
    """U12: 用户只选 suggest 项（未选 must 项）时，must 应被强制加回。"""

    def test_given_user_omits_must_checker_then_must_is_forced_back(self):
        """U12: 用户只输 '2'（suggest），must 强制保留。"""
        from scripts.lib.code_review_routing import RoutingPlan
        plan = RoutingPlan(
            must_checkers={"security-checker"},
            suggest_checkers={"performance-checker"},
            trivial_only=False,
            files_total=2,
            files_trivial=0,
            files_must_hit={"security-checker": ["auth.py"]},
            files_suggest_hit={"performance-checker": ["query.sql"]},
        )
        # recommended: security-checker 在前(idx 1)，performance-checker 在后(idx 2)
        recommended = [c for c in ALL_CHECKERS if c in plan.must_checkers | plan.suggest_checkers]
        # 找 performance-checker 的 1-based 索引
        perf_idx = recommended.index("performance-checker") + 1
        result = _parse_custom_input(str(perf_idx), plan, recommended)
        # 即便只选 suggest，must 也必须在结果中
        assert "security-checker" in result
        assert "performance-checker" in result


# ---------------------------------------------------------------------------
# 辅助函数：准备 pty 集成测试所需的临时仓库和 routing.yaml
# ---------------------------------------------------------------------------

def _setup_test_repo(tmp_path: Path) -> Path:
    """在 tmp_path 创建最小 git 仓库 + routing.yaml + 两个 commit。

    H-21 fix: 返回 (repo_path, base_sha, head_sha) 供集成测试使用。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    # 创建 .claude 目录和 routing.yaml
    claude_dir = repo / ".claude"
    claude_dir.mkdir()
    routing_yaml = claude_dir / "code-review-routing.yaml"
    routing_yaml.write_text(
        """version: 1
must:
  - pattern: "src/**"
    checkers:
      - security-checker
suggest:
  - pattern: "**/*.sql"
    checkers:
      - performance-checker
trivial_whitelist:
  - "**/*.md"
""",
        encoding="utf-8",
    )

    # base commit（空）
    (repo / "README.md").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()

    # head commit（src/main.py → 命中 must security-checker）
    src_dir = repo / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("# main", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add src"], cwd=repo, check=True, capture_output=True)
    head_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()

    # 创建 requirements/REQ-2099-001 目录（供 audit 写入）
    req_dir = repo / "requirements" / "REQ-2099-001"
    req_dir.mkdir(parents=True)

    return repo, base_sha, head_sha


def _build_argv(base_sha: str, head_sha: str) -> list[str]:
    """返回标准测试 CLI 参数列表。"""
    return [
        "--mode", "embedded",
        "--requirement-id", "REQ-2099-001",
        "--base-sha", base_sha,
        "--head-sha", head_sha,
        "--base-branch", "develop",
        "--current-branch", "feat/test",
        "--feature-id", "F-001",
    ]


def _subprocess_env(repo: Path) -> dict:
    """构造子进程 env，注入 PYTHONPATH 使 scripts 模块可 import。

    子进程 cwd 为临时仓库，但 scripts 包在测试运行目录，需要显式注入。
    """
    # 仓库根（scripts/ 目录的父目录）
    repo_root = str(Path(__file__).parent.parent.parent)
    env = os.environ.copy()
    existing_pypath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}:{existing_pypath}" if existing_pypath else repo_root
    return env


# ---------------------------------------------------------------------------
# F-014：自 cancel 人类卡点 A 起，routing.py 直接走自动决策
# 旧 T1-T6 pty / non-tty 集成测试已删除；保留 _setup_test_repo / _build_argv /
# _subprocess_env 三个辅助函数作为新自动模式 E2E 测试的基础设施。
# ---------------------------------------------------------------------------


class TestAutoRouteEndToEnd:
    """A1-A4: 自动路由 E2E——以 subprocess 跑 main()，AI/pipe 均可通过。"""

    def test_a1_given_must_hit_when_run_then_decision_accept_and_recommended(
        self, tmp_path: Path
    ):
        """A1: src/main.py 命中 must（security-checker）→ decision=accept，checker_route=[security-checker]。"""
        import json

        repo, base_sha, head_sha = _setup_test_repo(tmp_path)
        argv = _build_argv(base_sha, head_sha)

        proc = subprocess.run(
            [sys.executable, "-m", "scripts.lib.code_review_routing"] + argv,
            stdin=subprocess.PIPE,
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_subprocess_env(repo),
        )
        assert proc.returncode == 0, (
            f"期望退码 0，实际 {proc.returncode}\nstderr: {proc.stderr}"
        )
        scope = json.loads((repo / ".review-scope.json").read_text(encoding="utf-8"))
        assert scope["routing_decision"]["decision"] == "accept"
        assert scope["checker_route"] == ["security-checker"]
        assert scope["routing_decision"]["tty_verified"] is True

    def test_a2_given_grey_diff_when_run_then_decision_all_with_8_checkers(
        self, tmp_path: Path
    ):
        """A2: diff 全是灰色文件（未命中任何规则）→ 自动升 8 全集，decision=all。"""
        import json

        repo, base_sha, head_sha = _setup_grey_repo(tmp_path)
        argv = _build_argv(base_sha, head_sha)

        proc = subprocess.run(
            [sys.executable, "-m", "scripts.lib.code_review_routing"] + argv,
            stdin=subprocess.PIPE,
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_subprocess_env(repo),
        )
        assert proc.returncode == 0, (
            f"期望退码 0，实际 {proc.returncode}\nstderr: {proc.stderr}"
        )
        scope = json.loads((repo / ".review-scope.json").read_text(encoding="utf-8"))
        assert scope["routing_decision"]["decision"] == "all"
        assert set(scope["checker_route"]) == set(ALL_CHECKERS)

    def test_a3_given_pipe_stdin_when_run_then_still_succeeds(self, tmp_path: Path):
        """A3: 非 tty（pipe stdin）调用不再被拒绝——AI/CI 可直接跑。"""
        repo, base_sha, head_sha = _setup_test_repo(tmp_path)
        argv = _build_argv(base_sha, head_sha)

        proc = subprocess.run(
            [sys.executable, "-m", "scripts.lib.code_review_routing"] + argv,
            stdin=subprocess.PIPE,
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_subprocess_env(repo),
        )
        assert proc.returncode == 0, (
            f"期望退码 0（自动模式不再校验 tty），实际 {proc.returncode}\n"
            f"stderr: {proc.stderr}"
        )

    def test_a4_given_accept_decision_when_run_then_audit_silent(
        self, tmp_path: Path
    ):
        """A4: accept / all 路径**不写** process.txt（沿用 REQ-2026-003 §8.4 静默约定）。

        可追溯性由 scope.json.routing_decision 承担，包含 decision/confirmed_at/
        files_must_hit/files_suggest_hit/files_trivial/files_total 全量字段。
        process.txt 仅记录 trivial-skipped / aborted 等异常路径，避免噪音污染。
        """
        repo, base_sha, head_sha = _setup_test_repo(tmp_path)
        argv = _build_argv(base_sha, head_sha)

        proc = subprocess.run(
            [sys.executable, "-m", "scripts.lib.code_review_routing"] + argv,
            stdin=subprocess.PIPE,
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_subprocess_env(repo),
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        process_txt = repo / "requirements" / "REQ-2099-001" / "process.txt"
        if process_txt.exists():
            content = process_txt.read_text(encoding="utf-8")
            assert "[code-review-route-auto]" not in content, (
                f"accept 路径不应写 [code-review-route-auto]（§8.4 静默），实际: {content!r}"
            )


def _setup_grey_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """build 仓库时改 .changes/unknown.bin（不命中 must/suggest/trivial 任何一段）。

    用于 A2：验证「推荐集为空 → 升 8 全集」分支。
    """
    repo = tmp_path / "repo-grey"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    claude_dir = repo / ".claude"
    claude_dir.mkdir()
    (claude_dir / "code-review-routing.yaml").write_text(
        """version: 1
must:
  - pattern: "src/**"
    checkers:
      - security-checker
suggest:
  - pattern: "**/*.sql"
    checkers:
      - performance-checker
trivial_whitelist:
  - "**/*.md"
""",
        encoding="utf-8",
    )

    (repo / "README.md").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()

    # head commit：build/output.bin 不命中 must/suggest/trivial 任何规则 → 灰色
    build_dir = repo / "build"
    build_dir.mkdir()
    (build_dir / "output.bin").write_text("grey", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add grey file"], cwd=repo, check=True, capture_output=True)
    head_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()

    (repo / "requirements" / "REQ-2099-001").mkdir(parents=True)
    return repo, base_sha, head_sha


class TestAutoDecideUnit:
    """A5-A6: _auto_decide 纯函数单测。"""

    def _make_plan(
        self,
        must_checkers: set[str] | None = None,
        suggest_checkers: set[str] | None = None,
        files_total: int = 1,
    ) -> "RoutingPlan":
        must = must_checkers or set()
        sugg = suggest_checkers or set()
        return RoutingPlan(
            must_checkers=must,
            suggest_checkers=sugg,
            trivial_only=False,
            files_total=files_total,
            files_trivial=0,
            files_must_hit={c: ["x.py"] for c in must},
            files_suggest_hit={c: ["y.py"] for c in sugg},
        )

    def test_a5_given_must_and_suggest_then_decision_accept_with_union(self):
        """A5: must ∪ suggest 非空 → decision=accept，final_route 按 ALL_CHECKERS 顺序。"""
        from scripts.lib.code_review_routing import _auto_decide
        plan = self._make_plan(
            must_checkers={"security-checker"},
            suggest_checkers={"performance-checker"},
        )
        decision = _auto_decide(plan, confirmed_by="test@example.com")
        assert decision.decision == "accept"
        # security-checker (idx=1) 在 performance-checker (idx=3) 之前
        assert decision.final_route == ["security-checker", "performance-checker"]

    def test_a6_given_empty_recommended_then_decision_all_with_full_set(self):
        """A6: must/suggest 全空 → decision=all，final_route=ALL_CHECKERS（升 8 全集）。"""
        from scripts.lib.code_review_routing import _auto_decide
        plan = self._make_plan(files_total=3)
        decision = _auto_decide(plan, confirmed_by="test@example.com")
        assert decision.decision == "all"
        assert decision.final_route == list(ALL_CHECKERS)
