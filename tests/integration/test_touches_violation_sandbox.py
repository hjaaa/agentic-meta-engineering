"""F-008 沙盒 e2e — V-03：touches 越界双层拦截（TC-F8-3）。

验收点（detail-design.md §5.2 V-03 + outline §3.4 + §3.5）：
  - 软层：触发 touches_guard.py（PreToolUse Edit/Write/MultiEdit）→
    file_path 不在 task.touches glob 内 → append 到 receipt.touches_violations[]，hook exit 0
  - 硬层：phase-transition development → testing 触发 GATE-TOUCHES-VIOLATION →
    扫到任一 receipt.touches_violations[] 非空 → Decision.FAIL（exit 1）

实现策略：
  - tmp_path 沙盒（无需污染真 requirements/）
  - 软层：subprocess 调真 touches_guard.py，stdin 喂 PreToolUse JSON；
         用 CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE 重定向 _locate_req_dir
  - 硬层：subprocess 调一段 inline Python 加载 plugins.touches_violation 并 run，
         避免 GATE-WORKSPACE-CLEAN 因沙盒 untracked 误 fail

参考：tests/hooks/test_touches_guard.bats / tests/gates/test_touches_violation.py。
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path


from ._subprocess_helpers import run_with_timeout

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOUCHES_GUARD = _REPO_ROOT / ".claude" / "hooks" / "touches_guard.py"
_GATES_DIR = _REPO_ROOT / "scripts" / "gates"


def _write_features_json(req_dir: Path, req_id: str, feature_ids: list[str]) -> None:
    """写最小化 features.json（feature_required_fields 全齐）。"""
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


def _write_task_md_with_touches(
    tasks_dir: Path, fid: str, status: str, touches: list[str],
) -> None:
    """写 task.md frontmatter，touches 字段使用 YAML 列表。"""
    tasks_dir.mkdir(parents=True, exist_ok=True)
    touches_yaml = json.dumps(touches, ensure_ascii=False)  # JSON 子集兼容 YAML 列表
    content = (
        "---\n"
        "schema_version: \"1.0\"\n"
        f"feature_id: {fid}\n"
        f"title: {fid} 沙盒 task\n"
        f"status: {status}\n"
        "complexity: trivial\n"
        "depends_on: []\n"
        f"touches: {touches_yaml}\n"
        "created_at: 2026-05-06 10:00:00\n"
        "updated_at: 2026-05-06 10:00:00\n"
        "review_report: null\n"
        "---\n"
    )
    (tasks_dir / f"{fid}.md").write_text(content, encoding="utf-8")


def _write_dispatch_state(req_dir: Path, req_id: str, current_feature: str) -> None:
    """写 .dispatch-state.json，让 touches_guard 知道"当前派发的 feature"。"""
    state = {
        "schema_version": "1.0",
        "req_id": req_id,
        "current_feature": current_feature,
        "acquired_at": "2026-05-06T10:00:00+08:00",
        "acquired_by_pid": 99999,
    }
    (req_dir / ".dispatch-state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8",
    )


def _write_receipt_skeleton(tasks_dir: Path, fid: str, violations: list[dict]) -> None:
    """写带 touches_violations[] 的 receipt.json（用于硬层测试预置违规数据）。"""
    data = {
        "schema_version": "1.0",
        "feature_id": fid,
        "status": "DONE",
        "commit_sha": "HEAD",
        "files_changed": [],
        "test_summary": "sandbox 测试",
        "touches_violations": violations,
        "concerns": [],
        "missing_context": "",
        "block_reason": "",
        "timestamp": "2026-05-06T10:00:00+08:00",
    }
    (tasks_dir / f"{fid}.receipt.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def _run_touches_guard(
    req_dir: Path, file_path: str, tool_name: str = "Edit",
) -> subprocess.CompletedProcess:
    """以 subprocess 跑 touches_guard.py，stdin 喂 PreToolUse JSON。

    用 CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE 重定向 hook _locate_req_dir。
    始终 exit 0（fail-open 哲学）；副作用通过 receipt.json 验证。
    """
    payload = {
        "tool_name": tool_name,
        "tool_input": {"file_path": file_path, "old_string": "x", "new_string": "y"},
    }
    env = os.environ.copy()
    env["CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE"] = str(req_dir)
    return run_with_timeout(
        ["python3", str(_TOUCHES_GUARD)],
        timeout=10,
        input=json.dumps(payload),
        env=env,
    )


# 硬层 plugin 子进程模板：构造 GateContext，调 TouchesViolationGate.run，按 Decision 退出。
_HARD_GATE_TMPL = textwrap.dedent("""\
    import sys
    sys.path.insert(0, {gates_dir!r})
    from plugins.base import Decision, GateContext, Skip
    from plugins import touches_violation as plugin_mod

    ctx = GateContext(
        trigger="phase-transition",
        requirement_id={req_id!r},
        from_phase="development", to_phase="testing",
        extra={{"req_dir": {req_dir!r}, "target_phase": "testing"}},
    )
    gate = plugin_mod.TouchesViolationGate()
    skip = gate.precheck(ctx)
    if skip is not None:
        print("SKIP", skip.reason, file=sys.stderr)
        sys.exit(3)
    report = gate.run(ctx)
    print("DECISION", report.decision.value, "MESSAGE", (report.message or ""), file=sys.stderr)
    sys.exit(1 if report.decision == Decision.FAIL else 0)
""")


def _run_hard_gate(req_dir: Path, req_id: str) -> subprocess.CompletedProcess:
    """以子进程跑 GATE-TOUCHES-VIOLATION plugin，返回 exit 1=FAIL / 0=PASS / 3=SKIP。"""
    script = _HARD_GATE_TMPL.format(
        gates_dir=str(_GATES_DIR), req_id=req_id, req_dir=str(req_dir),
    )
    return run_with_timeout(
        ["python3", "-c", script],
        timeout=30,
    )


# ---------- V-03 软层：touches_guard.py 越界写 violations，放行 exit 0 ----------


def test_v03_soft_layer_out_of_bounds_records_violation(tmp_path: Path) -> None:
    """V-03 软层：派 F-001（touches=src/auth/**）改 .claude/hooks/x.py（不在 touches 内）
    → touches_guard.py 写 violations 到 receipt.json，但放行 exit 0。

    覆盖 outline §3.4：软拦截 = 记录 + 放行（避免开发链死锁）。
    """
    req_id = "REQ-2099-020"
    req_dir = tmp_path / req_id
    _write_features_json(req_dir, req_id, ["F-001"])
    _write_task_md_with_touches(
        req_dir / "artifacts" / "tasks", "F-001",
        status="in-progress", touches=["src/auth/**"],
    )
    _write_dispatch_state(req_dir, req_id, current_feature="F-001")

    # 改 .claude/hooks/dispatch_precheck.py（明显不在 src/auth/** 内）
    proc = _run_touches_guard(req_dir, ".claude/hooks/dispatch_precheck.py")

    assert proc.returncode == 0, (
        f"软拦截必须 fail-open（exit 0），实际 {proc.returncode}；stderr={proc.stderr!r}"
    )
    receipt_path = req_dir / "artifacts" / "tasks" / "F-001.receipt.json"
    assert receipt_path.exists(), (
        f"越界后 touches_guard 应建空骨架 receipt.json：{receipt_path}"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    violations = receipt.get("touches_violations", [])
    assert len(violations) >= 1, (
        f"receipt.touches_violations[] 应非空，实际：{violations}"
    )
    paths = [v.get("path") for v in violations]
    assert ".claude/hooks/dispatch_precheck.py" in paths, (
        f"violation.path 应含越界文件，实际 paths={paths}"
    )


def test_v03_soft_layer_in_bounds_no_violation(tmp_path: Path) -> None:
    """反向：file_path 在 touches glob 内 → 不写 violations。

    回归保护：避免 glob 命中场景被误记。
    """
    req_id = "REQ-2099-021"
    req_dir = tmp_path / req_id
    _write_features_json(req_dir, req_id, ["F-001"])
    _write_task_md_with_touches(
        req_dir / "artifacts" / "tasks", "F-001",
        status="in-progress", touches=["src/auth/**"],
    )
    _write_dispatch_state(req_dir, req_id, current_feature="F-001")

    proc = _run_touches_guard(req_dir, "src/auth/login.py")
    assert proc.returncode == 0, (
        f"hook 始终 exit 0，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )
    receipt_path = req_dir / "artifacts" / "tasks" / "F-001.receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt.get("touches_violations", []) == [], (
            f"in-bounds 文件不应写 violations，实际：{receipt}"
        )


# ---------- V-03 硬层：GATE-TOUCHES-VIOLATION 扫 receipt.violations[] 非空 → FAIL ----------


def test_v03_hard_layer_violation_present_fails_gate(tmp_path: Path) -> None:
    """V-03 硬层：phase-transition 触发 GATE-TOUCHES-VIOLATION，扫到 violations 非空 → FAIL。

    覆盖 outline §3.5：硬拦截 = 阶段切换时把软层记录的越界一次性兜住。
    """
    req_id = "REQ-2099-022"
    req_dir = tmp_path / req_id
    _write_features_json(req_dir, req_id, ["F-001", "F-002"])
    tasks_dir = req_dir / "artifacts" / "tasks"
    _write_task_md_with_touches(tasks_dir, "F-001", status="done", touches=[])
    _write_task_md_with_touches(tasks_dir, "F-002", status="done", touches=[])

    # F-001 receipt 干净
    _write_receipt_skeleton(tasks_dir, "F-001", violations=[])
    # F-002 receipt 含越界记录
    _write_receipt_skeleton(tasks_dir, "F-002", violations=[
        {
            "path": "scripts/out_of_scope.py",
            "ts": "2026-05-06T10:00:00+00:00",
            "tool": "Edit",
        }
    ])

    proc = _run_hard_gate(req_dir, req_id)
    assert proc.returncode == 1, (
        f"V-03 硬层期望 FAIL（exit 1），实际 {proc.returncode}；stderr={proc.stderr!r}"
    )
    assert "F-002" in proc.stderr, f"stderr 应含违规 feature_id F-002：{proc.stderr!r}"


def test_v03_hard_layer_all_clean_passes_gate(tmp_path: Path) -> None:
    """反向：所有 receipt.touches_violations[] 为空 → Decision.PASS。"""
    req_id = "REQ-2099-023"
    req_dir = tmp_path / req_id
    _write_features_json(req_dir, req_id, ["F-001"])
    tasks_dir = req_dir / "artifacts" / "tasks"
    _write_task_md_with_touches(tasks_dir, "F-001", status="done", touches=[])
    _write_receipt_skeleton(tasks_dir, "F-001", violations=[])

    proc = _run_hard_gate(req_dir, req_id)
    assert proc.returncode == 0, (
        f"无 violations 应 PASS（exit 0），实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


# ---------- V-03 软+硬联动：软层写完，硬层兜住 ----------


def test_v03_soft_then_hard_full_chain(tmp_path: Path) -> None:
    """V-03 联动：软层 touches_guard 写 violations，硬层 phase-transition 扫到后 FAIL。

    完整链路验证（detail-design.md §5.2 V-03 双层兜底）。
    """
    req_id = "REQ-2099-024"
    req_dir = tmp_path / req_id
    _write_features_json(req_dir, req_id, ["F-001"])
    tasks_dir = req_dir / "artifacts" / "tasks"
    _write_task_md_with_touches(
        tasks_dir, "F-001",
        status="in-progress",  # 软层用 in-progress（current_feature）
        touches=["src/auth/**"],
    )
    _write_dispatch_state(req_dir, req_id, current_feature="F-001")

    # 1) 软层：越界写 violations
    soft_proc = _run_touches_guard(req_dir, ".claude/hooks/dispatch_precheck.py")
    assert soft_proc.returncode == 0, f"软层应 fail-open：stderr={soft_proc.stderr!r}"

    # 2) 把 task.md 改成 done 模拟开发完成（硬层只扫 done feature 对应 receipt）
    _write_task_md_with_touches(
        tasks_dir, "F-001", status="done", touches=["src/auth/**"],
    )

    # 3) 硬层：phase-transition 扫 receipt.violations 非空 → FAIL
    hard_proc = _run_hard_gate(req_dir, req_id)
    assert hard_proc.returncode == 1, (
        f"软层写完 violations，硬层应 FAIL（exit 1），实际 {hard_proc.returncode}；"
        f"stderr={hard_proc.stderr!r}"
    )


# ---------- V-03 hook fail-open 兜底（无 .dispatch-state.json）----------


def test_v03_soft_layer_no_dispatch_state_fail_open(tmp_path: Path) -> None:
    """边界：.dispatch-state.json 缺失 → hook fail-open 不写 violations，exit 0。

    防御性回归：避免 hook 在 dispatch_state 异常时阻断 Edit 操作。
    """
    req_id = "REQ-2099-025"
    req_dir = tmp_path / req_id
    _write_features_json(req_dir, req_id, ["F-001"])
    _write_task_md_with_touches(
        req_dir / "artifacts" / "tasks", "F-001",
        status="in-progress", touches=["src/auth/**"],
    )
    # 故意不写 .dispatch-state.json

    proc = _run_touches_guard(req_dir, ".claude/hooks/anywhere.py")
    assert proc.returncode == 0, (
        f"无 dispatch_state 时 hook 应 fail-open（exit 0），实际 {proc.returncode}；"
        f"stderr={proc.stderr!r}"
    )
