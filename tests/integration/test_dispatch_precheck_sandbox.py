"""F-008 沙盒 e2e — V-01 / V-04 / V-06 派发链拒绝路径（TC-F8-1）。

验收点：
  - V-01: 派 F-002 但 F-001 status≠done → exit 2 BLOCKED（B-2 depends_on 全 done 校验失败）
  - V-04: 第一次派 F-001 成功（state.current_feature=F-001）；
          并发派 F-002 → exit 2 BLOCKED（B-3 串行 current_feature != null 校验失败）
  - V-06: F-001 status=in-progress 派 F-003 → exit 2 BLOCKED（B-1 status==pending 校验失败）

实现策略：
  - 用 tmp_path 建沙盒 REQ-2099-NNN（features.json + tasks/F-xxx.md）
  - 通过 env CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE 把 hook 的 locate_req_dir_by_branch 重定向到沙盒
  - 用 subprocess + stdin pipe 真实跑 .claude/hooks/dispatch_precheck.py
  - 沙盒 ID 严格 REQ-2099-NNN 纯数字（TC-F8-6 / 全局 memory 提示禁字母后缀）

参考既有范式：tests/hooks/test_dispatch_precheck.bats:38-77 的 _make_sandbox。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _REPO_ROOT / ".claude" / "hooks" / "dispatch_precheck.py"


def _write_features_json(req_dir: Path, req_id: str) -> None:
    """写最小化 features.json：F-001 / F-002 / F-003，F-002 依赖 F-001。"""
    artifacts = req_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": "1.0",
        "requirement_id": req_id,
        "features": [
            {
                "id": "F-001", "title": "a", "description": "d",
                "modules": [], "depends_on": [], "depends_on_features": [],
                "complexity": "trivial", "touches": [], "acceptance": [],
            },
            {
                "id": "F-002", "title": "b", "description": "d",
                "modules": [], "depends_on": [], "depends_on_features": ["F-001"],
                "complexity": "trivial", "touches": [], "acceptance": [],
            },
            {
                "id": "F-003", "title": "c", "description": "d",
                "modules": [], "depends_on": [], "depends_on_features": [],
                "complexity": "trivial", "touches": [], "acceptance": [],
            },
        ],
    }
    (artifacts / "features.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def _write_task_md(tasks_dir: Path, fid: str, status: str, depends_on: list[str]) -> None:
    """写 task.md frontmatter（含 status / depends_on / touches 等必填字段）。"""
    tasks_dir.mkdir(parents=True, exist_ok=True)
    deps_yaml = "[" + ", ".join(depends_on) + "]" if depends_on else "[]"
    content = (
        "---\n"
        "schema_version: \"1.0\"\n"
        f"feature_id: {fid}\n"
        f"title: {fid} 测试 task\n"
        f"status: {status}\n"
        "complexity: trivial\n"
        f"depends_on: {deps_yaml}\n"
        "touches: []\n"
        "created_at: 2026-05-06 10:00:00\n"
        "updated_at: 2026-05-06 10:00:00\n"
        "review_report: null\n"
        "---\n"
    )
    (tasks_dir / f"{fid}.md").write_text(content, encoding="utf-8")


def _build_sandbox(tmp_path: Path, req_id: str, statuses: dict[str, str]) -> Path:
    """构造沙盒 req_dir：features.json + tasks/F-001~F-003.md。

    参数 statuses：{"F-001": "pending", "F-002": "pending", ...}，
    缺省的 fid 走默认 status="pending"。
    """
    assert req_id.startswith("REQ-2099-"), f"沙盒 ID 必须 REQ-2099-NNN 格式：{req_id}"
    req_dir = tmp_path / req_id
    _write_features_json(req_dir, req_id)
    deps_map = {"F-001": [], "F-002": ["F-001"], "F-003": []}
    for fid in ("F-001", "F-002", "F-003"):
        _write_task_md(
            req_dir / "artifacts" / "tasks",
            fid,
            statuses.get(fid, "pending"),
            deps_map[fid],
        )
    return req_dir


def _run_hook(req_dir: Path, feature_id: str, audit_root: Path) -> subprocess.CompletedProcess:
    """以 subprocess 跑 dispatch_precheck.py，stdin 喂 Agent payload。

    用环境变量 CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE 重定向 hook locate；
    audit_root 隔离避免污染真 audit/.queue。
    """
    payload = {
        "tool_name": "Agent",
        "tool_input": {"prompt": f"feature_id: {feature_id}\nbody"},
    }
    env = os.environ.copy()
    env["CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE"] = str(req_dir)
    env["CLAUDE_GATES_AUDIT_ROOT"] = str(audit_root)
    return subprocess.run(
        ["python3", str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
        timeout=10,
    )


def _write_state(req_dir: Path, req_id: str, current_feature: str | None) -> None:
    """写 .dispatch-state.json（B-3 测试需要 current_feature 占用）。"""
    state = {
        "schema_version": "1.0",
        "req_id": req_id,
        "current_feature": current_feature,
    }
    if current_feature is not None:
        state["acquired_at"] = "2026-05-06T10:00:00+08:00"
        state["acquired_by_pid"] = 99999
    (req_dir / ".dispatch-state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8",
    )


# ---------- V-01：B-2 depends_on 未 done ----------


def test_v01_b2_depends_not_done_blocks_dispatch(tmp_path: Path) -> None:
    """V-01：派 F-002 但 F-001 仍 pending → exit 2 BLOCKED + stderr 含 F-001/F-002。

    覆盖 dispatch_precheck.py B-2 校验（depends_on_features 全 done）。
    """
    req_dir = _build_sandbox(
        tmp_path, "REQ-2099-001",
        statuses={"F-001": "pending", "F-002": "pending"},
    )
    audit_root = tmp_path / "audit_root"
    result = _run_hook(req_dir, "F-002", audit_root)

    assert result.returncode == 2, (
        f"V-01 期望 exit 2（BLOCKED），实际 {result.returncode}；"
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "BLOCKED" in result.stderr, f"stderr 应含 BLOCKED：{result.stderr!r}"
    assert "F-002" in result.stderr, f"stderr 应含 feature_id F-002：{result.stderr!r}"
    assert "F-001" in result.stderr, f"stderr 应含依赖项 F-001：{result.stderr!r}"


# ---------- V-04：B-3 串行——current_feature 占用 ----------


def test_v04_b3_concurrent_dispatch_blocked(tmp_path: Path) -> None:
    """V-04：F-001 pending 第一次派成功；并发再派 F-002 → exit 2（B-3 current_feature != null）。

    覆盖 dispatch_precheck.py B-3 校验：state.current_feature is None or == 自身。
    """
    req_id = "REQ-2099-002"
    req_dir = _build_sandbox(
        tmp_path, req_id,
        # 让 F-001 done 让 B-2 通过；测 B-3 单独
        statuses={"F-001": "done", "F-002": "pending"},
    )
    audit_root = tmp_path / "audit_root"
    # 模拟 F-001 已 acquire（concurrent dispatch 场景）
    _write_state(req_dir, req_id, current_feature="F-001")

    result = _run_hook(req_dir, "F-002", audit_root)

    assert result.returncode == 2, (
        f"V-04 期望 exit 2（B-3 current_feature 占用），实际 {result.returncode}；"
        f"stderr={result.stderr!r}"
    )
    assert "BLOCKED" in result.stderr, f"stderr 应含 BLOCKED：{result.stderr!r}"
    # bats 用例 stderr 是 "F-001 派发中"；保留同款匹配
    assert "F-001" in result.stderr, f"stderr 应含被占用 feature F-001：{result.stderr!r}"


def test_v04_same_feature_retry_passes(tmp_path: Path) -> None:
    """V-04 补充：current_feature == 待派 fid → 允许重派（B-3 同名豁免）。

    回归保护：避免 dispatch 重试场景被误拦（与 bats DISPATCH same feature retry 对齐）。
    """
    req_id = "REQ-2099-003"
    req_dir = _build_sandbox(
        tmp_path, req_id,
        statuses={"F-001": "pending"},
    )
    audit_root = tmp_path / "audit_root"
    _write_state(req_dir, req_id, current_feature="F-001")

    result = _run_hook(req_dir, "F-001", audit_root)
    assert result.returncode == 0, (
        f"重派同 feature 不应阻断，期望 exit 0，实际 {result.returncode}；"
        f"stderr={result.stderr!r}"
    )


# ---------- V-06：B-1 status≠pending（in-progress / done 都不可派）----------


def test_v06_b1_status_in_progress_blocks(tmp_path: Path) -> None:
    """V-06：F-003 status=in-progress 派 F-003 → exit 2（B-1 status 必须 pending）。

    覆盖 dispatch_precheck.py B-1 校验：tasks/<fid>.md frontmatter.status==pending。
    """
    req_dir = _build_sandbox(
        tmp_path, "REQ-2099-004",
        statuses={"F-003": "in-progress"},
    )
    audit_root = tmp_path / "audit_root"
    result = _run_hook(req_dir, "F-003", audit_root)

    assert result.returncode == 2, (
        f"V-06 期望 exit 2（B-1 status=in-progress），实际 {result.returncode}；"
        f"stderr={result.stderr!r}"
    )
    assert "BLOCKED" in result.stderr, f"stderr 应含 BLOCKED：{result.stderr!r}"
    assert "F-003" in result.stderr, f"stderr 应含 feature_id F-003：{result.stderr!r}"
    assert "in-progress" in result.stderr, (
        f"stderr 应含 status 实际值 in-progress：{result.stderr!r}"
    )


def test_v06_b1_status_done_blocks_redispatch(tmp_path: Path) -> None:
    """V-06 补充：status=done 也不可重派（语义上"已完成无需再派"）。

    与 bats BLOCKED B-1b 对齐——任何非 pending 的 status 都触发 B-1 拒绝。
    """
    req_dir = _build_sandbox(
        tmp_path, "REQ-2099-005",
        statuses={"F-003": "done"},
    )
    audit_root = tmp_path / "audit_root"
    result = _run_hook(req_dir, "F-003", audit_root)

    assert result.returncode == 2, (
        f"status=done 应拦截重派，期望 exit 2，实际 {result.returncode}；"
        f"stderr={result.stderr!r}"
    )
    assert "BLOCKED" in result.stderr
    assert "done" in result.stderr, f"stderr 应含 status=done：{result.stderr!r}"


# ---------- 成功路径 sanity（确保沙盒搭建正确，不是因构造错误而失败）----------


def test_v04_first_dispatch_succeeds_writes_state(tmp_path: Path) -> None:
    """sanity：F-001 pending + 无 current_feature → 第一次派成功，state 写入 F-001。

    与 bats DISPATCH OK 对齐；防止 V-04 / V-06 阴性测试误判（沙盒建错也会 exit 2）。
    """
    req_id = "REQ-2099-006"
    req_dir = _build_sandbox(
        tmp_path, req_id,
        statuses={"F-001": "pending"},
    )
    audit_root = tmp_path / "audit_root"
    result = _run_hook(req_dir, "F-001", audit_root)

    assert result.returncode == 0, (
        f"成功路径应 exit 0，实际 {result.returncode}；stderr={result.stderr!r}"
    )
    state_path = req_dir / ".dispatch-state.json"
    assert state_path.exists(), "成功 dispatch 后 .dispatch-state.json 应被写入"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state.get("current_feature") == "F-001", (
        f"state.current_feature 应为 F-001，实际：{state}"
    )
