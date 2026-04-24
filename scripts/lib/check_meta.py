"""meta.yaml 校验核心。

唯一事实源：context/team/engineering-spec/meta-schema.yaml
项目级白名单：context/project/<meta.project>/areas.yaml

用法：
  python3 scripts/lib/check_meta.py <path> [--strict]
  python3 scripts/lib/check_meta.py --all [--strict]

退出码见 common.py。
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from common import REPO_ROOT, Report, Severity, paint, rel

SCHEMA_PATH = REPO_ROOT / "context" / "team" / "engineering-spec" / "meta-schema.yaml"
REQUIREMENTS_DIR = REPO_ROOT / "requirements"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{rel(path)} 顶层不是 mapping")
    return data


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _check_datetime(value: Any) -> bool:
    """接受新格式（YYYY-MM-DD HH:MM:SS，Asia/Shanghai）和旧 ISO 8601（YYYY-MM-DDTHH:MM:SSZ，UTC）。

    PyYAML 会把 `2026-04-22 10:00:00` 或 `2026-04-22T10:00:00Z` 这类字面量自动解析为
    datetime 对象（分别是 naive 和 aware），视为合法。
    详见 context/team/engineering-spec/time-format.md。
    """
    if isinstance(value, datetime):
        return True
    if isinstance(value, str):
        try:
            datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            return True
        except ValueError:
            pass
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False
    return False


def _check_format(meta: dict[str, Any], schema: dict[str, Any], report: Report, file_label: str) -> None:
    fmt_rules = schema.get("format", {}) or {}
    for field, rule in fmt_rules.items():
        value = meta.get(field)
        if _is_empty(value):
            continue  # 空值由必填规则处理
        if rule in ("datetime", "iso8601"):
            # "iso8601" 保留兼容，等价 "datetime"；两者都接受新旧两种格式
            if not _check_datetime(value):
                report.add(
                    file_label,
                    Severity.ERROR,
                    "format",
                    f"字段 {field} 值 {value!r} 不符合时间格式（YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DDTHH:MM:SSZ）",
                )
        elif isinstance(rule, str) and rule.startswith("^"):
            if not isinstance(value, str) or not re.match(rule, value):
                report.add(file_label, Severity.ERROR, "format", f"字段 {field} 值 {value!r} 不符合正则 {rule}")


def _check_enums(meta: dict[str, Any], schema: dict[str, Any], report: Report, file_label: str) -> None:
    enums = schema.get("enums", {}) or {}
    for field, allowed in enums.items():
        value = meta.get(field)
        if _is_empty(value):
            continue
        if value not in allowed:
            report.add(
                file_label,
                Severity.ERROR,
                "enum",
                f"字段 {field} 值 {value!r} 不在枚举 {allowed} 内",
            )


def _check_required_fields(meta: dict[str, Any], schema: dict[str, Any], report: Report, file_label: str) -> None:
    required = schema.get("required_fields", {}) or {}
    # process 组：字段必须存在且非空
    for field in required.get("process", []):
        if field not in meta:
            report.add(file_label, Severity.ERROR, "missing", f"缺少流程组字段 {field}")
        elif _is_empty(meta.get(field)) and field not in {"services", "gates_passed", "pr_url", "pr_number"}:
            # services/gates_passed/pr_url/pr_number 允许为空（分别 [] / [] / "" / 0）
            report.add(file_label, Severity.ERROR, "empty", f"流程组字段 {field} 不能为空")
    # semantic 组：字段必须存在（允许空，由 conditional_required 按 phase 校验非空）
    for field in required.get("semantic", []):
        if field not in meta:
            report.add(file_label, Severity.ERROR, "missing", f"缺少语义组字段 {field}")


def _match_when(meta: dict[str, Any], when: dict[str, Any]) -> bool:
    for key, expected in when.items():
        if key == "phase_not":
            if meta.get("phase") in expected:
                return False
        elif key == "phase":
            if meta.get("phase") != expected:
                return False
        else:
            # 兜底：直接相等
            if meta.get(key) != expected:
                return False
    return True


def _check_conditional(meta: dict[str, Any], schema: dict[str, Any], report: Report, file_label: str) -> None:
    for rule in schema.get("conditional_required", []) or []:
        when = rule.get("when", {})
        if not _match_when(meta, when):
            continue
        for field in rule.get("non_empty", []):
            if _is_empty(meta.get(field)):
                report.add(
                    file_label,
                    Severity.ERROR,
                    "conditional",
                    f"phase={meta.get('phase')!r} 时字段 {field} 必须非空",
                )


def _check_project_scoped_enums(meta: dict[str, Any], schema: dict[str, Any], report: Report, file_label: str) -> None:
    """feature_area 必须在 context/project/<project>/areas.yaml 白名单内。

    若 phase=bootstrap 且 feature_area 为空，跳过（由 conditional 规则处理）。
    若 areas.yaml 不存在，输出 warning 而非 error（新项目可能未建）。
    """
    spec = (schema.get("project_scoped_enums") or {}).get("feature_area")
    if not spec:
        return
    value = meta.get("feature_area")
    if _is_empty(value):
        return
    project = meta.get("project")
    if _is_empty(project):
        report.add(file_label, Severity.ERROR, "project-scope", "feature_area 已填但 project 为空，无法校验白名单")
        return

    template = spec.get("source", "")
    areas_path = REPO_ROOT / template.format(project=project)
    key = spec.get("key", "areas")

    if not areas_path.exists():
        report.add(
            file_label,
            Severity.WARNING,
            "project-scope",
            f"项目白名单 {rel(areas_path)} 不存在，无法校验 feature_area={value!r}",
        )
        return

    try:
        data = _load_yaml(areas_path)
    except Exception as exc:  # noqa: BLE001
        report.add(file_label, Severity.ERROR, "project-scope", f"读 {rel(areas_path)} 失败: {exc}")
        return

    allowed = data.get(key, []) or []
    if value not in allowed:
        report.add(
            file_label,
            Severity.ERROR,
            "project-scope",
            f"feature_area={value!r} 不在 {rel(areas_path)} 白名单 {allowed}",
        )


def check_one(meta_path: Path, schema: dict[str, Any], report: Report) -> None:
    file_label = rel(meta_path)
    try:
        meta = _load_yaml(meta_path)
    except FileNotFoundError:
        report.add(file_label, Severity.ERROR, "io", "文件不存在")
        return
    except yaml.YAMLError as exc:
        report.add(file_label, Severity.ERROR, "yaml", f"YAML 解析失败: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        report.add(file_label, Severity.ERROR, "io", f"读文件失败: {exc}")
        return

    _check_required_fields(meta, schema, report, file_label)
    _check_enums(meta, schema, report, file_label)
    _check_format(meta, schema, report, file_label)
    _check_conditional(meta, schema, report, file_label)
    _check_project_scoped_enums(meta, schema, report, file_label)


def _discover_all_meta_files() -> list[Path]:
    if not REQUIREMENTS_DIR.exists():
        return []
    return sorted(REQUIREMENTS_DIR.glob("*/meta.yaml"))


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 requirements/<id>/meta.yaml 是否符合 meta-schema.yaml")
    parser.add_argument("path", nargs="?", help="单个 meta.yaml 路径（省略则需 --all）")
    parser.add_argument("--all", action="store_true", help="扫 requirements/*/meta.yaml")
    parser.add_argument("--strict", action="store_true", help="warning 也视为失败")
    args = parser.parse_args()

    if not args.all and not args.path:
        parser.error("必须提供 <path> 或 --all")
    if args.all and args.path:
        parser.error("--all 与 <path> 互斥")

    try:
        schema = _load_yaml(SCHEMA_PATH)
    except Exception as exc:  # noqa: BLE001
        print(paint(f"读取 schema {rel(SCHEMA_PATH)} 失败: {exc}", "red"), file=sys.stderr)
        return 2

    targets: list[Path]
    if args.all:
        targets = _discover_all_meta_files()
        if not targets:
            print(paint("requirements/ 下无 meta.yaml，无需校验", "cyan"))
            return 0
    else:
        targets = [Path(args.path)]

    report = Report()
    for target in targets:
        check_one(target, schema, report)

    print(report.render())
    return report.exit_code(strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
