"""features.json 校验工具（F-002）。

用途：
  - 校验 requirements/<id>/artifacts/features.json 是否符合
    context/team/engineering-spec/features-schema.yaml 定义的 schema。
  - GATE-FEATURES-SCHEMA plugin 在 run() 中调用本工具（导入方式），
    CI / 人工也可直接 CLI 调用。

退出码：
  0 — 校验通过，无 error
  1 — 数据违规（字段缺失 / 枚举越界 / 格式错误）
  2 — schema 文件自身损坏（check_features.py 启动时 assert 失败）

用法：
  python3 scripts/lib/check_features.py <features.json 路径>

双层 schema_version 校验（detailed-design.md §4.1）：
  L1：SCHEMA_PATH 文件顶部 schema_version 必须 == "1.0"（schema 文件布局版本）
  L2：features.json 顶部 schema_version 必须 ∈ SUPPORTED_VERSIONS（数据载荷版本）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# ---------- 常量 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = _REPO_ROOT / "context" / "team" / "engineering-spec" / "features-schema.yaml"

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
    """读 features-schema.yaml 并断言 L1 schema_version == "1.0"。

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
            "schema 文件可能被破坏或与当前 check_features.py 不匹配"
        )
    return schema


def _load_features(path: Path) -> dict[str, Any]:
    """读 features.json，解析失败时 exit 1（数据文件格式错误）。"""
    if not path.exists():
        print(f"错误：features.json 文件不存在：{path}", file=sys.stderr)
        sys.exit(1)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"错误：features.json 文件 JSON 解析失败：{exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, dict):
        print("错误：features.json 文件顶层不是 JSON object", file=sys.stderr)
        sys.exit(1)
    return data


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

    detailed-design.md §4.3：schema_version 列入 required_fields 顶层；
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
            f"迁移脚本：scripts/lib/migrate_features_{sv}_to_{max(SUPPORTED_VERSIONS)}.py"
        )


def _check_top_level_required(data: dict[str, Any], schema: dict[str, Any],
                               report: _ErrorReport, file_label: str) -> None:
    """校验顶层 required_fields 列表中的每个字段必须存在。"""
    required = schema.get("required_fields", []) or []
    # schema_version 单独在 _check_schema_version 处理
    non_schema_version = [f for f in required if f != "schema_version"]
    for field in non_schema_version:
        if field not in data:
            report.add(f"字段 {field} 必填，当前缺失")


def _check_top_level_format(data: dict[str, Any], schema: dict[str, Any],
                             report: _ErrorReport, file_label: str) -> None:
    """校验顶层 format 字段值的格式（regex）。

    schema_version 格式在 _check_schema_version 中已处理，此处跳过。
    """
    fmt_rules = schema.get("format", {}) or {}
    for field, rule in fmt_rules.items():
        if field == "schema_version":
            continue  # 单独处理
        value = data.get(field)
        if value is None or value == "":
            continue  # 空值由必填规则处理
        if isinstance(rule, str) and rule.startswith("^"):
            if not isinstance(value, str) or not re.fullmatch(rule, value):
                report.add(f"字段 {field} 值 {value!r} 不符合正则 {rule}")


def _check_feature_item(feature: Any, idx: int, schema: dict[str, Any],
                        report: _ErrorReport) -> None:
    """校验 features 数组中单条 feature 元素。

    Args:
        feature: features[] 中第 idx 条元素（任意类型，非 dict 会报错）。
        idx: 元素在数组中的下标（从 0 开始），用于错误消息定位（features[i].field）。
        schema: 已加载的 features-schema.yaml dict。
        report: 错误累积报告实例。
    """
    prefix = f"features[{idx}]"

    if not isinstance(feature, dict):
        report.add(f"{prefix} 不是 JSON object，实际类型：{type(feature).__name__}")
        return

    # 必填字段检查
    feat_required = schema.get("feature_required_fields", []) or []
    for field in feat_required:
        if field not in feature:
            report.add(f"{prefix}.{field} 必填，当前缺失")

    # id 格式校验
    feat_fmt = schema.get("feature_format", {}) or {}
    id_val = feature.get("id")
    if id_val is not None:
        id_rule = feat_fmt.get("id")
        if id_rule and (not isinstance(id_val, str) or not re.fullmatch(id_rule, id_val)):
            report.add(f"{prefix}.id 值 {id_val!r} 不符合正则 {id_rule}")

    # complexity 枚举校验
    enums = schema.get("enums", {}) or {}
    complexity_val = feature.get("complexity")
    if complexity_val is not None:
        allowed = enums.get("complexity", [])
        if complexity_val not in allowed:
            report.add(
                f"{prefix}.complexity 值 {complexity_val!r} 不在枚举 {allowed} 内"
            )

    # depends_on_features 元素格式校验
    dof = feature.get("depends_on_features")
    if dof is not None and isinstance(dof, list):
        item_rule = feat_fmt.get("depends_on_features_item")
        if item_rule:
            for j, item in enumerate(dof):
                if not isinstance(item, str) or not re.fullmatch(item_rule, item):
                    report.add(
                        f"{prefix}.depends_on_features[{j}] 值 {item!r} "
                        f"不符合正则 {item_rule}"
                    )

    # list 类型字段校验（必须是 list，不能是其他类型）
    list_fields = {"modules", "depends_on", "depends_on_features", "touches", "acceptance"}
    for field in list_fields:
        val = feature.get(field)
        if val is not None and not isinstance(val, list):
            report.add(f"{prefix}.{field} 必须是列表，实际类型：{type(val).__name__}")


def _check_features_array(data: dict[str, Any], schema: dict[str, Any],
                           report: _ErrorReport, file_label: str) -> None:
    """校验 features 数组：类型 + 每条元素单独校验。"""
    features = data.get("features")
    if features is None:
        return  # 缺失由 _check_top_level_required 报告

    if not isinstance(features, list):
        report.add(f"字段 features 必须是数组，实际类型：{type(features).__name__}")
        return

    for idx, feature in enumerate(features):
        _check_feature_item(feature, idx, schema, report)


def validate(data: dict[str, Any], schema: dict[str, Any], file_label: str) -> _ErrorReport:
    """对 features.json data 执行完整校验管道，返回错误报告。

    校验时序（detailed-design.md §4.3）：
      [1] schema_version（L2 双层）
      [2] required_fields（顶层）
      [3] format（顶层字段 regex）
      [4] features 数组：每条 element 的 required / enum / format

    Args:
        data: features.json 解析后的 dict，须经过 `_load_features()` 校验（顶层必须是 dict）。
        schema: `_load_schema()` 返回值，顶层 schema_version 已通过 L1 断言。
        file_label: 仅用于错误消息标签（不做路径操作），通常传 str(features_path)。

    Returns:
        _ErrorReport 实例；report.has_errors 为 True 时表示存在校验错误，
        调用 report.errors 获取错误列表，report.print_all() 输出到 stderr。
    """
    report = _ErrorReport()
    _check_schema_version(data, report, file_label)
    _check_top_level_required(data, schema, report, file_label)
    _check_top_level_format(data, schema, report, file_label)
    _check_features_array(data, schema, report, file_label)
    return report


# ---------- CLI 入口 ----------

def main() -> int:
    """CLI 入口：exit 0 OK / exit 1 数据违规 / exit 2 schema 损坏。"""
    if len(sys.argv) != 2:
        print("用法：python3 scripts/lib/check_features.py <features.json 路径>", file=sys.stderr)
        sys.exit(2)

    features_path = Path(sys.argv[1])
    try:
        schema = _load_schema()
    except SchemaLoadError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(2)
    data = _load_features(features_path)  # 失败时内部 exit 1

    file_label = str(features_path)
    report = validate(data, schema, file_label)

    if report.has_errors:
        report.print_all(file_label)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
