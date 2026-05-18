"""F-002 / F-004 · _bootstrap_requirement + _bootstrap_rollback + 拆出的 helper 测试。

从 tests/skills/test_workflow_commands.py 拆出（rev2 闭合 F-1 file-length）。

覆盖 features.json F-002 的 5 条 acceptance（legacy main-repo 路径，
no_worktree=True）：
  AC1 成功路径：4 文件/目录全存在
  AC2 成功后当前分支 = feat/req-<id>
  AC3 mkdir 失败时 req_dir 不残留
  AC4 git checkout 失败时分支与目录全回滚
  AC5 rollback 自身 IOError 不抛，仅 ERROR 日志

F-004 regression 处理（task context "F-003 regression cleanup"）：
  - _generate_req_id 不再创建顶层目录（F-001/F-003 P1-2）。本测试 setup 段
    走 no_worktree=True 路径，让 _bootstrap_requirement 在主仓根下建 artifacts/，
    不要求外部预 mkdir。
  - _parse_args 已升级返回 RunArgs（F-003），原 3-tuple unpack 改读字段。

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
        """given_clean_repo_when_bootstrap_then_all_artifacts_created_and_branch_switched.

        F-004 适配：传 no_worktree=True 走 legacy 主仓根路径，保留 AC1/AC2 语义。
        """
        req_id = wr._generate_req_id(real_git_repo)
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
                no_worktree=True,
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

        # AC2：当前分支 = feat/req-<id>（_strip_req_prefix 兼容 legacy + 新格式）
        expected_branch = f"feat/req-{wb._strip_req_prefix(req_id)}"
        result = _git(["git", "rev-parse", "--abbrev-ref", "HEAD"], real_git_repo)
        assert result.stdout.strip() == expected_branch, (
            f"分支应切到 {expected_branch}，实际：{result.stdout.strip()}"
        )


# ============================================================================
# P1-1（codex 2026-05-12）：bootstrap 在非 develop 分支上跑时，新分支应从 base_branch fork
# ============================================================================

class TestBootstrapBaseBranchAsCheckoutStartPoint:
    """codex P1-1：_checkout_feature_branch 必须以 base_branch 为新分支起点，
    避免在 feature/hotfix 分支上跑 bootstrap 时把不相关 commit 拉进需求分支。
    """

    def test_bootstrap_new_branch_starts_from_base_not_current_head(
        self, real_git_repo: Path,
    ):
        """given_on_other_branch_with_extra_commit_when_bootstrap_then_new_branch_lacks_that_commit."""
        # 1. 在 develop 上有 init commit（_init_real_git_repo 已建）
        develop_head = _git(
            ["git", "rev-parse", "HEAD"], real_git_repo,
        ).stdout.strip()

        # 2. 切到另一个 feature 分支并加一条不相关 commit
        _git(["git", "checkout", "-b", "feat/other-work"], real_git_repo)
        (real_git_repo / "other.txt").write_text("polluting commit\n", encoding="utf-8")
        _git(["git", "add", "other.txt"], real_git_repo)
        _git(["git", "commit", "-q", "-m", "polluting commit on other branch"],
             real_git_repo)
        other_head = _git(
            ["git", "rev-parse", "HEAD"], real_git_repo,
        ).stdout.strip()
        assert other_head != develop_head, "前置：other 分支 HEAD 应已偏离 develop"

        # 3. 在 other 分支上跑 bootstrap（legacy 路径走 no_worktree=True）
        req_id = wr._generate_req_id(real_git_repo)
        with patch("workflow_bootstrap.REPO_ROOT", _REPO_ROOT):
            wb._bootstrap_requirement(
                req_id=req_id,
                title="P1-1 测试需求",
                template_id="standard-8phase",
                template_path=real_git_repo / "fake.yaml",
                arguments="",
                repo_root=real_git_repo,
                no_worktree=True,
            )

        # 4. 新建的 feat/req-<id> 分支应从 develop fork（HEAD 上多了 bootstrap 自身写的
        #    workflow_started jsonl + 三件 artifacts，但起点是 develop_head 而非 other_head）
        expected_branch = f"feat/req-{wb._strip_req_prefix(req_id)}"
        result = _git(["git", "rev-parse", "--abbrev-ref", "HEAD"], real_git_repo)
        assert result.stdout.strip() == expected_branch

        # merge-base(new, develop) == develop_head（新分支祖先链包含 develop）
        merge_base = _git(
            ["git", "merge-base", expected_branch, "develop"], real_git_repo,
        ).stdout.strip()
        assert merge_base == develop_head, (
            f"新分支应从 develop fork，merge-base 应为 develop_head={develop_head[:8]}，"
            f"实际 {merge_base[:8]}"
        )

        # merge-base(new, other) 严格早于 other_head（新分支不含 other 上的污染 commit）
        merge_base_other = _git(
            ["git", "merge-base", expected_branch, "feat/other-work"], real_git_repo,
        ).stdout.strip()
        assert merge_base_other == develop_head, (
            f"新分支不应继承 other 分支的污染 commit，merge-base 应回退到 develop_head，"
            f"实际 {merge_base_other[:8]}"
        )


# ============================================================================
# AC3：mkdir 失败回滚
# ============================================================================

class TestBootstrapRequirementMkdirFailure:
    """AC3：mkdir artifacts/ 失败 → BootstrapError + rollback 后 req_dir 不残留。"""

    def test_bootstrap_requirement_when_mkdir_fails_then_rollback_leaves_no_residue(
        self, real_git_repo: Path, monkeypatch, caplog,
    ):
        """given_mkdir_raises_when_bootstrap_then_rollback_removes_req_dir.

        F-004 适配：走 no_worktree=True 路径，先 _setup_worktree_or_branch 完成
        分支切换（branch_created=True），然后 mkdir artifacts/ 失败 → rollback。
        """
        req_id = wr._generate_req_id(real_git_repo)
        previous_branch = wb._current_branch(real_git_repo)
        assert previous_branch == "develop"

        # 仅对 artifacts/ 子目录的 mkdir 抛错（顶层 requirements/<req_id>/ 由 parents=True 建）
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
                    no_worktree=True,
                )
        assert exc_info.value.artifacts_created is True
        # F-004：no_worktree=True 走 _checkout_feature_branch，mkdir 失败发生在分支切换之后
        assert exc_info.value.branch_created is True

        # 还原 mkdir，否则 rollback 自己也 mkdir 会受影响
        monkeypatch.setattr(Path, "mkdir", original_mkdir)

        # 调 rollback：req_dir 应被删干净，分支应切回 develop
        # F-004 rev2 F-4：_bootstrap_rollback 现为 keyword-only 签名
        wb._bootstrap_rollback(
            req_id, real_git_repo, previous_branch,
            artifacts_created=exc_info.value.artifacts_created,
            branch_created=exc_info.value.branch_created,
        )
        assert not (real_git_repo / "requirements" / req_id).exists(), (
            f"rollback 后 requirements/{req_id}/ 不应残留"
        )

        # 分支应切回 develop
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
        """given_branch_already_exists_when_bootstrap_then_rollback_restores_state.

        F-004 适配：走 no_worktree=True 路径，_checkout_feature_branch 因同名分支
        existing 失败 → BootstrapError(reason='path_or_branch_exists'，
        artifacts_created=False，branch_created=False)。
        """
        req_id = wr._generate_req_id(real_git_repo)
        previous_branch = wb._current_branch(real_git_repo)
        # 故意预建同名分支 → git checkout -b 必然失败 rc≠0
        target_branch = f"feat/req-{wb._strip_req_prefix(req_id)}"
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
                    no_worktree=True,
                )
        # F-004：_checkout_feature_branch 在 mkdir/write 之前抛
        # （worktree-first 顺序：step 2 setup → step 4 mkdir）
        assert exc_info.value.branch_created is False
        # reason 应为 path_or_branch_exists（F-003 retry 信号）
        assert exc_info.value.reason == "path_or_branch_exists"

        # 调 rollback：因为 branch_created=False，rollback 不会去删 target_branch
        # F-004 rev2 F-4：_bootstrap_rollback 现为 keyword-only 签名
        wb._bootstrap_rollback(
            req_id, real_git_repo, previous_branch,
            artifacts_created=exc_info.value.artifacts_created,
            branch_created=exc_info.value.branch_created,
        )

        # 主仓根 requirements/<req_id>/ 在 worktree-first 流程中不应被创建
        assert not (real_git_repo / "requirements" / req_id).exists()

        # 当前分支应仍是 develop（_checkout_feature_branch 失败，未切过去）
        result = _git(["git", "rev-parse", "--abbrev-ref", "HEAD"], real_git_repo)
        assert result.stdout.strip() == "develop"

    def test_bootstrap_rollback_when_branch_created_then_restores_previous_branch(
        self, real_git_repo: Path,
    ):
        """given_branch_created_true_when_rollback_then_branch_deleted_and_previous_restored.

        F-004 适配：req_dir 顶层目录现在由 _bootstrap_requirement 内部 parents=True 建，
        测试 setup 段直接 mkdir(parents=True) 模拟"分支 + artifacts 已建"中间态。
        """
        req_id = wr._generate_req_id(real_git_repo)
        previous_branch = "develop"
        # 手动模拟"分支已切"的中间态
        target_branch = f"feat/req-{wb._strip_req_prefix(req_id)}"
        _git(["git", "checkout", "-b", target_branch], real_git_repo)
        # 模拟 artifacts 已建一些文件（_generate_req_id 不再预建顶层目录，自己建）
        (real_git_repo / "requirements" / req_id / "artifacts").mkdir(parents=True)
        (real_git_repo / "requirements" / req_id / "meta.yaml").write_text("x", encoding="utf-8")

        wb._bootstrap_rollback(
            req_id, real_git_repo, previous_branch,
            artifacts_created=True, branch_created=True,
        )

        # 当前分支已切回 develop
        result = _git(["git", "rev-parse", "--abbrev-ref", "HEAD"], real_git_repo)
        assert result.stdout.strip() == "develop"
        # 新分支已被删（git branch --list 在分支不存在时返回空）
        branches = _git(
            ["git", "branch", "--list", target_branch], real_git_repo, check=False,
        ).stdout
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
        # 准备 req_dir 让 rollback 真的尝试 rmtree（_generate_req_id 不再预建顶层目录）
        (real_git_repo / "requirements" / req_id / "artifacts").mkdir(parents=True)

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
        (real_git_repo / "requirements" / req_id / "artifacts").mkdir(parents=True)

        # F-004 rev2 F-4：_bootstrap_rollback 现为 keyword-only 签名
        wb._bootstrap_rollback(
            req_id, real_git_repo, "develop",
            artifacts_created=True, branch_created=False,
        )
        # 第二次调用：req_dir 已被删，应静默
        wb._bootstrap_rollback(
            req_id, real_git_repo, "develop",
            artifacts_created=True, branch_created=False,
        )


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
        """given_template_and_title_when_parse_args_then_title_equals_arg1.

        F-003 适配：_parse_args 返回 RunArgs dataclass（原 3-tuple unpack 改读字段）。
        """
        result = wr._parse_args(["standard-8phase", "做个登录页"])
        assert result.template_id == "standard-8phase"
        assert result.title == "做个登录页"
        assert result.template_args == "做个登录页"

    def test_parse_args_when_no_title_then_falls_back_to_template_id(self):
        """given_only_template_when_parse_args_then_title_falls_back_to_template_id."""
        result = wr._parse_args(["standard-8phase"])
        assert result.template_id == "standard-8phase"
        assert result.template_args == ""
        assert result.title == "standard-8phase"  # fallback 避免 plan.md __TITLE__ 留空

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
