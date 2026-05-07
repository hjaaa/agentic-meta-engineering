"""subagent 回执 JSON 校验工具（F-001）。

用途：
  - 校验 requirements/<id>/artifacts/tasks/<F-xxx>.receipt.json 是否符合
    context/team/engineering-spec/receipt-schema.yaml 定义的 schema。
  - GATE-POST-DEV-RECEIPT plugin 在 run() 中调用本工具（导入方式），
    CI / 人工也可直接 CLI 调用。

退出码：
  0 — 校验通过，无 error
  1 — 数据违规（字段缺失 / 枚举越界 / 格式错误 / 条件必填不满足）
  2 — schema 文件自身损坏（check_receipt.py 启动时 assert 失败）

用法：
  python3 scripts/lib/check_receipt.py <receipt.json 路径>

双层 schema_version 校验（detailed-design.md §4.1）：
  L1：SCHEMA_PATH 文件顶部 schema_version 必须 == "1.0"（schema 文件布局版本）
  L2：receipt.json 顶部 schema_version 必须 ∈ SUPPORTED_VERSIONS（数据载荷版本）
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# ---------- 常量 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = _REPO_ROOT / "context" / "team" / "engineering-spec" / "receipt-schema.yaml"

# 数据载荷 schema_version 白名单（双层校验第 L2 层）
# 升级策略：
#   - 新增 minor（1.0→1.1）：集合更新为 {"1.0","1.1"}，兼容期至少一个 release cycle
#   - 破坏性升级（1.x→2.0）：集合替换为 {"1.x","2.0"}；过期后剔除旧版本
SUPPORTED_VERSIONS: frozenset[str] = frozenset({"1.0"})


# ---------- 自定义异常 ----------

class SchemaLoadError(RuntimeError):
    """schema 文件无法加载或 L1 校验失败（schema 文件自身被破坏）。"""


# ---------- 工具函数 ----------

def _load_schema() -> dict[str, Any]:
    """读 receipt-schema.yaml 并断言 L1 schema_version == "1.0"。

    失败时抛 SchemaLoadError（库函数不 sys.exit；CLI 入口 main() 负责捕获并 exit 2）。
    plugin 调用方应捕获 SchemaLoadError，不再需要 except SystemExit。
    """
    if not SCHEMA_PATH.exists():
        raise SchemaLoadError(f"schema 文件不存在：{SCHEMA_PATH}")
    try:
        with SCHEMA_PATH.open("r", encoding="utf-8") as f:
            schema = yaml.safe_load(f)
    except Exception as exc:  # noqa: BLE001
        raise SchemaLoadError(f"schema 文件解析失败：{exc}") from exc
    if not isinstance(schema, dict):
        raise SchemaLoadError("schema 文件顶层不是 mapping")
    # L1 断言：schema 文件自身版本必须是 "1.0"
    sv = schema.get("schema_version")
    if sv != "1.0":
        raise SchemaLoadError(
            f"schema 文件 schema_version={sv!r} ≠ '1.0'，"
            "schema 文件可能被破坏或与当前 check_receipt.py 不匹配"
        )
    return schema


def _load_receipt(path: Path) -> dict[str, Any]:
    """读 receipt.json，解析失败时 exit 1（数据文件格式错误）。"""
    if not path.exists():
        print(f"错误：receipt 文件不存在：{path}", file=sys.stderr)
        sys.exit(1)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"错误：receipt 文件 JSON 解析失败：{exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, dict):
        print("错误：receipt 文件顶层不是 JSON object", file=sys.stderr)
        sys.exit(1)
    return data


def _is_empty(value: Any) -> bool:
    """判断值是否为"空"（None / 空字符串 / 空列表 / 空 dict）。"""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _check_iso8601(value: Any) -> bool:
    """宽松 ISO8601 校验：datetime.fromisoformat 兼容格式即可。"""
    if not isinstance(value, str):
        return False
    try:
        # Python 3.7+ datetime.fromisoformat 接受 "2026-05-01T12:00:00" 等格式
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


# ---------- 校验管道 ----------

class _ErrorReport:
    """累积校验错误，不 fail-fast。"""

    def __init__(self) -> None:
        self._errors: list[str] = []

    def add(self, msg: str) -> None:
        self._errors.append(msg)

    @property
    def has_errors(self) -> bool:
        return len(self._errors) > 0

    @property
    def errors(self) -> list[str]:
        """返回错误列表的副本（避免外部 mutate 内部状态）。"""
        return list(self._errors)

    def print_all(self, file_label: str) -> None:
        """把所有错误输出到 stderr（含文件路径、字段名、期望 vs 实际）。"""
        for err in self._errors:
            print(f"{file_label}: {err}", file=sys.stderr)


def _check_schema_version(data: dict[str, Any], report: _ErrorReport, file_label: str) -> None:
    """L2 双层 schema_version 校验（required + format + SUPPORTED_VERSIONS）。

    detailed-design.md §4.4：schema_version 列入 required_fields 顶层；
    format regex ``^\\d+\\.\\d+$``（不接受 '1' / '1.0.0' / '1.0-beta'）。
    """
    sv = data.get("schema_version")
    if sv is None:
        report.add("字段 schema_version 必填，当前缺失")
        return
    # format 校验：必须是 major.minor 形式
    if not isinstance(sv, str) or not re.fullmatch(r"\d+\.\d+", sv):
        report.add(
            f"字段 schema_version 值 {sv!r} 格式不符合 ^\\d+\\.\\d+$"
            "（不接受 '1' / '1.0.0' / '1.0-beta'）"
        )
        return
    # SUPPORTED_VERSIONS 白名单（L2）
    if sv not in SUPPORTED_VERSIONS:
        report.add(
            f"字段 schema_version={sv!r} 不在 supported 集合 {set(SUPPORTED_VERSIONS)}；"
            f"迁移脚本：scripts/lib/migrate_receipt_{sv}_to_{max(SUPPORTED_VERSIONS)}.py"
        )


def _check_required_fields(data: dict[str, Any], schema: dict[str, Any],
                            report: _ErrorReport, file_label: str) -> None:
    """校验 required_fields 列表中的每个字段必须存在。

    注意：missing_context / block_reason 允许空字符串（条件必填由 _check_conditional 处理）。
    """
    required = schema.get("required_fields", []) or []
    # schema_version 单独在 _check_schema_version 处理
    non_schema_version = [f for f in required if f != "schema_version"]

    # 这里只校验存在性；空值的条件性约束（missing_context / block_reason /
    # concerns 等）由 _check_conditional 按状态判定。
    for field in non_schema_version:
        if field not in data:
            report.add(f"字段 {field} 必填，当前缺失")


def _check_enums(data: dict[str, Any], schema: dict[str, Any],
                 report: _ErrorReport, file_label: str) -> None:
    """校验 enums 中的字段值必须在枚举列表内。"""
    enums = schema.get("enums", {}) or {}
    for field, allowed in enums.items():
        value = data.get(field)
        if value is None:
            continue  # 缺失由 _check_required_fields 处理
        if value not in allowed:
            report.add(
                f"字段 {field} 值 {value!r} 不在枚举 {allowed} 内"
            )


def _check_format(data: dict[str, Any], schema: dict[str, Any],
                  report: _ErrorReport, file_label: str) -> None:
    """校验 format 字段值的格式（regex / iso8601）。

    schema_version 格式在 _check_schema_version 中已处理，此处跳过。
    """
    fmt_rules = schema.get("format", {}) or {}
    for field, rule in fmt_rules.items():
        if field == "schema_version":
            continue  # 单独处理
        value = data.get(field)
        if value is None or value == "":
            continue  # 空值由必填规则处理
        if rule == "iso8601" or rule == "datetime":
            if not _check_iso8601(str(value)):
                report.add(
                    f"字段 {field} 值 {value!r} 不符合 ISO8601 时间格式"
                    "（示例：2026-05-01T12:00:00+08:00）"
                )
        elif isinstance(rule, str) and rule.startswith("^"):
            if not isinstance(value, str) or not re.fullmatch(rule, value):
                report.add(f"字段 {field} 值 {value!r} 不符合正则 {rule}")


def _check_conditional(data: dict[str, Any], schema: dict[str, Any],
                       report: _ErrorReport, file_label: str) -> None:
    """校验条件必填规则（conditional_required）。

    详细设计 §4：
      - DONE_WITH_CONCERNS 时 concerns 必须非空列表
      - NEEDS_CONTEXT 时 missing_context 必须非空字符串
      - BLOCKED 时 block_reason 必须非空字符串
      - DONE 时 concerns 必须为空列表（防止 DONE 混入 concerns）
    """
    status = data.get("status")

    # schema 中的通用 conditional_required 规则
    for rule in schema.get("conditional_required", []) or []:
        when = rule.get("when", {})
        # 判断 when 条件是否满足
        matched = all(data.get(k) == v for k, v in when.items())
        if not matched:
            continue
        for field in rule.get("non_empty", []):
            if _is_empty(data.get(field)):
                report.add(
                    f"status={status!r} 时字段 {field} 必须非空，当前为空"
                )

    # 额外：DONE 时 concerns 必须为空列表
    if status == "DONE":
        concerns = data.get("concerns")
        if concerns is not None and not (isinstance(concerns, list) and len(concerns) == 0):
            report.add(
                f"status='DONE' 时字段 concerns 必须为空列表 []，"
                f"当前值：{concerns!r}"
            )


def validate(data: dict[str, Any], schema: dict[str, Any], file_label: str) -> _ErrorReport:
    """对 receipt data 执行完整校验管道，返回错误报告。

    校验时序（detailed-design.md §4.2）：
      [1] schema_version（L2 双层）
      [2] required_fields
      [3] enums
      [4] format
      [5] conditional_required

    Args:
        data: receipt.json 解析后的 dict，须经过 `_load_receipt()` 校验（顶层必须是 dict）。
        schema: `_load_schema()` 返回值，顶层 schema_version 已通过 L1 断言。
        file_label: 仅用于错误消息标签（不做路径操作），通常传 str(receipt_path)。

    Returns:
        _ErrorReport 实例；report.has_errors 为 True 时表示存在校验错误，
        调用 report.errors 获取错误列表，report.print_all() 输出到 stderr。
    """
    report = _ErrorReport()
    if not isinstance(data, dict):
        # 防御性 type guard：lib 调用方（如 plugins/post_dev_receipt.py）
        # 可能跳过 _load_receipt 而直接传入 json.load 结果——此时 data 可能是
        # list/str/None 等非 mapping，下游 _check_* 会 AttributeError 让 gate
        # plugin 整个 crash。改成 report 一条错误并立即返回，让调用方走
        # 正常 has_errors 失败路径。
        report.add(f"receipt 顶层不是 JSON object（实际类型：{type(data).__name__}）")
        return report
    _check_schema_version(data, report, file_label)
    _check_required_fields(data, schema, report, file_label)
    _check_enums(data, schema, report, file_label)
    _check_format(data, schema, report, file_label)
    _check_conditional(data, schema, report, file_label)
    return report


# ---------- CLI 入口 ----------

def main() -> int:
    """CLI 入口：exit 0 OK / exit 1 数据违规 / exit 2 schema 损坏。"""
    if len(sys.argv) != 2:
        print("用法：python3 scripts/lib/check_receipt.py <receipt.json 路径>", file=sys.stderr)
        sys.exit(2)

    receipt_path = Path(sys.argv[1])
    try:
        schema = _load_schema()
    except SchemaLoadError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(2)
    data = _load_receipt(receipt_path)  # 失败时内部 exit 1

    file_label = str(receipt_path)
    report = validate(data, schema, file_label)

    if report.has_errors:
        report.print_all(file_label)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
