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
import yaml  # noqa: E402（F-022：提至模块顶层）
from common import Report as LegacyReport  # noqa: E402
from common import Severity as LegacySeverity  # noqa: E402
import check_reviews  # noqa: E402

from .base import Decision, Gate, GateContext, Report, Severity, Skip

# phase-transition 的目标 phase → 必须存在的 review phase 映射
# 与 check_reviews.PHASE_REQUIREMENTS 保持一致（来源：scripts/lib/check_reviews.py:33-41）
_PHASE_REQUIREMENTS = check_reviews.PHASE_REQUIREMENTS


class ReviewVerdictGate(Gate):
    """reviewer verdict 门禁 gate（R001~R007 全规则包装）。"""

    id = "GATE-REVIEW-VERDICT"
    severity = Severity.ERROR
    # phase-transition 和 submit 时必须检查；ci 时扫全部需求
    triggers = {"phase-transition", "submit", "ci"}
    # H1 改造：R005 hash drift 命中 → ctx.staged_writes 暂存 → runner 全 pass 后 commit
    side_effects = "write_state"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        # ci trigger：扫全部需求，不需要 requirement_id 和 to_phase
        if ctx.trigger == "ci":
            return None

        if not ctx.requirement_id:
            return Skip("no requirement_id in context; review-verdict check skipped")

        if ctx.trigger == "phase-transition" and not ctx.to_phase:
            return Skip("phase-transition requires to_phase; review-verdict check skipped")

        # legacy=true 豁免（历史治理用）
        if ctx.meta.get("legacy") is True:
            return Skip(f"{ctx.requirement_id} legacy=true; review-verdict check skipped")

        return None

    def run(self, ctx: GateContext) -> Report:
        if ctx.trigger == "ci":
            return self._run_all_requirements(ctx)
        return self._run_single_requirement(ctx, ctx.requirement_id, ctx.to_phase)

    def _run_all_requirements(self, ctx: GateContext) -> Report:
        """ci trigger：扫全部 requirements/ 下的需求，汇总 findings。

        调用链：_load_req_meta → _should_skip_req → 主循环聚合。
        CC 保持 ≤ 6（来源：F-005 重构）。
        """
        req_root = _REPO_ROOT / "requirements"
        if not req_root.exists():
            return Report(gate_id=self.id, decision=Decision.PASS, message="no requirements dir")

        all_errors: list[tuple] = []
        all_warnings: list[tuple] = []

        for req_dir in sorted(req_root.iterdir()):
            if not req_dir.is_dir() or req_dir.name.startswith("."):
                continue
            req_id = req_dir.name
            meta = _load_req_meta(req_dir, all_warnings)
            if meta is None:
                continue
            if _should_skip_req(meta):
                continue
            _collect_findings(meta, req_id, all_errors, all_warnings)

        return _build_ci_report(self.id, all_errors, all_warnings)

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
        if not effective_phase or effective_phase not in _PHASE_REQUIREMENTS:
            return Report(
                gate_id=self.id,
                decision=Decision.PASS,
                message=f"target_phase={effective_phase!r} 无对应 review 要求；跳过",
            )

        legacy_report = LegacyReport()
        label = req_id
        _run_r_rules(legacy_report, meta, effective_phase, label, req_id, ctx.staged_writes)

        # 行为契约：把 legacy 完整 render 输出到 stdout
        if legacy_report.findings():
            print(legacy_report.render())

        return _legacy_to_report(self.id, legacy_report)

    def commit_staged_writes(self, ctx: GateContext) -> None:
        """H1 事务化：runner 全 pass 后调用，把 ctx.staged_writes 原子写入 meta.yaml。

        仅处理 path == "meta.yaml" 的暂存条目；其他 path 由对应 plugin 自己处理。
        多个 dot_key 一次性合并写入，减少 IO。
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
            _commit_meta_writes(meta_path, my_writes)
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


def _load_req_meta(req_dir: "Path", all_warnings: list[tuple]) -> "Optional[dict]":
    """读取 req_dir/meta.yaml；解析失败追加 warning 并返回 None。

    参数：
      req_dir      — 需求目录 Path（必须存在）
      all_warnings — 收集 warning 的列表（原地追加）
    """
    meta_path = req_dir / "meta.yaml"
    if not meta_path.exists():
        return None
    req_id = req_dir.name
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:  # noqa: BLE001
        print(
            f"WARNING GATE-REVIEW-VERDICT req={req_id} meta.yaml 解析失败: {exc}",
            file=sys.stderr,
        )
        all_warnings.append((req_id, "WARNING", "REVIEW-META-PARSE", f"meta.yaml 解析失败: {exc}"))
        return None


def _should_skip_req(meta: dict) -> bool:
    """判断是否应跳过当前需求（legacy 或 phase 无对应 review 要求）。

    参数：meta — meta.yaml 解析结果 dict。
    返回：True = 跳过；False = 继续校验。
    """
    if meta.get("legacy") is True:
        return True
    target_phase = meta.get("phase", "")
    return not target_phase or target_phase not in _PHASE_REQUIREMENTS


def _collect_findings(
    meta: dict,
    req_id: str,
    all_errors: list[tuple],
    all_warnings: list[tuple],
) -> None:
    """对单个需求跑 R001~R007，结果分类追加到 all_errors / all_warnings。

    参数：
      meta         — meta.yaml 解析结果
      req_id       — 需求 ID（用于日志 label）
      all_errors   — 收集 error 的列表（原地追加）
      all_warnings — 收集 warning 的列表（原地追加）

    ci trigger 走 _collect_findings 路径，不接 staged_writes（ci 是只读全量扫描）。
    """
    target_phase = meta.get("phase", "")
    legacy_report = LegacyReport()
    # ci 模式 staged_writes=None 让 _r005 走旧 CLI 行为（直接写盘 stale=true 也是历史可接受语义）
    _run_r_rules(legacy_report, meta, target_phase, req_id, req_id, None)
    for finding in legacy_report.findings():
        if finding[1] == LegacySeverity.ERROR:
            all_errors.append(finding)
        else:
            all_warnings.append(finding)


def _build_ci_report(gate_id: str, all_errors: list[tuple], all_warnings: list[tuple]) -> Report:
    """根据 ci trigger 汇总结果构造 Report。

    有 error → FAIL（first error 为主信息）；否则 PASS（warnings 附带）。
    """
    if all_errors:
        first = all_errors[0]
        return Report(
            gate_id=gate_id,
            decision=Decision.FAIL,
            code=first[2],
            message=f"{first[0]}: {first[3]}",
            fix_hint="对照 check-reviews.sh 规则修正对应 review 状态",
            vars={
                "errors": [list(f) for f in all_errors],
                "warnings": [list(f) for f in all_warnings],
            },
        )
    return Report(
        gate_id=gate_id,
        decision=Decision.PASS,
        vars={"warnings": [list(f) for f in all_warnings]} if all_warnings else {},
    )


def _run_r_rules(
    report: LegacyReport,
    meta: dict,
    target_phase: str,
    label: str,
    req_id: str,
    staged_writes: list | None,
) -> None:
    """运行 R001~R007 全部规则，结果写入 report。

    H1 事务化（来源：detailed-design.md §3.1）：
      staged_writes 非 None 时，R005 命中 drift 只 append 到暂存通道；
      为 None 时（如 ci trigger）走 CLI 旧行为（直接写盘 stale=true）。
    """
    check_reviews._r001_review_exists(meta, target_phase, report, label)
    check_reviews._r002_schema_recheck(meta, target_phase, report, label, req_id)
    check_reviews._r003_not_rejected(meta, target_phase, report, label)
    check_reviews._r004_needs_revision(meta, target_phase, report, label)
    # H1：传 staged_writes 让 R005 走事务化通道
    check_reviews._r005_hash_drift(meta, target_phase, report, label, req_id, staged_writes)
    check_reviews._r006_supersedes_chain(meta, target_phase, report, label, req_id)
    check_reviews._r007_code_by_feature_coverage(meta, target_phase, report, label, req_id)


def _legacy_to_report(gate_id: str, legacy: LegacyReport) -> Report:
    """把 common.Report 的 findings 列表降维成单条 Report。"""
    findings = legacy.findings()
    errors = [f for f in findings if f[1] == LegacySeverity.ERROR]
    warnings = [f for f in findings if f[1] == LegacySeverity.WARNING]

    if errors:
        first = errors[0]
        message = f"{first[0]}: {first[2]}: {first[3]}"
        return Report(
            gate_id=gate_id,
            decision=Decision.FAIL,
            code=first[2],
            message=message,
            fix_hint="对照 check-reviews.sh 规则修正对应 review 状态（R001~R007）",
            vars={
                "errors": [list(f) for f in errors],
                "warnings": [list(f) for f in warnings],
            },
        )

    return Report(
        gate_id=gate_id,
        decision=Decision.PASS,
        vars={"warnings": [list(f) for f in warnings]} if warnings else {},
    )


def _commit_meta_writes(meta_path: "Path", writes: list[tuple[str, str, object]]) -> None:
    """把多个 (path="meta.yaml", dot_key, value) 一次性原子写入 meta.yaml。

    使用 ruamel.yaml round-trip 保留注释（与 save_review.py 保持一致）。
    先写 .tmp 再 replace 保证原子性。

    F-010 round-2 加固：用 fcntl.lockf 对一个 sidecar lock 文件加排他锁，
    避免 commit-staged-writes 与 save_review CLI / 其他并发 runner 同时改同一份
    meta.yaml 触发 read-modify-write 数据竞争。锁随 with 块自动释放。
    """
    # 复用 save_review 的 ruamel 实例，避免依赖漂移
    import fcntl  # noqa: PLC0415
    import save_review as _save_review  # noqa: PLC0415

    lock_path = meta_path.with_suffix(meta_path.suffix + ".lock")
    # 'a' 模式确保锁文件存在；fcntl.lockf 在 fd 上加 LOCK_EX，关闭即释放
    with lock_path.open("a") as lock_f:
        fcntl.lockf(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                meta_rt = _save_review._meta_yaml.load(f) or {}

            for _path, dot_key, value in writes:
                _set_dot_path(meta_rt, dot_key, value)

            tmp_path = meta_path.with_suffix(meta_path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                _save_review._meta_yaml.dump(meta_rt, f)
            tmp_path.replace(meta_path)
        finally:
            fcntl.lockf(lock_f.fileno(), fcntl.LOCK_UN)


def _set_dot_path(target: dict, dot_key: str, value: object) -> None:
    """按 dot path 在 target dict 中递归设置 value，缺失节点自动建空 dict。"""
    parts = dot_key.split(".")
    node: dict = target
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


# 模块级导出
GATE_CLASS = ReviewVerdictGate
