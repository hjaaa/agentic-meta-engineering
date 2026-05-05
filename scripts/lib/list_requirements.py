"""需求索引列表：扫 requirements/*/meta.yaml 并按阶段/时间过滤。

用法：
  python3 scripts/lib/list_requirements.py [--all|--phase <phase>]

参数：
  --all           显示全部需求（包括 phase=completed）
  --phase <p>     仅显示指定阶段的需求

互斥规则：
  --all 与 --phase 不能同时使用。同时传入退出码为 1。

默认行为：
  隐藏 phase=completed 的需求；其余全显示。

返回值（库函数）：
  list[dict]，每条含 id/title/phase/branch/created_at/phase_label（中文名）
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from common import REPO_ROOT, paint, rel

REQUIREMENTS_DIR = REPO_ROOT / "requirements"

# Asia/Shanghai 时区常量——naive 时间戳排序前注入此 offset 防 TypeError
_CST = timezone(timedelta(hours=8))

# phase 中文名映射
PHASE_LABELS = {
    "bootstrap": "初始化",
    "definition": "需求定义",
    "tech-research": "技术预研",
    "outline-design": "概要设计",
    "detail-design": "详细设计",
    "task-planning": "任务规划",
    "development": "开发实施",
    "testing": "测试验收",
    "completed": "完成",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    """加载 YAML 文件，失败则抛异常含文件名。"""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"{rel(path)}: 顶层不是 mapping")
        return data
    except yaml.YAMLError as exc:
        raise ValueError(f"{rel(path)}: YAML 解析失败 — {exc}") from exc
    except Exception as exc:
        raise ValueError(f"{rel(path)}: 读文件失败 — {exc}") from exc


def _parse_created_at(value: Any) -> datetime:
    """解析 created_at，支持新旧格式。返回 **tzaware** datetime 便于排序。

    支持格式：
      - YYYY-MM-DD HH:MM:SS（新格式，无 offset，按 Asia/Shanghai 注入）
      - YYYY-MM-DDTHH:MM:SSZ（旧 ISO 8601，UTC）
      - YYYY-MM-DDTHH:MM:SS+HH:MM / -HH:MM（带 offset 的 ISO 8601）

    硬约束：返回值一定带 tzinfo——naive 与 aware 混在同一列表会让 list.sort
    抛 TypeError，导致 /requirement:list 整命令崩溃（codex P2 finding）。
    """
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=_CST)
    if isinstance(value, str):
        try:
            naive = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            return naive.replace(tzinfo=_CST)
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=_CST)
        except ValueError:
            pass
    raise ValueError(f"无法解析时间戳: {value!r}")


def list_requirements(
    *,
    all: bool = False,
    phase: str | None = None,
    requirements_dir: Path | None = None,
) -> list[dict]:
    """扫 requirements_dir/*/meta.yaml 并按过滤条件和 created_at 倒序返回。

    Args:
        all: 若 True，显示全部需求；若 False（默认），隐藏 phase=completed
        phase: 若指定，仅留该阶段的需求（与 all 互斥）
        requirements_dir: 需求目录，默认为 REPO_ROOT/requirements

    Returns:
        list[dict]，每条含 id/title/phase/branch/created_at/phase_label

    Raises:
        ValueError:
          - all=True 与 phase 同时指定
          - 扫目录或解析 YAML 时的 I/O 错误（含路径信息）
    """
    if all and phase is not None:
        raise ValueError("--all 与 --phase 互斥（mutually exclusive），不能同时使用")

    if requirements_dir is None:
        requirements_dir = REQUIREMENTS_DIR

    if not requirements_dir.exists():
        return []

    records: list[dict] = []

    # 扫 requirements/*/meta.yaml
    for meta_path in sorted(requirements_dir.glob("*/meta.yaml")):
        try:
            meta = _load_yaml(meta_path)
        except ValueError as exc:
            # 跳过解析失败的文件，输出警告
            print(
                paint(f"⚠️ 跳过: {exc}", "yellow"),
                file=sys.stderr,
            )
            continue

        req_id = meta.get("id", "")
        title = meta.get("title", "")
        req_phase = meta.get("phase", "")
        branch = meta.get("branch", "")
        created_at = meta.get("created_at", "")

        # 跳过缺少关键字段的条目
        if not req_id or not req_phase:
            continue

        # 应用过滤规则
        if not all and phase is None:
            # 默认行为：隐藏 completed
            if req_phase == "completed":
                continue
        elif phase is not None:
            # --phase 过滤：仅留指定阶段
            if req_phase != phase:
                continue
        # else: all=True，全部显示

        try:
            created_at_dt = _parse_created_at(created_at)
        except ValueError:
            # 时间戳解析失败，用 epoch 占位（排序用）；必须 tzaware 防 TypeError
            created_at_dt = datetime.min.replace(tzinfo=_CST)

        records.append({
            "id": req_id,
            "title": title,
            "phase": req_phase,
            "phase_label": PHASE_LABELS.get(req_phase, req_phase),
            "branch": branch,
            "created_at": str(created_at),
            "created_at_dt": created_at_dt,
        })

    # 按 created_at 倒序
    records.sort(key=lambda r: r["created_at_dt"], reverse=True)

    # 移除临时排序用字段
    for r in records:
        del r["created_at_dt"]

    return records


def _render_table(records: list[dict]) -> str:
    """渲染 Markdown 表格。"""
    if not records:
        return paint("当前无活跃需求", "cyan")

    lines = [
        "| ID | 标题 | 阶段 | 分支 | 创建时间 |",
        "|---|---|---|---|---|",
    ]
    for r in records:
        lines.append(
            f"| {r['id']} | {r['title']} | {r['phase_label']} | "
            f"{r['branch']} | {r['created_at'][:10]} |"
        )
    return "\n".join(lines)


def main() -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="列出所有需求的状态索引"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="显示全部需求，包括 phase=completed 的",
    )
    parser.add_argument(
        "--phase",
        type=str,
        help="仅显示指定阶段的需求",
    )
    args = parser.parse_args()

    try:
        records = list_requirements(all=args.all, phase=args.phase)
    except ValueError as exc:
        print(paint(f"❌ {exc}", "red"), file=sys.stderr)
        return 1

    print(_render_table(records))
    return 0


if __name__ == "__main__":
    sys.exit(main())
