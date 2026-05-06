"""touches_guard.py 自指白名单回归测试。

覆盖：
  TL-SR-001  file_path == receipt.json 自身 → 不追加 violation（自指豁免）
  TL-SR-002  file_path == 范围外其他文件  → 追加 violation（白名单不过宽）

背景：
  subagent 写 requirements/<id>/artifacts/tasks/<fid>.receipt.json 是 dispatch
  约定的回执产物，不在 task.md frontmatter touches 列表里（自指无意义）。
  修复前 touches_guard 会把写 receipt.json 本身的事件也追加为 violation，
  导致 GATE-TOUCHES-VIOLATION 因 self-referential 软违规硬挡 phase-transition。
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_PATH = _REPO_ROOT / ".claude" / "hooks" / "touches_guard.py"


def _load_touches_guard():
    """从文件路径加载 touches_guard 模块（非 package 路径）。"""
    spec = importlib.util.spec_from_file_location("touches_guard", _HOOK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {_HOOK_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tg():
    """加载 touches_guard 模块。"""
    return _load_touches_guard()


def _build_dispatch_state(tmp_path: Path, feature_id: str) -> Path:
    """在 tmp_path 下建 .dispatch-state.json，current_feature = feature_id。"""
    state = {
        "schema_version": "1.0",
        "current_feature": feature_id,
        "features": {
            feature_id: {"status": "in-progress"},
        },
    }
    state_file = tmp_path / ".dispatch-state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    return state_file


def _build_task_md(req_dir: Path, feature_id: str, touches: list[str]) -> Path:
    """在 req_dir/artifacts/tasks/<fid>.md 写 frontmatter，包含 touches 列表。"""
    tasks_dir = req_dir / "artifacts" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---", "schema_version: '1.0'", f"feature_id: {feature_id}", "touches:"]
    for t in touches:
        lines.append(f"  - {t}")
    lines += ["---", ""]
    task_md = tasks_dir / f"{feature_id}.md"
    task_md.write_text("\n".join(lines), encoding="utf-8")
    return task_md


def _run_main_inner(tg, tmp_path: Path, feature_id: str, file_path: str) -> dict:
    """构造 stdin payload，通过 CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE 注入 req_dir，
    调用 _main_inner，返回解析后的 receipt.json dict（若不存在则返回 {}）。"""
    req_dir = tmp_path / "requirements" / "REQ-2099-001"
    req_dir.mkdir(parents=True, exist_ok=True)

    _build_dispatch_state(req_dir, feature_id)
    # touches 只列一个无关文件，receipt.json 自身不在里面
    _build_task_md(req_dir, feature_id, ["src/something.py"])

    payload = json.dumps(
        {
            "tool_name": "Write",
            "tool_input": {"file_path": file_path},
        }
    )

    old_env = os.environ.get("CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE")
    os.environ["CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE"] = str(req_dir)
    try:
        tg._main_inner(payload)
    finally:
        if old_env is None:
            os.environ.pop("CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE", None)
        else:
            os.environ["CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE"] = old_env

    receipt_path = req_dir / "artifacts" / "tasks" / f"{feature_id}.receipt.json"
    if not receipt_path.exists():
        return {}
    return json.loads(receipt_path.read_text(encoding="utf-8"))


# ---------- TL-SR-001：自指 receipt.json 不记 violation ----------


def test_TL_SR_001_self_write_receipt_not_recorded(tg, tmp_path: Path) -> None:
    """file_path == 该 feature 的 receipt.json 绝对路径 → touches_violations[] 为空。

    修复前：touches_guard 把写 receipt.json 本身的事件追加为 violation。
    修复后：自指路径豁免，不记录为违规。
    """
    feature_id = "F-SR1"
    req_dir = tmp_path / "requirements" / "REQ-2099-001"
    receipt_abs = str(
        req_dir / "artifacts" / "tasks" / f"{feature_id}.receipt.json"
    )

    data = _run_main_inner(tg, tmp_path, feature_id, receipt_abs)

    violations = data.get("touches_violations", [])
    assert violations == [], (
        f"写 receipt.json 自身不应被记为 violation，实际 violations={violations}"
    )


# ---------- TL-SR-002：范围外文件仍正常记录 violation（白名单不过宽） ----------


def test_TL_SR_002_out_of_scope_file_still_recorded(tg, tmp_path: Path) -> None:
    """file_path == 范围外的其他文件 → touches_violations[] 包含该条目。

    确保自指白名单不过宽，不影响对真实越界文件的正常记录。
    """
    feature_id = "F-SR2"
    out_of_scope = "/tmp/unrelated_file.py"

    data = _run_main_inner(tg, tmp_path, feature_id, out_of_scope)

    violations = data.get("touches_violations", [])
    assert len(violations) >= 1, (
        f"超出 touches 范围的文件应被记录为 violation，实际 violations={violations}"
    )
    paths = [v.get("path") for v in violations]
    assert out_of_scope in paths, (
        f"期望 {out_of_scope} 在 violations.path 中，实际 paths={paths}"
    )
