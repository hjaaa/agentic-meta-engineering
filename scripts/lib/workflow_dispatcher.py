"""workflow 节点派发器（F-005 框架骨架；F-006 实现 bash/skill/prompt 节点）。

职责：
- `dispatch_node`：入口，按 node dict 内含的键派发到 7 类节点处理函数
- `_build_env`：从 RunState 构建注入到下游的环境变量字典
- bash/skill/prompt 节点：F-006 实现真实逻辑（substitute_vars + subprocess/事件写入）
- approval 节点：写 approval_pending 事件并返回 outcome="approval_pending"
- loop/sub_workflow/agent 节点：stub，分别由 F-011/F-010 替换

真实执行逻辑：bash/skill/prompt 已在 F-006 落地；agent/loop/sub_workflow 在后续 feature 替换。
"""
from __future__ import annotations

import json
import subprocess
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
import workflow_run  # noqa: E402（F-011：sub_workflow 节点派子 run 用；顶层导入便于测试 mock）


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
            result = _dispatch_skill_node(node, run_state, env, jsonl_path)
        elif "prompt" in node or "prompt_file" in node:
            # prompt_file 是 prompt 节点的另一种写法，统一派发（§1.6 描述两者互斥）
            result = _dispatch_prompt_node(node, run_state, env, run_dir, root, jsonl_path)
        elif "bash" in node:
            result = _dispatch_bash_node(node, run_state, env, run_dir, root, jsonl_path)
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
# 7 类节点 dispatcher（bash/skill/prompt 已在 F-006 落地；agent → F-010；approval 已落地；loop/sub_workflow → F-011）
# ============================================================================

def _dispatch_agent_node(
    node: dict,
    env: dict[str, Any],
    jsonl_path: Path,
) -> DispatchResult:
    """Agent 节点 stub。

    真实逻辑在 F-010 实现（mock_agent_dispatch fixture + 主 Claude 集成）。
    """
    return DispatchResult(outcome="completed")


def _dispatch_skill_node(
    node: dict,
    run_state: RunState,
    env: dict[str, Any],
    jsonl_path: Path,
) -> DispatchResult:
    """Skill 节点：渲染 args 中的变量（escape_for_bash=True）+ 写 node_completed{output: {skill, args}}。

    主 Claude 实际调用 skill 由后续集成层 PR 接管。
    args 中每个 value 调 substitute_vars escape_for_bash=True（默认安全转义）。
    """
    node_id: str = node.get("id", "<unknown>")
    skill_name: str = node.get("skill", "")
    if not skill_name:
        raise WorkflowError(f"skill 节点 {node_id!r} 缺少 skill 字段")

    raw_args: dict = node.get("args") or {}
    # 渲染每个 arg value（bash 模式：escape_for_bash=True，防注入）
    rendered_args: dict[str, str] = {
        k: substitute_vars(str(v), run_state.node_outputs, env, escape_for_bash=True)
        for k, v in raw_args.items()
    }

    output = {"skill": skill_name, "args": rendered_args}
    append_event(jsonl_path, {
        "type": "node_completed",
        "node_id": node_id,
        "data": {"output": output},
    })
    return DispatchResult(outcome="completed", output=output)


def _dispatch_prompt_node(
    node: dict,
    run_state: RunState,
    env: dict[str, Any],
    run_dir: Path,
    root: Path,
    jsonl_path: Path,
) -> DispatchResult:
    """Prompt 节点：取 prompt / prompt_file 文本 + 变量替换（escape_for_bash=True）+ 写 node_completed。

    主 Claude 实际消费 prompt 由后续集成层 PR 接管。
    优先取 node["prompt"]（inline 字符串），其次 node["prompt_file"]（相对仓库根读文件）。
    prompt_file 读不到 → raise WorkflowError，由 dispatch_node 入口的 except 转 node_failed。
    escape_for_bash=True：prompt 文本会作为 Claude 的 shell 参数传递，需防注入。
    """
    node_id: str = node.get("id", "<unknown>")

    # 获取原始 prompt 文本
    if "prompt" in node:
        raw_text: str = node["prompt"]
    elif "prompt_file" in node:
        prompt_path = root / node["prompt_file"]
        try:
            raw_text = prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise WorkflowError(
                f"prompt_file not found: {prompt_path}"
            ) from exc
    else:
        raise WorkflowError(f"prompt 节点 {node_id!r} 既无 prompt 也无 prompt_file")

    rendered = substitute_vars(raw_text, run_state.node_outputs, env, escape_for_bash=True)
    append_event(jsonl_path, {
        "type": "node_completed",
        "node_id": node_id,
        "data": {"output": rendered},
    })
    return DispatchResult(outcome="completed", output=rendered)


def _dispatch_bash_node(
    node: dict,
    run_state: RunState,
    env: dict[str, Any],
    run_dir: Path,
    root: Path,
    jsonl_path: Path,
) -> DispatchResult:
    """Bash 节点：变量预替换后 subprocess.run，按 returncode 写 node_completed/node_failed。

    关键约束：
    - escape_for_bash=False：bash 命令内变量以裸字面值注入，不加 shell 引号
    - cwd=root（仓库根）：standard-8phase.yaml 的 bash 块均用相对仓库根的路径
    - 超时/OSError 作为业务失败路径（写 node_failed），不让异常逃逸到入口（避免重复事件）
    """
    node_id: str = node.get("id", "<unknown>")
    raw_bash: str = node.get("bash") or ""
    # bash 命令中引用变量需裸字面值（不加 shell 引号）；escape_for_bash=False
    rendered_bash = substitute_vars(raw_bash, run_state.node_outputs, env, escape_for_bash=False)

    # timeout 字段单位毫秒（与 yaml 约定对齐）；默认 60000 ms = 60s
    timeout_ms: int = node.get("timeout", 60000)
    timeout_sec: float = timeout_ms / 1000.0

    try:
        proc = subprocess.run(
            ["bash", "-c", rendered_bash],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        error_msg = f"timeout after {timeout_sec}s"
        append_event(jsonl_path, {
            "type": "node_failed",
            "node_id": node_id,
            "data": {"error": error_msg},
        })
        return DispatchResult(outcome="failed", error=error_msg)
    except OSError as exc:
        error_msg = str(exc)
        append_event(jsonl_path, {
            "type": "node_failed",
            "node_id": node_id,
            "data": {"error": error_msg},
        })
        return DispatchResult(outcome="failed", error=error_msg)

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    if proc.returncode == 0:
        append_event(jsonl_path, {
            "type": "node_completed",
            "node_id": node_id,
            "data": {"output": stdout},
        })
        return DispatchResult(outcome="completed", output=stdout)
    else:
        error_msg = stderr or stdout or f"exit code {proc.returncode} (no stderr/stdout)"
        append_event(jsonl_path, {
            "type": "node_failed",
            "node_id": node_id,
            "data": {"error": error_msg},
        })
        return DispatchResult(outcome="failed", error=error_msg)


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
    """Loop 节点：迭代计数从 run_state.loop_counters[node_id] 读取。

    逻辑（F-011）：
    1. 读取当前迭代次数（loop_counters[node_id]，首次为 0）
    2. 写 loop_iteration_started 事件（data.iteration = current_iteration）
    3. 写 loop_iteration_completed 事件（data.iteration = current_iteration）
    4. 若 current_iteration + 1 >= max_iterations → outcome="loop_done"
       否则 → outcome="loop_continue"（workflow_continue.py 负责递增计数器并继续同节点）

    约束：
    - data["iteration"] 必须存在，供 RunState.rebuild 中 loop_counters 累计消费
    - max_iterations 取自 node["loop"]["max_iterations"]；缺省视为 1
    """
    node_id: str = node.get("id", "<unknown>")
    loop_cfg: dict = node.get("loop") or {}
    max_iterations: int = int(loop_cfg.get("max_iterations", 1))

    # 当前迭代索引（0-based）：首次不在 loop_counters 中，取 0
    current_iteration: int = run_state.loop_counters.get(node_id, 0)

    append_event(jsonl_path, {
        "type": "loop_iteration_started",
        "node_id": node_id,
        "run_id": run_state.run_id,
        "data": {"iteration": current_iteration},
    })

    append_event(jsonl_path, {
        "type": "loop_iteration_completed",
        "node_id": node_id,
        "run_id": run_state.run_id,
        "data": {"iteration": current_iteration},
    })

    # 已完成 current_iteration 轮（0-based），下一轮编号为 current_iteration + 1
    if current_iteration + 1 >= max_iterations:
        return DispatchResult(outcome="loop_done")
    return DispatchResult(outcome="loop_continue")


def _dispatch_sub_workflow_node(
    node: dict,
    env: dict[str, Any],
    run_dir: Path,
    root: Path,
    jsonl_path: Path,
) -> DispatchResult:
    """Sub-workflow 节点：派子 run 到 run_dir/sub_runs/<node_id>/。

    逻辑（F-011 最小实现）：
    1. 解析 node["sub_workflow"]["template"] 取模板 ID
    2. 子 run 目录固定为 run_dir / "sub_runs" / node_id（与 workflow_status / rollback 约定一致）
    3. 调 workflow_run.main 启动子 run（复用 Python 入口，不走 subprocess）
    4. 返回 outcome="sub_workflow_pending"（等 /workflow:continue 时检测子 run 状态）

    深度联动（多级嵌套 + 子 run 完成回填）留后续 REQ，本 feature 仅最小实现。
    """
    node_id: str = node.get("id", "<unknown>")
    sub_cfg: dict = node.get("sub_workflow") or {}
    template_id: str = sub_cfg.get("template", "")
    if not template_id:
        raise WorkflowError(f"sub_workflow 节点 {node_id!r} 缺少 template 字段")

    # 子 run 目录：与 workflow_status / workflow_rollback_subrun 约定一致
    sub_run_dir = run_dir / "sub_runs" / node_id
    sub_run_dir.mkdir(parents=True, exist_ok=True)

    # 复用 workflow_run.main Python 入口派子 run（不走 subprocess，避免路径/环境耦合）
    args = sub_cfg.get("args", "")
    args_list = [template_id] + (args.split() if isinstance(args, str) and args else [])
    rc = workflow_run.main(args_list, repo_root=root)
    if rc != 0:
        raise WorkflowError(
            f"sub_workflow 节点 {node_id!r} 启动子 run 失败（exit={rc}，template={template_id!r}）"
        )

    return DispatchResult(outcome="sub_workflow_pending")
