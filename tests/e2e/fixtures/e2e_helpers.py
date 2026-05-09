"""e2e 测试共享工具函数（由 conftest.py 和测试文件共同使用）。

复刻 tests/lib/test_workflow_rollback.py 的 _setup_run_dir / _write_jsonl_from_fixture 思路。

设计依据：requirements/REQ-2026-009/artifacts/detailed-design.md §7.3.3
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
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
