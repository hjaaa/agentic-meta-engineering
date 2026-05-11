"""F-002 · requirement bootstrap helpers（从 workflow_run.py 拆出）。

包含：
  - 异常类：BootstrapError
  - 渲染/工具函数：_render_meta_yaml / _render_plan_md / _strip_req_prefix / _now_shanghai_str
  - bootstrap 步骤：_write_artifact_file / _checkout_feature_branch / _resolve_base_branch
  - 主入口：_bootstrap_requirement / _bootstrap_rollback

拆分动机：F-002 rev1 把 9 个 helper 全部堆在 workflow_run.py，导致主文件
从 213 行涨到 679 行（涨幅 218%）。本模块按"职责单一"原则把 requirement
bootstrap 链路独立成文件，让 workflow_run.py 回到"命令入口分流"的薄壳定位。

详细设计参考 detailed-design.md §1.2 / §1.3 / §1.4。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError  # noqa: E402
from run_state import append_event  # noqa: E402

# requirement 类 base_branch 选择优先级（develop 优先，兜底 main/master）
_BASE_BRANCH_PRIORITY: tuple[str, ...] = ("develop", "main", "master")

# Asia/Shanghai 固定偏移（CST = UTC+8，无 DST 困扰）
_CST_TZ = timezone(timedelta(hours=8))

# git 子进程默认超时（秒）；分支操作通常 < 1s，5s 足够
_GIT_TIMEOUT_SECONDS = 5

# 模板源目录（managing-requirement-lifecycle Skill 持有真实模板，本模块只读）
_TEMPLATE_DIR_RELATIVE = Path(".claude/skills/managing-requirement-lifecycle/templates")


# ============================================================================
# F-002 异常体系
# ============================================================================

class BootstrapError(WorkflowError):
    """bootstrap 过程任一步失败时抛出。

    携带已完成步骤标志（artifacts_created / branch_created），供 main 调用
    _bootstrap_rollback 精确反向撤销——避免"什么都没建却试图删"或"建了一半
    没清理"的两种边界。继承 WorkflowError 以便上层 except 链复用既有兜底。
    """

    def __init__(
        self,
        message: str,
        *,
        artifacts_created: bool = False,
        branch_created: bool = False,
    ) -> None:
        super().__init__(message)
        self.artifacts_created = artifacts_created
        self.branch_created = branch_created


# ============================================================================
# 工具函数：分支名 / 当前分支 / 时间格式
# ============================================================================

def _strip_req_prefix(req_id: str) -> str:
    """REQ-2026-010 → 2026-010（小写），feat/req-<这部分> 用。"""
    if req_id.startswith("REQ-"):
        return req_id[len("REQ-"):].lower()
    return req_id.lower()


def _current_branch(repo_root: Path) -> str:
    """git rev-parse --abbrev-ref HEAD；失败返回空串。

    bootstrap 失败回滚时需要"切回去"的目标分支；获取不到（detached HEAD /
    非 git repo）时返回空串，调用方据此选择跳过 checkout。
    """
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
        # best-effort：非 git repo / git 未安装时返回空串，不阻断 bootstrap
        logging.debug("_current_branch 失败：%s", exc)
        return ""


def _resolve_base_branch(repo_root: Path) -> str:
    """按 develop > main > master 优先级返回第一个可用的本地分支名。

    仅检查本地存在性（git rev-parse --verify）；远程同步 / pull --ff-only 不在
    本函数职责内——bootstrap 阶段尽量减少网络依赖，避免离线开发被卡。
    全部不可用时返回空串（极端场景，调用方应当容错）。
    """
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

def _render_meta_yaml(
    req_id: str,
    title: str,
    branch: str,
    base_branch: str,
) -> str:
    """基于 meta.yaml.tmpl 渲染流程组字段（语义组/结果组保持模板默认空值）。

    模板源 `.claude/skills/managing-requirement-lifecycle/templates/meta.yaml.tmpl`
    用 `__PLACEHOLDER__` 风格占位符；本函数做最小字符串替换，不引入 jinja。
    PROJECT 留空（"" 字面量），与 requirement-bootstrapper.md 约定一致——bootstrap
    阶段不强制 project 归类，由后续 definition 阶段补齐。
    """
    template_path = REPO_ROOT / _TEMPLATE_DIR_RELATIVE / "meta.yaml.tmpl"
    raw = template_path.read_text(encoding="utf-8")
    replacements = {
        "__REQ_ID__": req_id,
        "__TITLE__": title,
        "__CREATED_AT__": _now_shanghai_str(),
        "__BRANCH__": branch,
        "__BASE_BRANCH__": base_branch or "main",  # 极端兜底（仓库无任何主干）
        "__PROJECT__": "",
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
# bootstrap 步骤：单文件写 / 切分支
# ============================================================================

def _write_artifact_file(
    path: Path,
    content: str,
    *,
    req_id: str,
    step_name: str,
) -> None:
    """写单个 bootstrap 产物文件（meta.yaml / plan.md / process.txt）。

    抽离 F-002 rev1 中 _bootstrap_requirement 内 3 步重复的 try-except-write 模板：
    包装 OSError → BootstrapError(artifacts_created=True, branch_created=False)，
    并在成功时打 step done 日志。

    step_name 仅用于错误信息和日志（如 "meta.yaml"），便于排查具体失败步骤。

    参数：
        path        — 目标文件路径
        content     — 写入内容（字符串，UTF-8 编码）
        req_id      — 需求 ID（错误信息和日志用）
        step_name   — 步骤名（错误信息和日志用）
    """
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        # 进入此分支时：artifacts/ 已建成功 → artifacts_created=True；
        # 切分支尚未发生 → branch_created=False。rollback rmtree 整树清理半写文件。
        raise BootstrapError(
            f"bootstrap req_id={req_id} step={step_name} 写文件失败：{exc}",
            artifacts_created=True,
            branch_created=False,
        ) from exc
    logging.info("bootstrap req_id=%s step=write_%s done", req_id, step_name)


def _checkout_feature_branch(req_id: str, repo_root: Path) -> str:
    """git checkout -b feat/req-<id>（id 已去前缀小写）。

    返回新分支名；失败抛 BootstrapError(branch_created=False)，由调用方决定是否
    回滚。本函数不负责 fetch / pull——base_branch 选择已发生在调用前。
    """
    branch = f"feat/req-{_strip_req_prefix(req_id)}"
    try:
        result = subprocess.run(
            ["git", "checkout", "-b", branch],
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
        ) from exc
    if result.returncode != 0:
        raise BootstrapError(
            f"git checkout -b {branch} 失败 rc={result.returncode}: {result.stderr.strip()}",
            artifacts_created=True,
            branch_created=False,
        )
    return branch


# ============================================================================
# F-002 主入口：_bootstrap_requirement / _bootstrap_rollback
# ============================================================================

def _bootstrap_requirement(
    req_id: str,
    title: str,
    template_id: str,
    template_path: Path,
    arguments: str,
    repo_root: Path,
) -> Path:
    """需求类 bootstrap 副作用三步：建目录文件 + 切分支 + 写 jsonl。

    详细设计 §1.2。任一步失败抛 BootstrapError，由 main 调
    `_bootstrap_rollback` 反向撤销。本函数自身**不**调用 rollback——分层
    清晰：bootstrap 负责"建"，rollback 负责"删"，main 负责"编排"。

    返回：requirements/<req_id>/ 路径。
    """
    req_dir = repo_root / "requirements" / req_id
    artifacts_created = False
    branch_created = False
    base_branch = _resolve_base_branch(repo_root)

    # 步骤 1：建 artifacts/（req_id 顶层目录已由 _generate_req_id 创建）
    try:
        (req_dir / "artifacts").mkdir(parents=False, exist_ok=False)
    except OSError as exc:
        # mkdir 失败：顶层目录已存在（_generate_req_id 副作用），rollback 需删它；
        # 但 artifacts 子目录本身未必建成功——标 artifacts_created=True 让 rollback
        # rmtree 整个 req_dir，覆盖"建了一半"的边界
        raise BootstrapError(
            f"创建 {req_dir}/artifacts/ 失败：{exc}",
            artifacts_created=True,
            branch_created=False,
        ) from exc
    artifacts_created = True
    logging.info("bootstrap req_id=%s step=mkdir_artifacts done", req_id)

    # 步骤 2/3/4：渲染并写 meta.yaml / plan.md / process.txt
    # 失败语义统一通过 _write_artifact_file 包装为 BootstrapError(artifacts_created=True)
    branch_name = f"feat/req-{_strip_req_prefix(req_id)}"
    meta_content = _render_meta_yaml(req_id, title, branch_name, base_branch)
    _write_artifact_file(req_dir / "meta.yaml", meta_content, req_id=req_id, step_name="meta.yaml")
    plan_content = _render_plan_md(req_id, title)
    _write_artifact_file(req_dir / "plan.md", plan_content, req_id=req_id, step_name="plan.md")
    # process.tool.log 由 Hook 首次触发时生成，bootstrap 阶段只建空 process.txt
    _write_artifact_file(req_dir / "process.txt", "", req_id=req_id, step_name="process.txt")

    # 步骤 5：切 feature 分支（注意：本步骤先于 jsonl，是因为 jsonl 写失败比
    # 分支切换失败更罕见；分支切失败比写文件更可能（已有同名分支 / detached HEAD），
    # 让"高风险动作"靠后能减少回滚频度）
    _checkout_feature_branch(req_id, repo_root)
    branch_created = True
    logging.info("bootstrap req_id=%s step=checkout_branch done", req_id)

    # 步骤 6：写 workflow_started jsonl 事件（顶层 run-state.jsonl）
    jsonl_path = req_dir / "run-state.jsonl"
    try:
        append_event(jsonl_path, {
            "type": "workflow_started",
            "run_id": req_id,
            "data": {
                "workflow_name": template_id,
                "arguments": arguments,
                "template_path": str(template_path.relative_to(repo_root)) if template_path else "",
                "title": title,
            },
        })
    except WorkflowError as exc:
        raise BootstrapError(
            f"写 workflow_started 事件失败：{exc}",
            artifacts_created=artifacts_created,
            branch_created=branch_created,
        ) from exc
    logging.info("bootstrap req_id=%s step=workflow_started done", req_id)

    return req_dir


def _bootstrap_rollback(
    req_id: str,
    repo_root: Path,
    previous_branch: str,
    artifacts_created: bool,
    branch_created: bool,
) -> None:
    """bootstrap 失败反向撤销。

    顺序：先 git 后文件——若先 rmtree 再切分支，HEAD 仍指向已被删的目录里
    的内容时 git checkout 会失败；而 `git checkout <prev>` 不依赖 req_dir 存在，
    切回去再删才是安全顺序。

    所有 IOError / 子进程异常被吞并 logging.error——本函数自身在 try/finally
    /兜底链上调用，再抛会掩盖**原始** BootstrapError（即 bootstrap 失败的根因）。
    幂等：所有 step 用 best-effort 失败容忍，可重复调用。
    """
    branch_name = f"feat/req-{_strip_req_prefix(req_id)}"

    # 步骤 1：先切回旧分支（若 bootstrap 已成功切到新分支）
    if branch_created:
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
                    # check=False 不 raise；rc!=0 需显式 ERROR 日志，否则用户不可观察
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

        # 步骤 2：删除新建的 feature 分支（-D 强制删，因为可能还有未提交内容）
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

    # 步骤 3：删除 requirements/<req_id>/ 整树（含 _generate_req_id 创建的顶层目录）
    if artifacts_created:
        req_dir = repo_root / "requirements" / req_id
        try:
            shutil.rmtree(req_dir)
        except FileNotFoundError:
            # 已被外部清理 → 等价于已回滚成功
            logging.debug("rollback req_id=%s req_dir 已不存在，跳过 rmtree", req_id)
        except OSError as exc:
            logging.error(
                "rollback req_id=%s rmtree %s 失败：%s",
                req_id, req_dir, exc,
            )
