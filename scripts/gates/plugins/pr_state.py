"""GATE-PR-MERGED-STATE：submit 时校验 PR 合并状态闭环（H4）。

设计来源：requirements/REQ-2026-002/artifacts/detailed-design.md §3.2（行 275-304）。

职责：
  - 在 /requirement:submit 触发时检查 meta.yaml.pr_number 对应的 PR 是否已 MERGED
  - 已 MERGED → FAIL，提示用户走 /requirement:next 推进 phase（不能向已合并 PR push 新 commit）
  - 未 MERGED（OPEN / CLOSED 等）→ PASS

precheck：
  - meta.pr_number 缺失 → Skip（首次 submit；没有 PR 可比对）
  - meta.pr_number 不是合法整数（注入防御）→ FAIL 走 PR-NUMBER-INVALID

外部依赖：
  - gh CLI（系统提供，零新增依赖）
  - subprocess.run（必须 mock 测试）

加固（round-2 review 修复，来源：reviews/code-F-003-001.json F-016/F-022/F-025/F-029）：
  - F-016：GH-CALL-FAILED 降级为 PASS + WARNING（不直接阻断 submit），保留 fix_hint
  - F-022：pr_number 入口 re.match 整数校验，拒绝注入字符
  - F-025：subprocess.run timeout=30 + TimeoutExpired；模块级 _PR_STATE_CACHE
    避免同进程多次 submit 重复请求
  - F-029：state 字段缺失打 WARNING + Report.vars state_missing=True，避免静默 PASS
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import Optional

from .base import Decision, Gate, GateContext, Report, Severity, Skip

# pr_number 必须是 1-9 位纯数字（GitHub PR 编号格式约束）
_PR_NUMBER_PATTERN = re.compile(r"^\d{1,9}$")

# F-025：模块级缓存避免同进程多次 submit 重复请求 gh
# key=str(pr_num)，value={"state": "...", "mergedAt": "..."} 或 None（曾失败）
_PR_STATE_CACHE: dict[str, Optional[dict]] = {}

# F-025：gh 调用超时（秒）；submit 路径接受较长等待，但避免无限期挂起
_GH_TIMEOUT_SEC = 30


class PrMergedStateGate(Gate):
    """submit 时检查 PR 是否已合并的门禁。"""

    id = "GATE-PR-MERGED-STATE"
    severity = Severity.ERROR
    triggers = {"submit"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """submit 才生效；缺 pr_number 则跳过（首次 submit 场景）。"""
        if ctx.trigger != "submit":
            return Skip(f"trigger={ctx.trigger!r} 非 submit；跳过 pr-merged-state")
        if not ctx.meta.get("pr_number"):
            return Skip("meta.pr_number 缺失（首次 submit）；跳过 pr-merged-state")
        return None

    def run(self, ctx: GateContext) -> Report:
        """调 gh pr view --json state,mergedAt 判断是否已 MERGED。

        F-022：在 fetch 前对 pr_number 做整数校验，防止注入污染日志/命令。
        F-016：gh 调用失败 → Decision.PASS 降级（不阻断 submit），WARNING 已在 _fetch 打。
        """
        pr_num_raw = ctx.meta["pr_number"]
        pr_num_str = str(pr_num_raw)
        # F-022：拒绝非整数 pr_number（log injection / 命令污染防御）
        if not _PR_NUMBER_PATTERN.match(pr_num_str):
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="PR-NUMBER-INVALID",
                message=f"meta.pr_number 不是合法整数（pattern={_PR_NUMBER_PATTERN.pattern}）",
                fix_hint="修正 meta.yaml 的 pr_number 为正整数，或清空后重跑 submit",
                vars={"pr_number_raw": pr_num_str[:50]},
            )

        data = _fetch_pr_state(pr_num_str)
        if data is None:
            # F-016：gh 调用失败降级为 PASS + WARNING，避免鉴权过期/网络抖动直接阻断 submit
            print(
                f"WARNING GATE-PR-MERGED-STATE gh 不可用 pr={pr_num_str}，"
                "降级为 PASS（请检查 gh auth status / 网络连通性）",
                file=sys.stderr,
            )
            return Report(
                gate_id=self.id,
                decision=Decision.PASS,
                vars={"pr_number": pr_num_str, "gh_call_failed": True},
            )

        state = data.get("state", "")
        if not state:
            # F-029：state 缺失 → 不静默，打 WARNING + vars 标注，让 audit 可追溯
            print(
                f"WARNING GATE-PR-MERGED-STATE PR #{pr_num_str} 返回 JSON 缺 state 字段，"
                "无法判定合并状态；按 PASS 放行但记录 state_missing=True",
                file=sys.stderr,
            )
            return Report(
                gate_id=self.id,
                decision=Decision.PASS,
                vars={"pr_number": pr_num_str, "state_missing": True},
            )

        if state == "MERGED":
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="PR-MERGED",
                message=(
                    f"PR #{pr_num_str} 已合并（mergedAt={data.get('mergedAt', '<unknown>')}），"
                    "禁止向已合并 PR 推送新 commit"
                ),
                fix_hint=(
                    "跑 /requirement:next 推进到下一阶段；如需开新 PR，"
                    "先清空 meta.pr_number 再重跑 submit"
                ),
                vars={"pr_number": pr_num_str, "merged_at": data.get("mergedAt")},
            )

        # F-005：CLOSED 状态加 INFO 标记（不阻断 submit，但在 vars 留审计痕迹）
        if state == "CLOSED":
            return Report(
                gate_id=self.id,
                decision=Decision.PASS,
                message=(
                    f"PR #{pr_num_str} 已 CLOSED；如需继续推进请确认是否需要重开 PR"
                ),
                vars={
                    "pr_number": pr_num_str,
                    "state": state,
                    "pr_state_closed": True,
                    "severity_hint": "info",
                },
            )

        # OPEN / DRAFT 等继续 submit
        return Report(
            gate_id=self.id,
            decision=Decision.PASS,
            vars={"pr_number": pr_num_str, "state": state},
        )


def _cache_miss(pr_num: str, reason: str, detail: object = "") -> None:
    """打 WARNING + 写失败缓存的统一 helper（F-016 round-3 抽出）。

    4 个异常 handler 各缩短为 2 行（_cache_miss + return None），新增异常类型时
    不再有遗漏「set cache=None」的风险（之前 4 处重复三步模式：print + cache + return）。
    """
    suffix = f": {detail}" if detail != "" else ""
    print(
        f"WARNING GATE-PR-MERGED-STATE {reason} pr={pr_num}{suffix}",
        file=sys.stderr,
    )
    _PR_STATE_CACHE[pr_num] = None


def _fetch_pr_state(pr_num: str) -> Optional[dict]:
    """调 gh CLI 查询 PR 状态；任一异常返回 None 让上层走降级路径。

    F-025 round-2：
      - subprocess.run timeout=30 + TimeoutExpired 兜底，避免网络挂起
      - 模块级 _PR_STATE_CACHE：同进程多次调用复用首次结果（含失败缓存为 None）
    F-016 round-3：4 类异常 handler 抽 _cache_miss helper（print + cache + return None）。

    返回：{"state": "MERGED"|"OPEN"|...,"mergedAt": "..."|None} 或 None。
    """
    if pr_num in _PR_STATE_CACHE:
        return _PR_STATE_CACHE[pr_num]

    try:
        result = subprocess.run(
            ["gh", "pr", "view", pr_num, "--json", "state,mergedAt"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GH_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        _cache_miss(pr_num, "gh 超时", f"timeout={_GH_TIMEOUT_SEC}s")
        return None
    except (FileNotFoundError, OSError) as exc:
        _cache_miss(pr_num, "gh 调用失败", exc)
        return None
    if result.returncode != 0:
        _cache_miss(
            pr_num,
            "gh 返回非零",
            f"rc={result.returncode} stderr={result.stderr.strip()[:200]}",
        )
        return None
    try:
        data = json.loads(result.stdout) or {}
    except json.JSONDecodeError as exc:
        _cache_miss(pr_num, "gh 输出非 JSON", exc)
        return None
    _PR_STATE_CACHE[pr_num] = data
    return data


# 模块级导出
GATE_CLASS = PrMergedStateGate
