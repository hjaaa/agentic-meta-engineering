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
  - gh CLI（仅 F-001 B 案 _pr_open_for_branch 用到；fail-closed 对 gh 缺失/未鉴权兜底）
  - subprocess.run（必须 mock 测试）

实现约束：
  - subprocess timeout=10s（可能涉及 origin 引用的本地解析）

环境变量依赖（F-001 B 案 follow-up）：
  - 推荐用 GH_TOKEN（环境变量鉴权）调 gh，避免 gh 写本地 ~/.config/gh/{hosts,state}.yml；
    多进程并发场景（虽然当前 GATE-AHEAD-OF-ORIGIN 仅 submit trigger 串行）下减少缓存竞争。
  - 或设 GH_CONFIG_DIR 隔离每个进程的 gh 配置目录。
  - 不设这两个变量也可正常工作；fail-closed 已兜底偶发鉴权异常 → 不 Skip 走主路径。

已知 TOCTOU 缺口（F-001 B 案 follow-up）：
  - precheck 时 gh pr list 看到 PR open → Skip；run 阶段 PR 可能被关闭/合并。
  - 业务语义可接受（push 自身会拒绝重复推送），doc-grade backlog；Skip reason 已带
    PR number 利于事后审计反查。
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
        Skip reason 带 PR number 便于事后审计（TOCTOU 异常时反查用）。
        """
        if ctx.trigger != "submit":
            return Skip(f"trigger={ctx.trigger!r} 非 submit；跳过 ahead-of-origin")
        branch = _detect_source_branch(ctx)
        if branch:
            pr_num = _pr_open_for_branch(branch)
            if pr_num is not None:
                return Skip(f"分支 {branch!r} 已有 open PR #{pr_num}；跳过 ahead-of-origin")
        return None

    def run(self, ctx: GateContext) -> Report:
        """解析 base 后跑 git rev-list --count origin/<base>..HEAD。"""
        base = _resolve_base(ctx)
        return _check_ahead_of_origin(base)


def _detect_source_branch(ctx: GateContext) -> str:
    """优先 ctx.cli_flags.source_branch；回退 git symbolic-ref --short HEAD。

    空字符串表示无法确定当前分支（detached HEAD / git 不可用）。

    注意：cli_flags["source_branch"] 是 **test-only override**——run.py / submit.py 的
    argparse 没暴露 --source-branch，仅供单测 mock 用，避免被误认为公开攻击面。
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


def _pr_open_for_branch(branch: str) -> Optional[int]:
    """gh pr list --head <branch> --state open --limit 1 --json number。

    返回：
      - 命中 → PR number（int），用于 Skip reason 反查审计
      - 未命中或异常 → None（不 Skip，走主路径）

    fail-closed 策略（None 路径覆盖）：
      - branch 为空（detached HEAD / git 不可用）
      - gh 缺失（FileNotFoundError）/ 进程异常（OSError）/ 超时
      - returncode ≠ 0（gh 未鉴权 / 仓库无权限 / 网络异常）
      - JSON 解析失败 / 非列表 / 空列表 / 缺 number 字段

    设计意图：fail-closed 让 gh 偶发问题（鉴权失效 / 网络抖动 / 缓存竞争）
    退化为"不 Skip 走主路径"而非"误 Skip 假豁免"，确保鉴权问题不会让门禁错误放行。
    """
    if not branch:
        return None
    # F-11（codex round-5 P2）已修 fork 同名分支假命中；F-12（codex round-6 P1）回退实现：
    # `gh pr list --head` 的 manual 明确「`<owner>:<branch>` 语法不支持」，前一版传
    # OWNER:BRANCH 让 gh 把 `:` 当作分支名一部分，命中永远空 → precheck 不再 skip
    # → 同分支已有 open PR 的 submit 重跑被错误拦下 R-NOTHING-TO-PUSH。
    # 正确做法：仍按 branch 名查，结果用 headRepositoryOwner 后过滤限定本 owner。
    owner = _detect_repo_owner()
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--state", "open",
             "--limit", "30", "--json", "number,headRepositoryOwner"],
            capture_output=True, text=True, check=False, timeout=_GIT_TIMEOUT_SEC,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or not data:
        return None
    # owner 已知 → 过滤到 headRepositoryOwner.login 等于本 owner 的 PR；
    # owner 未知（gh repo view 失败） → 不过滤（与 round-5 之前的旧行为兼容，fail-closed 由上层兜）
    candidates = data if owner is None else [
        pr for pr in data
        if isinstance(pr, dict)
        and isinstance(pr.get("headRepositoryOwner"), dict)
        and pr["headRepositoryOwner"].get("login") == owner
    ]
    if not candidates:
        return None
    first = candidates[0]
    if not isinstance(first, dict):
        return None
    pr_num = first.get("number")
    return pr_num if isinstance(pr_num, int) else None


def _detect_repo_owner() -> Optional[str]:
    """读当前 gh 仓库 owner（如 `hjaaa`）；失败时返 None，调用方退化为按 branch 名过滤。

    抽出独立函数便于单测 monkeypatch；与 `_pr_open_for_branch` 同级 fail-closed 风格。
    """
    try:
        proc = subprocess.run(
            ["gh", "repo", "view", "--json", "owner", "--jq", ".owner.login"],
            capture_output=True, text=True, check=False, timeout=_GIT_TIMEOUT_SEC,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    owner = (proc.stdout or "").strip()
    return owner or None


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
