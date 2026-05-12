"""workflow continue 命令入口（F-005 框架 + F-007 main loop 最小骨架 + F-008 失败矩阵）。

/workflow:continue [<run-id>]

反扫 jsonl 重建 RunState，做状态校验，进 main loop（F-008 扩展为完整 7 outcome 覆盖：
completed / failed / approval_pending / loop_continue / loop_done / sub_workflow_pending /
sub_workflow_done；F-008 接入失败矩阵 retry/skip/abort；F-011 接入 loop / sub_workflow）。

详细设计 §1.7。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import REPO_ROOT, WorkflowError, infer_run_id_from_branch  # noqa: E402
from run_state import RunState, _resolve_run_dir, append_event, read_events  # noqa: E402
from workflow_state_validator import validate_state_for_cmd  # noqa: E402
from workflow_loader import load_workflow  # noqa: E402


def _build_node_map(workflow: dict) -> dict[str, dict]:
    """从 workflow dict 构造 node_id → node dict 的映射。

    workflow 结构：{"nodes": [{"id": "...", ...}, ...]}
    """
    nodes: list[dict] = workflow.get("nodes", [])
    return {node.get("id"): node for node in nodes if node.get("id")}


def _next_node(
    current_node: dict,
    hint: str | None,
) -> str | None:
    """确定下一个节点 ID。

    优先级：
      1. hint 非 None 时返回 hint（显式覆盖，e.g. on_reject）
      2. 否则读 current_node.next（若存在）
      3. 否则返回 None（拓扑末尾）

    注：F-008 接入显式跳转（on_failure / on_skip）时，由调用方计算 hint 后传入；
    node_map 不由本函数持有，保持职责单一。
    """
    if hint is not None:
        return hint
    return current_node.get("next")


def _handle_retry(
    run_state: RunState,
    node: dict,
    jsonl_path: Path,
    error: str | None,
) -> bool:
    """retry 策略：统计已失败次数，未达上限则静默等待下次续跑，超出则升级为 abort。

    参照 workflow_dispatcher.py:185-200 _dispatch_skill_node 风格编写。

    返回值：False（调用方应 break，等待下次 continue 或因 abort 终结）。

    注意：dispatcher 已写 node_failed 事件，此处不重复写；
         超上限时才追加 workflow_failed 事件。
    """
    node_id = node["id"]
    # F-5：保留 warnings，暴露 jsonl 损坏行（损坏行会导致 fail_count 偏低）
    events, warnings = read_events(jsonl_path)
    if warnings:
        print(
            f"WARN: jsonl 含 {len(warnings)} 行损坏，retry 计数可能偏低: {warnings}",
            file=sys.stderr,
        )
    # node_failed 事件由 dispatcher 写入，node_id 在事件顶层（与 run_state.rebuild 读法一致）
    fail_count = sum(
        1 for evt in events
        if evt.get("type") == "node_failed" and evt.get("node_id") == node_id
    )
    max_retries: int = node.get("max_retries", 3)

    if fail_count < max_retries:
        # 未到重试上限：current_node 保持（下次 continue 自动从该节点重派）
        print(
            f"INFO: 节点 {node_id!r} 失败（第 {fail_count} 次），"
            f"将重试（max_retries={max_retries}）",
            file=sys.stderr,
        )
        return False

    # 超出重试上限：升级为 abort，写 workflow_failed 事件
    print(
        f"WARN: 节点 {node_id!r} 重试次数已达上限 {max_retries}，升级为 abort",
        file=sys.stderr,
    )
    append_event(
        jsonl_path,
        {
            "type": "workflow_failed",
            "data": {
                "node_id": node_id,
                "error": error or f"节点 {node_id!r} 超出最大重试次数 {max_retries}",
                "reason": "retry_exhausted",
            },
        },
    )
    run_state.state = "failed"
    return False


def _handle_skip(
    run_state: RunState,
    node: dict,
    jsonl_path: Path,
    error: str | None,
) -> bool:
    """skip 策略：写 node_skipped 事件，推进 current_node，返回 True（主循环继续）。

    参照 workflow_dispatcher.py:185-200 _dispatch_skill_node 风格编写。

    返回值：True（调用方应继续循环，推进到下一节点）。

    注意：node_skipped.data.reason 遵循 spec §2.1，记录实际错误信息。
    """
    node_id = node["id"]
    # node_skipped 事件：node_id 在顶层（与 run_state.rebuild 读法一致）
    append_event(
        jsonl_path,
        {
            "type": "node_skipped",
            "node_id": node_id,
            "data": {
                "reason": error or "on_failure=skip 但无具体错误",
            },
        },
    )
    # 更新 node_outputs（状态=skipped）
    run_state.node_outputs[node_id] = {
        "output": None,
        "state": "skipped",
        "data": {"reason": error or "on_failure=skip 但无具体错误"},
    }
    next_id = _next_node(node, None)
    run_state.current_node = next_id
    print(
        f"INFO: 节点 {node_id!r} 跳过（on_failure=skip），推进到 {next_id!r}",
        file=sys.stderr,
    )
    return True


def _handle_abort(
    run_state: RunState,
    node: dict,
    jsonl_path: Path,
    error: str | None,
    on_failure: str,
) -> bool:
    """abort 策略（或未知策略降级为 abort）：写 workflow_failed 事件，终结 run。

    参照 workflow_dispatcher.py:185-200 _dispatch_skill_node 风格编写。

    返回值：False（调用方应 break，run 终结）。

    注意：未知策略先打 WARN，再走 abort 路径。
    """
    node_id = node["id"]
    if on_failure != "abort":
        print(
            f"WARN: 未知 on_failure 策略 {on_failure!r}，降级为 abort",
            file=sys.stderr,
        )
    append_event(
        jsonl_path,
        {
            "type": "workflow_failed",
            "data": {
                "node_id": node_id,
                "error": error or f"节点 {node_id!r} 执行失败（abort）",
                "reason": "node_failed",
            },
        },
    )
    run_state.state = "failed"
    return False


def _handle_failure(
    run_state: RunState,
    node: dict,
    on_failure: str,
    jsonl_path: Path,
    error: str | None,
) -> bool:
    """按 on_failure 策略路由到对应助手函数。

    返回值语义：
      True  → 调用方继续循环（_handle_skip 成功推进）
      False → 调用方 break（_handle_retry 等待下次 / _handle_abort 终结 workflow）

    注意：dispatcher 已写 node_failed 事件，本函数不重复写；
         仅通过助手函数写 node_skipped / workflow_failed 两类新事件。
    """
    if on_failure == "retry":
        return _handle_retry(run_state, node, jsonl_path, error)
    elif on_failure == "skip":
        return _handle_skip(run_state, node, jsonl_path, error)
    else:
        return _handle_abort(run_state, node, jsonl_path, error, on_failure)


def _advance_after_completed(
    run_state: RunState,
    node: dict,
    result: "DispatchResult",  # type: ignore[name-defined]  # noqa: F821
) -> None:
    """completed / loop_done / sub_workflow_done 场景的公用推进逻辑。

    - 更新 node_outputs（outcome=completed 时记录 output；其余场景 output 可能为 None）
    - 推进 current_node → _next_node(node, result.next_node_hint)
    """
    node_id = node["id"]
    run_state.node_outputs[node_id] = {
        "output": result.output,
        "state": "completed",
        "data": {"output": result.output},
    }
    next_id = _next_node(node, result.next_node_hint)
    run_state.current_node = next_id


def _route_outcome(
    run_state: RunState,
    node: dict,
    result: "DispatchResult",  # type: ignore[name-defined]  # noqa: F821
    jsonl_path: Path,
) -> bool:
    """将 dispatch_node 返回的 outcome 路由到对应处理逻辑。

    返回值：True=继续循环（while 条件仍满足），False=立即 break。

    路由表（dispatcher 已写的事件不在此重复）：
      completed          → _advance_after_completed（推进 current_node）→ True
      loop_continue      → loop_counters += 1 + 写 loop_counter_advanced 事件，
                           current_node 不变 → True
      loop_done          → _advance_after_completed（推进 current_node）→ True
      sub_workflow_done  → _advance_after_completed（推进 current_node）→ True
      approval_pending   → state=approval_pending → False
      sub_workflow_pending → state 保持 running → False（等待子 workflow 回调）
      failed             → _handle_failure 返回值（retry/skip/abort 决定）
      未知 outcome       → 写 workflow_failed，state=failed → False
    """
    outcome = result.outcome
    node_id = node["id"]

    if outcome == "completed":
        # node_completed 事件已由 dispatcher 写入；仅更新 RunState + 推进指针
        _advance_after_completed(run_state, node, result)
        return True

    elif outcome == "loop_continue":
        # 循环节点继续迭代：递增计数器并写 loop_counter_advanced 事件。
        # 仅内存 +1 在 crash 后会被 rebuild 漏读，导致 dispatcher 用旧 iteration 重派同一轮。
        new_value = run_state.loop_counters.get(node_id, 0) + 1
        run_state.loop_counters[node_id] = new_value
        append_event(
            jsonl_path,
            {
                "type": "loop_counter_advanced",
                "node_id": node_id,
                "data": {"new_value": new_value},
            },
        )
        return True

    elif outcome in ("loop_done", "sub_workflow_done"):
        # 循环/子 workflow 完成：推进到下一节点
        _advance_after_completed(run_state, node, result)
        return True

    elif outcome == "approval_pending":
        # 派发器已写 approval_pending 事件；main loop 仅设置状态并退出
        run_state.state = "approval_pending"
        return False

    elif outcome == "sub_workflow_pending":
        # 子 workflow 已发起但尚未完成；state 保持 running，等待回调续跑
        return False

    elif outcome == "failed":
        # 按 on_failure 策略路由：retry / skip / abort
        on_failure: str = node.get("on_failure", "retry")
        return _handle_failure(run_state, node, on_failure, jsonl_path, result.error)

    else:
        # 未知 outcome（防御性兜底）：写 workflow_failed，避免 state 留 running 引发静默死循环
        append_event(
            jsonl_path,
            {
                "type": "workflow_failed",
                "data": {
                    "node_id": node_id,
                    "error": f"未知 outcome: {outcome!r}",
                },
            },
        )
        run_state.state = "failed"
        return False


def _main_loop(
    run_state: RunState,
    workflow: dict,
    run_dir: Path,
    root: Path,
    jsonl_path: Path,
) -> None:
    """主循环（F-008）：完整 7 outcome 路由表 + 失败矩阵。

    算法：
      while state == running and current_node:
        - 按 node 类型派发（dispatch_node 已写 node_started + node_completed/node_failed 事件）
        - 调用 _route_outcome 按 outcome 路由处理；返回 False 则 break
    """
    from workflow_dispatcher import _build_env, dispatch_node

    node_map = _build_node_map(workflow)

    while run_state.state == "running" and run_state.current_node:
        node = node_map.get(run_state.current_node)
        if node is None:
            # 未知节点（理论上不应发生；容错处理）
            append_event(
                jsonl_path,
                {
                    "type": "workflow_failed",
                    "data": {"error": f"未知节点 {run_state.current_node}"},
                },
            )
            run_state.state = "failed"
            break

        # 构建环境变量并派发节点（dispatcher 已写 node_started + node_completed/node_failed）
        env = _build_env(run_state, run_dir, root)
        result = dispatch_node(node, run_state, run_dir, root, env, jsonl_path)

        # 按 outcome 路由（False=break, True=继续循环）
        should_continue = _route_outcome(run_state, node, result, jsonl_path)
        if not should_continue:
            break


def _setup_run(
    run_id: str,
    root: Path,
) -> tuple["RunState", Path, Path]:
    """读 jsonl + rebuild RunState 的前置准备。

    仅 _resolve_run_dir 失败时抛 WorkflowError；read_events 内部把 OSError 转为
    warnings 列表返回，RunState.rebuild 不涉及 IO 也不抛异常。

    返回: (run_state, run_dir, jsonl_path)

    注：状态矩阵校验（validate_state_for_cmd）和 run_resumed 事件写入由 _resume_run()
    统一承担，保持各步骤职责清晰。
    """
    # D-007 双路径解析
    run_dir = _resolve_run_dir(run_id, root)
    jsonl_path = run_dir / "run-state.jsonl"
    events, warnings = read_events(jsonl_path)
    run_state = RunState.rebuild(events, run_id=run_id, warnings=warnings)
    return run_state, run_dir, jsonl_path


def _resume_run(run_id: str, run_state: "RunState", jsonl_path: Path) -> int:
    """校验状态矩阵并写 run_resumed 审计事件。

    返回 0（成功）或 1（状态不允许 / 事件写失败）。

    将 validate_state_for_cmd + append_event 合并，减少 main() 中的 try/except 块数量。
    """
    try:
        validate_state_for_cmd("continue", run_id, run_state.state)
    except WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # run_resumed 不映射 WORKFLOW_EVENT_TO_STATE，保持原 state 语义不变（详细设计 §1.2）
    try:
        append_event(jsonl_path, {"type": "run_resumed", "run_id": run_id})
    except WorkflowError as exc:
        # G-11：审计事件写失败与 cancel_requested 同级处理，exit 1 让调用方感知
        # 对照 cancel.py:93 写 cancel_requested 失败 exit 1 的统一处理策略
        print(f"ERROR: 写 run_resumed 审计事件失败：{exc}", file=sys.stderr)
        return 1

    return 0


def _load_workflow_for_run(
    run_state: "RunState",
    run_dir: Path,
    root: Path,
) -> dict | None:
    """根据 run_state 推断 workflow 名称并加载 workflow dict。

    查找优先级：
      1. 约定路径：.claude/workflows/requirement/<name>.yaml
      2. 降级路径：从 requirements/<id>/meta.yaml 读 workflow_template_path

    降级失败（OSError / YAMLError）时打 WARN 并仍走原约定路径兜底，
    不直接 return None——让后续 load_workflow 给出明确错误，而非静默空结果。

    返回 workflow dict；加载失败时返回 None（已打 ERROR）。
    """
    workflow_name = run_state.workflow_name
    if not workflow_name:
        print("ERROR: 无法确定 workflow 名称（workflow_started 事件缺失）", file=sys.stderr)
        return None

    # 约定路径：.claude/workflows/requirement/<name>.yaml
    workflow_path = root / ".claude" / "workflows" / "requirement" / f"{workflow_name}.yaml"
    if not workflow_path.exists():
        # 降级查找：尝试从 requirements/<id>/meta.yaml 读 workflow_template_path
        # 降级失败时写 WARN 到 stderr 留排查线索，但仍以原 workflow_path 兜底
        meta_path = run_dir / "meta.yaml"
        if meta_path.exists():
            try:
                meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
                workflow_path = root / meta.get("workflow_template_path", str(workflow_path))
            except (OSError, yaml.YAMLError) as exc:
                print(f"WARN: 读 meta.yaml 降级 workflow_path 失败：{exc}", file=sys.stderr)

    result = load_workflow(workflow_path)
    if result.report.errors:
        print(f"ERROR: 加载 workflow 失败\n{result.report.render()}", file=sys.stderr)
        return None

    workflow = result.workflow
    if not workflow:
        print("ERROR: workflow 加载失败（返回值为 None）", file=sys.stderr)
        return None

    return workflow


def main(args: list[str], repo_root: Path | None = None) -> int:
    """continue 命令主入口。

    参数：
        args      — [run_id?]（可选）
        repo_root — 注入 repo 根路径（测试用）

    返回：exit code（0 成功，1 失败）
    """
    root = repo_root or REPO_ROOT

    run_id = args[0] if args else infer_run_id_from_branch(root)
    if not run_id:
        print(
            "ERROR: 无法推断 run_id\n"
            "请提供 run_id 或确保当前分支为 feat/req-<id> 格式",
            file=sys.stderr,
        )
        return 1

    try:
        run_state, run_dir, jsonl_path = _setup_run(run_id, root)
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    rc = _resume_run(run_id, run_state, jsonl_path)
    if rc != 0:
        return rc

    print(f"恢复 workflow run {run_id!r}（state={run_state.state}）")

    workflow = _load_workflow_for_run(run_state, run_dir, root)
    if workflow is None:
        return 1

    # 调用 main loop；WorkflowError 由此捕获，让 main() 返回统一 ERROR 而非裸 traceback
    # 注：tests/skills/test_workflow_commands.py 直接调用 main()，不走 __main__ 兜底
    try:
        _main_loop(run_state, workflow, run_dir, root, jsonl_path)
    except WorkflowError as exc:
        print(f"ERROR: main loop 异常退出：{exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:] if len(sys.argv) > 1 else []))
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
