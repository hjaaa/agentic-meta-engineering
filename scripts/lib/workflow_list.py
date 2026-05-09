"""workflow list 命令入口（F-005）。

/workflow:list [--filter=<expr>]

扫 requirements/* + runs/*，过滤并表格输出。

详细设计 §1.2.5。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT  # noqa: E402
from run_state import RunState, read_events  # noqa: E402

_FILTER_FIELDS = {"phase", "state", "template", "requirement_id", "parent_run_id"}


def _load_run_entry(run_dir: Path) -> dict[str, Any] | None:
    """读取 run 的 meta.yaml（或 run-state.jsonl 推断）。

    返回：run entry dict，或 None（目录损坏 / 无效）
    """
    meta_path = run_dir / "meta.yaml"
    jsonl_path = run_dir / "run-state.jsonl"

    # 从 jsonl 重建状态
    if jsonl_path.exists():
        events, warnings = read_events(jsonl_path)
        run_state = RunState.rebuild(events, run_id=run_dir.name)
    else:
        run_state = None

    entry: dict[str, Any] = {
        "run_id": run_dir.name,
        "template": "",
        "state": run_state.state if run_state else "unknown",
        "phase": "",
        "current_node": run_state.current_node if run_state else "",
        "parent_run_id": "",
    }

    # 读 meta.yaml 补充模板名等
    if meta_path.exists():
        try:
            import yaml  # type: ignore
            with meta_path.open("r", encoding="utf-8") as fh:
                meta = yaml.safe_load(fh) or {}
        except yaml.YAMLError as exc:
            # yaml 解析失败 → 尝试 json fallback，并输出 WARN
            print(f"WARN: meta 解析失败（yaml） {run_dir.name}: {exc}", file=sys.stderr)
            try:
                import json
                with meta_path.open("r", encoding="utf-8") as fh:
                    meta = json.load(fh)
            except (json.JSONDecodeError, Exception) as exc2:
                print(f"WARN: meta 解析失败（json） {run_dir.name}: {exc2}", file=sys.stderr)
                meta = {}
        except Exception as exc:
            # 非 yaml 解析错误（IO 等）→ 尝试 json fallback
            try:
                import json
                with meta_path.open("r", encoding="utf-8") as fh:
                    meta = json.load(fh)
            except (json.JSONDecodeError, Exception) as exc2:
                print(f"WARN: meta 解析失败 {run_dir.name}: yaml={exc} json={exc2}", file=sys.stderr)
                meta = {}
        entry["template"] = meta.get("template", "")
        entry["phase"] = meta.get("phase", "")
        entry["parent_run_id"] = meta.get("parent_run_id", "")

    return entry


def _apply_filter(entries: list[dict[str, Any]], filter_expr: str) -> list[dict[str, Any]] | None:
    """应用过滤表达式，返回过滤后列表；语法错 → 返回 None。

    支持：field=value / field!=value / field contains value
    """
    expr = filter_expr.strip()
    # 尝试解析
    for op in (" contains ", "!=", "="):
        if op in expr:
            idx = expr.index(op)
            field = expr[:idx].strip()
            value = expr[idx + len(op):].strip()
            if field not in _FILTER_FIELDS:
                return None  # 语法错

            result = []
            for e in entries:
                field_val = str(e.get(field, ""))
                if op == "=":
                    if field_val == value:
                        result.append(e)
                elif op == "!=":
                    if field_val != value:
                        result.append(e)
                elif op == " contains ":
                    if value in field_val:
                        result.append(e)
            return result

    return None  # 无法解析


def main(args: list[str], repo_root: Path | None = None) -> int:
    """list 命令主入口。

    参数：
        args      — [--filter=expr?]（可选）
        repo_root — 注入 repo 根路径（测试用）

    返回：exit code（0 成功，2 filter 语法错）
    """
    root = repo_root or REPO_ROOT

    filter_expr: str | None = None
    for arg in args:
        if arg.startswith("--filter="):
            filter_expr = arg[len("--filter="):]

    # 扫所有 run（D-002 双轨期）
    entries: list[dict] = []
    for base_dir in [root / "requirements", root / "runs"]:
        if not base_dir.is_dir():
            continue
        for run_dir in sorted(base_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            # 跳过非 run 目录（无 jsonl 也无 meta.yaml）
            if not (run_dir / "run-state.jsonl").exists() and not (run_dir / "meta.yaml").exists():
                continue
            entry = _load_run_entry(run_dir)
            if entry:
                entries.append(entry)

    # 应用过滤
    if filter_expr:
        filtered = _apply_filter(entries, filter_expr)
        if filtered is None:
            print(
                f"ERROR [filter 语法错]: {filter_expr!r}\n"
                f"支持字段：{', '.join(sorted(_FILTER_FIELDS))}\n"
                f"操作符：= / != / contains\n"
                f"示例：--filter=state=paused",
                file=sys.stderr,
            )
            # exit 1：业务参数错；exit 2 保留为 fail-closed 专属（非 tty）
            return 1
        entries = filtered

    if not entries:
        print("(无 workflow run)")
        return 0

    # 表格输出
    headers = ["run_id", "template", "state", "phase", "current_node", "parent"]
    _field_map = {"run_id": "run_id", "template": "template", "state": "state",
                  "phase": "phase", "current_node": "current_node", "parent": "parent_run_id"}
    col_widths = [
        max(len(h), max(len(str(e.get(_field_map.get(h, h)) or "")) for e in entries))
        for h in headers
    ]

    def fmt_row(vals: list[str]) -> str:
        return "  ".join(v.ljust(w) for v, w in zip(vals, col_widths))

    print(fmt_row(headers))
    print(fmt_row(["-" * w for w in col_widths]))
    for e in entries:
        row = [
            str(e.get("run_id") or ""),
            str(e.get("template") or ""),
            str(e.get("state") or ""),
            str(e.get("phase") or ""),
            str(e.get("current_node") or ""),
            str(e.get("parent_run_id") or ""),
        ]
        print(fmt_row(row))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
