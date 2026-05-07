"""F-008 沙盒 e2e — V-08 自举 + V-07 历史 REQ 路径自然隔离（TC-F8-5）。

验收点（detail-design.md §2 / §5.2 / outline §5）：
  - V-08：本需求 REQ-2026-008 自身 development → testing 切换时
          4 个新增 gate（GATE-POST-DEV-RECEIPT / GATE-TOUCHES-VIOLATION /
          GATE-FEATURES-SCHEMA / GATE-TASK-FRONTMATTER）不应在 audit failed[] 中出现
          （它们要么 PASS，要么因前序 fail 短路而未运行；但绝不能由它们引入失败）
  - V-07：historic completed REQ（如 REQ-2026-001）走 ci 通道 dry-run 时，
          POST-DEV-RECEIPT / TOUCHES-VIOLATION 不在候选 plan（trigger 自然过滤），
          FEATURES-SCHEMA / TASK-FRONTMATTER 在 plan 但 precheck Skip（无 changed_files）

实现策略：
  - 真实 subprocess 调 python3 scripts/gates/run.py（V-08 强约束："必须真实跑"）
  - V-08 用 CLAUDE_GATES_AUDIT_ROOT 隔离 audit log 输出；解析 .queue/<date>.log
  - V-07 用 --dry-run 拿候选 plan 文本；再用真实 ci run 验证 audit 中无 4 gate fail

注意：
  - 不真切阶段：测试只读 run.py 退出码 + audit，不修改 meta.phase
  - 不要假设 exit 0：仓库有未提交改动 + 旧 review 文件 → GATE-WORKSPACE-CLEAN /
    GATE-SOURCING 可能 fail。我们只断言"4 新 gate 不引入 fail"。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from ._subprocess_helpers import run_with_timeout

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUN_PY = _REPO_ROOT / "scripts" / "gates" / "run.py"

# 本需求引入的 4 个新 gate（detail-design §5.1）
_NEW_GATE_IDS = (
    "GATE-POST-DEV-RECEIPT",
    "GATE-TOUCHES-VIOLATION",
    "GATE-FEATURES-SCHEMA",
    "GATE-TASK-FRONTMATTER",
)


def _run(
    args: list[str], audit_root: Path | None = None, env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """统一 subprocess 调 run.py；audit 隔离到 audit_root，避免污染真 audit/.queue。"""
    env = os.environ.copy()
    if audit_root is not None:
        env["CLAUDE_GATES_AUDIT_ROOT"] = str(audit_root)
    if env_extra:
        env.update(env_extra)
    return run_with_timeout(
        ["python3", str(_RUN_PY), *args],
        timeout=120,
        env=env,
        cwd=str(_REPO_ROOT),
    )


def _read_audit_entry(audit_root: Path) -> dict:
    """读 audit/.queue/<date>.log 最末一行的 JSON 部分。"""
    queue_dir = audit_root / "audit" / ".queue"
    log_files = sorted(queue_dir.glob("*.log"))
    assert log_files, f"audit log 缺失：{queue_dir}"
    # 取最后一个文件的最后一行（subprocess 调用可能写入多行；只关注最新）
    last_line = log_files[-1].read_text(encoding="utf-8").strip().split("\n")[-1]
    m = re.search(r"\{.*\}", last_line)
    assert m, f"audit log 行无 JSON 结构：{last_line!r}"
    return json.loads(m.group(0))


def _failed_gate_ids(audit: dict) -> set[str]:
    return {item.get("gate_id") for item in audit.get("failed", [])}


def _passed_gate_ids(audit: dict) -> set[str]:
    return set(audit.get("passed", []))


def _skipped_gate_ids(audit: dict) -> set[str]:
    return {item.get("gate_id") for item in audit.get("skipped", [])}


# ========================== V-08 自举 ==========================


def test_v08_self_bootstrap_no_new_gate_fail(tmp_path: Path) -> None:
    """V-08：本需求 development → testing 切换时，4 个新 gate 不能在 failed[] 出现。

    本需求（REQ-2026-008）正是引入这 4 个 gate 的需求，必须能"狗食"自身——
    新 gate 在本需求自身的产物（features.json / task.md / receipt.json）上要么 PASS
    要么因前序 error 短路而未到达，但绝不能被自己引入的 gate 反咬。

    不强制 exit 0：仓库工作区可能 dirty / 旧 review 含 sourcing issue → 不 attribute 到本需求。
    """
    audit_root = tmp_path / "audit_root"
    proc = _run(
        ["--trigger=phase-transition", "--req=REQ-2026-008",
         "--from=development", "--to=testing"],
        audit_root=audit_root,
    )

    # 退出码不应为 2（runner 自身异常或 CLI 入参非法）
    assert proc.returncode != 2, (
        f"runner 不应崩溃（exit 2），实际 returncode={proc.returncode}；"
        f"stderr={proc.stderr!r}"
    )

    audit = _read_audit_entry(audit_root)
    failed = _failed_gate_ids(audit)
    new_gate_failures = {g for g in _NEW_GATE_IDS if g in failed}
    assert not new_gate_failures, (
        f"V-08 自举失败：4 个新 gate 不应 fail，实际 fail={new_gate_failures}；"
        f"完整 audit failed={audit.get('failed')}；stderr={proc.stderr!r}"
    )


def test_v08_self_bootstrap_features_json_passes_schema(tmp_path: Path) -> None:
    """V-08 强化：本需求 features.json 自身必须能过 check_features.py（schema 自洽）。

    用 --legacy=check-features 不可用（不在 LEGACY_TO_PLUGIN）；改为直接调 check_features.py CLI。
    """
    target = _REPO_ROOT / "requirements" / "REQ-2026-008" / "artifacts" / "features.json"
    assert target.exists(), f"REQ-2026-008 features.json 缺失：{target}"

    proc = subprocess.run(
        ["python3", str(_REPO_ROOT / "scripts" / "lib" / "check_features.py"), str(target)],
        capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=30,
    )
    assert proc.returncode == 0, (
        f"REQ-2026-008 features.json 应过 check_features.py，"
        f"实际 returncode={proc.returncode}；stderr={proc.stderr!r}"
    )


def test_v08_self_bootstrap_task_frontmatter_gate_skip_when_no_changed_files(tmp_path: Path) -> None:
    """V-08 强化：phase-transition 不传 GATE_CHANGED_FILES → GATE-TASK-FRONTMATTER 走 precheck Skip。

    这是关键自举保证（detail-design.md §5.2 第 2 层 changed_files 自然过滤）：
    本需求自身的 task.md 在过渡期可能未注入 schema_version（F-007 派发模板新模板未回填
    历史 task.md），但 phase-transition 触发时无 changed_files → precheck Skip → 不 fail。
    """
    audit_root = tmp_path / "audit_root"
    proc = _run(
        ["--trigger=phase-transition", "--req=REQ-2026-008",
         "--from=development", "--to=testing"],
        audit_root=audit_root,
    )
    assert proc.returncode != 2, f"runner 不应崩溃，实际 {proc.returncode}"

    audit = _read_audit_entry(audit_root)
    failed = _failed_gate_ids(audit)
    # 关键断言：GATE-TASK-FRONTMATTER 不出现在 failed[]
    # 它要么 Skip（无 changed_files），要么因前序 fail 短路而未到达——都不算自举失败
    assert "GATE-TASK-FRONTMATTER" not in failed, (
        f"GATE-TASK-FRONTMATTER 不应 fail（无 changed_files 应 Skip）；"
        f"audit failed={audit.get('failed')}"
    )


# ========================== V-07 历史 REQ 路径自然隔离 ==========================


def test_v07_historic_req_ci_no_post_dev_receipt_in_plan(tmp_path: Path) -> None:
    """V-07：historic REQ-2026-001 走 ci dry-run 时，
    GATE-POST-DEV-RECEIPT / GATE-TOUCHES-VIOLATION 不在候选 plan（trigger 自然过滤）。

    这两个 gate 在 registry.yaml 中 triggers={phase-transition, submit}，不含 ci。
    historic completed REQ 在 ci 通道天然命中不到这俩 gate，无需 legacy-bypass tag。
    """
    audit_root = tmp_path / "audit_root"
    proc = _run(
        ["--trigger=ci", "--req=REQ-2026-001", "--dry-run"],
        audit_root=audit_root,
    )
    # dry-run 写入候选 gate 列表到 stdout
    assert proc.returncode == 0, (
        f"dry-run 应 exit 0，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )
    plan_text = proc.stdout
    assert "GATE-POST-DEV-RECEIPT" not in plan_text, (
        f"GATE-POST-DEV-RECEIPT 不应在 ci dry-run plan 中，实际 stdout={plan_text!r}"
    )
    assert "GATE-TOUCHES-VIOLATION" not in plan_text, (
        f"GATE-TOUCHES-VIOLATION 不应在 ci dry-run plan 中，实际 stdout={plan_text!r}"
    )


def test_v07_historic_req_ci_real_run_no_new_gate_fail(tmp_path: Path) -> None:
    """V-07：historic REQ-2026-001 ci 真实跑 → audit 中 4 个新 gate 都不 fail。

    完整链路验证（detail-design.md §5.2 三重保证）：
      - 第 1 层 trigger 过滤：POST-DEV-RECEIPT / TOUCHES-VIOLATION 不在 ci triggers
      - 第 2 层 changed_files 过滤：FEATURES-SCHEMA / TASK-FRONTMATTER 无 changed_files → precheck Skip
    """
    audit_root = tmp_path / "audit_root"
    # 不传 GATE_CHANGED_FILES → 空列表，FEATURES-SCHEMA / TASK-FRONTMATTER precheck Skip
    proc = _run(
        ["--trigger=ci", "--req=REQ-2026-001"],
        audit_root=audit_root,
    )
    # ci trigger 不应被 runner 视为非法（exit 2）
    assert proc.returncode != 2, (
        f"runner 不应崩溃（exit 2），实际 {proc.returncode}；stderr={proc.stderr!r}"
    )

    audit = _read_audit_entry(audit_root)
    failed = _failed_gate_ids(audit)
    new_gate_failures = {g for g in _NEW_GATE_IDS if g in failed}
    assert not new_gate_failures, (
        f"V-07 historic ci 失败：4 个新 gate 不应 fail，"
        f"实际 fail={new_gate_failures}；完整 audit failed={audit.get('failed')}"
    )


def test_v07_historic_req_ci_schema_gates_skipped_when_no_changed_files(tmp_path: Path) -> None:
    """V-07 强化：ci 通道无 changed_files 时，FEATURES-SCHEMA / TASK-FRONTMATTER 走 precheck Skip。

    detail-design.md §5.2 第 2 层：自然过滤——historic features.json 不在 commit diff 中
    （ci 通道里）→ plugin precheck 第 2 层（changed_files 不含 features.json）返回 Skip。
    """
    audit_root = tmp_path / "audit_root"
    proc = _run(
        ["--trigger=ci", "--req=REQ-2026-001"],
        audit_root=audit_root,
        # 不设 GATE_CHANGED_FILES → ctx.changed_files=[]
    )
    assert proc.returncode != 2, f"runner 不应崩溃，实际 {proc.returncode}"

    audit = _read_audit_entry(audit_root)
    skipped = _skipped_gate_ids(audit)
    passed = _passed_gate_ids(audit)
    failed = _failed_gate_ids(audit)

    # FEATURES-SCHEMA / TASK-FRONTMATTER 必须不 fail；它们要么 Skip 要么因前序 fail 未到
    for gate_id in ("GATE-FEATURES-SCHEMA", "GATE-TASK-FRONTMATTER"):
        assert gate_id not in failed, (
            f"{gate_id} 不应 fail（无 changed_files 应 Skip）；"
            f"audit failed={audit.get('failed')}"
        )
        # 若到达 precheck（前序无 error fail），必须 Skip 而非 PASS
        if gate_id in passed:
            pytest.fail(
                f"{gate_id} 不应 PASS（无 changed_files 应 Skip）；audit passed={passed}"
            )
        # 若被 reach 到 plugin，应该 in skipped
        # 若前序 fail 短路，可能 not appear（这也是合法路径）；不强制 in skipped


def test_v07_historic_req_ci_no_legacy_bypass_tag_added(tmp_path: Path) -> None:
    """V-07 守卫红线（D-005 #2 / D-006）：4 个新 gate 在 registry 中**不**带 legacy-bypass tag。

    detail-design §5.2 表格第 3 层保证：未来若有人想给 4 gate 加 legacy-bypass 让 historic
    REQ 跳过——错误的修复方式。本测试通过读 registry.yaml 守卫这条决策。
    """
    import yaml
    registry_path = _REPO_ROOT / "scripts" / "gates" / "registry.yaml"
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    gates_by_id = {g["id"]: g for g in data.get("gates", [])}

    for gate_id in _NEW_GATE_IDS:
        assert gate_id in gates_by_id, f"新 gate {gate_id} 应在 registry 中"
        tags = gates_by_id[gate_id].get("tags") or []
        assert "legacy-bypass" not in tags, (
            f"{gate_id} 不应带 legacy-bypass tag（D-005 #2 红线）；实际 tags={tags}"
        )
