"""Kahn 拓扑排序：把节点列表转成可并发执行的 layer 序列。

每个 layer 内的节点彼此独立、可并发；layer 之间严格串行（layer N 必须等
layer N-1 全部 terminal 才能启动）。

输入约定：每个 node 是一个 dict，至少含 `id`，可选 `depends_on` 字符串列表；
caller 必须先把"depends_on 缺省 = 上一节点"的语法糖展开。
"""
from __future__ import annotations

from typing import Any


class CycleError(Exception):
    """DAG 存在环。

    `remaining_nodes` 列出在 Kahn 末尾仍未被消费的节点 id（环中节点）。
    """

    def __init__(self, remaining_nodes: list[str]) -> None:
        super().__init__(f"DAG 存在环，剩余节点: {remaining_nodes}")
        self.remaining_nodes = remaining_nodes


def topological_layers(nodes: list[dict[str, Any]]) -> list[list[str]]:
    """对节点做分层拓扑排序。返回 [[layer0_ids], [layer1_ids], ...]。

    - 每层内 id 按字母序稳定排序（便于测试断言）
    - 检测到环时抛 CycleError，附剩余节点便于定位

    实现：经典 Kahn 算法 — 先把入度为 0 的节点放入第一层，
    每弹出一层就把后继的入度减 1，新归零的进下一层。
    """
    in_degree: dict[str, int] = {}
    successors: dict[str, list[str]] = {}
    all_ids: set[str] = set()

    for node in nodes:
        nid = node.get("id")
        if not nid:
            continue
        all_ids.add(nid)
        deps = node.get("depends_on") or []
        in_degree[nid] = len(deps)
        for dep in deps:
            successors.setdefault(dep, []).append(nid)

    # 第一层 = 入度为 0 的节点（包含 deps 引用了不存在节点时可能为空，由上层做 W121 校验）
    layers: list[list[str]] = []
    ready = sorted(nid for nid in all_ids if in_degree[nid] == 0)

    while ready:
        layers.append(ready)
        next_ready: list[str] = []
        for nid in ready:
            for succ in successors.get(nid, []):
                if succ not in in_degree:
                    continue
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    next_ready.append(succ)
        ready = sorted(next_ready)

    processed = sum(len(layer) for layer in layers)
    if processed != len(all_ids):
        # 存在环；列出剩余 in_degree > 0 的节点
        remaining = sorted(nid for nid in all_ids if in_degree.get(nid, 0) > 0)
        raise CycleError(remaining)

    return layers
