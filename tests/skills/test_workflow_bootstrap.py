"""F-002 · _bootstrap_requirement + _bootstrap_rollback + 拆出的 helper 测试。

从 tests/skills/test_workflow_commands.py 拆出（rev2 闭合 F-1 file-length）。

覆盖 features.json F-002 的 5 条 acceptance：
  AC1 成功路径：4 文件/目录全存在
  AC2 成功后当前分支 = feat/req-<id>
  AC3 mkdir 失败时 req_dir 不残留
  AC4 git checkout 失败时分支与目录全回滚
  AC5 rollback 自身 IOError 不抛，仅 ERROR 日志

外部依赖处理策略：
  - 不 mock 真 git：在 tmp_path 用 subprocess 起真 repo + 建 develop 分支，
    保证 _checkout_feature_branch / _bootstrap_rollback 切换链路真跑过去
  - 模板路径走真实 REPO_ROOT/.claude/skills/managing-requirement-lifecycle/templates/
    （本 feature 不动模板，复用真实文件最简单可靠）

pytest 命名规范：test_<场景>_when_<条件>_then_<期望>（CLAUDE.md §7）。
"""
from __future__ import annotations

import logging as logging_mod
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------- 路径注入 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import workflow_bootstrap as wb  # noqa: E402  bootstrap helper（F-002 主对象）
import workflow_run as wr  # noqa: E402  仅 _generate_req_id 等顶层入口
from run_state import read_events  # noqa: E402


# ============================================================================
# 模块级 git helper（rev2 F-12：从 _init_real_git_repo 内嵌闭包提升为模块级）
# ============================================================================

def _git(
    cmd: list[str],
    cwd: Path,
    *,
    check: bool = True,
    timeout: int = 10,
    **kwargs,
) -> subprocess.CompletedProcess:
    """统一封装 subprocess.run 调 git——cwd / capture / check / timeout 默认值。

    F-12：原 _init_real_git_repo 内闭包 _run 提升为模块级 _git，方便单测
    新增的 rollback rc!=0 路径用例（F-16）直接复用相同调用风格。
    """
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True,
        check=check, timeout=timeout, **kwargs,
    )


def _init_real_git_repo(tmp_path: Path) -> Path:
    """在 tmp_path 起一个真 git repo，配 user.name/email，建 develop 分支。

    F-002 测试基础设施——不 mock subprocess，让 _checkout_feature_branch /
    _bootstrap_rollback 的 git 子进程调用真实落到 tmp_path 上，杜绝 mock 偏离。

    返回：repo_root（与 tmp_path 相同，方便链式调用）。
    """
    # 0. 镜像 tmp_repo fixture：建 requirements/ 等顶层目录
    (tmp_path / "requirements").mkdir(exist_ok=True)
    (tmp_path / "runs").mkdir(exist_ok=True)

    _git(["git", "init", "-q"], tmp_path)
    _git(["git", "config", "user.email", "f002@test.local"], tmp_path)
    _git(["git", "config", "user.name", "F-002 Test"], tmp_path)
    _git(["git", "config", "commit.gpgsign", "false"], tmp_path)
    # 建初始 commit 作为 develop 锚点
    (tmp_path / "README.md").write_text("F-002 test repo\n", encoding="utf-8")
    _git(["git", "add", "README.md"], tmp_path)
    _git(["git", "commit", "-q", "-m", "init"], tmp_path)
    # 切到 develop（rename 当前默认分支即可，避免依赖具体默认分支名）
    _git(["git", "branch", "-M", "develop"], tmp_path)
    return tmp_path


@pytest.fixture()
def real_git_repo(tmp_path: Path) -> Path:
    """真 git repo fixture：F-002 5 条 acceptance 共用。"""
    return _init_real_git_repo(tmp_path)


# ============================================================================
# AC1 + AC2：成功路径
# ============================================================================

class TestBootstrapRequirementHappyPath:
    """AC1 + AC2：成功路径——文件/目录齐全 + 分支切到 feat/req-<id>。"""

    def test_bootstrap_requirement_when_success_creates_all_artifacts(
        self, real_git_repo: Path,
    ):
        """given_clean_repo_when_bootstrap_then_all_artifacts_created_and_branch_switched."""
        req_id = wr._generate_req_id(real_git_repo)  # 顶层目录已建
        template_path = real_git_repo / ".claude" / "workflows" / "requirement" / "fake.yaml"

        # patch workflow_bootstrap.REPO_ROOT 让 _render_meta_yaml / _render_plan_md
        # 读真实模板（迁移后渲染逻辑在 workflow_bootstrap 模块）
        with patch("workflow_bootstrap.REPO_ROOT", _REPO_ROOT):
            req_dir = wb._bootstrap_requirement(
                req_id=req_id,
                title="F-002 测试需求",
                template_id="standard-8phase",
                template_path=template_path,
                arguments="",
                repo_root=real_git_repo,
            )

        # AC1：4 文件/目录全存在
        assert req_dir == real_git_repo / "requirements" / req_id
        assert (req_dir / "artifacts").is_dir(), "artifacts/ 目录应存在"
        assert (req_dir / "meta.yaml").is_file(), "meta.yaml 应存在"
        assert (req_dir / "plan.md").is_file(), "plan.md 应存在"
        assert (req_dir / "process.txt").is_file(), "process.txt 应存在"
        # process.txt 是空（hook 首次触发才填）
        assert (req_dir / "process.txt").read_text(encoding="utf-8") == ""

        # meta.yaml 至少含 req_id + title 渲染结果
        meta_text = (req_dir / "meta.yaml").read_text(encoding="utf-8")
        assert req_id in meta_text, f"meta.yaml 应含 req_id={req_id}"
        assert "F-002 测试需求" in meta_text, "meta.yaml 应含 title"
        # 流程组 base_branch 渲染为 develop（_init_real_git_repo 唯一存在）
        assert "base_branch: develop" in meta_text, "base_branch 应渲染为 develop"
        # F-17：流程组其它必备字段断言
        assert "log_layout: split" in meta_text, "meta.yaml 应含 log_layout: split"
        assert "phase: bootstrap" in meta_text, "meta.yaml phase 应为 bootstrap"

        # plan.md 含 title
        plan_text = (req_dir / "plan.md").read_text(encoding="utf-8")
        assert "F-002 测试需求" in plan_text

        # jsonl workflow_started 写入
        events, _ = read_events(req_dir / "run-state.jsonl")
        types = [e["type"] for e in events]
        assert "workflow_started" in types, f"应写入 workflow_started 事件，实际：{types}"

        # AC2：当前分支 = feat/req-<id>（小写、去 REQ- 前缀）
        expected_branch = f"feat/req-{req_id[len('REQ-'):].lower()}"
        result = _git(["git", "rev-parse", "--abbrev-ref", "HEAD"], real_git_repo)
        assert result.stdout.strip() == expected_branch, (
            f"分支应切到 {expected_branch}，实际：{result.stdout.strip()}"
        )


# ============================================================================
# AC3：mkdir 失败回滚
# ============================================================================

class TestBootstrapRequirementMkdirFailure:
    """AC3：mkdir artifacts/ 失败 → BootstrapError + rollback 后 req_dir 不残留。"""

    def test_bootstrap_requirement_when_mkdir_fails_then_rollback_leaves_no_residue(
        self, real_git_repo: Path, monkeypatch, caplog,
    ):
        """given_mkdir_raises_when_bootstrap_then_rollback_removes_req_dir."""
        req_id = wr._generate_req_id(real_git_repo)
        previous_branch = wb._current_branch(real_git_repo)
        assert previous_branch == "develop"

        # 仅对 artifacts/ 子目录的 mkdir 抛错（_generate_req_id 已经 mkdir 完顶层目录）
        target_artifacts = real_git_repo / "requirements" / req_id / "artifacts"
        original_mkdir = Path.mkdir

        def fail_on_artifacts(self_path, *args, **kwargs):
            if self_path == target_artifacts:
                raise OSError("E-TEST: 模拟 mkdir 失败")
            return original_mkdir(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", fail_on_artifacts)

        # 触发 bootstrap：应抛 BootstrapError
        with patch("workflow_bootstrap.REPO_ROOT", _REPO_ROOT):
            with pytest.raises(wb.BootstrapError) as exc_info:
                wb._bootstrap_requirement(
                    req_id=req_id,
                    title="mkdir 失败用例",
                    template_id="standard-8phase",
                    template_path=real_git_repo / "fake.yaml",
                    arguments="",
                    repo_root=real_git_repo,
                )
        assert exc_info.value.artifacts_created is True
        assert exc_info.value.branch_created is False

        # 还原 mkdir，否则 rollback 自己也 mkdir 会受影响
        monkeypatch.setattr(Path, "mkdir", original_mkdir)

        # 调 rollback：req_dir 应被删干净
        wb._bootstrap_rollback(
            req_id, real_git_repo, previous_branch,
            exc_info.value.artifacts_created, exc_info.value.branch_created,
        )
        assert not (real_git_repo / "requirements" / req_id).exists(), (
            f"rollback 后 requirements/{req_id}/ 不应残留"
        )

        # 分支应保持 develop（未切换过）
        result = _git(["git", "rev-parse", "--abbrev-ref", "HEAD"], real_git_repo)
        assert result.stdout.strip() == "develop"


# ============================================================================
# AC4：git checkout -b 失败 → 全回滚
# ============================================================================

class TestBootstrapRequirementCheckoutFailure:
    """AC4：git checkout -b 失败 → BootstrapError + rollback 后分支与目录全恢复。"""

    def test_bootstrap_requirement_when_checkout_fails_then_full_rollback(
        self, real_git_repo: Path, monkeypatch,
    ):
        """given_branch_already_exists_when_bootstrap_then_rollback_restores_state."""
        req_id = wr._generate_req_id(real_git_repo)
        previous_branch = wb._current_branch(real_git_repo)
        # 故意预建同名分支 → git checkout -b 必然失败 rc≠0
        target_branch = f"feat/req-{req_id[len('REQ-'):].lower()}"
        _git(["git", "branch", target_branch], real_git_repo)

        with patch("workflow_bootstrap.REPO_ROOT", _REPO_ROOT):
            with pytest.raises(wb.BootstrapError) as exc_info:
                wb._bootstrap_requirement(
                    req_id=req_id,
                    title="checkout 失败用例",
                    template_id="standard-8phase",
                    template_path=real_git_repo / "fake.yaml",
                    arguments="",
                    repo_root=real_git_repo,
                )
        # checkout 失败发生在 mkdir/write 之后，artifacts_created=True、branch_created=False
        assert exc_info.value.artifacts_created is True
        assert exc_info.value.branch_created is False

        # 关键回归：rollback 前预建分支还在；rollback 后该分支应被 git branch -D 清掉
        # 但因为 branch_created=False，rollback 不会去删 target_branch——它认为新分支没建成
        # 所以预建分支保留是正确行为；我们关心的是 req_dir 应被清掉
        wb._bootstrap_rollback(
            req_id, real_git_repo, previous_branch,
            exc_info.value.artifacts_created, exc_info.value.branch_created,
        )

        assert not (real_git_repo / "requirements" / req_id).exists(), (
            "checkout 失败后 rollback 应清掉 req_dir"
        )

        # 当前分支应仍是 develop（_bootstrap_requirement 的 _checkout_feature_branch 失败了，
        # 不会切过去；rollback 也不需要切）
        result = _git(["git", "rev-parse", "--abbrev-ref", "HEAD"], real_git_repo)
        assert result.stdout.strip() == "develop"

    def test_bootstrap_rollback_when_branch_created_then_restores_previous_branch(
        self, real_git_repo: Path,
    ):
        """given_branch_created_true_when_rollback_then_branch_deleted_and_previous_restored.

        模拟 _bootstrap_requirement 已 checkout 到 feat/req-<id>，但后续写 jsonl
        失败的场景——branch_created=True，rollback 应切回 develop + 删 feat 分支。
        """
        req_id = wr._generate_req_id(real_git_repo)
        previous_branch = "develop"
        # 手动模拟"分支已切"的中间态
        target_branch = f"feat/req-{req_id[len('REQ-'):].lower()}"
        _git(["git", "checkout", "-b", target_branch], real_git_repo)
        # 模拟 artifacts 已建一些文件
        (real_git_repo / "requirements" / req_id / "artifacts").mkdir()
        (real_git_repo / "requirements" / req_id / "meta.yaml").write_text("x", encoding="utf-8")

        wb._bootstrap_rollback(
            req_id, real_git_repo, previous_branch,
            artifacts_created=True, branch_created=True,
        )

        # 当前分支已切回 develop
        result = _git(["git", "rev-parse", "--abbrev-ref", "HEAD"], real_git_repo)
        assert result.stdout.strip() == "develop"
        # 新分支已被删
        branches = _git(["git", "branch", "--list", target_branch], real_git_repo).stdout
        assert target_branch not in branches, f"feat 分支应被删除，实际：{branches!r}"
        # req_dir 已 rmtree
        assert not (real_git_repo / "requirements" / req_id).exists()


# ============================================================================
# AC5：rollback 自身 IOError 不抛，仅 ERROR 日志
# ============================================================================

class TestBootstrapRollbackSilentOnIOError:
    """AC5：rollback 自身 IOError 不抛，仅 ERROR 日志。"""

    def test_bootstrap_rollback_when_rmtree_raises_then_no_exception_propagated(
        self, real_git_repo: Path, monkeypatch, caplog,
    ):
        """given_rmtree_raises_oserror_when_rollback_then_logged_not_raised."""
        req_id = wr._generate_req_id(real_git_repo)
        # 准备 req_dir 让 rollback 真的尝试 rmtree
        (real_git_repo / "requirements" / req_id / "artifacts").mkdir()

        def fail_rmtree(path):
            raise OSError("E-TEST: 模拟 rmtree 失败（磁盘只读）")

        monkeypatch.setattr("workflow_bootstrap.shutil.rmtree", fail_rmtree)
        caplog.set_level(logging_mod.ERROR, logger="root")

        # 不应抛任何异常
        wb._bootstrap_rollback(
            req_id, real_git_repo, "develop",
            artifacts_created=True, branch_created=False,
        )

        # 应有 ERROR 日志
        error_msgs = [r.message for r in caplog.records if r.levelno >= logging_mod.ERROR]
        assert any("rmtree" in m or req_id in m for m in error_msgs), (
            f"rollback 应记录 ERROR 日志，实际：{error_msgs}"
        )

    def test_bootstrap_rollback_when_called_repeatedly_then_idempotent(
        self, real_git_repo: Path,
    ):
        """given_already_rolled_back_when_rollback_again_then_no_raise.

        幂等验证：rollback 已成功清理后，再次调用不应抛 FileNotFoundError。
        """
        req_id = wr._generate_req_id(real_git_repo)
        (real_git_repo / "requirements" / req_id / "artifacts").mkdir()

        wb._bootstrap_rollback(req_id, real_git_repo, "develop", True, False)
        # 第二次调用：req_dir 已被删，应静默
        wb._bootstrap_rollback(req_id, real_git_repo, "develop", True, False)


# ============================================================================
# F-16：rollback subprocess rc!=0 路径 ERROR 日志覆盖
# ============================================================================

class TestBootstrapRollbackSilentOnSubprocessFailure:
    """F-16：rollback 内 subprocess.run check=False，rc!=0 时记 ERROR 日志且不抛。

    与 F-9（生产代码补 rc!=0 logging）配套：mock subprocess.run 返回 rc=1，
    断言 logging.error 被触发、rollback 不抛异常。覆盖 git_checkout / git_branch_delete 两条路径。
    """

    def test_bootstrap_rollback_when_git_checkout_returncode_nonzero_then_logged(
        self, real_git_repo: Path, monkeypatch, caplog,
    ):
        """given_rollback_calls_git_checkout_rc1_when_rollback_then_error_logged_not_raised."""
        def _fake_run(cmd, *args, **kwargs):
            # 让 git checkout 失败，但 git branch -D 成功
            if "checkout" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="",
                    stderr="fatal: cannot switch (mock)",
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr("workflow_bootstrap.subprocess.run", _fake_run)
        caplog.set_level(logging_mod.ERROR, logger="root")

        # 不应抛任何异常
        wb._bootstrap_rollback(
            "REQ-2026-999", real_git_repo, "develop",
            artifacts_created=False, branch_created=True,
        )

        # ERROR 日志应包含 step=git_checkout 与 rc=1
        msgs = [r.message for r in caplog.records if r.levelno >= logging_mod.ERROR]
        assert any("step=git_checkout" in m and "rc=1" in m for m in msgs), (
            f"应记录 git_checkout rc=1 ERROR，实际：{msgs}"
        )

    def test_bootstrap_rollback_when_git_branch_delete_returncode_nonzero_then_logged(
        self, real_git_repo: Path, monkeypatch, caplog,
    ):
        """given_rollback_calls_git_branch_d_rc1_when_rollback_then_error_logged_not_raised."""
        def _fake_run(cmd, *args, **kwargs):
            # checkout 成功，branch -D 失败
            if "branch" in cmd and "-D" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="",
                    stderr="error: branch not fully merged (mock)",
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr("workflow_bootstrap.subprocess.run", _fake_run)
        caplog.set_level(logging_mod.ERROR, logger="root")

        wb._bootstrap_rollback(
            "REQ-2026-998", real_git_repo, "develop",
            artifacts_created=False, branch_created=True,
        )

        msgs = [r.message for r in caplog.records if r.levelno >= logging_mod.ERROR]
        assert any("step=git_branch_delete" in m and "rc=1" in m for m in msgs), (
            f"应记录 git_branch_delete rc=1 ERROR，实际：{msgs}"
        )


# ============================================================================
# _parse_args：参数切分约定
# ============================================================================

class TestParseArgs:
    """_parse_args 的几个典型切分约定。"""

    def test_parse_args_when_title_provided_returns_correct_split(self):
        """given_template_and_title_when_parse_args_then_title_equals_arg1."""
        tid, args, title = wr._parse_args(["standard-8phase", "做个登录页"])
        assert tid == "standard-8phase"
        assert title == "做个登录页"
        assert args == "做个登录页"

    def test_parse_args_when_no_title_then_falls_back_to_template_id(self):
        """given_only_template_when_parse_args_then_title_falls_back_to_template_id."""
        tid, args, title = wr._parse_args(["standard-8phase"])
        assert tid == "standard-8phase"
        assert args == ""
        assert title == "standard-8phase"  # fallback 避免 plan.md __TITLE__ 留空

    def test_parse_args_empty_raises_workflow_error(self):
        """given_empty_args_when_parse_args_then_raises_workflow_error."""
        from common import WorkflowError
        with pytest.raises(WorkflowError):
            wr._parse_args([])


# ============================================================================
# _is_requirement_template 相关测试（F-003 已删除此函数）
# ============================================================================
# F-003 删除了 _is_requirement_template 过渡 helper，改由 load_workflow().workflow.get("category")
# 直接判定。对应的等价测试已迁移到 tests/skills/test_workflow_commands.py
# 的 TestLoadWorkflowSchemaGate 类中（test_main_passes_through_valid_requirement_template）。
