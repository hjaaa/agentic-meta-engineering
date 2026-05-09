"""MockSubAgent：模拟 Claude Code Agent({run_in_background: true}) 派发的子 subagent。

设计依据：requirements/REQ-2026-009/artifacts/detailed-design.md §7.3.1
规则：
- 子 jsonl 永远由子自身写（不允许父跨 run 写文件，D-005 第 4 项决策）
- 每节点完成前 poll parent_jsonl，检测到 cancel_requested 则写 parent_cancelled 并 graceful 退出
- poll_interval_ms 可调；测试默认 100ms，生产值由 spec §6.10 决定
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MockSubAgent:
    """模拟子 subagent，可按 scripted_nodes 列表顺序执行节点，并在每节点边界 poll 父 jsonl。

    构造参数：
        child_run_id   — 子 run id（用于 jsonl 事件 run_id 字段 + 日志）
        jsonl_path     — 子 run-state.jsonl 的绝对路径（子自身写入）
        poll_interval_ms — poll 父 jsonl 的间隔毫秒，默认 100ms（测试用）；0 = 每次立即 poll

    run() 返回值：
        "graceful_exit"  — poll 检测到 cancel_requested，写 parent_cancelled 后退出
        "completed"      — 所有节点正常完成
        "failed:<msg>"   — 节点执行抛异常（由 on_fail 逻辑上层处理）
    """

    def __init__(
        self,
        child_run_id: str,
        jsonl_path: Path,
        poll_interval_ms: int = 100,
    ) -> None:
        self.child_run_id = child_run_id
        self.jsonl_path = jsonl_path
        self.poll_interval_ms = poll_interval_ms
        # 注入点：测试可替换 _sleep 实现快进
        self._sleep = time.sleep

    # ----------------------------------------------------------------
    # 公开入口
    # ----------------------------------------------------------------

    def run(self, parent_jsonl: Path, scripted_nodes: list[str]) -> str:
        """按 scripted_nodes 顺序执行；每节点开始前 poll parent_jsonl。

        参数：
            parent_jsonl: 父 run-state.jsonl 路径（只读，用于 poll cancel_requested）
            scripted_nodes: 节点 id 列表（按序执行）

        返回：
            "graceful_exit" / "completed" / "failed:<msg>"
        """
        logger.info(
            "MockSubAgent 启动（child_run_id=%s, nodes=%s）",
            self.child_run_id, scripted_nodes,
        )
        self._append_event("workflow_started", data={"workflow_name": "mock-sub-workflow"})

        for node in scripted_nodes:
            # 每节点边界：先 poll，再执行
            if self._poll_parent_cancel(parent_jsonl):
                logger.info(
                    "MockSubAgent poll 命中 cancel_requested（child_run_id=%s, at_node=%s）",
                    self.child_run_id, node,
                )
                self._append_event("parent_cancelled")
                return "graceful_exit"

            result = self._execute_node(node)
            if result is not None:
                # 节点抛异常：写 workflow_failed，返回 failed 标记
                self._append_event(
                    "workflow_failed",
                    data={"error": result, "failed_node": node},
                )
                return f"failed:{result}"

        self._append_event("workflow_completed")
        logger.info("MockSubAgent 完成（child_run_id=%s）", self.child_run_id)
        return "completed"

    # ----------------------------------------------------------------
    # 内部工具：节点执行
    # ----------------------------------------------------------------

    def _execute_node(self, node_id: str) -> str | None:
        """执行单个节点。返回 None = 成功；返回错误消息 str = 失败。

        测试可向 scripted_nodes 注入特殊标记触发异常：
            "__raise_<msg>"  — 此节点抛 RuntimeError(<msg>)
            "__block_<secs>" — 此节点阻塞 <secs> 秒（用于 TC-F8-5 超时测试）
        """
        if node_id.startswith("__raise_"):
            msg = node_id[len("__raise_"):]
            logger.warning(
                "MockSubAgent 节点 %s 抛异常（child_run_id=%s）：%s",
                node_id, self.child_run_id, msg,
            )
            self._append_event("node_started", node_id=node_id)
            self._append_event("node_failed", node_id=node_id, data={"error": msg})
            raise RuntimeError(msg)

        if node_id.startswith("__block_"):
            secs = float(node_id[len("__block_"):])
            logger.info(
                "MockSubAgent 节点 %s 阻塞 %.1fs（child_run_id=%s）",
                node_id, secs, self.child_run_id,
            )
            self._append_event("node_started", node_id=node_id)
            self._sleep(secs)
            self._append_event("node_completed", node_id=node_id, data={"output": "blocked"})
            return None

        self._append_event("node_started", node_id=node_id)
        self._append_event("node_completed", node_id=node_id, data={"output": f"{node_id}-done"})
        logger.debug("MockSubAgent 节点 %s 完成（child_run_id=%s）", node_id, self.child_run_id)
        return None

    # ----------------------------------------------------------------
    # 内部工具：poll 父 jsonl
    # ----------------------------------------------------------------

    def _poll_parent_cancel(self, parent_jsonl: Path) -> bool:
        """读父 jsonl，检测是否有 cancel_requested 事件。

        等待 poll_interval_ms 后再读（模拟真实 subagent 的等待语义）。
        返回 True = 检测到 cancel_requested。
        """
        if self.poll_interval_ms > 0:
            self._sleep(self.poll_interval_ms / 1000.0)

        if not parent_jsonl.exists():
            return False

        try:
            with parent_jsonl.open("r", encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        evt = json.loads(stripped)
                        if evt.get("type") == "cancel_requested":
                            return True
                    except json.JSONDecodeError:
                        continue
        except OSError as exc:
            logger.warning(
                "MockSubAgent poll 父 jsonl 失败（child_run_id=%s, parent_jsonl=%s）：%s",
                self.child_run_id, parent_jsonl, exc,
            )
        return False

    # ----------------------------------------------------------------
    # 内部工具：写子 jsonl
    # ----------------------------------------------------------------

    def _append_event(
        self,
        event_type: str,
        node_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """向子 jsonl 追加一条事件（fcntl O_APPEND）。

        子 jsonl 永远由子自身写，不依赖父侧 append_event（D-005 规则）。
        """
        ts = _utc_now_iso()
        event: dict[str, Any] = {
            "type": event_type,
            "ts": ts,
            "run_id": self.child_run_id,
        }
        if node_id is not None:
            event["node_id"] = node_id
        if data:
            event["data"] = data

        payload = json.dumps(event, ensure_ascii=False) + "\n"
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(
                str(self.jsonl_path),
                os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                0o644,
            )
            try:
                os.write(fd, payload.encode("utf-8"))
            finally:
                os.close(fd)
        except OSError as exc:
            raise RuntimeError(
                f"MockSubAgent 写子 jsonl 失败（child_run_id={self.child_run_id}）：{exc}"
            ) from exc


# ----------------------------------------------------------------
# 内部辅助
# ----------------------------------------------------------------

def _utc_now_iso() -> str:
    """返回 UTC 时间 ISO8601 字符串，如 2026-05-09T12:00:00Z。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
