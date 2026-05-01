"""code-review-routing 核心引擎。

功能（F-001 核心层，无 IO / tty / main）：
  - 异常体系与退出码常量
  - 数据模型（frozen dataclass）
  - yaml 加载与 schema 校验（V1-V7）
  - pathspec 三段匹配与 RoutingPlan 构造

F-002 IO 层（本文件追加）：
  main / _parse_args / _check_tty / _prompt_user
  _write_scope / _audit_log / _resolve_confirmed_by
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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

# H-10 fix: 合法 email 正则（比 "@" in email 更严格，防止 a@b 这类通过）
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

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
# F-002 IO 层：参数解析 / tty 校验 / 用户确认 / 写盘 / 审计
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """解析 CLI 参数并做白名单校验。

    严格校验 sha 格式（7-40 位 hex）和 requirement-id 格式（REQ-YYYY-NNN），
    是为了在入口层尽早拒绝明显错误的调用，而不是让 git diff 或 audit 写了一条垃圾记录。
    """
    parser = argparse.ArgumentParser(
        prog="code-review-routing",
        description="代码审查路由器：tty 卡点 A，产出 .review-scope.json",
    )
    parser.add_argument("--mode", required=True, help="embedded | standalone")
    parser.add_argument("--requirement-id", required=True, dest="requirement_id")
    parser.add_argument("--base-sha", required=True, dest="base_sha")
    parser.add_argument("--head-sha", required=True, dest="head_sha")
    parser.add_argument("--base-branch", required=True, dest="base_branch")
    parser.add_argument("--current-branch", required=True, dest="current_branch")
    parser.add_argument("--feature-id", required=False, dest="feature_id", default="")
    parser.add_argument(
        "--services",
        required=False,
        default="agentic-meta-engineering",
        help="逗号分隔的 service 列表",
    )

    ns = parser.parse_args(argv)

    # 白名单：mode 必须是枚举值
    if ns.mode not in ("embedded", "standalone"):
        raise RoutingError(
            f"--mode 必须是 embedded 或 standalone，实际为 {ns.mode!r}",
            exit_code=EXIT_BAD_ARGS,
        )

    # 白名单：sha 格式（7-40 位十六进制）
    sha_pattern = re.compile(r"^[0-9a-f]{7,40}$")
    for flag, sha in (("--base-sha", ns.base_sha), ("--head-sha", ns.head_sha)):
        if not sha_pattern.fullmatch(sha):
            raise RoutingError(
                f"{flag} sha 格式非法（期望 7-40 位十六进制），实际为 {sha!r}",
                exit_code=EXIT_BAD_ARGS,
            )

    # 白名单：requirement-id 格式（REQ-YYYY-NNN）
    if not re.fullmatch(r"^REQ-\d{4}-\d{3}$", ns.requirement_id):
        raise RoutingError(
            f"--requirement-id 格式非法（期望 REQ-YYYY-NNN），实际为 {ns.requirement_id!r}",
            exit_code=EXIT_BAD_ARGS,
        )

    return ns


def _check_tty() -> None:
    """确认当前进程的 stdin 是真实 tty，否则拒绝运行。

    tty 校验是核心安全门禁：防止 AI 管道、heredoc、CI 自动化绕过人工卡点 A。
    严禁通过任何 env var（FAKE_TTY 等）旁路——旁路会使 F-002 整体价值归零。
    """
    if not sys.stdin.isatty():
        raise RoutingTTYError()


def _resolve_confirmed_by() -> str:
    """读取 git config user.email 作为确认人身份标识。

    用 email 而非 name，因为 email 更具唯一性，便于后续 audit 追溯到具体责任人。
    """
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            check=True,
        )
        email = result.stdout.strip()
    except subprocess.CalledProcessError:
        email = ""

    # H-10 fix: 使用 EMAIL_RE 完整正则校验，防止 a@b 这类格式通过
    if not email or not EMAIL_RE.fullmatch(email):
        raise RoutingError(
            f"git config user.email 格式不合法"
            f"（需匹配 ^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$）：{email!r}。"
            "请先执行：git config user.email 'your@email.com'",
            exit_code=EXIT_BAD_ARGS,
        )
    return email


def _parse_custom_input(
    line: str,
    plan: RoutingPlan,
    recommended_indexed: list[str],
) -> set[str]:
    """解析用户输入的自定义子集（逗号分隔 1-based 索引）。

    独立抽出是为了让 U11/U12 单测可以直接覆盖容错逻辑，
    避免把 stdin 交互混入单测范围。

    返回：用户选择的 checker 名称集合（已强制包含 must_checkers），
    若输入无法解析为任何合法索引则返回空集（调用方据此计 invalid_count）。
    """
    parts = [p.strip() for p in line.split(",") if p.strip()]
    if not parts:
        return set()

    selected: set[str] = set()
    n = len(recommended_indexed)
    for part in parts:
        # 只接受纯数字
        if not part.isdigit():
            return set()
        idx = int(part) - 1  # 1-based → 0-based
        if idx < 0 or idx >= n:
            return set()
        selected.add(recommended_indexed[idx])

    # must 强制保留：即便用户未选，也要自动加回
    selected.update(plan.must_checkers)
    return selected


def _classify_input(
    line: str,
    plan: RoutingPlan,
    recommended_indexed: list[str],
) -> tuple[str, set[str] | None]:
    """对单次用户输入进行分类与解析（H-2 fix：从 _prompt_user 抽出以降低圈复杂度）。

    返回 (kind, payload)，kind 为以下之一：
      "accept"  — 直接回车（payload=None）
      "all"     — 输入 'a'/'A'（payload=None）
      "abort"   — 输入 'q'/'Q'（payload=None）
      "custom"  — 合法数字子集（payload=set[str]，已强制含 must_checkers）
      "invalid" — 其他无效输入（payload=None）
    """
    if line == "":
        return ("accept", None)
    if line.lower() == "a":
        return ("all", None)
    if line.lower() == "q":
        return ("abort", None)

    selected = _parse_custom_input(line, plan, recommended_indexed)
    if selected:
        return ("custom", selected)

    return ("invalid", None)


def _prompt_user(plan: RoutingPlan, req_id: str = "") -> RoutingDecision:
    """在 tty 展示路由计划，等待用户输入 4 档热键，返回 RoutingDecision。

    4 档热键：
      ""（直接回车）→ accept：接受推荐集（must ∪ suggest），按 ALL_CHECKERS 顺序
      "a" / "A"   → all：升全集 8 路
      "q" / "Q"   → audit 写 "用户主动取消 (q)" 后 raise RoutingAbort
      "1,3,5" 等  → custom：自定义子集，must 强制保留

    连续 3 次无效输入同样 audit 写 "连续 3 次无效输入" 后 raise RoutingAbort。
    req_id 用于写 audit；为空则跳过 audit（单测无仓库场景）。
    """
    # 推荐集 = sorted(must ∪ suggest)，按 ALL_CHECKERS 顺序
    recommended: list[str] = [
        c for c in ALL_CHECKERS
        if c in plan.must_checkers or c in plan.suggest_checkers
    ]

    # 灰色文件数 = total - trivial - 命中 must/suggest 的唯一文件数
    files_grey = max(
        0,
        plan.files_total - plan.files_trivial
        - len({f for paths in plan.files_must_hit.values() for f in paths})
        - len({f for paths in plan.files_suggest_hit.values() for f in paths}),
    )

    separator = "─" * 60
    print(separator)
    print("代码审查路由器·卡点 A")
    print(
        f"diff 共 {plan.files_total} 个文件"
        f"（trivial {plan.files_trivial}"
        f" / must {len(plan.must_checkers)}"
        f" / suggest {len(plan.suggest_checkers)}"
        f" / 灰色 {files_grey}）"
    )
    print("推荐 checker 集（标 [must] 不可去掉）：")
    for i, checker in enumerate(recommended, 1):
        tag = "[must]" if checker in plan.must_checkers else "[sug] "
        print(f"  {i}. {tag} {checker}")
    print(separator)
    print("回车=接受推荐  a=升全集 8 路  q=取消  数字逗号(如 1,3)=自定义子集")

    invalid_count = 0
    while True:
        try:
            raw = input("> ").strip()
        except EOFError:
            # stdin 被关闭，视为 abort
            raise RoutingAbort("[routing] stdin 关闭，视为 abort")

        kind, payload = _classify_input(raw, plan, recommended)

        if kind == "accept":
            return RoutingDecision(
                decision="accept",
                confirmed_at=_now_shanghai(),
                confirmed_by="",  # main() 层补充 confirmed_by
                tty_verified=True,
                final_route=recommended[:],
            )

        if kind == "all":
            return RoutingDecision(
                decision="all",
                confirmed_at=_now_shanghai(),
                confirmed_by="",
                tty_verified=True,
                final_route=list(ALL_CHECKERS),
            )

        if kind == "abort":
            # 用户主动取消：先 audit 再 raise
            if req_id:
                _audit_log(req_id, "[code-review-aborted] 用户主动取消 (q)")
            raise RoutingAbort(
                _ERROR_MESSAGES[EXIT_USER_ABORT].format(cause="用户主动取消 (q)")
            )

        if kind == "custom":
            assert payload is not None  # _classify_input 保证
            final_route = [c for c in ALL_CHECKERS if c in payload]
            return RoutingDecision(
                decision="custom",
                confirmed_at=_now_shanghai(),
                confirmed_by="",
                tty_verified=True,
                final_route=final_route,
            )

        # kind == "invalid"
        invalid_count += 1
        remaining = MAX_INVALID_PROMPTS - invalid_count
        if invalid_count >= MAX_INVALID_PROMPTS:
            # 连续 3 次无效：先 audit 再 raise
            if req_id:
                _audit_log(req_id, "[code-review-aborted] 连续 3 次无效输入")
            raise RoutingAbort(
                _ERROR_MESSAGES[EXIT_USER_ABORT].format(cause="连续 3 次无效输入")
            )
        print(
            f"[invalid] 不识别的输入。提示：直接回车=接受 / a=全集 / q=取消 / "
            f"数字逗号(如 1,3)=自定义子集（剩余 {remaining} 次机会）"
        )


def _now_shanghai() -> str:
    """返回当前 Asia/Shanghai 时间的 ISO8601 字符串（含 +08:00）。

    统一时区来源，避免不同机器时区配置导致 audit 时间不一致。
    """
    tz_shanghai = timezone(timedelta(hours=8))
    return datetime.now(tz=tz_shanghai).isoformat(timespec="seconds")


def _now_shanghai_display() -> str:
    """返回 YYYY-MM-DD HH:MM:SS 格式（写入 scope.json routing_decision.confirmed_at）。

    H-18 fix: scope.json 的 confirmed_at 用人类可读格式，与 audit 日志的 ISO8601 格式分离，
    是刻意设计——audit 日志面向机器排序，scope.json 面向人工审阅。
    """
    tz_shanghai = timezone(timedelta(hours=8))
    return datetime.now(tz=tz_shanghai).strftime("%Y-%m-%d %H:%M:%S")


def _audit_log(req_id: str, line: str) -> None:
    """追加一条 audit 记录到 requirements/<req_id>/process.txt。

    用 append 模式保证日志不会因原子写操作而截断历史，
    每条记录前缀 ISO8601 时间戳，方便按时间排序和 grep。
    """
    log_path = Path("requirements") / req_id / "process.txt"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = _now_shanghai()
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"{timestamp} {line}\n")
    except OSError as exc:
        # audit 写失败不应阻断主流程，但需要记录到 stderr 让用户知晓
        print(f"[routing] audit_log 写入失败（{exc}），继续执行", file=sys.stderr)


def _assert_scope_invariants(
    plan: RoutingPlan,
    decision: RoutingDecision,
    skipped_checkers: list[dict],
) -> None:
    """校验 _write_scope 写盘前的 I1-I8 不变量。

    H-9/H-11 fix：全部用 raise RoutingSchemaError 替代 assert，
    防止 AssertionError 穿透 main() 的 except RoutingError 捕获层。
    """
    is_trivial_skipped = decision.decision == "trivial-skipped"
    is_all = decision.decision == "all"
    is_custom = decision.decision == "custom"

    # I1: trivial-skipped ⇔ final_route=[] ∧ len(skipped_checkers)==8（H-9 fix：修复恒真断言）
    if is_trivial_skipped != (decision.final_route == [] and len(skipped_checkers) == 8):
        raise RoutingSchemaError(
            f"I1 violated: trivial_skipped={is_trivial_skipped} "
            f"but final_route={decision.final_route} skipped_count={len(skipped_checkers)}",
        )

    # I2: decision="all" ⇒ checker_route == list(ALL_CHECKERS)
    if is_all and decision.final_route != list(ALL_CHECKERS):
        raise RoutingSchemaError(
            f"I2 violated: decision=all 但 final_route={decision.final_route}",
        )

    # I3: decision="custom" → must_checkers ⊆ checker_route
    if is_custom and not plan.must_checkers.issubset(set(decision.final_route)):
        raise RoutingSchemaError(
            f"I3 violated: must_checkers={plan.must_checkers} not ⊆ final_route={decision.final_route}",
        )

    # I5: tty_verified is True
    if not decision.tty_verified:
        raise RoutingSchemaError("I5 violated: tty_verified 必须为 True")

    # I7: trivial-skipped ⇒ final_route==[] ∧ len(skipped_checkers)==8
    if is_trivial_skipped and not (decision.final_route == [] and len(skipped_checkers) == 8):
        raise RoutingSchemaError(
            f"I7 violated: trivial-skipped 但 final_route={decision.final_route} "
            f"skipped_count={len(skipped_checkers)}",
        )

    # I8: len(checker_route) + len(skipped_checkers) == 8
    total = len(decision.final_route) + len(skipped_checkers)
    if total != 8:
        raise RoutingSchemaError(
            f"I8 violated: len(final_route)={len(decision.final_route)} "
            f"+ len(skipped_checkers)={len(skipped_checkers)} = {total} ≠ 8",
        )


def _write_scope(
    plan: RoutingPlan,
    decision: RoutingDecision,
    args: argparse.Namespace,
) -> None:
    """原子写 .review-scope.json。

    使用 tempfile + os.replace 保证写盘原子性：
    不会出现外部进程读到半写状态的 JSON。
    写盘前调用 _assert_scope_invariants 校验 I1-I8，违反视为实现 bug（raise RoutingSchemaError）。
    """
    # ---- 构造 skipped_checkers ----
    all_checkers_set = set(ALL_CHECKERS)  # noqa: F841（保留供未来扩展参考）
    route_set = set(decision.final_route)
    is_trivial_skipped = decision.decision == "trivial-skipped"

    if decision.decision == "trivial-skipped":
        # H-5 fix: 字段名 checker → name（§3.1 schema / scope-schema.md L88）
        # H-6 fix: reason 使用 §3.3 三选一字面字符串
        skipped_checkers = [
            {"name": c, "reason": "diff 全在 trivial 白名单内（skipped=true 全 8 个）"}
            for c in ALL_CHECKERS
        ]
    else:
        # accept / all / custom：未在 final_route 中的 checker 被 skipped
        skipped_checkers = []
        for c in ALL_CHECKERS:
            if c not in route_set:
                # H-6 fix: reason 严格按 §3.3 三选一字面字符串，不允许自造
                if c not in plan.must_checkers and c not in plan.suggest_checkers:
                    # 灰色：该 checker 对应规则未命中 diff 中任何文件
                    reason = "路径未命中 must/suggest 任何规则"
                elif decision.decision == "custom" and c in plan.suggest_checkers:
                    # custom 路径：suggest 命中但用户未在自定义子集中选择
                    reason = "用户在 custom 子集中未选择"
                else:
                    # 兜底（理论上 accept=must∪suggest 全包，all=全8路，不应触达此分支）
                    reason = "路径未命中 must/suggest 任何规则"
                skipped_checkers.append({"name": c, "reason": reason})

    # ---- I1-I8 不变量校验（H-9/H-11 fix: assert → raise RoutingSchemaError，穿透堆栈风险消除）----
    _assert_scope_invariants(plan, decision, skipped_checkers)

    # ---- 构造 stats / diff_summary（调用 git diff --shortstat / --numstat）----
    stats, diff_summary = _git_diff_stats(args.base_sha, args.head_sha)

    # ---- 构造 services 列表 ----
    services = [s.strip() for s in args.services.split(",") if s.strip()]

    # ---- 构造完整 scope dict ----
    scope = {
        "mode": args.mode,
        "requirement_id": args.requirement_id,
        "feature_id": args.feature_id or "",
        "base_sha": args.base_sha,
        "head_sha": args.head_sha,
        "base_branch": args.base_branch,
        "current_branch": args.current_branch,
        "services": services,
        "stats": stats,
        "diff_summary": diff_summary,
        "timestamp": _now_shanghai(),
        "skipped": is_trivial_skipped,
        "checker_route": decision.final_route,
        "skipped_checkers": skipped_checkers,
        "routing_decision": {
            "decision": decision.decision,
            "confirmed_at": decision.confirmed_at,
            "confirmed_by": decision.confirmed_by,
            "tty_verified": decision.tty_verified,
            # H-8 fix: §3.1 schema 要求 int（命中文件唯一数），而非 dict[str, list[str]]
            "files_must_hit": len({p for paths in plan.files_must_hit.values() for p in paths}),
            "files_suggest_hit": len({p for paths in plan.files_suggest_hit.values() for p in paths}),
            "files_trivial": plan.files_trivial,
            "files_total": plan.files_total,
        },
    }

    # ---- 原子写 ----
    scope_path = SCOPE_JSON_PATH
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=scope_path.parent if scope_path.parent != Path(".") else Path("."),
        suffix=".tmp",
        prefix=".review-scope-",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(scope, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, scope_path)
    except Exception:
        # 清理残留 tmp 文件，再重新抛出
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _git_diff_stats(base_sha: str, head_sha: str) -> tuple[dict, str]:
    """获取 git diff shortstat 和 numstat，解析为结构化数据。

    失败时返回空结构，不阻断主流程（stats 仅用于展示，非关键路径）。
    """
    stats: dict = {"insertions": 0, "deletions": 0, "files_changed": 0}
    diff_summary = ""

    try:
        # --shortstat：例如 "3 files changed, 50 insertions(+), 10 deletions(-)"
        shortstat = subprocess.run(
            ["git", "diff", "--shortstat", f"{base_sha}..{head_sha}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        m_files = re.search(r"(\d+) file", shortstat)
        m_ins = re.search(r"(\d+) insertion", shortstat)
        m_del = re.search(r"(\d+) deletion", shortstat)
        if m_files:
            stats["files_changed"] = int(m_files.group(1))
        if m_ins:
            stats["insertions"] = int(m_ins.group(1))
        if m_del:
            stats["deletions"] = int(m_del.group(1))

        # --numstat：每行 "ins\tdel\tfile"
        numstat_out = subprocess.run(
            ["git", "diff", "--numstat", f"{base_sha}..{head_sha}"],
            capture_output=True, text=True, check=True,
        ).stdout
        lines = []
        for row in numstat_out.splitlines():
            parts = row.split("\t", 2)
            if len(parts) == 3:
                ins, dl, fname = parts
                lines.append(f"{fname} (+{ins} -{dl})")
        diff_summary = "\n".join(lines)
    except Exception as exc:
        # H-15 fix: 降级但不静默吞没，打印到 stderr 让用户知晓（stats 仅展示用，非关键路径）
        print(f"[routing] git diff stats 获取失败（{exc}），使用空结构", file=sys.stderr)
        return {"files_changed": 0, "insertions": 0, "deletions": 0, "diff_summary": ""}

    return stats, diff_summary


def _handle_routing_result(
    plan: RoutingPlan,
    args: argparse.Namespace,
    confirmed_by: str,
) -> None:
    """处理 routing 结果的四个分支（trivial-skipped / accept / all / custom）。

    H-4 fix：从 main() 抽出，降低 main 嵌套层级，使 main 只保留 8 步骨架。
    abort 路径由 _prompt_user 内部 raise RoutingAbort，由 main 的 except 捕获。
    """
    if plan.trivial_only:
        # 全 trivial，自动跳过，无需人工确认
        decision = RoutingDecision(
            decision="trivial-skipped",
            confirmed_at=_now_shanghai_display(),
            confirmed_by=confirmed_by,
            tty_verified=True,
            final_route=[],
        )
        _write_scope(plan, decision, args)
        _audit_log(
            args.requirement_id,
            f"[code-review-skipped] {plan.files_total} 文件全在 trivial 白名单内（routing-auto）",
        )
        return

    # 需要人工确认；abort 路径由 _prompt_user 内部 raise RoutingAbort
    decision_raw = _prompt_user(plan, req_id=args.requirement_id)

    # 补充 confirmed_by（_prompt_user 不做 git 调用，避免在交互过程中阻塞）
    decision = RoutingDecision(
        decision=decision_raw.decision,
        confirmed_at=_now_shanghai_display(),
        confirmed_by=confirmed_by,
        tty_verified=True,
        final_route=decision_raw.final_route,
    )

    _write_scope(plan, decision, args)

    if decision.decision == "custom":
        checker_list = ", ".join(decision.final_route)
        _audit_log(
            args.requirement_id,
            f"[code-review-route-custom] 用户自定义子集：{checker_list}",
        )
    # accept / all 不写 audit（§8.4）


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口：routing 8 步流程。

    不直接调用 sys.exit；返回整数退出码，由调用方决定是否 exit。
    顶层 try/except RoutingError 统一处理所有退码分支。
    """
    try:
        # 步骤 1：解析参数
        args = _parse_args(argv)

        # 步骤 2：tty 校验
        _check_tty()

        # 步骤 3：加载 yaml
        raw = _load_yaml(ROUTING_YAML_PATH)

        # 步骤 4：schema 校验
        config = _validate_schema(raw)

        # 步骤 5：枚举 diff 文件
        files = _enumerate_diff_files(args.base_sha, args.head_sha)

        # 步骤 6：构造路由计划
        plan = _build_plan(files, config)

        # 步骤 7：分支处理（H-4 fix：委托给 _handle_routing_result，main 只保留 8 步骨架）
        confirmed_by = _resolve_confirmed_by()
        _handle_routing_result(plan, args, confirmed_by)

        return EXIT_OK

    except RoutingError as e:
        if e.exit_code == EXIT_USER_ABORT:
            # H-7 fix: RoutingAbort.detail 已是 _ERROR_MESSAGES[5].format(cause=...) 完整字符串
            # 不能再套一层 format，否则输出嵌套消息（如"已取消（已取消（...））"）
            # 用户主动 abort 不算错误，输出到 stdout（§6）
            print(str(e))
        else:
            # 其他错误输出到 stderr
            try:
                msg = _ERROR_MESSAGES[e.exit_code].format(
                    detail=str(e),
                    file="routing.yaml",
                    line="?",
                    cause=str(e),
                )
            except KeyError:
                msg = f"[routing] 未知错误（退码 {e.exit_code}）：{e}"
            print(msg, file=sys.stderr)
        return e.exit_code


if __name__ == "__main__":
    sys.exit(main())


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
    # 核心函数（F-001）
    "_load_yaml",
    "_validate_rule_entry",
    "_validate_schema",
    "_parse_rule_list",
    "_enumerate_diff_files",
    "_compile_specs",
    "_match_file",
    "_assert_plan_invariants",
    "_build_plan",
    # IO 层（F-002）
    "_parse_args",
    "_check_tty",
    "_resolve_confirmed_by",
    "_parse_custom_input",
    "_classify_input",
    "_prompt_user",
    "_assert_scope_invariants",
    "_handle_routing_result",
    "_write_scope",
    "_audit_log",
    # H-20 fix: 私有工具函数补入 __all__，与同模块其他私有符号保持一致
    "_now_shanghai",
    "_now_shanghai_display",
    "main",
]
