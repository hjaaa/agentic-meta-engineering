"""e2e 测试共享 fixture loader（pytest conftest）。

工具函数定义在 tests/e2e/fixtures/e2e_helpers.py（供测试文件直接 import）。
本文件只暴露 pytest fixture（供 @pytest.fixture 声明）。

设计依据：requirements/REQ-2026-009/artifacts/detailed-design.md §7.3.3
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# 把 scripts/lib 和 fixtures 目录加入 sys.path，让所有 e2e 测试能直接 import
if str(REPO_ROOT / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
if str(REPO_ROOT / "tests" / "e2e" / "fixtures") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tests" / "e2e" / "fixtures"))

# F1 fixture 路径见 e2e_helpers.F1_FIXTURE_DIR


# ============================================================================
# F-010 AC-05：mock_agent_dispatch fixture
# monkeypatch 替换 _dispatch_agent_node，返回预设 output 但走完整 main loop。
# ============================================================================

@pytest.fixture
def mock_agent_dispatch(monkeypatch: pytest.MonkeyPatch) -> Any:
    """mock _dispatch_agent_node，返回预设 output 但走完整 main loop。

    不调用真实 Claude API，不发起网络请求。
    与真实 _dispatch_agent_node 签名一致：(node, run_state, env, jsonl_path)。
    写入 node_completed 事件（真实 agent 节点落地后需要写此事件；stub 未写故此处补上）。
    yield 值为捕获的调用记录列表，供断言验证节点被触达。
    """
    from run_state import RunState, append_event
    from workflow_dispatcher import DispatchResult

    captured_calls: list[dict] = []

    def _fake_dispatch(
        node: dict, run_state: RunState, env: dict, jsonl_path: Path
    ) -> DispatchResult:
        captured_calls.append({
            "node_id": node["id"],
            "run_id": run_state.run_id,
            "env_keys": list(env.keys()),
        })
        # 优先使用节点内嵌的 mock_response，否则使用默认预设
        preset = node.get("mock_response", {"verdict": "approved", "score": 90})
        # 写 node_completed 事件（真实 agent 节点落地后需要写此事件）
        append_event(jsonl_path, {
            "type": "node_completed",
            "node_id": node["id"],
            "run_id": run_state.run_id,
            "data": {"output": preset},
        })
        return DispatchResult(outcome="completed", output=preset)

    monkeypatch.setattr("workflow_dispatcher._dispatch_agent_node", _fake_dispatch)
    yield captured_calls
