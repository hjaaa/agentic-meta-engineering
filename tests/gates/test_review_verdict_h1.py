"""F-003 H1 · review_verdict 事务化三路径单测。

来源：detailed-design.md §3.1（行 246-273）+ plan.md "F-003 必修清单"。

三条路径覆盖：
  1) drift → 后续 R 全 pass → commit_staged_writes → meta.yaml 落盘 stale=true
  2) drift → 后续 R fail → rollback → meta.yaml 不变（暂存被丢弃）
  3) 仅 R005 单独 fail（其他 R 全 pass）→ 也走 commit 路径（drift 自身是 error，
     但作为本 gate 内部 finding，commit_staged_writes 仍由 runner 调；从语义看
     R005 fail 阻断 phase 切换是 runner 责任，本测试断言 plugin 层 staged_writes
     行为：单独 fail 时 staged_writes 已 append；commit 通道由 runner 决定）

外部依赖（meta.yaml / reviews/*.json）通过 tmp_path + monkeypatch 隔离。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from plugins.base import Decision, GateContext
from plugins import review_verdict as plugin_mod


_REVIEW_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "context/team/engineering-spec/review-schema.yaml"
)


# ====================== 工具函数（与 test_review_verdict_plugin 风格一致） ======================


def _make_req(tmp_path: Path, req_id: str) -> Path:
    req_dir = tmp_path / "requirements" / req_id
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "reviews").mkdir(exist_ok=True)
    return req_dir


def _base_meta(req_id: str, phase: str) -> dict:
    return {
        "id": req_id,
        "title": "test",
        "phase": phase,
        "created_at": "2026-01-01 00:00:00",
        "branch": f"feat/{req_id.lower()}",
        "base_branch": "develop",
        "reviews": {},
    }


def _write_review_json(req_dir: Path, suffix: str, req_id: str, phase: str) -> str:
    review_id = f"REV-{req_id}-{suffix}"
    _reviewer_map = {
        "definition": "requirement-quality-reviewer",
        "outline-design": "outline-design-quality-reviewer",
        "detail-design": "detail-design-quality-reviewer",
    }
    reviewer = _reviewer_map.get(phase, "requirement-quality-reviewer")
    review_data = {
        "schema_version": "1.0",
        "review_id": review_id,
        "requirement_id": req_id,
        "phase": phase,
        "reviewer": reviewer,
        "reviewed_at": "2026-01-01 00:00:00",
        "reviewed_commit": "abc1234",
        "reviewed_artifacts": [],
        "conclusion": "approved",
        "score": 90,
        "dimensions": {
            k: {"score": 90, "issues": []}
            for k in [
                "design_consistency",
                "security",
                "concurrency",
                "complexity",
                "error_handling",
                "auxiliary_spec",
                "performance",
                "history_context",
            ]
        },
        "required_fixes": [],
        "suggestions": [],
        "scope": {"feature_id": None},
        "supersedes": None,
    }
    (req_dir / "reviews" / f"{suffix}.json").write_text(
        json.dumps(review_data), encoding="utf-8"
    )
    return review_id


def _write_meta(req_dir: Path, meta: dict) -> None:
    with (req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True)


def _patch_paths(monkeypatch, tmp_path: Path) -> None:
    """把 check_reviews / save_review / common 的根路径重定向到 tmp_path。

    plugin 内部 _REPO_ROOT 也要 patch，让 commit_staged_writes 写入 tmp_path 下的
    requirements/<req>/meta.yaml，而不是真实仓库。
    """
    import check_reviews as cr_mod
    monkeypatch.setattr(cr_mod, "REQUIREMENTS_DIR", tmp_path / "requirements")
    import common as cm_mod
    monkeypatch.setattr(cm_mod, "REPO_ROOT", tmp_path)
    import save_review as sr_mod
    monkeypatch.setattr(sr_mod, "REQUIREMENTS_DIR", tmp_path / "requirements")
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)


def _setup_drift(tmp_path: Path, monkeypatch) -> tuple[str, Path, dict]:
    """构造 R005 drift 场景：reviewed_artifacts 中记录了一个 hash，但实际文件已变更。

    返回：(req_id, req_dir, meta_dict)
    """
    req_id = "REQ-2099-100"
    req_dir = _make_req(tmp_path, req_id)
    _patch_paths(monkeypatch, tmp_path)

    # 写一个 detail-design.md 作为 reviewed_artifact
    artifacts_dir = req_dir / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    artifact = artifacts_dir / "detailed-design.md"
    artifact.write_text("current content", encoding="utf-8")

    # 假装记录的 hash 是另一个内容的 hash（drift 触发）
    fake_hash = hashlib.sha256(b"original content").hexdigest()

    review_id = _write_review_json(req_dir, "detail-design-001", req_id, "detail-design")
    meta = _base_meta(req_id, "task-planning")
    meta["reviews"] = {
        "detail-design": {
            "latest": review_id,
            "conclusion": "approved",
            "artifact_hashes": {"artifacts/detailed-design.md": fake_hash},
        }
    }
    _write_meta(req_dir, meta)
    return req_id, req_dir, meta


# ====================== 路径 1：drift → 全 pass → commit 落盘 ======================


def test_should_commit_stale_when_drift_then_all_pass(tmp_path, monkeypatch):
    """given_drift_then_all_other_R_pass_when_run_and_commit_then_meta_stale_true。

    模拟 runner 流程：plugin.run → ctx.staged_writes 暂存 → plugin.commit_staged_writes 落盘。
    """
    req_id, req_dir, meta = _setup_drift(tmp_path, monkeypatch)

    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id=req_id,
        to_phase="task-planning",
        meta=meta,
    )
    report = gate.run(ctx)

    # plugin run 自身：R005 drift → FAIL（这里测的是事务化通道，不是阻断语义）
    assert report.decision == Decision.FAIL
    # staged_writes 应已 append
    assert any(
        path == "meta.yaml" and "stale" in key
        for (path, key, _v) in ctx.staged_writes
    ), f"staged_writes 未含 stale 暂存项：{ctx.staged_writes}"

    # 模拟 runner 全 pass 路径：调 commit_staged_writes
    gate.commit_staged_writes(ctx)

    # 验证 meta.yaml 已落盘 stale=true
    on_disk = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))
    assert on_disk["reviews"]["detail-design"]["stale"] is True


# ====================== 路径 2：drift → 后续 fail → rollback → meta 不变 ======================


def test_should_not_write_stale_when_drift_then_fail_rolls_back(tmp_path, monkeypatch):
    """given_drift_appended_when_rollback_then_meta_unchanged。

    模拟 runner fail 路径：plugin.run → staged_writes 暂存 → plugin.rollback → meta 不变。
    """
    req_id, req_dir, meta = _setup_drift(tmp_path, monkeypatch)
    meta_path = req_dir / "meta.yaml"
    original_bytes = meta_path.read_bytes()

    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id=req_id,
        to_phase="task-planning",
        meta=meta,
    )
    gate.run(ctx)
    # rollback 路径：runner 调 plugin.rollback，不调 commit_staged_writes
    gate.rollback(ctx)

    # meta.yaml 字节级未变化
    assert meta_path.read_bytes() == original_bytes
    # staged_writes 中关于 meta.yaml 的暂存已被清空
    assert not any(p == "meta.yaml" for (p, _k, _v) in ctx.staged_writes)


# ====================== 路径 3：仅 R005 fail，其他 R 全 pass —— staged_writes 仍 append 但磁盘未提前写 ======================


def test_should_not_partial_write_when_r005_alone_fails(tmp_path, monkeypatch):
    """given_only_r005_fails_when_run_then_no_partial_write_to_disk。

    本路径关键点：plugin.run 阶段 **绝不**直接写盘，无论后续是否 fail。
    runner 决定走 commit 还是 rollback；本测试验证 plugin run 完后磁盘 meta 字节未变。
    """
    req_id, req_dir, meta = _setup_drift(tmp_path, monkeypatch)
    meta_path = req_dir / "meta.yaml"
    original_bytes = meta_path.read_bytes()

    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id=req_id,
        to_phase="task-planning",
        meta=meta,
    )
    gate.run(ctx)

    # 关键：plugin.run 不应直接写盘（事务化的核心约束）
    assert meta_path.read_bytes() == original_bytes
    # staged_writes 已 append
    assert any(p == "meta.yaml" for (p, _k, _v) in ctx.staged_writes)


# ====================== F-027 round-2：retry 幂等约束 ======================


def test_should_not_accumulate_stale_when_retried(tmp_path, monkeypatch):
    """given_drift_rollback_then_rerun_when_run_again_then_staged_writes_size_eq_1。

    F-027 round-2：覆盖 retry 场景——drift→rollback→重新 run 后 staged_writes 应仍是
    每个 stale 暂存项一条，不累积重复。当前实现（rollback 清空 + R005 每次重新计算）
    天然满足，但缺测试约束；本用例固化此幂等行为，避免未来重构悄破坏。
    """
    req_id, req_dir, meta = _setup_drift(tmp_path, monkeypatch)
    gate = plugin_mod.ReviewVerdictGate()

    # 第一次 run：drift 触发，staged_writes 暂存 1 条
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id=req_id,
        to_phase="task-planning",
        meta=meta,
    )
    gate.run(ctx)
    first_count = len([s for s in ctx.staged_writes if s[0] == "meta.yaml"])
    assert first_count == 1, f"首次 run 应只暂存 1 条 stale，实际 {first_count}"

    # 模拟 runner fail 路径：rollback 清空暂存
    gate.rollback(ctx)
    assert len(ctx.staged_writes) == 0, "rollback 后 staged_writes 应空"

    # 第二次 run：重新触发 drift（meta.yaml 未落盘 → drift 仍存在）
    gate.run(ctx)
    second_count = len([s for s in ctx.staged_writes if s[0] == "meta.yaml"])
    assert second_count == 1, (
        f"retry 后 staged_writes 应仍是 1 条（不累积），实际 {second_count}"
    )


# ====================== F-13 carry-over：全 pass 后 .bak 清理 ======================


def test_should_cleanup_bak_when_all_gates_pass(tmp_path):
    """given_snapshot_after_commit_when_cleanup_then_bak_removed（F-13 carry-over）."""
    import run as runner_mod

    backup = tmp_path / "meta.yaml.bak"
    backup.write_text("backup content", encoding="utf-8")
    snapshots = {str(tmp_path / "meta.yaml"): backup}

    runner_mod._cleanup_snapshots(snapshots)
    assert not backup.exists(), ".bak 应被清理"


def test_should_warn_when_cleanup_fails(tmp_path, capsys, monkeypatch):
    """given_unlink_raises_when_cleanup_then_warning_not_silenced。"""
    import run as runner_mod

    backup = tmp_path / "meta.yaml.bak"
    backup.write_text("backup content", encoding="utf-8")
    snapshots = {str(tmp_path / "meta.yaml"): backup}

    def _boom(*args, **kwargs):
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(Path, "unlink", _boom)

    runner_mod._cleanup_snapshots(snapshots)
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "gate-cleanup-snapshot" in captured.err
