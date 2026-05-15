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
from run_state import (  # noqa: E402
    RunState,
    _resolve_run_dir,
    append_event,
    read_events,
)
from workflow_state_validator import validate_state_for_cmd  # noqa: E402
from workflow_loader import load_workflow  # noqa: E402
from workflow_scheduler import (  # noqa: E402
    _finalize_after_rebuild_if_last_topology_node,
    _next_node,
    _select_next_dispatch_target,
)
from workflow_outcome_router import _route_outcome  # noqa: E402
import path_lock  # noqa: E402


def _build_node_map(workflow: dict) -> dict[str, dict]:
    """从 workflow dict 构造 node_id → node dict 的映射。

    workflow 结构：{"nodes": [{"id": "...", ...}, ...]}
    """
    nodes: list[dict] = workflow.get("nodes", [])
    return {node.get("id"): node for node in nodes if node.get("id")}


# ============================================================================
# F-011：sub_workflow 父子完成回填（AC-08）
# ============================================================================

def _handle_child_completed(
    node_id: str,
    jsonl_path: Path,
    run_state: RunState,
) -> None:
    """子 workflow_completed → 父写 child_graceful_exited + node_completed。

    调用方已保证父节点未关闭（幂等守卫在 _poll_sub_workflows）。
    任一 append_event 的 OSError → 包成 WorkflowError 向上抛（fail-closed）。
    """
    try:
        append_event(jsonl_path, {
            "type": "child_graceful_exited",
            "node_id": node_id,
            "data": {
                "sub_run_id": node_id,
                "sub_terminal_event": "workflow_completed",
                "on_subworkflow_failure": None,
            },
        })
        append_event(jsonl_path, {
            "type": "node_completed",
            "node_id": node_id,
            "data": {"output": "", "sub_workflow_done": True},
        })
    except WorkflowError as exc:
        raise WorkflowError(
            f"_poll_sub_workflows append_event failed: {exc}"
        ) from exc
    # 更新内存 RunState（避免重复回填 + 让 finalize 可识别拓扑完成）
    run_state.node_outputs[node_id] = {
        "output": "",
        "state": "completed",
        "data": {"output": "", "sub_workflow_done": True},
    }
    if run_state.current_node == node_id:
        run_state.current_node = None


def _handle_child_failed_by_policy(
    node_id: str,
    on_failure: str,
    jsonl_path: Path,
    run_state: RunState,
) -> None:
    """子 workflow_failed → 按 on_subworkflow_failure 策略写父事件三件套。

    # abort 语义实现为 on_subworkflow_failure='fail'，沿用 workflow_loader.ALLOWED_ON_SUB_FAILURE 真值源
    策略：
    - skip     → child_failed + node_skipped
    - fail     → child_failed + node_failed + workflow_failed（scheduler 不再推进）
    - continue → child_failed + node_completed（继续下游）

    任一 append_event 的 OSError → 包成 WorkflowError 向上抛（fail-closed）。
    """
    try:
        append_event(jsonl_path, {
            "type": "child_failed",
            "node_id": node_id,
            "data": {
                "sub_run_id": node_id,
                "sub_terminal_event": "workflow_failed",
                "on_subworkflow_failure": on_failure,
            },
        })

        if on_failure == "skip":
            append_event(jsonl_path, {
                "type": "node_skipped",
                "node_id": node_id,
                "data": {"reason": "child_failed", "on_subworkflow_failure": on_failure},
            })
            run_state.node_outputs[node_id] = {
                "output": "",
                "state": "skipped",
                "data": {"reason": "child_failed", "on_subworkflow_failure": on_failure},
            }
        elif on_failure == "fail":
            append_event(jsonl_path, {
                "type": "node_failed",
                "node_id": node_id,
                "data": {"reason": "child_failed", "on_subworkflow_failure": on_failure},
            })
            # 写 workflow_failed 前先判断是否已 failed（幂等守卫）
            if run_state.state != "failed":
                append_event(jsonl_path, {
                    "type": "workflow_failed",
                    "data": {
                        "node_id": node_id,
                        "error": f"sub_workflow {node_id!r} failed，on_subworkflow_failure=fail",
                    },
                })
                run_state.state = "failed"
            run_state.node_outputs[node_id] = {
                "output": "",
                "state": "failed",
                "data": {"reason": "child_failed", "on_subworkflow_failure": on_failure},
            }
        else:
            # continue 分支：子失败但父继续下游
            append_event(jsonl_path, {
                "type": "node_completed",
                "node_id": node_id,
                "data": {"output": "", "sub_workflow_done": True},
            })
            run_state.node_outputs[node_id] = {
                "output": "",
                "state": "completed",
                "data": {"output": "", "sub_workflow_done": True},
            }
    except WorkflowError as exc:
        raise WorkflowError(
            f"_poll_sub_workflows append_event failed: {exc}"
        ) from exc

    if run_state.current_node == node_id:
        run_state.current_node = None


def _handle_child_cancelled(
    node_id: str,
    jsonl_path: Path,
    run_state: RunState,
) -> None:
    """子 workflow_cancelled → 父写 child_force_killed + node_failed。

    任一 append_event 的 OSError → 包成 WorkflowError 向上抛（fail-closed）。
    """
    try:
        append_event(jsonl_path, {
            "type": "child_force_killed",
            "node_id": node_id,
            "data": {
                "sub_run_id": node_id,
                "sub_terminal_event": "workflow_cancelled",
                "on_subworkflow_failure": None,
            },
        })
        append_event(jsonl_path, {
            "type": "node_failed",
            "node_id": node_id,
            "data": {"reason": "child_force_killed"},
        })
    except WorkflowError as exc:
        raise WorkflowError(
            f"_poll_sub_workflows append_event failed: {exc}"
        ) from exc
    run_state.node_outputs[node_id] = {
        "output": "",
        "state": "failed",
        "data": {"reason": "child_force_killed"},
    }
    if run_state.current_node == node_id:
        run_state.current_node = None


def _poll_sub_workflows(
    run_state: RunState,
    workflow: dict,
    run_dir: Path,
    jsonl_path: Path,
) -> bool:
    """AC-08：每次 continue 进入 main loop 前，反扫所有 sub_runs 子 jsonl 末位状态。

    若发现某子 run 处于 terminal 状态（completed/failed/cancelled），且父 run 中
    对应 sub_workflow 节点尚未关闭：
      - 父 run 写 child_graceful_exited / child_failed / child_force_killed 事件
      - 按 on_subworkflow_failure 决定写 node_completed / node_skipped / node_failed
      - 父节点关闭后由 main loop 重算 _ready_nodes 推进下游

    返回：True = 至少有一个父节点状态被推进；False = 无变化
    """
    sub_runs_dir = run_dir / "sub_runs"
    if not sub_runs_dir.is_dir():
        return False

    node_map = _build_node_map(workflow)
    advanced = False

    for sub_jsonl in sub_runs_dir.glob("*/run-state.jsonl"):
        node_id = sub_jsonl.parent.name

        # 幂等守卫：父节点已关闭（node_outputs 已有该节点）→ 跳过
        if node_id in run_state.node_outputs:
            continue

        # fail-soft：子 jsonl 损坏（read_events 返 warnings 非空）→ 跳过该 sub_run
        sub_events, sub_warnings = read_events(sub_jsonl)
        if sub_warnings:
            print(
                f"WARN: _poll_sub_workflows 跳过损坏子 jsonl "
                f"(node_id={node_id!r}, warnings={sub_warnings})",
                file=sys.stderr,
            )
            continue

        # 找子 run 末位 workflow 级事件
        terminal_types = {"workflow_completed", "workflow_failed", "workflow_cancelled"}
        last_terminal: str | None = None
        for evt in reversed(sub_events):
            if evt.get("type") in terminal_types:
                last_terminal = evt.get("type")
                break

        if last_terminal is None:
            # 子尚未到终态，跳过
            continue

        if last_terminal == "workflow_completed":
            _handle_child_completed(node_id, jsonl_path, run_state)
            advanced = True

        elif last_terminal == "workflow_failed":
            # 取父 yaml 节点的 on_subworkflow_failure；None 时默认 "fail"（fail-soft）
            parent_node = node_map.get(node_id) or {}
            on_failure: str = parent_node.get("on_subworkflow_failure") or "fail"
            _handle_child_failed_by_policy(node_id, on_failure, jsonl_path, run_state)
            advanced = True

        elif last_terminal == "workflow_cancelled":
            _handle_child_cancelled(node_id, jsonl_path, run_state)
            advanced = True

    return advanced


def _main_loop(
    run_state: RunState,
    workflow: dict,
    run_dir: Path,
    root: Path,
    jsonl_path: Path,
) -> None:
    """主循环（F-008）：完整 7 outcome 路由表 + 失败矩阵。

    算法：
      0. 入口先调 _finalize_after_rebuild_if_last_topology_node 补救 round-5 P2 窗口
      while state == running and current_node:
        - 按 node 类型派发（dispatch_node 已写 node_started + node_completed/node_failed 事件）
        - 调用 _route_outcome 按 outcome 路由处理；返回 False 则 break
    """
    from workflow_dispatcher import _build_env, dispatch_node

    node_map = _build_node_map(workflow)

    # F-011：进入 main loop 前反扫所有 sub_runs，回填父节点完成事件（AC-08）
    _poll_sub_workflows(run_state, workflow, run_dir, jsonl_path)
    # 子状态推进后，可能让父拓扑跑完 → finalize 兜底必须紧跟

    # round-5 P2：crash 在 advance 之后 / finalize 之前的窗口补救
    # F-004：新签名传 workflow（DAG / 单链双分支判定）
    if _finalize_after_rebuild_if_last_topology_node(
        run_state, workflow, node_map, jsonl_path
    ):
        return

    # F-CR-002：main_loop 入口 bootstrap。
    # main() 调用链 `_setup_run → _resume_run → _main_loop` 不预设 current_node；
    # 真新 run（current_node is None）或 crash-window（rebuild 已置 None 但 jsonl 还有未跑完的
    # 拓扑）走到这里时，需要 scheduler 算出下一个待派发节点才能进 while 循环。
    # 上一步 _finalize_after_rebuild 已处理"拓扑跑完无需推进"的场景；走到这里
    # 仍有 current_node is None ∧ state==running 时一定需要 bootstrap。
    # 若 _select_next_dispatch_target 返 None（无可派发节点，但拓扑也未到 finalize 条件，
    # 例如 yaml 与 jsonl 不一致），while 因 current_node 假值不进入，让上游或 finalize
    # 接管——此处不强制写 workflow_failed/completed，行为对齐 v8 P1 "保持 running 不推进"
    # 的容错语义。
    if run_state.current_node is None and run_state.state == "running":
        next_id = _select_next_dispatch_target(run_state, workflow, node_map)
        if next_id is not None:
            run_state.current_node = next_id
        else:
            # IB-10：bootstrap 无可派发节点时打 WARN，让人类可见（yaml/jsonl 不一致时易触发）。
            # while 因 current_node 假值不进入，函数静默返回；WARN 对齐 _finalize_after_rebuild:493 风格。
            print(
                f"WARN: bootstrap 阶段无可派发节点，state=running 但 workflow 停止推进，"
                f"yaml/jsonl 可能不一致 (run_id={run_state.run_id})",
                file=sys.stderr,
            )

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
        # P1-c v2（codex round-4）：workflow_completed 由 _route_outcome 内的
        # _finalize_if_topology_done 写入——只在真的从 completed/loop_done/sub_workflow_done
        # outcome 推进且无 next 时触发。crash → rebuild 看到 current_node=None 的场景不会
        # 误触发（main loop 直接因 while 失败退出，不进 _route_outcome）。
        # F-CR-001：传 workflow + node_map 让 completed/loop_done/sub_workflow_done
        # 分支按 depends_on_explicit 调 _select_next_dispatch_target 推进 DAG。
        should_continue = _route_outcome(
            run_state, node, result, jsonl_path, workflow, node_map
        )
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
        print(f"ERROR: {exc}", file=sys.stderr)
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
        # 降级查找：从 meta.yaml 读模板路径
        # codex P1（2026-05-12）：writer 用的 key 是 template_path（见 workflow_run._run_generic
        # workflow_bootstrap），旧版误读 workflow_template_path 导致 non-requirement run
        # （如 review/code-review-embedded.yaml）resume 时拿不到真路径。优先 template_path，
        # 兼容历史 workflow_template_path 字段。降级失败时写 WARN 到 stderr 留排查线索，
        # 但仍以原 workflow_path 兜底。
        meta_path = run_dir / "meta.yaml"
        if meta_path.exists():
            try:
                meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
                rel_path = meta.get("template_path") or meta.get("workflow_template_path")
                if rel_path:
                    workflow_path = root / rel_path
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

    # F-008: 在 _setup_run 之后、_resume_run 之前取 path_lock；LockBusyError 被 WorkflowError
    # 兜底（继承关系），打 stderr 含 "another continue is running, pid=N" + exit 1。
    lock_handle = None
    try:
        lock_handle = path_lock.acquire(run_id, root)
    except path_lock.LockBusyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
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
    finally:
        # atexit 已注册 release，此处显式 release 为双保险（try/finally 覆盖所有 return 路径）
        if lock_handle is not None:
            path_lock.release(lock_handle)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:] if len(sys.argv) > 1 else []))
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
