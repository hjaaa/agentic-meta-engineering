"""worktree 状态探测 / 创建 / setup / 清理的统一入口（F-002）。

设计来源：requirements/REQ-2026-014/artifacts/detailed-design.md §3.2 / §2

模块定位：
  - 叶子节点（OD-1 默认锁死）：本模块**不引用** scripts/lib/requirement_naming
    或任何其它 scripts/lib/ 兄弟，避免 lib 内部循环依赖
  - 标准库 only（subprocess + pathlib + dataclasses + typing + logging + time + os）
  - 不读 / 不写 meta.yaml，所有持久化由调用方（F-004 bootstrap / F-005 archive）负责

公开接口（来源：detailed-design.md:343-506）：
  - detect_worktree_state(repo_root)            → WorktreeState
  - select_worktree_location(repo_root, branch) → Path
  - ensure_worktree_dir_ignored(repo_root, loc) → None / WorktreeBootstrapError
  - create_worktree(repo_root, branch, base, location) → WorktreeInfo
  - run_worktree_setup(worktree_path, policy, *, owner) → SetupResult
  - resolve_main_repo_root(worktree_path)       → Path  (P1-3)
  - cleanup_worktree_if_owned(meta, main_root)  → CleanupResult

异常类：
  - WorktreeBootstrapError(BootstrapError)：本模块统一异常出口；引入
    reason / retain_worktree 两个扩展字段。subclass + kwargs 兼容（来源：
    F-002 task context "BootstrapError 与 reason / retain_worktree 字段约束"）
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from workflow_bootstrap import BootstrapError  # noqa: E402

# git 子进程默认超时（秒）；worktree / rev-parse 操作通常 < 1s，30s 留足
# baseline 执行（make gates-validate）单独走更长的 timeout
_GIT_TIMEOUT_SECONDS = 30

# baseline 子进程超时（秒）；make gates-validate 可能跑较久（lint + test 套件），
# 给 30 分钟兜底——超时落 failed，与 rc!=0 同等语义（OD-2）
_BASELINE_TIMEOUT_SECONDS = 1800

# stderr trim 上限：worktree_manager 内统一 2KB，防 BootstrapError 消息爆炸
_STDERR_TRIM_BYTES = 2048

# 默认 worktree 容器目录（D-010 .gitignore 白名单前缀）
_DEFAULT_WORKTREE_DIR = ".worktrees"


# ============================================================================
# 异常类
# ============================================================================

class WorktreeBootstrapError(BootstrapError):
    """worktree 操作失败的统一异常出口。

    继承 BootstrapError 让调用方 `except BootstrapError` 兜底仍命中（is-a 关系）。
    扩展两个字段：
      - reason：分类标识，调用方按 reason 决定 retry / 终止 / 透传
        常用值：'path_or_branch_exists' / 'porcelain_malformed'
                 / 'main_root_missing' / 'worktree_dir_not_ignored' /
                 'git_failure' / 'other'
      - retain_worktree：True 表示调用方应保留 worktree / 分支现场
        （baseline 失败保留排查现场，OD-2 落点）

    F-004 改造 workflow_bootstrap.py 时会把这两个字段并入父类；当前阶段
    subclass 是唯一合规路径（F-002 不许碰 workflow_bootstrap.py）。
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str = "other",
        branch_created: bool = False,
        artifacts_created: bool = False,
        retain_worktree: bool = False,
        worktree_info: Optional["WorktreeInfo"] = None,
    ) -> None:
        """初始化 worktree-flavor BootstrapError。

        Args:
          message: 错误消息（含 branch / location / rc / stderr trim 等业务主键）
          reason: 失败原因枚举（常用：path_or_branch_exists / other /
                  worktree_dir_not_ignored / porcelain_malformed /
                  main_root_missing / git_failure）
          branch_created / artifacts_created: 透传父类，由 _bootstrap_rollback
                  决定回滚动作
          retain_worktree: True 时调用层应保留 worktree / branch 现场
                  （OD-2 baseline_failed 落点）
          worktree_info: F-004 rev2 加入；caller-side _bootstrap_rollback 需
                  此字段触发 step 1 worktree remove 守卫，避免孤儿 worktree。
        """
        super().__init__(
            message,
            artifacts_created=artifacts_created,
            branch_created=branch_created,
            reason=reason,
            retain_worktree=retain_worktree,
            worktree_info=worktree_info,
        )


# ============================================================================
# dataclass 定义（来源：detailed-design.md:347-374 / 490-506）
# ============================================================================

@dataclass(frozen=True)
class WorktreeState:
    """git 拓扑探测结果。"""
    is_git_repo: bool
    is_linked_worktree: bool
    is_submodule: bool
    is_detached: bool
    branch: str                # 当前分支名；detached HEAD 时为空串
    worktree_path: Path
    git_dir: Path              # 当前 worktree 的 git 目录（git rev-parse --git-dir 输出）
    git_common_dir: Path       # 主 worktree 的 git 公共目录（git rev-parse --git-common-dir 输出）


@dataclass(frozen=True)
class WorktreeInfo:
    """worktree 元信息（写入 meta.yaml.worktree 段用）。"""
    path: Path
    branch: str
    base_branch: str
    owner: Literal["workflow", "external", "none"]
    created: bool              # 本次调用是否新建（vs. 复用）


@dataclass(frozen=True)
class SetupResult:
    """baseline 执行结果（meta.yaml.worktree.baseline 段填值用）。"""
    status: Literal["passed", "failed", "skipped"]
    rc: int
    duration_ms: int
    log_tail: str              # stderr 末 2KB；写 process.txt / notes.md 时引用


@dataclass(frozen=True)
class CleanupResult:
    """archive 清理结果。"""
    action: Literal["removed", "skipped", "aborted", "failed"]
    reason: str                # 合法取值：external / legacy_no_worktree_field /
                               # path_not_in_whitelist / main_root_equals_worktree /
                               # git_failure / workflow_ok
    removed_path: Optional[Path]


# ============================================================================
# 工具：subprocess 包装 + stderr trim
# ============================================================================

def _trim_stderr(raw: str) -> str:
    """将 stderr 截断到 _STDERR_TRIM_BYTES 字节内，utf-8 decode errors='replace'。"""
    if not raw:
        return ""
    encoded = raw.encode("utf-8", errors="replace")
    if len(encoded) <= _STDERR_TRIM_BYTES:
        return raw
    return encoded[-_STDERR_TRIM_BYTES:].decode("utf-8", errors="replace")


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    timeout: int = _GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    """git 子进程调用统一入口；不抛裸 subprocess/OSError。

    返回 CompletedProcess（rc 非零也返回，调用方据 rc 判定）。
    底层 subprocess.SubprocessError / OSError / FileNotFoundError 统一包装为
    WorktreeBootstrapError(reason='other', branch_created=False) 抛出——
    本模块所有 git 调用都走此入口。
    """
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise WorktreeBootstrapError(
            f"git binary not found: {exc}",
            reason="other",
            branch_created=False,
        ) from exc
    except (subprocess.SubprocessError, OSError) as exc:
        raise WorktreeBootstrapError(
            f"git subprocess failed: args={args} cwd={cwd} err={exc}",
            reason="other",
            branch_created=False,
        ) from exc


# ============================================================================
# 探测 git 拓扑状态（detect_worktree_state）
# ============================================================================

def detect_worktree_state(repo_root: Path) -> WorktreeState:
    """探测 repo_root 的 git 拓扑状态。

    判定逻辑（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:225）：
      git rev-parse --git-dir / --git-common-dir 双源
      - git_dir == git_common_dir → 主 worktree（normal repo）
      - git_dir != git_common_dir 且 git_dir 不含 '/modules/' → linked worktree
      - git_dir 含 '/modules/' → submodule
      - git symbolic-ref HEAD 失败 → detached HEAD

    入参：repo_root — 候选 git 根（pathlib.Path）
    返回：WorktreeState
    异常：
      - 非 git 仓库（`git rev-parse --git-dir` rc!=0）→ 返回
        is_git_repo=False 的 WorktreeState（不抛异常）
      - 已是 git 仓库但 `git rev-parse --git-common-dir` rc!=0（git 版本过旧 /
        仓库损坏）→ WorktreeBootstrapError(reason='other')，避免静默 fallback
        让 is_linked_worktree 永远 False 的拓扑误判
      - 已是 git 仓库但 `git rev-parse --show-toplevel` rc!=0（bare repo /
        检测竞争）→ WorktreeBootstrapError(reason='other')；与
        --git-common-dir 同策略，符合 detailed-design.md:386 "所有 subprocess
        失败统一包装 BootstrapError"
      - _run_git 底层灾难级错误（git 二进制丢失 / OSError）→
        WorktreeBootstrapError(reason='other')
    """
    git_dir_proc = _run_git(["rev-parse", "--git-dir"], cwd=repo_root)
    if git_dir_proc.returncode != 0:
        # 非 git 仓库或路径不存在 → 返回 is_git_repo=False（不抛）
        logging.debug(
            "detect_worktree_state: not a git repo repo_root=%s stderr=%s",
            repo_root, _trim_stderr(git_dir_proc.stderr),
        )
        return WorktreeState(
            is_git_repo=False,
            is_linked_worktree=False,
            is_submodule=False,
            is_detached=False,
            branch="",
            worktree_path=repo_root,
            git_dir=Path(""),
            git_common_dir=Path(""),
        )

    git_dir_raw = git_dir_proc.stdout.strip()
    git_dir = (repo_root / git_dir_raw).resolve() if not Path(git_dir_raw).is_absolute() else Path(git_dir_raw)

    common_proc = _run_git(["rev-parse", "--git-common-dir"], cwd=repo_root)
    if common_proc.returncode != 0:
        # fail-fast：静默 fallback 会让 git_dir==git_common_dir 恒成立，
        # is_linked_worktree 永远 False（拓扑误判）。掩盖 git 版本过旧 /
        # 仓库损坏属硬伤，必须抛出。
        raise WorktreeBootstrapError(
            f"detect_worktree_state: `git rev-parse --git-common-dir` 失败 "
            f"rc={common_proc.returncode} stderr={_trim_stderr(common_proc.stderr)}",
            reason="other",
        )
    common_raw = common_proc.stdout.strip()
    git_common_dir = (
        (repo_root / common_raw).resolve()
        if not Path(common_raw).is_absolute()
        else Path(common_raw)
    )

    is_submodule = "/modules/" in str(git_dir)
    is_linked_worktree = (git_dir != git_common_dir) and not is_submodule

    head_proc = _run_git(["symbolic-ref", "--short", "HEAD"], cwd=repo_root)
    is_detached = head_proc.returncode != 0
    branch = head_proc.stdout.strip() if not is_detached else ""

    worktree_proc = _run_git(["rev-parse", "--show-toplevel"], cwd=repo_root)
    if worktree_proc.returncode != 0:
        # 与 --git-common-dir 同策略 fail-fast：静默 fallback 会让
        # worktree_path 永远等于 repo_root，下游 is_linked_worktree
        # / cleanup 判定都会受错误锚点影响。已通过 --git-dir 仍 show-toplevel
        # 失败属硬伤（bare repo / 检测竞争 / git 版本异常）必须抛出。
        raise WorktreeBootstrapError(
            f"detect_worktree_state: `git rev-parse --show-toplevel` 失败 "
            f"rc={worktree_proc.returncode} "
            f"stderr={_trim_stderr(worktree_proc.stderr)}",
            reason="other",
        )
    worktree_path = Path(worktree_proc.stdout.strip())

    return WorktreeState(
        is_git_repo=True,
        is_linked_worktree=is_linked_worktree,
        is_submodule=is_submodule,
        is_detached=is_detached,
        branch=branch,
        worktree_path=worktree_path,
        git_dir=git_dir,
        git_common_dir=git_common_dir,
    )


# ============================================================================
# 选择 worktree 目录（select_worktree_location）
# ============================================================================

def select_worktree_location(
    repo_root: Path,
    branch: str,
    preference: str = _DEFAULT_WORKTREE_DIR,
) -> Path:
    """按优先级选 worktree 目录：preference 相对主仓根（默认 .worktrees/）。

    入参：
      repo_root — 主仓根（绝对路径）
      branch    — 分支名（如 'feat/req-20260518-foo'）；'/' 替换为 '-'
      preference — 容器目录相对路径（默认 '.worktrees'）
    返回：repo_root / preference / branch.replace('/', '-')
    纯字符串拼接，不读 / 不写 FS。
    """
    sanitized = branch.replace("/", "-")
    return repo_root / preference / sanitized


# ============================================================================
# 校验 .gitignore 收录 worktree 容器（ensure_worktree_dir_ignored）
# ============================================================================

def ensure_worktree_dir_ignored(repo_root: Path, location: Path) -> None:
    """校验 location 已被 .gitignore（D-010 fail-closed）。

    实现：读 repo_root/.gitignore 行扫描，命中以下任一即返回：
      - '.worktrees/'
      - '.worktrees'
      - '/.worktrees/'
      - 等价于 location 容器相对路径的条目
    未命中 → 抛 WorktreeBootstrapError(reason='worktree_dir_not_ignored')
    （提示用户先 commit F-007 .gitignore 改动）。

    入参：
      repo_root — 主仓根
      location  — select_worktree_location 返回的具体 worktree 目录
    返回：None
    异常：
      - .gitignore 不存在 / 未含 container 条目 →
        WorktreeBootstrapError(reason='worktree_dir_not_ignored')
      - 读 .gitignore 抛 OSError →
        WorktreeBootstrapError(reason='other')

    rev2 F-8：reason 名实统一——从 'gitignore_missing' 改为
    'worktree_dir_not_ignored'，与 BootstrapError reason 枚举
    （workflow_bootstrap.py:65 / detailed-design.md §5.1）保持一致。
    """
    # 推导 location 所在的容器相对路径（如 '.worktrees'）
    try:
        rel = location.relative_to(repo_root)
        container = rel.parts[0] if rel.parts else _DEFAULT_WORKTREE_DIR
    except ValueError:
        container = _DEFAULT_WORKTREE_DIR

    gitignore_path = repo_root / ".gitignore"
    if not gitignore_path.is_file():
        raise WorktreeBootstrapError(
            f"missing .gitignore at {gitignore_path}; "
            f"先 commit F-007 .gitignore 改动（{container}/ 必须 ignore）",
            reason="worktree_dir_not_ignored",
            branch_created=False,
        )

    candidates = {
        container,
        f"{container}/",
        f"/{container}",
        f"/{container}/",
    }

    try:
        for raw_line in gitignore_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line in candidates:
                logging.debug(
                    "ensure_worktree_dir_ignored: matched line=%r container=%s",
                    line, container,
                )
                return
    except OSError as exc:
        raise WorktreeBootstrapError(
            f"read .gitignore failed: {exc}",
            reason="other",
            branch_created=False,
        ) from exc

    raise WorktreeBootstrapError(
        f".gitignore missing entry for '{container}/'; "
        f"先 commit F-007 .gitignore 改动后重试",
        reason="worktree_dir_not_ignored",
        branch_created=False,
    )


# ============================================================================
# 新建 worktree（create_worktree）
# ============================================================================

def create_worktree(
    repo_root: Path,
    branch: str,
    base_branch: str,
    location: Path,
) -> WorktreeInfo:
    """执行 git worktree add <location> -b <branch> <base_branch>。

    入参：
      repo_root   — 主仓根
      branch      — 待创建分支名（feat/req-<key>）
      base_branch — 切出基准分支（develop / main / master）
      location    — worktree 目录路径（来自 select_worktree_location）
    返回：WorktreeInfo(owner='workflow', created=True)
    异常：
      - stderr 命中 "fatal: '<path>' already exists" 或
        "fatal: a branch named '<branch>' already exists" →
        WorktreeBootstrapError(reason='path_or_branch_exists', branch_created=False)
        （P1-2 retry 信号源）
      - 其它 rc!=0 → WorktreeBootstrapError(reason='other', branch_created=False) + stderr trim
    """
    proc = _run_git(
        ["worktree", "add", str(location), "-b", branch, base_branch],
        cwd=repo_root,
    )

    if proc.returncode == 0:
        logging.info(
            "create_worktree: ok branch=%s base=%s location=%s",
            branch, base_branch, location,
        )
        return WorktreeInfo(
            path=location,
            branch=branch,
            base_branch=base_branch,
            owner="workflow",
            created=True,
        )

    stderr_trim = _trim_stderr(proc.stderr)
    # P1-2 信号识别：仅精确匹配 git 'fatal:' 前缀两条字符串，避免无关 hook /
    # 子命令 stderr（如 "pre-commit hook: file already exists"）误升 retry。
    # 不同 git 版本若措辞变化由单测捕获。
    is_exists_collision = (
        f"fatal: '{location}' already exists" in stderr_trim
        or f"fatal: a branch named '{branch}' already exists" in stderr_trim
    )
    reason = "path_or_branch_exists" if is_exists_collision else "other"

    logging.error(
        "create_worktree: failed branch=%s location=%s rc=%d reason=%s stderr=%s",
        branch, location, proc.returncode, reason, stderr_trim,
    )
    raise WorktreeBootstrapError(
        f"git worktree add failed rc={proc.returncode} branch={branch} "
        f"location={location} stderr={stderr_trim}",
        reason=reason,
        branch_created=False,
    )


# ============================================================================
# 执行 baseline 校验（run_worktree_setup）
# ============================================================================

def run_worktree_setup(
    worktree_path: Path,
    policy: dict,
    *,
    owner: str,
) -> SetupResult:
    """在 worktree 内执行 baseline（make gates-validate）。

    OD-4 落点：owner='external' 短路返回 SetupResult(status='skipped')，
    **不读** policy.required 字段。

    OD-2 落点：owner='workflow' →
      rc==0 → SetupResult(status='passed')
      rc!=0 → SetupResult(status='failed')
        （policy.required 真假与否都返回 failed；调用方据 policy.required
         决定是否抛 retain_worktree=True；本函数职责只是忠实返回结果）

    环境变量：owner='workflow' 时向子进程注入 CLAUDE_GATES_AUDIT_ROOT=main_repo_root
    便于 baseline 跑跨 worktree 审计（来源：tech-feasibility.md:129）。

    入参：
      worktree_path — 待执行 baseline 的目录
      policy        — yaml worktree 段（含 required 字段；本函数不读 required）
      owner         — 'workflow' / 'external' / 'none'
    返回：SetupResult
    异常：本函数不向外抛；所有 subprocess / 超时 / OSError 均转换为
          SetupResult(status='failed', rc=<int>, log_tail=<stderr trim>)。
    """
    if owner == "external":
        logging.info(
            "run_worktree_setup: skipped owner=external worktree_path=%s",
            worktree_path,
        )
        return SetupResult(
            status="skipped",
            rc=0,
            duration_ms=0,
            log_tail="",
        )

    # owner='workflow' (or 'none' 走同一路径) → 真正执行 make gates-validate
    env = os.environ.copy()
    # 透传 CLAUDE_GATES_AUDIT_ROOT；调用方若未设，回写主仓根（worktree 上游目录）
    if "CLAUDE_GATES_AUDIT_ROOT" not in env:
        env["CLAUDE_GATES_AUDIT_ROOT"] = str(worktree_path)

    start = time.monotonic()
    try:
        proc = subprocess.run(
            ["make", "gates-validate"],
            capture_output=True,
            text=True,
            cwd=str(worktree_path),
            env=env,
            timeout=_BASELINE_TIMEOUT_SECONDS,
        )
        rc = proc.returncode
        stderr_raw = proc.stderr
    except FileNotFoundError as exc:
        # make 二进制不存在 → 视同 baseline failed（rc=127 类比 shell）
        logging.error("run_worktree_setup: make binary not found: %s", exc)
        rc = 127
        stderr_raw = f"FileNotFoundError: {exc}"
    except subprocess.TimeoutExpired as exc:
        logging.error(
            "run_worktree_setup: baseline timeout worktree_path=%s timeout=%ds",
            worktree_path, _BASELINE_TIMEOUT_SECONDS,
        )
        rc = 124  # 与 GNU timeout 退出码对齐
        stderr_raw = f"TimeoutExpired after {_BASELINE_TIMEOUT_SECONDS}s: {exc}"
    except (subprocess.SubprocessError, OSError) as exc:
        logging.error(
            "run_worktree_setup: subprocess error worktree_path=%s err=%s",
            worktree_path, exc,
        )
        rc = 1
        stderr_raw = f"SubprocessError: {exc}"

    duration_ms = int((time.monotonic() - start) * 1000)
    log_tail = _trim_stderr(stderr_raw)
    status: Literal["passed", "failed"] = "passed" if rc == 0 else "failed"

    logging.info(
        "run_worktree_setup: done owner=%s rc=%d status=%s duration_ms=%d",
        owner, rc, status, duration_ms,
    )
    return SetupResult(
        status=status,
        rc=rc,
        duration_ms=duration_ms,
        log_tail=log_tail,
    )


# ============================================================================
# 解析主 worktree 根（resolve_main_repo_root · P1-3）
# ============================================================================

def resolve_main_repo_root(worktree_path: Path) -> Path:
    """从任意 worktree（含 main worktree）解析主 worktree 根。

    实现（来源：detailed-design.md:447-467）：在 worktree_path 下执行
    `git worktree list --porcelain`；按规范第一段即主 worktree。
    解析首段 `worktree <path>` 行取 path 即主仓根。

    **不**用 `git rev-parse --git-common-dir + dirname` 推路径：
    common-dir 形态是 git 内部实现细节，按层级 dirname 推容易受 git 版本 /
    路径布局 / 子模块嵌套影响。

    入参：worktree_path — 任意 worktree 路径
    返回：主仓根（绝对路径）
    异常：
      - subprocess 失败 / git rc!=0 → WorktreeBootstrapError(reason='other')
      - porcelain 首段不含 'worktree ' 行 → WorktreeBootstrapError(reason='porcelain_malformed')
      - 解析得到的 path 不在 FS → WorktreeBootstrapError(reason='main_root_missing')
    """
    proc = _run_git(["worktree", "list", "--porcelain"], cwd=worktree_path)
    if proc.returncode != 0:
        stderr_trim = _trim_stderr(proc.stderr)
        raise WorktreeBootstrapError(
            f"git worktree list --porcelain failed rc={proc.returncode} stderr={stderr_trim}",
            reason="other",
            branch_created=False,
        )

    stdout = proc.stdout
    # porcelain 输出按空行分段，每段第一行为 `worktree <path>`
    first_segment = stdout.split("\n\n", 1)[0] if stdout else ""
    first_line = first_segment.splitlines()[0] if first_segment else ""

    if not first_line.startswith("worktree "):
        raise WorktreeBootstrapError(
            f"porcelain output malformed: first_line={first_line!r}",
            reason="porcelain_malformed",
            branch_created=False,
        )

    main_path = Path(first_line[len("worktree "):].strip())
    if not main_path.exists():
        raise WorktreeBootstrapError(
            f"resolved main root does not exist: {main_path}",
            reason="main_root_missing",
            branch_created=False,
        )

    logging.debug(
        "resolve_main_repo_root: from=%s → main=%s", worktree_path, main_path,
    )
    return main_path


# ============================================================================
# 三重保护清理 worktree（cleanup_worktree_if_owned · D-008 / D-009 / P1-3）
# ============================================================================

def _check_owner_guard(worktree_meta: Optional[dict]) -> Optional[CleanupResult]:
    """cleanup 保护 1：检查 meta.worktree.owner（来源：detailed-design.md:473）。

    短路场景（返 CleanupResult）：
      - meta 缺 worktree 字段（旧需求迁移前）→ skipped/legacy_no_worktree_field
      - owner='external'（用户挂的 worktree）→ skipped/external
      - owner ∉ {'workflow'}（owner='none' 或未知值）→ skipped/external
        （安全保留，视同 external 处理）
    返回 None 表示通过，进入保护 2/3。
    """
    if not isinstance(worktree_meta, dict):
        logging.info(
            "cleanup_worktree_if_owned: legacy meta has no 'worktree' field",
        )
        return CleanupResult(
            action="skipped",
            reason="legacy_no_worktree_field",
            removed_path=None,
        )

    owner = worktree_meta.get("owner", "none")
    if owner == "external":
        logging.info("cleanup_worktree_if_owned: skipped owner=external")
        return CleanupResult(
            action="skipped",
            reason="external",
            removed_path=None,
        )
    if owner != "workflow":
        # owner=none / 未知值 → 视同 external 安全保留
        logging.info(
            "cleanup_worktree_if_owned: skipped owner=%s (non-workflow)",
            owner,
        )
        return CleanupResult(
            action="skipped",
            reason="external",
            removed_path=None,
        )
    return None


def _check_path_whitelist(
    main_repo_root: Path,
    worktree_meta: dict,
) -> tuple[Optional[Path], Optional[CleanupResult]]:
    """cleanup 保护 2：路径白名单（规范化 + 容器硬编码）。

    白名单基准 location **硬编码**为 `main_repo_root / _DEFAULT_WORKTREE_DIR`，
    **不读** meta.yaml.worktree.location 字段——避免 attacker 通过同时设置
    meta.worktree.{path: '/etc/passwd', location: '/'} 让
    `is_relative_to(/)` 恒真绕过白名单（G-2 rev3 修复）。

    raw_path 仍来自 meta 但规范化后必须 is_relative_to 主仓
    `_DEFAULT_WORKTREE_DIR/`，对应同时挡住 '../' 反向遍历。

    入参：
      main_repo_root — 主仓根
      worktree_meta  — meta.yaml.worktree 段（dict）
    返回：
      (resolved_path, None) — 通过，下游可直接使用绝对规范化路径
      (None, CleanupResult) — aborted，调用方直接返回
    """
    raw_path = worktree_meta.get("path", "")
    if not raw_path:
        logging.warning(
            "cleanup_worktree_if_owned: aborted empty raw_path",
        )
        return None, CleanupResult(
            action="aborted",
            reason="path_not_in_whitelist",
            removed_path=None,
        )

    try:
        resolved_path = (main_repo_root / Path(raw_path)).resolve()
        resolved_location = (main_repo_root / _DEFAULT_WORKTREE_DIR).resolve()
        is_in_whitelist = resolved_path.is_relative_to(resolved_location)
    except (OSError, ValueError):
        is_in_whitelist = False
    if not is_in_whitelist:
        logging.warning(
            "cleanup_worktree_if_owned: aborted path=%r not under %s/",
            raw_path,
            _DEFAULT_WORKTREE_DIR,
        )
        return None, CleanupResult(
            action="aborted",
            reason="path_not_in_whitelist",
            removed_path=None,
        )
    return resolved_path, None


def _execute_remove_prune(
    main_repo_root: Path,
    worktree_path: Path,
) -> CleanupResult:
    """三重保护全过后真正动手：git worktree remove + prune（来源：detailed-design.md:483）。

    remove 与 prune **非原子**：remove 后 prune 前若并发 create_worktree
    用同名分支，调用方需处理 path_or_branch_exists 重试（G-6 follow-up）。

    异常 / rc 处理（G-9 区分 remove vs prune）：
      - remove rc!=0 / WorktreeBootstrapError →
        CleanupResult(action='failed', reason='git_failure') + log ERROR
      - prune rc!=0 / WorktreeBootstrapError →
        仅 log（warning / error）；worktree 已成功 remove，prune 失败不回滚，
        仍返 CleanupResult(action='removed')

    入参：
      main_repo_root — 主仓根（cwd）
      worktree_path  — 已通过保护 2/3 的规范化绝对路径
    返回：CleanupResult
    """
    try:
        remove_proc = _run_git(
            ["worktree", "remove", str(worktree_path)],
            cwd=main_repo_root,
        )
    except WorktreeBootstrapError as exc:
        logging.error(
            "cleanup_worktree_if_owned: git worktree remove raised %s "
            "(reason=%s); 转 CleanupResult(action='failed')",
            exc, exc.reason,
        )
        return CleanupResult(
            action="failed",
            reason="git_failure",
            removed_path=None,
        )
    if remove_proc.returncode != 0:
        logging.error(
            "cleanup_worktree_if_owned: git worktree remove failed rc=%d stderr=%s",
            remove_proc.returncode, _trim_stderr(remove_proc.stderr),
        )
        return CleanupResult(
            action="failed",
            reason="git_failure",
            removed_path=None,
        )

    try:
        prune_proc = _run_git(
            ["worktree", "prune"],
            cwd=main_repo_root,
        )
    except WorktreeBootstrapError as exc:
        # prune 灾难级失败也不致命（worktree 已 remove）；记 ERROR 但返 removed
        logging.error(
            "cleanup_worktree_if_owned: git worktree prune raised %s "
            "(reason=%s); worktree already removed",
            exc, exc.reason,
        )
    else:
        if prune_proc.returncode != 0:
            # prune 失败不致命（worktree 已 remove）；记 warning 但仍返回 removed
            logging.warning(
                "cleanup_worktree_if_owned: git worktree prune non-zero rc=%d "
                "stderr=%s (worktree already removed)",
                prune_proc.returncode, _trim_stderr(prune_proc.stderr),
            )

    logging.info(
        "cleanup_worktree_if_owned: removed worktree_path=%s", worktree_path,
    )
    return CleanupResult(
        action="removed",
        reason="workflow_ok",
        removed_path=worktree_path,
    )


def cleanup_worktree_if_owned(meta: dict, main_repo_root: Path) -> CleanupResult:
    """三重保护清理 worktree（来源：detailed-design.md:470-487 / D-008 / D-009 / P1-3）。

    保护 1（_check_owner_guard）：meta.worktree.owner == 'workflow'
      - owner='external' → CleanupResult(action='skipped', reason='external')
      - meta 缺 worktree 字段 → CleanupResult(action='skipped',
        reason='legacy_no_worktree_field')

    保护 2（_check_path_whitelist）：meta.worktree.path 规范化后必须位于
            主仓 `_DEFAULT_WORKTREE_DIR/`（**容器硬编码**，不读 meta.location）
      - 白名单失败 → CleanupResult(action='aborted', reason='path_not_in_whitelist')

    保护 3：main_repo_root != worktree_path（纯入参对比，**不读 cwd**）
      - 相等 → CleanupResult(action='aborted', reason='main_root_equals_worktree')

    全部通过 → 在 main_repo_root cwd 下调 git worktree remove <path> + git worktree prune
      - 详细 rc 处理见 _execute_remove_prune

    入参：
      meta            — 从 meta.yaml 加载的字典（read-only）
      main_repo_root  — 调用方先用 resolve_main_repo_root 解出的主仓根
    返回：CleanupResult
    异常：本函数不向外抛；
      - remove rc!=0 / WorktreeBootstrapError → CleanupResult(action='failed',
        reason='git_failure')
      - prune rc!=0 / WorktreeBootstrapError → 仅 log.error，仍返
        CleanupResult(action='removed')（worktree 已成功 remove，prune 失败不回滚）
    """
    worktree_meta = meta.get("worktree") if isinstance(meta, dict) else None

    # 保护 1：owner guard
    early = _check_owner_guard(worktree_meta)
    if early is not None:
        return early

    # 类型缩窄：保护 1 通过后 worktree_meta 必是 dict
    assert isinstance(worktree_meta, dict)

    # 保护 2：路径白名单（容器硬编码 + 规范化反向遍历防护）
    resolved_path, abort = _check_path_whitelist(main_repo_root, worktree_meta)
    if abort is not None:
        return abort
    assert resolved_path is not None

    # 保护 3：self-remove guard（复用 resolved_main，避免重复 resolve）
    resolved_main = main_repo_root.resolve()
    if resolved_main == resolved_path:
        logging.error(
            "cleanup_worktree_if_owned: aborted main_repo_root == worktree_path (%s)",
            main_repo_root,
        )
        return CleanupResult(
            action="aborted",
            reason="main_root_equals_worktree",
            removed_path=None,
        )

    # 三重保护全过 → 真正动手
    return _execute_remove_prune(main_repo_root, resolved_path)
