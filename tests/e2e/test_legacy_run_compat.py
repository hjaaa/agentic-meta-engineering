"""TC-F11-3 AC-E2E：Legacy paused run 反扫 RunState.rebuild 兼容性测试。

设计依据：requirements/REQ-2026-009/artifacts/detailed-design.md §8 / acceptance TC-F11-3
决策 A：REQ-2026-005 已 phase=completed 且无 jsonl（早于 F-001 落地）。
        用 tests/e2e/fixtures/legacy_run/ 下的仿历史 paused run fixture 驱动测试。
        详见 requirements/REQ-2026-009/notes.md Plan 6 自举验证 SOP。

测试主体：
  1. 加载 fixture legacy_run/.workflow/runs/RUN-LEGACY-001/events.jsonl
  2. 调 RunState.rebuild(events, run_id) 反扫重建 → 断言无异常 + state == "paused"
  3. 模拟 /workflow:continue 命令路径（直接调用 Python 实现）→ 断言无错
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

# conftest.py 已注入 scripts/lib
REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "legacy_run"

# run_state 从 scripts/lib 导入
from run_state import RunState  # noqa: E402


# ============================================================================
# 工具函数
# ============================================================================

def _load_events_from_fixture(run_id: str) -> list[dict]:
    """从 fixture 目录加载 events.jsonl，返回事件列表。

    失败时抛出含路径的明确异常。
    """
    jsonl_path = LEGACY_FIXTURE_DIR / ".workflow" / "runs" / run_id / "events.jsonl"
    if not jsonl_path.exists():
        raise FileNotFoundError(
            f"Legacy run fixture 不存在：{jsonl_path}。"
            f"请确认 tests/e2e/fixtures/legacy_run/.workflow/runs/{run_id}/events.jsonl 已创建。"
        )
    events: list[dict] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                try:
                    events.append(json.loads(stripped))
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"events.jsonl 含损坏 JSON 行（path={jsonl_path}, line={stripped!r}）：{exc}"
                    ) from exc
    return events


# ============================================================================
# TC-F11-3 主测试
# ============================================================================

def test_legacy_run_rebuild_state() -> None:
    """TC-F11-3 AC-E2E Part 1：反扫 fixture events.jsonl，RunState.rebuild 无异常 + state==paused。

    fixture：tests/e2e/fixtures/legacy_run/.workflow/runs/RUN-LEGACY-001/events.jsonl
    验证：
      - read_events 能无损解析所有 6 条事件（无 warnings）
      - RunState.rebuild 不抛异常
      - 重建后 state == "paused"（最后一条 workflow_paused 事件）
      - run_id 正确回填
    """
    run_id = "RUN-LEGACY-001"
    events = _load_events_from_fixture(run_id)

    assert len(events) == 6, (
        f"fixture events.jsonl 应含 6 条事件，实际 {len(events)} 条"
    )

    # 调 RunState.rebuild 反扫重建
    state = RunState.rebuild(events=events, run_id=run_id)

    assert state.state == "paused", (
        f"RunState.rebuild 后 state 应为 paused，实际 {state.state!r}。"
        f"events 末尾应为 workflow_paused 事件。"
    )
    assert state.run_id == run_id, (
        f"RunState.run_id 应为 {run_id!r}，实际 {state.run_id!r}"
    )
    assert len(state.warnings) == 0, (
        f"RunState.rebuild 不应产生 warnings，实际 {state.warnings}"
    )


def test_legacy_run_node_outputs() -> None:
    """TC-F11-3 AC-E2E Part 2：验证反扫后 node_outputs 包含已完成的节点。

    fixture 中 definition / tech-research 两个节点均有 node_completed。
    """
    run_id = "RUN-LEGACY-001"
    events = _load_events_from_fixture(run_id)
    state = RunState.rebuild(events=events, run_id=run_id)

    assert "definition" in state.node_outputs, (
        f"node_outputs 应含 definition 节点，实际 keys={list(state.node_outputs.keys())}"
    )
    assert state.node_outputs["definition"]["state"] == "completed", (
        f"definition 节点应为 completed，实际 {state.node_outputs['definition']['state']!r}"
    )
    assert "tech-research" in state.node_outputs, (
        f"node_outputs 应含 tech-research 节点，实际 keys={list(state.node_outputs.keys())}"
    )
    assert state.node_outputs["tech-research"]["state"] == "completed", (
        f"tech-research 节点应为 completed，实际 {state.node_outputs['tech-research']['state']!r}"
    )


def test_legacy_run_meta_fixture_valid() -> None:
    """TC-F11-3 AC-E2E Part 3：验证 fixture meta.yaml 结构合法。

    fixture meta.yaml 模拟 REQ-2026-005 风格（phase=development），
    确认字段完整，供后续 /workflow:continue 路径使用。
    """
    meta_path = LEGACY_FIXTURE_DIR / "meta.yaml"
    assert meta_path.exists(), f"legacy_run fixture meta.yaml 不存在：{meta_path}"

    with meta_path.open("r", encoding="utf-8") as f:
        try:
            meta = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ValueError(
                f"legacy_run fixture meta.yaml YAML 解析失败（path={meta_path}）：{exc}"
            ) from exc

    assert isinstance(meta, dict), f"meta.yaml 应为 YAML mapping，实际 {type(meta)}"
    required_fields = ["id", "title", "phase", "created_at", "branch", "base_branch"]
    for field in required_fields:
        assert field in meta, (
            f"meta.yaml 缺少必要字段 {field!r}（path={meta_path}）"
        )
    assert meta["phase"] == "development", (
        f"fixture meta.yaml phase 应为 development（模拟中间阶段），实际 {meta['phase']!r}"
    )


def test_legacy_run_continue_path_no_error(tmp_path: Path) -> None:
    """TC-F11-3 AC-E2E Part 4：模拟 /workflow:continue 路径，不应抛异常。

    由于 /workflow:continue 最终调用 workflow_continue.py + run_state 引擎，
    此处用轻量 Python 实现验证：
      1. RunState.rebuild 重建 paused 状态（模拟 continue 前读取）
      2. 向 events 追加 run_resumed 事件（模拟 continue 后写入）
      3. 再次 rebuild → state 不变（run_resumed 不映射 WORKFLOW_EVENT_TO_STATE）
    不实际改测试机其他需求库（通过 tmp_path 隔离）。
    """
    from run_state import append_event

    run_id = "RUN-LEGACY-001"
    events = _load_events_from_fixture(run_id)
    state = RunState.rebuild(events=events, run_id=run_id)
    assert state.state == "paused", "前置条件：初始状态应为 paused"

    # 模拟 continue：写 run_resumed 事件到 tmp_path 的 jsonl
    jsonl_path = tmp_path / "test-continue.jsonl"
    resume_event = {
        "type": "run_resumed",
        "run_id": run_id,
        "ts": "2026-01-01 11:00:00",
        "data": {"resumed_by": "workflow:continue"},
    }
    append_event(jsonl_path, resume_event)

    # 读取后追加到原 events 重建（模拟 continue 后读取完整 jsonl）
    with jsonl_path.open("r", encoding="utf-8") as f:
        resumed_events_raw = [json.loads(l.strip()) for l in f if l.strip()]

    all_events = events + resumed_events_raw
    state_after_resume = RunState.rebuild(events=all_events, run_id=run_id)

    # run_resumed 不映射 WORKFLOW_EVENT_TO_STATE → state 仍为 paused
    assert state_after_resume.state == "paused", (
        f"run_resumed 不改变 state，应仍为 paused，实际 {state_after_resume.state!r}"
    )
    assert len(state_after_resume.warnings) == 0, (
        f"continue 路径不应产生 warnings，实际 {state_after_resume.warnings}"
    )

    # ── 真调 workflow_continue.main() 验证 _resolve_run_dir / validate_state_for_cmd 路径 ──
    from workflow_continue import main as wf_continue_main

    # 在 tmp_path 下建 runs/<run_id>/run-state.jsonl（_resolve_run_dir D-007 新路径）
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_state_jsonl = run_dir / "run-state.jsonl"
    # 把 fixture events 写入 run-state.jsonl（workflow_continue 读此文件）
    with run_state_jsonl.open("w", encoding="utf-8") as f:
        for evt in events:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")

    rc = wf_continue_main([run_id], repo_root=tmp_path)
    assert rc == 0, (
        f"workflow_continue.main([{run_id!r}], repo_root=tmp_path) 应返回 0，实际 rc={rc}"
    )
