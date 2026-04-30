"""code-review-routing 核心引擎。

功能（F-001 核心层，无 IO / tty / main）：
  - 异常体系与退出码常量
  - 数据模型（frozen dataclass）
  - yaml 加载与 schema 校验（V1-V7）
  - pathspec 三段匹配与 RoutingPlan 构造

F-002 负责：main / _parse_args / _check_tty / _prompt_user
           _write_scope / _audit_log / _resolve_confirmed_by
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pathspec
import yaml

# ---------------------------------------------------------------------------
# 模块常量
# ---------------------------------------------------------------------------

# 8 个 checker 全集（固定顺序，tuple 防止意外修改）
ALL_CHECKERS: tuple[str, ...] = (
    "complexity-checker",
    "security-checker",
    "concurrency-checker",
    "performance-checker",
    "error-handling-checker",
    "design-consistency-checker",
    "history-context-checker",
    "auxiliary-spec-checker",
)

ROUTING_YAML_PATH = Path(".claude/code-review-routing.yaml")
SCOPE_JSON_PATH = Path(".review-scope.json")
MAX_INVALID_PROMPTS = 3
MAX_MUST_RULES = 5

# 退出码（F-002 main() 实际使用，这里定义让 F-002 直接 import）
EXIT_OK = 0
EXIT_BAD_ARGS = 1
EXIT_NON_TTY = 2
EXIT_SCHEMA_INVALID = 3
EXIT_YAML_LOAD_ERROR = 4
EXIT_USER_ABORT = 5

# 用户提示模板（F-002 可直接 import 复用）
_ERROR_MESSAGES: dict[int, str] = {
    1: (
        "[routing] 入参非法：{detail}\n"
        "  fix-hint：检查 --mode / --requirement-id / --base-sha / --head-sha / "
        "--base-branch / --current-branch 必填项；sha 格式应为 7 位短 hash；"
        "requirement-id 格式应为 REQ-YYYY-NNN。"
    ),
    2: (
        "[routing] 卡点 A 必须人工执行：检测到 stdin 非 tty"
        "（AI / 管道 / heredoc 调用被拒绝）。\n"
        "  fix-hint：在交互式终端手动运行 /code-review；CI 场景请直接跳过本步。"
    ),
    3: (
        "[routing] routing.yaml schema 校验失败：{detail}\n"
        "  fix-hint：参考 .claude/code-review-routing.yaml 的现有结构；"
        "must 段最多 5 条；checkers 元素必须 ∈ 8-checker 全集。"
    ),
    4: (
        "[routing] routing.yaml 加载失败：{file}:{line} {detail}\n"
        "  fix-hint：确认文件存在、yaml 语法正确、UTF-8 编码；"
        "可用 yamllint 离线校验。"
    ),
    5: "[routing] 本次审查已取消（{cause}）。",
}

# ---------------------------------------------------------------------------
# 异常体系
# ---------------------------------------------------------------------------


class RoutingError(Exception):
    """路由引擎基础异常；exit_code 供 main() 作为进程退出码使用。"""

    def __init__(self, detail: str, exit_code: int = EXIT_BAD_ARGS) -> None:
        super().__init__(detail)
        self.detail = detail
        self.exit_code = exit_code

    def __str__(self) -> str:
        return self.detail


class RoutingYamlError(RoutingError):
    """yaml 文件缺失 / 编码错误 / 语法错误。exit_code=4。"""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, exit_code=EXIT_YAML_LOAD_ERROR)


class RoutingSchemaError(RoutingError):
    """yaml schema 校验失败（V1-V7）。exit_code=3。"""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, exit_code=EXIT_SCHEMA_INVALID)


class RoutingTTYError(RoutingError):
    """非 tty 环境拒绝运行。exit_code=2。"""

    def __init__(self, detail: str = _ERROR_MESSAGES[EXIT_NON_TTY]) -> None:
        super().__init__(detail, exit_code=EXIT_NON_TTY)


class RoutingAbort(RoutingError):
    """用户主动取消。exit_code=5。"""

    def __init__(self, detail: str = _ERROR_MESSAGES[EXIT_USER_ABORT]) -> None:
        super().__init__(detail, exit_code=EXIT_USER_ABORT)


# ---------------------------------------------------------------------------
# 数据模型（全部 frozen=True，保证不可变）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RuleEntry:
    """routing.yaml 中单条规则（pattern + checkers）。"""

    pattern: str
    checkers: tuple[str, ...]


@dataclass(frozen=True)
class RoutingConfig:
    """从 routing.yaml 解析并校验后的配置对象。"""

    version: int
    must: tuple[_RuleEntry, ...]
    suggest: tuple[_RuleEntry, ...]
    trivial_whitelist: tuple[str, ...]


@dataclass(frozen=True)
class MatchResult:
    """单个文件的路由匹配结果。"""

    path: str
    matched_must: list[str] = field(default_factory=list)
    matched_suggest: list[str] = field(default_factory=list)
    matched_trivial: bool = False


@dataclass(frozen=True)
class RoutingPlan:
    """所有文件的聚合路由计划。"""

    must_checkers: set[str]
    suggest_checkers: set[str]
    trivial_only: bool
    files_total: int
    files_trivial: int
    # checker → 命中该 checker 的文件路径列表
    files_must_hit: dict[str, list[str]]
    files_suggest_hit: dict[str, list[str]]


@dataclass(frozen=True)
class RoutingDecision:
    """人类卡点 A 确认结果（F-002 构造，F-001 仅定义类型）。"""

    decision: Literal["accept", "all", "custom", "abort", "trivial-skipped"]
    confirmed_at: str
    confirmed_by: str
    tty_verified: bool
    final_route: list[str]


# ---------------------------------------------------------------------------
# 无 IO 纯计算函数
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    """从磁盘加载 routing.yaml，返回原始 dict。

    文件缺失 / 编码错误 / yaml 语法错 → RoutingYamlError(4)。
    语法错时 detail 含 "file:line detail" 格式定位信息。
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except FileNotFoundError:
        raise RoutingYamlError(f"routing.yaml 不存在: {path}")
    except UnicodeDecodeError as exc:
        raise RoutingYamlError(f"routing.yaml 编码错误: {exc}")
    except yaml.YAMLError as exc:
        # 尽量带行号，方便定位
        if hasattr(exc, "problem_mark") and exc.problem_mark is not None:
            line = exc.problem_mark.line
            raise RoutingYamlError(
                f"{path}:{line} yaml 语法错误: {exc.problem}"
            )
        raise RoutingYamlError(f"routing.yaml yaml 语法错误: {exc}")

    if raw is None:
        # 空文件 safe_load 返回 None，视为 schema 缺字段（由 _validate_schema 报 V1）
        return {}
    return raw


def _validate_rule_entry(rule: object, section: str, idx: int) -> _RuleEntry:
    """校验单条规则 dict，违反 V4/V5 → RoutingSchemaError。

    校验项：
      - rule 必须是 dict（V4）
      - 含 pattern（非空 str）与 checkers（list[str]）字段（V4）
      - checkers 元素 ∈ ALL_CHECKERS（V5）
      - pattern 可被 pathspec 解析（V4，提前校验）
    """
    if not isinstance(rule, dict):
        raise RoutingSchemaError(
            f"V4: {section}[{idx}] 必须是 dict，实际为 {type(rule).__name__}"
        )
    if "pattern" not in rule or "checkers" not in rule:
        raise RoutingSchemaError(
            f"V4: {section}[{idx}] 缺少 pattern 或 checkers 字段"
        )
    pattern = rule["pattern"]
    checkers = rule["checkers"]
    if not isinstance(pattern, str) or not pattern.strip():
        raise RoutingSchemaError(
            f"V4: {section}[{idx}].pattern 必须是非空字符串，实际为 {pattern!r}"
        )
    if not isinstance(checkers, list):
        raise RoutingSchemaError(
            f"V4: {section}[{idx}].checkers 必须是列表"
        )
    # V5：checkers 元素 ∈ ALL_CHECKERS
    for c in checkers:
        if not isinstance(c, str):
            raise RoutingSchemaError(
                f"V5: {section}[{idx}].checkers 元素必须是字符串，实际为 {c!r}"
            )
        if c not in ALL_CHECKERS:
            raise RoutingSchemaError(
                f"V5: {section}[{idx}].checkers 含未知 checker {c!r}"
            )
    try:
        pathspec.PathSpec.from_lines("gitignore", [pattern])
    except Exception as exc:
        raise RoutingSchemaError(
            f"V4: {section}[{idx}].pattern {pattern!r} 无法被 pathspec 解析: {exc}"
        )
    return _RuleEntry(pattern=pattern, checkers=tuple(checkers))


def _validate_schema(raw: dict) -> RoutingConfig:
    """校验 routing.yaml 原始 dict，返回 RoutingConfig。

    任意校验项（V1-V7）失败 → RoutingSchemaError(3)，detail 含违反编号。
    """
    # V1：顶层必含 version / must / suggest / trivial_whitelist
    required_keys = {"version", "must", "suggest", "trivial_whitelist"}
    missing = required_keys - set(raw.keys())
    if missing:
        raise RoutingSchemaError(f"V1: 缺少必填字段 {sorted(missing)}")

    # V2：version == 1
    if raw["version"] != 1:
        raise RoutingSchemaError(f"V2: version 必须为 1，实际为 {raw['version']!r}")

    # V3：must 必须是长度 ≤ MAX_MUST_RULES 的 list
    must_raw = raw["must"]
    if not isinstance(must_raw, list):
        raise RoutingSchemaError("V3: must 必须是列表")
    if len(must_raw) > MAX_MUST_RULES:
        raise RoutingSchemaError(
            f"V3: must 规则数 {len(must_raw)} 超过上限 {MAX_MUST_RULES}"
        )

    # V3b：suggest 必须是 list
    suggest_raw = raw["suggest"]
    if not isinstance(suggest_raw, list):
        raise RoutingSchemaError("V3b: suggest 必须是列表")

    # V4：must/suggest 每项 pattern(str, 非空) + checkers(list[str] ∈ ALL_CHECKERS)
    must_entries = [_validate_rule_entry(r, "must", i) for i, r in enumerate(must_raw)]
    suggest_entries = [_validate_rule_entry(r, "suggest", i) for i, r in enumerate(suggest_raw)]

    # V6：trivial_whitelist 每项是非空 str
    trivial_raw = raw["trivial_whitelist"]
    if not isinstance(trivial_raw, list):
        raise RoutingSchemaError("V6: trivial_whitelist 必须是列表")
    trivial_list: list[str] = []
    for idx, item in enumerate(trivial_raw):
        if not isinstance(item, str) or not item.strip():
            raise RoutingSchemaError(
                f"V6: trivial_whitelist[{idx}] 必须是非空字符串，实际为 {item!r}"
            )
        trivial_list.append(item)

    # V7：trivial_whitelist 所有 pattern 可被 pathspec 解析
    # 注：must/suggest 的 pattern 已在 _validate_rule_entry 中通过 V4 校验
    for pat in trivial_list:
        try:
            pathspec.PathSpec.from_lines("gitignore", [pat])
        except Exception as exc:
            raise RoutingSchemaError(f"V7: pattern {pat!r} 无法被 pathspec 解析: {exc}")

    return RoutingConfig(
        version=raw["version"],
        must=tuple(must_entries),
        suggest=tuple(suggest_entries),
        trivial_whitelist=tuple(trivial_list),
    )


def _parse_rule_list(rules: list, section: str) -> list[_RuleEntry]:
    """解析 must 或 suggest 规则列表，违反 V4/V5 → RoutingSchemaError。

    已被 _validate_rule_entry 取代，保留以维持向后兼容（外部可能 import）。
    """
    return [_validate_rule_entry(r, section, i) for i, r in enumerate(rules)]


def _enumerate_diff_files(base_sha: str, head_sha: str) -> list[str]:
    """通过 git diff --name-only 枚举两个 commit 之间变更的文件列表。

    git 执行失败 → RoutingError(EXIT_BAD_ARGS)。
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_sha}..{head_sha}"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        # exc.stderr 在某些场景（如 mock）可能为 None，需防御
        stderr_msg = (exc.stderr or "").strip()
        raise RoutingError(
            f"git diff 执行失败（{base_sha}..{head_sha}）: {stderr_msg}",
            exit_code=EXIT_BAD_ARGS,
        )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return lines


def _compile_specs(
    config: RoutingConfig,
) -> tuple[
    list[tuple[pathspec.PathSpec, tuple[str, ...]]],
    list[tuple[pathspec.PathSpec, tuple[str, ...]]],
    pathspec.PathSpec,
]:
    """预编译 RoutingConfig 中的所有 pathspec，避免对每个文件重复编译。

    返回：
      must_specs    — [(compiled_spec, checkers), ...]，对应 config.must
      suggest_specs — [(compiled_spec, checkers), ...]，对应 config.suggest
      trivial_spec  — 将 trivial_whitelist 合并为单个 PathSpec
    """
    must_specs = [
        (pathspec.PathSpec.from_lines("gitignore", [rule.pattern]), rule.checkers)
        for rule in config.must
    ]
    suggest_specs = [
        (pathspec.PathSpec.from_lines("gitignore", [rule.pattern]), rule.checkers)
        for rule in config.suggest
    ]
    trivial_spec = pathspec.PathSpec.from_lines(
        "gitignore", list(config.trivial_whitelist)
    )
    return must_specs, suggest_specs, trivial_spec


def _match_file(
    path: str,
    must_specs: list[tuple[pathspec.PathSpec, tuple[str, ...]]],
    suggest_specs: list[tuple[pathspec.PathSpec, tuple[str, ...]]],
    trivial_spec: pathspec.PathSpec,
) -> tuple[set[str], dict[str, list[str]], set[str], dict[str, list[str]], bool]:
    """对单个文件执行三段 pathspec 匹配，返回该文件的命中结果。

    返回：
      file_must_checkers   — 该文件命中的 must checker 集合
      file_must_hit        — {checker: [path]} 映射（仅命中时填充）
      file_suggest_checkers — 该文件命中的 suggest checker 集合
      file_suggest_hit     — {checker: [path]} 映射（仅命中时填充）
      hit_trivial          — 是否命中 trivial（must+suggest 均未命中时才判断）
    """
    file_must_checkers: set[str] = set()
    file_must_hit: dict[str, list[str]] = {}
    file_suggest_checkers: set[str] = set()
    file_suggest_hit: dict[str, list[str]] = {}

    # 第一段：must 匹配
    for spec, checkers in must_specs:
        if spec.match_file(path):
            for c in checkers:
                file_must_checkers.add(c)
                file_must_hit.setdefault(c, []).append(path)

    # 第二段：suggest 匹配（独立，不受 must 影响）
    for spec, checkers in suggest_specs:
        if spec.match_file(path):
            for c in checkers:
                file_suggest_checkers.add(c)
                file_suggest_hit.setdefault(c, []).append(path)

    # 第三段：trivial —— 仅当 must 和 suggest 都未命中时才计入
    hit_trivial = (
        not file_must_checkers
        and not file_suggest_checkers
        and trivial_spec.match_file(path)
    )
    return file_must_checkers, file_must_hit, file_suggest_checkers, file_suggest_hit, hit_trivial


def _assert_plan_invariants(plan: RoutingPlan) -> None:
    """校验 RoutingPlan 的 INV-PLAN-1..4 不变量，违反说明实现有 bug。"""
    # INV-PLAN-1: files_must_hit 的 key 集合必须等于 must_checkers
    assert set(plan.files_must_hit.keys()) == plan.must_checkers, (
        f"INV-PLAN-1 violated: files_must_hit.keys()={set(plan.files_must_hit.keys())} "
        f"!= must_checkers={plan.must_checkers}"
    )
    # INV-PLAN-2: files_suggest_hit 的 key 集合必须等于 suggest_checkers
    assert set(plan.files_suggest_hit.keys()) == plan.suggest_checkers, (
        f"INV-PLAN-2 violated: files_suggest_hit.keys()={set(plan.files_suggest_hit.keys())} "
        f"!= suggest_checkers={plan.suggest_checkers}"
    )
    # INV-PLAN-3: must_checkers ∪ suggest_checkers ⊆ ALL_CHECKERS
    assert plan.must_checkers <= set(ALL_CHECKERS) and plan.suggest_checkers <= set(ALL_CHECKERS), (
        "INV-PLAN-3 violated: checkers 超出 ALL_CHECKERS 范围"
    )
    # INV-PLAN-4: trivial_only=True ⇒ must/suggest 全空 ∧ files_trivial == files_total > 0
    if plan.trivial_only:
        assert (
            len(plan.must_checkers) == 0
            and len(plan.suggest_checkers) == 0
            and plan.files_trivial == plan.files_total
            and plan.files_total > 0
        ), "INV-PLAN-4 violated"


def _build_plan(files: list[str], config: RoutingConfig) -> RoutingPlan:
    """对文件列表执行三段 pathspec 匹配，构造 RoutingPlan。

    三段匹配优先级：
      1. must   — 命中 → 并入 must_checkers
      2. suggest — 无论 must 是否命中，独立匹配并入 suggest_checkers
      3. trivial — 仅当 must + suggest 都未命中时计入 files_trivial

    出口前强制校验 INV-PLAN-1..4（assert），违反说明实现有 bug。
    """
    must_specs, suggest_specs, trivial_spec = _compile_specs(config)

    must_checkers: set[str] = set()
    suggest_checkers: set[str] = set()
    files_must_hit: dict[str, list[str]] = {}
    files_suggest_hit: dict[str, list[str]] = {}
    files_trivial = 0

    for path in files:
        fm_c, fm_h, fs_c, fs_h, hit_trivial = _match_file(
            path, must_specs, suggest_specs, trivial_spec
        )
        # 聚合 must 结果
        must_checkers.update(fm_c)
        for c, paths in fm_h.items():
            files_must_hit.setdefault(c, []).extend(paths)
        # 聚合 suggest 结果
        suggest_checkers.update(fs_c)
        for c, paths in fs_h.items():
            files_suggest_hit.setdefault(c, []).extend(paths)
        if hit_trivial:
            files_trivial += 1

    trivial_only = (
        len(must_checkers) == 0
        and len(suggest_checkers) == 0
        and files_trivial == len(files)
        and len(files) > 0
    )

    plan = RoutingPlan(
        must_checkers=must_checkers,
        suggest_checkers=suggest_checkers,
        trivial_only=trivial_only,
        files_total=len(files),
        files_trivial=files_trivial,
        files_must_hit=files_must_hit,
        files_suggest_hit=files_suggest_hit,
    )
    _assert_plan_invariants(plan)
    return plan


# ---------------------------------------------------------------------------
# 公开 API（F-002 import 时使用）
# ---------------------------------------------------------------------------

__all__ = [
    # 常量
    "ALL_CHECKERS",
    "ROUTING_YAML_PATH",
    "SCOPE_JSON_PATH",
    "MAX_INVALID_PROMPTS",
    "MAX_MUST_RULES",
    "EXIT_OK",
    "EXIT_BAD_ARGS",
    "EXIT_NON_TTY",
    "EXIT_SCHEMA_INVALID",
    "EXIT_YAML_LOAD_ERROR",
    "EXIT_USER_ABORT",
    "_ERROR_MESSAGES",
    # 异常
    "RoutingError",
    "RoutingYamlError",
    "RoutingSchemaError",
    "RoutingTTYError",
    "RoutingAbort",
    # 数据类
    "MatchResult",
    "RoutingPlan",
    "RoutingDecision",
    "RoutingConfig",
    # 核心函数
    "_load_yaml",
    "_validate_rule_entry",
    "_validate_schema",
    "_parse_rule_list",
    "_enumerate_diff_files",
    "_compile_specs",
    "_match_file",
    "_assert_plan_invariants",
    "_build_plan",
]
