"""workflow 节点派发器（F-005 框架骨架）。

职责：
- `dispatch_node`：入口，按 node dict 内含的键派发到 7 类节点处理函数
- `_build_env`：从 RunState 构建注入到下游的环境变量字典
- 7 类 stub 函数（除 approval 外均返回 outcome="completed"；
  approval stub 写 approval_pending 事件并返回 outcome="approval_pending"）

真实执行逻辑将在后续 feature（F-006/F-007/F-011）中替换相应 stub。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

# 确保 lib 目录在 sys.path 中（直接运行脚本时使用）
_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import WorkflowError  # noqa: E402（WorkflowError 统一定义在 common，禁止本地重定义）
from run_state import RunState, append_event  # noqa: E402
from substitute_vars import substitute_vars  # noqa: E402


# ============================================================================
# DispatchOutcome：7 个合法派发结果（详细设计 §1.5）
# ============================================================================

# 注意：node_started 等是「事件类型」，skipped 不在此枚举中（见开发上下文的笔误说明）
DispatchOutcome = Literal[
    "completed",
    "approval_pending",
    "failed",
    "loop_continue",
    "loop_done",
    "sub_workflow_pending",
    "sub_workflow_done",
]


# ============================================================================
# DispatchResult（详细设计 §1.6）
# ============================================================================

@dataclass
class DispatchResult:
    """节点执行结果载体。

    - outcome：节点执行结论（7 个枚举值之一）
    - output：节点产出（stdout 字符串或结构化对象）；可为 None
    - error：失败时的错误描述；非失败路径留 None
    - next_node_hint：显式覆盖默认拓扑（on_reject 等场景）；None 则走默认
    """

    outcome: DispatchOutcome
    output: Any | None = None
    error: str | None = None
    next_node_hint: str | None = None


# ============================================================================
# _build_env（详细设计 §2.3）
# ============================================================================

def _build_env(run_state: RunState, run_dir: Path, root: Path) -> dict[str, str]:
    """从 RunState 构建注入到节点的环境变量字典。

    包含 6 个基础变量（RUN_ID/RUN_DIR/META_PATH/ARTIFACTS_DIR/ARGUMENTS/BRANCH_NAME）
    以及所有已完成节点的 <nodeId>.output 引用（供 $nodeId.output 变量替换消费）。

    注意：run_state.node_outputs 存储的是 dict[str, dict[str, Any]]
    （含 output/state/data 三键），需从 entry["output"] 取出实际值。
    """
    short_id = (run_state.run_id or "").removeprefix("REQ-").lower()
    branch_name = f"feat/req-{short_id}"

    env: dict[str, str] = {
        "RUN_ID": run_state.run_id or "",
        "RUN_DIR": str(run_dir),
        "META_PATH": str(run_dir / "meta.yaml"),
        "ARTIFACTS_DIR": str(run_dir / "artifacts"),
        "ARGUMENTS": run_state.arguments or "",
        "BRANCH_NAME": branch_name,
    }

    # 注入已完成节点的 output（F-004 路径参数化消费 $META_PATH/$BRANCH_NAME 的基础）
    for node_id, entry in run_state.node_outputs.items():
        # entry 是 {"output": ..., "state": ..., "data": ...}；取 output 而非整个 dict
        output = entry.get("output", "") if isinstance(entry, dict) else entry
        env[f"{node_id}.output"] = (
            json.dumps(output, ensure_ascii=False)
            if not isinstance(output, str)
            else output
        )

    return env


# ============================================================================
# 入口：dispatch_node（详细设计 §1.5 派发规则）
# ============================================================================

def dispatch_node(
    node: dict,
    run_state: RunState,
    run_dir: Path,
    root: Path,
    env: dict[str, Any],
    jsonl_path: Path,
) -> DispatchResult:
    """按 node dict 内含的键派发到 7 类节点处理函数。

    进入时写 node_started 事件；异常时写 node_failed 事件并返回 outcome="failed"。
    未知节点类型抛 WorkflowError（被 except 捕获后写 node_failed）。

    派发优先级（按 detailed-design.md:158-165）：
      agent > skill > prompt > bash > approval > loop > sub_workflow
    """
    node_id: str = node.get("id", "<unknown>")

    # 进入节点即写 node_started（与 type 识别无关，保证事件成对）
    append_event(jsonl_path, {
        "type": "node_started",
        "node_id": node_id,
        "run_id": run_state.run_id,
    })

    try:
        # 按 node dict 内含键识别类型（顺序即优先级）
        if "agent" in node:
            result = _dispatch_agent_node(node, env, jsonl_path)
        elif "skill" in node:
            result = _dispatch_skill_node(node, env, jsonl_path)
        elif "prompt" in node:
            result = _dispatch_prompt_node(node, env, jsonl_path)
        elif "bash" in node:
            result = _dispatch_bash_node(node, env, run_dir, jsonl_path)
        elif "approval" in node:
            result = _dispatch_approval_node(node, env, run_state, jsonl_path)
        elif "loop" in node:
            result = _dispatch_loop_node(node, env, run_state, jsonl_path)
        elif "sub_workflow" in node:
            result = _dispatch_sub_workflow_node(node, env, run_dir, root, jsonl_path)
        else:
            raise WorkflowError(f"未知节点类型: {node_id}")

    except Exception as exc:
        # 所有异常（含 WorkflowError）统一转换为 outcome=failed，写 node_failed 事件
        # 这是规范要求的"转换为 outcome=failed"，而非吞没异常
        error_msg = str(exc)
        append_event(jsonl_path, {
            "type": "node_failed",
            "node_id": node_id,
            "run_id": run_state.run_id,
            "data": {"error": error_msg},
        })
        return DispatchResult(outcome="failed", error=error_msg)

    return result


# ============================================================================
# 7 类节点 stub 函数（F-006/F-007/F-011 替换真实逻辑）
# ============================================================================

def _dispatch_agent_node(
    node: dict,
    env: dict[str, Any],
    jsonl_path: Path,
) -> DispatchResult:
    """Agent 节点 stub。

    真实逻辑在 F-006 实现（调用 subagent 执行 agent 字段指定的 agent）。
    """
    return DispatchResult(outcome="completed")


def _dispatch_skill_node(
    node: dict,
    env: dict[str, Any],
    jsonl_path: Path,
) -> DispatchResult:
    """Skill 节点 stub。

    真实逻辑在 F-006 实现（调用 /skill:xxx）。
    """
    return DispatchResult(outcome="completed")


def _dispatch_prompt_node(
    node: dict,
    env: dict[str, Any],
    jsonl_path: Path,
) -> DispatchResult:
    """Prompt 节点 stub。

    真实逻辑在 F-006 实现（直接向 Claude 发 prompt 并收 stdout）。
    """
    return DispatchResult(outcome="completed")


def _dispatch_bash_node(
    node: dict,
    env: dict[str, Any],
    run_dir: Path,
    jsonl_path: Path,
) -> DispatchResult:
    """Bash 节点 stub。

    真实逻辑在 F-006 实现（subprocess.run bash 命令、捕获 stdout/stderr/exit code）。
    """
    return DispatchResult(outcome="completed")


def _dispatch_approval_node(
    node: dict,
    env: dict[str, Any],
    run_state: RunState,
    jsonl_path: Path,
) -> DispatchResult:
    """Approval 节点：写 approval_pending 事件供 F-007 续跑消费。

    按 detailed-design.md:178-185：
    1. 对 node["approval"]["prompt"] 执行 substitute_vars 替换
    2. 写 approval_pending 事件（data.prompt = 替换后的文本）
    3. 返回 DispatchResult(outcome="approval_pending")

    人类 sign-off 后由 /workflow:approve 写 approval_approved 事件，
    F-007 的续跑逻辑再推进到 node_completed。
    """
    node_id: str = node.get("id", "<unknown>")
    approval_cfg = node.get("approval") or {}

    # 替换 prompt 中的变量引用（$RUN_ID / $nodeId.output 等）
    raw_prompt: str = approval_cfg.get("prompt", "")
    # 传 run_state.node_outputs 让 prompt 中 $<nodeId>.output[.field] 引用能解析（env 走 ENV_VAR 路径覆盖不到 .output 后缀）
    rendered_prompt = substitute_vars(raw_prompt, run_state.node_outputs, env)

    append_event(jsonl_path, {
        "type": "approval_pending",
        "node_id": node_id,
        "data": {"prompt": rendered_prompt},
    })

    return DispatchResult(outcome="approval_pending")


def _dispatch_loop_node(
    node: dict,
    env: dict[str, Any],
    run_state: RunState,
    jsonl_path: Path,
) -> DispatchResult:
    """Loop 节点 stub。

    真实逻辑在 F-011 实现（迭代控制 + loop_iteration_started/completed 事件写入）。
    """
    return DispatchResult(outcome="completed")


def _dispatch_sub_workflow_node(
    node: dict,
    env: dict[str, Any],
    run_dir: Path,
    root: Path,
    jsonl_path: Path,
) -> DispatchResult:
    """Sub-workflow 节点 stub。

    真实逻辑在 F-011 实现（启动子 workflow run、等待结果、写 child_* 事件）。
    """
    return DispatchResult(outcome="completed")
