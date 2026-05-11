"""F-005 · workflow_list 单测。

覆盖：
- _load_run_entry 在 PyYAML 缺失时仍能从 JSON 兼容的 meta.yaml fallback。

测试运行：
    python3 -m pytest tests/lib/test_workflow_list.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import workflow_list  # noqa: E402


def test_load_run_entry_no_pyyaml_falls_back_to_json(tmp_path, monkeypatch, capsys):
    """PyYAML 未安装（yaml=None）时 _load_run_entry 应走 json fallback。

    回归 codex round-1 P1-1：原实现 import yaml 在 try 块内，except yaml.YAMLError
    会因 yaml 名未绑定再抛 NameError，导致 /workflow:list 在最小环境完全失败。
    本用例同时覆盖：
      1) 修复要求 yaml 必须挂模块级（否则 monkeypatch.setattr 找不到属性）；
      2) yaml=None 分支必须走 json fallback 并正确读出 template/phase/parent_run_id。
    """
    # 构造一个 JSON 兼容内容的 meta.yaml（dict 字面量在 yaml/json 下等价）
    run_dir = tmp_path / "REQ-2099-001"
    run_dir.mkdir()
    meta_path = run_dir / "meta.yaml"
    meta_payload = {
        "template": "feature-dev",
        "phase": "development",
        "parent_run_id": "REQ-2099-000",
    }
    meta_path.write_text(json.dumps(meta_payload), encoding="utf-8")

    # 模拟 PyYAML 缺失：把模块级 yaml 句柄置 None
    # raising=True（默认）确保只要 workflow_list 没把 yaml 挂模块级即报错——
    # 这是修复"yaml 必须模块级"的硬约束。
    monkeypatch.setattr(workflow_list, "yaml", None, raising=True)

    entry = workflow_list._load_run_entry(run_dir)
    assert entry is not None
    assert entry["template"] == "feature-dev"
    assert entry["phase"] == "development"
    assert entry["parent_run_id"] == "REQ-2099-000"
    # state 在缺 jsonl 时应为 unknown（与原行为一致）
    assert entry["state"] == "unknown"
