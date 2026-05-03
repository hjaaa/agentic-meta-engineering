"""GATE-BRANCH-MATCH：submit 时校验当前 git 分支与 meta.branch 一致（F-004）。

设计来源：requirements/REQ-2026-005/artifacts/detailed-design.md §4.4

职责：
  - 在 /requirement:submit 触发时，比对 `git branch --show-current` 与
    `meta.branch`，不一致则 FAIL 给出 R-BRANCH-MISMATCH 错误码 + git switch 修复建议
  - 防止"在 develop 误调 submit"或"切错 feature 分支"导致的错误 PR

precheck：
  - submit trigger 才生效；其他 trigger 直接 Skip（registry 已限制 triggers，
    保留 precheck 防御性兜底，与 base_reachable / gh_auth 风格一致）

外部依赖：
  - git CLI（系统提供，零新增依赖）
  - subprocess.run（必须 mock 测试）

实现约束：
  - subprocess timeout=5s（仅本地操作，不涉及网络）
  - check=False：git 非零退出当作失败信号自行处理，不抛 CalledProcessError
"""
from __future__ import annotations

import subprocess
from typing import Optional

from .base import Decision, Gate, GateContext, Report, Severity, Skip

# git branch --show-current 超时（秒）；纯本地查询，5s 足够兜底网络/IO 异常
_GIT_TIMEOUT_SEC = 5


class BranchMatchGate(Gate):
    """submit 时检查当前分支 == meta.branch 的门禁。"""

    id = "GATE-BRANCH-MATCH"
    severity = Severity.ERROR
    triggers = {"submit"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """仅 submit trigger 生效；其他 trigger 直接跳过。"""
        if ctx.trigger != "submit":
            return Skip(f"trigger={ctx.trigger!r} 非 submit；跳过 branch-match")
        return None

    def run(self, ctx: GateContext) -> Report:
        """读取当前分支与 meta.branch 比对，不一致 → FAIL。"""
        expected = ctx.meta.get("branch")
        if not expected:
            # meta.branch 缺失：明确 FAIL，避免 None == "" 之类的隐式语义
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="R-BRANCH-MISMATCH",
                message="meta.branch 字段缺失，无法校验分支一致性",
                fix_hint="在 requirements/<REQ>/meta.yaml 补全 branch 字段",
            )
        return _check_branch_match(expected)


def _check_branch_match(expected: str) -> Report:
    """执行 git branch --show-current 与 expected 比对，独立函数便于 mock。"""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return Report(
            gate_id="GATE-BRANCH-MATCH",
            decision=Decision.FAIL,
            code="R-BRANCH-MISMATCH",
            message=f"git branch --show-current 超时（>{_GIT_TIMEOUT_SEC}s）",
            fix_hint="检查本地 git 是否被锁；可手工运行 git branch --show-current 确认",
        )
    except FileNotFoundError:
        return Report(
            gate_id="GATE-BRANCH-MATCH",
            decision=Decision.FAIL,
            code="R-BRANCH-MISMATCH",
            message="git CLI 未找到",
            fix_hint="确认 git 已安装且在 PATH 中",
        )
    except OSError as exc:
        return Report(
            gate_id="GATE-BRANCH-MATCH",
            decision=Decision.FAIL,
            code="R-BRANCH-MISMATCH",
            message=f"git 调用失败：{exc}",
            fix_hint="检查 git CLI 可执行权限后重试",
        )

    if result.returncode != 0:
        return Report(
            gate_id="GATE-BRANCH-MATCH",
            decision=Decision.FAIL,
            code="R-BRANCH-MISMATCH",
            message=f"git branch --show-current 退出非零：{result.stderr.strip() or '(无 stderr)'}",
            fix_hint="确认当前位于 git 仓库根目录后重试",
        )

    current = (result.stdout or "").strip()
    if current != expected:
        return Report(
            gate_id="GATE-BRANCH-MATCH",
            decision=Decision.FAIL,
            code="R-BRANCH-MISMATCH",
            message=f"当前分支 {current!r} 与 meta.branch {expected!r} 不一致",
            fix_hint=f"git switch {expected}",
        )

    return Report(gate_id="GATE-BRANCH-MATCH", decision=Decision.PASS)


# 模块级导出（与 registry.py:_validate_s2_plugin 约定一致）
GATE_CLASS = BranchMatchGate
