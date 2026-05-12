"""test_workflow_commands_*.py 共享辅助函数。

命名以 _ 开头，pytest discovery 不会把此文件当测试模块收集。
三个拆分文件均从此处 import，避免重复定义。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------- 路径注入（辅助模块也需要保证 sys.path 正确）----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import append_event  # noqa: E402


def _make_run_dir(repo: Path, run_id: str, initial_state: str = "running") -> Path:
    """创建测试用 run 目录 + jsonl，初始化到指定状态。

    返回 run_dir（路径已存在）。支持的 initial_state：
    running / paused / failed / completed / approval_pending / cancel_requested / cancelled。
    """
    run_dir = repo / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = run_dir / "run-state.jsonl"

    # 写 workflow_started 事件
    append_event(jsonl_path, {
        "type": "workflow_started",
        "run_id": run_id,
        "data": {"workflow_name": "test-template", "arguments": ""},
    })

    # 根据 initial_state 补充事件
    if initial_state == "paused":
        append_event(jsonl_path, {"type": "workflow_paused", "run_id": run_id})
    elif initial_state == "failed":
        append_event(jsonl_path, {"type": "workflow_failed", "run_id": run_id})
    elif initial_state == "completed":
        append_event(jsonl_path, {"type": "workflow_completed", "run_id": run_id})
    elif initial_state == "approval_pending":
        append_event(jsonl_path, {
            "type": "approval_pending",
            "run_id": run_id,
            "node_id": "approval-node",
        })
    elif initial_state == "cancel_requested":
        append_event(jsonl_path, {"type": "cancel_requested", "run_id": run_id})
    elif initial_state == "cancelled":
        append_event(jsonl_path, {"type": "workflow_cancelled", "run_id": run_id})

    return run_dir


def _patch_git_branch(run_id: str):
    """patch git branch 推断为 feat/req-<run_id>。"""
    mock_result = MagicMock()
    mock_result.stdout = f"feat/req-{run_id}\n"
    return patch("subprocess.run", return_value=mock_result)
