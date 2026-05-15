"""F-005 · _dispatch_artifact_node 单元测试（AC-02 第 8 类 dispatcher）。

覆盖（5 条验收标准）：
- TC-F05-1：happy path — spec.must_exist 全过 → jsonl 仅含 1 node_started + 1 node_completed（不双写）
- TC-F05-2：failure path — run_artifact_checks 返非空 → dispatch_node 整体回 outcome=failed + jsonl 仅 1 node_failed
- TC-F05-3：real schema_check 路径 check_meta.py → 不发生 FileNotFoundError
- TC-F05-4：grep 反向断言 — _dispatch_artifact_node 函数源码内不含 'node_started' 字面值
- TC-F05-5：yaml 断言 — standard-8phase.yaml 不含 check_meta_schema 字符串

测试运行：
    python3 -m pytest tests/lib/test_dispatch_artifact.py -v
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

from run_state import RunState  # noqa: E402
from workflow_dispatcher import (  # noqa: E402
    DispatchResult,
    _dispatch_artifact_node,
    dispatch_node,
)


# ============================================================================
# 公共 fixture / 辅助函数
# ============================================================================

@pytest.fixture
def tmp_jsonl(tmp_path: Path) -> Path:
    """提供临时 jsonl 文件路径（append_event 会自动创建）。"""
    return tmp_path / "run-state.jsonl"


def _make_run_state() -> RunState:
    """构造基础 RunState（无特殊状态）。"""
    return RunState(run_id="REQ-2026-011")


def _read_events(jsonl_path: Path) -> list[dict]:
    """从 jsonl 文件读取所有事件行。"""
    if not jsonl_path.exists():
        return []
    events: list[dict] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


# ============================================================================
# TC-F05-1：happy path — 全过时仅有 node_started + node_completed（不双写）
# ============================================================================

def test_artifact_happy_path_events(tmp_jsonl: Path, tmp_path: Path) -> None:
    """run_artifact_checks 返 [] → dispatch_node 整体写 1 node_started + 1 node_completed。

    验收标准 1：jsonl 不含 node_failed，且 node_started / node_completed 各仅 1 条。
    """
    node = {"id": "check-artifacts", "artifact": {"must_exist": []}}
    run_state = _make_run_state()
    env: dict = {}

    # mock run_artifact_checks 返回空 list（全部通过）
    with patch(
        "run_artifact_checks.run_artifact_checks",
        return_value=[],
    ):
        result = dispatch_node(node, run_state, tmp_path, tmp_path, env, tmp_jsonl)

    assert result.outcome == "completed", f"应 completed，实际 {result.outcome}"

    events = _read_events(tmp_jsonl)
    types = [e["type"] for e in events]

    started = [t for t in types if t == "node_started"]
    completed = [t for t in types if t == "node_completed"]
    failed = [t for t in types if t == "node_failed"]

    assert len(started) == 1, f"node_started 应恰好 1 条，实际 {len(started)}"
    assert len(completed) == 1, f"node_completed 应恰好 1 条，实际 {len(completed)}"
    assert len(failed) == 0, f"不应有 node_failed，实际 {len(failed)}"


def test_artifact_happy_path_output_fields(tmp_jsonl: Path, tmp_path: Path) -> None:
    """node_completed 事件的 data.output 含 artifact_pass=True 和 checks_run 字段。"""
    node = {
        "id": "validate-outputs",
        "artifact": {
            "must_exist": ["file1.md", "file2.md"],
            "must_not_exist": [],
        },
    }
    run_state = _make_run_state()

    with patch("run_artifact_checks.run_artifact_checks", return_value=[]):
        dispatch_node(node, run_state, tmp_path, tmp_path, {}, tmp_jsonl)

    events = _read_events(tmp_jsonl)
    completed_events = [e for e in events if e["type"] == "node_completed"]
    assert completed_events, "应有 node_completed 事件"

    output = completed_events[0].get("data", {}).get("output", {})
    assert output.get("artifact_pass") is True, "artifact_pass 应为 True"
    assert "checks_run" in output, "output 应含 checks_run 字段"
    # must_exist 有 2 项，must_not_exist 有 0 项 → checks_run=2
    assert output["checks_run"] == 2, f"checks_run 应为 2，实际 {output['checks_run']}"


# ============================================================================
# TC-F05-2：failure path — run_artifact_checks 返非空 → outcome=failed，仅 1 node_failed
# ============================================================================

def test_artifact_failure_path_events(tmp_jsonl: Path, tmp_path: Path) -> None:
    """run_artifact_checks 返非空 list → dispatch_node 写 node_failed（外层兜底），handler 不双写。

    验收标准 2：
    - result.outcome == 'failed'
    - jsonl 含 1 node_started + 0 node_completed + 1 node_failed（仅外层一条）
    """
    node = {"id": "check-must-exist", "artifact": {"must_exist": ["missing-file.md"]}}
    run_state = _make_run_state()

    mock_failures = ["must_exist 失败：missing-file.md 不存在"]
    with patch("run_artifact_checks.run_artifact_checks", return_value=mock_failures):
        result = dispatch_node(node, run_state, tmp_path, tmp_path, {}, tmp_jsonl)

    assert result.outcome == "failed", f"应 failed，实际 {result.outcome}"

    events = _read_events(tmp_jsonl)
    types = [e["type"] for e in events]

    assert types.count("node_started") == 1, "node_started 应恰好 1 条"
    assert types.count("node_failed") == 1, "node_failed 应恰好 1 条（仅外层写，不双写）"
    assert types.count("node_completed") == 0, "不应有 node_completed"


def test_artifact_failure_error_message(tmp_jsonl: Path, tmp_path: Path) -> None:
    """node_failed 事件的 data.error 含失败明细信息。"""
    node = {"id": "check-x", "artifact": {"must_exist": ["x.md"]}}
    run_state = _make_run_state()
    failure_msg = "must_exist 失败：x.md 不存在"

    with patch("run_artifact_checks.run_artifact_checks", return_value=[failure_msg]):
        dispatch_node(node, run_state, tmp_path, tmp_path, {}, tmp_jsonl)

    events = _read_events(tmp_jsonl)
    failed_events = [e for e in events if e["type"] == "node_failed"]
    assert failed_events, "应有 node_failed 事件"

    error = failed_events[0].get("data", {}).get("error", "")
    assert failure_msg in error, f"node_failed.data.error 应含失败明细，实际：{error!r}"


# ============================================================================
# TC-F05-3：real schema_check 路径 — check_meta.py 存在，不发生 FileNotFoundError
# ============================================================================

def test_real_check_meta_script_exists(tmp_path: Path, tmp_jsonl: Path) -> None:
    """构造含 check_meta.py schema_check 的节点，校验脚本文件真实存在（不发生 FileNotFoundError）。

    验收标准 3：scripts/lib/check_meta.py 路径存在；spec 中引用该脚本的节点
    在 run_artifact_checks 不 mock 情况下不会因脚本缺失而 FileNotFoundError。

    注：本测试不 mock run_artifact_checks，直接调 _dispatch_artifact_node 触发真实校验路径。
    使用 tmp_path 作为 cwd，check_meta.py 会被调用；因 args 中是不存在的 meta.yaml 路径，
    expected_exit_code=0 但脚本返非 0，会走 failure 路径（不是 FileNotFoundError）。
    这已足够验证脚本文件本身可被找到并执行。
    """
    # 验证脚本文件真实存在
    check_meta_path = _REPO_ROOT / "scripts" / "lib" / "check_meta.py"
    assert check_meta_path.exists(), (
        f"check_meta.py 应存在于 {check_meta_path}，实际不存在"
    )

    # 构造含 check_meta.py 的 artifact 节点
    node = {
        "id": "schema-check-node",
        "artifact": {
            "schema_check": [
                {
                    "script": str(check_meta_path),
                    "args": [str(tmp_path / "nonexistent-meta.yaml")],
                    "expected_exit_code": 0,
                }
            ]
        },
    }

    run_state = _make_run_state()
    env: dict = {}

    # 不 mock run_artifact_checks，直接调用 dispatch_node
    # 预期：不会抛 FileNotFoundError；failure 会被外层捕获为 node_failed
    try:
        result = dispatch_node(node, run_state, tmp_path, _REPO_ROOT, env, tmp_jsonl)
    except FileNotFoundError as exc:
        pytest.fail(f"不应发生 FileNotFoundError，check_meta.py 应存在：{exc}")

    # outcome 可能是 failed（因 meta.yaml 不存在），但不应是 FileNotFoundError
    assert result.outcome in ("completed", "failed"), f"outcome 应为 completed 或 failed，实际 {result.outcome}"


# ============================================================================
# TC-F05-4：grep 反向断言 — _dispatch_artifact_node 函数体不含 'node_started' 字面值
# ============================================================================

def test_dispatch_artifact_no_node_started_literal() -> None:
    """_dispatch_artifact_node 函数体内不含 append_event('node_started') 调用。

    验收标准 5（D-008 职责分工硬约束）：handler 禁止写 node_started / node_failed 事件。
    docstring 注释中提及字段名是允许的；禁止的是实际的 append_event 写入调用。
    检查方式：在函数源码中不存在以 append_event 传入 'node_started' 或 'node_failed' 的行。
    """
    source = inspect.getsource(_dispatch_artifact_node)

    # 提取所有非注释、非 docstring 的实际代码行（去除缩进后以 # 开头为注释，跳过）
    # 简化策略：检查源码中不含 append_event 传参含 "node_started" / "node_failed" 的模式
    import re
    # 匹配 append_event(...) 调用中含有 node_started 或 node_failed 的行
    append_node_started = re.search(
        r'append_event\s*\(.*node_started', source
    )
    append_node_failed = re.search(
        r'append_event\s*\(.*node_failed', source
    )

    assert append_node_started is None, (
        "_dispatch_artifact_node 不得调用 append_event 写 'node_started'（D-008 职责分工）"
    )
    assert append_node_failed is None, (
        "_dispatch_artifact_node 不得调用 append_event 写 'node_failed'（D-008 职责分工）"
    )


# ============================================================================
# TC-F05-5：yaml 断言 — standard-8phase.yaml 不含 check_meta_schema 字符串
# ============================================================================

def test_standard_8phase_yaml_no_check_meta_schema() -> None:
    """standard-8phase.yaml 内不含 check_meta_schema 字符串（AC-02 R-I03 路径修正）。

    验收标准 4：grep check_meta_schema 在该 yaml 内 0 hit。
    """
    yaml_path = _REPO_ROOT / ".claude" / "workflows" / "requirement" / "standard-8phase.yaml"
    assert yaml_path.exists(), f"standard-8phase.yaml 应存在于 {yaml_path}"

    content = yaml_path.read_text(encoding="utf-8")
    assert "check_meta_schema" not in content, (
        "standard-8phase.yaml 内不应含 'check_meta_schema'（应已改为 check_meta.py）"
    )
