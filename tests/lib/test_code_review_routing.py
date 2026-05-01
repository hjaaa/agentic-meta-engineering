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
        from scripts.lib.code_review_routing import RoutingPlan
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
# T6: non-pty 场景（stdin 是 pipe → 退码 2 + stderr 含退码 2 模板）
# ---------------------------------------------------------------------------

class TestNonTtyRejection:
    """T6: stdin 不是 tty 时，进程退码 2，stderr 含 §6 退码 2 模板关键词。"""

    def test_given_pipe_stdin_then_exit_code_2_and_stderr_contains_non_tty_message(
        self, tmp_path: Path
    ):
        repo, base_sha, head_sha = _setup_test_repo(tmp_path)
        argv = _build_argv(base_sha, head_sha)

        # 通过 subprocess 以 pipe 方式调用（stdin 非 tty）
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.lib.code_review_routing"] + argv,
            stdin=subprocess.PIPE,
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=_subprocess_env(repo),
        )
        assert proc.returncode == 2, f"期望退码 2，实际 {proc.returncode}\nstderr: {proc.stderr}"
        assert "非 tty" in proc.stderr or "tty" in proc.stderr.lower(), (
            f"stderr 应含 tty 相关提示，实际: {proc.stderr!r}"
        )


# ---------------------------------------------------------------------------
# T1-T5: pty 集成测试（真实 tty，模拟用户键盘输入）
# ---------------------------------------------------------------------------

# pty 仅在 Unix 系统可用
pytestmark_pty = pytest.mark.skipif(
    sys.platform == "win32", reason="pty 仅在 Unix 系统可用"
)


def _run_with_pty(
    repo: Path,
    argv: list[str],
    user_input: str,
    timeout: float = 10.0,
) -> tuple[int, str, str]:
    """使用 pty.openpty() 启动子进程，向 master 端写模拟用户输入。

    返回 (returncode, stdout_text, stderr_text)。
    使用 pty 而非 pipe 是因为 _check_tty() 严格校验 sys.stdin.isatty()，
    只有真实 pty 才能通过该校验。
    """
    import pty
    import select
    import signal

    master_fd, slave_fd = pty.openpty()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "scripts.lib.code_review_routing"] + argv,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=subprocess.PIPE,
            cwd=str(repo),
            close_fds=True,
            env=_subprocess_env(repo),
        )
        # slave_fd 已传给子进程，父进程关闭以避免阻塞
        os.close(slave_fd)
        slave_fd = -1

        # 小延迟等待子进程展示提示符
        import time
        time.sleep(0.5)

        # 写入用户输入到 master 端（带 \n 模拟回车）
        os.write(master_fd, user_input.encode())

        # 读取 master 端输出，直到进程结束
        stdout_chunks: list[bytes] = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                rlist, _, _ = select.select([master_fd], [], [], 0.2)
                if rlist:
                    chunk = os.read(master_fd, 4096)
                    if chunk:
                        stdout_chunks.append(chunk)
            except OSError:
                break
            if proc.poll() is not None:
                # 进程已结束，再读一次确保缓冲区清空
                try:
                    rlist, _, _ = select.select([master_fd], [], [], 0.2)
                    if rlist:
                        chunk = os.read(master_fd, 4096)
                        if chunk:
                            stdout_chunks.append(chunk)
                except OSError:
                    pass
                break

        if proc.poll() is None:
            proc.kill()
        proc.wait()

        stdout_text = b"".join(stdout_chunks).decode(errors="replace")
        _, stderr_bytes = proc.communicate(timeout=2) if proc.stderr else (None, b"")
        stderr_text = (stderr_bytes or b"").decode(errors="replace")
        return proc.returncode, stdout_text, stderr_text

    finally:
        os.close(master_fd)
        if slave_fd != -1:
            os.close(slave_fd)


@pytestmark_pty
class TestPtyIntegration:
    """T1-T5: pty 集成测试，验证 4 档热键 + abort 场景。"""

    def should_write_accept_decision_when_user_presses_enter(self, tmp_path: Path):
        """T1: 直接回车 → .review-scope.json 中 decision=accept，退码 0。"""
        repo, base_sha, head_sha = _setup_test_repo(tmp_path)
        argv = _build_argv(base_sha, head_sha)

        returncode, stdout, stderr = _run_with_pty(repo, argv, "\n")

        assert returncode == 0, f"期望退码 0，实际 {returncode}\nstdout: {stdout}\nstderr: {stderr}"
        scope_file = repo / ".review-scope.json"
        assert scope_file.exists(), ".review-scope.json 应被写入"
        import json
        scope = json.loads(scope_file.read_text(encoding="utf-8"))
        assert scope["routing_decision"]["decision"] == "accept", (
            f"期望 decision=accept，实际: {scope['routing_decision']['decision']}"
        )

    def should_write_all_decision_when_user_presses_a(self, tmp_path: Path):
        """T2: 输入 'a' → decision=all，final_route 包含全 8 个 checker。"""
        repo, base_sha, head_sha = _setup_test_repo(tmp_path)
        argv = _build_argv(base_sha, head_sha)

        returncode, stdout, stderr = _run_with_pty(repo, argv, "a\n")

        assert returncode == 0, f"期望退码 0，实际 {returncode}\nstderr: {stderr}"
        import json
        scope = json.loads((repo / ".review-scope.json").read_text(encoding="utf-8"))
        assert scope["routing_decision"]["decision"] == "all"
        assert set(scope["checker_route"]) == set(ALL_CHECKERS)

    def should_force_keep_must_when_user_picks_custom_subset(self, tmp_path: Path):
        """T3: 输入 '1' → decision=custom，security-checker (must) 强制保留。"""
        repo, base_sha, head_sha = _setup_test_repo(tmp_path)
        argv = _build_argv(base_sha, head_sha)

        returncode, stdout, stderr = _run_with_pty(repo, argv, "1\n")

        assert returncode == 0, f"期望退码 0，实际 {returncode}\nstdout: {stdout}\nstderr: {stderr}"
        import json
        scope = json.loads((repo / ".review-scope.json").read_text(encoding="utf-8"))
        assert scope["routing_decision"]["decision"] == "custom"
        # security-checker 是 must，必须在 final_route
        assert "security-checker" in scope["checker_route"]

    def should_exit_5_with_audit_when_user_presses_q(self, tmp_path: Path):
        """T4: 输入 'q' → 退码 5，stdout 含 §6 取消提示，audit 含 '用户主动取消'。"""
        repo, base_sha, head_sha = _setup_test_repo(tmp_path)
        argv = _build_argv(base_sha, head_sha)

        returncode, stdout, stderr = _run_with_pty(repo, argv, "q\n")

        assert returncode == 5, f"期望退码 5，实际 {returncode}\nstdout: {stdout}\nstderr: {stderr}"
        # audit 应含 "用户主动取消"
        process_txt = repo / "requirements" / "REQ-2099-001" / "process.txt"
        assert process_txt.exists(), "process.txt 应存在"
        content = process_txt.read_text(encoding="utf-8")
        assert "用户主动取消" in content, f"process.txt 应含 '用户主动取消'，实际: {content!r}"

    def should_exit_5_with_audit_when_three_invalid_inputs(self, tmp_path: Path):
        """T5: 连续 3 次无效输入 → 退码 5，audit 含 '连续 3 次无效输入'。"""
        repo, base_sha, head_sha = _setup_test_repo(tmp_path)
        argv = _build_argv(base_sha, head_sha)

        # 3 次无效输入
        returncode, stdout, stderr = _run_with_pty(repo, argv, "xxx\nyyy\nzzz\n")

        assert returncode == 5, f"期望退码 5，实际 {returncode}\nstdout: {stdout}\nstderr: {stderr}"
        process_txt = repo / "requirements" / "REQ-2099-001" / "process.txt"
        assert process_txt.exists(), "process.txt 应存在"
        content = process_txt.read_text(encoding="utf-8")
        assert "连续 3 次无效输入" in content, (
            f"process.txt 应含 '连续 3 次无效输入'，实际: {content!r}"
        )
