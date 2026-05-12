"""touches_guard.py 过程产物白名单回归测试（hotfix REQ-2026-008 + REQ-2026-010）。

覆盖 8 类豁免路径 + 3 类反例（白名单不过宽）+ 1 类测试隔离回归：

  TL-WL-001  <req_dir>/artifacts/tasks/<fid>.md                       → 不记 violation
  TL-WL-002  <req_dir>/plan.md                                        → 不记 violation
  TL-WL-003  <req_dir>/notes.md                                       → 不记 violation
  TL-WL-004  <req_dir>/meta.yaml                                      → 不记 violation
  TL-WL-005  <req_dir>/process.txt                                    → 不记 violation
  TL-WL-006  <other_req_dir>/plan.md（其他需求） → 应记 violation（白名单不跨需求）
  TL-WL-007  tests/foo/bar.py（不在 touches 也不在白名单）  → 应记 violation
  TL-WL-008  <req_dir>/artifacts/review-YYYYMMDD-HHMMSS.md  → 不记 violation（hotfix REQ-2026-010）
  TL-WL-009  <other_req_dir>/artifacts/review-*.md（其他需求） → 应记 violation（白名单不跨需求）
  TL-WL-010  <req_dir>/artifacts/notes.md（非 review- 前缀） → 应记 violation（不过宽）
  TL-WL-011  <req_dir>/.dispatch-state.json                  → 不记 violation（hotfix REQ-2026-010 follow-up）
  TL-WL-012  <other_req_dir>/.dispatch-state.json（其他需求） → 应记 violation（白名单不跨需求）
  TL-ISO-001 OVERRIDE 指向 sandbox 时，写入路径不会落到 sandbox 外的真实 receipt.json

背景：
  hotfix 前，主 Agent SOP 必经的写入（task.md status 翻转 / plan.md ADR 落地 /
  notes.md 笔记 / meta.yaml signoff 字段 / process.txt progress logger）会被
  touches_guard 记为软违规，进而硬挡 GATE-TOUCHES-VIOLATION。
  REQ-2026-010 hotfix 补 code-review-report 嵌入模式审查报告 review-*.md 豁免。
  REQ-2026-010 follow-up 再补 .dispatch-state.json lock 自身豁免——dispatch
  acquire / release / cleanup 写入本应是流程必经，不该污染当时 current_feature
  的 receipt.json（典型场景：F-009 done 之后 lock 未释放，后续任意 Edit 都被
  误记到 F-009.receipt.json，触发 GATE-TOUCHES-VIOLATION 硬挡 phase-transition）。
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


def _build_dispatch_state(req_dir: Path, feature_id: str) -> Path:
    state = {
        "schema_version": "1.0",
        "current_feature": feature_id,
        "features": {feature_id: {"status": "in-progress"}},
    }
    state_file = req_dir / ".dispatch-state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    return state_file


def _build_task_md(req_dir: Path, feature_id: str, touches: list[str]) -> Path:
    """frontmatter.touches 列出 touches；写入 <req_dir>/artifacts/tasks/<fid>.md。"""
    tasks_dir = req_dir / "artifacts" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---", "schema_version: '1.0'", f"feature_id: {feature_id}", "touches:"]
    for t in touches:
        lines.append(f"  - {t}")
    lines += ["---", ""]
    task_md = tasks_dir / f"{feature_id}.md"
    task_md.write_text("\n".join(lines), encoding="utf-8")
    return task_md


def _make_req(tmp_path: Path, req_id: str, feature_id: str,
              touches: list[str]) -> Path:
    req_dir = tmp_path / "requirements" / req_id
    req_dir.mkdir(parents=True, exist_ok=True)
    _build_dispatch_state(req_dir, feature_id)
    _build_task_md(req_dir, feature_id, touches)
    return req_dir


def _run(tg, req_dir: Path, file_path: str) -> dict:
    """通过 OVERRIDE 注入 req_dir，跑 _main_inner，返回 receipt.json dict。"""
    payload = json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": file_path}}
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

    # 通过 dispatch_state.json 读 feature_id
    state = json.loads((req_dir / ".dispatch-state.json").read_text("utf-8"))
    fid = state["current_feature"]
    receipt_path = req_dir / "artifacts" / "tasks" / f"{fid}.receipt.json"
    if not receipt_path.exists():
        return {}
    return json.loads(receipt_path.read_text(encoding="utf-8"))


# ---------- TL-WL-001 ~ TL-WL-005：5 类 req-level 过程产物（receipt.json 自指见 test_touches_guard_self_referential.py） ----------


@pytest.mark.parametrize(
    "case_id,relpath",
    [
        ("TL-WL-001", "artifacts/tasks/{fid}.md"),
        ("TL-WL-002", "plan.md"),
        ("TL-WL-003", "notes.md"),
        ("TL-WL-004", "meta.yaml"),
        ("TL-WL-005", "process.txt"),
    ],
)
def test_whitelist_process_artifact_not_recorded(
    tg, tmp_path: Path, case_id: str, relpath: str
) -> None:
    """6 类过程产物豁免；命中即不应写 violation。"""
    feature_id = "F-WL"
    req_dir = _make_req(tmp_path, "REQ-2099-001", feature_id,
                        touches=["src/something.py"])
    file_path = str(req_dir / relpath.format(fid=feature_id))

    data = _run(tg, req_dir, file_path)

    violations = data.get("touches_violations", [])
    assert violations == [], (
        f"{case_id}: 过程产物白名单应豁免 {file_path}，实际 violations={violations}"
    )


# ---------- TL-WL-006：跨需求同名文件不豁免 ----------


def test_TL_WL_006_cross_req_plan_md_still_recorded(tg, tmp_path: Path) -> None:
    """白名单仅作用于当前 req_dir；其他需求的 plan.md 仍然记 violation。"""
    feature_id = "F-WL6"
    req_dir = _make_req(tmp_path, "REQ-2099-001", feature_id,
                        touches=["src/something.py"])

    # 另建一个无关需求目录，写其 plan.md 应被记为越界
    other_req = tmp_path / "requirements" / "REQ-2099-OTHER"
    other_req.mkdir(parents=True, exist_ok=True)
    other_plan = str(other_req / "plan.md")

    data = _run(tg, req_dir, other_plan)

    violations = data.get("touches_violations", [])
    paths = [v.get("path") for v in violations]
    assert other_plan in paths, (
        f"TL-WL-006: 跨需求 plan.md 应被记为 violation（白名单不跨需求），"
        f"实际 paths={paths}"
    )


# ---------- TL-WL-007：完全无关路径仍正常记录（白名单不过宽） ----------


def test_TL_WL_007_unrelated_path_still_recorded(tg, tmp_path: Path) -> None:
    """白名单只覆盖 6 类过程产物；其他越界路径正常记录（防过宽）。"""
    feature_id = "F-WL7"
    req_dir = _make_req(tmp_path, "REQ-2099-001", feature_id,
                        touches=["src/something.py"])

    out_of_scope = "/tmp/touches_guard_unrelated_xyz.py"
    data = _run(tg, req_dir, out_of_scope)

    violations = data.get("touches_violations", [])
    paths = [v.get("path") for v in violations]
    assert out_of_scope in paths, (
        f"TL-WL-007: 与白名单无关的越界路径应记 violation，实际 paths={paths}"
    )


# ---------- TL-WL-008：当前 req_dir 的 artifacts/review-*.md 豁免 ----------


def test_TL_WL_008_review_report_under_artifacts_not_recorded(
    tg, tmp_path: Path
) -> None:
    """code-review-report 嵌入模式产物 artifacts/review-YYYYMMDD-HHMMSS.md 豁免。

    背景（REQ-2026-010 hotfix 触发）：F-002 rev2 review 写盘时 current_feature=F-002
    导致 review-20260511-155100.md 被记入 F-002.receipt.json 的 touches_violations[]，
    后续 phase-transition / submit 被 GATE-TOUCHES-VIOLATION 硬挡。
    """
    feature_id = "F-WL8"
    req_dir = _make_req(tmp_path, "REQ-2099-001", feature_id,
                        touches=["src/something.py"])
    review_path = str(req_dir / "artifacts" / "review-20260511-155100.md")

    data = _run(tg, req_dir, review_path)

    violations = data.get("touches_violations", [])
    assert violations == [], (
        f"TL-WL-008: artifacts/review-*.md 应豁免，实际 violations={violations}"
    )


# ---------- TL-WL-009：跨需求 review-*.md 不豁免（白名单不过宽） ----------


def test_TL_WL_009_cross_req_review_md_still_recorded(tg, tmp_path: Path) -> None:
    """白名单仅作用于当前 req_dir；其他需求 artifacts/review-*.md 仍记 violation。"""
    feature_id = "F-WL9"
    req_dir = _make_req(tmp_path, "REQ-2099-001", feature_id,
                        touches=["src/something.py"])

    other_req = tmp_path / "requirements" / "REQ-2099-OTHER"
    other_artifacts = other_req / "artifacts"
    other_artifacts.mkdir(parents=True, exist_ok=True)
    other_review = str(other_artifacts / "review-20260511-100000.md")

    data = _run(tg, req_dir, other_review)

    violations = data.get("touches_violations", [])
    paths = [v.get("path") for v in violations]
    assert other_review in paths, (
        f"TL-WL-009: 跨需求 review-*.md 应记 violation（白名单不跨需求），"
        f"实际 paths={paths}"
    )


# ---------- TL-WL-010：artifacts 下非 review- 前缀的 .md 不豁免（防过宽） ----------


def test_TL_WL_010_artifacts_non_review_md_still_recorded(
    tg, tmp_path: Path
) -> None:
    """pattern 仅匹配 review-*.md；artifacts/ 下其他 .md（如 notes.md）应记 violation。

    防止过宽：避免 artifacts/ 整体被 SOP 化误豁免。
    """
    feature_id = "F-WL10"
    req_dir = _make_req(tmp_path, "REQ-2099-001", feature_id,
                        touches=["src/something.py"])

    artifacts_dir = req_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    non_review_md = str(artifacts_dir / "design-draft.md")

    data = _run(tg, req_dir, non_review_md)

    violations = data.get("touches_violations", [])
    paths = [v.get("path") for v in violations]
    assert non_review_md in paths, (
        f"TL-WL-010: artifacts/ 下非 review-*.md 应记 violation（防过宽），"
        f"实际 paths={paths}"
    )


# ---------- TL-WL-011：当前 req_dir 的 .dispatch-state.json 豁免 ----------


def test_TL_WL_011_dispatch_state_json_not_recorded(tg, tmp_path: Path) -> None:
    """dispatch lock 自身的 acquire / release / cleanup 写入豁免。

    背景（REQ-2026-010 follow-up 触发）：F-009 done 之后 dispatch_state_cleanup
    没被自动调用，current_feature 一直停在 F-009；后续主 Agent 任何 Edit 都被
    touches_guard 记到 F-009.receipt.json，导致 4 条 violation 污染（dispatch
    lock 写入触发自身的 violation 也是同款）。修复：把 .dispatch-state.json 加入
    白名单，写它本身不再触发 violation。
    """
    feature_id = "F-WL11"
    req_dir = _make_req(tmp_path, "REQ-2099-001", feature_id,
                        touches=["src/something.py"])
    dispatch_state_path = str(req_dir / ".dispatch-state.json")

    data = _run(tg, req_dir, dispatch_state_path)

    violations = data.get("touches_violations", [])
    assert violations == [], (
        f"TL-WL-011: .dispatch-state.json 应豁免，实际 violations={violations}"
    )


# ---------- TL-WL-012：跨需求 .dispatch-state.json 不豁免（白名单不过宽） ----------


def test_TL_WL_012_cross_req_dispatch_state_still_recorded(
    tg, tmp_path: Path
) -> None:
    """白名单仅作用于当前 req_dir；其他需求的 .dispatch-state.json 仍记 violation。"""
    feature_id = "F-WL12"
    req_dir = _make_req(tmp_path, "REQ-2099-001", feature_id,
                        touches=["src/something.py"])

    other_req = tmp_path / "requirements" / "REQ-2099-OTHER"
    other_req.mkdir(parents=True, exist_ok=True)
    other_dispatch = str(other_req / ".dispatch-state.json")

    data = _run(tg, req_dir, other_dispatch)

    violations = data.get("touches_violations", [])
    paths = [v.get("path") for v in violations]
    assert other_dispatch in paths, (
        f"TL-WL-012: 跨需求 .dispatch-state.json 应记 violation（白名单不跨需求），"
        f"实际 paths={paths}"
    )


# ---------- TL-ISO-001：测试隔离回归（OVERRIDE 生效时不污染外部 receipt） ----------


def test_TL_ISO_001_override_isolates_writes_to_sandbox(
    tg, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """设 CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE → 写入仅落 sandbox。

    回归 F-007 真实事故：bats test_pre_tool_use_guard 没有设 OVERRIDE，
    touches_guard._locate_req_dir 通过 _REPO_ROOT 真分支匹配真 meta.yaml，
    a.txt / src/foo.py 等测试 fixture 路径写到了真 F-007.receipt.json。

    本测试通过显式 OVERRIDE 验证隔离生效：写入仅落 sandbox，sandbox 外的
    任何 receipt.json 都不会被改动。
    """
    feature_id = "F-ISO"
    req_dir = _make_req(tmp_path, "REQ-2099-ISO", feature_id,
                        touches=["only/this/path.py"])

    # 模拟一个 sandbox 外"真实"位置（不应被写）
    outside = tmp_path / "outside" / "fake_real_repo"
    outside.mkdir(parents=True, exist_ok=True)

    file_path = "totally/unrelated/file.py"  # 越界 → 必然记 violation
    data = _run(tg, req_dir, file_path)

    # sandbox 内 receipt.json 存在并含 1 条 violation
    violations = data.get("touches_violations", [])
    assert any(v.get("path") == file_path for v in violations), (
        f"TL-ISO-001: sandbox 内 receipt 应记 violation，实际 violations={violations}"
    )

    # sandbox 外 outside 目录 / _REPO_ROOT 下应未被写入
    for stray in outside.rglob("*"):
        assert not stray.is_file(), (
            f"TL-ISO-001: sandbox 外 outside 不应有任何文件被创建，发现 {stray}"
        )
