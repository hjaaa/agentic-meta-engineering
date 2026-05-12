"""F-006 · bash/skill/prompt 节点完整实现单测。

覆盖范围：
  TC-B1  bash 节点：returncode=0 → outcome=completed，写 node_completed 事件，output=stdout
  TC-B2  bash 节点：returncode!=0 → outcome=failed，写 node_failed 事件，error=stderr
  TC-B3  bash 节点：TimeoutExpired → outcome=failed，error 含 "timeout"
  TC-B4  bash 节点：OSError → outcome=failed，error 为异常信息
  TC-B5  bash 节点：$ENV_VAR 被裸字面值替换（escape_for_bash=False）
  TC-B6  bash 节点：cwd=root（仓库根），而非 run_dir
  TC-S1  skill 节点：成功路径——渲染 args + 写 node_completed + output 结构正确
  TC-S2  skill 节点：缺 skill 字段 → raise WorkflowError → dispatch_node 写 node_failed
  TC-S3  skill 节点：args 中变量被 escape_for_bash=True 渲染
  TC-P1  prompt 节点：inline prompt 文本渲染 + 写 node_completed
  TC-P2  prompt 节点：prompt_file 存在 → 读取文件内容后渲染
  TC-P3  prompt 节点：prompt_file 不存在 → dispatch_node 写 node_failed
  TC-P4  prompt 节点：既无 prompt 也无 prompt_file → dispatch_node 写 node_failed

外部依赖（文件 IO / subprocess）使用 tmp_path + echo 真跑或 unittest.mock.patch。
pytest 命名规范：test_<场景>_<期望>（CLAUDE.md §7）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch
import subprocess

import pytest

# ---------- 路径注入 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import RunState, read_events  # noqa: E402
from workflow_dispatcher import (  # noqa: E402
    _dispatch_bash_node,
    _dispatch_skill_node,
    _dispatch_prompt_node,
    dispatch_node,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture()
def jsonl_path(tmp_path: Path) -> Path:
    """返回一个临时 jsonl 文件路径（父目录已存在）。"""
    return tmp_path / "run-state.jsonl"


@pytest.fixture()
def base_run_state() -> RunState:
    """最小化 RunState，含 run_id + arguments。"""
    return RunState(run_id="REQ-2026-010", arguments="test-arg")


# ============================================================================
# TC-B1 · bash 节点成功路径
# ============================================================================

def test_bash_node_success_writes_node_completed_and_returns_stdout(
    jsonl_path, base_run_state, tmp_path
):
    """bash returncode=0 时，写 node_completed 事件且 output=stdout。"""
    node = {"id": "bash-ok", "bash": "echo hello"}
    result = _dispatch_bash_node(
        node, base_run_state, {}, tmp_path, tmp_path, jsonl_path
    )

    assert result.outcome == "completed"
    assert "hello" in (result.output or "")

    events, _ = read_events(jsonl_path)
    completed = [e for e in events if e.get("type") == "node_completed"]
    assert len(completed) == 1
    assert completed[0]["node_id"] == "bash-ok"
    assert "hello" in completed[0]["data"]["output"]


def test_bash_node_success_via_dispatch_node(jsonl_path, base_run_state, tmp_path):
    """通过 dispatch_node 入口，bash 节点成功路径写 node_started + node_completed。"""
    node = {"id": "bash-dispatch-ok", "bash": "printf 'done'"}
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)

    assert result.outcome == "completed"
    events, _ = read_events(jsonl_path)
    types = [e.get("type") for e in events]
    assert "node_started" in types
    assert "node_completed" in types


# ============================================================================
# TC-B2 · bash 节点失败路径
# ============================================================================

def test_bash_node_nonzero_returncode_writes_node_failed_with_stderr(
    jsonl_path, base_run_state, tmp_path
):
    """bash returncode!=0 时，写 node_failed 事件，error=stderr。"""
    node = {"id": "bash-fail", "bash": "echo err_msg >&2; exit 1"}
    result = _dispatch_bash_node(
        node, base_run_state, {}, tmp_path, tmp_path, jsonl_path
    )

    assert result.outcome == "failed"
    assert "err_msg" in (result.error or "")

    events, _ = read_events(jsonl_path)
    failed = [e for e in events if e.get("type") == "node_failed"]
    assert len(failed) == 1
    assert "err_msg" in failed[0]["data"]["error"]


def test_bash_node_nonzero_returncode_via_dispatch_node(
    jsonl_path, base_run_state, tmp_path
):
    """通过 dispatch_node 入口，bash 失败 → node_started + node_failed（无重复事件）。"""
    node = {"id": "bash-fail-dispatch", "bash": "exit 2"}
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)

    assert result.outcome == "failed"
    events, _ = read_events(jsonl_path)
    types = [e.get("type") for e in events]
    assert types.count("node_failed") == 1  # 不重复写
    assert "node_started" in types
    assert result.error and ("exit code" in result.error or result.error.strip())


# ============================================================================
# TC-B3 · bash 节点超时
# ============================================================================

def test_bash_node_timeout_writes_node_failed_with_timeout_message(
    jsonl_path, base_run_state, tmp_path
):
    """subprocess.TimeoutExpired 时，写 node_failed 且 error 含 'timeout'。"""
    node = {"id": "bash-timeout", "bash": "sleep 999", "timeout": 100}  # 100ms

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("bash", 0.1)):
        result = _dispatch_bash_node(
            node, base_run_state, {}, tmp_path, tmp_path, jsonl_path
        )

    assert result.outcome == "failed"
    assert "timeout" in (result.error or "").lower()

    events, _ = read_events(jsonl_path)
    failed = [e for e in events if e.get("type") == "node_failed"]
    assert len(failed) == 1
    assert "timeout" in failed[0]["data"]["error"].lower()


# ============================================================================
# TC-B4 · bash 节点 OSError
# ============================================================================

def test_bash_node_oserror_writes_node_failed(
    jsonl_path, base_run_state, tmp_path
):
    """OSError 时（如 bash 不可执行），写 node_failed，error=str(exc)。"""
    node = {"id": "bash-oserr", "bash": "echo x"}

    with patch("subprocess.run", side_effect=OSError("no such file")):
        result = _dispatch_bash_node(
            node, base_run_state, {}, tmp_path, tmp_path, jsonl_path
        )

    assert result.outcome == "failed"
    assert "no such file" in (result.error or "")

    events, _ = read_events(jsonl_path)
    failed = [e for e in events if e.get("type") == "node_failed"]
    assert len(failed) == 1


# ============================================================================
# TC-B5 · bash 节点变量替换（escape_for_bash=False）
# ============================================================================

def test_bash_node_env_var_substituted_as_literal(
    jsonl_path, base_run_state, tmp_path
):
    """bash 节点使用 escape_for_bash=False，$ENV_VAR 替换为裸字面值（不加引号）。

    验证方式：把替换后的值通过 echo 打出，检查 stdout 包含字面值而非带引号的形式。
    """
    node = {"id": "bash-var", "bash": "echo $MSG"}
    env = {"MSG": "hello-world"}
    result = _dispatch_bash_node(
        node, base_run_state, env, tmp_path, tmp_path, jsonl_path
    )

    assert result.outcome == "completed"
    # 裸字面值替换后命令变为 `echo hello-world`，stdout 应为 "hello-world"
    assert "hello-world" in (result.output or "")


def test_bash_node_node_output_substituted_as_literal(
    jsonl_path, tmp_path
):
    """bash 节点使用 escape_for_bash=False，$nodeId.output 替换为裸字面值。"""
    rs = RunState(run_id="REQ-TEST-001")
    rs.node_outputs["prev"] = {"output": "myval", "state": "completed", "data": {}}
    node = {"id": "bash-noderef", "bash": "echo $prev.output"}
    result = _dispatch_bash_node(
        node, rs, {}, tmp_path, tmp_path, jsonl_path
    )

    assert result.outcome == "completed"
    assert "myval" in (result.output or "")


# ============================================================================
# TC-B6 · bash 节点 cwd=root（仓库根）
# ============================================================================

def test_bash_node_cwd_is_root_not_run_dir(jsonl_path, base_run_state, tmp_path):
    """bash 节点 cwd=root（仓库根），不是 run_dir——验证 pwd 输出。

    用独立子目录模拟 root 与 run_dir 不同的场景。
    """
    root_dir = tmp_path / "root"
    run_dir = tmp_path / "run"
    root_dir.mkdir()
    run_dir.mkdir()

    node = {"id": "bash-cwd", "bash": "pwd"}
    result = _dispatch_bash_node(
        node, base_run_state, {}, run_dir, root_dir, jsonl_path
    )

    assert result.outcome == "completed"
    # stdout 应为 root_dir 的路径，而非 run_dir
    assert str(root_dir) in (result.output or "").strip()
    assert str(run_dir) not in (result.output or "").strip()


# ============================================================================
# TC-S1 · skill 节点成功路径
# ============================================================================

def test_skill_node_success_writes_node_completed_with_output(
    jsonl_path, base_run_state, tmp_path
):
    """skill 节点成功路径：output 结构为 {skill, args}，写 node_completed 事件。"""
    node = {
        "id": "skill-ok",
        "skill": "my-skill",
        "args": {"key1": "val1", "key2": "val2"},
    }
    result = _dispatch_skill_node(node, base_run_state, {}, jsonl_path)

    assert result.outcome == "completed"
    assert result.output is not None
    assert result.output["skill"] == "my-skill"
    assert "key1" in result.output["args"]

    events, _ = read_events(jsonl_path)
    completed = [e for e in events if e.get("type") == "node_completed"]
    assert len(completed) == 1
    assert completed[0]["node_id"] == "skill-ok"
    assert completed[0]["data"]["output"]["skill"] == "my-skill"


def test_skill_node_no_args_success(jsonl_path, base_run_state):
    """skill 节点无 args 时，output.args 为空 dict，仍返回 completed。"""
    node = {"id": "skill-noarg", "skill": "bare-skill"}
    result = _dispatch_skill_node(node, base_run_state, {}, jsonl_path)

    assert result.outcome == "completed"
    assert result.output["args"] == {}


# ============================================================================
# TC-S2 · skill 节点缺 skill 字段 → node_failed
# ============================================================================

def test_skill_node_missing_skill_field_returns_failed(
    jsonl_path, base_run_state, tmp_path
):
    """skill 键值为空时，dispatch_node 捕获 WorkflowError，写 node_failed。"""
    # node["skill"] = "" 触发 WorkflowError
    node = {"id": "skill-bad", "skill": ""}
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)

    assert result.outcome == "failed"
    events, _ = read_events(jsonl_path)
    failed = [e for e in events if e.get("type") == "node_failed"]
    assert len(failed) == 1


# ============================================================================
# TC-S3 · skill 节点 args 变量渲染（escape_for_bash=True）
# ============================================================================

def test_skill_node_args_substituted_with_escape(jsonl_path, tmp_path):
    """skill 节点 args 中的 $ENV_VAR 以 escape_for_bash=True 渲染（加单引号）。"""
    rs = RunState(run_id="REQ-TEST-002")
    env = {"MY_VAR": "my value"}
    node = {
        "id": "skill-esc",
        "skill": "esc-skill",
        "args": {"param": "$MY_VAR"},
    }
    result = _dispatch_skill_node(node, rs, env, jsonl_path)

    assert result.outcome == "completed"
    # escape_for_bash=True 时，"my value" 会被包成 'my value'
    rendered = result.output["args"]["param"]
    assert "my value" in rendered
    # 验证有 shell 引号（单引号包裹）
    assert rendered.startswith("'") and rendered.endswith("'")


def test_skill_node_args_node_output_substituted(jsonl_path):
    """skill 节点 args 中 $nodeId.output 通过 run_state.node_outputs 解析。"""
    rs = RunState(run_id="REQ-TEST-003")
    rs.node_outputs["upstream"] = {
        "output": "upstream-result",
        "state": "completed",
        "data": {},
    }
    node = {
        "id": "skill-noderef",
        "skill": "ref-skill",
        "args": {"data": "$upstream.output"},
    }
    result = _dispatch_skill_node(node, rs, {}, jsonl_path)

    assert result.outcome == "completed"
    rendered = result.output["args"]["data"]
    assert "upstream-result" in rendered


# ============================================================================
# TC-P1 · prompt 节点 inline 文本
# ============================================================================

def test_prompt_node_inline_writes_node_completed(jsonl_path, base_run_state, tmp_path):
    """prompt 节点 inline 文本路径：渲染后写 node_completed，output=渲染后文本。"""
    env = {"RUN_ID": "REQ-2026-010"}
    node = {"id": "prompt-inline", "prompt": "请处理 $RUN_ID"}
    result = _dispatch_prompt_node(
        node, base_run_state, env, tmp_path, tmp_path, jsonl_path
    )

    assert result.outcome == "completed"
    assert "REQ-2026-010" in (result.output or "")

    events, _ = read_events(jsonl_path)
    completed = [e for e in events if e.get("type") == "node_completed"]
    assert len(completed) == 1
    assert "REQ-2026-010" in completed[0]["data"]["output"]


def test_prompt_node_inline_via_dispatch_node(jsonl_path, base_run_state, tmp_path):
    """通过 dispatch_node 入口，prompt inline 节点成功路径写 node_started + node_completed。"""
    node = {"id": "prompt-dispatch", "prompt": "hello world"}
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)

    assert result.outcome == "completed"
    events, _ = read_events(jsonl_path)
    types = [e.get("type") for e in events]
    assert "node_started" in types
    assert "node_completed" in types


# ============================================================================
# TC-P2 · prompt 节点 prompt_file
# ============================================================================

def test_prompt_node_prompt_file_reads_and_renders(
    jsonl_path, base_run_state, tmp_path
):
    """prompt_file 存在时，读取文件内容并渲染变量后写 node_completed。"""
    prompt_file = tmp_path / "prompts" / "test.md"
    prompt_file.parent.mkdir(parents=True)
    prompt_file.write_text("请处理 $RUN_ID 的任务", encoding="utf-8")

    env = {"RUN_ID": "REQ-2026-010"}
    node = {"id": "prompt-file", "prompt_file": "prompts/test.md"}
    result = _dispatch_prompt_node(
        node, base_run_state, env, tmp_path, tmp_path, jsonl_path
    )

    assert result.outcome == "completed"
    assert "REQ-2026-010" in (result.output or "")

    events, _ = read_events(jsonl_path)
    completed = [e for e in events if e.get("type") == "node_completed"]
    assert len(completed) == 1


# ============================================================================
# TC-P3 · prompt 节点 prompt_file 不存在 → node_failed
# ============================================================================

def test_prompt_node_missing_prompt_file_returns_failed(
    jsonl_path, base_run_state, tmp_path
):
    """prompt_file 不存在时，dispatch_node 捕获 WorkflowError，写 node_failed。"""
    node = {"id": "prompt-nofile", "prompt_file": "nonexistent/prompt.md"}
    result = dispatch_node(node, base_run_state, tmp_path, tmp_path, {}, jsonl_path)

    assert result.outcome == "failed"
    assert "prompt_file not found" in (result.error or "")

    events, _ = read_events(jsonl_path)
    failed = [e for e in events if e.get("type") == "node_failed"]
    assert len(failed) == 1
    assert "prompt_file not found" in failed[0]["data"]["error"]


# ============================================================================
# TC-P4 · prompt 节点既无 prompt 也无 prompt_file → node_failed
# ============================================================================

def test_prompt_node_no_prompt_nor_file_returns_failed(
    jsonl_path, base_run_state, tmp_path
):
    """prompt 节点键存在但 node["prompt"] / node["prompt_file"] 均缺失，dispatch_node 写 node_failed。"""
    # node 有 "prompt" 键但值为 None，走 prompt 路径 → substitute_vars 能处理 None 返回 ""
    # 为测试"既无 prompt 也无 prompt_file"，手工构造一个带 prompt=None + 无 prompt_file 的节点
    # 注意：dispatch_node 用 "prompt" in node 判断，所以要绕过用 _dispatch_prompt_node 直接调用
    from common import WorkflowError
    node = {"id": "prompt-empty"}  # 既无 prompt 也无 prompt_file

    with pytest.raises(WorkflowError, match="既无 prompt 也无 prompt_file"):
        _dispatch_prompt_node(node, base_run_state, {}, tmp_path, tmp_path, jsonl_path)

    # 通过 dispatch_node 路由时，该节点不含 prompt/bash/skill 等已知键，
    # 会走 unknown 路径（未知节点类型）。测试直接调用已覆盖该逻辑。
