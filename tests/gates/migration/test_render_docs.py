"""scripts/gates/migration/render-docs.py 的单元测试。

覆盖 F-004 round-2 Block 4（F-8）+ 部分 F-20：
  1. valid registry → render 成功
  2. registry 不存在 → exit 1 + ERROR
  3. registry YAML 语法错 → exit 1 + ERROR
  4. registry 不可读（mock OSError）→ exit 1 + ERROR
  5. --check 模式 diff 为空 → exit 0
  6. --check 模式 diff 非空 → exit 1 + 打印行数差异
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, mock_open

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION_DIR = _REPO_ROOT / "scripts" / "gates" / "migration"
if str(_MIGRATION_DIR) not in sys.path:
    sys.path.insert(0, str(_MIGRATION_DIR))

# render-docs.py 模块名含连字符，用 importlib 导入
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "render_docs", _MIGRATION_DIR / "render-docs.py"
)
render_docs = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(render_docs)


# ====================== 辅助 ======================


def _minimal_registry_dict() -> dict:
    """合法 registry dict，含 1 个 gate 覆盖所有 trigger。"""
    return {
        "schema_version": "1.0",
        "gates": [
            {
                "id": "GATE-META-SCHEMA",
                "plugin": "meta_schema",
                "severity": "error",
                "triggers": ["phase-transition", "ci"],
                "failure_message": "meta schema fail",
            }
        ],
        "escape_hatches": [],
    }


def _minimal_registry_yaml() -> str:
    return yaml.dump(_minimal_registry_dict(), allow_unicode=True)


# ====================== Case 1：valid registry → render 成功 ======================


def test_render_gate_checklist_valid(tmp_path):
    """合法 registry → render_gate_checklist 返回含 gate id 的 Markdown 字符串。"""
    registry = _minimal_registry_dict()
    result = render_docs.render_gate_checklist(registry)
    assert "GATE-META-SCHEMA" in result
    assert "<!-- generated" in result


# ====================== Case 2：registry 不存在 → exit 1 ======================


def test_load_registry_not_exist(tmp_path, capsys, monkeypatch):
    """registry.yaml 不存在 → sys.exit(1) + ERROR 日志。"""
    nonexistent = tmp_path / "no_registry.yaml"
    monkeypatch.setattr(render_docs, "_REGISTRY_PATH", nonexistent)
    with pytest.raises(SystemExit) as exc_info:
        render_docs._load_registry()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "不存在" in captured.err


# ====================== Case 3：registry YAML 语法错 → exit 1 ======================


def test_load_registry_yaml_error(tmp_path, capsys, monkeypatch):
    """registry.yaml 含 YAML 语法错误 → sys.exit(1) + ERROR 日志。"""
    bad_yaml = tmp_path / "registry.yaml"
    bad_yaml.write_text(": : bad yaml {{{{", encoding="utf-8")
    monkeypatch.setattr(render_docs, "_REGISTRY_PATH", bad_yaml)
    with pytest.raises(SystemExit) as exc_info:
        render_docs._load_registry()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "语法错误" in captured.err


# ====================== Case 4：registry 不可读（mock OSError）→ exit 1 ======================


def test_load_registry_oserror(tmp_path, capsys, monkeypatch):
    """registry.yaml 读取抛 OSError → sys.exit(1) + ERROR 日志。"""
    # 创建一个存在的文件，然后 mock open 抛 OSError
    real_file = tmp_path / "registry.yaml"
    real_file.write_text("key: value", encoding="utf-8")
    monkeypatch.setattr(render_docs, "_REGISTRY_PATH", real_file)

    original_open = Path.open

    def _raise_oserror(self, *args, **kwargs):
        if self == real_file:
            raise OSError("Permission denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _raise_oserror)
    with pytest.raises(SystemExit) as exc_info:
        render_docs._load_registry()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "读取失败" in captured.err


# ====================== Case 5：--check 模式 diff 为空 → exit 0 ======================


def test_main_check_mode_no_diff(tmp_path, capsys, monkeypatch):
    """--check 模式：目标文件内容与渲染结果相同 → exit 0。"""
    registry_file = tmp_path / "registry.yaml"
    registry_file.write_text(_minimal_registry_yaml(), encoding="utf-8")

    # 先渲染得到内容
    registry = _minimal_registry_dict()
    expected_content = render_docs.render_gate_checklist(registry)

    output_file = tmp_path / "gate-checklist.md"
    output_file.write_text(expected_content, encoding="utf-8")

    monkeypatch.setattr(render_docs, "_REGISTRY_PATH", registry_file)
    monkeypatch.setattr(render_docs, "_OUTPUT_PATH", output_file)
    monkeypatch.setattr(sys, "argv", ["render-docs.py", "--check"])

    result = render_docs.main()
    assert result == 0
    captured = capsys.readouterr()
    assert "无差异" in captured.out


# ====================== Case 6：--check 模式 diff 非空 → exit 1 + 行数差异 ======================


def test_main_check_mode_with_diff(tmp_path, capsys, monkeypatch):
    """--check 模式：目标文件内容与渲染结果不同 → exit 1 + 行数差异提示。"""
    registry_file = tmp_path / "registry.yaml"
    registry_file.write_text(_minimal_registry_yaml(), encoding="utf-8")

    output_file = tmp_path / "gate-checklist.md"
    output_file.write_text("旧内容\n只有一行", encoding="utf-8")

    monkeypatch.setattr(render_docs, "_REGISTRY_PATH", registry_file)
    monkeypatch.setattr(render_docs, "_OUTPUT_PATH", output_file)
    monkeypatch.setattr(sys, "argv", ["render-docs.py", "--check"])

    result = render_docs.main()
    assert result == 1
    captured = capsys.readouterr()
    # 应包含行数差异提示
    assert "行" in captured.err
    assert "不同步" in captured.err
