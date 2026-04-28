"""GATE-PR-MERGED-STATE：submit 时校验 PR 合并状态闭环（H4）。

设计来源：requirements/REQ-2026-002/artifacts/detailed-design.md §3.2（行 275-304）。

职责：
  - 在 /requirement:submit 触发时检查 meta.yaml.pr_number 对应的 PR 是否已 MERGED
  - 已 MERGED → FAIL，提示用户走 /requirement:next 推进 phase（不能向已合并 PR push 新 commit）
  - 未 MERGED（OPEN / CLOSED 等）→ PASS

precheck：
  - meta.pr_number 缺失 → Skip（首次 submit；没有 PR 可比对）

外部依赖：
  - gh CLI（系统提供，零新增依赖）
  - subprocess.run（必须 mock 测试）
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Optional

from .base import Decision, Gate, GateContext, Report, Severity, Skip


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
        """调 gh pr view --json state,mergedAt 判断是否已 MERGED。"""
        pr_num = ctx.meta["pr_number"]
        data = _fetch_pr_state(pr_num)
        if data is None:
            # gh 调用失败：当作 warning 行为（FAIL with code GH-CALL-FAILED 让用户排查）
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="GH-CALL-FAILED",
                message=f"无法查询 PR #{pr_num} 状态（gh 不可用或鉴权失败）",
                fix_hint="检查 gh auth status / 网络连通性；或临时用 --skip 豁免",
                vars={"pr_number": pr_num},
            )

        state = data.get("state", "")
        if state == "MERGED":
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="PR-MERGED",
                message=(
                    f"PR #{pr_num} 已合并（mergedAt={data.get('mergedAt', '<unknown>')}），"
                    "禁止向已合并 PR 推送新 commit"
                ),
                fix_hint=(
                    "跑 /requirement:next 推进到下一阶段；如需开新 PR，"
                    "先清空 meta.pr_number 再重跑 submit"
                ),
                vars={"pr_number": pr_num, "merged_at": data.get("mergedAt")},
            )
        # OPEN / CLOSED / DRAFT 等都允许继续 submit（CLOSED 由用户判断是否重开）
        return Report(
            gate_id=self.id,
            decision=Decision.PASS,
            vars={"pr_number": pr_num, "state": state},
        )


def _fetch_pr_state(pr_num: object) -> Optional[dict]:
    """调 gh CLI 查询 PR 状态；任一异常返回 None 让上层走 GH-CALL-FAILED。

    返回：{"state": "MERGED"|"OPEN"|...,"mergedAt": "..."|None} 或 None。
    """
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_num), "--json", "state,mergedAt"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError) as exc:
        print(
            f"WARNING GATE-PR-MERGED-STATE gh 调用失败 pr={pr_num}: {exc}",
            file=sys.stderr,
        )
        return None
    if result.returncode != 0:
        print(
            f"WARNING GATE-PR-MERGED-STATE gh 返回非零 pr={pr_num} "
            f"rc={result.returncode} stderr={result.stderr.strip()[:200]}",
            file=sys.stderr,
        )
        return None
    try:
        return json.loads(result.stdout) or {}
    except json.JSONDecodeError as exc:
        print(
            f"WARNING GATE-PR-MERGED-STATE gh 输出非 JSON pr={pr_num}: {exc}",
            file=sys.stderr,
        )
        return None


# 模块级导出
GATE_CLASS = PrMergedStateGate
