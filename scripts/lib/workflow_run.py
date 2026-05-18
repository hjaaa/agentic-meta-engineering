"""workflow run 命令入口（F-005 + F-002 + F-003）。

/workflow:run <template-id> [<title-or-args>...] [--slug=<slug>] [--no-worktree] [--worktree-policy=<policy>]

副作用：
  - requirement 类模板（category == "requirement"）：走 _bootstrap_requirement
    路径，建 `requirements/<REQ-ID>/`、写 meta.yaml/plan.md/process.txt、
    切 feat/req-<id> 分支、追加 workflow_started 事件。失败时调
    _bootstrap_rollback 反向撤销，不残留中间产物。
  - 其他模板：保留原有 run_id 路径，建 `runs/<RUN-ID>/` + meta.yaml + jsonl。

详细设计 §1.2 / §1.3 / §1.4 / §3.3。
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

# _generate_run_id 最大 EEXIST 重试次数（并发冲突时递增编号）
_RUN_ID_MAX_RETRIES = 3

# REQ-YYYY-NNN 格式正则（legacy 格式检测用）
_REQ_ID_PATTERN = re.compile(r"^REQ-(\d{4})-(\d{3})$")

# .worktrees/ 内 worktree 目录名前缀（对应 branch feat/req-<key>）
_WORKTREE_DIR_PREFIX = "feat-req-"

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError  # noqa: E402
from run_state import append_event  # noqa: E402
from workflow_loader import load_workflow  # noqa: E402  # F-003: schema 校验

# F-002 bootstrap 链路：异常 + 6 helper + 主入口（拆分到 workflow_bootstrap.py 后导入）
# 保持公开符号兼容：原 workflow_run.BootstrapError / _bootstrap_requirement 等
# 用例仍可通过 `from workflow_run import ...` 访问，避免下游测试 / dispatcher 改动。
from workflow_bootstrap import (  # noqa: E402,F401
    BootstrapError,
    _bootstrap_requirement,
    _bootstrap_rollback,
    _checkout_feature_branch,
    _current_branch,
    _now_shanghai_str,
    _render_meta_yaml,
    _render_plan_md,
    _resolve_base_branch,
    _strip_req_prefix,
    _write_artifact_file,
)
import requirement_naming  # noqa: E402
from requirement_naming import SlugError  # noqa: E402


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


def _scan_existing_requirement_keys(repo_root: Path) -> set[str]:
    """收集主仓根 requirements/ 与 .worktrees/ 下的占用 key。

    requirements/<key>/ 直接取目录名；.worktrees/feat-req-<key>/ 去前缀 'feat-req-'。
    缺目录视同空集；不抛异常。
    """
    occupied: set[str] = set()

    # 扫 requirements/<key>/
    req_base = repo_root / "requirements"
    if req_base.is_dir():
        try:
            with os.scandir(req_base) as it:
                for entry in it:
                    if entry.is_dir():
                        occupied.add(entry.name)
        except OSError as exc:
            logging.warning("_scan_existing_requirement_keys requirements/ 扫描失败：%s", exc)

    # 扫 .worktrees/feat-req-<key>/（去前缀还原 key）
    worktrees_base = repo_root / ".worktrees"
    if worktrees_base.is_dir():
        try:
            with os.scandir(worktrees_base) as it:
                for entry in it:
                    if entry.is_dir() and entry.name.startswith(_WORKTREE_DIR_PREFIX):
                        key = entry.name[len(_WORKTREE_DIR_PREFIX):]
                        if key:
                            occupied.add(key)
        except OSError as exc:
            logging.warning("_scan_existing_requirement_keys .worktrees/ 扫描失败：%s", exc)

    return occupied


def _generate_req_id(
    repo_root: Path,
    *,
    slug: str | None = None,
    today: date | None = None,
) -> str:
    """生成新 requirement key（D-013）。

    保留函数名 _generate_req_id 作为兼容入口，内部转调
    requirement_naming.generate_requirement_key（OD-1 汇合点）。

    函数体不出现 mkdir / open(W) 等占名 IO（P1-2）。
    slug 为 None 时，尝试 derive_slug_from_title("legacy-req") 作兜底
    （保持与旧签名的向后兼容）。

    返回：新 requirement key（str，格式 YYYYMMDD-<slug> 或带后缀）。
    抛出：SlugError 若同日同 slug 后缀 -02~-99 均已占用。
    """
    effective_slug = slug
    if effective_slug is None:
        effective_slug = requirement_naming.derive_slug_from_title("legacy-req")
    today = today or date.today()
    existing = _scan_existing_requirement_keys(repo_root)
    return requirement_naming.generate_requirement_key(today, effective_slug, existing_keys=existing)


def _generate_req_id_with_existing(
    repo_root: Path,
    *,
    slug: str,
    existing_keys: set[str],
    today: date | None = None,
) -> str:
    """生成新 requirement key，将外部 existing_keys 注入（retry 循环专用）。

    与 _generate_req_id 不同：existing_keys 由调用方管理（retry 时累积 tried_keys），
    不重新扫描文件系统——避免 race 窗口内的重复扫描。
    """
    today = today or date.today()
    # 合并文件系统已有 key 与调用方传入的 tried_keys
    fs_keys = _scan_existing_requirement_keys(repo_root)
    all_existing = fs_keys | existing_keys
    return requirement_naming.generate_requirement_key(today, slug, existing_keys=all_existing)


# ============================================================================
# F-003 RunArgs dataclass + 参数解析
# ============================================================================


# --worktree-policy 合法枚举值（来源：requirements/REQ-2026-014/artifacts/detailed-design.md:862）
_VALID_WORKTREE_POLICIES: frozenset[str] = frozenset({"auto", "never", "require", "current"})


@dataclass(frozen=True)
class RunArgs:
    """_parse_args 返回类型（F-003 扩展）。"""
    template_id: str
    template_args: str
    title: str
    slug: str | None
    no_worktree: bool
    worktree_policy: str | None


def _parse_args(args: list[str]) -> RunArgs:
    """切分 /workflow:run 的位置参数与 long-option 参数。

    位置参数约定：
      args[0]      → template_id
      args[1]      → title（如缺省，title 退回 template_id 作 fallback）
      args[1:]     → arguments（template_args，整体作为模板渲染输入字符串，
                       不含 -- 选项部分）

    支持 long-option（空格形式 `--key value` 与等号形式 `--key=value` 均接受）：
      --slug       → RunArgs.slug
      --no-worktree → RunArgs.no_worktree（单独 flag，无值）
      --worktree-policy → RunArgs.worktree_policy

    抛出：WorkflowError 若 args 为空 / --slug 后无值 / 遇未知 -- 选项。
    """
    if not args:
        raise WorkflowError("/workflow:run 需要 <template-id> 参数")

    # 已识别的 long-option 名（不含 --）
    _KNOWN_OPTIONS = {"slug", "no-worktree", "worktree-policy"}

    slug: str | None = None
    no_worktree: bool = False
    worktree_policy: str | None = None
    positional: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            # 等号形式：--key=value
            if "=" in arg:
                key, _, value = arg[2:].partition("=")
                if key not in _KNOWN_OPTIONS:
                    raise WorkflowError(f"未知选项：{arg!r}（允许：{sorted(_KNOWN_OPTIONS)}）")
                if key == "slug":
                    slug = value
                elif key == "worktree-policy":
                    if value not in _VALID_WORKTREE_POLICIES:
                        raise WorkflowError(
                            f"--worktree-policy 非法值 {value!r}，"
                            f"合法值：{', '.join(sorted(_VALID_WORKTREE_POLICIES))}"
                        )
                    worktree_policy = value
                elif key == "no-worktree":
                    no_worktree = True
                i += 1
            # 单 flag（--no-worktree 无值）
            elif arg == "--no-worktree":
                no_worktree = True
                i += 1
            # 空格形式：--key value
            else:
                key = arg[2:]
                if key not in _KNOWN_OPTIONS:
                    raise WorkflowError(f"未知选项：{arg!r}（允许：{sorted(_KNOWN_OPTIONS)}）")
                if key == "no-worktree":
                    no_worktree = True
                    i += 1
                else:
                    # 需要后续 value
                    if i + 1 >= len(args) or args[i + 1].startswith("--"):
                        raise WorkflowError(f"选项 {arg!r} 缺少值（后接 -- 选项或参数列表结束）")
                    value = args[i + 1]
                    if key == "slug":
                        slug = value
                    elif key == "worktree-policy":
                        if value not in _VALID_WORKTREE_POLICIES:
                            raise WorkflowError(
                                f"--worktree-policy 非法值 {value!r}，"
                                f"合法值：{', '.join(sorted(_VALID_WORKTREE_POLICIES))}"
                            )
                        worktree_policy = value
                    i += 2
        else:
            positional.append(arg)
            i += 1

    if not positional:
        raise WorkflowError("/workflow:run 需要 <template-id> 参数")

    template_id = positional[0]
    # title 取第一个位置参数；为空时降级用 template_id（避免 plan.md __TITLE__ 留占位）
    title = positional[1] if len(positional) > 1 and positional[1].strip() else template_id
    # template_args 是所有位置参数（除 template_id）拼合
    template_args = " ".join(positional[1:]) if len(positional) > 1 else ""

    return RunArgs(
        template_id=template_id,
        template_args=template_args,
        title=title,
        slug=slug,
        no_worktree=no_worktree,
        worktree_policy=worktree_policy,
    )


# ============================================================================
# main 入口
# ============================================================================

def main(args: list[str], repo_root: Path | None = None) -> int:
    """run 命令主入口。

    参数：
        args      — [template_id, title?, ...rest_args, --slug=<slug>, ...]
        repo_root — 注入 repo 根路径（测试用）

    返回：exit code（0 成功，1 失败）
    """
    root = repo_root or REPO_ROOT

    # 参数解析（_parse_args 抛 WorkflowError 时统一兜底）
    try:
        run_args = _parse_args(args)
    except WorkflowError as exc:
        print(
            f"ERROR: {exc}\n"
            "用法：/workflow:run <template-id> [<title>] [<args>...] [--slug <slug>] [--no-worktree] [--worktree-policy <policy>]",
            file=sys.stderr,
        )
        return 1

    template_id = run_args.template_id

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

    # F-003：schema 校验门禁——load_workflow 自身不抛异常，
    # 失败信息通过 report.errors 报告，调用方无需 try/except。
    load_result = load_workflow(template_path)
    if load_result.report.errors:
        print(load_result.report.render(), file=sys.stderr)
        return 1
    # schema 通过后，直接从已解析产物取 category，不再重复读 yaml
    workflow = load_result.workflow  # dict，由 load_workflow 保证非 None

    # F-003 替换 _is_requirement_template：用 workflow.get("category") 直接判定，
    # 无路径兜底降级——schema 已保证 category 在 ALLOWED_CATEGORIES 内。
    if workflow.get("category") == "requirement":
        return _run_requirement(run_args, template_path, root)
    return _run_generic(run_args.template_id, run_args.template_args, template_path, root)


def _run_requirement(
    args: RunArgs,
    template_path: Path,
    root: Path,
) -> int:
    """requirement 类模板的 run 流程：决定 slug → 生成 REQ-ID → bootstrap retry → 输出提示。

    返回：int（0 成功 / 1 失败）
    失败处理：BootstrapError 已在函数内部触发 _bootstrap_rollback 反向撤销，
    调用方无需再清理 requirements/<req_id>/ 或 feat 分支。

    F-003 改造点（§3.3 改造点 3）：
    1. 决定 slug（args.slug 或 derive_slug_from_title）
    2. 中文标题 + 缺 slug 时 fail-closed exit 1
    3. bootstrap retry 循环：仅 reason='path_or_branch_exists' 重试（≤ 99 次）
    """
    template_id = args.template_id
    template_args = args.template_args
    title = args.title

    # 决定 slug
    slug = args.slug or requirement_naming.derive_slug_from_title(title)
    if not slug:
        print(
            "ERROR: 中文标题需显式 --slug=<ascii-slug>；详见 D-013\n"
            "  用法示例（空格形式）：/workflow:run standard-8phase 我的需求 --slug my-req\n"
            "  用法示例（等号形式）：/workflow:run standard-8phase 我的需求 --slug=my-req",
            file=sys.stderr,
        )
        return 1

    previous_branch = _current_branch(root)
    # tried_keys 在每次 retry 前累积已尝试过的 key，避免重复生成同一 key
    tried_keys: set[str] = set()

    try:
        for attempt in range(1, 100):
            # 每轮重新生成 req_id（注入 tried_keys 使其跳过已尝试的 key）
            try:
                req_id = _generate_req_id_with_existing(root, slug=slug, existing_keys=tried_keys)
            except SlugError as exc:
                print(f"ERROR: 无法生成 requirement key：{exc}", file=sys.stderr)
                return 1

            try:
                req_dir = _bootstrap_requirement(
                    req_id, title, template_id, template_path, template_args, root,
                    worktree_policy=args.worktree_policy,
                    no_worktree=args.no_worktree,
                )
            except BootstrapError as exc:
                reason = getattr(exc, "reason", None)
                if reason == "path_or_branch_exists":
                    # 路径/分支占用：bump tried_keys 重试（F-003 retry 语义）
                    logging.warning(
                        "bootstrap req_id=%s reason=path_or_branch_exists，尝试下一个 key（attempt=%d）",
                        req_id, attempt,
                    )
                    tried_keys.add(req_id)
                    continue
                # 其它 reason：先 logging 再 rollback，原异常透传
                logging.error(
                    "bootstrap req_id=%s 失败，已触发 rollback：%s",
                    req_id, exc,
                )
                _bootstrap_rollback(
                    req_id, root, previous_branch,
                    exc.artifacts_created, exc.branch_created,
                )
                print(f"ERROR: bootstrap 失败：{exc}", file=sys.stderr)
                return 1
            else:
                # bootstrap 成功
                print("workflow run 已启动（requirement）")
                print(f"  req_id:   {req_id}")
                print(f"  template: {template_id}")
                print(f"  req_dir:  {req_dir.relative_to(root)}")
                print(f"  branch:   feat/req-{_strip_req_prefix(req_id)}")
                print(f"  下一步: /requirement:continue 或 /workflow:continue {req_id}")
                return 0

        # 超过 99 次重试上限（与 generate_requirement_key 内部上限对齐）
        raise SlugError(
            f"bootstrap retry 超过 99 次上限（slug={slug!r}），无法生成可用 requirement key"
        )
    except SlugError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


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
