"""F-002 / F-004 · requirement bootstrap helpers（worktree-first 改造版）。

包含：
  - 异常类：BootstrapError（F-004 起携带 reason / retain_worktree 字段）
  - 渲染/工具函数：_render_meta_yaml / _render_plan_md / _strip_req_prefix / _now_shanghai_str
  - bootstrap 步骤：
      _write_artifact_file / _write_bootstrap_artifacts
      _checkout_feature_branch（policy=never 老路径）
      _setup_worktree_or_branch / _bind_current_worktree（F-004 新增）
      _load_yaml_worktree_cfg（F-004 新增）
      _resolve_base_branch
  - 主入口：_bootstrap_requirement / _bootstrap_rollback

F-004 改造要点（来源：detailed-design.md §3.4）：
  - 写产物落点改为 worktree path（active_repo_root），主仓根 requirements/<key>/ 不创建
  - rollback 顺序：worktree remove + prune → branch -D → rmtree 主仓根 + worktree path 双扫
  - baseline 失败（required=true）保留现场，不进 rollback
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError  # noqa: E402
from run_state import append_event  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover  避免运行时循环 import
    import worktree_manager
    from worktree_manager import SetupResult, WorktreeInfo

# requirement 类 base_branch 选择优先级（develop 优先，兜底 main/master）
_BASE_BRANCH_PRIORITY: tuple[str, ...] = ("develop", "main", "master")

# Asia/Shanghai 固定偏移（CST = UTC+8，无 DST 困扰）
_CST_TZ = timezone(timedelta(hours=8))

# git 子进程默认超时（秒）；分支操作通常 < 1s，5s 足够
_GIT_TIMEOUT_SECONDS = 5

# 模板源目录（managing-requirement-lifecycle Skill 持有真实模板，本模块只读）
_TEMPLATE_DIR_RELATIVE = Path(".claude/skills/managing-requirement-lifecycle/templates")


# ============================================================================
# F-002 / F-004 异常体系
# ============================================================================

class BootstrapError(WorkflowError):
    """bootstrap 过程任一步失败时抛出。

    携带：
      - artifacts_created / branch_created：rollback 精确反向撤销标志
      - reason（F-004 加入）：失败原因枚举字符串，调用方（F-003 _run_requirement）
        据此决定是否 retry。常用值见 detailed-design.md §5.1：
          path_or_branch_exists / other / policy_current_in_normal_repo /
          worktree_dir_not_ignored / baseline_failed_required /
          porcelain_malformed / main_root_missing
      - retain_worktree（F-004 加入）：True 表示调用方应保留 worktree / 分支 /
        requirements/<key>/ 现场（baseline_failed_required 落点）。
      - worktree_info（F-004 rev2 加入）：bootstrap 创建/绑定的 WorktreeInfo
        透传给 caller-side _bootstrap_rollback，让 rollback 步骤 1
        worktree remove 守卫可触发；rev1 漏传 → 孤儿 worktree。

    继承 WorkflowError 以便上层 except 链复用既有兜底。子类
    WorktreeBootstrapError 已默认带 reason / retain_worktree；F-004 把这两个字段
    并入父类后，子类签名保持兼容（is-a 关系不破）。
    """

    def __init__(
        self,
        message: str,
        *,
        artifacts_created: bool = False,
        branch_created: bool = False,
        reason: str = "other",
        retain_worktree: bool = False,
        worktree_info: Optional["WorktreeInfo"] = None,
    ) -> None:
        super().__init__(message)
        self.artifacts_created = artifacts_created
        self.branch_created = branch_created
        self.reason = reason
        self.retain_worktree = retain_worktree
        self.worktree_info = worktree_info


# ============================================================================
# 工具函数：分支名 / 当前分支 / 时间格式
# ============================================================================

def _strip_req_prefix(req_id: str) -> str:
    """REQ-2026-010 → 2026-010（小写），feat/req-<这部分> 用。

    新格式 YYYYMMDD-<slug> 直接小写返回（不去前缀）。
    """
    if req_id.startswith("REQ-"):
        return req_id[len("REQ-"):].lower()
    return req_id.lower()


def _current_branch(repo_root: Path) -> str:
    """git rev-parse --abbrev-ref HEAD；失败返回空串。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            logging.debug("git rev-parse HEAD 失败 rc=%d stderr=%s", result.returncode, result.stderr)
            return ""
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        logging.debug("_current_branch 失败：%s", exc)
        return ""


def _resolve_base_branch(repo_root: Path) -> str:
    """按 develop > main > master 优先级返回第一个可用的本地分支名。"""
    for branch in _BASE_BRANCH_PRIORITY:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
                timeout=_GIT_TIMEOUT_SECONDS,
            )
            if result.returncode == 0:
                return branch
        except (subprocess.SubprocessError, OSError) as exc:
            logging.debug("_resolve_base_branch %s 校验失败：%s", branch, exc)
    return ""


def _now_shanghai_str() -> str:
    """返回当前 Asia/Shanghai 时间，格式 YYYY-MM-DD HH:MM:SS（time-format.md 约定）。"""
    return datetime.now(_CST_TZ).strftime("%Y-%m-%d %H:%M:%S")


# ============================================================================
# 模板渲染：meta.yaml / plan.md
# ============================================================================

def _infer_default_project() -> str:
    """bootstrap 时推断 meta.yaml.project 字段（Bug-2）。

    规则（codex P2 修订后）：
      - context/project/<X>/ 单个目录 → 返回 <X>
      - 多目录 → 返回空 + warning（要求用户显式编辑 meta.yaml；不静默自动选避免
        多 project 仓库误绑定到字典序首项）
      - 零目录 → 返回空

    多 project 时返回空让 check_meta 在 bootstrap 阶段已放宽路径通过，
    并以 warning 提示用户在 definition 阶段离开前手工填 project 字段。
    """
    project_root = REPO_ROOT / "context" / "project"
    if not project_root.is_dir():
        return ""
    candidates = sorted(
        p.name for p in project_root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    if not candidates:
        return ""
    if len(candidates) == 1:
        return candidates[0]
    logging.warning(
        "_infer_default_project: 发现多个 project (%s)，bootstrap 不自动选；"
        "请在 definition 阶段离开前手工编辑 meta.yaml.project 字段指向目标 project",
        candidates,
    )
    return ""


def _render_meta_yaml(
    req_id: str,
    title: str,
    branch: str,
    base_branch: str,
    *,
    worktree_info: Optional["WorktreeInfo"] = None,
    baseline_result: Optional["SetupResult"] = None,
) -> str:
    """渲染 meta.yaml（流程组 + worktree 段）。

    F-008 阶段只填占位符；F-004 起当 worktree_info 非空时**回填**真实 worktree 元信息
    （enabled/owner/path/absolute_path/created_at + baseline.status 等）。

    Args:
      req_id / title / branch / base_branch — 流程组 4 字段
      worktree_info — 由 _setup_worktree_or_branch 返回；None 表示未启用 worktree
      baseline_result — run_worktree_setup 返回；None 表示 baseline 未跑或被跳过

    base_branch 缺省走 "main" 兜底；worktree_info=None 时所有 worktree 字段走
    F-008 安全占位（enabled=false / owner=none / path="" / status=skipped）。
    worktree.state 主状态机（active / baseline_failed）落入 process.txt
    而非 meta；本函数仅承载 baseline.status 字段渲染（详细设计 §2.3）。
    """
    template_path = REPO_ROOT / _TEMPLATE_DIR_RELATIVE / "meta.yaml.tmpl"
    raw = template_path.read_text(encoding="utf-8")

    base_branch_resolved = base_branch or "main"

    # 默认占位（F-008 安全态：未启用 worktree）
    wt_enabled = "false"
    wt_owner = "none"
    wt_path = '""'
    wt_abs_path = '""'
    wt_branch = branch
    wt_base_branch = base_branch_resolved
    wt_created_at = '""'
    wt_baseline_cmd = "make gates-validate"
    wt_baseline_status = "skipped"
    wt_baseline_completed = '""'

    # F-004：worktree 实际创建/绑定后回填
    # rev2 F-5：owner='none'（policy=never 兜底）时仍走占位路径——与 run-state.jsonl
    # workflow_started 事件 (worktree_info.owner != 'none') 判定保持一致；否则
    # meta.enabled=true 但 jsonl enabled=false，下游 dispatch / status 会困惑。
    if worktree_info is not None and worktree_info.owner != "none":
        wt_enabled = "true"
        wt_owner = worktree_info.owner
        # path: worktree path 相对主仓根（容器硬编码 .worktrees/feat-req-<key>）
        try:
            rel_path = worktree_info.path.relative_to(REPO_ROOT)
            wt_path = f'"{rel_path}"'
        except ValueError:
            # 不在主仓根下（current 路径绑定 + main worktree）→ 留空串
            wt_path = '""'
        wt_abs_path = f'"{worktree_info.path}"'
        wt_branch = worktree_info.branch
        wt_base_branch = worktree_info.base_branch or base_branch_resolved
        if worktree_info.created:
            wt_created_at = f'"{_now_shanghai_str()}"'
        else:
            wt_created_at = '""'

    if baseline_result is not None:
        wt_baseline_status = baseline_result.status
        if baseline_result.status != "skipped":
            wt_baseline_completed = f'"{_now_shanghai_str()}"'

    replacements = {
        "__REQ_ID__": req_id,
        "__TITLE__": title,
        "__CREATED_AT__": _now_shanghai_str(),
        "__BRANCH__": branch,
        "__BASE_BRANCH__": base_branch_resolved,
        "__PROJECT__": _infer_default_project(),
        "__WT_ENABLED__": wt_enabled,
        "__WT_OWNER__": wt_owner,
        "__WT_PATH__": wt_path,
        "__WT_ABS_PATH__": wt_abs_path,
        "__WT_BRANCH__": wt_branch,
        "__WT_BASE_BRANCH__": wt_base_branch,
        "__WT_CREATED_AT__": wt_created_at,
        "__WT_BASELINE_CMD__": wt_baseline_cmd,
        "__WT_BASELINE_STATUS__": wt_baseline_status,
        "__WT_BASELINE_COMPLETED_AT__": wt_baseline_completed,
    }
    rendered = raw
    for key, val in replacements.items():
        rendered = rendered.replace(key, val)
    return rendered


def _render_plan_md(req_id: str, title: str) -> str:
    """基于 plan.md.tmpl 渲染——只替换 __REQ_ID__ / __TITLE__ 两个占位符。"""
    template_path = REPO_ROOT / _TEMPLATE_DIR_RELATIVE / "plan.md.tmpl"
    raw = template_path.read_text(encoding="utf-8")
    return raw.replace("__REQ_ID__", req_id).replace("__TITLE__", title)


# ============================================================================
# F-004 yaml.worktree 段读取（fail-soft，缺 yaml 解析能力时 fallback 空 dict）
# ============================================================================

def _load_yaml_worktree_cfg(template_path: Optional[Path]) -> dict[str, Any]:
    """从 workflow yaml 模板顶层读 worktree: 段；任何失败 fallback {}.

    使用 PyYAML 时尝试 safe_load；模块不可用或解析异常时不阻断 bootstrap，
    返回空 dict 让上层走默认 policy=auto + required=false 路径。
    """
    if not template_path:
        return {}
    try:
        text = Path(template_path).read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        logging.debug("_load_yaml_worktree_cfg 读 %s 失败：%s", template_path, exc)
        return {}
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
    except ImportError:
        logging.debug("_load_yaml_worktree_cfg: pyyaml 不可用，fallback 空 dict")
        return {}
    except Exception as exc:  # noqa: BLE001  yaml 解析异常（语法 / 非 dict 顶层）
        # F-004 rev2 F-13：升 warning 让用户感知 yaml 配置异常
        logging.warning(
            "_load_yaml_worktree_cfg: yaml worktree config parse failed; "
            "falling back to defaults (path=%s): %s",
            template_path, exc,
        )
        return {}
    if not isinstance(data, dict):
        logging.warning(
            "_load_yaml_worktree_cfg: top-level not dict; falling back to defaults (path=%s)",
            template_path,
        )
        return {}
    wt = data.get("worktree")
    return wt if isinstance(wt, dict) else {}


# ============================================================================
# bootstrap 步骤：单文件写 / 切分支 / worktree 编排
# ============================================================================

def _write_artifact_file(
    path: Path,
    content: str,
    *,
    req_id: str,
    step_name: str,
) -> None:
    """写单个 bootstrap 产物文件；失败时抛 BootstrapError(artifacts_created=True)。"""
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise BootstrapError(
            f"bootstrap req_id={req_id} step={step_name} 写文件失败：{exc}",
            artifacts_created=True,
            branch_created=False,
        ) from exc
    logging.info("bootstrap req_id=%s step=write_%s done", req_id, step_name)


def _write_bootstrap_artifacts(
    req_dir: Path,
    req_id: str,
    title: str,
    base_branch: str,
    *,
    active_repo_root: Optional[Path] = None,
    worktree_info: Optional["WorktreeInfo"] = None,
    baseline_result: Optional["SetupResult"] = None,
    branch_created: bool = False,
) -> None:
    """渲染并写 meta.yaml / plan.md / process.txt 三个 bootstrap 产物。

    F-004：req_dir 必须位于 `active_repo_root / requirements / <req_id>` 下；
    active_repo_root 显式入参避免 R1 路径错乱（主仓 vs worktree path）。
    worktree_info / baseline_result 透传给 _render_meta_yaml 回填 worktree 段。

    rev2 F-10：helper `_write_artifact_file` 自身不知 branch_created 的真实值
    （只能默认 False），由本函数在 caller-side 捕获并重抛——附带本上下文真实
    的 branch_created / worktree_info，避免 rollback 信号丢失。
    """
    # active_repo_root 仅做断言（防呼叫方传错），落点已由 req_dir 决定。
    if active_repo_root is not None:
        try:
            req_dir.relative_to(active_repo_root)
        except ValueError:
            logging.warning(
                "bootstrap req_id=%s req_dir=%s 不在 active_repo_root=%s 下，"
                "请检查调用方参数",
                req_id, req_dir, active_repo_root,
            )

    branch_name = f"feat/req-{_strip_req_prefix(req_id)}"
    meta_content = _render_meta_yaml(
        req_id, title, branch_name, base_branch,
        worktree_info=worktree_info,
        baseline_result=baseline_result,
    )
    try:
        _write_artifact_file(req_dir / "meta.yaml", meta_content, req_id=req_id, step_name="meta.yaml")
        plan_content = _render_plan_md(req_id, title)
        _write_artifact_file(req_dir / "plan.md", plan_content, req_id=req_id, step_name="plan.md")
        _write_artifact_file(req_dir / "process.txt", "", req_id=req_id, step_name="process.txt")
    except BootstrapError as exc:
        # rev2 F-10：用本函数上下文的 branch_created + worktree_info 重抛，避免 helper
        # 内硬编码 branch_created=False / worktree_info=None 导致 rollback 信号丢失。
        raise BootstrapError(
            str(exc),
            artifacts_created=True,
            branch_created=branch_created,
            reason=getattr(exc, "reason", "other"),
            worktree_info=worktree_info,
        ) from exc


def _checkout_feature_branch(req_id: str, repo_root: Path, base_branch: str = "") -> str:
    """git checkout -b feat/req-<id> [<base_branch>]（policy=never 的兜底路径）。"""
    branch = f"feat/req-{_strip_req_prefix(req_id)}"
    cmd = ["git", "checkout", "-b", branch]
    if base_branch:
        cmd.append(base_branch)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise BootstrapError(
            f"git checkout -b {branch} 失败（子进程错误）：{exc}",
            artifacts_created=True,
            branch_created=False,
            reason="other",
        ) from exc
    if result.returncode != 0:
        # 与 worktree path/branch already exists 同语义：触发 F-003 retry
        stderr = result.stderr.strip()
        is_collision = "already exists" in stderr
        raise BootstrapError(
            f"git checkout -b {branch} 失败 rc={result.returncode}: {stderr}",
            artifacts_created=True,
            branch_created=False,
            reason="path_or_branch_exists" if is_collision else "other",
        )
    return branch


def _bind_current_worktree(
    state: "worktree_manager.WorktreeState",
    req_id: str,
    base_branch: str,
) -> "WorktreeInfo":
    """D-004 复用路径：已在 linked worktree 内 → 直接绑定。

    owner='external' 表示 harness 创建的 worktree 不归 workflow 拥有，
    archive 阶段 cleanup_worktree_if_owned 见到 external 会自动跳过。
    """
    from worktree_manager import WorktreeInfo  # 局部导入避免顶层循环依赖
    branch = state.branch if state.branch else f"feat/req-{_strip_req_prefix(req_id)}"
    logging.info(
        "bootstrap req_id=%s step=bind_current_worktree path=%s branch=%s",
        req_id, state.worktree_path, branch,
    )
    return WorktreeInfo(
        path=state.worktree_path,
        branch=branch,
        base_branch=base_branch,
        owner="external",
        created=False,
    )


def _setup_worktree_or_branch(
    req_id: str,
    repo_root: Path,
    base_branch: str,
    *,
    worktree_policy: str,
    yaml_worktree_cfg: dict[str, Any],
) -> "WorktreeInfo":
    """根据 policy 决策 create / bind / fallback 到旧分支路径。

    输入 policy ∈ {auto, never, require, current}，决策矩阵见
    detailed-design.md §2.4 子状态机。

    异常：
      - policy=current + 非 linked worktree → BootstrapError(reason='policy_current_in_normal_repo')
      - create_worktree 抛 WorktreeBootstrapError → 透传（is-a BootstrapError）
    """
    import worktree_manager  # 局部导入避免顶层循环依赖
    import requirement_naming  # 同上

    state = worktree_manager.detect_worktree_state(repo_root)

    # policy=current：必须已在 linked worktree（fail-closed）
    if worktree_policy == "current" and not state.is_linked_worktree:
        raise BootstrapError(
            "worktree policy=current 要求在 linked worktree 中运行，"
            "当前在 normal repo；请先 cd 到 .worktrees/feat-req-<key> 目录后重试",
            artifacts_created=False,
            branch_created=False,
            reason="policy_current_in_normal_repo",
        )

    # 已在 linked worktree → bind（D-004）；policy=never 也走 bind（沿用当前）
    if state.is_linked_worktree:
        return _bind_current_worktree(state, req_id, base_branch)

    # policy=never → 老路径 _checkout_feature_branch
    if worktree_policy == "never":
        branch = _checkout_feature_branch(req_id, repo_root, base_branch=base_branch)
        return worktree_manager.WorktreeInfo(
            path=repo_root,
            branch=branch,
            base_branch=base_branch,
            owner="none",
            created=False,
        )

    # auto / require：创建新 worktree
    branch = requirement_naming.branch_for_requirement_key(req_id)
    preference = yaml_worktree_cfg.get("location", ".worktrees") or ".worktrees"
    location = worktree_manager.select_worktree_location(
        repo_root, branch, preference=preference,
    )
    # ensure 容器目录已被 .gitignore 收录（fail-closed reason='worktree_dir_not_ignored'）
    worktree_manager.ensure_worktree_dir_ignored(repo_root, location)
    info = worktree_manager.create_worktree(repo_root, branch, base_branch, location)
    logging.info(
        "bootstrap req_id=%s step=create_worktree path=%s branch=%s base=%s",
        req_id, info.path, info.branch, info.base_branch,
    )
    return info


# ============================================================================
# F-004 主入口：_bootstrap_requirement / _bootstrap_rollback
# ============================================================================

def _bootstrap_requirement(
    req_id: str,
    title: str,
    template_id: str,
    template_path: Path,
    arguments: str,
    repo_root: Path,
    *,
    worktree_policy: Optional[str] = None,
    no_worktree: bool = False,
) -> Path:
    """需求类 bootstrap 主入口（worktree-first 流程）。

    详细设计 §3.4 改造点 2 步骤 1-8：
      1. 读 yaml.worktree 段 + 决定 policy
      2. _setup_worktree_or_branch → WorktreeInfo（建/复用 worktree）
      3. run_worktree_setup baseline；required=true + rc!=0 → 写 meta + 抛 retain_worktree=True
      4. mkdir <active_repo_root>/requirements/<req_id>/artifacts/
      5-6. 渲染并写 meta.yaml / plan.md / process.txt（落 worktree path）
      7. 写 workflow_started run-state.jsonl
      8. 输出成功 banner（由调用方 _run_requirement 负责）

    返回：active_repo_root/requirements/<req_id>/ 路径（worktree path 下，
          policy=never 时退化为主仓根下）。
    """
    import worktree_manager  # 局部导入

    # 步骤 1：解析 yaml.worktree 段 + policy
    yaml_worktree_cfg = _load_yaml_worktree_cfg(template_path)
    effective_policy = _resolve_worktree_policy(
        no_worktree=no_worktree,
        cli_policy=worktree_policy,
        yaml_cfg=yaml_worktree_cfg,
    )
    base_branch = _resolve_base_branch(repo_root)

    # 步骤 2：建/绑定 worktree（抛 WorktreeBootstrapError 透传给 caller）
    worktree_info = _setup_worktree_or_branch(
        req_id, repo_root, base_branch,
        worktree_policy=effective_policy,
        yaml_worktree_cfg=yaml_worktree_cfg,
    )
    branch_created = worktree_info.created or (worktree_info.owner == "none")
    active_repo_root = worktree_info.path

    # 步骤 3：baseline 校验（baseline 失败 + required=true → 保留现场）
    # owner='none'（policy=never 兜底 / 无 worktree）→ 跳过 baseline，与 'external' 同语义
    baseline_required = bool(
        yaml_worktree_cfg.get("setup", {})
                          .get("baseline", {})
                          .get("required", False)
    )
    if worktree_info.owner == "none":
        baseline_result = worktree_manager.SetupResult(
            status="skipped", rc=0, duration_ms=0, log_tail="",
        )
    else:
        baseline_result = worktree_manager.run_worktree_setup(
            active_repo_root,
            yaml_worktree_cfg,
            owner=worktree_info.owner,
        )
    if baseline_result.status == "failed":
        if baseline_required:
            # 保留现场：写 meta.yaml + 抛 retain_worktree=True，不触发 rollback
            _persist_baseline_failed_state(
                req_id, title, base_branch, active_repo_root,
                worktree_info, baseline_result,
            )
            raise BootstrapError(
                f"baseline 失败（required=true）req_id={req_id} rc={baseline_result.rc} "
                f"log_tail={baseline_result.log_tail[:200]!r}；"
                f"worktree 已保留供排查：{active_repo_root}",
                artifacts_created=True,
                branch_created=branch_created,
                reason="baseline_failed_required",
                retain_worktree=True,
                worktree_info=worktree_info,
            )
        else:
            logging.warning(
                "bootstrap req_id=%s baseline failed but required=false，继续写产物（log_tail=%s）",
                req_id, baseline_result.log_tail[:200],
            )

    # 步骤 4：mkdir <active_repo_root>/requirements/<req_id>/artifacts/
    req_dir = active_repo_root / "requirements" / req_id
    try:
        (req_dir / "artifacts").mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        # 主仓根 requirements/<key>/ 未创建过（worktree-first 流程不预建），失败标记
        # artifacts_created=True 让 rollback 双扫 rmtree 兜底（worktree path 也清理）
        raise BootstrapError(
            f"创建 {req_dir}/artifacts/ 失败：{exc}",
            artifacts_created=True,
            branch_created=branch_created,
            reason="other",
            worktree_info=worktree_info,
        ) from exc
    logging.info(
        "bootstrap req_id=%s step=mkdir_artifacts active_root=%s",
        req_id, active_repo_root,
    )

    # 步骤 5-6：渲染并写 meta.yaml / plan.md / process.txt（worktree-first 落点）
    _write_bootstrap_artifacts(
        req_dir, req_id, title, base_branch,
        active_repo_root=active_repo_root,
        worktree_info=worktree_info,
        baseline_result=baseline_result,
        branch_created=branch_created,
    )

    # 步骤 7：写 workflow_started jsonl 事件
    jsonl_path = req_dir / "run-state.jsonl"
    try:
        try:
            template_rel = str(template_path.relative_to(repo_root)) if template_path else ""
        except ValueError:
            template_rel = str(template_path) if template_path else ""
        append_event(jsonl_path, {
            "type": "workflow_started",
            "run_id": req_id,
            "data": {
                "workflow_name": template_id,
                "arguments": arguments,
                "template_path": template_rel,
                "title": title,
                "worktree": {
                    "enabled": worktree_info.owner != "none",
                    "owner": worktree_info.owner,
                    "path": str(worktree_info.path),
                    "branch": worktree_info.branch,
                },
            },
        })
    except WorkflowError as exc:
        raise BootstrapError(
            f"写 workflow_started 事件失败：{exc}",
            artifacts_created=True,
            branch_created=branch_created,
            reason="other",
            worktree_info=worktree_info,
        ) from exc
    logging.info("bootstrap req_id=%s step=workflow_started done", req_id)

    # 步骤 8：成功 banner 由调用方 _run_requirement 输出。把 WorktreeInfo 通过
    # req_dir 隐式传递（_run_requirement 暂不消费 WorktreeInfo；F-003 调用层
    # 仅依赖 req_dir 路径），保持向后兼容。
    return req_dir


def _resolve_worktree_policy(
    *,
    no_worktree: bool,
    cli_policy: Optional[str],
    yaml_cfg: dict[str, Any],
) -> str:
    """policy 决策优先级（来源：F-003 task context "yaml worktree 配置读取"）：
      --no-worktree=True > CLI --worktree-policy > yaml.worktree.policy > "auto"
    """
    if no_worktree:
        return "never"
    if cli_policy:
        return cli_policy
    yaml_policy = yaml_cfg.get("policy")
    if isinstance(yaml_policy, str) and yaml_policy:
        return yaml_policy
    return "auto"


def _persist_baseline_failed_state(
    req_id: str,
    title: str,
    base_branch: str,
    active_repo_root: Path,
    worktree_info: "WorktreeInfo",
    baseline_result: "SetupResult",
) -> None:
    """baseline 失败 (required=true) 时尽力把 meta.yaml + process.txt 写到 worktree
    供排查。best-effort：写入失败 logging.error 但不抛——根因 BootstrapError 优先透传。
    """
    req_dir = active_repo_root / "requirements" / req_id
    try:
        (req_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        meta_text = _render_meta_yaml(
            req_id, title,
            f"feat/req-{_strip_req_prefix(req_id)}",
            base_branch,
            worktree_info=worktree_info,
            baseline_result=baseline_result,
        )
        (req_dir / "meta.yaml").write_text(meta_text, encoding="utf-8")
        # process.txt 写一行 blocker 提示
        diag = f"[blocker] baseline failed (rc={baseline_result.rc}): {baseline_result.log_tail[:300]}\n"
        (req_dir / "process.txt").write_text(diag, encoding="utf-8")
    except OSError as exc:
        logging.error(
            "_persist_baseline_failed_state req_id=%s 写诊断失败：%s",
            req_id, exc,
        )


def _rollback_remove_worktree(
    req_id: str,
    repo_root: Path,
    worktree_info: Optional["WorktreeInfo"],
) -> None:
    """rollback step 1：worktree remove + prune。

    只在 owner='workflow' + created=True 时操作；其它 owner 表示 worktree 由 harness
    或用户创建，rollback 不该擅自删——把删除权交给上层 archive 流程。
    """
    if worktree_info is None or not worktree_info.created or worktree_info.owner != "workflow":
        return
    try:
        remove_proc = subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_info.path)],
            capture_output=True, text=True,
            cwd=str(repo_root),
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
        if remove_proc.returncode != 0:
            logging.error(
                "rollback req_id=%s step=worktree_remove rc=%d stderr=%s",
                req_id, remove_proc.returncode, remove_proc.stderr.strip(),
            )
    except (subprocess.SubprocessError, OSError) as exc:
        logging.error(
            "rollback req_id=%s git worktree remove %s 失败：%s",
            req_id, worktree_info.path, exc,
        )
    try:
        prune_proc = subprocess.run(
            ["git", "worktree", "prune"],
            capture_output=True, text=True,
            cwd=str(repo_root),
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
        if prune_proc.returncode != 0:
            logging.warning(
                "rollback req_id=%s step=worktree_prune rc=%d stderr=%s",
                req_id, prune_proc.returncode, prune_proc.stderr.strip(),
            )
    except (subprocess.SubprocessError, OSError) as exc:
        logging.warning(
            "rollback req_id=%s git worktree prune 失败：%s", req_id, exc,
        )


def _rollback_delete_branch(
    req_id: str,
    repo_root: Path,
    previous_branch: str,
    branch_created: bool,
) -> None:
    """rollback step 2：checkout previous_branch + branch -D feat/req-<key>。

    与原 F-002 行为对齐：仅在 branch_created=True 时操作；previous_branch 为空时
    记 error 不抛——HEAD 仍指向待删分支会导致 -D 失败，但仍 best-effort 尝试。
    """
    if not branch_created:
        return
    branch_name = f"feat/req-{_strip_req_prefix(req_id)}"
    if previous_branch:
        try:
            checkout_result = subprocess.run(
                ["git", "checkout", previous_branch],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
                timeout=_GIT_TIMEOUT_SECONDS,
                check=False,
            )
            if checkout_result.returncode != 0:
                logging.error(
                    "rollback req_id=%s step=git_checkout rc=%d stderr=%s",
                    req_id, checkout_result.returncode,
                    checkout_result.stderr.strip(),
                )
        except (subprocess.SubprocessError, OSError) as exc:
            logging.error(
                "rollback req_id=%s git checkout %s 失败：%s",
                req_id, previous_branch, exc,
            )
    else:
        logging.error(
            "rollback req_id=%s previous_branch 为空，跳过 checkout（HEAD 可能仍在 %s）",
            req_id, branch_name,
        )

    try:
        branch_del_result = subprocess.run(
            ["git", "branch", "-D", branch_name],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
        if branch_del_result.returncode != 0:
            logging.error(
                "rollback req_id=%s step=git_branch_delete rc=%d stderr=%s",
                req_id, branch_del_result.returncode,
                branch_del_result.stderr.strip(),
            )
    except (subprocess.SubprocessError, OSError) as exc:
        logging.error(
            "rollback req_id=%s git branch -D %s 失败：%s",
            req_id, branch_name, exc,
        )


def _rollback_clean_artifacts(
    req_id: str,
    repo_root: Path,
    worktree_info: Optional["WorktreeInfo"],
    artifacts_created: bool,
) -> None:
    """rollback step 3：双扫 rmtree。

    主仓根 + worktree path 两处 requirements/<req_id> 都尝试删——
    路径错乱 / 中间态残留时一次性兜底。
    """
    if not artifacts_created:
        return
    candidates: list[Path] = [repo_root / "requirements" / req_id]
    if worktree_info is not None and worktree_info.path != repo_root:
        candidates.append(worktree_info.path / "requirements" / req_id)
    for req_dir in candidates:
        try:
            shutil.rmtree(req_dir)
        except FileNotFoundError:
            logging.debug(
                "rollback req_id=%s req_dir=%s 已不存在，跳过 rmtree",
                req_id, req_dir,
            )
        except OSError as exc:
            logging.error(
                "rollback req_id=%s rmtree %s 失败：%s",
                req_id, req_dir, exc,
            )


def _bootstrap_rollback(
    req_id: str,
    repo_root: Path,
    previous_branch: str,
    *,
    artifacts_created: bool,
    branch_created: bool,
    worktree_info: Optional["WorktreeInfo"] = None,
) -> None:
    """bootstrap 失败反向撤销（F-004 rev2 拆 3 子函数版）。

    顺序（来源：detailed-design.md §3.4 改造点 3）：
      0. cd 主仓根（cwd 可能在 worktree 内）
      1. _rollback_remove_worktree —— git worktree remove + prune
      2. _rollback_delete_branch  —— git checkout previous + branch -D
      3. _rollback_clean_artifacts —— rmtree 主仓根 + worktree path 双扫

    keyword-only 签名（rev2 F-4）防误调（位置参数易混淆 bool 顺序）。
    幂等：所有 step best-effort 失败容忍。
    baseline_failed_required 路径**不**调本函数（caller 在 retain_worktree=True
    时 skip）。
    """
    # 步骤 0：cd 主仓根
    try:
        os.chdir(repo_root)
    except OSError as exc:
        logging.error(
            "rollback req_id=%s step=chdir_main_root failed: %s", req_id, exc,
        )

    _rollback_remove_worktree(req_id, repo_root, worktree_info)
    _rollback_delete_branch(req_id, repo_root, previous_branch, branch_created)
    _rollback_clean_artifacts(req_id, repo_root, worktree_info, artifacts_created)
