"""artifact 节点执行器（spec §8 5 lego 中的 ④ 后置文件校验）。

输入：节点的 `artifact:` 子结构（已被 substitute_vars 替换变量），形如：
    {
      "must_exist": ["path/to/file.md", ...],
      "must_not_exist": ["path/to/forbidden", ...],
      "schema_check": [{"script": "scripts/lib/check_meta.py",
                         "args": ["path/to/meta.yaml"],
                         "expected_exit_code": 0}],
      "must_contain_sections": [{"file": "...", "sections": ["A", "B"]}],
      "must_match_regex": [{"file": "...", "regex": "..."}]
    }

输出：exit code（0 = 全部通过；1 = 至少一项失败）+ 失败明细到 stderr。

CLI 用法：
    python3 scripts/lib/run_artifact_checks.py <artifact-spec.json> [--cwd <dir>]

设计原则：
- 子进程隔离：schema_check 跑外部脚本时，按 expected_exit_code 比对；不假设具体脚本行为。
- 不读 yaml：caller（workflow-engine）已经把 yaml 节点的 artifact 字段提取出来，
  并把变量替换好后写到一个临时 JSON 文件，再 invoke 本脚本。这样保持职责单一。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def _check_must_exist(spec: list[Any], cwd: Path) -> list[str]:
    failures: list[str] = []
    for entry in spec or []:
        if not isinstance(entry, str):
            failures.append(f"must_exist 项非字符串：{entry!r}")
            continue
        path = (cwd / entry).resolve() if not Path(entry).is_absolute() else Path(entry)
        if not path.exists():
            failures.append(f"must_exist 失败：{entry} 不存在")
    return failures


def _check_must_not_exist(spec: list[Any], cwd: Path) -> list[str]:
    failures: list[str] = []
    for entry in spec or []:
        if not isinstance(entry, str):
            failures.append(f"must_not_exist 项非字符串：{entry!r}")
            continue
        path = (cwd / entry).resolve() if not Path(entry).is_absolute() else Path(entry)
        if path.exists():
            failures.append(f"must_not_exist 失败：{entry} 不应存在但存在")
    return failures


def _check_schema(spec: list[Any], cwd: Path) -> list[str]:
    """schema_check 子进程调用。每项必须含 script + 可选 args + expected_exit_code（默认 0）。"""
    failures: list[str] = []
    for entry in spec or []:
        if not isinstance(entry, dict):
            failures.append(f"schema_check 项必须是对象：{entry!r}")
            continue
        script = entry.get("script")
        if not script:
            failures.append("schema_check 项缺 script 字段")
            continue
        args = entry.get("args") or []
        expected = entry.get("expected_exit_code", 0)
        cmd = [sys.executable, str(script), *(str(a) for a in args)]
        try:
            proc = subprocess.run(
                cmd, cwd=str(cwd), capture_output=True, text=True, timeout=120
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(f"schema_check 调用失败：{script} | {exc}")
            continue
        if proc.returncode != expected:
            tail = (proc.stderr or proc.stdout or "").splitlines()[-3:]
            failures.append(
                f"schema_check 失败：{script} 期望 exit={expected} 实际 exit={proc.returncode}"
                + (f"\n  > {chr(10).join(tail)}" if tail else "")
            )
    return failures


def _check_sections(spec: list[Any], cwd: Path) -> list[str]:
    """must_contain_sections 校验：file 内容含全部 section 标题。"""
    failures: list[str] = []
    for entry in spec or []:
        if not isinstance(entry, dict):
            failures.append(f"must_contain_sections 项必须是对象：{entry!r}")
            continue
        file_ref = entry.get("file")
        sections = entry.get("sections") or []
        if not file_ref:
            failures.append("must_contain_sections 项缺 file 字段")
            continue
        path = (cwd / file_ref).resolve() if not Path(file_ref).is_absolute() else Path(file_ref)
        if not path.exists():
            failures.append(f"must_contain_sections 失败：{file_ref} 不存在")
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(f"must_contain_sections 读取 {file_ref} 失败：{exc}")
            continue
        for section in sections:
            if section not in content:
                failures.append(
                    f"must_contain_sections 失败：{file_ref} 缺 section {section!r}"
                )
    return failures


def _check_regex(spec: list[Any], cwd: Path) -> list[str]:
    """must_match_regex 校验：file 内容匹配每条 regex。"""
    failures: list[str] = []
    for entry in spec or []:
        if not isinstance(entry, dict):
            failures.append(f"must_match_regex 项必须是对象：{entry!r}")
            continue
        file_ref = entry.get("file")
        regex = entry.get("regex")
        if not file_ref or not regex:
            failures.append("must_match_regex 项缺 file 或 regex")
            continue
        path = (cwd / file_ref).resolve() if not Path(file_ref).is_absolute() else Path(file_ref)
        if not path.exists():
            failures.append(f"must_match_regex 失败：{file_ref} 不存在")
            continue
        try:
            content = path.read_text(encoding="utf-8")
            pattern = re.compile(regex)
        except (OSError, re.error) as exc:
            failures.append(f"must_match_regex 失败：{file_ref} | {exc}")
            continue
        if not pattern.search(content):
            failures.append(f"must_match_regex 失败：{file_ref} 不匹配 {regex!r}")
    return failures


def run_artifact_checks(spec: dict[str, Any], cwd: Path | None = None) -> list[str]:
    """主入口：跑 5 类校验并汇总失败明细。

    返回：失败描述列表（空 = 全过）。
    """
    if not isinstance(spec, dict):
        return [f"artifact spec 必须是 mapping，实际 {type(spec).__name__}"]
    work_dir = cwd or Path.cwd()
    failures: list[str] = []
    failures.extend(_check_must_exist(spec.get("must_exist") or [], work_dir))
    failures.extend(_check_must_not_exist(spec.get("must_not_exist") or [], work_dir))
    failures.extend(_check_schema(spec.get("schema_check") or [], work_dir))
    failures.extend(_check_sections(spec.get("must_contain_sections") or [], work_dir))
    failures.extend(_check_regex(spec.get("must_match_regex") or [], work_dir))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Run artifact node checks.")
    parser.add_argument("spec_file", help="artifact spec JSON 文件路径")
    parser.add_argument("--cwd", default=None, help="校验 cwd（默认当前进程目录）")
    args = parser.parse_args()

    try:
        with open(args.spec_file, "r", encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"artifact spec 加载失败：{exc}", file=sys.stderr)
        return 2

    cwd = Path(args.cwd).resolve() if args.cwd else None
    failures = run_artifact_checks(spec, cwd=cwd)
    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
