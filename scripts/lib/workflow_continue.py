"""workflow continue 命令入口（F-005）。

/workflow:continue [<run-id>]

反扫 jsonl 重建 RunState，做状态校验，进 main loop stub（F-006 实现完整 loop）。

详细设计 §1.2.2。
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
    node_map: dict[str, dict],
    hint: str | None,
) -> str | None:
    """确定下一个节点 ID。

    优先级：
      1. hint 非 None 时返回 hint（显式覆盖，e.g. on_reject）
      2. 否则读 current_node.next（若存在）
      3. 否则返回 None（拓扑末尾）
    """
    if hint is not None:
        return hint
    return current_node.get("next")


def _main_loop(
    run_state: RunState,
    workflow: dict,
    run_dir: Path,
    root: Path,
    jsonl_path: Path,
) -> None:
    """主循环最小骨架（F-007）：仅处理 completed / failed / approval_pending 三种 outcome。

    完整失败矩阵 / loop / sub_workflow 由 F-008 / F-011 接入。

    算法：
      while state == running and current_node:
        - 派发节点（dispatch_node 已自行写 node_started 和 node_completed/node_failed 事件）
        - 根据 outcome 更新状态：
          - completed：更新 node_outputs，推进到下一节点
          - approval_pending：设 state=approval_pending 并 break
          - failed：设 state=failed 并 break（完整矩阵由 F-008 实现）
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

        # 构建环境变量并派发节点
        env = _build_env(run_state, run_dir, root)
        result = dispatch_node(node, run_state, run_dir, root, env, jsonl_path)

        # 根据派发结果更新状态
        if result.outcome == "completed":
            # 注意：node_completed 事件已由各 _dispatch_*_node 写入；
            # main loop 不再重复写，以避免双写。仅更新 RunState 与推进指针。
            run_state.node_outputs[node["id"]] = {
                "output": result.output,
                "state": "completed",
                "data": {"output": result.output},
            }
            next_id = _next_node(node, node_map, result.next_node_hint)
            run_state.current_node = next_id

        elif result.outcome == "approval_pending":
            # 派发器已写 approval_pending 事件；main loop 仅设置状态并退出
            run_state.state = "approval_pending"
            break

        elif result.outcome == "failed":
            # F-007 最小处理：仅设 state 并 break
            # 完整失败矩阵（retry / skip / abort）由 F-008 的 _handle_failure 实现
            run_state.state = "failed"
            break

        else:
            # 其他 outcome（loop_continue / loop_done / sub_workflow_pending / sub_workflow_done）
            # 由 F-008 / F-011 接入；F-007 暂无处理，仅 break 并让状态保持
            break


def main(args: list[str], repo_root: Path | None = None) -> int:
    """continue 命令主入口。

    参数：
        args      — [run_id?]（可选）
        repo_root — 注入 repo 根路径（测试用）

    返回：exit code（0 成功，1 失败）
    """
    root = repo_root or REPO_ROOT

    run_id = args[0] if args else None
    if not run_id:
        run_id = infer_run_id_from_branch(root)
    if not run_id:
        print(
            "ERROR: 无法推断 run_id\n"
            "请提供 run_id 或确保当前分支为 feat/req-<id> 格式",
            file=sys.stderr,
        )
        return 1

    # D-007 双路径解析
    try:
        run_dir = _resolve_run_dir(run_id, root)
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    jsonl_path = run_dir / "run-state.jsonl"
    events, warnings = read_events(jsonl_path)
    run_state = RunState.rebuild(events, run_id=run_id, warnings=warnings)

    # 状态矩阵校验
    try:
        validate_state_for_cmd("continue", run_id, run_state.state)
    except WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # 写 run_resumed 事件（详细设计 §1.2.2 + skill continue.md 步骤 5）
    # run_resumed 不映射 WORKFLOW_EVENT_TO_STATE，保持原 state 语义不变
    try:
        append_event(jsonl_path, {
            "type": "run_resumed",
            "run_id": run_id,
        })
    except WorkflowError as exc:
        # G-11：审计事件写失败与 cancel_requested 同级处理，exit 1 让调用方感知
        # 对照 cancel.py:93 写 cancel_requested 失败 exit 1 的统一处理策略
        print(f"ERROR: 写 run_resumed 审计事件失败：{exc}", file=sys.stderr)
        return 1

    print(f"恢复 workflow run {run_id!r}（state={run_state.state}）")

    # 加载 workflow 模板（从 meta.yaml 读 workflow_name）
    workflow_name = run_state.workflow_name
    if not workflow_name:
        print("ERROR: 无法确定 workflow 名称（workflow_started 事件缺失）", file=sys.stderr)
        return 1

    # 查找 workflow 文件（按约定位置：.claude/workflows/<category>/<name>.yaml）
    # 对于需求类 workflow，category 通常为 "requirement"，模板名为 standard-8phase
    workflow_path = root / ".claude" / "workflows" / "requirement" / f"{workflow_name}.yaml"
    if not workflow_path.exists():
        # 降级查找：尝试从 requirements/<id>/meta.yaml 读 workflow_path
        meta_path = run_dir / "meta.yaml"
        if meta_path.exists():
            try:
                meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
                workflow_path = root / meta.get("workflow_template_path", str(workflow_path))
            except Exception:
                pass

    # 加载并校验 workflow
    result = load_workflow(workflow_path)
    if result.report.errors:
        print(f"ERROR: 加载 workflow 失败\n{result.report.render()}", file=sys.stderr)
        return 1

    workflow = result.workflow
    if not workflow:
        print("ERROR: workflow 加载失败（返回值为 None）", file=sys.stderr)
        return 1

    # 调用 main loop
    _main_loop(run_state, workflow, run_dir, root, jsonl_path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:] if len(sys.argv) > 1 else []))
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
