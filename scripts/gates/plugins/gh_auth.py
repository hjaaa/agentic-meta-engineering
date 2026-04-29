"""GATE-GH-AUTH：submit 时校验 gh CLI 已登录（关 H4 submit 完整化）。

设计来源：requirements/REQ-2026-002/artifacts/detailed-design.md §4.2

职责：
  - 在 /requirement:submit 触发时校验 `gh auth status` 返回码 = 0
  - 未登录 → FAIL，给出 "运行 gh auth login" 修复建议
  - gh CLI 不存在 → FAIL，给出安装建议
  - 超时 → FAIL，给出网络检查建议

precheck：
  - submit trigger 才生效；其他 trigger 直接 Skip

外部依赖：
  - gh CLI（系统提供，零新增依赖）
  - subprocess.run（必须 mock 测试）

实现约束：
  - subprocess timeout=10s，防止网络挂起
  - stderr 捕获（不透传到用户终端）
  - 不打印 token / credential 等敏感信息（日志安全要求）
"""
from __future__ import annotations

import subprocess
import sys
from typing import Optional

from .base import Decision, Gate, GateContext, Report, Severity, Skip

# gh auth status 超时（秒）；认证检查不涉及网络 IO，10s 足够兜底
_GH_TIMEOUT_SEC = 10


class GhAuthGate(Gate):
    """submit 时检查 gh CLI 已登录的门禁。"""

    id = "GATE-GH-AUTH"
    severity = Severity.ERROR
    triggers = {"submit"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """仅 submit trigger 生效；其他 trigger 直接跳过。"""
        if ctx.trigger != "submit":
            return Skip(f"trigger={ctx.trigger!r} 非 submit；跳过 gh-auth")
        return None

    def run(self, ctx: GateContext) -> Report:
        """调 gh auth status 校验 gh CLI 已登录。

        F-004：timeout=10s + stderr 捕获；不输出敏感凭据信息到日志。
        """
        return _check_gh_auth()


def _check_gh_auth() -> Report:
    """执行 gh auth status 并返回 Report。

    独立为模块级函数，便于测试 mock。
    返回：PASS（退出码 0）/ FAIL（含修复建议）。
    """
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GH_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return Report(
            gate_id="GATE-GH-AUTH",
            decision=Decision.FAIL,
            code="GH-AUTH-TIMEOUT",
            message=f"gh auth status 超时（>{_GH_TIMEOUT_SEC}s）",
            fix_hint="检查网络连通性后重试；或运行 gh auth status 手工确认",
        )
    except FileNotFoundError:
        return Report(
            gate_id="GATE-GH-AUTH",
            decision=Decision.FAIL,
            code="GH-NOT-FOUND",
            message="gh CLI 未安装或不在 PATH",
            fix_hint="安装 gh CLI：https://cli.github.com/；安装后运行 gh auth login",
        )
    except OSError as exc:
        return Report(
            gate_id="GATE-GH-AUTH",
            decision=Decision.FAIL,
            code="GH-OS-ERROR",
            message=f"gh 调用失败：{exc}",
            fix_hint="检查 gh CLI 可执行权限后重试",
        )

    if result.returncode != 0:
        # 仅打 WARNING 级日志，不输出 stderr（可能含 token 信息）
        print(
            "WARNING GATE-GH-AUTH gh auth status 返回非零，gh CLI 未登录",
            file=sys.stderr,
        )
        return Report(
            gate_id="GATE-GH-AUTH",
            decision=Decision.FAIL,
            code="GH-NOT-LOGGED-IN",
            message="gh CLI 未登录，无法开 PR",
            fix_hint="运行 gh auth login 完成 GitHub 认证后重试 submit",
        )

    return Report(
        gate_id="GATE-GH-AUTH",
        decision=Decision.PASS,
    )


# 模块级导出
GATE_CLASS = GhAuthGate
