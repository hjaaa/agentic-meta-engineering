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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

# 确保 lib 目录在 sys.path 中（直接运行脚本时使用）
_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from artifact_spec_renderer import _render_artifact_spec  # noqa: E402
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
    "awaiting_claude_action",  # F-002：节点就绪等待 Claude 执行（node_ready / approval_repair_started 路径）
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

    # Bug-12：$LOG_DIR 注入（task-list-summary 等节点依赖）
    log_dir = run_dir / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 仅日志目录创建失败 → warn but 不阻断；节点 bash 自身写失败会有更清晰错误
        pass

    env: dict[str, str] = {
        "RUN_ID": run_state.run_id or "",
        "RUN_DIR": str(run_dir),
        "META_PATH": str(run_dir / "meta.yaml"),
        "ARTIFACTS_DIR": str(run_dir / "artifacts"),
        "LOG_DIR": str(log_dir),
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

def _dispatch_node_by_type_key(
    node: dict,
    run_state: RunState,
    run_dir: Path,
    root: Path,
    env: dict[str, Any],
    jsonl_path: Path,
) -> DispatchResult:
    """按 node 内含的类型键派发到对应 _dispatch_*_node。

    顺序优先级（与历史 elif 链一致）：
      agent > skill > prompt/prompt_file > bash > approval > loop > sub_workflow > artifact

    抽离为独立函数（IB-21b），使 dispatch_node 主函数 CCN 降为 ≈ 4。
    各 handler 签名不同，无法用统一字典映射——保留 if 链 self-contained 语义。
    """
    if "agent" in node:
        return _dispatch_agent_node(node, run_state, env, jsonl_path)
    if "skill" in node:
        return _dispatch_skill_node(node, run_state, env, jsonl_path)
    if "prompt" in node or "prompt_file" in node:
        # prompt_file 是 prompt 节点的另一种写法，统一派发（§1.6 描述两者互斥）
        return _dispatch_prompt_node(node, run_state, env, run_dir, root, jsonl_path)
    if "bash" in node:
        return _dispatch_bash_node(node, run_state, env, run_dir, root, jsonl_path)
    if "approval" in node:
        return _dispatch_approval_node(node, env, run_state, jsonl_path)
    if "loop" in node:
        return _dispatch_loop_node(node, env, run_state, jsonl_path, root)
    if "sub_workflow" in node:
        # env 当前未在 sub_workflow 节点使用；run_state 用于写 parent_run_id 入 sub run meta
        return _dispatch_sub_workflow_node(node, run_state, run_dir, root, jsonl_path)
    if "artifact" in node:                              # AC-02 第 8 类
        return _dispatch_artifact_node(node, run_state, root, env, jsonl_path)
    node_id: str = node.get("id", "<unknown>")
    raise WorkflowError(f"未知节点类型: {node_id}")


def dispatch_node(
    node: dict,
    run_state: RunState,
    run_dir: Path,
    root: Path,
    env: dict[str, Any],
    jsonl_path: Path,
) -> DispatchResult:
    """按 node dict 内含的键派发到 8 类节点处理函数。

    进入时写 node_started 事件；异常时写 node_failed 事件并返回 outcome="failed"。
    未知节点类型抛 WorkflowError（被 except 捕获后写 node_failed）。

    派发优先级（按 detailed-design.md:158-165）：
      agent > skill > prompt > bash > approval > loop > sub_workflow > artifact

    类型识别委托给 _dispatch_node_by_type_key（IB-21b），主函数 CCN ≤ 4。
    """
    node_id: str = node.get("id", "<unknown>")

    # 进入节点即写 node_started（与 type 识别无关，保证事件成对）
    append_event(jsonl_path, {
        "type": "node_started",
        "node_id": node_id,
        "run_id": run_state.run_id,
    })

    try:
        return _dispatch_node_by_type_key(node, run_state, run_dir, root, env, jsonl_path)
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


# ============================================================================
# 7 类节点 dispatcher（bash/skill/prompt 已在 F-006 落地；agent → F-010；approval 已落地；loop/sub_workflow → F-011）
# ============================================================================

def _build_external_action_contract(node: dict) -> dict:
    """AC-10：从 yaml 节点提取 7 字段透传 contract（缺省值见详细设计 §2.2.1）。"""
    return {
        "allowed_tools": node.get("allowed_tools", []),
        "denied_tools":  node.get("denied_tools", []),
        "mcp":           node.get("mcp", []),
        "skills":        node.get("skills", []),
        "agents":        node.get("agents", []),
        "idle_timeout":  node.get("idle_timeout"),
        "output_format": node.get("output_format"),
    }


def _dispatch_agent_node(
    node: dict,
    run_state: RunState,
    env: dict[str, Any],
    jsonl_path: Path,
) -> DispatchResult:
    """Agent 节点：写 node_ready + external_action_contract，返回 awaiting_claude_action。

    AC-04a / AC-10：真实 agent 执行由主 Claude Code 反扫末位 node_ready 后触发；
    本期 contract 仅透传到 jsonl（save_node_result.py 不消费 contract 字段）。
    """
    node_id: str = node.get("id", "<unknown>")
    contract = _build_external_action_contract(node)
    append_event(jsonl_path, {
        "type": "node_ready",
        "node_id": node_id,
        "run_id": run_state.run_id,
        "data": {
            "node_kind": "agent",
            "external_action_contract": contract,
            "agent": node.get("agent", ""),
        },
    })
    return DispatchResult(outcome="awaiting_claude_action")


def _dispatch_skill_node(
    node: dict,
    run_state: RunState,
    env: dict[str, Any],
    jsonl_path: Path,
) -> DispatchResult:
    """Skill 节点：渲染 args + 写 node_ready{skill, args, external_action_contract}。

    AC-04a / AC-10：写 node_ready 而非 node_completed；真实 skill 调用由主 Claude Code
    反扫末位 node_ready 后执行；save_node_result.py --kind=skill_result 写 node_completed。
    args 中每个 value 调 substitute_vars escape_for_bash=True（防注入）。
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

    contract = _build_external_action_contract(node)
    append_event(jsonl_path, {
        "type": "node_ready",
        "node_id": node_id,
        "run_id": run_state.run_id,
        "data": {
            "node_kind": "skill",
            "external_action_contract": contract,
            "skill": skill_name,
            "args": rendered_args,
        },
    })
    return DispatchResult(outcome="awaiting_claude_action")


def _dispatch_prompt_node(
    node: dict,
    run_state: RunState,
    env: dict[str, Any],
    run_dir: Path,
    root: Path,
    jsonl_path: Path,
) -> DispatchResult:
    """Prompt 节点：取 prompt / prompt_file 文本 + 变量替换 + 写 node_ready{prompt, external_action_contract}。

    AC-04a / AC-10：写 node_ready 而非 node_completed；真实 prompt 消费由主 Claude Code 执行。
    优先取 node["prompt"]（inline 字符串），其次 node["prompt_file"]（相对仓库根读文件）。
    prompt_file 读不到 → raise WorkflowError，由 dispatch_node 入口的 except 转 node_failed。
    escape_for_bash=True：prompt 文本会作为 Claude 的 shell 参数传递，需防注入。
    """
    node_id: str = node.get("id", "<unknown>")

    # 获取原始 prompt 文本
    if "prompt" in node:
        raw_text: str = node["prompt"]
    elif "prompt_file" in node:
        from workflow_loader import _resolve_prompt_file  # Bug-8 workaround: dispatcher/loader 解析逻辑对齐
        # Bug-19 修复：透传 `root`（测试 fixture 注入；生产场景仍回退模块级常量）
        prompt_path = _resolve_prompt_file(node["prompt_file"], repo_root=root)
        try:
            raw_text = prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise WorkflowError(
                f"prompt_file not found: {prompt_path}"
            ) from exc
    else:
        raise WorkflowError(f"prompt 节点 {node_id!r} 既无 prompt 也无 prompt_file")

    rendered = substitute_vars(raw_text, run_state.node_outputs, env, escape_for_bash=True)
    contract = _build_external_action_contract(node)
    append_event(jsonl_path, {
        "type": "node_ready",
        "node_id": node_id,
        "run_id": run_state.run_id,
        "data": {
            "node_kind": "prompt",
            "external_action_contract": contract,
            "prompt": rendered,
        },
    })
    return DispatchResult(outcome="awaiting_claude_action")


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

    按 schema（workflow_loader.py:390-393）：approval.message 或 approval.gate_message
    至少有一个；codex round-3（2026-05-12）发现旧实现读 approval.prompt 与 schema 不
    一致，导致所有按 schema 写的真实 approval 节点（如 standard-8phase.yaml 的 8 处
    阶段 signoff）写出来 approval_pending.data.prompt 永远空，人类看不到该签什么。

    修后顺序：message → gate_message → prompt（legacy fallback，兼容历史 yaml）；
    渲染后写 approval_pending.data.prompt（事件字段名保留不变，下游消费者 / 测试断言
    不破坏）。

    流程：
    1. 取消息文本（message > gate_message > prompt）
    2. 对文本执行 substitute_vars 替换
    3. 写 approval_pending 事件（data.prompt = 替换后的文本）
    4. 返回 DispatchResult(outcome="approval_pending")

    人类 sign-off 后由 /workflow:approve 写 approval_approved 事件，
    F-007 的续跑逻辑再推进到 node_completed。
    """
    node_id: str = node.get("id", "<unknown>")
    approval_cfg = node.get("approval") or {}

    # P1-a：schema 字段 message / gate_message 优先；legacy prompt 兜底
    raw_prompt: str = (
        approval_cfg.get("message")
        or approval_cfg.get("gate_message")
        or approval_cfg.get("prompt", "")
    )
    # 传 run_state.node_outputs 让 prompt 中 $<nodeId>.output[.field] 引用能解析（env 走 ENV_VAR 路径覆盖不到 .output 后缀）
    rendered_prompt = substitute_vars(raw_prompt, run_state.node_outputs, env)

    append_event(jsonl_path, {
        "type": "approval_pending",
        "node_id": node_id,
        "data": {"prompt": rendered_prompt},
    })

    return DispatchResult(outcome="approval_pending")


def _read_last_loop_iteration_outcome(jsonl_path: Path, node_id: str) -> str | None:
    """反扫 jsonl，找最后一条 loop_iteration_completed 事件中该 node_id 的 data.outcome。

    Bug-14 修复：interactive 模式 dispatcher 根据上一轮 outcome 决定终止/继续。
    返回 None 表示无对应事件或 outcome 字段缺失。
    """
    if not jsonl_path.exists():
        return None
    try:
        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if evt.get("type") == "loop_iteration_completed" and evt.get("node_id") == node_id:
            return (evt.get("data") or {}).get("outcome")
    return None


def _resolve_loop_prompt_text(loop_cfg: dict, node_id: str, repo_root: Optional[Path] = None) -> str:
    """读取 loop.prompt（inline）或 loop.prompt_file（外置文件）。

    Bug-14 修复：interactive loop 节点需要 prompt 文本提供给 Claude。
    Bug-19 同源修复：repo_root 参数对齐 _dispatch_prompt_node，避免 fixture 注入失效。
    """
    if "prompt" in loop_cfg:
        return loop_cfg["prompt"]
    if "prompt_file" in loop_cfg:
        from workflow_loader import _resolve_prompt_file
        prompt_path = _resolve_prompt_file(loop_cfg["prompt_file"], repo_root=repo_root)
        try:
            return prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise WorkflowError(
                f"loop prompt_file not found: {prompt_path}"
            ) from exc
    raise WorkflowError(
        f"interactive loop 节点 {node_id!r} 需配 loop.prompt 或 loop.prompt_file"
    )


def _dispatch_loop_interactive(
    node: dict,
    env: dict[str, Any],
    run_state: RunState,
    jsonl_path: Path,
    node_id: str,
    loop_cfg: dict,
    max_iterations: int,
    current_iteration: int,
    root: Optional[Path] = None,
) -> DispatchResult:
    """interactive=true 时的 loop 节点派发（Bug-14 修复主体）。

    决策顺序：
      1. 上一轮 outcome=all_done → loop_completed + node_completed → loop_done
      2. counter ≥ max_iterations → loop_max_iterations_exceeded + node_completed → loop_done
      3. 否则 → loop_iteration_started + node_ready{loop_iteration, prompt} → awaiting_claude_action

    Claude 干完本轮活后必须调:
      save_node_result --kind=loop_iteration --output='{"outcome":"continue"|"all_done"}'
    写入 loop_iteration_completed{iteration, outcome}（continue 时附带 loop_counter_advanced）。
    """
    # 1) Claude 已声明 all_done → 终止
    last_outcome = _read_last_loop_iteration_outcome(jsonl_path, node_id)
    if last_outcome == "all_done":
        append_event(jsonl_path, {
            "type": "loop_completed",
            "node_id": node_id,
            "data": {"iteration": current_iteration},
        })
        append_event(jsonl_path, {
            "type": "node_completed",
            "node_id": node_id,
            "data": {
                "output": "",
                "loop_done": True,
                "iteration": current_iteration,
            },
        })
        return DispatchResult(outcome="loop_done")

    # 2) max_iterations 兜底终止
    if current_iteration >= max_iterations:
        append_event(jsonl_path, {
            "type": "loop_max_iterations_exceeded",
            "node_id": node_id,
            "data": {
                "max_iterations": max_iterations,
                "iteration": current_iteration,
            },
        })
        append_event(jsonl_path, {
            "type": "node_completed",
            "node_id": node_id,
            "data": {
                "output": "",
                "loop_done": True,
                "max_iterations_exceeded": True,
                "iteration": current_iteration,
            },
        })
        return DispatchResult(outcome="loop_done")

    # 3) 进入新一轮：渲染 prompt + 写 node_ready + 等 Claude
    raw_prompt = _resolve_loop_prompt_text(loop_cfg, node_id, repo_root=root)
    loop_env = {
        **env,
        "LOOP_ITERATION": str(current_iteration),
        "LOOP_PREV_OUTPUT": str(env.get("LOOP_PREV_OUTPUT", "")),
        "LOOP_USER_INPUT": str(env.get("LOOP_USER_INPUT", "")),
    }
    rendered = substitute_vars(
        raw_prompt, run_state.node_outputs, loop_env, escape_for_bash=False
    )

    append_event(jsonl_path, {
        "type": "loop_iteration_started",
        "node_id": node_id,
        "data": {"iteration": current_iteration},
    })
    contract = _build_external_action_contract(node)
    append_event(jsonl_path, {
        "type": "node_ready",
        "node_id": node_id,
        "run_id": run_state.run_id,
        "data": {
            "node_kind": "loop_iteration",
            "prompt": rendered,
            "loop_iteration": current_iteration,
            "external_action_contract": contract,
        },
    })
    return DispatchResult(outcome="awaiting_claude_action")


def _dispatch_loop_node(
    node: dict,
    env: dict[str, Any],
    run_state: RunState,
    jsonl_path: Path,
    root: Path = Path("."),
) -> DispatchResult:
    """Loop 节点：迭代计数从 run_state.loop_counters[node_id] 读取。

    AC-07 扩展：
    - 新增 node["loop"]["until_bash"]: str 字段
    - 每轮迭代前先跑 until_bash；exit=0 → loop_completed + outcome=loop_done
    - exit≠0 → 继续既有 loop_iteration_started/completed 路径
    - 达到 max_iterations → loop_max_iterations_exceeded + outcome=loop_done
    - until_bash timeout（30s） → error 写 data.error = "timeout: <cmd>"，按 max_iterations 兜底
    - until_bash 不传 → 完全走既有路径（保护 F-011 历史行为）

    Bug-14 修复：interactive=true 时走交互路径，每轮写 node_ready + 等 Claude
    通过 save_node_result --kind=loop_iteration 写 loop_iteration_completed{outcome}。

    约束：
    - data["iteration"] 必须存在，供 RunState.rebuild 中 loop_counters 累计消费
    - max_iterations 取自 node["loop"]["max_iterations"]；缺省视为 1
    """
    import os  # 用于注入 iter 环境变量

    node_id: str = node.get("id", "<unknown>")
    loop_cfg: dict = node.get("loop") or {}
    max_iterations: int = int(loop_cfg.get("max_iterations", 1))
    until_bash: str | None = loop_cfg.get("until_bash")
    interactive: bool = bool(loop_cfg.get("interactive"))

    # 当前迭代索引（0-based）：首次不在 loop_counters 中，取 0
    current_iteration: int = run_state.loop_counters.get(node_id, 0)

    # Bug-14：interactive=true → 走交互式路径（不走 until_bash / 既有路径）
    if interactive:
        return _dispatch_loop_interactive(
            node, env, run_state, jsonl_path,
            node_id, loop_cfg, max_iterations, current_iteration,
            root=root,
        )

    # AC-07：until_bash 优先判定（仅在传入时生效）
    if until_bash:
        rendered_until = substitute_vars(
            until_bash, run_state.node_outputs, env, escape_for_bash=False
        )
        try:
            proc = subprocess.run(
                ["bash", "-c", rendered_until],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=30.0,
                env={**os.environ, "iter": str(current_iteration)},
            )
            if proc.returncode == 0:
                # exit=0 → until 条件成立，跳过本轮迭代直接完成
                append_event(jsonl_path, {
                    "type": "loop_completed",
                    "node_id": node_id,
                    "data": {"iteration": current_iteration},
                })
                # loop_done 也属于节点完成生命周期：补写 node_completed 让 rebuild
                # 能把 loop 节点标 SUCCESS_TERMINAL，避免 bootstrap 把它当 ready 重派。
                # 对齐 completed / sub_workflow_done 两个 outcome 的 jsonl 写入语义。
                append_event(jsonl_path, {
                    "type": "node_completed",
                    "node_id": node_id,
                    "data": {"output": "", "loop_done": True,
                              "iteration": current_iteration},
                })
                return DispatchResult(outcome="loop_done")
            # exit≠0 → 条件不成立，继续走迭代路径
        except subprocess.TimeoutExpired:
            # timeout 不视为 loop_done，继续走迭代路径；error 记录在 completed 事件
            _write_loop_iteration_with_error(
                jsonl_path, node_id, current_iteration,
                f"timeout: {rendered_until}",
            )
            return _loop_check_max_or_continue(
                node_id, current_iteration, max_iterations, jsonl_path
            )
        except OSError as exc:
            _write_loop_iteration_with_error(
                jsonl_path, node_id, current_iteration, f"oserror: {exc}",
            )
            return _loop_check_max_or_continue(
                node_id, current_iteration, max_iterations, jsonl_path
            )

    # 既有路径（until_bash 不传，或 until_bash exit≠0 时）
    append_event(jsonl_path, {
        "type": "loop_iteration_started",
        "node_id": node_id,
        "data": {"iteration": current_iteration},
    })

    append_event(jsonl_path, {
        "type": "loop_iteration_completed",
        "node_id": node_id,
        "data": {"iteration": current_iteration},
    })

    # 已完成 current_iteration 轮（0-based），下一轮编号为 current_iteration + 1
    return _loop_check_max_or_continue(
        node_id, current_iteration, max_iterations, jsonl_path
    )


def _write_loop_iteration_with_error(
    jsonl_path: Path,
    node_id: str,
    iteration: int,
    error: str,
) -> None:
    """写 loop_iteration_started + loop_iteration_completed（含 error 字段）。"""
    append_event(jsonl_path, {
        "type": "loop_iteration_started",
        "node_id": node_id,
        "data": {"iteration": iteration},
    })
    append_event(jsonl_path, {
        "type": "loop_iteration_completed",
        "node_id": node_id,
        "data": {"iteration": iteration, "error": error},
    })


def _loop_check_max_or_continue(
    node_id: str,
    current_iteration: int,
    max_iterations: int,
    jsonl_path: Path,
) -> DispatchResult:
    """达到 max_iterations → 写 loop_max_iterations_exceeded + outcome=loop_done；
    否则 → outcome=loop_continue。
    """
    if current_iteration + 1 >= max_iterations:
        append_event(jsonl_path, {
            "type": "loop_max_iterations_exceeded",
            "node_id": node_id,
            "data": {"max_iterations": max_iterations, "iteration": current_iteration},
        })
        # 与 until_bash exit=0 路径对称：loop_done 必须伴随 node_completed，
        # 否则 rebuild 时 loop 节点缺 SUCCESS_TERMINAL 标记，bootstrap 反复重派。
        append_event(jsonl_path, {
            "type": "node_completed",
            "node_id": node_id,
            "data": {"output": "", "loop_done": True,
                      "max_iterations_exceeded": True,
                      "iteration": current_iteration},
        })
        return DispatchResult(outcome="loop_done")
    return DispatchResult(outcome="loop_continue")


def _dispatch_sub_workflow_node(
    node: dict,
    run_state: RunState,
    run_dir: Path,
    root: Path,
    jsonl_path: Path,
) -> DispatchResult:
    """Sub-workflow 节点：派子 run **直接落在** run_dir/sub_runs/<node_id>/。

    逻辑（F-011 最小实现 + codex 2026-05-12 P1-2 + P2 修订）：
    1. 解析 node["sub_workflow"]["template"] 取模板 ID
    2. 子 run 目录固定为 run_dir/sub_runs/<node_id>/（与 workflow_status:42 / workflow_rollback_subrun:81
       共用约定：目录名即子 run id）
    3. **重复派发守卫**（P1-2）：sub_run_dir/.dispatched 标记存在 → 直接回 pending，不再二次写 jsonl
    4. **P2 修订**：不再调 workflow_run.main——后者会另起 runs/<auto_id>/ 目录与父子约定脱节，导致
       /workflow:status 把 node_id 当 run_id 渲染却找不到真 jsonl，rollback 也无 run-state 可归档。
       改为在 sub_run_dir 内直接写 meta.yaml + run-state.jsonl，sub_run_id=node_id，保持与
       rollback_subrun:164（child_run_id = child_run_dir.name）一致。
    5. 写 .dispatched 标记 + 返回 outcome="sub_workflow_pending"

    深度联动（多级嵌套 + 子 run 完成回填）留后续 REQ，本 feature 仅最小实现。

    参数 env 旧位置改为 run_state（携带父 run_id 写入 meta + jsonl 供追溯）；env 字典本身在
    本节点暂未使用，回归通过 dispatch_node 调用点同步替换。
    """
    node_id: str = node.get("id", "<unknown>")
    sub_cfg: dict = node.get("sub_workflow") or {}
    template_id: str = sub_cfg.get("template", "")
    if not template_id:
        raise WorkflowError(f"sub_workflow 节点 {node_id!r} 缺少 template 字段")

    # 子 run 目录：与 workflow_status / workflow_rollback_subrun 约定一致
    sub_run_dir = run_dir / "sub_runs" / node_id
    sub_run_dir.mkdir(parents=True, exist_ok=True)

    # P1-2 重复派发守卫：标记文件存在 → 子 run 已派发过，直接回 pending
    dispatched_marker = sub_run_dir / ".dispatched"
    if dispatched_marker.exists():
        return DispatchResult(outcome="sub_workflow_pending")

    # 校验模板存在性（不走全量 schema 校验——子 run 的 /workflow:continue 时再 load_workflow）
    workflow_dir = root / ".claude" / "workflows"
    candidates = list(workflow_dir.glob(f"**/{template_id}.yaml"))
    if not candidates:
        raise WorkflowError(
            f"sub_workflow 节点 {node_id!r} 模板 {template_id!r} 未在 .claude/workflows/ 找到"
        )
    template_path = candidates[0]

    args = sub_cfg.get("args", "")
    sub_run_id = node_id  # 与 sub_runs/<node_id>/ 目录名一致
    parent_run_id = run_state.run_id

    # 子 run meta.yaml：key=template_path 与 _run_generic 对齐（P1 新 codex finding 已修
    # workflow_continue._load_workflow_for_run 读取同名 key）
    ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {
        "run_id": sub_run_id,
        "template": template_id,
        "template_path": str(template_path.relative_to(root)),
        "arguments": args,
        "state": "running",
        "start_ts": ts_now,
        "parent_run_id": parent_run_id,
    }
    try:
        import yaml  # type: ignore  # yaml 已是项目硬依赖
        with (sub_run_dir / "meta.yaml").open("w", encoding="utf-8") as fh:
            yaml.safe_dump(meta, fh, allow_unicode=True, sort_keys=False)
    except (OSError, ImportError) as exc:
        raise WorkflowError(
            f"sub_workflow 节点 {node_id!r} 写 meta.yaml 失败：{exc}"
        ) from exc

    # 写子 run run-state.jsonl 的 workflow_started 事件（让后续 /workflow:continue <node_id>
    # 能正确 rebuild RunState）
    sub_jsonl = sub_run_dir / "run-state.jsonl"
    append_event(sub_jsonl, {
        "type": "workflow_started",
        "run_id": sub_run_id,
        "data": {
            "workflow_name": template_id,
            "arguments": args,
            "parent_run_id": parent_run_id,
        },
    })

    # 写派发标记（best-effort：失败仅打 warn，不阻断本次成功的派发）
    try:
        dispatched_marker.write_text(template_id, encoding="utf-8")
    except OSError as exc:
        print(
            f"WARN: 写 sub_workflow 派发标记 {dispatched_marker} 失败：{exc}；"
            f"重复派发守卫退化为下一轮 continue 时仍可能重复入节点",
            file=sys.stderr,
        )

    return DispatchResult(outcome="sub_workflow_pending")


# ============================================================================
# artifact 节点 dispatcher（AC-02 第 8 类，F-005 落地）
# ============================================================================

def _dispatch_artifact_node(
    node: dict,
    run_state: RunState,
    root: Path,
    env: dict[str, Any],
    jsonl_path: Path,
) -> DispatchResult:
    """artifact 第 8 类 dispatcher（AC-02）。

    职责：
      - 用 _render_artifact_spec 对 spec 内所有 $VAR 引用做变量展开（escape_for_bash=False）
      - 调 run_artifact_checks.run_artifact_checks(spec, cwd=root) 跑 5 类校验
      - failures 为空 → 写 node_completed（success path）
      - failures 非空 → raise WorkflowError，由外层转 node_failed（D-008 职责分工）

    禁止：
      - 写 node_started（外层已写）
      - 直接写 node_failed（由外层 try/except 兜底）

    Raises:
      WorkflowError: artifact 校验失败（含失败明细列表）
    """
    from run_artifact_checks import run_artifact_checks  # 避免顶层循环导入

    node_id: str = node.get("id", "<unknown>")
    raw_spec = node.get("artifact") or {}
    spec = _render_artifact_spec(raw_spec, run_state, env)
    try:
        failures = run_artifact_checks(spec, cwd=root)
    except (OSError, ValueError) as exc:
        raise WorkflowError(
            f"artifact 节点 {node_id!r} 校验过程异常：{type(exc).__name__}: {exc}"
        ) from exc
    if failures:
        raise WorkflowError(
            f"artifact 节点 {node_id!r} 校验失败：\n  - " + "\n  - ".join(failures)
        )

    # 统计实际校验项数：failures 为空时，spec 内各类目项数之和
    checks_run = sum(
        len(spec.get(k) or [])
        for k in (
            "must_exist", "must_not_exist", "schema_check",
            "must_contain_sections", "must_match_regex",
        )
    )
    append_event(jsonl_path, {
        "type": "node_completed",
        "node_id": node_id,
        "data": {"output": {"artifact_pass": True, "checks_run": checks_run}},
    })
    return DispatchResult(outcome="completed")
