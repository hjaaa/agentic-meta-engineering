"""workflow continue 命令入口（F-005 框架 + F-007 main loop 最小骨架）。

/workflow:continue [<run-id>]

反扫 jsonl 重建 RunState，做状态校验，进 main loop（F-007 实现 completed / approval_pending / failed
三种 outcome；F-008 接入失败矩阵 retry/skip/abort；F-011 接入 loop / sub_workflow）。

详细设计 §1.2.2 / §1.7。
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
            next_id = _next_node(node, result.next_node_hint)
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
            # 由 F-008 / F-011 接入；F-007 阶段静默 break 会让 main() 返回 0 但 state 仍为 running，
            # 调用方无法感知部分失败。写 WARN 至少留下排查线索。
            print(
                f"WARN: F-007 阶段不支持的 outcome={result.outcome!r}（node_id={node['id']!r}）；"
                f"main loop 退出但 state 仍为 running，等待 F-008/F-011 接入",
                file=sys.stderr,
            )
            break


def _setup_run(
    run_id: str,
    root: Path,
) -> tuple["RunState", Path, Path]:
    """解析 run_dir、读取 jsonl 事件并重建 RunState。

    返回 (run_state, run_dir, jsonl_path)；失败时抛出 WorkflowError（由调用方转 exit 1）。

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

    # run_resumed 不映射 WORKFLOW_EVENT_TO_STATE，保持原 state 语义不变（详细设计 §1.2.2）
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
