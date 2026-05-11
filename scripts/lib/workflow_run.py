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
import sys
from datetime import datetime, timezone
from pathlib import Path

# _generate_run_id 最大 EEXIST 重试次数（并发冲突时递增编号）
_RUN_ID_MAX_RETRIES = 3

# _generate_req_id 最大 EEXIST 重试次数（并发冲突时递增编号）
_REQ_ID_MAX_RETRIES = 3

# REQ-YYYY-NNN 格式正则
_REQ_ID_PATTERN = re.compile(r"^REQ-(\d{4})-(\d{3})$")

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError  # noqa: E402
from run_state import append_event  # noqa: E402

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
# F-002 helpers：模板分类 / 参数解析（其余 bootstrap helper 已迁至 workflow_bootstrap.py）
# ============================================================================

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
    """requirement 类模板的 run 流程：生成 REQ-ID → bootstrap → 输出提示。

    返回：int（0 成功 / 1 失败）
    失败处理：BootstrapError 已在函数内部触发 _bootstrap_rollback 反向撤销，
    调用方无需再清理 requirements/<req_id>/ 或 feat 分支。
    """
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
        # 关键失败链路必须先 logging 再 rollback——rollback 自身若再异常会掩盖原因，
        # logging.error 在前确保 ERROR 日志至少落盘一行（不依赖 rollback 成功与否）
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
