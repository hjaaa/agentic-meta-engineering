"""Workflow yaml 加载与强校验（F-001 范围）。

入口：
    from workflow_loader import load_workflow, discover_workflows, LoadResult
    result = load_workflow(Path('.claude/workflows/requirement/standard-8phase.yaml'))
    if result.report.errors:
        print(result.report.render())
        sys.exit(1)

错误码（W000~W153，14 类）：
    W000  yaml 文件不存在
    W001  yaml 解析失败 / 顶层非 mapping
    W100  schema 缺必填字段（顶层 / 节点 / loop / approval / retry 等）
    W110  节点同时声明 ≥2 个互斥类型字段（skill/agent/prompt/bash/loop/approval/artifact/sub_workflow）
    W111  节点未声明任一类型字段
    W112  节点 ID 重复
    W120  DAG 存在环
    W121  depends_on 引用了未定义的节点
    W130  when 表达式语法非法
    W131  $nodeId.output 引用了不存在节点
    W140  prompt 与 prompt_file 互斥违反（含 loop.prompt / loop.prompt_file）
    W141  prompt_file 路径不在 .claude/workflows/prompts/ 内
    W142  prompt_file 引用的文件不存在
    W150  sub_workflow 嵌套深度 > 2
    W151  sub_workflow 路径未找到
    W152  sub_workflow 循环引用
    W153  sub_workflow 解析失败 / 默认值补全错

设计要点：
- 不依赖 `jsonschema`（项目环境未装），用手写校验 + Severity / Report 复用。
- 校验顺序：W000/W001 → schema（W100）→ 互斥（W110/W111）→ 唯一（W112）
  → DAG（W120/W121）→ when/var-ref（W130/W131）→ prompt_file（W140-142）
  → sub_workflow（W150-153）→ 默认值补全（最后；无错才补）。
- 错的越早越要短路：schema 级错误存在时不再做语义级校验，避免错误瀑布。
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from common import REPO_ROOT, Report, Severity, WorkflowError, rel
from topological_sort import CycleError, topological_layers


# ============================================================================
# 公开数据结构
# ============================================================================

@dataclass
class LoadResult:
    """workflow_loader.load_workflow() 返回值。"""

    workflow: dict[str, Any] | None
    report: Report = field(default_factory=Report)
    source_path: Path | None = None


@dataclass
class DiscoveredWorkflow:
    """三层模板发现的单条结果。"""

    name: str
    workflow: dict[str, Any]
    source: str  # "bundled" | "home" | "project"
    source_path: Path


# WorkflowError 统一从 common.py 导入（跨模块 except 同一性保证）
# loader 层确定性错误（D-007 _resolve_run_dir 找不到时）抛此异常


# ============================================================================
# 常量与正则
# ============================================================================

NODE_TYPE_FIELDS: tuple[str, ...] = (
    "skill", "agent", "prompt", "prompt_file", "bash",
    "loop", "approval", "artifact", "sub_workflow",
)
# prompt 与 prompt_file 在引擎层等价（外置 / 内联），互斥校验单独出 W140
NODE_TYPE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("skill",),
    ("agent",),
    ("prompt", "prompt_file"),
    ("bash",),
    ("loop",),
    ("approval",),
    ("artifact",),
    ("sub_workflow",),
)
TOP_REQUIRED: tuple[str, ...] = ("name", "version", "category", "nodes")
ALLOWED_CATEGORIES: set[str] = {
    "requirement", "review", "release", "knowledge", "pr", "assist",
}
ALLOWED_PROVIDERS: set[str] = {"claude"}
ALLOWED_EFFORTS: set[str] = {"low", "medium", "high", "max"}
ALLOWED_THINKING: set[str] = {"adaptive", "enabled", "disabled"}
ALLOWED_TRIGGER_RULES: set[str] = {"all_success", "one_success", "all_done"}
ALLOWED_CONTEXT: set[str] = {"fresh", "shared"}
ALLOWED_ON_SUB_FAILURE: set[str] = {"fail", "continue", "skip"}

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,49}$")
NODE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,59}$")

# `$nodeId.output[.field]`
VAR_REF_RE = re.compile(
    r"\$(?P<node>[a-z][a-z0-9-]*)\.output(?:\.(?P<field>[a-zA-Z_][a-zA-Z0-9_]*))?"
)

WORKFLOWS_PROMPTS_DIR = REPO_ROOT / ".claude" / "workflows" / "prompts"
MAX_SUB_WORKFLOW_DEPTH = 2

DEFAULT_RETRY: dict[str, Any] = {"max_attempts": 2, "delay_ms": 3000, "on_error": "transient"}
DEFAULT_TRIGGER_RULE = "all_success"
NODE_TYPE_DEFAULT_TIMEOUT_MS: dict[str, int] = {
    "skill": 300_000,
    "agent": 300_000,
    "prompt": 300_000,
    "prompt_file": 300_000,
    "bash": 60_000,
    "loop": 300_000,
    "approval": 86_400_000,        # 24h（用户响应可能慢）
    "artifact": 30_000,
    "sub_workflow": 1_800_000,     # 30min
}


# ============================================================================
# 主入口：load_workflow
# ============================================================================

def load_workflow(path: Path) -> LoadResult:
    """加载并强校验单个 workflow yaml。

    返回 LoadResult；调用方按 `report.errors` / `report.exit_code(strict)` 判断结果。
    校验失败时 `result.workflow` 保持 None，避免 caller 误用半校验产物。
    """
    result = LoadResult(workflow=None, source_path=path)
    file_label = rel(path)

    if not path.exists():
        result.report.add(file_label, Severity.ERROR, "W000", f"yaml 文件不存在: {path}")
        return result

    raw = _parse_yaml(path, result, file_label)
    if raw is None:
        return result

    # 1) schema 必填 / 类型 / 枚举
    _validate_schema_top(raw, result.report, file_label)
    if result.report.errors:
        return result

    # 2) 节点字段 schema（深入每节点的子结构）
    _validate_nodes_schema(raw, result.report, file_label)
    if result.report.errors:
        return result

    # 3) 互斥（W110/W111）
    _validate_node_type_mutex(raw, result.report, file_label)
    # 4) 唯一性（W112）
    _validate_node_id_uniqueness(raw, result.report, file_label)
    if result.report.errors:
        return result

    # 5) depends_on 隐式接上一节点 → 写回展开
    _expand_implicit_depends_on(raw)
    # 6) DAG（W120/W121）
    _validate_dag(raw, result.report, file_label)
    # 7) when 语法 + 变量引用合法（W130/W131）
    _validate_when_and_var_refs(raw, result.report, file_label)
    # 8) prompt / prompt_file（W140-142）
    _validate_prompt_files(raw, result.report, file_label)
    # 9) sub_workflow 嵌套深度（W150-153）
    search_root = _infer_workflows_search_root(path)
    _validate_sub_workflow_depth(raw, result.report, file_label, search_root)

    # 默认值补全只在无错时做（避免错误叠加）
    if not result.report.errors:
        _apply_defaults(raw, result.report, file_label)
        result.workflow = raw

    return result


# ============================================================================
# 三层模板发现
# ============================================================================

def discover_workflows(
    bundled_dir: Path | None = None,
    home_dir: Path | None = None,
    project_dir: Path | None = None,
) -> dict[str, DiscoveredWorkflow]:
    """三层模板发现：bundled → home → project，后者覆盖前者（spec §5.2）。"""
    if bundled_dir is None:
        bundled_dir = REPO_ROOT / ".claude" / "workflows" / "bundled"
    if home_dir is None:
        home_dir = Path.home() / ".claude" / "workflows"
    if project_dir is None:
        project_dir = REPO_ROOT / ".claude" / "workflows"

    discovered: dict[str, DiscoveredWorkflow] = {}

    def scan(directory: Path, source: str) -> None:
        if not directory.exists():
            return
        for yaml_path in directory.rglob("*.yaml"):
            # 跳过 prompts 目录（不是 workflow yaml）
            if "prompts" in yaml_path.parts:
                continue
            # project_dir 扫描时跳过 bundled 子目录（避免双扫）
            if source == "project":
                try:
                    yaml_path.relative_to(bundled_dir)
                    continue
                except ValueError:
                    pass
            res = load_workflow(yaml_path)
            if res.report.errors or res.workflow is None:
                continue
            name = res.workflow["name"]
            discovered[name] = DiscoveredWorkflow(
                name=name,
                workflow=res.workflow,
                source=source,
                source_path=yaml_path,
            )

    scan(bundled_dir, "bundled")
    scan(home_dir, "home")
    scan(project_dir, "project")
    return discovered


# ============================================================================
# 内部：parse / schema 校验
# ============================================================================

def _parse_yaml(path: Path, result: LoadResult, file_label: str) -> dict[str, Any] | None:
    """加载 yaml 并校验顶层 mapping；返回 raw dict 或 None。"""
    try:
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        result.report.add(file_label, Severity.ERROR, "W001", f"yaml 解析失败: {exc}")
        return None
    except OSError as exc:
        result.report.add(file_label, Severity.ERROR, "W001", f"yaml 读取失败: {exc}")
        return None

    if raw is None:
        result.report.add(file_label, Severity.ERROR, "W001", "yaml 内容为空")
        return None
    if not isinstance(raw, dict):
        result.report.add(file_label, Severity.ERROR, "W001", "yaml 顶层必须是 mapping")
        return None
    return raw


def _validate_schema_top(workflow: dict[str, Any], report: Report, file_label: str) -> None:
    """顶层字段 schema：必填 + 类型 + 枚举 + name/version 形态。"""
    for field_name in TOP_REQUIRED:
        if field_name not in workflow:
            report.add(file_label, Severity.ERROR, "W100",
                       f"顶层缺少必填字段 {field_name!r}")
    if report.errors:
        return

    name = workflow.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        report.add(file_label, Severity.ERROR, "W100",
                   f"name 必须匹配 ^[a-z][a-z0-9-]{{0,49}}$，实际 {name!r}")

    version = workflow.get("version")
    if version != 1:
        report.add(file_label, Severity.ERROR, "W100",
                   f"version 必须 = 1（当前 schema v1），实际 {version!r}")

    category = workflow.get("category")
    if category not in ALLOWED_CATEGORIES:
        report.add(file_label, Severity.ERROR, "W100",
                   f"category 必须 ∈ {sorted(ALLOWED_CATEGORIES)}，实际 {category!r}")

    nodes = workflow.get("nodes")
    if not isinstance(nodes, list) or len(nodes) == 0:
        report.add(file_label, Severity.ERROR, "W100",
                   f"nodes 必须为非空数组，实际 {type(nodes).__name__}")

    # 顶层可选字段类型校验
    if "provider" in workflow and workflow["provider"] not in ALLOWED_PROVIDERS:
        report.add(file_label, Severity.ERROR, "W100",
                   f"provider 必须 ∈ {sorted(ALLOWED_PROVIDERS)}，实际 {workflow['provider']!r}")
    if "effort" in workflow and workflow["effort"] not in ALLOWED_EFFORTS:
        report.add(file_label, Severity.ERROR, "W100",
                   f"effort 必须 ∈ {sorted(ALLOWED_EFFORTS)}，实际 {workflow['effort']!r}")
    if "thinking" in workflow and not _is_valid_thinking(workflow["thinking"]):
        report.add(file_label, Severity.ERROR, "W100",
                   f"thinking 必须是 adaptive/enabled/disabled 字符串或带 budgetTokens 的 object")


def _is_valid_thinking(value: Any) -> bool:
    """thinking 字段：字符串枚举 或 {type: 枚举, budgetTokens?: int}。"""
    if isinstance(value, str):
        return value in ALLOWED_THINKING
    if isinstance(value, dict):
        if value.get("type") not in ALLOWED_THINKING:
            return False
        budget = value.get("budgetTokens")
        if budget is not None and not (isinstance(budget, int) and budget >= 1):
            return False
        return True
    return False


def _validate_nodes_schema(workflow: dict[str, Any], report: Report, file_label: str) -> None:
    """每个节点的 schema：id 形态 / 子字段类型 / 子结构必填。"""
    nodes = workflow.get("nodes") or []
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            report.add(file_label, Severity.ERROR, "W100",
                       f"nodes[{idx}] 必须是 mapping，实际 {type(node).__name__}")
            continue
        nid = node.get("id")
        if not isinstance(nid, str) or not NODE_ID_PATTERN.match(nid):
            report.add(file_label, Severity.ERROR, "W100",
                       f"nodes[{idx}].id 必须匹配 ^[a-z][a-z0-9-]{{0,59}}$，实际 {nid!r}")
            continue
        # 公共字段类型
        if "depends_on" in node and not isinstance(node["depends_on"], list):
            report.add(file_label, Severity.ERROR, "W100",
                       f"节点 {nid}.depends_on 必须是数组")
        if "trigger_rule" in node and node["trigger_rule"] not in ALLOWED_TRIGGER_RULES:
            report.add(file_label, Severity.ERROR, "W100",
                       f"节点 {nid}.trigger_rule 必须 ∈ {sorted(ALLOWED_TRIGGER_RULES)}")
        if "context" in node and node["context"] not in ALLOWED_CONTEXT:
            report.add(file_label, Severity.ERROR, "W100",
                       f"节点 {nid}.context 必须 ∈ {sorted(ALLOWED_CONTEXT)}")
        if "provider" in node and node["provider"] not in ALLOWED_PROVIDERS:
            report.add(file_label, Severity.ERROR, "W100",
                       f"节点 {nid}.provider 必须 ∈ {sorted(ALLOWED_PROVIDERS)}")
        if "effort" in node and node["effort"] not in ALLOWED_EFFORTS:
            report.add(file_label, Severity.ERROR, "W100",
                       f"节点 {nid}.effort 必须 ∈ {sorted(ALLOWED_EFFORTS)}")
        if "thinking" in node and not _is_valid_thinking(node["thinking"]):
            report.add(file_label, Severity.ERROR, "W100",
                       f"节点 {nid}.thinking 字段非法")
        if "idle_timeout" in node and not (
            isinstance(node["idle_timeout"], int) and node["idle_timeout"] >= 1
        ):
            report.add(file_label, Severity.ERROR, "W100",
                       f"节点 {nid}.idle_timeout 必须是正整数")
        # 子结构必填校验
        _validate_node_substructures(node, nid, report, file_label)


def _validate_node_substructures(
    node: dict[str, Any], nid: str, report: Report, file_label: str
) -> None:
    """loop / approval / retry 等子结构的必填字段校验。"""
    loop = node.get("loop")
    if loop is not None:
        if not isinstance(loop, dict):
            report.add(file_label, Severity.ERROR, "W100",
                       f"节点 {nid}.loop 必须是 mapping")
        else:
            if "max_iterations" not in loop:
                report.add(file_label, Severity.ERROR, "W100",
                           f"节点 {nid}.loop 缺少必填字段 max_iterations")
            elif not (isinstance(loop["max_iterations"], int) and loop["max_iterations"] >= 1):
                report.add(file_label, Severity.ERROR, "W100",
                           f"节点 {nid}.loop.max_iterations 必须是 ≥ 1 的整数")
            if loop.get("interactive") is True and "gate_message" not in loop:
                report.add(file_label, Severity.ERROR, "W100",
                           f"节点 {nid}.loop interactive=true 必须配 gate_message")

    approval = node.get("approval")
    if approval is not None:
        if not isinstance(approval, dict):
            report.add(file_label, Severity.ERROR, "W100",
                       f"节点 {nid}.approval 必须是 mapping")
        else:
            # message 与 gate_message 至少有一个（spec §6.4 approval 节点）
            if "message" not in approval and "gate_message" not in approval:
                report.add(file_label, Severity.ERROR, "W100",
                           f"节点 {nid}.approval 必须含 message 或 gate_message")
            on_reject = approval.get("on_reject")
            if on_reject is not None:
                if not isinstance(on_reject, dict):
                    report.add(file_label, Severity.ERROR, "W100",
                               f"节点 {nid}.approval.on_reject 必须是 mapping")
                else:
                    for sub in ("prompt", "max_attempts"):
                        if sub not in on_reject:
                            report.add(file_label, Severity.ERROR, "W100",
                                       f"节点 {nid}.approval.on_reject 缺少必填 {sub}")

    retry = node.get("retry")
    if retry is not None:
        if not isinstance(retry, dict):
            report.add(file_label, Severity.ERROR, "W100",
                       f"节点 {nid}.retry 必须是 mapping")
        else:
            if "max_attempts" in retry and not (
                isinstance(retry["max_attempts"], int) and retry["max_attempts"] >= 0
            ):
                report.add(file_label, Severity.ERROR, "W100",
                           f"节点 {nid}.retry.max_attempts 必须是 ≥ 0 的整数")
            if "on_error" in retry and retry["on_error"] not in {"transient", "all"}:
                report.add(file_label, Severity.ERROR, "W100",
                           f"节点 {nid}.retry.on_error 必须 ∈ {{transient, all}}")

    sub_failure = node.get("on_subworkflow_failure")
    if sub_failure is not None and sub_failure not in ALLOWED_ON_SUB_FAILURE:
        report.add(file_label, Severity.ERROR, "W100",
                   f"节点 {nid}.on_subworkflow_failure 必须 ∈ {sorted(ALLOWED_ON_SUB_FAILURE)}")


# ============================================================================
# 内部：互斥 / 唯一性
# ============================================================================

def _node_type_groups_present(node: dict[str, Any]) -> list[tuple[str, ...]]:
    """返回节点上"出现至少一个字段"的 NODE_TYPE_GROUPS（用 prompt/prompt_file 组判定）。"""
    present_groups: list[tuple[str, ...]] = []
    for group in NODE_TYPE_GROUPS:
        if any(f in node for f in group):
            present_groups.append(group)
    return present_groups


def _validate_node_type_mutex(workflow: dict[str, Any], report: Report, file_label: str) -> None:
    """每个节点必须恰好 1 组 NODE_TYPE_GROUPS（prompt 与 prompt_file 同组）。"""
    for idx, node in enumerate(workflow.get("nodes") or []):
        nid = node.get("id", f"<node #{idx}>")
        groups = _node_type_groups_present(node)
        if len(groups) > 1:
            present_fields = [f for g in groups for f in g if f in node]
            report.add(file_label, Severity.ERROR, "W110",
                       f"节点 {nid} 同时声明了 {present_fields}，"
                       f"节点类型字段必须互斥")
        elif len(groups) == 0:
            report.add(file_label, Severity.ERROR, "W111",
                       f"节点 {nid} 必须声明 1 个节点类型字段："
                       f"skill/agent/prompt/prompt_file/bash/loop/approval/artifact/sub_workflow")


def _validate_node_id_uniqueness(
    workflow: dict[str, Any], report: Report, file_label: str
) -> None:
    """节点 ID 唯一性。"""
    seen: dict[str, int] = {}
    for idx, node in enumerate(workflow.get("nodes") or []):
        nid = node.get("id")
        if not nid:
            continue
        if nid in seen:
            report.add(file_label, Severity.ERROR, "W112",
                       f"节点 ID {nid!r} 重复（首次在 #{seen[nid]}，再次在 #{idx}）")
        else:
            seen[nid] = idx


# ============================================================================
# 内部：DAG 校验
# ============================================================================

def _expand_implicit_depends_on(workflow: dict[str, Any]) -> None:
    """`depends_on` 缺省 = 隐式接上一节点（spec §6.12）。"""
    nodes = workflow.get("nodes") or []
    prev_id: str | None = None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if "depends_on" not in node:
            node["depends_on"] = [prev_id] if prev_id else []
        prev_id = node.get("id")


def _validate_dag(workflow: dict[str, Any], report: Report, file_label: str) -> None:
    """W121 引用未定义节点 + W120 环。"""
    nodes = workflow.get("nodes") or []
    all_ids = {n["id"] for n in nodes if isinstance(n, dict) and "id" in n}

    # W121
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        for dep in node.get("depends_on") or []:
            if dep not in all_ids:
                report.add(file_label, Severity.ERROR, "W121",
                           f"节点 {nid} 的 depends_on 引用了不存在的节点 {dep!r}")

    if report.errors:
        # 有 W121 时跳拓扑（环检测会误报）
        return

    # W120
    try:
        topological_layers(nodes)
    except CycleError as exc:
        report.add(file_label, Severity.ERROR, "W120",
                   f"DAG 存在环：{exc.remaining_nodes}")


# ============================================================================
# 内部：when 语法 + 变量引用
# ============================================================================

# when 比较段：允许 `$nodeId.output[.field]` / 字符串 / 数字 / true|false|null
_WHEN_TERM_RE = re.compile(
    r"""
    \s*
    (?:
        \$ [a-z][a-z0-9-]* \.output (?:\.[a-zA-Z_][a-zA-Z0-9_]*)?
      | '[^']*'
      | "[^"]*"
      | -? \d+ (?:\.\d+)?
      | true | false | null
    )
    \s*
    """,
    re.VERBOSE,
)
_WHEN_OP_RE = re.compile(r"\s*(?:==|!=|<=|>=|<|>)\s*")
_WHEN_LOGIC_RE = re.compile(r"\s*(?:&&|\|\|)\s*")


def _validate_when_expression(expr: str) -> bool:
    """when 语法：term [OP term] (&& | || term [OP term])*；外层括号可选。

    返回 True = 合法；False = 语法错（loader 报 W130）。
    """
    if not expr or not expr.strip():
        return False
    s = expr.strip()
    # 剥外层括号最多 5 层（防止极端嵌套但不过度宽松）
    for _ in range(5):
        if s.startswith("(") and s.endswith(")"):
            s = s[1:-1].strip()
        else:
            break
    # 按 && / || 切段
    segments = _WHEN_LOGIC_RE.split(s)
    for seg in segments:
        seg = seg.strip().lstrip("(").rstrip(")").strip()
        if not seg:
            return False
        if not _is_valid_when_segment(seg):
            return False
    return True


def _is_valid_when_segment(seg: str) -> bool:
    """单段：要么 `term` 单独（boolean term），要么 `term OP term`。"""
    # 尝试 term OP term
    op_match = _WHEN_OP_RE.search(seg)
    if op_match:
        left = seg[: op_match.start()].strip()
        right = seg[op_match.end():].strip()
        return bool(_WHEN_TERM_RE.fullmatch(left)) and bool(_WHEN_TERM_RE.fullmatch(right))
    # 单 term
    return bool(_WHEN_TERM_RE.fullmatch(seg))


def _collect_referenced_node_ids(text: str) -> set[str]:
    """提取所有 $nodeId.output 中的 nodeId。"""
    return {m.group("node") for m in VAR_REF_RE.finditer(text or "")}


def _validate_when_and_var_refs(
    workflow: dict[str, Any], report: Report, file_label: str
) -> None:
    """W130 when 语法 + W131 $nodeId.output 引用合法。"""
    nodes = workflow.get("nodes") or []
    all_ids = {n["id"] for n in nodes if isinstance(n, dict) and "id" in n}

    def scan(text: str | None, owner: str, kind: str) -> None:
        if not text or not isinstance(text, str):
            return
        for ref in _collect_referenced_node_ids(text):
            if ref not in all_ids:
                report.add(file_label, Severity.ERROR, "W131",
                           f"节点 {owner} 的 {kind} 引用了不存在的节点 ${ref}.output")

    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node.get("id", "<unknown>")

        when_expr = node.get("when")
        if when_expr is not None:
            if not isinstance(when_expr, str) or not _validate_when_expression(when_expr):
                report.add(file_label, Severity.ERROR, "W130",
                           f"节点 {nid} 的 when 表达式语法错误: {when_expr!r}")
            scan(when_expr if isinstance(when_expr, str) else None, nid, "when")

        for fld in ("prompt", "prompt_override", "bash"):
            scan(node.get(fld), nid, fld)
        loop = node.get("loop")
        if isinstance(loop, dict):
            for lf in ("prompt", "until_bash", "gate_message"):
                scan(loop.get(lf), nid, f"loop.{lf}")
        approval = node.get("approval")
        if isinstance(approval, dict):
            scan(approval.get("message"), nid, "approval.message")
            scan(approval.get("gate_message"), nid, "approval.gate_message")
            on_reject = approval.get("on_reject")
            if isinstance(on_reject, dict):
                scan(on_reject.get("prompt"), nid, "approval.on_reject.prompt")
        # args 字段（dict）值扫描
        args = node.get("args")
        if isinstance(args, dict):
            for value in args.values():
                if isinstance(value, str):
                    scan(value, nid, "args")
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            scan(item, nid, "args")


# ============================================================================
# 内部：prompt_file 校验
# ============================================================================

def _validate_prompt_files(
    workflow: dict[str, Any], report: Report, file_label: str
) -> None:
    """W140/141/142：prompt vs prompt_file 互斥；prompt_file 必须在
    `.claude/workflows/prompts/` 下且文件存在。"""
    prompts_root = WORKFLOWS_PROMPTS_DIR.resolve()
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        nid = node.get("id", "<unknown>")
        # 节点级互斥
        if "prompt" in node and "prompt_file" in node:
            report.add(file_label, Severity.ERROR, "W140",
                       f"节点 {nid} 同时配置了 prompt 与 prompt_file，必须互斥")
        # loop 内互斥
        loop = node.get("loop") or {}
        if isinstance(loop, dict) and "prompt" in loop and "prompt_file" in loop:
            report.add(file_label, Severity.ERROR, "W140",
                       f"节点 {nid}.loop 同时配置了 prompt 与 prompt_file，必须互斥")

        # prompt_file 路径校验
        for owner_label, pf_value in [
            (f"{nid}.prompt_file", node.get("prompt_file")),
            (f"{nid}.loop.prompt_file", loop.get("prompt_file") if isinstance(loop, dict) else None),
        ]:
            if not pf_value or not isinstance(pf_value, str):
                continue
            target = _resolve_prompt_file(pf_value)
            try:
                target.relative_to(prompts_root)
            except ValueError:
                report.add(file_label, Severity.ERROR, "W141",
                           f"{owner_label} = {pf_value!r} 必须指向 "
                           f".claude/workflows/prompts/ 内")
                continue
            if not target.exists():
                report.add(file_label, Severity.ERROR, "W142",
                           f"{owner_label} 引用的文件不存在: {pf_value}")


def _resolve_prompt_file(pf_value: str) -> Path:
    """把 yaml 内的 prompt_file 字面量解析到绝对路径。

    支持两种写法：
    - `prompts/foo.md`   → `.claude/workflows/prompts/foo.md`
    - `foo.md` 或 `bar/foo.md` → `.claude/workflows/prompts/foo.md`（不带 prompts/ 前缀）
    """
    cleaned = pf_value
    if cleaned.startswith("prompts/"):
        cleaned = cleaned[len("prompts/"):]
    candidate = (WORKFLOWS_PROMPTS_DIR / cleaned).resolve()
    return candidate


# ============================================================================
# 内部：sub_workflow 嵌套深度
# ============================================================================

def _infer_workflows_search_root(yaml_path: Path) -> Path:
    """yaml 在 `.claude/workflows/<sub>/<file>.yaml` 时，根 = `.claude/workflows/`；
    fixtures 则用 yaml 自身父目录的"workflows"语义根（兼容测试 fixtures）。"""
    parts = yaml_path.resolve().parts
    if "workflows" in parts:
        idx = parts.index("workflows")
        return Path(*parts[: idx + 1])
    # fixtures 兜底：取 yaml 所在目录
    return yaml_path.parent


def _resolve_sub_workflow_path(ref: str, search_root: Path) -> Path | None:
    """支持相对 search_root 的路径与省略 .yaml 后缀。"""
    candidates = [
        search_root / f"{ref}.yaml",
        search_root / ref,
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def _validate_sub_workflow_depth(
    workflow: dict[str, Any],
    report: Report,
    file_label: str,
    search_root: Path,
    depth: int = 1,
    visited: set[Path] | None = None,
) -> None:
    """递归加载 sub_workflow 的 yaml，深度 > MAX_SUB_WORKFLOW_DEPTH 即 W150。"""
    if visited is None:
        visited = set()

    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        sub_ref = node.get("sub_workflow")
        if not sub_ref or not isinstance(sub_ref, str):
            continue
        sub_path = _resolve_sub_workflow_path(sub_ref, search_root)
        if sub_path is None:
            report.add(file_label, Severity.ERROR, "W151",
                       f"节点 {node.get('id')} 的 sub_workflow {sub_ref!r} 未找到"
                       f"（搜索 {rel(search_root)}）")
            continue
        # 循环引用检查必须先于深度检查；否则自引用 yaml 会在 depth 限定时被
        # 误报为 W150 而掩盖更准确的 W152。
        if sub_path in visited:
            report.add(file_label, Severity.ERROR, "W152",
                       f"节点 {node.get('id')} 出现 sub_workflow 循环引用: "
                       f"{rel(sub_path)}")
            continue
        if depth >= MAX_SUB_WORKFLOW_DEPTH:
            report.add(file_label, Severity.ERROR, "W150",
                       f"节点 {node.get('id')} 嵌套子 workflow 超过最大深度 "
                       f"{MAX_SUB_WORKFLOW_DEPTH}")
            continue
        visited.add(sub_path)
        try:
            with sub_path.open("r", encoding="utf-8") as fh:
                sub_yaml = yaml.safe_load(fh)
        except (yaml.YAMLError, OSError) as exc:
            report.add(file_label, Severity.ERROR, "W153",
                       f"嵌套 sub_workflow {rel(sub_path)} 解析失败: {exc}")
            continue
        if isinstance(sub_yaml, dict):
            _validate_sub_workflow_depth(
                sub_yaml, report, file_label, search_root, depth + 1, visited
            )


# ============================================================================
# 内部：默认值补全
# ============================================================================

def _infer_node_type(node: dict[str, Any]) -> str | None:
    """返回节点类型（首个匹配的字段名），无匹配返回 None。"""
    for field_name in NODE_TYPE_FIELDS:
        if field_name in node:
            return field_name
    return None


def _apply_defaults(workflow: dict[str, Any], report: Report, file_label: str) -> None:
    """补全 trigger_rule / retry / idle_timeout / 顶层默认继承。

    AC-06 字段优先级（yaml 节点 > 顶层默认；prompt frontmatter 由 F-002+ 接管）：
    本函数只做"yaml 节点缺省时从顶层默认继承"，且不会覆盖节点已有值。
    """
    wf_provider = workflow.get("provider", "claude")
    wf_model = workflow.get("model")
    wf_effort = workflow.get("effort")
    wf_thinking = workflow.get("thinking")

    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node.setdefault("trigger_rule", DEFAULT_TRIGGER_RULE)
        if "retry" not in node:
            node["retry"] = dict(DEFAULT_RETRY)
        elif isinstance(node["retry"], dict):
            for k, v in DEFAULT_RETRY.items():
                node["retry"].setdefault(k, v)
        # 顶层继承
        node.setdefault("provider", wf_provider)
        if wf_model is not None:
            node.setdefault("model", wf_model)
        if wf_effort is not None:
            node.setdefault("effort", wf_effort)
        if wf_thinking is not None:
            node.setdefault("thinking", wf_thinking)
        # idle_timeout 按节点类型默认
        ntype = _infer_node_type(node)
        if ntype and "idle_timeout" not in node:
            try:
                node["idle_timeout"] = NODE_TYPE_DEFAULT_TIMEOUT_MS[ntype]
            except KeyError:
                report.add(file_label, Severity.ERROR, "W153",
                           f"节点 {node.get('id')} 类型 {ntype} 无默认 idle_timeout")
        # spec §6.13: prompt/prompt_file/loop 节点 context 默认 shared
        # bash / approval / sub_workflow 等其他类型由引擎固定处理（不在此补默认）
        if ntype in ("prompt", "prompt_file", "loop"):
            node.setdefault("context", "shared")


# ============================================================================
# CLI
# ============================================================================

def main() -> int:
    """CLI 入口：`python3 scripts/lib/workflow_loader.py <yaml-path>`。"""
    import argparse

    parser = argparse.ArgumentParser(description="Validate a workflow yaml.")
    parser.add_argument("path", help="path to workflow yaml")
    parser.add_argument("--strict", action="store_true", help="warning 视为失败")
    parser.add_argument("--quiet", action="store_true", help="无错误时静默")
    parser.add_argument("--json", action="store_true",
                        help="输出 JSON（含 errors/warnings/summary）")
    args = parser.parse_args()

    target = Path(args.path)
    result = load_workflow(target)

    if args.json:
        payload = {
            "path": str(target),
            "errors": result.report.errors,
            "warnings": result.report.warnings,
            "findings": [
                {"file": f, "severity": s, "code": c, "message": m}
                for f, s, c, m in result.report.findings()
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if not args.quiet or result.report.errors > 0:
            print(result.report.render())

    return result.report.exit_code(args.strict)


if __name__ == "__main__":
    sys.exit(main())
