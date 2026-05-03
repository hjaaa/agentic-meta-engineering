"""GATE-BASE-REACHABLE：submit 时校验 base 分支在远端可达（关 H4 submit 完整化）。

设计来源：requirements/REQ-2026-002/artifacts/detailed-design.md §4.2

职责：
  - 在 /requirement:submit 触发时，从 meta.yaml.base_branch 读取基点分支名，
    跑 `git fetch origin <base_branch> --dry-run` 验证远端可达性
  - 分支不存在 / 网络不通 → FAIL，给出修复建议
  - meta.base_branch 缺失时取默认值 develop，再 fallback main

precheck：
  - submit trigger 才生效；其他 trigger 直接 Skip

外部依赖：
  - git CLI（系统提供，零新增依赖）
  - subprocess.run（必须 mock 测试）

实现约束：
  - subprocess timeout=10s，防止网络挂起
  - stderr 捕获（避免 git 进度信息污染输出）
  - 不打印 token / remote URL 等敏感信息
"""
from __future__ import annotations

import subprocess
import sys
from typing import Optional

from .base import Decision, Gate, GateContext, Report, Severity, Skip

# git fetch --dry-run 超时（秒）；仅验证分支可达，10s 足够
_GIT_TIMEOUT_SEC = 10

# base_branch 的 fallback 顺序：meta.base_branch → develop → main
_FALLBACK_BRANCHES = ("develop", "main")


class BaseReachableGate(Gate):
    """submit 时检查 base 分支在远端可达的门禁。"""

    id = "GATE-BASE-REACHABLE"
    severity = Severity.ERROR
    triggers = {"submit"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """仅 submit trigger 生效；其他 trigger 直接跳过。"""
        if ctx.trigger != "submit":
            return Skip(f"trigger={ctx.trigger!r} 非 submit；跳过 base-reachable")
        return None

    def run(self, ctx: GateContext) -> Report:
        """从 meta.base_branch 读取目标分支，校验远端可达。"""
        base_branch = _resolve_base_branch(ctx)
        return _check_branch_reachable(base_branch)


def _resolve_base_branch(ctx: GateContext) -> str:
    """解析目标 base 分支名。

    解析顺序（F-004 升级）：
      1. ctx.cli_flags["target"] — 用户显式 --target；submit.py / phase-transition 透传
      2. ctx.meta["base_branch"] — meta.yaml 配置
      3. _FALLBACK_BRANCHES[0] — 兜底（develop）
    """
    cli_flags = ctx.cli_flags or {}
    target = cli_flags.get("target")
    if target:
        return target
    return ctx.meta.get("base_branch") or _FALLBACK_BRANCHES[0]


def _check_branch_reachable(base_branch: str) -> Report:
    """执行 git fetch origin <branch> --dry-run 验证远端可达性。

    独立为模块级函数，便于测试 mock。
    返回：PASS（退出码 0）/ FAIL（含修复建议）。

    check=False 说明：
      不使用 check=True（即不让 subprocess 自动抛 CalledProcessError），
      因为 git fetch 非零退出本身就是我们要捕获的分支不可达信号；
      我们在 result.returncode != 0 时自行返回 FAIL Report，
      避免异常路径与 git 退出码语义冲突。
      check=True 只应在"非零 = 程序 bug"场景下启用；此处"非零 = 预期失败路径"。
    """
    try:
        result = subprocess.run(
            ["git", "fetch", "origin", base_branch, "--dry-run"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return Report(
            gate_id="GATE-BASE-REACHABLE",
            decision=Decision.FAIL,
            code="BASE-FETCH-TIMEOUT",
            message=f"git fetch origin {base_branch} --dry-run 超时（>{_GIT_TIMEOUT_SEC}s）",
            fix_hint="检查网络连通性后重试；或手工运行 git fetch origin 确认",
        )
    except FileNotFoundError:
        return Report(
            gate_id="GATE-BASE-REACHABLE",
            decision=Decision.FAIL,
            code="GIT-NOT-FOUND",
            message="git CLI 未找到",
            fix_hint="确认 git 已安装且在 PATH 中",
        )
    except OSError as exc:
        return Report(
            gate_id="GATE-BASE-REACHABLE",
            decision=Decision.FAIL,
            code="GIT-OS-ERROR",
            message=f"git 调用失败：{exc}",
            fix_hint="检查 git CLI 可执行权限后重试",
        )

    if result.returncode != 0:
        print(
            f"WARNING GATE-BASE-REACHABLE git fetch origin {base_branch} --dry-run 返回非零，"
            "base 分支不可达",
            file=sys.stderr,
        )
        return Report(
            gate_id="GATE-BASE-REACHABLE",
            decision=Decision.FAIL,
            code="BASE-NOT-REACHABLE",
            message=f"base 分支 {base_branch!r} 在远端不可达",
            fix_hint=(
                f"确认 origin 地址正确且网络可达；若分支名有误，"
                f"更新 meta.yaml 的 base_branch 字段（当前：{base_branch!r}）"
            ),
            vars={"base_branch": base_branch},
        )

    return Report(
        gate_id="GATE-BASE-REACHABLE",
        decision=Decision.PASS,
        vars={"base_branch": base_branch},
    )


# 模块级导出
GATE_CLASS = BaseReachableGate
