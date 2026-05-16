"""F-012 · workflow_list --json flag 单元测试。

覆盖：
- acceptance #4：--json 输出有效 JSON，含 schema_version + items[]
- acceptance #5：缺省（无 --json）输出为表格，不是 JSON
- acceptance #6：--json --filter=phase=<X> → items[] 仅含该 phase
- --json + 空结果 → {"schema_version":"1.0","items":[]}

测试运行：
    python3 -m pytest tests/lib/test_workflow_list_json.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

import workflow_list  # noqa: E402


# ============================================================================
# fixture：准备含两条 run 的临时 repo_root
# ============================================================================

@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """构造含两个 requirements/ run 的最小 repo_root。

    REQ-2099-001：phase=development，template=standard-8phase
    REQ-2099-002：phase=design，template=feature-dev

    使用 JSON 兼容格式写 meta.yaml（workflow_list 支持 json fallback）。
    """
    req_dir = tmp_path / "requirements"
    req_dir.mkdir()

    # run 1
    run1 = req_dir / "REQ-2099-001"
    run1.mkdir()
    (run1 / "meta.yaml").write_text(
        json.dumps({
            "template": "standard-8phase",
            "phase": "development",
            "parent_run_id": "",
        }),
        encoding="utf-8",
    )
    # 无 run-state.jsonl → state=unknown（_load_run_entry 行为）

    # run 2
    run2 = req_dir / "REQ-2099-002"
    run2.mkdir()
    (run2 / "meta.yaml").write_text(
        json.dumps({
            "template": "feature-dev",
            "phase": "design",
            "parent_run_id": "",
        }),
        encoding="utf-8",
    )

    return tmp_path


# ============================================================================
# acceptance #4：--json 输出有效 JSON，含 schema_version + items[]
# ============================================================================

def test_json_flag_outputs_valid_json(fake_repo: Path, capsys):
    """--json → stdout 是有效 JSON；含 schema_version 与 items 键。"""
    rc = workflow_list.main(["--json"], repo_root=fake_repo)
    captured = capsys.readouterr()

    assert rc == 0
    payload = json.loads(captured.out)          # json.loads 不抛即为有效 JSON
    assert "schema_version" in payload, "JSON 输出缺 schema_version"
    assert "items" in payload, "JSON 输出缺 items"
    assert isinstance(payload["items"], list), "items 应为列表"


def test_json_flag_items_contain_runs(fake_repo: Path, capsys):
    """--json items[] 应包含 fixture 准备的两条 run。"""
    workflow_list.main(["--json"], repo_root=fake_repo)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert len(payload["items"]) == 2, f"期望 2 条 run，实际 {len(payload['items'])}"


# ============================================================================
# acceptance #5：缺省（无 --json）输出为表格，不是 JSON
# ============================================================================

def test_default_output_is_table_not_json(fake_repo: Path, capsys):
    """缺省模式（无 --json）stdout 不可被 json.loads 解析（表格格式）。"""
    rc = workflow_list.main([], repo_root=fake_repo)
    captured = capsys.readouterr()

    assert rc == 0
    # 表格输出不是 JSON
    with pytest.raises((json.JSONDecodeError, ValueError)):
        json.loads(captured.out)
    # 表格头应含列名
    assert "run_id" in captured.out


# ============================================================================
# acceptance #6：--json --filter=phase=development → items[] 仅含该 phase
# ============================================================================

def test_json_with_filter_returns_only_matching_phase(fake_repo: Path, capsys):
    """--json --filter=phase=development → items[] 仅含 phase=development 的 run。"""
    rc = workflow_list.main(["--json", "--filter=phase=development"], repo_root=fake_repo)
    captured = capsys.readouterr()

    assert rc == 0
    payload = json.loads(captured.out)
    items = payload["items"]
    assert len(items) == 1, f"filter=development 应得 1 条，实际 {len(items)}"
    assert items[0]["phase"] == "development"
    assert items[0]["run_id"] == "REQ-2099-001"


# ============================================================================
# --json + 空结果 → {"schema_version":"1.0","items":[]}
# ============================================================================

def test_json_empty_result(tmp_path: Path, capsys):
    """repo_root 下无任何 run → --json 输出 {"schema_version":"1.0","items":[]} 单行 JSON。"""
    # tmp_path 里什么都没有
    rc = workflow_list.main(["--json"], repo_root=tmp_path)
    captured = capsys.readouterr()

    assert rc == 0
    payload = json.loads(captured.out)
    assert payload == {"schema_version": "1.0", "items": []}, (
        f"空结果期望 {{schema_version, items:[]}}, 实际 {payload}"
    )
    # stdout 不含 "(无 workflow run)"（该文案仅在非 json 模式出现）
    assert "(无 workflow run)" not in captured.out


# ============================================================================
# filter 语法错 + json 模式：exit 1 + stderr 错误文案，不输出 partial JSON
# ============================================================================

def test_json_with_bad_filter_exits_1_no_stdout_json(fake_repo: Path, capsys):
    """--json --filter=bad_field=x → exit 1；stdout 不含 JSON；stderr 含 ERROR。"""
    rc = workflow_list.main(["--json", "--filter=bad_field=x"], repo_root=fake_repo)
    captured = capsys.readouterr()

    assert rc == 1
    assert "ERROR" in captured.err
    # stdout 应为空（不输出 partial JSON）
    assert captured.out.strip() == "", f"stdout 应为空，实际：{captured.out!r}"
