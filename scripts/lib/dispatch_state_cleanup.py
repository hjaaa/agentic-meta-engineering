"""派发状态清理 CLI（F-004 / detail-design §3.4）。

用途：
  - feature 完成（receipt.json 写完）后清理 .dispatch-state.json.current_feature
  - /requirement:rollback 命令调用时同步清理

行为：
  - 内部调 dispatch_state.clear_state(req_dir)
  - 幂等执行（重复调用安全；已 idle 态再调一次结果等价）

退出码：
  0 — 清理成功（含幂等场景）
  1 — req_dir 不存在 / 不是目录 / 无写权限等

CLI：
  python3 scripts/lib/dispatch_state_cleanup.py --req-dir requirements/REQ-2026-008
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 把 repo root 加到 sys.path，便于以脚本方式直接执行
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.lib import dispatch_state  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="清理 requirements/<id>/.dispatch-state.json 的 current_feature 字段"
    )
    parser.add_argument(
        "--req-dir",
        required=True,
        type=Path,
        help="需求根目录路径，例如 requirements/REQ-2026-008",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口；幂等清理。

    退出码语义：
      0 = 成功（含幂等成功）
      1 = req_dir 不存在 / 非目录 / 锁 timeout / 写失败等可恢复错误
    """
    args = _parse_args(argv)
    req_dir: Path = args.req_dir

    if not req_dir.exists():
        print(f"错误：req_dir 不存在：{req_dir}", file=sys.stderr)
        return 1
    if not req_dir.is_dir():
        print(f"错误：req_dir 不是目录：{req_dir}", file=sys.stderr)
        return 1

    try:
        dispatch_state.clear_state(req_dir)
    except TimeoutError as exc:
        print(f"错误：取锁 timeout：{exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"错误：状态文件格式损坏：{exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"错误：写状态文件失败：{exc}", file=sys.stderr)
        return 1

    print(f"OK: 已清理 {req_dir}/{dispatch_state.STATE_FILE_NAME} 的 current_feature")
    return 0


if __name__ == "__main__":
    sys.exit(main())
