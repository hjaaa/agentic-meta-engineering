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

import copy
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
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
            # env 当前未在 sub_workflow 节点使用；run_state 用于写 parent_run_id 入 sub run meta
            result = _dispatch_sub_workflow_node(node, run_state, run_dir, root, jsonl_path)
        elif "artifact" in node:                          # AC-02 第 8 类
            result = _dispatch_artifact_node(node, run_state, root, env, jsonl_path)
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

    P1-b（codex round-3 2026-05-12）：必须写 node_completed 事件，否则 crash 后
    RunState.rebuild 看不到完成事件，会把节点当 unfinished 重派——破坏 F-010
    AC-05 mock fixture 的真实保证。其他节点类型（skill/prompt/bash）入口处都写了
    node_completed，agent 节点为了对齐补上。
    """
    node_id: str = node.get("id", "<unknown>")
    append_event(jsonl_path, {
        "type": "node_completed",
        "node_id": node_id,
        "data": {"output": ""},  # stub 输出留空；F-010 真接入后由 fixture / 主 Claude 填
    })
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
        "data": {"iteration": current_iteration},
    })

    append_event(jsonl_path, {
        "type": "loop_iteration_completed",
        "node_id": node_id,
        "data": {"iteration": current_iteration},
    })

    # 已完成 current_iteration 轮（0-based），下一轮编号为 current_iteration + 1
    if current_iteration + 1 >= max_iterations:
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

def _render_list_field(items: list, fn) -> list:
    """渲染 must_exist / must_not_exist 列表（每项 str，调 fn 展开）。"""
    return [fn(item) if isinstance(item, str) else item for item in items]


def _render_schema_check_items(items: list, fn) -> list:
    """渲染 schema_check 列表项的 script + args[] 字段。"""
    rendered = []
    for chk in items:
        new_chk = dict(chk)
        if isinstance(new_chk.get("script"), str):
            new_chk["script"] = fn(new_chk["script"])
        if isinstance(new_chk.get("args"), list):
            new_chk["args"] = _render_list_field(new_chk["args"], fn)
        rendered.append(new_chk)
    return rendered


def _render_must_contain_items(items: list, fn) -> list:
    """渲染 must_contain_sections 列表项的 file + sections[] 字段。"""
    rendered = []
    for chk in items:
        new_chk = dict(chk)
        if isinstance(new_chk.get("file"), str):
            new_chk["file"] = fn(new_chk["file"])
        if isinstance(new_chk.get("sections"), list):
            new_chk["sections"] = _render_list_field(new_chk["sections"], fn)
        rendered.append(new_chk)
    return rendered


def _render_must_match_items(items: list, fn) -> list:
    """渲染 must_match_regex 列表项的 file + pattern 字段。"""
    rendered = []
    for chk in items:
        new_chk = dict(chk)
        if isinstance(new_chk.get("file"), str):
            new_chk["file"] = fn(new_chk["file"])
        if isinstance(new_chk.get("pattern"), str):
            new_chk["pattern"] = fn(new_chk["pattern"])
        rendered.append(new_chk)
    return rendered


def _make_spec_expander(run_state: RunState, env: dict[str, Any]):
    """构造 artifact spec $VAR 展开函数（escape_for_bash=False，路径类变量用裸字面值）。"""
    def _s(text: str) -> str:
        return substitute_vars(text, run_state.node_outputs, env, escape_for_bash=False)
    return _s


# 已知的 5 类可展开 spec 字段（key → helper 函数）；主函数按此表分发，其余字段 deepcopy 保留
_SPEC_RENDER_MAP = {
    "must_exist": _render_list_field,
    "must_not_exist": _render_list_field,
    "schema_check": _render_schema_check_items,
    "must_contain_sections": _render_must_contain_items,
    "must_match_regex": _render_must_match_items,
}


def _render_artifact_spec(spec: dict, run_state: RunState, env: dict[str, Any]) -> dict:
    """对 artifact spec 内 $VAR 引用做 substitute_vars 展开（5 类字段）。

    生产 yaml 字段全集 = {must_exist, schema_check, must_contain_sections}（已知）
    + 设计层 must_not_exist / must_match_regex 也覆盖（防御性）。
    「其余字段原样保留」路径走 deepcopy 防 mutation 共享（F-CR2-004 修复）。
    """
    fn = _make_spec_expander(run_state, env)
    rendered: dict = {}
    for key, helper in _SPEC_RENDER_MAP.items():
        if key in spec:
            rendered[key] = helper(spec[key] or [], fn)
    for key, val in spec.items():
        if key not in rendered:
            rendered[key] = copy.deepcopy(val)
    return rendered


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
    failures = run_artifact_checks(spec, cwd=root)
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
