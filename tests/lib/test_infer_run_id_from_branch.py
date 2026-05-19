"""infer_run_id_from_branch 兼容性测试（REQ-2026-014 验收 #7 前置 / Phase 3 提前实施）。

覆盖：
  - 旧 REQ-* 分支（feat/req-2026-014）解析为 canonical REQ-2026-014
  - 新 key 分支（feat/req-20260518-worktree-isolation）直接返回 stripped
  - 非 feat/req-* 分支返回 None
  - 找不到任何目录时退回原行为返回 stripped（让调用方报路径不存在）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT_PATH = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT_PATH / "scripts" / "lib"))

import common  # noqa: E402
from common import infer_run_id_from_branch  # noqa: E402


def _mock_branch(name: str):
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=f"{name}\n", stderr="")
    return patch.object(common.subprocess, "run", return_value=completed)


def test_legacy_req_branch_returns_canonical_uppercase_id(tmp_path):
    (tmp_path / "requirements" / "REQ-2026-014").mkdir(parents=True)
    with _mock_branch("feat/req-2026-014"):
        assert infer_run_id_from_branch(tmp_path) == "REQ-2026-014"


def test_legacy_req_branch_under_runs_dir(tmp_path):
    (tmp_path / "runs" / "REQ-2026-099").mkdir(parents=True)
    with _mock_branch("feat/req-2026-099"):
        assert infer_run_id_from_branch(tmp_path) == "REQ-2026-099"


def test_new_key_branch_returns_stripped(tmp_path):
    (tmp_path / "requirements" / "20260518-worktree-isolation").mkdir(parents=True)
    with _mock_branch("feat/req-20260518-worktree-isolation"):
        assert infer_run_id_from_branch(tmp_path) == "20260518-worktree-isolation"


def test_non_feat_branch_returns_none(tmp_path):
    with _mock_branch("develop"):
        assert infer_run_id_from_branch(tmp_path) is None


def test_missing_dir_returns_stripped_for_backwards_compat(tmp_path):
    """目录都不存在时退回原行为返回 stripped；不静默 fail。"""
    with _mock_branch("feat/req-2099-999"):
        assert infer_run_id_from_branch(tmp_path) == "2099-999"


def test_already_uppercase_prefix_no_double_prefix(tmp_path):
    """防御性：若 stripped 已带 REQ- 前缀（如某历史脚本未走 _strip_req_prefix），不重复加。"""
    (tmp_path / "requirements" / "REQ-2026-014").mkdir(parents=True)
    with _mock_branch("feat/req-REQ-2026-014"):
        assert infer_run_id_from_branch(tmp_path) == "REQ-2026-014"
