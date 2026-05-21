"""tests for workflow_bootstrap._infer_default_project（Bug-2）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import workflow_bootstrap as wb  # noqa: E402


def test_real_repo_returns_agentic_meta_engineering():
    """实际仓库下 context/project/ 单个目录 agentic-meta-engineering → 返回该名"""
    assert wb._infer_default_project() == "agentic-meta-engineering"


def test_multi_project_picks_first_sorted(tmp_path, monkeypatch):
    """多 project → 默认取首个（按字典序）"""
    fake_repo = tmp_path
    (fake_repo / "context" / "project" / "alpha").mkdir(parents=True)
    (fake_repo / "context" / "project" / "beta").mkdir(parents=True)
    monkeypatch.setattr(wb, "REPO_ROOT", fake_repo)
    assert wb._infer_default_project() == "alpha"


def test_zero_project_returns_empty(tmp_path, monkeypatch):
    """零 project 目录 → 返回空字符串"""
    fake_repo = tmp_path
    (fake_repo / "context" / "project").mkdir(parents=True)
    monkeypatch.setattr(wb, "REPO_ROOT", fake_repo)
    assert wb._infer_default_project() == ""


def test_no_project_root(tmp_path, monkeypatch):
    """context/project 根都不存在 → 返回空字符串"""
    fake_repo = tmp_path
    monkeypatch.setattr(wb, "REPO_ROOT", fake_repo)
    assert wb._infer_default_project() == ""


def test_hidden_dir_ignored(tmp_path, monkeypatch):
    """以 . 开头的目录被忽略"""
    fake_repo = tmp_path
    (fake_repo / "context" / "project" / ".git").mkdir(parents=True)
    (fake_repo / "context" / "project" / "real").mkdir(parents=True)
    monkeypatch.setattr(wb, "REPO_ROOT", fake_repo)
    assert wb._infer_default_project() == "real"
