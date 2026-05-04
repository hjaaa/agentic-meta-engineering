"""GATE-AHEAD-OF-ORIGIN：submit 时校验本地分支相对 origin/<base> 至少有一个新 commit（F-004）。

设计来源：requirements/REQ-2026-005/artifacts/detailed-design.md §4.4

职责：
  - 在 /requirement:submit 触发时，跑 `git rev-list --count origin/<base>..HEAD`；
    输出 0 → 没有新 commit 可推 → FAIL，错误码 R-NOTHING-TO-PUSH
  - 防止"刚切完分支没改东西就误开 PR"

base 解析顺序（与 base_reachable._resolve_base_branch 同款）：
  1. ctx.cli_flags["target"]（submit.py --target / run.py --target 透传）
  2. ctx.meta["base_branch"]
  3. fallback "develop"

外部依赖：
  - git CLI（系统提供，零新增依赖）
  - subprocess.run（必须 mock 测试）

实现约束：
  - subprocess timeout=10s（可能涉及 origin 引用的本地解析）
"""
from __future__ import annotations

import json
import subprocess
from typing import Optional

from .base import Decision, Gate, GateContext, Report, Severity, Skip

_GIT_TIMEOUT_SEC = 10
_DEFAULT_BASE = "develop"


class AheadOfOriginGate(Gate):
    """submit 时检查本地相对 origin/<base> 有新 commit 的门禁。"""

    id = "GATE-AHEAD-OF-ORIGIN"
    severity = Severity.ERROR
    triggers = {"submit"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """仅 submit trigger 生效；非 submit 直接跳过。
        B 案放宽：submit 时若当前分支已有 open PR → Skip（避免重复推导致冲突）。
        """
        if ctx.trigger != "submit":
            return Skip(f"trigger={ctx.trigger!r} 非 submit；跳过 ahead-of-origin")
        branch = _detect_source_branch(ctx)
        if branch and _pr_open_for_branch(branch):
            return Skip(f"分支 {branch!r} 已有 open PR；跳过 ahead-of-origin")
        return None

    def run(self, ctx: GateContext) -> Report:
        """解析 base 后跑 git rev-list --count origin/<base>..HEAD。"""
        base = _resolve_base(ctx)
        return _check_ahead_of_origin(base)


def _detect_source_branch(ctx: GateContext) -> str:
    """优先 ctx.cli_flags.source_branch；回退 git symbolic-ref --short HEAD。

    空字符串表示无法确定当前分支（detached HEAD / git 不可用）。
    """
    cli_flags = ctx.cli_flags or {}
    explicit = cli_flags.get("source_branch")
    if explicit:
        return str(explicit)
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            capture_output=True, text=True, check=False, timeout=_GIT_TIMEOUT_SEC,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _pr_open_for_branch(branch: str) -> bool:
    """gh pr list --head <branch> --state open --limit 1 --json number；命中即 True。

    fail-closed：gh 缺失 / returncode≠0 / JSON 解析失败 / branch 为空 → False
    （不放行 skip，让主路径继续校验；避免 gh 鉴权问题导致假豁免）。
    """
    if not branch:
        return False
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--state", "open",
             "--limit", "1", "--json", "number"],
            capture_output=True, text=True, check=False, timeout=_GIT_TIMEOUT_SEC,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    if result.returncode != 0:
        return False
    try:
        data = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return False
    return isinstance(data, list) and len(data) > 0


def _resolve_base(ctx: GateContext) -> str:
    """优先 cli_flags.target，回退 meta.base_branch，再 fallback develop。

    与 base_reachable._resolve_base_branch 保持同款顺序，确保 submit --target
    透传链路一致。
    """
    cli_flags = ctx.cli_flags or {}
    target = cli_flags.get("target")
    if target:
        return target
    return ctx.meta.get("base_branch") or _DEFAULT_BASE


def _check_ahead_of_origin(base: str) -> Report:
    """执行 git rev-list --count origin/<base>..HEAD，独立函数便于 mock。

    退出码 ≠ 0 → 当作 R-NOTHING-TO-PUSH（base 不存在或 git 失败）报错；
    输出可解析为 0 → R-NOTHING-TO-PUSH；
    输出 ≥ 1 → PASS。
    """
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"origin/{base}..HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return Report(
            gate_id="GATE-AHEAD-OF-ORIGIN",
            decision=Decision.FAIL,
            code="R-NOTHING-TO-PUSH",
            message=f"git rev-list 超时（>{_GIT_TIMEOUT_SEC}s）",
            fix_hint="检查本地 git 是否被锁后重试",
        )
    except FileNotFoundError:
        return Report(
            gate_id="GATE-AHEAD-OF-ORIGIN",
            decision=Decision.FAIL,
            code="R-NOTHING-TO-PUSH",
            message="git CLI 未找到",
            fix_hint="确认 git 已安装且在 PATH 中",
        )
    except OSError as exc:
        return Report(
            gate_id="GATE-AHEAD-OF-ORIGIN",
            decision=Decision.FAIL,
            code="R-NOTHING-TO-PUSH",
            message=f"git 调用失败：{exc}",
            fix_hint="检查 git CLI 可执行权限后重试",
        )

    if result.returncode != 0:
        return Report(
            gate_id="GATE-AHEAD-OF-ORIGIN",
            decision=Decision.FAIL,
            code="R-NOTHING-TO-PUSH",
            message=(
                f"git rev-list origin/{base}..HEAD 失败："
                f"{result.stderr.strip() or '(无 stderr)'}"
            ),
            fix_hint=(
                f"确认 origin/{base} 存在；可先 git fetch origin {base} 拉取"
            ),
        )

    raw = (result.stdout or "").strip()
    try:
        ahead = int(raw)
    except ValueError:
        return Report(
            gate_id="GATE-AHEAD-OF-ORIGIN",
            decision=Decision.FAIL,
            code="R-NOTHING-TO-PUSH",
            message=f"git rev-list 输出非整数：{raw!r}",
            fix_hint="git 行为异常；手工运行 git rev-list --count 确认",
        )

    if ahead == 0:
        return Report(
            gate_id="GATE-AHEAD-OF-ORIGIN",
            decision=Decision.FAIL,
            code="R-NOTHING-TO-PUSH",
            message=f"本地相对 origin/{base} 无新 commit，没有内容可推",
            fix_hint=(
                "至少先 git commit 一个改动；如已有 commit 但未对齐 base，"
                "确认 --target 是否正确"
            ),
        )

    return Report(gate_id="GATE-AHEAD-OF-ORIGIN", decision=Decision.PASS)


# 模块级导出
GATE_CLASS = AheadOfOriginGate
