"""task.md frontmatter 校验工具（F-003）。

用途：
  - 校验 requirements/<id>/artifacts/tasks/<F-xxx>.md 的 YAML frontmatter 是否符合
    context/team/engineering-spec/task-frontmatter-schema.yaml 定义的 schema。
  - GATE-TASK-FRONTMATTER plugin 在 run() 中调用本工具（导入方式），
    CI / 人工也可直接 CLI 调用。

退出码：
  0 — 校验通过，无 error
  1 — 数据违规（字段缺失 / 枚举越界 / 格式错误 / frontmatter 缺失）
  2 — schema 文件自身损坏（check_task_frontmatter.py 启动时 assert 失败）

用法：
  python3 scripts/lib/check_task_frontmatter.py <task.md 路径>

双层 schema_version 校验（detailed-design.md §4.3）：
  L1：SCHEMA_PATH 文件顶部 schema_version 必须 == "1.0"（schema 文件布局版本）
  L2：task.md frontmatter 的 schema_version 必须 ∈ SUPPORTED_VERSIONS（数据载荷版本）

ADR（F-003）：schema_version 列为 required（不软兼容缺失），由 F-007 派发模板改造时统一注入；
  当前阶段若 task.md 改动触发 GATE-TASK-FRONTMATTER，会 fail 提示加 schema_version——这是预期行为。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

# ---------- 常量 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = _REPO_ROOT / "context" / "team" / "engineering-spec" / "task-frontmatter-schema.yaml"

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
    """读 task-frontmatter-schema.yaml 并断言 L1 schema_version == "1.0"。

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
            "schema 文件可能被破坏或与当前 check_task_frontmatter.py 不匹配"
        )
    return schema


def _load_task_frontmatter(path: Path) -> dict[str, Any]:
    """解析 task.md 的 YAML frontmatter（--- 块）。

    frontmatter 规则：
      - 文件首行必须是 '---'（否则视为无 frontmatter）
      - 必须有对应的 '---' 关闭行
      - 中间内容用 yaml.safe_load 解析
      - 解析异常 / 顶层非 dict → exit 1

    Args:
        path: task.md 文件绝对路径。

    Returns:
        frontmatter dict（顶层保证是 dict）。

    Side effect:
        校验失败时 print 到 stderr 并 sys.exit(1)。
    """
    if not path.exists():
        print(f"错误：task.md 文件不存在：{path}", file=sys.stderr)
        sys.exit(1)

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"错误：task.md 文件读取失败：{exc}", file=sys.stderr)
        sys.exit(1)

    lines = content.splitlines()
    # 首行必须是 '---'；否则视为无 frontmatter，报 schema_version 必填
    if not lines or lines[0].strip() != "---":
        print(
            f"错误：{path} 首行不是 '---'，无法读取 frontmatter；"
            "字段 schema_version 必填，当前缺失",
            file=sys.stderr,
        )
        sys.exit(1)

    # 寻找结束 '---'（从第二行起）
    end_idx: Optional[int] = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        print(
            f"错误：{path} 没有找到 frontmatter 结束标记 '---'；"
            "字段 schema_version 必填，当前缺失",
            file=sys.stderr,
        )
        sys.exit(1)

    frontmatter_text = "\n".join(lines[1:end_idx])
    try:
        data = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        print(f"错误：{path} frontmatter YAML 解析失败：{exc}", file=sys.stderr)
        sys.exit(1)

    if data is None:
        # 空 frontmatter 视为空 dict（后续必填校验会报字段缺失）
        return {}

    if not isinstance(data, dict):
        print(
            f"错误：{path} frontmatter 顶层不是 mapping，实际类型：{type(data).__name__}",
            file=sys.stderr,
        )
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


def _check_schema_version(
    data: dict[str, Any], report: _ErrorReport, file_label: str
) -> None:
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
            f"迁移脚本：scripts/lib/migrate_task_frontmatter_{sv}_to_{max(SUPPORTED_VERSIONS)}.py"
        )


def _check_required_fields(
    data: dict[str, Any], schema: dict[str, Any], report: _ErrorReport, file_label: str
) -> None:
    """校验 required_fields 列表中每个字段必须存在。

    schema_version 单独在 _check_schema_version 处理，此处跳过。
    """
    required = schema.get("required_fields", []) or []
    non_schema_version = [f for f in required if f != "schema_version"]
    for field_name in non_schema_version:
        if field_name not in data:
            report.add(f"字段 {field_name} 必填，当前缺失")


def _check_format_fields(
    data: dict[str, Any], schema: dict[str, Any], report: _ErrorReport, file_label: str
) -> None:
    """校验顶层 format 字段值的格式（regex）。

    schema_version 格式在 _check_schema_version 中已处理，此处跳过。
    depends_on_item 是列表元素格式规则，由 _check_depends_on 单独处理。
    """
    fmt_rules = schema.get("format", {}) or {}
    skip_keys = {"schema_version", "depends_on_item"}
    for field_name, rule in fmt_rules.items():
        if field_name in skip_keys:
            continue
        value = data.get(field_name)
        if value is None or value == "":
            continue  # 空值由必填规则处理
        if isinstance(rule, str):
            if not isinstance(value, str) or not re.fullmatch(rule, value):
                report.add(f"字段 {field_name} 值 {value!r} 不符合正则 {rule}")


def _check_enums(
    data: dict[str, Any], schema: dict[str, Any], report: _ErrorReport, file_label: str
) -> None:
    """校验 enums 定义的字段枚举值。"""
    enums = schema.get("enums", {}) or {}
    for field_name, allowed in enums.items():
        value = data.get(field_name)
        if value is None:
            continue  # 缺失由必填规则处理
        if value not in allowed:
            report.add(
                f"字段 {field_name} 值 {value!r} 不在枚举 {allowed} 内"
            )


def _check_depends_on(
    data: dict[str, Any], schema: dict[str, Any], report: _ErrorReport, file_label: str
) -> None:
    """校验 depends_on 字段：必须是列表，元素格式符合 depends_on_item regex。"""
    depends_on = data.get("depends_on")
    if depends_on is None:
        return  # 缺失由必填规则处理

    if not isinstance(depends_on, list):
        report.add(f"字段 depends_on 必须是列表，实际类型：{type(depends_on).__name__}")
        return

    fmt_rules = schema.get("format", {}) or {}
    item_rule = fmt_rules.get("depends_on_item")
    if not item_rule:
        return

    for j, item in enumerate(depends_on):
        if not isinstance(item, str) or not re.fullmatch(item_rule, item):
            report.add(
                f"字段 depends_on[{j}] 值 {item!r} 不符合正则 {item_rule}"
            )


def _check_list_fields(
    data: dict[str, Any], report: _ErrorReport, file_label: str
) -> None:
    """校验 list 类型字段：touches / depends_on 必须是 list（depends_on 单独 format 校验）。"""
    list_fields = {"touches", "depends_on"}
    for field_name in list_fields:
        val = data.get(field_name)
        if val is not None and not isinstance(val, list):
            report.add(
                f"字段 {field_name} 必须是列表，实际类型：{type(val).__name__}"
            )


def validate(
    data: dict[str, Any], schema: dict[str, Any], file_label: str
) -> _ErrorReport:
    """对 task.md frontmatter data 执行完整校验管道，返回错误报告。

    校验时序（detailed-design.md §4.3）：
      [1] schema_version（L2 双层）
      [2] required_fields（顶层）
      [3] format（顶层字段 regex，含 feature_id）
      [4] enums（status / complexity）
      [5] depends_on（list 类型 + 元素 format）
      [6] list_fields 类型校验（touches）

    Args:
        data: task.md frontmatter 解析后的 dict，须经过 `_load_task_frontmatter()` 校验。
        schema: `_load_schema()` 返回值，顶层 schema_version 已通过 L1 断言。
        file_label: 仅用于错误消息标签，通常传 str(task_path)。

    Returns:
        _ErrorReport 实例；report.has_errors 为 True 时表示存在校验错误。
    """
    report = _ErrorReport()
    _check_schema_version(data, report, file_label)
    _check_required_fields(data, schema, report, file_label)
    _check_format_fields(data, schema, report, file_label)
    _check_enums(data, schema, report, file_label)
    _check_depends_on(data, schema, report, file_label)
    _check_list_fields(data, report, file_label)
    return report


# ---------- CLI 入口 ----------

def main() -> int:
    """CLI 入口：exit 0 OK / exit 1 数据违规 / exit 2 schema 损坏。"""
    if len(sys.argv) != 2:
        print(
            "用法：python3 scripts/lib/check_task_frontmatter.py <task.md 路径>",
            file=sys.stderr,
        )
        sys.exit(2)

    task_path = Path(sys.argv[1])
    try:
        schema = _load_schema()
    except SchemaLoadError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(2)

    # _load_task_frontmatter 失败时内部 exit 1
    data = _load_task_frontmatter(task_path)

    file_label = str(task_path)
    report = validate(data, schema, file_label)

    if report.has_errors:
        report.print_all(file_label)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
