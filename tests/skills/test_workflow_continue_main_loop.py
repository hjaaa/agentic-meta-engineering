"""F-007/F-008 · workflow_continue.py main loop 单测（happy path + 辅助函数 + 端到端）。

覆盖范围（_main_loop 主循环 + 辅助函数 + dispatcher 集成 e2e）：
  TC build_node_map  _build_node_map 辅助函数单测（映射构造 + 跳过无 id 节点）
  TC next_node       _next_node 辅助函数单测（hint 优先 / 无 hint 用 next / 无 next 返 None）
  TC-F7-3  failed outcome：节点派发返回 failed，main loop 调 _handle_failure
  TC-F7-4  node_outputs 结构正确：completed 时含 output / state / data 三键
  TC-F7-5  unknown node 容错：写 workflow_failed + state=failed
  TC-F8-5  main loop 端到端：mock dispatch_node，standard-8phase 前 3 节点 completed × 3

outcome 路由（approval_pending / loop_continue / sub_workflow_pending）单测移至：
  test_workflow_continue_outcomes.py（F-NEW-7 拆分，按 outcome 维度独立归档）

_handle_failure 的 retry/skip/abort 单测移至：
  test_workflow_continue_failure_handler.py

外部依赖（jsonl IO）使用 tmp_path；mock workflow doc。
pytest 命名规范：test_<场景>_<期望>（CLAUDE.md §7）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------- 路径注入 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import RunState, read_events  # noqa: E402
from workflow_continue import _main_loop, _build_node_map  # noqa: E402
from workflow_scheduler import _next_node  # noqa: E402


# ============================================================================
# Fixture
# ============================================================================


@pytest.fixture()
def jsonl_path(tmp_path: Path) -> Path:
    """返回一个临时 jsonl 文件路径（父目录已存在）。"""
    return tmp_path / "run-state.jsonl"


@pytest.fixture()
def mock_workflow_2nodes() -> dict:
    """2 节点 workflow：node-a (bash) → node-b (approval)。"""
    return {
        "id": "test-wf",
        "name": "test-workflow",
        "version": "1.0",
        "category": "requirement",
        "nodes": [
            {
                "id": "node-a",
                "bash": "echo 'hello'",
                "next": "node-b",
            },
            {
                "id": "node-b",
                "approval": {"prompt": "Approve?"},
            },
        ],
    }


# ============================================================================
# Helper 函数单测
# ============================================================================


def test_build_node_map_constructs_mapping():
    """_build_node_map 正确构造 id → node dict 映射。"""
    workflow = {
        "nodes": [
            {"id": "a", "bash": "cmd1"},
            {"id": "b", "bash": "cmd2"},
        ]
    }
    node_map = _build_node_map(workflow)
    assert "a" in node_map
    assert "b" in node_map
    assert node_map["a"]["bash"] == "cmd1"


def test_build_node_map_skips_nodes_without_id():
    """_build_node_map 跳过不含 id 字段的节点。"""
    workflow = {
        "nodes": [
            {"id": "a", "bash": "cmd1"},
            {"bash": "cmd2"},  # 无 id
        ]
    }
    node_map = _build_node_map(workflow)
    assert len(node_map) == 1
    assert "a" in node_map


def test_next_node_prioritizes_hint():
    """_next_node：hint 非 None 时优先返回 hint。"""
    node = {"id": "a", "next": "b"}
    result = _next_node(node, "override")
    assert result == "override"


def test_next_node_falls_back_to_next_field():
    """_next_node：hint 为 None 时返回 node.next。"""
    node = {"id": "a", "next": "b"}
    result = _next_node(node, None)
    assert result == "b"


def test_next_node_returns_none_when_no_next():
    """_next_node：无 next 字段且无 hint 时返回 None。"""
    node = {"id": "a"}
    result = _next_node(node, None)
    assert result is None


# ============================================================================
# TC-F7-3 · failed outcome
# ============================================================================


def test_main_loop_failed_outcome_with_abort_sets_state_failed_and_breaks(
    jsonl_path,
    tmp_path,
):
    """节点设 on_failure=abort 时，派发返回 failed → main loop 写 workflow_failed + state=failed + break。

    场景：node-a 带 on_failure=abort，dispatch 返回 failed
    期望：state 变为 failed，loop break，current_node 保持 node-a
    """
    from workflow_dispatcher import DispatchResult

    workflow = {
        "id": "test-wf",
        "name": "test-workflow",
        "version": "1.0",
        "category": "requirement",
        "nodes": [
            {
                "id": "node-a",
                "bash": "echo 'hello'",
                "next": "node-b",
                "on_failure": "abort",  # 显式 abort，保证 state=failed
            },
            {
                "id": "node-b",
                "approval": {"prompt": "Approve?"},
            },
        ],
    }
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:
        mock_dispatch.return_value = DispatchResult(
            outcome="failed",
            error="node-a execution failed",
        )

        _main_loop(run_state, workflow, tmp_path, tmp_path, jsonl_path)

        # 期望：state 变为 failed，loop break，current_node 保持不变
        assert run_state.state == "failed"
        assert run_state.current_node == "node-a"


# ============================================================================
# TC-F7-4 · node_outputs 结构正确
# ============================================================================


def test_main_loop_node_outputs_structure(
    mock_workflow_2nodes,
    jsonl_path,
    tmp_path,
):
    """completed outcome 时，node_outputs 条目含 output / state / data 三键。"""
    from workflow_dispatcher import DispatchResult

    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:
        mock_dispatch.return_value = DispatchResult(
            outcome="completed",
            output="test-output",
        )

        _main_loop(run_state, mock_workflow_2nodes, tmp_path, tmp_path, jsonl_path)

        assert "node-a" in run_state.node_outputs
        entry = run_state.node_outputs["node-a"]
        assert entry["output"] == "test-output"
        assert entry["state"] == "completed"
        assert entry["data"]["output"] == "test-output"


# ============================================================================
# TC-F7-5 · unknown node 容错
# ============================================================================


def test_main_loop_unknown_node_writes_workflow_failed_event(
    jsonl_path,
    tmp_path,
):
    """current_node 指向不存在的节点，写 workflow_failed 事件并设 state=failed。"""
    workflow = {"nodes": []}  # 空节点列表
    run_state = RunState(run_id="REQ-2026-010", current_node="nonexistent", state="running")

    _main_loop(run_state, workflow, tmp_path, tmp_path, jsonl_path)

    # 期望：state=failed，workflow_failed 事件写入
    assert run_state.state == "failed"
    events, _ = read_events(jsonl_path)
    workflow_failed_events = [e for e in events if e.get("type") == "workflow_failed"]
    assert len(workflow_failed_events) == 1
    assert "未知节点" in workflow_failed_events[0]["data"]["error"]


# ============================================================================
# TC-F8-5 · main loop 端到端：standard-8phase 前 3 节点 completed × 3
# ============================================================================


def test_main_loop_completes_three_nodes_with_mocked_dispatch(tmp_path, jsonl_path):
    """端到端：mock dispatch_node，按 standard-8phase 前 3 节点顺序返 completed × 3。

    场景：3 节点 workflow 全部返回 completed
      bootstrap-validate → req-input-normalize → req-draft
    期望：main loop 正常结束（state=running，current_node=None）
          node_outputs 含全部 3 节点
          dispatch_node 被调用 3 次
    """
    from workflow_dispatcher import DispatchResult

    workflow = {
        "id": "standard-8phase",
        "name": "standard-8phase",
        "version": "1.0",
        "category": "requirement",
        "nodes": [
            {
                "id": "bootstrap-validate",
                "bash": "echo 'bootstrap'",
                "next": "req-input-normalize",
            },
            {
                "id": "req-input-normalize",
                "bash": "echo 'normalize'",
                "next": "req-draft",
            },
            {
                "id": "req-draft",
                "bash": "echo 'draft'",
                # 末尾节点，无 next
            },
        ],
    }

    run_state = RunState(
        run_id="REQ-2026-010",
        current_node="bootstrap-validate",
        state="running",
    )

    node_outputs_map = {
        "bootstrap-validate": "bootstrap output",
        "req-input-normalize": "normalize output",
        "req-draft": "draft output",
    }

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:

        def dispatch_side_effect(node, *args, **kwargs):
            node_id = node.get("id")
            output = node_outputs_map.get(node_id, "")
            return DispatchResult(outcome="completed", output=output)

        mock_dispatch.side_effect = dispatch_side_effect

        _main_loop(run_state, workflow, tmp_path, tmp_path, jsonl_path)

    # main loop 应正常结束：current_node=None；P1-c（codex round-3）修后 state 翻 completed
    # 且写 workflow_completed 事件
    assert run_state.current_node is None
    assert run_state.state == "completed", "末节点跑完应翻 state=completed（P1-c 修后）"
    types = [e["type"] for e in read_events(jsonl_path)[0]]
    assert "workflow_completed" in types, "P1-c：main loop 正常退出应写 workflow_completed 事件"

    # 全部 3 节点的 node_outputs 已记录
    assert "bootstrap-validate" in run_state.node_outputs
    assert "req-input-normalize" in run_state.node_outputs
    assert "req-draft" in run_state.node_outputs

    assert run_state.node_outputs["bootstrap-validate"]["output"] == "bootstrap output"
    assert run_state.node_outputs["req-draft"]["output"] == "draft output"

    # dispatch 应被调用 3 次
    assert mock_dispatch.call_count == 3


# ============================================================================
# codex P1（2026-05-12 round-4）：crash 在 _advance_after_completed 之前重启不应
# 误写 workflow_completed（P1-c v2 回归）
# ============================================================================

class TestMainLoopCrashWindowDoesNotFinalize:
    """codex round-4 P1：rebuild 看到 node_completed 后 current_node 会被置 None
    （rebuild 凭"current_node == node_id 则置 None"判定），与"自然跑完"无法区分。
    旧实现在 _main_loop 退出后凭 `current_node is None` 写 workflow_completed，
    会把 crash 在 advance 之前的 run 误判为完成，截断剩余拓扑。

    P1-c v2 修后：workflow_completed 只在 _route_outcome 内 outcome=completed/loop_done/
    sub_workflow_done 推进且 next is None 时写——crash 路径根本不会进 _route_outcome，
    不会误触发。
    """

    def test_main_loop_skips_finalize_when_rebuild_yields_none_current_node(
        self,
        jsonl_path,
        tmp_path,
    ):
        """模拟 crash 场景：rebuild 把 current_node 置 None，但 state 仍为 running 且
        拓扑还有未完成节点。

        F-004 rev2（F-CR-002）后：_main_loop 在 finalize 与 while 之间插了 bootstrap，
        会调 _select_next_dispatch_target 反扫 last_visited → _next_node 推进 → 继续
        跑剩余节点，不再"保持 running 不推进"。

        本测覆盖 bootstrap 的"无可派发节点"分支：mock _select_next_dispatch_target 返 None
        来模拟 yaml/jsonl 不一致或拓扑全阻塞场景——此时 while 因 current_node 仍是 None 不
        进入，state 保持 running，**不**写 workflow_completed。
        """
        # 模拟 crash 后 rebuild 的产物：current_node=None（rebuild 看到 node-a 已 completed），
        # 但工作流还有 node-b 没跑完
        from run_state import append_event as _append
        _append(jsonl_path, {
            "type": "node_completed",
            "node_id": "node-a",
            "data": {"output": "ok"},
        })

        workflow = {
            "nodes": [
                {"id": "node-a", "bash": "echo a", "next": "node-b"},
                {"id": "node-b", "bash": "echo b"},
            ]
        }
        run_state = RunState(
            run_id="REQ-CRASH-001",
            current_node=None,  # rebuild 后 current_node 已 None
            state="running",     # state 仍是 running（无 workflow_completed 事件）
        )

        # F-CR-002 新语义：mock _select_next_dispatch_target 返 None 模拟"无可派发节点"，
        # bootstrap 不置 current_node → while 不进入 → state 保持 running。
        with patch(
            "workflow_continue._select_next_dispatch_target",
            return_value=None,
        ):
            _main_loop(run_state, workflow, tmp_path, tmp_path, jsonl_path)

        # bootstrap 返 None 时：state 应保持 running，**不**翻 completed/failed
        assert run_state.state == "running", (
            f"bootstrap 拿不到下一节点应保持 running 让用户介入；"
            f"实际 state={run_state.state!r}"
        )
        # current_node 仍为 None（while 未进入即未派发）
        assert run_state.current_node is None
        # jsonl 不应含 workflow_completed
        events, _ = read_events(jsonl_path)
        types = [e["type"] for e in events]
        assert "workflow_completed" not in types, (
            f"无可派发节点时不应写 workflow_completed 事件，实际 jsonl events: {types}"
        )

    def test_main_loop_bootstrap_resumes_remaining_chain_after_crash(
        self,
        jsonl_path,
        tmp_path,
    ):
        """F-CR-002 正向覆盖：crash-window 场景下 bootstrap 通过 _select_next_dispatch_target
        反扫 last_visited 后能正确推进到剩余链路。

        场景：node-a 已 completed（jsonl 有事件 + node_outputs 含 SUCCESS_TERMINAL），
              node-b 未跑完；rebuild 后 current_node=None / state=running。
        期望：bootstrap 通过分支 b 反扫 node_outputs 找到 last_visited=node-a，调
              _next_node 返 node-b → 推进继续跑 → 最终 completed。
        """
        from workflow_dispatcher import DispatchResult
        from run_state import append_event as _append

        # 模拟 rebuild 后状态：node_outputs 含 node-a SUCCESS_TERMINAL
        _append(jsonl_path, {
            "type": "node_completed",
            "node_id": "node-a",
            "data": {"output": "ok"},
        })

        workflow = {
            "nodes": [
                {"id": "node-a", "bash": "echo a", "next": "node-b"},
                {"id": "node-b", "bash": "echo b"},
            ]
        }
        run_state = RunState(
            run_id="REQ-RESUME-001",
            current_node=None,
            state="running",
            node_outputs={
                "node-a": {"output": "ok", "state": "completed", "data": {}}
            },
        )

        with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:
            mock_dispatch.return_value = DispatchResult(
                outcome="completed",
                output="b-output",
            )
            _main_loop(run_state, workflow, tmp_path, tmp_path, jsonl_path)

        # bootstrap 把 current_node 设为 node-b → 派发 → completed → 推进 None →
        # finalize 写 workflow_completed
        assert run_state.state == "completed", (
            f"bootstrap 应推进 node-b 完成全链；实际 state={run_state.state!r}"
        )
        assert mock_dispatch.call_count == 1, "应仅派发剩余 node-b 一次"
        # dispatcher 第一次调用即派 node-b
        dispatched_node = mock_dispatch.call_args_list[0].args[0]
        assert dispatched_node["id"] == "node-b"

    def test_main_loop_auto_finalizes_when_rebuild_yields_none_after_last_node(
        self,
        jsonl_path,
        tmp_path,
    ):
        """codex round-5 P2：crash 在 _advance_after_completed 与 _finalize_if_topology_done
        之间——末节点 node_completed 已落盘 + current_node 置 None，但 workflow_completed
        没写。重启后 _main_loop 入口的 _finalize_after_rebuild_if_last_topology_node
        helper 检测到"最后 completed 节点无 next"，补写 workflow_completed 把 state 翻
        completed。
        """
        from run_state import append_event as _append
        # 末节点（node-b 无 next）的 node_completed 已落盘
        _append(jsonl_path, {
            "type": "node_completed",
            "node_id": "node-b",
            "data": {"output": "final"},
        })

        workflow = {
            "nodes": [
                {"id": "node-a", "bash": "echo a", "next": "node-b"},
                {"id": "node-b", "bash": "echo b"},
            ]
        }
        run_state = RunState(
            run_id="REQ-CRASH-002",
            current_node=None,  # rebuild 在 node_completed 分支把 current_node 置 None
            state="running",     # 但还没人写 workflow_completed
        )

        _main_loop(run_state, workflow, tmp_path, tmp_path, jsonl_path)

        # round-5 P2 关键回归：补写后 state 应翻 completed
        assert run_state.state == "completed", (
            f"末节点 completed 后 crash 应被 finalize helper 补救，"
            f"state 应翻 completed；实际 state={run_state.state!r}"
        )
        events, _ = read_events(jsonl_path)
        types = [e["type"] for e in events]
        assert "workflow_completed" in types, (
            f"finalize helper 应补写 workflow_completed 事件，实际 jsonl events: {types}"
        )


# ============================================================================
# codex P1（2026-05-12 round-2）：_load_workflow_for_run meta key 对齐
# ============================================================================

class TestLoadWorkflowForRunMetaKey:
    """codex P1：_load_workflow_for_run 旧版误读 meta["workflow_template_path"]，
    但 workflow_run._run_generic 写 meta.yaml 时 key 是 template_path——
    导致 non-requirement run（如 review/code-review-embedded.yaml）resume 时
    拿不到真路径而走默认 .claude/workflows/requirement/<name>.yaml 找不到模板失败。

    修后：优先 template_path，兼容历史 workflow_template_path 字段。
    """

    def _make_repo(self, tmp_path: Path, workflow_name: str, category: str = "review"):
        """构造最小可用的 .claude/workflows/<category>/<name>.yaml 模板 + meta.yaml + jsonl。"""
        # 真模板：放 review/ 子目录，避免命中 requirement/ 默认路径
        wf_dir = tmp_path / ".claude" / "workflows" / category
        wf_dir.mkdir(parents=True, exist_ok=True)
        wf_path = wf_dir / f"{workflow_name}.yaml"
        wf_path.write_text(
            f"name: {workflow_name}\n"
            "version: 1\n"
            f"category: {category}\n"
            "nodes:\n"
            "  - id: stub-node\n"
            "    bash: echo stub\n",
            encoding="utf-8",
        )

        # 子 run 目录
        run_dir = tmp_path / "runs" / "RUN-20260512-X"
        run_dir.mkdir(parents=True)

        return wf_path, run_dir

    def test_load_workflow_for_run_reads_template_path_key(self, tmp_path: Path):
        """meta.yaml 用 template_path（_run_generic 的实际 key）应被识别。"""
        import yaml as _yaml  # noqa: PLC0415
        from workflow_continue import _load_workflow_for_run  # noqa: PLC0415

        wf_path, run_dir = self._make_repo(tmp_path, "code-review-embedded")
        # 写 meta.yaml：key=template_path（_run_generic 实际写入的 key）
        meta = {
            "run_id": "RUN-20260512-X",
            "template": "code-review-embedded",
            "template_path": str(wf_path.relative_to(tmp_path)),
            "state": "running",
        }
        (run_dir / "meta.yaml").write_text(
            _yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        rs = RunState(run_id="RUN-20260512-X")
        rs.workflow_name = "code-review-embedded"

        workflow = _load_workflow_for_run(rs, run_dir, tmp_path)
        assert workflow is not None, "P1 修后应能识别 template_path key 加载 workflow"
        assert workflow.get("name") == "code-review-embedded"

    def test_load_workflow_for_run_back_compat_workflow_template_path_key(self, tmp_path: Path):
        """历史 meta.yaml 用 workflow_template_path 也应兼容识别。"""
        import yaml as _yaml  # noqa: PLC0415
        from workflow_continue import _load_workflow_for_run  # noqa: PLC0415

        wf_path, run_dir = self._make_repo(tmp_path, "legacy-name")
        meta = {
            "run_id": "RUN-20260512-X",
            "workflow_template_path": str(wf_path.relative_to(tmp_path)),  # 旧 key
        }
        (run_dir / "meta.yaml").write_text(
            _yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        rs = RunState(run_id="RUN-20260512-X")
        rs.workflow_name = "legacy-name"

        workflow = _load_workflow_for_run(rs, run_dir, tmp_path)
        assert workflow is not None, "向后兼容读取 workflow_template_path 失败"
