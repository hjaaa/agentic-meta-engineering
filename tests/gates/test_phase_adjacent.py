"""F-003 · TC-FG3-2：phase 相邻校验单测 + 集成测试。

来源：requirements/REQ-2026-005/artifacts/detailed-design.md §3.2 / §3.3
       requirements/REQ-2026-005/artifacts/features.json TC-FG3-2

覆盖：
  - load_adjacent_phases() 从 enums.phase 推导前进对（单元）
  - load_canonical_phases_ordered() 保留 yaml 顺序（单元）
  - _validate_phase_args 合法相邻前进 → None
  - _validate_phase_args 非法跳跃前进 → 含 R-INVALID-PHASE-TRANSITION 错误消息
  - _validate_phase_args 回退方向 → 不校验（None）
  - main() CLI 端到端：bootstrap→testing dry-run → exit=2 + stderr 含错误码
"""
from __future__ import annotations

import argparse

import pytest

import run as runner_mod

import sys
from pathlib import Path

_REPO_ROOT = Path(runner_mod._REPO_ROOT)
if str(_REPO_ROOT / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))
import phase_enum


# ====================== load_adjacent_phases / load_canonical_phases_ordered ======================


def test_load_adjacent_phases_returns_forward_pairs():
    """given_canonical_list_when_load_adjacent_then_returns_forward_pairs_only。

    canonical = [bootstrap, definition, tech-research, outline-design, detail-design,
                 task-planning, development, testing, completed]
    返回应含 8 对前进相邻；不含回退（如 testing→development）。
    """
    phase_enum.reset_cache()
    pairs = phase_enum.load_adjacent_phases()
    ordered = phase_enum.load_canonical_phases_ordered()
    assert len(pairs) == len(ordered) - 1
    for i in range(len(ordered) - 1):
        assert (ordered[i], ordered[i + 1]) in pairs
    # 反向不应在
    assert ("testing", "development") not in pairs
    assert ("completed", "testing") not in pairs


def test_load_canonical_phases_ordered_preserves_yaml_order():
    """given_yaml_phase_list_when_load_ordered_then_keep_order（不排序）。"""
    phase_enum.reset_cache()
    ordered = phase_enum.load_canonical_phases_ordered()
    assert ordered[0] == "bootstrap"
    # tech-research 应在 outline-design 之前
    assert ordered.index("tech-research") < ordered.index("outline-design")


def test_load_adjacent_phases_cached():
    """重复调用应走缓存，返回同一对象。"""
    phase_enum.reset_cache()
    a = phase_enum.load_adjacent_phases()
    b = phase_enum.load_adjacent_phases()
    assert a is b


# ====================== _validate_phase_args 相邻校验 ======================


def _ns(from_phase: str | None, to_phase: str | None) -> argparse.Namespace:
    """构造 _validate_phase_args 期望的 Namespace。"""
    return argparse.Namespace(from_phase=from_phase, to_phase=to_phase)


def test_validate_phase_args_allows_adjacent_forward():
    """given_adjacent_forward_when_validate_then_none。"""
    assert runner_mod._validate_phase_args(_ns("bootstrap", "definition")) is None
    assert runner_mod._validate_phase_args(_ns("development", "testing")) is None


def test_validate_phase_args_rejects_skip_forward():
    """given_skip_forward_when_validate_then_error_with_R_INVALID_PHASE_TRANSITION。

    bootstrap→testing 跳过中间 6 个阶段；必须返回错误码 R-INVALID-PHASE-TRANSITION。
    """
    err = runner_mod._validate_phase_args(_ns("bootstrap", "testing"))
    assert err is not None
    assert "R-INVALID-PHASE-TRANSITION" in err
    assert "bootstrap" in err
    assert "testing" in err


def test_validate_phase_args_rejects_skip_one_phase():
    """given_skip_single_phase_when_validate_then_error。bootstrap→tech-research 也算非法。"""
    err = runner_mod._validate_phase_args(_ns("bootstrap", "tech-research"))
    assert err is not None
    assert "R-INVALID-PHASE-TRANSITION" in err


def test_validate_phase_args_allows_backward():
    """given_backward_direction_when_validate_then_none（回退场景豁免）。"""
    # testing → development（回退一阶）
    assert runner_mod._validate_phase_args(_ns("testing", "development")) is None
    # completed → bootstrap（极端回退）
    assert runner_mod._validate_phase_args(_ns("completed", "bootstrap")) is None


def test_validate_phase_args_allows_same_phase():
    """同 phase（重跑）也豁免——不算前进方向。"""
    assert runner_mod._validate_phase_args(_ns("development", "development")) is None


def test_validate_phase_args_skips_when_either_empty():
    """ci 模式不传 --from / --to 是合法用法，不校验相邻。"""
    assert runner_mod._validate_phase_args(_ns(None, None)) is None
    assert runner_mod._validate_phase_args(_ns("development", None)) is None
    assert runner_mod._validate_phase_args(_ns(None, "testing")) is None


def test_validate_phase_args_typo_still_caught():
    """typo 拦截优先于相邻校验（保 REQ-2026-003 历史行为）。"""
    err = runner_mod._validate_phase_args(_ns("technical-research", "outline-design"))
    assert err is not None
    assert "canonical phase" in err  # typo 路径错误消息
    assert "R-INVALID-PHASE-TRANSITION" not in err  # 不要走相邻路径


# ====================== main() CLI 端到端 ======================


def test_main_returns_two_for_invalid_phase_jump(capsys):
    """given_bootstrap_to_testing_dry_run_when_main_then_exit_2。

    TC-FG3-2 的核心断言：bootstrap→testing dry-run 应 exit=2 + stderr 含
    R-INVALID-PHASE-TRANSITION。
    """
    rc = runner_mod.main([
        "--trigger=phase-transition",
        "--req=REQ-2099-001",
        "--from=bootstrap",
        "--to=testing",
        "--dry-run",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "R-INVALID-PHASE-TRANSITION" in err
    assert "bootstrap" in err
    assert "testing" in err


def test_main_allows_legal_adjacent_forward_dry_run(capsys):
    """given_development_to_testing_dry_run_when_main_then_exit_0（合法相邻）。"""
    rc = runner_mod.main([
        "--trigger=phase-transition",
        "--req=REQ-2099-001",
        "--from=development",
        "--to=testing",
        "--dry-run",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "R-INVALID-PHASE-TRANSITION" not in err


def test_main_allows_backward_direction_dry_run(capsys):
    """给 testing→development 不报错（回退方向豁免）。"""
    rc = runner_mod.main([
        "--trigger=phase-transition",
        "--req=REQ-2099-001",
        "--from=testing",
        "--to=development",
        "--dry-run",
    ])
    assert rc == 0


# ====================== 缓存隔离（避免污染其他测试） ======================


@pytest.fixture(autouse=True)
def _reset_phase_cache():
    """每个用例前后重置 phase_enum 缓存，避免与 monkeypatch META_SCHEMA_PATH 的测试互染。"""
    phase_enum.reset_cache()
    yield
    phase_enum.reset_cache()
