"""save_review._check_artifact_blacklist 单测。

防止 reviewer agent 把 meta.yaml 或 reviews/ 自身塞进 reviewed_artifacts，
避免 R005 hash drift 自引用循环（历史教训：REQ-2026-003 曾踩到）。

来源：fix/reviewer-artifact-hashes-contract（双层防护——代码层是真护栏，
agent spec 层只是文档约束）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 注入 scripts/lib 到 path 以便 import save_review
_LIB_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import save_review as sr  # noqa: E402


def test_blacklist_passes_when_only_requirement_md():
    """given_only_requirement_md_when_check_then_pass."""
    artifacts = [{"path": "artifacts/requirement.md", "sha256": "0" * 64}]
    assert sr._check_artifact_blacklist(artifacts) is None


def test_blacklist_passes_when_multiple_design_artifacts():
    """given_design_phase_3_artifacts_when_check_then_pass."""
    artifacts = [
        {"path": "artifacts/detailed-design.md", "sha256": "0" * 64},
        {"path": "artifacts/features.json", "sha256": "0" * 64},
        {"path": "artifacts/outline-design.md", "sha256": "0" * 64},
    ]
    assert sr._check_artifact_blacklist(artifacts) is None


def test_blacklist_rejects_meta_yaml():
    """given_meta_yaml_in_artifacts_when_check_then_reject_with_loop_explanation."""
    artifacts = [
        {"path": "artifacts/requirement.md", "sha256": "0" * 64},
        {"path": "meta.yaml", "sha256": "0" * 64},
    ]
    err = sr._check_artifact_blacklist(artifacts)
    assert err is not None
    assert "meta.yaml" in err
    assert "自引用循环" in err  # 必须明示原因


def test_blacklist_rejects_meta_yaml_alone():
    """given_only_meta_yaml_when_check_then_reject."""
    artifacts = [{"path": "meta.yaml", "sha256": "0" * 64}]
    err = sr._check_artifact_blacklist(artifacts)
    assert err is not None
    assert "meta.yaml" in err


def test_blacklist_rejects_reviews_subpath():
    """given_reviews_dir_path_when_check_then_reject."""
    artifacts = [
        {"path": "artifacts/requirement.md", "sha256": "0" * 64},
        {"path": "reviews/definition-001.json", "sha256": "0" * 64},
    ]
    err = sr._check_artifact_blacklist(artifacts)
    assert err is not None
    assert "reviews/" in err
    assert "definition-001.json" in err  # 必须报具体 path


def test_blacklist_empty_list_passes():
    """given_empty_artifacts_when_check_then_pass（边界）."""
    assert sr._check_artifact_blacklist([]) is None


def test_blacklist_handles_missing_path_field():
    """given_artifact_dict_without_path_when_check_then_pass（防御性，不崩）."""
    # path 缺失的 artifact 由后续 sha256 重算逻辑自然报错；本检查不关心
    artifacts = [{"sha256": "0" * 64}]
    assert sr._check_artifact_blacklist(artifacts) is None
