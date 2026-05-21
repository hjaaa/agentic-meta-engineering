"""tests for workflow_rollback_topology._find_workflow_yaml jsonl fallback（次生 bug）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import workflow_rollback_topology as wrt  # noqa: E402


def test_jsonl_fallback_finds_standard_8phase(tmp_path: Path, monkeypatch):
    """run_dir 内无 workflow.yaml，但 jsonl 含 workflow_started → 查 .claude/workflows/**/<name>.yaml"""
    run_dir = tmp_path / "REQ-2099-RB"
    run_dir.mkdir()
    jsonl = run_dir / "run-state.jsonl"
    jsonl.write_text(
        json.dumps({
            "type": "workflow_started",
            "data": {"workflow_name": "standard-8phase"},
        }) + "\n",
        encoding="utf-8",
    )
    # 实际仓库 .claude/workflows/requirement/standard-8phase.yaml 存在
    monkeypatch.setattr(wrt, "REPO_ROOT", REPO_ROOT)
    result = wrt._find_workflow_yaml(run_dir)
    assert result.name == "standard-8phase.yaml"
    assert ".claude/workflows" in str(result)


def test_jsonl_fallback_no_jsonl(tmp_path: Path, monkeypatch):
    """无 jsonl → 抛 TargetNodeNotFoundError"""
    from workflow_rollback import TargetNodeNotFoundError

    run_dir = tmp_path / "REQ-2099-RB"
    run_dir.mkdir()
    monkeypatch.setattr(wrt, "REPO_ROOT", tmp_path)  # 空仓库根
    with pytest.raises(TargetNodeNotFoundError):
        wrt._find_workflow_yaml(run_dir)


def test_jsonl_fallback_unknown_workflow_name(tmp_path: Path, monkeypatch):
    """jsonl 含 workflow_started 但 workflow_name 不存在于 .claude/workflows/ → 抛"""
    from workflow_rollback import TargetNodeNotFoundError

    run_dir = tmp_path / "REQ-2099-RB"
    run_dir.mkdir()
    jsonl = run_dir / "run-state.jsonl"
    jsonl.write_text(
        json.dumps({
            "type": "workflow_started",
            "data": {"workflow_name": "non-existent-workflow"},
        }) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(wrt, "REPO_ROOT", REPO_ROOT)
    with pytest.raises(TargetNodeNotFoundError):
        wrt._find_workflow_yaml(run_dir)


def test_jsonl_skips_malformed_lines(tmp_path: Path, monkeypatch):
    """jsonl 含非法行 → 跳过继续找 workflow_started"""
    run_dir = tmp_path / "REQ-2099-RB"
    run_dir.mkdir()
    jsonl = run_dir / "run-state.jsonl"
    jsonl.write_text(
        "not a json\n"
        + json.dumps({"type": "some_other"}) + "\n"
        + json.dumps({"type": "workflow_started", "data": {"workflow_name": "standard-8phase"}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(wrt, "REPO_ROOT", REPO_ROOT)
    result = wrt._find_workflow_yaml(run_dir)
    assert result.name == "standard-8phase.yaml"


def test_direct_workflow_yaml_still_works(tmp_path: Path):
    """run_dir/workflow.yaml 存在 → 优先返回（兼容旧行为）"""
    run_dir = tmp_path / "REQ-2099-RB"
    run_dir.mkdir()
    yaml_path = run_dir / "workflow.yaml"
    yaml_path.write_text("nodes: []\n", encoding="utf-8")
    result = wrt._find_workflow_yaml(run_dir)
    assert result == yaml_path
