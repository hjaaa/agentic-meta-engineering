"""F-006 · workflow_reject.py 验收测试（AC-03b/c）。

覆盖：
- AC-03b：reject attempt=1/max=3 → 原子写 [approval_rejected(attempt=1),
  approval_repair_started(attempt=1, max=3)]；state 派生 awaiting_claude_action
- AC-03b：reject reason ≥ 4KB（让 batch 超 4096） → manifest fallback；
  event.data.reason 被替换为 reason_ref，manifest/<event_id>.txt 落盘
- 反向：reason < 3.5KB 且 batch < 4KB → 直写 inline，无 manifest
- AC-03c：reject attempt=3/max=3 → 原子写 [approval_rejected, node_failed,
  workflow_failed]；state→failed
- yaml on_reject.max_attempts=5 override → 引擎 honor；缺省走 D-009 默认 3
- yaml on_reject.max_attempts=0/-2 非法值 → 静默降级 D-009 默认 + logging.warning
- isatty=False → exit 2
- reason < 8 字符 → exit 1
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import RunState, append_event, read_events  # noqa: E402
import workflow_reject  # noqa: E402

# 复用 e2e 测试的断言 helper（避免双份维护——同根因来自 review F-CR-008/F-CR-016/F-CR-018）
_E2E_DIR = REPO_ROOT / "tests" / "e2e"
if str(_E2E_DIR) not in sys.path:
    sys.path.insert(0, str(_E2E_DIR))
from test_approval_reject_repair import _assert_after_reject  # noqa: E402

WORKFLOW_REJECT_PY = REPO_ROOT / "scripts" / "lib" / "workflow_reject.py"


# ---------- 辅助 ----------

_MIN_TEMPLATE = """\
name: test-template
version: 1
category: assist
description: F-006 reject test 用模板
nodes:
  - id: gate-design
    approval:
      message: "请审查方案"
      on_reject:
        prompt: "修复后重提"
        max_attempts: 3
"""


def _write_workflow_yaml(repo: Path, content: str = _MIN_TEMPLATE) -> Path:
    """在 repo/.claude/workflows/requirement/test-template.yaml 写最小 workflow yaml。"""
    yaml_dir = repo / ".claude" / "workflows" / "requirement"
    yaml_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = yaml_dir / "test-template.yaml"
    yaml_path.write_text(content, encoding="utf-8")
    return yaml_path


def _seed_approval_pending(
    repo: Path,
    run_id: str,
    node_id: str = "gate-design",
    prior_rejects: int = 0,
) -> Path:
    """在 repo/runs/<run_id>/run-state.jsonl 写至 approval_pending；可叠加历史 rejects。

    每条历史 reject 写 [approval_rejected, approval_repair_started, approval_repair_completed]
    三联事件，确保 rebuild 后仍是 approval_pending（attempt 计数靠反扫 approval_rejected）。
    """
    run_dir = repo / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    jsonl = run_dir / "run-state.jsonl"
    append_event(jsonl, {
        "type": "workflow_started",
        "run_id": run_id,
        "data": {"workflow_name": "test-template", "arguments": ""},
    })
    append_event(jsonl, {"type": "node_started", "run_id": run_id, "node_id": node_id})
    append_event(jsonl, {
        "type": "approval_pending",
        "run_id": run_id,
        "node_id": node_id,
    })
    for i in range(1, prior_rejects + 1):
        append_event(jsonl, {
            "type": "approval_rejected",
            "run_id": run_id,
            "node_id": node_id,
            "data": {"reason": f"prior reject #{i}", "attempt": i},
        })
        append_event(jsonl, {
            "type": "approval_repair_started",
            "run_id": run_id,
            "node_id": node_id,
            "data": {"attempt": i, "max_attempts": 3, "prompt_ref": "p"},
        })
        append_event(jsonl, {
            "type": "approval_repair_completed",
            "run_id": run_id,
            "node_id": node_id,
            "data": {"attempt": i},
        })
    return run_dir


def _patch_git_branch(run_id: str):
    mock_result = MagicMock()
    mock_result.stdout = f"feat/req-{run_id}\n"
    return patch("subprocess.run", return_value=mock_result)


def _run_reject(reason_args: list[str], tmp_repo: Path, run_id: str) -> int:
    """带 isatty=True + git mock 调 workflow_reject.main。"""
    with _patch_git_branch(run_id):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            return workflow_reject.main(reason_args, repo_root=tmp_repo)


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """临时仓库根目录（runs / requirements / .claude/workflows）。"""
    (tmp_path / "runs").mkdir()
    (tmp_path / "requirements").mkdir()
    (tmp_path / ".claude" / "workflows" / "requirement").mkdir(parents=True)
    return tmp_path


# ---------- AC-03b：attempt=1/max=3 ----------

def test_reject_attempt_1_writes_repair_started_inline(tmp_repo: Path) -> None:
    """AC-03b：首次 reject 应原子写 [approval_rejected(attempt=1), approval_repair_started]。

    锚定字段（review F-CR-016）：
    - approval_repair_started.data.prompt_ref == 'approval.on_reject.prompt'
      （detailed-design §2.2.2 L151 显式必填）
    """
    _write_workflow_yaml(tmp_repo)
    run_id = "RUN-F006-REJ-001"
    _seed_approval_pending(tmp_repo, run_id, prior_rejects=0)

    rc = _run_reject(["设计方案存在严重缺陷"], tmp_repo, run_id)
    assert rc == 0, f"reject attempt=1 应返回 0，实际 rc={rc}"

    jsonl = tmp_repo / "runs" / run_id / "run-state.jsonl"
    events, warnings = read_events(jsonl)
    # 复用 e2e helper 做 [rejected, repair_started] 形状 + attempt + max + prompt_ref 一站式校验
    _assert_after_reject(events, warnings, expected_attempt=1, expected_max=3)

    rej = events[-2]
    assert rej["data"]["reason"] == "设计方案存在严重缺陷"


def test_reject_attempt_1_state_derives_awaiting_claude_action(tmp_repo: Path) -> None:
    """AC-03b：attempt<max 后 state 应派生 awaiting_claude_action（rebuild 验证）。"""
    _write_workflow_yaml(tmp_repo)
    run_id = "RUN-F006-REJ-002"
    _seed_approval_pending(tmp_repo, run_id, prior_rejects=0)

    rc = _run_reject(["设计方案不合理需重审"], tmp_repo, run_id)
    assert rc == 0

    jsonl = tmp_repo / "runs" / run_id / "run-state.jsonl"
    events, warnings = read_events(jsonl)
    state = RunState.rebuild(events, run_id=run_id, warnings=warnings)
    assert state.state == "awaiting_claude_action", (
        f"reject attempt<max 后应 awaiting_claude_action，实际 {state.state}"
    )
    assert state.pending_approval == "gate-design", (
        f"approval_repair_started 应保留 pending_approval，实际 {state.pending_approval}"
    )


# ---------- AC-03b：reason ≥ 4KB → manifest fallback ----------

def test_reject_large_reason_triggers_manifest_fallback(tmp_repo: Path) -> None:
    """AC-03b：reason ≥ 4KB 触发 manifest fallback；jsonl 仅留 reason_ref + 落盘 manifest 文件。"""
    _write_workflow_yaml(tmp_repo)
    run_id = "RUN-F006-REJ-003"
    _seed_approval_pending(tmp_repo, run_id, prior_rejects=0)

    big_reason = "X" * 5000  # 5KB > 4KB batch + > 3500 单字段入选
    rc = _run_reject([big_reason], tmp_repo, run_id)
    assert rc == 0, f"reject 大 reason 应返回 0（manifest fallback），实际 rc={rc}"

    jsonl = tmp_repo / "runs" / run_id / "run-state.jsonl"
    events, warnings = read_events(jsonl)
    assert not warnings, f"不应有 jsonl warn，实际：{warnings}"
    rej = events[-2]
    assert rej["type"] == "approval_rejected"
    assert "reason" not in rej.get("data", {}), (
        f"大 reason 应被外置，data 内不应再有 inline reason，实际 data={rej.get('data')}"
    )
    reason_ref = rej["data"].get("reason_ref")
    assert isinstance(reason_ref, dict) and reason_ref.get("path", "").startswith("manifest/"), (
        f"reason_ref 应指向 manifest/ 文件，实际：{reason_ref}"
    )

    manifest_file = tmp_repo / "runs" / run_id / reason_ref["path"]
    assert manifest_file.exists(), f"manifest 文件应落盘：{manifest_file}"
    assert manifest_file.read_text(encoding="utf-8") == big_reason
    index_path = tmp_repo / "runs" / run_id / "manifest" / "index.txt"
    assert index_path.exists(), "manifest/index.txt 应存在"


def test_reject_small_reason_inline_no_manifest(tmp_repo: Path) -> None:
    """反向：reason 短（<3.5KB）且 batch <4KB → 直写 inline，无 manifest。"""
    _write_workflow_yaml(tmp_repo)
    run_id = "RUN-F006-REJ-004"
    _seed_approval_pending(tmp_repo, run_id, prior_rejects=0)

    short_reason = "Y" * 100  # 100 字节，远低于阈值
    rc = _run_reject([short_reason], tmp_repo, run_id)
    assert rc == 0

    jsonl = tmp_repo / "runs" / run_id / "run-state.jsonl"
    events, _ = read_events(jsonl)
    rej = events[-2]
    assert rej["data"].get("reason") == short_reason, (
        f"短 reason 应 inline 直写，实际 data={rej.get('data')}"
    )
    assert "reason_ref" not in rej["data"], "短 reason 不应触发 manifest fallback"
    manifest_dir = tmp_repo / "runs" / run_id / "manifest"
    assert not manifest_dir.exists(), "短 reason 不应落 manifest 目录"


# ---------- AC-03c：attempt=3/max=3 → 三事件 + state=failed ----------

def test_reject_attempt_eq_max_writes_node_failed_and_workflow_failed(tmp_repo: Path) -> None:
    """AC-03c：attempt 达上限 → 原子写 3 事件，state→failed。"""
    _write_workflow_yaml(tmp_repo)
    run_id = "RUN-F006-REJ-005"
    _seed_approval_pending(tmp_repo, run_id, prior_rejects=2)  # 已 2 次，本次 = 3 = max

    rc = _run_reject(["第三次仍不合格需关闭流程"], tmp_repo, run_id)
    assert rc == 0, f"reject attempt=max 应返回 0，实际 rc={rc}"

    jsonl = tmp_repo / "runs" / run_id / "run-state.jsonl"
    events, warnings = read_events(jsonl)
    assert not warnings, f"不应有 jsonl warn，实际：{warnings}"
    types = [e["type"] for e in events]
    assert types[-3:] == ["approval_rejected", "node_failed", "workflow_failed"], (
        f"达上限应原子写 3 事件，实际末位 3：{types[-3:]}"
    )
    rej = events[-3]
    failed = events[-2]
    wf_failed = events[-1]
    assert rej["data"]["attempt"] == 3
    assert failed["data"]["reason"] == "approval_attempts_exhausted"
    assert failed["data"]["attempt"] == 3
    assert wf_failed["data"]["reason"] == "approval_attempts_exhausted"
    assert wf_failed["data"]["node_id"] == "gate-design"

    state = RunState.rebuild(events, run_id=run_id, warnings=warnings)
    assert state.state == "failed", (
        f"达上限后 state 应 failed，实际 {state.state}"
    )


# ---------- yaml on_reject.max_attempts=5 override ----------

def test_reject_honors_yaml_max_attempts_override(tmp_repo: Path) -> None:
    """yaml on_reject.max_attempts=5 → attempt=3/max=5 仍走 repair（不进 failed）。"""
    yaml_with_5 = _MIN_TEMPLATE.replace("max_attempts: 3", "max_attempts: 5")
    _write_workflow_yaml(tmp_repo, yaml_with_5)
    run_id = "RUN-F006-REJ-006"
    _seed_approval_pending(tmp_repo, run_id, prior_rejects=2)  # 本次 = 3 < 5

    rc = _run_reject(["override 测试 reason"], tmp_repo, run_id)
    assert rc == 0

    jsonl = tmp_repo / "runs" / run_id / "run-state.jsonl"
    events, _ = read_events(jsonl)
    types = [e["type"] for e in events]
    assert types[-2:] == ["approval_rejected", "approval_repair_started"], (
        f"override max=5 attempt=3 应仍走 repair，实际末位 2：{types[-2:]}"
    )
    repair = events[-1]
    assert repair["data"]["max_attempts"] == 5
    assert repair["data"]["attempt"] == 3


def test_reject_default_max_attempts_when_yaml_missing(tmp_repo: Path) -> None:
    """yaml 不存在 → 走 D-009 默认 max_attempts=3。"""
    # 不写 workflow yaml，让 _load_workflow_node 退化
    run_id = "RUN-F006-REJ-007"
    _seed_approval_pending(tmp_repo, run_id, prior_rejects=2)

    rc = _run_reject(["缺 yaml 兜底测试"], tmp_repo, run_id)
    assert rc == 0

    jsonl = tmp_repo / "runs" / run_id / "run-state.jsonl"
    events, _ = read_events(jsonl)
    types = [e["type"] for e in events]
    # 默认 max=3 + 已 2 次 reject + 本次 = 3 → 达上限
    assert types[-3:] == ["approval_rejected", "node_failed", "workflow_failed"], (
        f"缺 yaml 应走 D-009 默认 max=3，实际末位 3：{types[-3:]}"
    )


# ---------- yaml on_reject.max_attempts 非法值 → 静默降级 + warning（review F-CR-002）----------

@pytest.mark.parametrize("bad_value", [0, -2, "foo"])
def test_reject_invalid_max_attempts_warns_and_falls_back(
    tmp_repo: Path, caplog: pytest.LogCaptureFixture, bad_value: object,
) -> None:
    """yaml on_reject.max_attempts=0/-2/字符串 → 降级 D-009 默认 + 打 logging.warning。

    锚定 review F-CR-002（workflow_loader.py:394-403 校验仅查字段存在不校验类型/范围，
    yaml 笔误绕过 loader 静默 fallback；本函数做最后一道兜底 + 留 audit trail）。
    """
    bad_yaml = _MIN_TEMPLATE.replace("max_attempts: 3", f"max_attempts: {bad_value!r}")
    _write_workflow_yaml(tmp_repo, bad_yaml)
    run_id = f"RUN-F006-REJ-INVALID-{bad_value}".replace(" ", "_")
    _seed_approval_pending(tmp_repo, run_id, prior_rejects=0)

    with caplog.at_level(logging.WARNING):
        rc = _run_reject(["非法 max_attempts 测试"], tmp_repo, run_id)
    assert rc == 0

    # 应打 warning 提示降级 D-009（区分缺字段 None vs 显式非法值）
    assert any(
        "on_reject.max_attempts" in rec.message and "非法" in rec.message
        for rec in caplog.records
    ), f"应有 warning 提示降级 D-009，实际 records={[r.message for r in caplog.records]}"

    # attempt=1 + 默认 max=3 → 走 repair 路径
    jsonl = tmp_repo / "runs" / run_id / "run-state.jsonl"
    events, warnings = read_events(jsonl)
    _assert_after_reject(events, warnings, expected_attempt=1, expected_max=3)


# ---------- isatty=False → exit 2 ----------

def test_isatty_false_returns_exit_2_subprocess() -> None:
    """isatty=False（subprocess 喂空 stdin）→ exit 2（R-S01 不破）。"""
    proc = subprocess.run(
        [sys.executable, str(WORKFLOW_REJECT_PY), "需要修复，理由如下"],
        input="",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 2, (
        f"isatty=False 应 exit 2，实际 {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )


# ---------- reason < 8 字符 → exit 1 ----------

def test_reject_short_reason_returns_exit_1(tmp_repo: Path) -> None:
    """reason < 8 字符 → exit 1。"""
    _write_workflow_yaml(tmp_repo)
    run_id = "RUN-F006-REJ-008"
    _seed_approval_pending(tmp_repo, run_id, prior_rejects=0)

    rc = _run_reject(["短"], tmp_repo, run_id)
    assert rc == 1, f"短 reason 应 exit 1，实际 rc={rc}"


def test_reject_no_reason_returns_exit_1(tmp_repo: Path) -> None:
    """无 reason 参数 → exit 1。"""
    _write_workflow_yaml(tmp_repo)
    run_id = "RUN-F006-REJ-009"
    _seed_approval_pending(tmp_repo, run_id, prior_rejects=0)

    rc = _run_reject([], tmp_repo, run_id)
    assert rc == 1
