"""GATE-REVIEW-VERDICT：reviewer verdict 门禁（R001~R007 全规则）。

设计说明（来源：detailed-design.md §3.1 + detailed-design.md §3.4）：
  承载 R001~R007 全部规则，复用 scripts/lib/check_reviews.py 中的各 _rXXX 函数。

  R005 事务化（H1 改造，来源：detailed-design.md §3.1，行 246-273）：
    - side_effects = "write_state"
    - run() 调用 _r005_hash_drift 时传入 ctx.staged_writes，只 append (path, dot_key, value)
    - commit_staged_writes() 在所有 gate pass 后由 runner 调用，原子写 meta.yaml
    - rollback() 清空 ctx.staged_writes（fail 路径丢弃暂存）

precheck：
  - 需要 ctx.requirement_id + ctx.to_phase 才能跑（缺失任一直接 Skip）
  - ctx.meta.get("legacy") == True 时短路（历史治理豁免）
  - trigger 非 phase-transition / submit / ci 时跳过（review 校验仅在这些时机有意义）

F-015 round-3 拆分：
  - 本文件保留 ReviewVerdictGate 类 + 单需求 run 路径 + commit_staged_writes / rollback
  - ci 全量扫描 → review_verdict_ci.py（run_all_requirements / load_req_meta / collect_findings / build_ci_report）
  - meta.yaml 原子写入 → meta_writer.py（commit_meta_writes / set_dot_path / fcntl 锁）
  目标：单文件降至约 180 行，三套独立职责拆开。

F-001 B 案 follow-up（submit --draft Skip 的 process 假设）：
  precheck 顶部 `submit --draft → Skip` 仅信任 CLI flag，不验证目标 PR 是否真为 draft。
  当前威胁模型可接受的依据：
    - 仓库定位为单人 agentic 工程骨架（非多租户生产服务），调用方就是 owner 自己
    - .claude/settings.json deny `git push --force:*`（不能强推覆盖）
    - protect-branch hook 阻断 main/master/develop 上的 Edit/Write/Bash 写操作
    - push / commit / Edit / Write 全走 ask 授权
  多人协作或开放外部贡献者时需补：
    - `gh pr view --json isDraft` 实证目标 PR 真为 draft
    - WARN 日志带 branch / req_id / 触发者，留 audit
    - 限 --draft 仅对非保护分支生效
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

# noqa: E402 —— sys.path 注入后才能 import
import yaml  # noqa: E402
from common import Report as LegacyReport  # noqa: E402
import check_reviews  # noqa: E402
import canonical_phases  # noqa: E402  canonical phase 枚举单一事实源（F-012 改自 phase_enum）

from .base import Decision, Gate, GateContext, Report, Severity, Skip
from . import review_verdict_ci  # F-015 round-3：ci 路径委托
from . import meta_writer  # F-015 round-3：meta.yaml 原子写入委托

# target-phase → 必须存在的 review phase 列表（plugin 本地副本，F-012 取代跨模块
# 共享 dict 的旧设计；详见 scripts/lib/check_reviews.py:_PHASE_REVIEW_DEPS 顶部的
# 设计动机注释）。
# 来源：context/team/engineering-spec/meta-schema.yaml `enums.phase`
_PHASE_REVIEW_DEPS: dict[str, list[str]] = {
    "tech-research":  ["definition"],
    "outline-design": ["definition"],
    "detail-design":  ["outline-design"],
    "task-planning":  ["detail-design"],
    "development":    ["detail-design"],
    "testing":        ["detail-design", "code"],
    "completed":      ["definition", "outline-design", "detail-design"],
}


class ReviewVerdictGate(Gate):
    """reviewer verdict 门禁 gate（R001~R007 全规则包装）。"""

    id = "GATE-REVIEW-VERDICT"
    severity = Severity.ERROR
    # phase-transition 和 submit 时必须检查；ci 时扫全部需求
    triggers = {"phase-transition", "submit", "ci"}
    # H1 改造：R005 hash drift 命中 → ctx.staged_writes 暂存 → runner 全 pass 后 commit
    side_effects = "write_state"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """前置门控：判断是否跳过本 gate（F-014 round-2 加 docstring）。

        参数：ctx — GateContext，含 trigger / requirement_id / to_phase / meta。
        返回：Skip 跳过本 gate 并解释原因；None 继续 run。
        分支：
          - ci trigger：始终运行（扫全部 requirements/）
          - phase-transition：缺 to_phase 时跳过（无目标 phase 无法判定 review 要求）
          - legacy=true：历史治理需求豁免 R001~R007
        """
        # B 案：submit --draft 模式跳过 review verdict（必须放最顶，先于 ci/legacy 等所有判断）
        # 草稿 PR 场景下 review 尚未完成属预期，不应阻断推送
        if ctx.trigger == "submit" and (ctx.cli_flags or {}).get("draft"):
            return Skip("submit --draft 模式；跳过 review-verdict 校验")

        # ci trigger：扫全部需求，不需要 requirement_id 和 to_phase
        if ctx.trigger == "ci":
            return None

        if not ctx.requirement_id:
            # F-035 round-2：Skip reason 中文化
            return Skip("ctx.requirement_id 缺失；跳过 review-verdict 校验")

        if ctx.trigger == "phase-transition" and not ctx.to_phase:
            return Skip("phase-transition 缺 to_phase；跳过 review-verdict 校验")

        # legacy=true 豁免（历史治理用）
        if ctx.meta.get("legacy") is True:
            return Skip(f"{ctx.requirement_id} 标记 legacy=true；跳过 review-verdict 校验")

        return None

    def run(self, ctx: GateContext) -> Report:
        """主流程：按 trigger 分流到 ci 全量扫描或单需求校验（F-014 round-2 加 docstring）。

        参数：ctx — GateContext。
        返回：Report —— PASS（含 warnings vars）或 FAIL（首个 error 为 message，
              全集放 vars.errors / vars.warnings）。
        H1：trigger ∈ {phase-transition, submit} 时走 staged_writes 暂存通道；
            ci trigger 走 None 通道（仅扫描，不暂存写态）。
        F-015 round-3：ci 分支委托给 review_verdict_ci.run_all_requirements。
        """
        if ctx.trigger == "ci":
            return review_verdict_ci.run_all_requirements(self.id)
        return self._run_single_requirement(ctx, ctx.requirement_id, ctx.to_phase)

    def _run_single_requirement(
        self, ctx: GateContext, req_id: Optional[str], target_phase: Optional[str]
    ) -> Report:
        """phase-transition / submit trigger：检查指定需求。"""
        assert req_id is not None

        try:
            meta = check_reviews._load_meta(req_id)
        except FileNotFoundError as exc:
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="REVIEW-META-MISSING",
                message=str(exc),
                fix_hint="确认 requirements/<REQ-ID>/meta.yaml 存在",
            )

        if meta.get("legacy") is True:
            return Report(
                gate_id=self.id,
                decision=Decision.PASS,
                message=f"{req_id} legacy=true；跳过 R001~R007",
            )

        # submit trigger 时，target_phase 取 meta 中当前 phase
        effective_phase = target_phase or meta.get("phase", "")

        # fail-closed：typo / 非法 phase 名直接报错，避免静默 vacuous pass
        # （历史 bug：'technical-research' 因不在 _PHASE_REVIEW_DEPS 中而走下面 PASS 分支）
        valid_phases = canonical_phases.load_canonical_phases()
        if effective_phase and effective_phase not in valid_phases:
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="REVIEW-INVALID-PHASE",
                message=(
                    f"target_phase={effective_phase!r} 不在 canonical phase 枚举内 "
                    f"({sorted(valid_phases)})；可能 phase 名拼写有误"
                ),
                fix_hint=(
                    "检查 meta.yaml.phase 或 --to/--from 参数；canonical 枚举见 "
                    "context/team/engineering-spec/meta-schema.yaml:38"
                ),
            )

        if not effective_phase or effective_phase not in _PHASE_REVIEW_DEPS:
            return Report(
                gate_id=self.id,
                decision=Decision.PASS,
                message=f"target_phase={effective_phase!r} 无对应 review 要求；跳过",
            )

        required_phases = _PHASE_REVIEW_DEPS[effective_phase]
        legacy_report = LegacyReport()
        review_verdict_ci.run_r_rules(
            legacy_report, meta, effective_phase, required_phases, req_id, req_id, ctx.staged_writes
        )

        # 行为契约：把 legacy 完整 render 输出到 stdout
        if legacy_report.findings():
            print(legacy_report.render())

        return review_verdict_ci.legacy_to_report(self.id, legacy_report)

    def commit_staged_writes(self, ctx: GateContext) -> None:
        """H1 事务化：runner 全 pass 后调用，把 ctx.staged_writes 原子写入 meta.yaml。

        仅处理 path == "meta.yaml" 的暂存条目；其他 path 由对应 plugin 自己处理。
        多个 dot_key 一次性合并写入，减少 IO。
        F-015 round-3：实际写入委托给 meta_writer.commit_meta_writes（含 fcntl 锁）。
        """
        if not ctx.requirement_id or not ctx.staged_writes:
            return
        my_writes = [(p, k, v) for (p, k, v) in ctx.staged_writes if p == "meta.yaml"]
        if not my_writes:
            return
        meta_path = _REPO_ROOT / "requirements" / ctx.requirement_id / "meta.yaml"
        if not meta_path.exists():
            print(
                f"WARNING GATE-REVIEW-VERDICT commit 跳过 req={ctx.requirement_id} "
                f"meta.yaml 不存在 path={meta_path}",
                file=sys.stderr,
            )
            return
        try:
            meta_writer.commit_meta_writes(meta_path, my_writes)
        except (OSError, yaml.YAMLError) as exc:
            # 写盘失败：保留 staged_writes 让 runner 走 rollback 路径恢复
            print(
                f"ERROR GATE-REVIEW-VERDICT commit 失败 req={ctx.requirement_id} "
                f"path={meta_path}: {exc}",
                file=sys.stderr,
            )
            raise
        # 成功后清空，避免被其他 plugin 重复消费
        ctx.staged_writes[:] = [
            (p, k, v) for (p, k, v) in ctx.staged_writes if p != "meta.yaml"
        ]

    def rollback(self, ctx: GateContext) -> None:
        """H1 事务化：fail 路径丢弃 meta.yaml 暂存（runner 还会 _restore_state 恢复磁盘备份）。

        异常不静默，按 F-002 review-003 经验需要 WARNING 上抛 runner 处理。
        """
        try:
            ctx.staged_writes[:] = [
                (p, k, v) for (p, k, v) in ctx.staged_writes if p != "meta.yaml"
            ]
        except Exception as exc:  # noqa: BLE001
            print(
                f"WARNING GATE-REVIEW-VERDICT rollback 异常 req={ctx.requirement_id}: {exc}",
                file=sys.stderr,
            )
            raise


# 模块级导出
GATE_CLASS = ReviewVerdictGate
