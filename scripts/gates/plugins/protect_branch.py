"""GATE-PROTECT-BRANCH：受保护分支写操作拦截（从 .claude/hooks/protect-branch.sh 拆出）。

设计说明（来源：detailed-design.md §3.4）：
  protect_branch 只在 pre-tool-use trigger 生效，拦截在 main/master/develop 分支上
  的 Edit/Write/MultiEdit 工具调用，以及任意分支对 reviews/*.json 的直接写操作。

  与 F-003 的 bash_write_protect（H5）不同：
    - protect_branch 拦截 Edit/Write/MultiEdit（非 Bash），当前 trigger=pre-tool-use
    - bash_write_protect 拦截 Bash 命令，在 F-003 实现

precheck：
  - 仅对 Edit/Write/MultiEdit 工具名响应（Bash 等其他工具直接 Skip）
  - trigger 非 pre-tool-use 时直接 Skip（由 registry 的 triggers 字段保证）
"""
from __future__ import annotations

import subprocess
from typing import Optional

from .base import Decision, Gate, GateContext, Report, Severity, Skip

# 受保护分支列表，也可通过 ctx.env 覆盖
DEFAULT_PROTECTED_BRANCHES = frozenset({"main", "master", "develop"})

# 拦截的写工具名
WRITE_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})


class ProtectBranchGate(Gate):
    """受保护分支 / reviews/*.json 直接写操作拦截 gate。"""

    id = "GATE-PROTECT-BRANCH"
    severity = Severity.ERROR
    triggers = {"pre-tool-use"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        # defense-in-depth：registry triggers=[pre-tool-use] 已保证，但 plugin 自身也校验（F-12）
        if ctx.trigger != "pre-tool-use":
            return Skip(f"trigger={ctx.trigger!r} 非 pre-tool-use；跳过 protect-branch")
        tool_name = ctx.extra.get("tool_name", "")
        # 非写工具（如 Bash / Read）直接放行
        if tool_name not in WRITE_TOOLS:
            return Skip(f"tool_name={tool_name!r} is not a write tool; skip protect-branch")
        return None

    def run(self, ctx: GateContext) -> Report:
        tool_name = ctx.extra.get("tool_name", "")
        file_path = ctx.extra.get("file_path") or ctx.extra.get("path") or ""

        # 路径级拦截：reviews/*.json 任意分支均禁止直接 Edit/Write/MultiEdit
        if _is_reviews_json(file_path):
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="PROTECT-REVIEWS",
                message=(
                    f"禁止直接 {tool_name} [{file_path}]，"
                    "reviews/*.json 是 save-review.sh 的唯一写入通道"
                ),
                fix_hint=(
                    "如要修订评审结论，请让 reviewer Agent 重新评审（supersedes 链）；"
                    "紧急绕过：git commit --no-verify（CI 仍会拦）"
                ),
                vars={"file_path": file_path, "tool_name": tool_name},
            )

        # 分支级拦截：受保护分支上禁止写操作
        current_branch = _get_current_branch(ctx)
        if not current_branch:
            # 不在 git 仓库，放行（无法判断分支）
            return Report(gate_id=self.id, decision=Decision.PASS)

        protected = _get_protected_branches(ctx)
        if current_branch in protected:
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="PROTECT-BRANCH",
                message=f"禁止在受保护分支 [{current_branch}] 上直接写操作",
                fix_hint="请先切换到 feature 分支：/requirement:new 会自动建分支",
                vars={"branch": current_branch, "tool_name": tool_name, "file_path": file_path},
            )

        return Report(gate_id=self.id, decision=Decision.PASS)


def _is_reviews_json(file_path: str) -> bool:
    """判断路径是否为 requirements/*/reviews/*.json。"""
    if not file_path:
        return False
    parts = file_path.replace("\\", "/").lstrip("/").split("/")
    # 兼容绝对路径：取末尾的相对部分
    try:
        # 找到 requirements 的位置
        idx = None
        for i, p in enumerate(parts):
            if p == "requirements":
                idx = i
                break
        if idx is None:
            return False
        rel_parts = parts[idx:]
        return (
            len(rel_parts) >= 4
            and rel_parts[0] == "requirements"
            and rel_parts[2] == "reviews"
            and rel_parts[-1].endswith(".json")
        )
    except Exception as exc:  # noqa: BLE001
        # 纯字符串路径操作理论上不抛，保留此处用于未知边界情况的日志记录
        import sys
        print(f"WARNING _is_reviews_json 路径解析异常 file_path={file_path!r}: {exc}", file=sys.stderr)
        return False


def _get_current_branch(ctx: GateContext) -> str:
    """获取当前 git 分支名；失败返回空字符串。"""
    # 优先从 ctx.env 取（便于测试 mock）
    branch_override = ctx.env.get("CLAUDE_HOOK_BRANCH")
    if branch_override is not None:
        return branch_override

    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip()
    except (FileNotFoundError, OSError):
        return ""


def _get_protected_branches(ctx: GateContext) -> frozenset[str]:
    """从 ctx.env 或默认值取受保护分支集合。"""
    env_val = ctx.env.get("CLAUDE_PROTECTED_BRANCHES")
    if env_val:
        return frozenset(b.strip() for b in env_val.split(",") if b.strip())
    return DEFAULT_PROTECTED_BRANCHES


# 模块级导出
GATE_CLASS = ProtectBranchGate
