"""workflow run 命令入口（F-005）。

/workflow:run <template-id> [<args>]

副作用：创建 run 目录 + meta.yaml + jsonl `workflow_started` 事件。

详细设计 §1.2.1。
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


def main(args: list[str], repo_root: Path | None = None) -> int:
    """run 命令主入口。

    参数：
        args      — [template_id, ...rest_args]
        repo_root — 注入 repo 根路径（测试用）

    返回：exit code（0 成功，1 失败）
    """
    root = repo_root or REPO_ROOT

    if not args:
        print(
            "ERROR: /workflow:run 需要 <template-id> 参数\n"
            "用法：/workflow:run <template-id> [<args>]",
            file=sys.stderr,
        )
        return 1

    template_id = args[0]
    template_args = " ".join(args[1:]) if len(args) > 1 else ""

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

    # 生成 run_id + 原子创建目录（_generate_run_id 已完成 mkdir）
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
