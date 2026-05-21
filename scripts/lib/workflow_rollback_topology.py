"""workflow_rollback 拓扑与 YAML 加载工具模块（F-007）。

提供：
- _find_workflow_yaml: 从 run 目录查找 workflow.yaml
- _load_nodes: 加载 workflow.yaml 并返回 nodes 列表（含 depends_on 展开）
- _expand_implicit_depends_on: 展开隐式 depends_on
- _all_node_ids: 从 nodes 提取节点 ID 集合
- _get_ordered_node_ids: 拓扑排序后平铺节点 ID 列表
- _validate_to_node_is_upstream: 校验 to_node 是当前节点的拓扑上游
- _find_current_position: 确定当前执行位置索引

详细设计：requirements/REQ-2026-009/artifacts/detailed-design.md §6.1~§6.3
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import yaml  # noqa: E402
from common import REPO_ROOT  # noqa: E402
from topological_sort import topological_layers  # noqa: E402


def _find_workflow_yaml(run_dir: Path) -> Path:
    """从 run 目录找到 workflow.yaml。

    查找顺序：
      1. run_dir/workflow.yaml
      2. run_dir/../workflow.yaml
      3. 向上最多 3 层
      4. 次生 bug fallback：从 run_dir/run-state.jsonl 读 workflow_started 事件取
         workflow_name，然后查 .claude/workflows/**/<workflow_name>.yaml
    找不到则抛 TargetNodeNotFoundError。
    """
    from workflow_rollback import TargetNodeNotFoundError

    # 优先 run_dir 内
    direct = run_dir / "workflow.yaml"
    if direct.is_file():
        return direct
    # 兼容：run_dir 同级（requirements/<id>/ 下的 workflow.yaml）
    sibling = run_dir.parent / "workflow.yaml"
    if sibling.is_file():
        return sibling
    # 向上最多 3 层，遇到 REPO_ROOT 或文件系统根停止（H-14：加 root 边界防止越界）
    for candidate in [run_dir.parent, run_dir.parent.parent, run_dir.parent.parent.parent]:
        if candidate == Path("/") or not candidate.is_relative_to(REPO_ROOT):
            break
        c = candidate / "workflow.yaml"
        if c.is_file():
            return c
    # 次生 bug fallback：从 jsonl 取 workflow_name 再查 .claude/workflows/
    resolved = _resolve_via_jsonl(run_dir)
    if resolved is not None:
        return resolved
    raise TargetNodeNotFoundError(
        f"run_dir {run_dir} 未找到 workflow.yaml；无法校验 to_node"
    )


def _resolve_via_jsonl(run_dir: Path) -> Path | None:
    """从 jsonl workflow_started 事件读 workflow_name，查 .claude/workflows/**/<name>.yaml。

    任何步骤失败 → 返回 None（fail-soft，让上层抛标准错误）。
    """
    import json

    jsonl_path = run_dir / "run-state.jsonl"
    if not jsonl_path.is_file():
        return None
    try:
        with jsonl_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") != "workflow_started":
                    continue
                name = (ev.get("data") or {}).get("workflow_name", "")
                if not name:
                    continue
                # 拼 .claude/workflows/**/<name>.yaml
                workflows_root = REPO_ROOT / ".claude" / "workflows"
                if not workflows_root.is_dir():
                    return None
                matches = list(workflows_root.rglob(f"{name}.yaml"))
                if matches:
                    return matches[0]
                return None
    except OSError:
        return None
    return None


def _load_nodes(run_dir: Path) -> list[dict[str, Any]]:
    """加载 workflow.yaml 并返回 nodes 列表（已做 depends_on 展开）。

    rollback 只需要节点 ID 集合 + depends_on 拓扑结构，
    不需要深入校验 sub_workflow 路径/prompt_file 等运行时资源，
    因此直接用 yaml.safe_load 读取而不走 load_workflow 的严格校验。
    """
    from workflow_rollback import TargetNodeNotFoundError

    yaml_path = _find_workflow_yaml(run_dir)
    try:
        with yaml_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except (yaml.YAMLError, OSError) as exc:
        raise TargetNodeNotFoundError(
            f"workflow.yaml 读取失败（{yaml_path}）：{exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise TargetNodeNotFoundError(
            f"workflow.yaml 顶层不是 mapping（{yaml_path}）"
        )

    nodes = raw.get("nodes") or []
    if not isinstance(nodes, list):
        raise TargetNodeNotFoundError(
            f"workflow.yaml nodes 不是列表（{yaml_path}）"
        )

    # H-13：校验节点 id 合法性（仅允许字母/数字/下划线/横线）
    _NODE_ID_PATTERN = re.compile(r'^[A-Za-z0-9_\-]+$')
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node.get("id", "")
        if nid and not _NODE_ID_PATTERN.fullmatch(nid):
            raise TargetNodeNotFoundError(
                f"非法节点 id：{nid!r}（仅允许字母/数字/下划线/横线）"
            )

    # 展开隐式 depends_on（缺省 = 接上一节点）
    _expand_implicit_depends_on(nodes)
    return nodes


def _expand_implicit_depends_on(nodes: list[dict[str, Any]]) -> None:
    """展开 depends_on 缺省规则：缺失时隐式接上一节点（spec §6.12）。

    在 workflow_loader._expand_implicit_depends_on 同逻辑，这里独立实现，
    避免导入 workflow_loader（后者有严格校验依赖）。
    """
    prev_id: str | None = None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if "depends_on" not in node:
            node["depends_on"] = [prev_id] if prev_id else []
        prev_id = node.get("id")


def _all_node_ids(nodes: list[dict[str, Any]]) -> set[str]:
    """从 nodes 提取所有节点 ID 集合。"""
    return {n["id"] for n in nodes if isinstance(n, dict) and "id" in n}


def _get_ordered_node_ids(nodes: list[dict[str, Any]]) -> list[str]:
    """返回拓扑排序后的节点 ID 平铺列表（前→后）。"""
    layers = topological_layers(nodes)
    return [nid for layer in layers for nid in layer]


def _validate_to_node_is_upstream(
    nodes: list[dict[str, Any]],
    current_node: str | None,
    to_node: str,
    run_state: Any,
) -> None:
    """校验 to_node 是 current_node 的拓扑上游（严格上游，不能是当前节点本身）。

    如果 current_node 为 None，使用 node_outputs 中最后完成的节点作为当前位置。
    """
    from workflow_rollback import TargetNodeNotFoundError, TargetNodeNotUpstreamError

    ordered = _get_ordered_node_ids(nodes)

    # 确定"当前"节点的位置（最后完成/运行中的节点）
    current_pos = _find_current_position(ordered, current_node, run_state)
    to_pos = ordered.index(to_node) if to_node in ordered else -1

    if to_pos < 0:
        # to_node 不在节点集合时由 _resolve_and_validate 调用方已校验；这里兜底
        raise TargetNodeNotFoundError(f"to_node={to_node!r} 不在 workflow 节点列表")

    if to_pos >= current_pos:
        raise TargetNodeNotUpstreamError(
            f"to_node={to_node!r}（位置 {to_pos}）不是 current_node（位置 {current_pos}）的上游；"
            f"rollback 只能回到更早的节点"
        )


def _find_current_position(
    ordered: list[str],
    current_node: str | None,
    run_state: Any,
) -> int:
    """确定当前执行位置索引（在 ordered 中的位置）。

    优先用 current_node（正在运行中的节点），否则用 node_outputs 中最后完成的节点。
    """
    if current_node and current_node in ordered:
        return ordered.index(current_node)

    # 从 node_outputs 推断：找最后一个完成的节点
    last_pos = -1
    for nid, info in run_state.node_outputs.items():
        if nid in ordered:
            pos = ordered.index(nid)
            if pos > last_pos:
                last_pos = pos

    if last_pos < 0:
        # 无已完成节点；返回列表末尾（允许回滚到任意节点）
        return len(ordered)

    # 最后完成节点的下一个位置
    return last_pos + 1
