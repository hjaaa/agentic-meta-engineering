"""e2e 测试共享工具函数（由 conftest.py 和测试文件共同使用）。

复刻 tests/lib/test_workflow_rollback.py 的 _setup_run_dir / _write_jsonl_from_fixture 思路。

设计依据：requirements/REQ-2026-009/artifacts/detailed-design.md §7.3.3
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 把 scripts/lib 放入路径，让 helpers 能 import run_state 等
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

# F1 fixture 根目录（复用 F1-cross-parent-child 的 workflow.yaml + jsonl 模板）
F1_FIXTURE_DIR = REPO_ROOT / "tests" / "lib" / "fixtures" / "rollback" / "F1-cross-parent-child"


def make_run_dir(tmp_path: Path, run_id: str) -> Path:
    """在 tmp_path/runs/<run_id>/ 下建目录，返回 run_dir。"""
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_parent_jsonl_from_template(
    run_dir: Path,
    run_id: str,
    extra_events: list[dict[str, Any]] | None = None,
) -> None:
    """把 F1 fixture 的 parent-jsonl.txt 写到 run_dir/run-state.jsonl，并可追加额外事件。

    extra_events 用于 TC-F8-2 等需要注入 sub_workflow 调用事件的场景。
    """
    src = F1_FIXTURE_DIR / "parent-jsonl.txt"
    dst = run_dir / "run-state.jsonl"

    # 逐行读取并替换 run_id（fixture 里硬编码的是 TEST-F1-PARENT）
    lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
    rewritten = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            evt = json.loads(stripped)
            if evt.get("run_id") == "TEST-F1-PARENT":
                evt["run_id"] = run_id
            rewritten.append(json.dumps(evt, ensure_ascii=False) + "\n")
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"fixture 模板含损坏 JSON 行（src={src}, line={stripped!r}）："
                f"{exc.msg}"
            ) from exc

    dst.write_text("".join(rewritten), encoding="utf-8")

    # 追加额外事件
    if extra_events:
        with dst.open("a", encoding="utf-8") as fh:
            for evt in extra_events:
                fh.write(json.dumps(evt, ensure_ascii=False) + "\n")


def write_child_jsonl_from_template(
    child_run_dir: Path,
    child_run_id: str,
    extra_events: list[dict[str, Any]] | None = None,
) -> None:
    """把 F1 fixture 的 child-jsonl.txt 写到 child_run_dir/run-state.jsonl。"""
    src = F1_FIXTURE_DIR / "child-jsonl.txt"
    dst = child_run_dir / "run-state.jsonl"

    lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
    rewritten = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            evt = json.loads(stripped)
            if evt.get("run_id") == "TEST-F1-CHILD":
                evt["run_id"] = child_run_id
            rewritten.append(json.dumps(evt, ensure_ascii=False) + "\n")
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"fixture 模板含损坏 JSON 行（src={src}, line={stripped!r}）："
                f"{exc.msg}"
            ) from exc

    dst.write_text("".join(rewritten), encoding="utf-8")

    if extra_events:
        with dst.open("a", encoding="utf-8") as fh:
            for evt in extra_events:
                fh.write(json.dumps(evt, ensure_ascii=False) + "\n")


def create_node_artifacts(run_dir: Path, node_ids: list[str]) -> None:
    """在 run_dir/<node_id>/ 下创建 output.json，模拟节点产物。"""
    for nid in node_ids:
        node_dir = run_dir / nid
        node_dir.mkdir(parents=True, exist_ok=True)
        (node_dir / "output.json").write_text(
            json.dumps({"node": nid, "output": "done"}, ensure_ascii=False),
            encoding="utf-8",
        )


def copy_workflow_yaml(run_dir: Path) -> None:
    """把 F1 fixture 的 workflow.yaml 复制到 run_dir。"""
    shutil.copy(F1_FIXTURE_DIR / "workflow.yaml", run_dir / "workflow.yaml")


def read_jsonl_events(jsonl_path: Path) -> list[dict[str, Any]]:
    """读 jsonl 文件，返回所有合法事件列表。"""
    if not jsonl_path.exists():
        return []
    events = []
    with jsonl_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                try:
                    events.append(json.loads(stripped))
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "read_jsonl_events 跳过损坏行（path=%s, line=%r）：%s",
                        jsonl_path, stripped, exc.msg,
                    )
    return events


def get_event_types(jsonl_path: Path) -> list[str]:
    """提取 jsonl 中所有事件的 type 字段列表。"""
    return [e.get("type", "") for e in read_jsonl_events(jsonl_path)]


def write_event_to_jsonl(jsonl_path: Path, event: dict[str, Any]) -> None:
    """直接向 jsonl 写入一条事件（无 VALID_EVENT_TYPES 校验，用于造 fixture 数据）。

    从 test_sub_workflow_lifecycle.py 提出（F-011 跨文件共享，去下划线公开）。
    原私有版本 _write_event_to_jsonl 在 lifecycle.py 保留为别名以向下兼容。
    """
    payload = json.dumps(event, ensure_ascii=False) + "\n"
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(payload)


class ParentCancelCoordinator:
    """父侧等待子 graceful 退出的协调器（模拟 §7.1 时序图父侧逻辑）。

    职责：
    1. 向父 jsonl 写 cancel_requested
    2. 轮询等待子 jsonl 出现 parent_cancelled（graceful 信号）
    3. 若超时则调 task_stop_fn（TaskStop 兜底）
    4. 写 child_graceful_exited 或 child_force_killed 到父 jsonl

    从 test_sub_workflow_lifecycle.py 提出（F-011 跨文件共享，去下划线公开）。
    原私有版本 _ParentCancelCoordinator 在 lifecycle.py 保留为别名以向下兼容。
    """

    def __init__(
        self,
        parent_jsonl: Path,
        child_jsonl: Path,
        parent_run_id: str,
        graceful_timeout_secs: float = 30.0,
        poll_interval_secs: float = 0.05,
    ) -> None:
        # 延迟 import 避免循环依赖（append_event 来自 scripts/lib，由调用方已挂入 sys.path）
        from run_state import append_event as _append_event  # noqa: PLC0415
        self._append_event = _append_event
        self.parent_jsonl = parent_jsonl
        self.child_jsonl = child_jsonl
        self.parent_run_id = parent_run_id
        self.graceful_timeout_secs = graceful_timeout_secs
        self.poll_interval_secs = poll_interval_secs
        # 注入点：测试可 mock 以拦截 TaskStop 调用
        self.task_stop_called = False
        self.task_stop_run_id: str | None = None

    def request_cancel_and_wait(self, child_run_id: str) -> str:
        """写 cancel_requested 并等待子 graceful 退出。

        返回：
            "graceful"     — 子在 timeout 内写了 parent_cancelled
            "force_killed" — 超时，调 TaskStop
        """
        # 父写 cancel_requested
        self._append_event(self.parent_jsonl, {
            "type": "cancel_requested",
            "run_id": self.parent_run_id,
        })

        # 轮询子 jsonl
        deadline = time.monotonic() + self.graceful_timeout_secs
        while time.monotonic() < deadline:
            child_types = get_event_types(self.child_jsonl)
            if "parent_cancelled" in child_types:
                # 子 graceful 退出，父写 child_graceful_exited
                self._append_event(self.parent_jsonl, {
                    "type": "child_graceful_exited",
                    "run_id": self.parent_run_id,
                    "data": {"child_run_id": child_run_id},
                })
                return "graceful"
            time.sleep(self.poll_interval_secs)

        # 超时：TaskStop forceful 兜底
        self._call_task_stop(child_run_id)
        self._append_event(self.parent_jsonl, {
            "type": "child_force_killed",
            "run_id": self.parent_run_id,
            "data": {"child_run_id": child_run_id},
        })
        return "force_killed"

    def _call_task_stop(self, child_run_id: str) -> None:
        """调用 TaskStop（生产 = Anthropic SDK；测试可 monkeypatch）。

        当前为 stub；F-009 落地时替换为真实调用。
        记录调用情况供测试断言使用。
        """
        self.task_stop_called = True
        self.task_stop_run_id = child_run_id
