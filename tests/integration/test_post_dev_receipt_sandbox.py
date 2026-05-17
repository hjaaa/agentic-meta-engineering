"""F-008 沙盒 e2e — V-02：phase-transition 缺 receipt 触发 GATE-POST-DEV-RECEIPT 拦截（TC-F8-2）。

验收点（detail-design.md §5.4 TC-F1-2 case1）：
  - phase-transition development → testing：features.json 含 done feature 但缺 receipt.json
    → 该 gate 返回 Decision.FAIL（runner 层映射为 exit 1）
  - 反向 case：所有 done feature 都有合法 receipt.json → Decision.PASS
  - skip case：features.json 不存在（早期 REQ）→ precheck 返回 Skip

实现策略（兼顾"真实跑 + 隔离"）：
  - 沙盒 req_dir 用 tmp_path 建（无需占用真 requirements/ 目录）
  - 通过 subprocess 调 python3 -c 启动一个隔离 Python 进程，加载 plugin 真实执行；
    避免 run.py 全套 gates 调用（GATE-WORKSPACE-CLEAN 会因 untracked 沙盒目录误 fail
    淹没 GATE-POST-DEV-RECEIPT 的真实信号）
  - subprocess 退出码：plugin Decision.FAIL → exit 1；PASS → exit 0；SKIP → exit 3

参考：tests/gates/test_post_dev_receipt.py（plugin 直接调用范式）+
     tests/integration/test_feature_lifecycle_signoff_gate.py（subprocess wrapper 范式）。
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path


from ._subprocess_helpers import run_with_timeout

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATES_DIR = _REPO_ROOT / "scripts" / "gates"


def _write_features_json(req_dir: Path, req_id: str, feature_ids: list[str]) -> None:
    """写合法 features.json（每个 feature 必填字段齐全，schema_version=1.0）。"""
    artifacts = req_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": "1.0",
        "requirement_id": req_id,
        "features": [
            {
                "id": fid, "title": f"feature {fid}", "description": f"desc {fid}",
                "modules": [], "depends_on": [], "depends_on_features": [],
                "complexity": "trivial", "touches": [], "acceptance": [],
            }
            for fid in feature_ids
        ],
    }
    (artifacts / "features.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def _write_task_md(tasks_dir: Path, fid: str, status: str) -> None:
    """写 task.md frontmatter。status / complexity / 必填字段齐全。"""
    tasks_dir.mkdir(parents=True, exist_ok=True)
    content = (
        "---\n"
        "schema_version: \"1.0\"\n"
        f"feature_id: {fid}\n"
        f"title: {fid} 沙盒 task\n"
        f"status: {status}\n"
        "complexity: trivial\n"
        "depends_on: []\n"
        "touches: []\n"
        "created_at: 2026-05-06 10:00:00\n"
        "updated_at: 2026-05-06 10:00:00\n"
        "review_report: null\n"
        "---\n"
    )
    (tasks_dir / f"{fid}.md").write_text(content, encoding="utf-8")


def _write_receipt(tasks_dir: Path, fid: str, status: str = "DONE") -> None:
    """写合法 receipt.json（schema_version=1.0，status=DONE / DONE_WITH_CONCERNS）。"""
    concerns = [] if status == "DONE" else ["sandbox 已知疑虑"]
    data = {
        "schema_version": "1.0",
        "feature_id": fid,
        "status": status,
        "commit_sha": "HEAD",
        "files_changed": [],
        "test_summary": "sandbox 通过",
        "touches_violations": [],
        "concerns": concerns,
        "missing_context": "",
        "block_reason": "",
        "timestamp": "2026-05-06T10:00:00+08:00",
    }
    (tasks_dir / f"{fid}.receipt.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )


# ---------- 子进程驱动 plugin（隔离工作区污染影响） ----------

# 子进程脚本：构造 GateContext，调 PostDevReceiptGate.precheck/run，按 Decision 退出。
# decision == FAIL → exit 1；PASS → exit 0；Skip（precheck）→ exit 3；异常 → exit 9
_PLUGIN_RUNNER_TMPL = textwrap.dedent("""\
    import json, sys
    from pathlib import Path
    sys.path.insert(0, {gates_dir!r})

    from plugins.base import Decision, GateContext, Skip
    from plugins import post_dev_receipt as plugin_mod

    ctx_kwargs = {{
        "trigger": {trigger!r},
        "requirement_id": {req_id!r},
        "extra": {{"req_dir": {req_dir!r}, "target_phase": {target_phase!r}}},
    }}
    if {trigger!r} == "phase-transition":
        ctx_kwargs["from_phase"] = "development"
        ctx_kwargs["to_phase"] = {target_phase!r}

    ctx = GateContext(**ctx_kwargs)
    gate = plugin_mod.PostDevReceiptGate()
    skip = gate.precheck(ctx)
    if skip is not None:
        print("SKIP", skip.reason, file=sys.stderr)
        sys.exit(3)
    report = gate.run(ctx)
    print("DECISION", report.decision.value, "MESSAGE", (report.message or ""), file=sys.stderr)
    if report.decision == Decision.FAIL:
        sys.exit(1)
    sys.exit(0)
""")


def _invoke_plugin(req_dir: Path, trigger: str, target_phase: str = "testing") -> subprocess.CompletedProcess:
    """以子进程跑 PostDevReceiptGate；返回 CompletedProcess（含 returncode + stderr）。

    feature_id / req_id 通过 stderr 文本可断言；exit code 映射 Decision。
    """
    script = _PLUGIN_RUNNER_TMPL.format(
        gates_dir=str(_GATES_DIR),
        trigger=trigger,
        req_id="REQ-2099-SANDBOX",  # ctx.requirement_id 仅日志用，不参与文件路径解析
        req_dir=str(req_dir),
        target_phase=target_phase,
    )
    return run_with_timeout(
        ["python3", "-c", script],
        timeout=30,
    )


# ---------- V-02 主线 ----------


def test_v02_phase_transition_missing_receipt_fails(tmp_path: Path) -> None:
    """V-02：features.json 含 F-001 done 但 receipt.json 缺失 → plugin Decision.FAIL（exit 1）。

    覆盖 detail-design.md §5.4 TC-F1-2 case1（受 fail-fast 影响下 runner 层 exit 1）。
    """
    req_dir = tmp_path / "REQ-2099-010"
    _write_features_json(req_dir, "REQ-2099-010", ["F-001"])
    _write_task_md(req_dir / "artifacts" / "tasks", "F-001", status="done")
    # 故意不写 receipt.json

    proc = _invoke_plugin(req_dir, trigger="phase-transition")
    assert proc.returncode == 1, (
        f"V-02 期望 Decision.FAIL（exit 1），实际 returncode={proc.returncode}；"
        f"stderr={proc.stderr!r}"
    )
    assert "F-001" in proc.stderr, (
        f"stderr 应含 feature_id F-001：{proc.stderr!r}"
    )


def test_v02_phase_transition_with_valid_receipts_passes(tmp_path: Path) -> None:
    """反向 case：所有 done feature 都有合法 receipt.json → plugin Decision.PASS（exit 0）。"""
    req_dir = tmp_path / "REQ-2099-011"
    _write_features_json(req_dir, "REQ-2099-011", ["F-001", "F-002"])
    tasks_dir = req_dir / "artifacts" / "tasks"
    _write_task_md(tasks_dir, "F-001", status="done")
    _write_task_md(tasks_dir, "F-002", status="done")
    _write_receipt(tasks_dir, "F-001", status="DONE")
    _write_receipt(tasks_dir, "F-002", status="DONE_WITH_CONCERNS")

    proc = _invoke_plugin(req_dir, trigger="phase-transition")
    assert proc.returncode == 0, (
        f"合法 receipt 齐全应 PASS（exit 0），实际 returncode={proc.returncode}；"
        f"stderr={proc.stderr!r}"
    )


def test_v02_phase_transition_blocked_status_fails(tmp_path: Path) -> None:
    """补充：receipt.status=BLOCKED → plugin Decision.FAIL（detail-design TC-F1-2 case2）。"""
    req_dir = tmp_path / "REQ-2099-013"
    _write_features_json(req_dir, "REQ-2099-013", ["F-001"])
    tasks_dir = req_dir / "artifacts" / "tasks"
    _write_task_md(tasks_dir, "F-001", status="done")
    # 写 status=BLOCKED + block_reason 非空（schema 要求）
    blocked_data = {
        "schema_version": "1.0",
        "feature_id": "F-001",
        "status": "BLOCKED",
        "commit_sha": "HEAD",
        "files_changed": [],
        "test_summary": "sandbox 测试",
        "touches_violations": [],
        "concerns": [],
        "missing_context": "",
        "block_reason": "外部服务不可用",
        "timestamp": "2026-05-06T10:00:00+08:00",
    }
    (tasks_dir / "F-001.receipt.json").write_text(
        json.dumps(blocked_data, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    proc = _invoke_plugin(req_dir, trigger="phase-transition")
    assert proc.returncode == 1, (
        f"BLOCKED status 应 FAIL（exit 1），实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


# ---------- V-02 skip 路径 ----------


def test_v02_phase_transition_no_features_json_skips(tmp_path: Path) -> None:
    """skip case：features.json 不存在（早期 REQ 未到 task-planning）→ precheck Skip（exit 3）。

    覆盖 detail-design.md §5.3 plugin precheck 第 3 层。
    """
    req_dir = tmp_path / "REQ-2099-012"
    (req_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    # 故意不写 features.json

    proc = _invoke_plugin(req_dir, trigger="phase-transition")
    assert proc.returncode == 3, (
        f"features.json 缺失应 Skip（exit 3），实际 {proc.returncode}；stderr={proc.stderr!r}"
    )
    assert "features.json" in proc.stderr.lower() or "feature" in proc.stderr.lower()


def test_v02_phase_transition_non_testing_target_skips(tmp_path: Path) -> None:
    """skip case：phase-transition 但 target_phase != testing → precheck Skip。

    覆盖 detail-design.md §5.3 plugin precheck 第 4 层（仅 development → testing 命中）。
    """
    req_dir = tmp_path / "REQ-2099-014"
    _write_features_json(req_dir, "REQ-2099-014", ["F-001"])
    _write_task_md(req_dir / "artifacts" / "tasks", "F-001", status="done")

    # target_phase=definition（非 testing）
    proc = _invoke_plugin(req_dir, trigger="phase-transition", target_phase="definition")
    assert proc.returncode == 3, (
        f"target_phase=definition 应 Skip（exit 3），实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


def test_v02_ci_trigger_skips(tmp_path: Path) -> None:
    """skip case：trigger=ci → precheck Skip（V-07 三重保证第 1 层）。

    覆盖 detail-design.md §5.2 trigger 自然过滤；防止 historic REQ 在 ci 通道被本 gate 误 fail。
    """
    req_dir = tmp_path / "REQ-2099-015"
    _write_features_json(req_dir, "REQ-2099-015", ["F-001"])
    _write_task_md(req_dir / "artifacts" / "tasks", "F-001", status="done")

    proc = _invoke_plugin(req_dir, trigger="ci", target_phase="testing")
    assert proc.returncode == 3, (
        f"trigger=ci 应 Skip（exit 3），实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


# ---------- V-02 多 feature 混合：部分缺 receipt ----------


def test_v02_multiple_features_one_missing_receipt_fails(tmp_path: Path) -> None:
    """given_two_done_features_one_missing_receipt_when_run_then_fail。

    覆盖 detail-design.md §5.4 多 feature 校验路径——只要一个 done feature 缺 receipt 即 FAIL。
    """
    req_dir = tmp_path / "REQ-2099-016"
    _write_features_json(req_dir, "REQ-2099-016", ["F-001", "F-002"])
    tasks_dir = req_dir / "artifacts" / "tasks"

    # F-001 done + receipt 齐全
    _write_task_md(tasks_dir, "F-001", status="done")
    _write_receipt(tasks_dir, "F-001", status="DONE")
    # F-002 done 但 receipt 缺失
    _write_task_md(tasks_dir, "F-002", status="done")

    proc = _invoke_plugin(req_dir, trigger="phase-transition")
    assert proc.returncode == 1, (
        f"任一 done feature 缺 receipt 应 FAIL（exit 1），实际 {proc.returncode}；"
        f"stderr={proc.stderr!r}"
    )
    assert "F-002" in proc.stderr, f"stderr 应含缺 receipt 的 F-002：{proc.stderr!r}"
