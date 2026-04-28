"""门禁状态快照与恢复（事务化基础设施）。

设计来源：requirements/REQ-2026-002/artifacts/detailed-design.md §2.2 + §3.1。

职责：
  1. stash_state：执行前对受保护文件（meta.yaml）做 .bak 备份
  2. restore_state：fail 路径恢复 .bak 后清理（语义：失败回退）
  3. cleanup_snapshots：全 pass 路径只清理 .bak，不恢复（语义：成功收尾）

F-012 round-2 拆出：从 run.py 抽出，run.py 通过 re-export 保持向后兼容。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_ROOT.parent.parent


def stash_state(ctx) -> dict[str, Path]:
    """对受保护文件做快照备份（本 PR 仅备份 meta.yaml；F-002 起按 plugin 写态扩展）。

    requirement_id 在 build_context 阶段已校验，此处直接使用。
    """
    snapshots: dict[str, Path] = {}
    if ctx.requirement_id:
        meta_path = _REPO_ROOT / "requirements" / ctx.requirement_id / "meta.yaml"
        if meta_path.exists():
            backup = meta_path.with_suffix(".yaml.bak")
            shutil.copy2(meta_path, backup)
            snapshots[str(meta_path)] = backup
    return snapshots


def restore_state(ctx, snapshots: dict[str, Path]) -> None:
    """fail 路径恢复快照；restore 后清理 .bak。"""
    for original, backup in snapshots.items():
        try:
            shutil.copy2(backup, original)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR restore_state failed: {original}: {exc}", file=sys.stderr)
        try:
            backup.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            print(
                f"WARNING restore_state .bak 清理失败 backup={backup}: {exc}",
                file=sys.stderr,
            )


def cleanup_snapshots(snapshots: dict[str, Path]) -> None:
    """F-13 carry-over：全 pass 路径下清理 .bak 备份（避免污染工作区）。

    与 restore_state 区别：本函数只清理，不恢复。
    每个 backup 单独处理；失败打 WARNING 不静默（来源：F-002 review-003 经验）。
    """
    for original, backup in snapshots.items():
        try:
            backup.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            print(
                f"WARNING gate-cleanup-snapshot 失败 original={original} backup={backup}: {exc}",
                file=sys.stderr,
            )
