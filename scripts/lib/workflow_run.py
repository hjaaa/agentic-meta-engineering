"""workflow run 命令入口（F-005 + F-002）。

/workflow:run <template-id> [<title-or-args>...]

副作用：
  - requirement 类模板（category == "requirement"）：走 _bootstrap_requirement
    路径，建 `requirements/<REQ-ID>/`、写 meta.yaml/plan.md/process.txt、
    切 feat/req-<id> 分支、追加 workflow_started 事件。失败时调
    _bootstrap_rollback 反向撤销，不残留中间产物。
  - 其他模板：保留原有 run_id 路径，建 `runs/<RUN-ID>/` + meta.yaml + jsonl。

详细设计 §1.2 / §1.3 / §1.4。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# _generate_run_id 最大 EEXIST 重试次数（并发冲突时递增编号）
_RUN_ID_MAX_RETRIES = 3

# _generate_req_id 最大 EEXIST 重试次数（并发冲突时递增编号）
_REQ_ID_MAX_RETRIES = 3

# REQ-YYYY-NNN 格式正则
_REQ_ID_PATTERN = re.compile(r"^REQ-(\d{4})-(\d{3})$")

# requirement 类 base_branch 选择优先级（develop 优先，兜底 main/master）
_BASE_BRANCH_PRIORITY: tuple[str, ...] = ("develop", "main", "master")

# Asia/Shanghai 固定偏移（CST = UTC+8，无 DST 困扰）
_CST_TZ = timezone(timedelta(hours=8))

# git 子进程默认超时（秒）；分支操作通常 < 1s，5s 足够
_GIT_TIMEOUT_SECONDS = 5

# 模板源目录（managing-requirement-lifecycle Skill 持有真实模板，本模块只读）
_TEMPLATE_DIR_RELATIVE = Path(".claude/skills/managing-requirement-lifecycle/templates")

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError  # noqa: E402
from run_state import append_event  # noqa: E402


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


def _generate_run_id(repo_root: Path) -> str:
    """生成唯一 run_id（RUN-YYYYMMDD-NNN 格式）并原子化创建目录。

    并发安全策略：先扫描已有编号取 max+1，再用 mkdir(exist_ok=False) 尝试
    原子创建；若遇 FileExistsError（EEXIST，并发进程已抢占同编号）则递增
    编号重试，最多 _RUN_ID_MAX_RETRIES 次。

    返回：已成功创建目录的 run_id（str）。
    抛出：WorkflowError 若超 _RUN_ID_MAX_RETRIES。
    """
    ts_prefix = datetime.now(timezone.utc).strftime("%Y%m%d")
    base = repo_root / "runs"
    base.mkdir(parents=True, exist_ok=True)

    # 扫描已有编号，取 max+1 作为起始候选
    existing = [d.name for d in base.iterdir() if d.is_dir() and d.name.startswith(f"RUN-{ts_prefix}-")]
    nums = []
    for name in existing:
        parts = name.split("-")
        if len(parts) == 3 and parts[2].isdigit():
            nums.append(int(parts[2]))
    next_num = max(nums) + 1 if nums else 1

    # 原子化创建：exist_ok=False 确保只有一个进程成功；冲突时递增重试
    for attempt in range(_RUN_ID_MAX_RETRIES):
        candidate_id = f"RUN-{ts_prefix}-{next_num:03d}"
        candidate_dir = base / candidate_id
        try:
            candidate_dir.mkdir(parents=False, exist_ok=False)
            return candidate_id
        except FileExistsError:
            # 并发冲突：另一进程已抢占该编号，取下一个编号重试
            logging.debug("run_id %s 冲突，递增重试 attempt=%d", candidate_id, attempt)
            next_num += 1

    # 超过最大重试次数（极低概率；最多支持 3 路并发冲突重试，≥4 进程同时竞争才会失败）
    raise WorkflowError(
        f"生成 run_id 失败：并发冲突超过 {_RUN_ID_MAX_RETRIES} 次重试"
    )


def _generate_req_id(repo_root: Path) -> str:
    """扫 requirements/ 下现有 REQ-YYYY-NNN 取 max+1，原子化建目录。

    并发安全：mkdir(exist_ok=False) + EEXIST 重试，与 _generate_run_id 一致。

    max 取**当年** REQ-YYYY-NNN 中 NNN 的 max（year==ts_prefix），跨年从 1 重新开始。

    返回：成功创建目录的 REQ-ID（str）。
    抛出：WorkflowError 若超 _REQ_ID_MAX_RETRIES。
    """
    # 当前年份（4 位，UTC）
    ts_prefix = datetime.now(timezone.utc).strftime("%Y")
    base = repo_root / "requirements"
    base.mkdir(parents=True, exist_ok=True)

    # 扫描已有当年编号，取 max+1 作为起始候选
    # os.scandir 先按名字过滤再 stat，规避 requirements/ 累积大量目录时的性能退化
    nums = []
    with os.scandir(base) as it:
        for entry in it:
            m = _REQ_ID_PATTERN.match(entry.name)
            if m and m.group(1) == ts_prefix and entry.is_dir():
                # 仅收集当年编号；跨年重新从 1 计
                nums.append(int(m.group(2)))
    next_num = max(nums) + 1 if nums else 1

    # 检查溢出（NNN 为 3 位，最大 999）；进入此分支前 next_num>999 已保证 nums 非空
    if next_num > 999:
        raise WorkflowError(
            f"生成 req_id 失败：{ts_prefix} 年编号已达上限 999（当前 max={max(nums)}），请人工干预"
        )

    # 原子化创建：exist_ok=False 确保只有一个进程成功；EEXIST 时递增重试
    for attempt in range(_REQ_ID_MAX_RETRIES):
        candidate_id = f"REQ-{ts_prefix}-{next_num:03d}"
        candidate_dir = base / candidate_id
        try:
            candidate_dir.mkdir(parents=False, exist_ok=False)
            logging.debug("req_id=%s 顶层目录已创建", candidate_id)
            return candidate_id
        except FileExistsError:
            # 并发冲突：另一进程已抢占该编号，取下一个编号重试
            logging.debug("req_id %s 冲突，递增重试 attempt=%d", candidate_id, attempt)
            next_num += 1
            if next_num > 999:
                raise WorkflowError(
                    f"生成 req_id 失败：{ts_prefix} 年编号已达上限 999（当前 max={next_num - 1}）"
                )

    # 超过最大重试次数（极低概率；最多支持 3 路并发冲突重试，≥4 进程同时竞争才会失败）
    raise WorkflowError(
        f"生成 req_id 失败：并发冲突超过 {_REQ_ID_MAX_RETRIES} 次重试"
    )


# ============================================================================
# F-002 helpers：分支推断 / 模板分类 / 参数解析 / 模板渲染
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


def _is_requirement_template(template_path: Path) -> bool:
    """读 yaml 顶部 category 字段判定是否走 requirement bootstrap 路径。

    优先解析 yaml；解析失败 / 无 yaml 依赖时降级用路径片段 `/requirement/`
    判定（与现有 `.claude/workflows/requirement/*.yaml` 目录约定一致）。
    F-003 落地 schema 校验后此函数会被 load_workflow().workflow.category 取代，
    本 feature 用最小依赖实现，不引入 schema。
    """
    try:
        import yaml  # type: ignore
        with template_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if isinstance(data, dict) and data.get("category") == "requirement":
            return True
        # category 显式非 requirement 时也走显式判定，不再退回路径推断
        if isinstance(data, dict) and "category" in data:
            return False
    except (ImportError, OSError) as exc:
        # yaml 缺失或读文件失败 → 用路径片段兜底
        logging.debug("_is_requirement_template yaml 解析失败：%s", exc)
    # 路径兜底：.claude/workflows/requirement/*.yaml
    return "/requirement/" in str(template_path).replace("\\", "/")


def _parse_args(args: list[str]) -> tuple[str, str, str]:
    """切分 /workflow:run 的位置参数。

    约定（最小可行）：
      args[0]      → template_id
      args[1]      → title（如缺省，title 退回 template_id 作 fallback）
      args[1:]     → arguments（template_args，整体作为模板渲染输入字符串）

    返回：(template_id, template_args, title)
    抛出：WorkflowError 若 args 为空。
    """
    if not args:
        raise WorkflowError("/workflow:run 需要 <template-id> 参数")
    template_id = args[0]
    template_args = " ".join(args[1:]) if len(args) > 1 else ""
    # title 取第一个位置参数；为空时降级用 template_id（避免 plan.md __TITLE__ 留占位）
    title = args[1] if len(args) > 1 and args[1].strip() else template_id
    return template_id, template_args, title


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

    # 步骤 2：渲染并写 meta.yaml
    branch_name = f"feat/req-{_strip_req_prefix(req_id)}"
    try:
        meta_content = _render_meta_yaml(req_id, title, branch_name, base_branch)
        (req_dir / "meta.yaml").write_text(meta_content, encoding="utf-8")
    except OSError as exc:
        raise BootstrapError(
            f"写 meta.yaml 失败：{exc}",
            artifacts_created=artifacts_created,
            branch_created=branch_created,
        ) from exc
    logging.info("bootstrap req_id=%s step=write_meta done", req_id)

    # 步骤 3：渲染并写 plan.md
    try:
        plan_content = _render_plan_md(req_id, title)
        (req_dir / "plan.md").write_text(plan_content, encoding="utf-8")
    except OSError as exc:
        raise BootstrapError(
            f"写 plan.md 失败：{exc}",
            artifacts_created=artifacts_created,
            branch_created=branch_created,
        ) from exc
    logging.info("bootstrap req_id=%s step=write_plan done", req_id)

    # 步骤 4：写空 process.txt（process.tool.log 由 Hook 首次触发时生成，不在这里建）
    try:
        (req_dir / "process.txt").write_text("", encoding="utf-8")
    except OSError as exc:
        raise BootstrapError(
            f"写 process.txt 失败：{exc}",
            artifacts_created=artifacts_created,
            branch_created=branch_created,
        ) from exc
    logging.info("bootstrap req_id=%s step=write_process done", req_id)

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
                subprocess.run(
                    ["git", "checkout", previous_branch],
                    capture_output=True,
                    text=True,
                    cwd=str(repo_root),
                    timeout=_GIT_TIMEOUT_SECONDS,
                    check=False,
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
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
                timeout=_GIT_TIMEOUT_SECONDS,
                check=False,
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


# ============================================================================
# main 入口
# ============================================================================

def main(args: list[str], repo_root: Path | None = None) -> int:
    """run 命令主入口。

    参数：
        args      — [template_id, title?, ...rest_args]
        repo_root — 注入 repo 根路径（测试用）

    返回：exit code（0 成功，1 失败）
    """
    root = repo_root or REPO_ROOT

    # 参数解析（_parse_args 抛 WorkflowError 时统一兜底）
    try:
        template_id, template_args, title = _parse_args(args)
    except WorkflowError as exc:
        print(
            f"ERROR: {exc}\n"
            "用法：/workflow:run <template-id> [<title>] [<args>...]",
            file=sys.stderr,
        )
        return 1

    # 查找模板（.claude/workflows/*.yaml 三层）
    workflow_dir = root / ".claude" / "workflows"
    candidates = list(workflow_dir.glob(f"**/{template_id}.yaml"))
    if not candidates:
        available = [p.stem for p in workflow_dir.glob("**/*.yaml")]
        print(
            f"ERROR: 模板 {template_id!r} 未找到\n"
            f"可用模板：{', '.join(sorted(available)) or '(无)'}",
            file=sys.stderr,
        )
        return 1

    template_path = candidates[0]

    # F-002 分支判定：requirement 类走 _bootstrap_requirement 重路径；
    # 其他类（code-review-embedded 等）保留原 run_id 轻路径，向后兼容 F-005。
    if _is_requirement_template(template_path):
        return _run_requirement(template_id, template_args, title, template_path, root)
    return _run_generic(template_id, template_args, template_path, root)


def _run_requirement(
    template_id: str,
    template_args: str,
    title: str,
    template_path: Path,
    root: Path,
) -> int:
    """requirement 类模板的 run 流程：生成 REQ-ID → bootstrap → 输出提示。"""
    previous_branch = _current_branch(root)

    # 生成 REQ-ID + 顶层目录（_generate_req_id 已 mkdir requirements/<REQ-ID>/）
    try:
        req_id = _generate_req_id(root)
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        req_dir = _bootstrap_requirement(
            req_id, title, template_id, template_path, template_args, root,
        )
    except BootstrapError as exc:
        _bootstrap_rollback(
            req_id, root, previous_branch,
            exc.artifacts_created, exc.branch_created,
        )
        print(f"ERROR: bootstrap 失败：{exc}", file=sys.stderr)
        return 1

    print("workflow run 已启动（requirement）")
    print(f"  req_id:   {req_id}")
    print(f"  template: {template_id}")
    print(f"  req_dir:  {req_dir.relative_to(root)}")
    print(f"  branch:   feat/req-{_strip_req_prefix(req_id)}")
    print(f"  下一步: /requirement:continue 或 /workflow:continue {req_id}")
    return 0


def _run_generic(
    template_id: str,
    template_args: str,
    template_path: Path,
    root: Path,
) -> int:
    """非 requirement 类模板的原 run 流程（F-005 已上线行为，向后兼容）。"""
    # 生成 run_id + 原子创建目录
    try:
        run_id = _generate_run_id(root)
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    run_dir = root / "runs" / run_id

    # 写 meta.yaml
    ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {
        "run_id": run_id,
        "template": template_id,
        "template_path": str(template_path.relative_to(root)),
        "arguments": template_args,
        "state": "running",
        "start_ts": ts_now,
    }
    meta_path = run_dir / "meta.yaml"
    try:
        try:
            import yaml  # type: ignore  # yaml 是可选第三方依赖，用 fallback 写 json
            with meta_path.open("w", encoding="utf-8") as fh:
                yaml.safe_dump(meta, fh, allow_unicode=True, sort_keys=False)
        except ImportError:
            # 无 yaml 依赖时降级写 json
            with meta_path.open("w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise WorkflowError(f"写 meta.yaml 失败: {exc}") from exc

    # 写 workflow_started jsonl 事件
    jsonl_path = run_dir / "run-state.jsonl"
    try:
        append_event(jsonl_path, {
            "type": "workflow_started",
            "run_id": run_id,
            "data": {
                "workflow_name": template_id,
                "arguments": template_args,
            },
        })
    except WorkflowError as exc:
        print(f"ERROR: 写 jsonl 事件失败：{exc}", file=sys.stderr)
        return 1

    print("workflow run 已启动")
    print(f"  run_id:   {run_id}")
    print(f"  template: {template_id}")
    print(f"  run_dir:  {run_dir.relative_to(root)}")
    print(f"  下一步: /workflow:continue {run_id}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:] if len(sys.argv) > 1 else []))
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
