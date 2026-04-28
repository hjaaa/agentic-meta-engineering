"""GATE-REVIEWS-CONSISTENCY：reviews/*.json 与 meta.yaml.reviews 段双向一致性校验。

设计说明（来源：detailed-design.md §3.4 + PR3 commit 27af77f D7-2 逻辑复活）：

  防止主对话 LLM 或人工直接 Edit meta.yaml.reviews 段 / reviews/*.json，
  绕过 save-review.sh / check-reviews.sh 的唯一合法写入通道。

  双向校验逻辑：
  - 正向：staged meta.yaml.reviews 段有 diff → 同目录 reviews/*.json 必须同步 staged
  - 反向：staged reviews/*.json 有改动    → 同目录 meta.yaml 必须同步 staged

  review 子键白名单（同 PR3 D7-2）：
    latest / conclusion / reviewed_commit / artifact_hashes / history / stale / by_feature

precheck：
  - trigger 非 pre-commit 时直接 Skip（仅在提交阶段有意义）
  - changed_files 中无 meta.yaml / reviews/*.json 时直接 Skip

side_effects：none（只做读检查，不写文件）
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from .base import Decision, Gate, GateContext, Report, Severity, Skip

# meta.yaml.reviews 段的子键白名单（与 PR3 D7-2 保持一致）
_REVIEWS_SUBKEYS = re.compile(
    r"^[+-][ \t]*(reviews:|[ \t]+(latest|conclusion|reviewed_commit|artifact_hashes|history|stale|by_feature):)"
)

# staged 文件路径正则
_META_PATTERN = re.compile(r"^requirements/[^/]+/meta\.yaml$")
_REVIEWS_JSON_PATTERN = re.compile(r"^requirements/[^/]+/reviews/.*\.json$")


class ReviewsConsistencyGate(Gate):
    """reviews/*.json 与 meta.yaml.reviews 段双向一致性校验 gate。"""

    id = "GATE-REVIEWS-CONSISTENCY"
    severity = Severity.ERROR
    triggers = {"pre-commit"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """仅 pre-commit trigger 需要检查；无相关 staged 文件时跳过。

        参数约束：ctx.trigger 必须为 pre-commit；ctx.changed_files 由 runner 注入。
        """
        if ctx.trigger != "pre-commit":
            return Skip(f"trigger={ctx.trigger!r} 非 pre-commit；跳过双向一致性校验")

        # 快速过滤：staged 中无 meta.yaml 且无 reviews/*.json 时直接跳过
        has_meta = any(_META_PATTERN.match(f) for f in ctx.changed_files)
        has_reviews = any(_REVIEWS_JSON_PATTERN.match(f) for f in ctx.changed_files)
        if not has_meta and not has_reviews:
            return Skip("staged 文件中无 meta.yaml / reviews/*.json；跳过双向一致性校验")

        return None

    def run(self, ctx: GateContext) -> Report:
        """双向校验 staged reviews/*.json ↔ meta.yaml.reviews 段同步性。

        正向：meta.yaml.reviews 段被改 → 同目录 reviews/*.json 必须同步 staged。
        反向：reviews/*.json 被改     → 同目录 meta.yaml 必须同步 staged。

        失败场景：
          REVIEWS-META-ONLY  — 只改了 meta.yaml.reviews 但无对应 reviews/*.json
          REVIEWS-JSON-ONLY  — 只改了 reviews/*.json 但无对应 meta.yaml
        """
        staged = _get_staged_files()
        meta_changed = [f for f in staged if _META_PATTERN.match(f)]
        reviews_changed = [f for f in staged if _REVIEWS_JSON_PATTERN.match(f)]

        # 正向校验：meta.yaml.reviews 段被改 → 必须有 reviews/*.json 同步 staged
        for meta_path in meta_changed:
            if not _has_reviews_diff(meta_path):
                # meta.yaml 被 staged 但 reviews: 段无改动，不需要同步
                continue
            req_dir = str(Path(meta_path).parent)
            has_json = any(
                f.startswith(req_dir + "/reviews/") and f.endswith(".json")
                for f in reviews_changed
            )
            if not has_json:
                return Report(
                    gate_id=self.id,
                    decision=Decision.FAIL,
                    code="REVIEWS-META-ONLY",
                    message=(
                        f"{meta_path} 的 reviews: 段被改，"
                        f"但 {req_dir}/reviews/*.json 无对应 staged 改动"
                    ),
                    fix_hint=(
                        "meta.yaml.reviews 必须由 save-review.sh 自动维护，不允许手工 Edit。\n"
                        "如确实需要更新 review 记录，请让 reviewer Agent 重新评审（supersedes 链）；\n"
                        "紧急绕过：git commit --no-verify（CI 仍会拦截）"
                    ),
                    vars={"meta_path": meta_path, "req_dir": req_dir},
                )

        # 反向校验：reviews/*.json 被改 → 对应 meta.yaml 必须同步 staged
        for r_path in reviews_changed:
            # 路径形如 requirements/REQ-XXX/reviews/foo.json
            req_dir = str(Path(r_path).parent.parent)
            meta_path = req_dir + "/meta.yaml"
            if not any(f == meta_path for f in meta_changed):
                return Report(
                    gate_id=self.id,
                    decision=Decision.FAIL,
                    code="REVIEWS-JSON-ONLY",
                    message=(
                        f"{r_path} 被改，"
                        f"但 {meta_path} 未同步 staged"
                    ),
                    fix_hint=(
                        "应通过 save-review.sh / check-reviews.sh 重新生成 meta.yaml.reviews 段后再 commit。\n"
                        "紧急绕过：git commit --no-verify"
                    ),
                    vars={"reviews_path": r_path, "meta_path": meta_path},
                )

        return Report(
            gate_id=self.id,
            decision=Decision.PASS,
            message="reviews/*.json 与 meta.yaml.reviews 段双向同步一致",
        )


def _get_staged_files() -> list[str]:
    """获取 staged 文件列表（git diff --cached --name-only）。

    失败时返回空列表，不抛出（让调用方做 skip 处理）。
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            check=False,
        )
        return [f for f in result.stdout.splitlines() if f.strip()]
    except (FileNotFoundError, OSError):
        return []


def _has_reviews_diff(meta_path: str) -> bool:
    """检查 meta.yaml 的 staged diff 中是否含 reviews: 段改动。

    扫描 git diff --cached -U0 输出，匹配 reviews 子键白名单。
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "-U0", "--", meta_path],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return False

    for line in result.stdout.splitlines():
        if _REVIEWS_SUBKEYS.match(line):
            return True
    return False


# 模块级导出
GATE_CLASS = ReviewsConsistencyGate
