"""统一门禁 runner 主入口。

设计文档：requirements/REQ-2026-002/artifacts/detailed-design.md §2.2

主要职责：
  1. 解析 CLI 参数 → 构造 GateContext（含 meta.yaml 解析）
  2. 加载 registry.yaml + S1~S10 schema 校验 + 拓扑无环（实现在 registry.py）
  3. 按 trigger + applies_when 过滤 gate
  4. 拓扑排序后顺序执行；side_effects=write_state 的 plugin 通过
     ctx.staged_writes 暂存，全 pass 后由 runner 调 commit_staged_writes 落盘
  5. 写 audit log 到 audit/<YYYY-MM>/<trigger>-<timestamp>.json（实现在 audit.py）
  6. 计算 exit code 返回（0 通过 / 1 存在 error / 2 自身异常）

F-012 round-2：registry / audit / schema 校验拆到独立模块（registry.py / audit.py），
本文件保留 re-export 以保持测试与外部代码的向后兼容。

使用：
  python scripts/gates/run.py --trigger=ci --dry-run
  python scripts/gates/run.py --trigger=phase-transition --req=REQ-2026-002 --from=X --to=Y
  python scripts/gates/run.py --validate-registry        # 仅校验 registry，不跑 gate
  python scripts/gates/run.py --trigger=adapter --legacy=check-meta requirements/REQ.../meta.yaml
"""
from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
import traceback
import unicodedata
from graphlib import TopologicalSorter
from pathlib import Path
from typing import Any, Optional

import pathspec
import yaml

# 把 plugins 包加入 import 路径
_PKG_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_ROOT.parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from plugins.base import (  # noqa: E402
    TRIGGERS,
    Decision,
    Gate,
    GateContext,
    Report,
    Severity,
)

# F-012 round-2：registry / audit / state_io 拆分为独立模块；本文件 re-export 保持向后兼容
import registry as _registry  # noqa: E402
import audit as _audit  # noqa: E402
import state_io as _state_io  # noqa: E402

# canonical phase 枚举单一事实源（scripts/lib/phase_enum.py）
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))
import phase_enum  # noqa: E402

# Re-export：测试和 triggers/submit.py 通过 `import run as runner_mod` 访问以下符号
RegistryError = _registry.RegistryError
_validate_registry_schema = _registry._validate_registry_schema
_validate_one_entry = _registry._validate_one_entry
_validate_write_state_plugin = _registry._validate_write_state_plugin
ID_PATTERN = _registry.ID_PATTERN
SEVERITY_VALUES = _registry.SEVERITY_VALUES
SIDE_EFFECTS_VALUES = _registry.SIDE_EFFECTS_VALUES
REGISTRY_PATH = _registry.REGISTRY_PATH


def load_registry(
    path: Optional[Path] = None,
    validate_only_ids: Optional[set[str]] = None,
) -> dict[str, Any]:
    """re-export 包装：把 run 模块级 REGISTRY_PATH（被测试 monkeypatch 的入口）
    传给底层 registry.load_registry。

    F-012 round-2：测试代码通过 `monkeypatch.setattr(runner_mod, "REGISTRY_PATH", x)`
    改路径；本包装确保 monkeypatch 真正生效（否则 registry.py 模块级 REGISTRY_PATH
    保持原值，覆盖被忽略）。
    """
    return _registry.load_registry(
        path=path if path is not None else REGISTRY_PATH,
        validate_only_ids=validate_only_ids,
    )

write_audit = _audit.write_audit
_build_audit = _audit.build_audit
_calc_exit_code = _audit.calc_exit_code
AUDIT_DIR = _audit.AUDIT_DIR
SCHEMA_VERSION = _audit.SCHEMA_VERSION

_stash_state = _state_io.stash_state
_restore_state = _state_io.restore_state
_cleanup_snapshots = _state_io.cleanup_snapshots

# 安全校验：requirement_id 白名单正则，防止路径穿越（F-001 review 建议）
_REQ_ID_PATTERN = r"^REQ-\d{4}-\d{3}$"


class GateFailed(Exception):
    """某个 severity=error gate 的 Decision.FAIL 触发的中断信号。"""

    def __init__(self, report: Report) -> None:
        super().__init__(f"{report.gate_id} failed: {report.message}")
        self.report = report


# ====================== CLI ======================


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析 runner 的 CLI 参数（F-022 round-3 补 docstring，与 submit.py:36 风格一致）。

    参数：argv — argparse 入参列表（不含程序名）。
    返回：argparse.Namespace，含 trigger / requirement_id / from_phase / to_phase /
          strict / dry_run / validate_registry / legacy / paths 字段。

    支持的 flag：
      --trigger             触发器名，白名单 ∈ {pre-tool-use, pre-commit, phase-transition,
                            submit, ci, post-dev, adapter}（adapter 在 _resolve_trigger 归一化为 ci）。
                            未给且未带 --validate-registry 时 main 退 2。
      --req                 需求 ID，必须匹配 ^REQ-\\d{4}-\\d{3}$（防路径穿越；非法格式直接 SystemExit(2)）。
      --from / --to         phase-transition 专用：源 phase / 目标 phase（其他 trigger 忽略）。
      --strict              warning 级 Decision.FAIL 也升为进程退出 1（默认仅 error 级失败升 1）。
      --dry-run             不执行 gate.run，仅打印执行计划后退 0。
      --validate-registry   仅跑 S1~S10 schema 校验后退 0；--trigger 缺失时也允许该路径单跑。
      --legacy              adapter 模式专用：旧入口名（白名单见 LEGACY_TO_PLUGIN：check-meta /
                            check-index / check-sourcing / check-reviews / check-plan / workspace-clean），
                            过滤 plan 后只保留对应 plugin。
      paths                 adapter 模式位置参数：旧入口要处理的目标文件（如 meta.yaml 路径）。

    退出码语义（main 返回 → triggers/pre_tool_use.sh 透传给 hook）：
      0  全部 gate 通过（含 SKIP / PASS）
      1  存在 severity=error 的 Decision.FAIL；strict 下 warning 级 fail 也升 1
      2  runner 自身异常 / 非法 trigger / 非法 requirement_id / registry 加载失败
         / 非法 --force-with-blockers reason（CLI 入参非法统一归 2）
    """
    p = argparse.ArgumentParser(description="统一门禁 runner")
    p.add_argument("--trigger", help="触发器：pre-tool-use|pre-commit|phase-transition|submit|ci|post-dev|adapter")
    p.add_argument("--req", dest="requirement_id", help="目标需求 ID，如 REQ-2026-002")
    p.add_argument("--from", dest="from_phase", help="phase-transition: 源 phase")
    p.add_argument("--to", dest="to_phase", help="phase-transition: 目标 phase")
    p.add_argument("--strict", action="store_true", help="warning 也视为失败")
    p.add_argument("--dry-run", action="store_true", help="不执行 gate.run，仅打印执行计划")
    p.add_argument("--validate-registry", action="store_true", help="仅校验 registry，不跑 gate")
    p.add_argument("--legacy", help="adapter 模式：包装某个旧 plugin（如 check-meta / check-index）")
    # F-004：推荐别名（语义更准确：仅放行 review-verdict tag 类 gate，非"任意 blocker"）
    p.add_argument(
        "--bypass-review-blockers",
        dest="force_with_blockers",
        default=None,
        metavar="REASON",
        help=(
            "submit / phase-transition trigger 专用 escape_hatch：仅放行 review-verdict tag "
            "类 gate（GATE-REVIEW-VERDICT 等），不放行 workspace_clean / meta_schema 等非 review 类失败；"
            "必须提供非空 reason；使用情况写入 audit log（escape_used: force-with-blockers）"
        ),
    )
    # F-004：旧名保留 6 个月迁移窗口（D-004 决策：2026-11-01 无条件删旧名）
    p.add_argument(
        "--force-with-blockers",
        dest="force_with_blockers",
        default=None,
        metavar="REASON",
        help="[DEPRECATED 2026-11-01] 等价于 --bypass-review-blockers；命中时打 stderr deprecation 提示",
    )
    p.add_argument(
        "--target",
        dest="target",
        default=None,
        metavar="BRANCH",
        help="目标 base 分支，覆盖 meta.base_branch（submit / phase-transition trigger 专用）",
    )
    p.add_argument("paths", nargs="*", help="adapter 模式下传入的目标文件（如 meta.yaml 路径）")
    return p.parse_args(argv)


# ====================== context 构造（F-011 round-2 拆分） ======================


def _validate_requirement_id(req_id: str) -> bool:
    """校验 requirement_id 格式，防止路径穿越（F-001 review 安全建议）。

    只接受 REQ-YYYY-NNN 格式（4 位年份 + 3 位序号），拒绝含 .. / / 等路径穿越字符的输入。
    """
    return bool(re.match(_REQ_ID_PATTERN, req_id))


def _resolve_trigger(trigger: Optional[str]) -> str:
    """trigger 白名单校验 + adapter 模式归一化（F-011 round-2 抽出）。

    返回归一化后的 trigger（adapter → 'ci'）；非法 trigger 直接 SystemExit(2)。
    """
    if trigger == "adapter":
        return "ci"
    if trigger not in (*TRIGGERS, "adapter"):
        # F-11：trigger 白名单校验，防止写 audit 到 AUDIT_DIR 之外
        print(f"ERROR --trigger 非法：{trigger!r}，合法值 {sorted(TRIGGERS)}", file=sys.stderr)
        raise SystemExit(2)
    return trigger


def _load_meta_for_req(req_id: Optional[str]) -> dict[str, Any]:
    """按 requirement_id 加载 meta.yaml（含路径穿越防御 + 解析失败降级）。"""
    if not req_id:
        return {}
    if not _validate_requirement_id(req_id):
        print(
            f"ERROR requirement_id={req_id!r} 格式非法，必须匹配 REQ-YYYY-NNN",
            file=sys.stderr,
        )
        raise SystemExit(2)
    meta_path = _REPO_ROOT / "requirements" / req_id / "meta.yaml"
    if not meta_path.exists():
        return {}
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as exc:
        print(f"WARNING 读取 meta.yaml 失败 req={req_id}：{exc}", file=sys.stderr)
        return {}


def _build_extra(args: argparse.Namespace, trigger: str) -> dict[str, Any]:
    """构造 ctx.extra（F-011 round-2 抽出）。

    包含 adapter 模式的 meta_paths + pre-tool-use 的 tool_name/file_path/command。
    """
    extra: dict[str, Any] = {}
    if args.legacy and args.paths:
        extra["meta_paths"] = args.paths
    # pre-tool-use trigger：从环境变量取 tool_name / file_path / command
    # （由 triggers/pre_tool_use.sh 解析 stdin 后注入；不让 plugin 自己读 os.environ）
    if trigger == "pre-tool-use":
        extra.setdefault("tool_name", os.environ.get("CLAUDE_HOOK_TOOL_NAME", ""))
        extra.setdefault("file_path", os.environ.get("CLAUDE_HOOK_FILE_PATH", ""))
        extra.setdefault("command", os.environ.get("CLAUDE_HOOK_COMMAND", ""))
    return extra


# F-15 / F-005 round-2：env 白名单常量（plugin 通过 ctx.env 读取，禁止直接 os.environ）
_ENV_WHITELIST = (
    "CLAUDE_HOOK_BRANCH",
    "CLAUDE_PROTECTED_BRANCHES",
    "CLAUDE_GATES_BYPASS",
    "CLAUDE_GATES_BYPASS_REASON",
    "SAVE_REVIEW_PID",  # F-005 round-2：save-review.sh 启动时 export 的 PID
)


def _build_env_whitelist() -> dict[str, str]:
    """从 os.environ 抽取白名单 key（F-011 round-2 抽出）。"""
    return {k: os.environ[k] for k in _ENV_WHITELIST if k in os.environ}


def _build_changed_files() -> list[str]:
    """pre-commit hook 通过 GATE_CHANGED_FILES 环境变量传入 staged 文件列表（换行分隔）。"""
    gate_changed = os.environ.get("GATE_CHANGED_FILES", "")
    if not gate_changed:
        return []
    return [f for f in gate_changed.splitlines() if f.strip()]


def build_context(args: argparse.Namespace) -> GateContext:
    """构造 GateContext（F-011 round-2 拆分：trigger / meta / extra / env / changed_files 子例程）。"""
    trigger = _resolve_trigger(args.trigger)
    meta = _load_meta_for_req(args.requirement_id)
    extra = _build_extra(args, trigger)
    changed_files = _build_changed_files()
    env = _build_env_whitelist()

    return GateContext(
        trigger=trigger,
        requirement_id=args.requirement_id,
        from_phase=args.from_phase,
        to_phase=args.to_phase,
        meta=meta,
        cli_flags={
            "strict": args.strict,
            "dry_run": args.dry_run,
            "legacy": args.legacy,
            "force_with_blockers": getattr(args, "force_with_blockers", None),
            # F-004：--target 透传给 base_reachable / ahead_of_origin 解析 base 分支
            "target": getattr(args, "target", None),
        },
        extra=extra,
        changed_files=changed_files,
        env=env,
    )


# ====================== 过滤 + 拓扑 ======================


def filter_gates(
    registry_data: dict[str, Any],
    ctx: GateContext,
    *,
    ignore_changed_files: bool = False,
) -> list[dict[str, Any]]:
    """按 trigger + applies_when 全部 5 字段过滤 gate（F-003 升级）。

    新增字段消费（每个字段满足"任一不命中即过滤掉"的 AND 语义；空值 = 不限制）：
      - applies_when.changed_files: list[str]   gitignore-style，pathspec 库匹配
      - applies_when.target_phase:  str | null  与 ctx.to_phase 比对
      - applies_when.current_phase_in: list[str] 与 ctx.meta.phase 比对
      - applies_when.transition:    str ("from->to") 与 ctx.from_phase->ctx.to_phase 比对
      - applies_when.requires:      list[str]    每项为 'meta.<field>'，要求该字段非空

    legacy grandfather：ctx.meta.get("legacy") is True 时，跳过 tags 含
      "legacy-bypass" 的 gate（如 GATE-TRACEABILITY 历史 REQ 没追溯链）。
      该判定优先于 5 字段过滤；命中跳过即不进 candidates。

    adapter 模式：ctx.cli_flags['legacy'] 指定旧入口名（如 check-meta），
      通过 LEGACY_TO_PLUGIN 映射到 plugin 名后只保留对应 gate；不走 5 字段过滤
      （旧入口快照行为契约）。

    参数：
      registry_data        — load_registry 返回值（dict，含 gates list）
      ctx                  — 当前执行上下文
      ignore_changed_files — 测试场景跳过 changed_files 过滤；默认 False
    """
    out: list[dict[str, Any]] = []
    legacy_adapter = ctx.cli_flags.get("legacy")
    legacy_plugin = LEGACY_TO_PLUGIN.get(legacy_adapter) if legacy_adapter else None
    is_legacy_meta = ctx.meta.get("legacy") is True

    for entry in registry_data.get("gates", []):
        # adapter 模式：仅保留命中 plugin 的 gate，不消费 applies_when（保旧契约）
        if legacy_adapter:
            if entry["plugin"] == legacy_plugin:
                out.append(entry)
            continue

        # 普通模式：trigger 命中是前置硬条件
        if ctx.trigger not in (entry.get("triggers") or []):
            continue

        # legacy grandfather：meta.legacy=true 跳过 legacy-bypass tag 的 gate
        if is_legacy_meta and "legacy-bypass" in (entry.get("tags") or []):
            continue

        # 5 字段 applies_when 过滤：任一字段不命中 → 该 gate 被剔除
        if not _matches_applies_when(entry, ctx, ignore_changed_files=ignore_changed_files):
            continue

        out.append(entry)
    return out


def _matches_applies_when(
    entry: dict[str, Any],
    ctx: GateContext,
    *,
    ignore_changed_files: bool,
) -> bool:
    """对单条 gate entry 跑 applies_when 5 字段命中判定（AND 逻辑）。

    任一字段为 None / 空列表 / 缺失 → 视为"不限制"，pass-through 不参与判定。
    所有非空字段必须全部命中，gate 才进 candidates。

    切分原因：filter_gates 主体保持 ≤ 60 行；本 helper 单独可单测。
    """
    aw = entry.get("applies_when") or {}

    # changed_files：pathspec 任一命中（仅 pre-commit trigger 起作用）
    # 设计依据：ci / phase-transition / submit / post-dev / pre-tool-use 不通过 staged
    # 文件列表过滤；changed_files 只在 pre-commit 路径短路那些与改动无关的 gate（保
    # 与 4 plugin 旧 precheck"if ctx.trigger == 'pre-commit'"一致的语义）。
    if (
        ctx.trigger == "pre-commit"
        and not ignore_changed_files
        and not _match_changed_files(aw.get("changed_files"), ctx.changed_files)
    ):
        return False
    # target_phase：与 ctx.to_phase 严格相等
    if not _match_target_phase(aw.get("target_phase"), ctx.to_phase):
        return False
    # current_phase_in：ctx.meta.phase 必须在列表中
    if not _match_current_phase_in(aw.get("current_phase_in"), ctx.meta.get("phase")):
        return False
    # transition：'from->to' 字面匹配 ctx.from_phase / ctx.to_phase
    if not _match_transition(aw.get("transition"), ctx.from_phase, ctx.to_phase):
        return False
    # requires：每项 'meta.<field>' 必须在 ctx.meta 中存在且非空
    if not _match_requires(aw.get("requires"), ctx.meta):
        return False

    return True


def _match_changed_files(patterns: Optional[list[str]], changed_files: list[str]) -> bool:
    """changed_files 字段命中：patterns 为空（None/[]）→ 不限制；否则 pathspec 任一命中即可。

    用 pathspec.GitIgnoreSpec 解析 gitignore-style 模式（与 .gitignore 语义一致）；
    解析失败抛 ValueError，调用方（filter_gates）让其冒泡——registry 配错应早爆而非静默。
    """
    if not patterns:
        return True
    if not changed_files:
        # 模式非空但本次无 changed_files：视为不命中（pre-commit hook 必须有改动才跑此类 gate）
        return False
    try:
        spec = pathspec.GitIgnoreSpec.from_lines(patterns)
    except (ValueError, TypeError) as exc:
        # 配置错误：明确报错，不静默放行
        raise RuntimeError(
            f"applies_when.changed_files 模式解析失败: {patterns!r}: {exc}"
        ) from exc
    # match_files 返回命中迭代器；用 any 短路
    return any(True for _ in spec.match_files(changed_files))


def _match_target_phase(target_phase: Optional[str], to_phase: Optional[str]) -> bool:
    """target_phase 字段命中：None → 不限制；非空必须 == ctx.to_phase。"""
    if target_phase is None:
        return True
    return target_phase == to_phase


def _match_current_phase_in(allowed: Optional[list[str]], current: Optional[str]) -> bool:
    """current_phase_in 字段命中：空列表/None → 不限制；非空必须包含 ctx.meta.phase。"""
    if not allowed:
        return True
    return current in allowed


def _match_transition(transition: Optional[str], from_phase: Optional[str], to_phase: Optional[str]) -> bool:
    """transition 字段命中：None → 不限制；'X->Y' 必须等于 from->to 字面拼接。"""
    if transition is None:
        return True
    if not from_phase or not to_phase:
        # 配置要求 transition 但 ctx 没给 from/to → 不命中
        return False
    return transition == f"{from_phase}->{to_phase}"


def _match_requires(requires: Optional[list[str]], meta: dict[str, Any]) -> bool:
    """requires 字段命中：空列表/None → 不限制；每项 'meta.<field>' 必须在 meta 中非空。

    支持 dot key（如 'meta.pr_number' / 'meta.foo.bar'）；S9 已强制要求 'meta.' 前缀。
    """
    if not requires:
        return True
    for key in requires:
        if not isinstance(key, str) or not key.startswith("meta."):
            # S9 应已拦下；保险兜底视作不命中
            return False
        # 'meta.foo.bar' → 取 ('foo', 'bar') 在 meta 中逐层查找
        path = key[len("meta."):].split(".")
        cursor: Any = meta
        for seg in path:
            if not isinstance(cursor, dict) or seg not in cursor:
                return False
            cursor = cursor[seg]
        # 非空判定：None / "" / [] / {} / 0 都视为不存在；本字段语义是"必须有值"
        if not cursor:
            return False
    return True


# 旧入口名 → plugin 名的映射（adapter 模式用；snapshot 行为契约用）
# F-002：补全全部 6 个旧入口（来源：requirements/REQ-2026-002/artifacts/detailed-design.md §5）
LEGACY_TO_PLUGIN: dict[str, str] = {
    "check-meta": "meta_schema",
    "check-index": "index_integrity",
    "check-sourcing": "sourcing",
    "check-reviews": "review_verdict",
    "check-plan": "plan_freshness",
    "workspace-clean": "workspace_clean",
}


def topological_sort(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 dependencies 拓扑排序，仅在候选集内的依赖参与（悬挂依赖已被 S5 拒绝）。"""
    if not entries:
        return []
    by_id = {e["id"]: e for e in entries}
    graph = {gid: set(d for d in (by_id[gid].get("dependencies") or []) if d in by_id)
             for gid in by_id}
    sorter = TopologicalSorter(graph)
    return [by_id[gid] for gid in sorter.static_order()]


def instantiate(entry: dict[str, Any]) -> Gate:
    """按 plugin 名实例化 Gate 子类。"""
    mod = importlib.import_module(f"plugins.{entry['plugin']}")
    return mod.GATE_CLASS()


# ====================== 主流程 ======================


def _validate_phase_args(args: argparse.Namespace) -> Optional[str]:
    """校验 --from / --to 是否在 canonical phase 枚举内 + 前进方向相邻。

    返回：None 表示通过；非空 str 为错误消息（调用方打 stderr 后退 2）。

    设计动机：
      历史 bug（REQ-2026-003 排查）——meta.yaml.phase 被写成 'technical-research'
      （应为 'tech-research'）后，phase-transition 门禁链上多处 vacuous pass：
        1. _r001_review_exists 用 PHASE_REQUIREMENTS.get(..., []) 默认空 list
        2. ReviewVerdictGate.run 同样落到 PASS 分支
      入口处先做白名单校验，把 typo 在最早一关拦下，比下游 plugin 各自防御更稳。

      REQ-2026-005 F-003 扩展：仅 typo 拦截不够——前进跨阶段（如 bootstrap→testing）
      会跳过中间 6 个阶段的所有评审 / 设计产物，必须在入口处再加"相邻校验"。

    校验规则：
      - args.from_phase / args.to_phase 任一为空时跳过（合法用法：CI 模式不传）
      - 非空且不在 canonical phases 时返回错误消息（typo 拦截）
      - 两端都在 canonical 内 + to 在 from 之后（前进方向）：必须为相邻对
        - 回退方向（to_idx <= from_idx）不校验，rollback 场景豁免
        - 错误码 R-INVALID-PHASE-TRANSITION（severity: error）
    """
    canonical = phase_enum.load_canonical_phases()
    for label, val in (("--from", args.from_phase), ("--to", args.to_phase)):
        if val and val not in canonical:
            return (
                f"{label}={val!r} 不在 canonical phase 枚举内 "
                f"({sorted(canonical)})；可能 phase 名拼写有误，"
                f"参考 context/team/engineering-spec/meta-schema.yaml:38"
            )

    # 两端非空 + 都已通过 canonical 校验时，做前进方向相邻校验
    if args.from_phase and args.to_phase:
        ordered = phase_enum.load_canonical_phases_ordered()
        try:
            from_idx = ordered.index(args.from_phase)
            to_idx = ordered.index(args.to_phase)
        except ValueError:
            # 已在上方 canonical 校验拦下；保险兜底，理论不会到此
            return None
        if to_idx > from_idx:  # 前进方向才校验相邻
            adjacent = phase_enum.load_adjacent_phases()
            if (args.from_phase, args.to_phase) not in adjacent:
                return (
                    f"R-INVALID-PHASE-TRANSITION "
                    f"非法 phase 跳跃 {args.from_phase}→{args.to_phase}（前进方向必须相邻）；"
                    f"canonical 顺序参考 context/team/engineering-spec/meta-schema.yaml:38"
                )
        # 回退方向（to_idx <= from_idx）不校验，rollback / 同 phase 重跑均合法
    return None


def _validate_force_reason(reason: Optional[str]) -> Optional[str]:
    """校验 --force-with-blockers reason 的三段合法性规则（F-004 round-3 抽出）。

    reason 为 None 时表示未传 --force-with-blockers，直接返回 None（无需校验）。
    三段规则任一不过时返回可直接打印的**错误消息字符串**；全部通过返回 None。

    参数：
      reason — argparse 解析出的 force_with_blockers 值；None 表示未提供该参数。

    返回：
      None    — 校验通过（含 reason=None 的"未提供"场景）。
      str     — 错误消息，调用方打印到 stderr 后返回退出码 2。

    规则：
      1. 非空：reason.strip() 非空。
      2. 长度：len(reason) ≤ 1024 字符。
      3. 控制字符：不含 unicodedata.category 以 'C' 开头的字符（\\t / \\n 例外）。
    """
    if reason is None:
        # 未传 --force-with-blockers，无需校验
        return None
    # 规则 1：非空
    if not reason.strip():
        return (
            "--force-with-blockers 必须提供非空 reason，"
            "如：--force-with-blockers='临时绕过：已有 Jira 跟进'"
        )
    # 规则 2：长度 ≤ 1024
    if len(reason) > 1024:
        return (
            f"--force-with-blockers reason 长度 {len(reason)} 超过上限 1024 字符；"
            "请缩减描述"
        )
    # 规则 3：无控制字符（\t / \n 例外）
    bad_chars = [
        ch for ch in reason
        if ch not in ("\t", "\n") and unicodedata.category(ch).startswith("C")
    ]
    if bad_chars:
        return (
            f"--force-with-blockers reason 含控制字符（{[repr(c) for c in bad_chars[:5]]}）；"
            "请移除控制字符后重试"
        )
    return None


def main(argv: Optional[list[str]] = None) -> int:
    """runner 主入口（F-022 round-3 补 docstring，与 submit.py:60 风格一致）。

    参数：argv — CLI 参数列表；None 时取 sys.argv[1:]（CLI 直跑场景）。
    返回：进程退出码（0 通过 / 1 含 error 级失败 / 2 自身异常）。

    流程：
      1. parse_args → trigger 白名单 / req-id 路径穿越校验在 build_context 内做
      2. load_registry：S1~S10 schema 校验；pre-tool-use 触发器开 validate_only_ids
         冷启动优化（只 import 候选 plugin，节省 ~12ms）
      3. --validate-registry：仅跑 S 校验，打印 OK 行后退 0
      4. dry-run：不执行 gate.run，按拓扑序打印执行计划后退 0
      5. 真实执行：进入 _execute_plan，含事务化 stash / commit_staged_writes / rollback /
         restore + audit 落盘

    异常路径：
      - RegistryError → 打 ERROR 后退 2（registry/plugin 自身故障）
      - 缺 trigger 且未带 --validate-registry → 打 ERROR 后退 2
      - plugin 抛未捕获异常 → 由 _handle_runner_exception 兜底退 2 + 写 audit
    """
    raw_argv = argv if argv is not None else sys.argv[1:]
    args = parse_args(raw_argv)

    # F-004：旧名 --force-with-blockers 命中 → stderr deprecation 提示（不阻断）
    if any(a == "--force-with-blockers" or a.startswith("--force-with-blockers=") for a in raw_argv):
        print(
            "[DEPRECATED] use --bypass-review-blockers instead, removed at 2026-11-01",
            file=sys.stderr,
        )

    # F-018：pre-tool-use 高频路径冷启动优化
    validate_only_ids: Optional[set[str]] = None
    if args.trigger == "pre-tool-use":
        validate_only_ids = {"GATE-PROTECT-BRANCH", "GATE-BASH-WRITE-PROTECT"}

    try:
        registry_data = load_registry(validate_only_ids=validate_only_ids)
    except RegistryError as exc:
        print(f"ERROR registry 加载失败：{exc}", file=sys.stderr)
        return 2

    if args.validate_registry:
        gate_count = len(registry_data.get("gates", []))
        print(f"OK registry 校验通过，共 {gate_count} 条 gate")
        return 0

    if not args.trigger:
        print("ERROR 必须指定 --trigger 或 --validate-registry", file=sys.stderr)
        return 2

    # F-004 round-3：reason 校验抽到 _validate_force_reason，失败归 return 2（CLI 入参非法）
    force_reason = getattr(args, "force_with_blockers", None)
    reason_err = _validate_force_reason(force_reason)
    if reason_err:
        print(f"ERROR {reason_err}", file=sys.stderr)
        return 2

    # canonical phase 校验：拒绝 --from / --to 写错的 phase 名（如 'technical-research'），
    # 避免下游 review-verdict / meta-schema 链路的 vacuous pass。
    phase_err = _validate_phase_args(args)
    if phase_err:
        print(f"ERROR {phase_err}", file=sys.stderr)
        return 2

    ctx = build_context(args)
    candidates = filter_gates(registry_data, ctx)
    plan = topological_sort(candidates)

    if args.dry_run:
        return _print_dry_run(ctx, plan)

    # 真实执行（registry_data 透传给 _execute_plan → _handle_escape_hatch，
    # 用于 escape_hatches[*].skips_gates_with_tag 与失败 gate.tags 做交集判定）
    return _execute_plan(ctx, plan, args.strict, registry_data=registry_data)


def _print_dry_run(ctx: GateContext, plan: list[dict[str, Any]]) -> int:
    """dry-run 模式：打印执行计划摘要后直接返回，不执行任何 gate。

    参数：
      ctx  — 当前执行上下文（trigger / requirement_id 用于日志输出）。
      plan — 拓扑排序后的候选 gate 列表（过滤 + 排序后结果）。

    作用：
      按序逐行打印每个 gate 的 id / plugin / severity，便于人工确认
      执行计划是否符合预期（可在跑真实 gate 前用 --dry-run 检查注册情况）。

    返回值：始终返回 0（dry-run 不判断 gate 结果，不影响退出码）。
    """
    print(f"[dry-run] trigger={ctx.trigger} req={ctx.requirement_id} 候选 gate 数={len(plan)}")
    for entry in plan:
        print(f"  - {entry['id']} (plugin={entry['plugin']}, severity={entry['severity']})")
    return 0


# ====================== 执行 plan（F-011 round-2 拆分） ======================


def _resolve_failed_gate_tags(
    gate_fail: "GateFailed",
    registry_data: Optional[dict[str, Any]],
) -> set[str]:
    """从 registry_data 取出失败 gate 的 tags 集合（缺失时返回空集）。

    F-004：用于 _handle_escape_hatch 的 tag 交集判定；registry_data=None 时
    返回空集 → 必然不命中 → escape hatch 不放行（safe default）。
    """
    if not registry_data:
        return set()
    failed_id = gate_fail.report.gate_id
    for entry in registry_data.get("gates", []):
        if entry.get("id") == failed_id:
            return set(entry.get("tags") or [])
    return set()


def _resolve_escape_skips_tags(
    escape_id: str,
    registry_data: Optional[dict[str, Any]],
) -> set[str]:
    """从 registry_data 取出 escape_hatch 的 skips_gates_with_tag 集合。

    F-004：与 _resolve_failed_gate_tags 对称；registry_data=None 时返回空集。
    """
    if not registry_data:
        return set()
    for entry in registry_data.get("escape_hatches", []) or []:
        if entry.get("id") == escape_id:
            return set(entry.get("skips_gates_with_tag") or [])
    return set()


def _handle_escape_hatch(
    ctx: GateContext,
    gate_fail: "GateFailed",
    executed: "list[Gate]",
    snapshots: dict,
    *,
    registry_data: Optional[dict[str, Any]] = None,
) -> tuple[bool, bool]:
    """处理 GateFailed 时的 force-with-blockers 分支判定（F-004 升级：tag 限定）。

    force-with-blockers 是流程级 escape_hatch，仅 phase-transition / submit trigger 生效
    （与 registry.yaml escape_hatches.triggers 对齐）。

    F-004 收紧：原实现命中后无脑放行任何 error fail（F6 缺陷），改为：
      - 必须命中：trigger ∈ {phase-transition, submit} ∧ force_reason 非空
      - 必须命中：失败 gate.tags ∩ escape.skips_gates_with_tag ≠ ∅
      不命中 → 走 _handle_gate_failed rollback 路径

    registry_data 缺省 None 时（旧调用站 / 测试场景），tag 集合视为空 → 不命中 →
    走 rollback 路径，与 F-004 设计语义一致（safe default）。

    参数：
      ctx           — 当前执行上下文（含 cli_flags.force_with_blockers）。
      gate_fail     — 触发失败的 GateFailed 异常（含 report.gate_id 用于日志）。
      executed      — 已执行的 Gate 列表（非命中路径执行 rollback 用）。
      snapshots     — 事务快照（非命中时传给 _handle_gate_failed 执行 rollback）。
      registry_data — registry.yaml 加载后的 dict，用于查 tags / skips_gates_with_tag。

    返回：(force_used, rollback_failed)
    """
    force_reason = ctx.cli_flags.get("force_with_blockers")
    if not (force_reason and ctx.trigger in ("phase-transition", "submit")):
        rollback_failed = _handle_gate_failed(ctx, executed, snapshots)
        return False, rollback_failed

    # F-004：失败 gate 必须有 tag 命中 escape_hatch.skips_gates_with_tag 才放行
    failed_tags = _resolve_failed_gate_tags(gate_fail, registry_data)
    skips_tags = _resolve_escape_skips_tags("force-with-blockers", registry_data)
    if not (failed_tags & skips_tags):
        # 无 tag 交集（含 registry_data=None 的 safe default）→ 不放行
        print(
            f"INFO ESCAPE-HATCH force-with-blockers 未命中："
            f"gate_id={gate_fail.report.gate_id} "
            f"failed_tags={sorted(failed_tags)} "
            f"skips_tags={sorted(skips_tags)}；走正常 rollback 路径",
            file=sys.stderr,
        )
        rollback_failed = _handle_gate_failed(ctx, executed, snapshots)
        return False, rollback_failed

    # tag 命中：放行
    print(
        f"WARNING ESCAPE-HATCH force-with-blockers 触发："
        f"gate_id={gate_fail.report.gate_id} "
        f"trigger={ctx.trigger} req={ctx.requirement_id or '-'} "
        f"matched_tags={sorted(failed_tags & skips_tags)} "
        f"reason={force_reason!r}",
        file=sys.stderr,
    )
    # G-3 round-3：force 路径也要清理快照和暂存写态，
    # 避免 .bak 文件残留 + ctx 跨调用复用时 staged_writes 幻态
    _cleanup_snapshots(snapshots)
    ctx.staged_writes.clear()
    return True, False


def _build_audit_extra(force_used: bool, force_reason: str) -> dict[str, Any]:
    """拼装 escape_hatch 命中时的 audit 附加字段。

    force_reason 在写入前经过：
      1. 长度截断（max_len=1024 字符）
      2. 控制字符过滤（unicodedata.category 以 'C' 开头的类，\t 和 \n 例外）

    参数：
      force_used   — True 时才生成非空 dict。
      force_reason — --force-with-blockers 传入的原始 reason 文本。

    返回：含 escape_used / escape_reason 的 dict；force_used=False 时返回空 dict。
    """
    if not force_used:
        return {}
    # 长度截断（F-4 spec：max_len=1024）
    reason = force_reason[:1024]
    # 控制字符过滤（F-4 spec：排除 unicodedata.category 以 'C' 开头，保留 \t / \n）
    reason = "".join(
        ch for ch in reason
        if ch in ("\t", "\n") or not unicodedata.category(ch).startswith("C")
    )
    return {
        "escape_used": "force-with-blockers",
        "escape_reason": reason,
    }


def _init_snapshots(ctx: GateContext, plan: list[dict[str, Any]]) -> dict:
    """按需做 stash_state，返回 snapshots dict（F-004 round-3 从 _execute_plan 抽出）。

    仅 plan 中含 side_effects=write_state 的 gate 时才调 _stash_state；否则返回 {}。
    stash 失败时降级为 {}（打 ERROR + 继续执行），保证 plugin 仍能运行。

    参数：
      ctx  — 当前执行上下文（trigger / requirement_id 用于日志）。
      plan — 拓扑排序后候选 gate 列表。

    返回：snapshots dict（_stash_state 返回值）；无需 stash 或 stash 失败时为 {}。
    """
    needs_stash = any(e.get("side_effects") == "write_state" for e in plan)
    if not needs_stash:
        return {}
    # F-020 round-3：stash_state 单独包裹，PermissionError/磁盘满/路径异常时降级 {}
    try:
        return _stash_state(ctx)
    except Exception as stash_exc:  # noqa: BLE001
        print(
            f"ERROR stash_state 失败 req={ctx.requirement_id or '-'} "
            f"trigger={ctx.trigger}: {stash_exc}；跳过事务化保护继续执行",
            file=sys.stderr,
        )
        return {}


def _finalize_audit(
    ctx: GateContext,
    reports: list[Report],
    rollback_failed: bool,
    force_used: bool,
    force_reason: str,
    plan: list[dict[str, Any]] | None = None,
    strict: bool = False,
) -> None:
    """构建并落盘 audit log；失败时仅打 ERROR，不阻断 gate 结果（F-004 round-3 从 _execute_plan 抽出）。

    F-004 round-5（Codex P3 修复，先本体后调用规则）：
      新增 plan + strict 参数（default None/False 保持 backward compat），传给
      _build_audit 让 audit.exit_code 与 runner 实际退出码一致。call site 在下一
      commit 升级；本 commit 仅函数定义改，old 5-arg 调用仍可工作（plan=None 时
      audit 走老的"any fail = 1"行为，等同重构前）。

    F-019 round-3：write_audit 单独包裹 try/except，避免 audit 落盘故障（磁盘满/无写权限）
    冒泡为 exit 2 阻断 Claude；audit 是基础设施级失败，绝不能升级为 gate 全崩。

    参数：
      ctx           — 当前执行上下文。
      reports       — 本次执行所有 gate 的 Report 列表。
      rollback_failed — fail 路径中 rollback 是否出现异常。
      force_used    — escape_hatch 是否命中。
      force_reason  — --force-with-blockers 传入的原始 reason 文本。
    """
    audit_extra = _build_audit_extra(force_used, force_reason)
    try:
        audit_data = _build_audit(ctx, reports, rollback_failed, plan=plan, strict=strict)
        if audit_extra:
            audit_data.update(audit_extra)
        write_audit(audit_data)
    except Exception as audit_exc:  # noqa: BLE001
        print(
            f"ERROR audit 落盘失败 req={ctx.requirement_id or '-'} "
            f"trigger={ctx.trigger}: {audit_exc}；跳过 audit 不阻断 gate 结果",
            file=sys.stderr,
        )


def _execute_plan(
    ctx: GateContext,
    plan: list[dict[str, Any]],
    strict: bool,
    *,
    registry_data: Optional[dict[str, Any]] = None,
) -> int:
    """执行 plan：init_snapshots → run/commit → escape_hatch → finalize_audit → exit_code。

    H1 事务化（F-002 round-2 修复）：
      commit_staged_writes 抛异常时统一走 GateFailed 路径——回滚已 commit 的 plugin、
      恢复 meta.yaml 磁盘快照、清空 staged_writes，避免 partial-commit 持久化。

    F-011 round-2：把"跑 gate / commit 写态 / GateFailed 处理"三段抽到子例程。
    F-007 round-2：拆出 _handle_escape_hatch + _build_audit_extra 降低复杂度。
    F-004 round-3：抽 _init_snapshots + _finalize_audit，函数降至 ≤ 50 行 / CC ≤ 10。
    F-004（FG-004）：透传 registry_data 给 _handle_escape_hatch，做 tag 交集判定。
      registry_data=None 时（旧调用站）→ tag 集合空集 → escape hatch 不命中 → safe default。
    """
    snapshots = _init_snapshots(ctx, plan)
    executed: list[Gate] = []
    reports: list[Report] = []
    rollback_failed = False
    force_used = False
    _current_plugin: list[str] = ["<unknown>"]

    try:
        _run_gates(ctx, plan, executed, reports, _current_plugin)
        _commit_write_state(ctx, executed, _current_plugin)
        _cleanup_snapshots(snapshots)
    except GateFailed as gate_fail:
        force_used, rollback_failed = _handle_escape_hatch(
            ctx, gate_fail, executed, snapshots, registry_data=registry_data
        )
    except Exception as exc:  # noqa: BLE001
        return _handle_runner_exception(ctx, snapshots, reports, _current_plugin[0], exc)

    force_reason = ctx.cli_flags.get("force_with_blockers", "")
    _finalize_audit(ctx, reports, rollback_failed, force_used, force_reason, plan=plan, strict=strict)

    # force-with-blockers 命中时允许 blocker fail 不影响 exit code（视为全通）
    if force_used:
        return 0
    return _calc_exit_code(reports, plan, strict)


def _run_gates(
    ctx: GateContext,
    plan: list[dict[str, Any]],
    executed: list[Gate],
    reports: list[Report],
    current_plugin: list[str],
) -> None:
    """跑每个 gate 的 precheck + run；任一 error 级 FAIL 抛 GateFailed（F-011 round-2 抽出）。"""
    for entry in plan:
        current_plugin[0] = entry.get("plugin", "<unknown>")
        gate = instantiate(entry)
        _log_gate_start(ctx, gate.id)
        skip = gate.precheck(ctx)
        if skip:
            reports.append(Report(gate.id, Decision.SKIP, message=skip.reason))
            continue
        executed.append(gate)
        r = gate.run(ctx)
        reports.append(r)
        sev = Severity(entry["severity"])
        if r.decision == Decision.FAIL and sev == Severity.ERROR:
            raise GateFailed(r)


def _commit_write_state(ctx: GateContext, executed: list[Gate], current_plugin: list[str]) -> None:
    """全 pass 后 commit 各 write_state plugin；任一异常转 GateFailed（F-011 round-2 抽出）。"""
    for g in executed:
        if getattr(g, "side_effects", "none") != "write_state":
            continue
        current_plugin[0] = g.id
        try:
            g.commit_staged_writes(ctx)
        except Exception as commit_exc:  # noqa: BLE001
            print(
                f"ERROR gate-commit-failed plugin={g.id} "
                f"trigger={ctx.trigger} req={ctx.requirement_id or '-'}: {commit_exc}",
                file=sys.stderr,
            )
            raise GateFailed(
                Report(
                    gate_id=g.id,
                    decision=Decision.FAIL,
                    code="GATE-COMMIT-FAILED",
                    message=f"commit_staged_writes 抛异常: {commit_exc}",
                    fix_hint="检查 meta.yaml 写权限、磁盘空间、并发锁竞争；可重试该 trigger",
                )
            ) from commit_exc


def _handle_gate_failed(ctx: GateContext, executed: list[Gate], snapshots: dict[str, Path]) -> bool:
    """GateFailed 路径：逆序 rollback + 恢复磁盘快照 + 清空 staged_writes（F-011 round-2 抽出）。

    返回：rollback_failed 标志（用于 audit log）。
    """
    rollback_failed = False
    for g in reversed(executed):
        try:
            g.rollback(ctx)
        except Exception as ex:  # noqa: BLE001
            rollback_failed = True
            print(f"ERROR gate-rollback-failed: {g.id}: {ex}", file=sys.stderr)
    _restore_state(ctx, snapshots)
    ctx.staged_writes.clear()
    return rollback_failed


def _handle_runner_exception(
    ctx: GateContext,
    snapshots: dict[str, Path],
    reports: list[Report],
    plugin_name: str,
    exc: Exception,
) -> int:
    """plugin 抛未捕获异常：恢复磁盘 + 写 audit 后返 2（F-011/F-033 round-2）。"""
    print(
        f"ERROR plugin 执行异常 plugin={plugin_name} "
        f"trigger={ctx.trigger} req={ctx.requirement_id or '-'}: {exc}",
        file=sys.stderr,
    )
    if not os.environ.get("CI"):
        traceback.print_exc(file=sys.stderr)
    _restore_state(ctx, snapshots)
    ctx.staged_writes.clear()
    # F-033：异常路径补 audit log，含 RUNNER-PLUGIN-EXCEPTION 占位条目，避免审计黑洞
    try:
        err_report = Report(
            gate_id=plugin_name,
            decision=Decision.FAIL,
            code="RUNNER-PLUGIN-EXCEPTION",
            message=f"plugin 抛未捕获异常: {exc}",
        )
        write_audit(_build_audit(ctx, reports + [err_report], rollback_failed=False))
    except Exception as audit_exc:  # noqa: BLE001
        print(f"ERROR audit log 异常路径写入失败: {audit_exc}", file=sys.stderr)
    return 2


def _log_gate_start(ctx: GateContext, gate_id: str) -> None:
    """关键业务节点日志：含 gate_id / trigger / requirement_id（无敏感信息）。"""
    print(
        f"INFO gate.start gate_id={gate_id} trigger={ctx.trigger} "
        f"requirement_id={ctx.requirement_id or '-'}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
