"""F-013 · workflow_dispatcher contract 透传测试（AC-10）。

覆盖 acceptance #5-7：
  #5  dispatcher skill 节点缺省 7 字段 → node_ready.data.external_action_contract 含 7 空缺省
  #6  dispatcher skill 节点 allowed_tools=['Read'] → node_ready.data.external_action_contract.allowed_tools == ['Read']
  #7  行为级断言：dispatcher 写 node_ready 后，save_node_result --kind=skill_result 写出的
      node_completed.data 不含 external_action_contract 字段

测试运行：
    python3 -m pytest tests/lib/test_dispatch_skill_contract.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

from run_state import RunState, append_event  # noqa: E402
from workflow_dispatcher import (  # noqa: E402
    _build_external_action_contract,
    _dispatch_agent_node,
    _dispatch_prompt_node,
    _dispatch_skill_node,
)

_SAVE_NODE_RESULT_PY = _REPO_ROOT / "scripts" / "lib" / "save_node_result.py"

# 7 缺省字段名与缺省值（§2.2.1）
_DEFAULT_CONTRACT = {
    "allowed_tools": [],
    "denied_tools": [],
    "mcp": [],
    "skills": [],
    "agents": [],
    "idle_timeout": None,
    "output_format": None,
}


# ============================================================================
# 公共 helper
# ============================================================================

@pytest.fixture
def tmp_jsonl(tmp_path: Path) -> Path:
    """临时 jsonl 路径（append_event 自动创建）。"""
    return tmp_path / "run-state.jsonl"


def _make_run_state() -> RunState:
    rs = RunState(run_id="REQ-2099-013")
    return rs


def _read_events(jsonl_path: Path) -> list[dict]:
    if not jsonl_path.exists():
        return []
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lines if l.strip()]


def _node_ready_event(events: list[dict]) -> dict | None:
    """返回第一条 type=node_ready 事件，无则 None。"""
    return next((e for e in events if e.get("type") == "node_ready"), None)


# ============================================================================
# _build_external_action_contract 单元测试
# ============================================================================

def test_build_contract_defaults_all_seven_fields() -> None:
    """节点无 7 字段时，contract 包含 7 缺省值。"""
    contract = _build_external_action_contract({})
    assert contract == _DEFAULT_CONTRACT, (
        f"缺省 contract 与期望不符，实际 {contract}"
    )


def test_build_contract_passes_through_allowed_tools() -> None:
    """allowed_tools 有值时，contract 中透传该值。"""
    node = {"id": "n1", "allowed_tools": ["Read", "Edit"]}
    contract = _build_external_action_contract(node)
    assert contract["allowed_tools"] == ["Read", "Edit"]


def test_build_contract_passes_through_output_format() -> None:
    """output_format 有值时，contract 中透传该值。"""
    node = {"id": "n1", "output_format": {"type": "json"}}
    contract = _build_external_action_contract(node)
    assert contract["output_format"] == {"type": "json"}


# ============================================================================
# acceptance #5：dispatcher skill 缺省 7 字段 → node_ready.data.external_action_contract 含 7 空缺省
# ============================================================================

def test_skill_node_default_contract_in_node_ready(tmp_jsonl: Path) -> None:
    """AC-10 acceptance #5：skill 节点无 7 字段 → node_ready.data.external_action_contract == 7 缺省。"""
    rs = _make_run_state()
    node = {"id": "skill-default", "skill": "my-skill"}
    result = _dispatch_skill_node(node, rs, {}, tmp_jsonl)

    assert result.outcome == "awaiting_claude_action", (
        f"skill 节点应返回 awaiting_claude_action，实际 {result.outcome!r}"
    )

    events = _read_events(tmp_jsonl)
    ready_evt = _node_ready_event(events)
    assert ready_evt is not None, "应写入 node_ready 事件"
    assert ready_evt["node_id"] == "skill-default"

    contract = ready_evt.get("data", {}).get("external_action_contract")
    assert contract is not None, "node_ready.data.external_action_contract 不应为 None"
    assert contract == _DEFAULT_CONTRACT, (
        f"缺省 contract 期望 {_DEFAULT_CONTRACT}，实际 {contract}"
    )


# ============================================================================
# acceptance #6：allowed_tools=['Read'] → node_ready.data.external_action_contract.allowed_tools == ['Read']
# ============================================================================

def test_skill_node_allowed_tools_propagated(tmp_jsonl: Path) -> None:
    """AC-10 acceptance #6：allowed_tools=['Read'] → node_ready.data.external_action_contract.allowed_tools == ['Read']。"""
    rs = _make_run_state()
    node = {"id": "skill-tools", "skill": "my-skill", "allowed_tools": ["Read"]}
    _dispatch_skill_node(node, rs, {}, tmp_jsonl)

    events = _read_events(tmp_jsonl)
    ready_evt = _node_ready_event(events)
    assert ready_evt is not None, "应写入 node_ready 事件"

    contract = ready_evt["data"]["external_action_contract"]
    assert contract["allowed_tools"] == ["Read"], (
        f"allowed_tools 应为 ['Read']，实际 {contract['allowed_tools']}"
    )
    # 其余 5 个列表字段应为空 list，idle_timeout/output_format 为 None
    assert contract["denied_tools"] == []
    assert contract["idle_timeout"] is None


# ============================================================================
# node_ready 内容断言：node_kind / skill / args 字段保留
# ============================================================================

def test_skill_node_ready_contains_skill_and_args(tmp_jsonl: Path) -> None:
    """node_ready.data 含 node_kind='skill' / skill / args 字段，不破坏既有结构。"""
    rs = _make_run_state()
    node = {"id": "skill-full", "skill": "req-skill", "args": {"key": "val"}}
    _dispatch_skill_node(node, rs, {}, tmp_jsonl)

    events = _read_events(tmp_jsonl)
    ready_evt = _node_ready_event(events)
    assert ready_evt is not None
    data = ready_evt["data"]
    assert data.get("node_kind") == "skill"
    assert data.get("skill") == "req-skill"
    assert "args" in data


# ============================================================================
# prompt 节点 contract 透传
# ============================================================================

def test_prompt_node_default_contract_in_node_ready(tmp_jsonl: Path, tmp_path: Path) -> None:
    """prompt 节点缺省 7 字段 → node_ready.data.external_action_contract == 7 缺省。"""
    rs = _make_run_state()
    node = {"id": "prompt-default", "prompt": "Hello $WORLD"}
    result = _dispatch_prompt_node(node, rs, {"WORLD": "earth"}, tmp_path, tmp_path, tmp_jsonl)

    assert result.outcome == "awaiting_claude_action", (
        f"prompt 节点应返回 awaiting_claude_action，实际 {result.outcome!r}"
    )

    events = _read_events(tmp_jsonl)
    ready_evt = _node_ready_event(events)
    assert ready_evt is not None, "应写入 node_ready 事件"
    assert ready_evt["data"].get("node_kind") == "prompt"

    contract = ready_evt["data"]["external_action_contract"]
    assert contract == _DEFAULT_CONTRACT, (
        f"prompt 节点缺省 contract 期望 {_DEFAULT_CONTRACT}，实际 {contract}"
    )


# ============================================================================
# agent 节点 contract 透传
# ============================================================================

def test_agent_node_default_contract_in_node_ready(tmp_jsonl: Path) -> None:
    """agent 节点缺省 7 字段 → node_ready.data.external_action_contract == 7 缺省。"""
    node = {"id": "agent-default", "agent": "my-agent"}
    result = _dispatch_agent_node(node, _make_run_state(), {}, tmp_jsonl)

    assert result.outcome == "awaiting_claude_action", (
        f"agent 节点应返回 awaiting_claude_action，实际 {result.outcome!r}"
    )

    events = _read_events(tmp_jsonl)
    ready_evt = _node_ready_event(events)
    assert ready_evt is not None, "应写入 node_ready 事件"
    assert ready_evt["data"].get("node_kind") == "agent"

    contract = ready_evt["data"]["external_action_contract"]
    assert contract == _DEFAULT_CONTRACT, (
        f"agent 节点缺省 contract 期望 {_DEFAULT_CONTRACT}，实际 {contract}"
    )


def test_agent_node_allowed_tools_propagated(tmp_jsonl: Path) -> None:
    """agent 节点 allowed_tools 透传到 node_ready.data.external_action_contract。"""
    node = {"id": "agent-tools", "agent": "my-agent", "allowed_tools": ["Bash"]}
    _dispatch_agent_node(node, _make_run_state(), {}, tmp_jsonl)

    events = _read_events(tmp_jsonl)
    ready_evt = _node_ready_event(events)
    assert ready_evt is not None
    contract = ready_evt["data"]["external_action_contract"]
    assert contract["allowed_tools"] == ["Bash"]


# ============================================================================
# acceptance #7：行为级断言——save_node_result 写出的 node_completed.data 不含 external_action_contract
# ============================================================================

def _make_run_dir_for_save(tmp_path: Path, run_id: str) -> tuple[Path, Path]:
    """构造 save_node_result 期望的 run 目录结构，返回 (run_dir, jsonl_path)。"""
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    jsonl_path = run_dir / "run-state.jsonl"
    return run_dir, jsonl_path


def test_save_node_result_node_completed_excludes_external_action_contract(
    tmp_path: Path,
) -> None:
    """AC-10 acceptance #7：dispatcher 写 node_ready（含 external_action_contract）后，
    save_node_result --kind=skill_result 写出的 node_completed.data 不含 external_action_contract。

    验证 save_node_result.py 不会消费 / 透传 external_action_contract 字段。
    """
    run_id = "REQ-2099-013"
    node_id = "skill-ac7"
    run_dir, jsonl_path = _make_run_dir_for_save(tmp_path, run_id)

    # 1. 写 workflow_started（RunState.rebuild 需要）
    append_event(jsonl_path, {"type": "workflow_started", "run_id": run_id})

    # 2. 写 node_started（dispatch_node 入口会写；此处手动补以保持完整事件序列）
    append_event(jsonl_path, {"type": "node_started", "node_id": node_id, "run_id": run_id})

    # 3. 调 _dispatch_skill_node 写 node_ready（含 external_action_contract）
    rs = RunState(run_id=run_id)
    node = {"id": node_id, "skill": "my-skill", "allowed_tools": ["Read"]}
    _dispatch_skill_node(node, rs, {}, jsonl_path)

    # 4. 确认 node_ready 被写入且含 external_action_contract
    events_before = [json.loads(l) for l in jsonl_path.read_text().splitlines() if l.strip()]
    ready_events = [e for e in events_before if e.get("type") == "node_ready"]
    assert len(ready_events) == 1, "应有 1 条 node_ready 事件"
    assert "external_action_contract" in ready_events[0]["data"]

    # 5. 调 save_node_result.py --kind=skill_result（子进程模拟真实使用场景）
    output_json = json.dumps({"verdict": "ok"})
    proc = subprocess.run(
        [sys.executable, str(_SAVE_NODE_RESULT_PY),
         f"--repo-root={tmp_path}",
         "--run", run_id,
         "--node", node_id,
         "--kind", "skill_result",
         "--output", output_json],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"save_node_result 应 exit 0，实际 {proc.returncode}\nstderr={proc.stderr}"
    )

    # 6. 读 node_completed 事件，断言 data 不含 external_action_contract
    events_after = [json.loads(l) for l in jsonl_path.read_text().splitlines() if l.strip()]
    completed_events = [e for e in events_after if e.get("type") == "node_completed"]
    assert len(completed_events) == 1, (
        f"应有 1 条 node_completed 事件，实际 {len(completed_events)}"
    )
    completed_data = completed_events[0].get("data", {})
    assert "external_action_contract" not in completed_data, (
        f"node_completed.data 不应含 external_action_contract 字段，实际 {completed_data}"
    )
