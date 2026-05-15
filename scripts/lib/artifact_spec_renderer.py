"""artifact 节点 spec 渲染（B4b IB-20 拆出，原属 workflow_dispatcher.py）。

职责：
  - 对 artifact spec 内 5 类字段（must_exist / must_not_exist / schema_check /
    must_contain_sections / must_match_regex）的 $VAR 引用做 substitute_vars 展开
  - 防御性深拷贝其余字段，避免 mutation 共享

设计来源：
  - F-005 rev2 落地 _render_artifact_spec（reviews/code-F-005-002.json）
  - B1 IB-19 拆 4 helper（refactor commit 1a25db4）
  - B4b IB-20 拆模块独立化
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import RunState  # noqa: E402
from substitute_vars import substitute_vars  # noqa: E402


def _render_list_field(items: list, fn) -> list:
    """渲染 must_exist / must_not_exist 列表（每项 str，调 fn 展开）。"""
    return [fn(item) if isinstance(item, str) else item for item in items]


def _render_schema_check_items(items: list, fn) -> list:
    """渲染 schema_check 列表项的 script + args[] 字段。"""
    rendered = []
    for chk in items:
        new_chk = dict(chk)
        if isinstance(new_chk.get("script"), str):
            new_chk["script"] = fn(new_chk["script"])
        if isinstance(new_chk.get("args"), list):
            new_chk["args"] = _render_list_field(new_chk["args"], fn)
        rendered.append(new_chk)
    return rendered


def _render_must_contain_items(items: list, fn) -> list:
    """渲染 must_contain_sections 列表项的 file + sections[] 字段。"""
    rendered = []
    for chk in items:
        new_chk = dict(chk)
        if isinstance(new_chk.get("file"), str):
            new_chk["file"] = fn(new_chk["file"])
        if isinstance(new_chk.get("sections"), list):
            new_chk["sections"] = _render_list_field(new_chk["sections"], fn)
        rendered.append(new_chk)
    return rendered


def _render_must_match_items(items: list, fn) -> list:
    """渲染 must_match_regex 列表项的 file + pattern 字段。"""
    rendered = []
    for chk in items:
        new_chk = dict(chk)
        if isinstance(new_chk.get("file"), str):
            new_chk["file"] = fn(new_chk["file"])
        if isinstance(new_chk.get("pattern"), str):
            new_chk["pattern"] = fn(new_chk["pattern"])
        rendered.append(new_chk)
    return rendered


def _make_spec_expander(run_state: RunState, env: dict[str, Any]):
    """构造 artifact spec $VAR 展开函数（escape_for_bash=False，路径类变量用裸字面值）。"""
    def _s(text: str) -> str:
        return substitute_vars(text, run_state.node_outputs, env, escape_for_bash=False)
    return _s


# 已知的 5 类可展开 spec 字段（key → helper 函数）；主函数按此表分发，其余字段 deepcopy 保留
_SPEC_RENDER_MAP = {
    "must_exist": _render_list_field,
    "must_not_exist": _render_list_field,
    "schema_check": _render_schema_check_items,
    "must_contain_sections": _render_must_contain_items,
    "must_match_regex": _render_must_match_items,
}


def _render_artifact_spec(spec: dict, run_state: RunState, env: dict[str, Any]) -> dict:
    """对 artifact spec 内 $VAR 引用做 substitute_vars 展开（5 类字段）。

    生产 yaml 字段全集 = {must_exist, schema_check, must_contain_sections}（已知）
    + 设计层 must_not_exist / must_match_regex 也覆盖（防御性）。
    「其余字段原样保留」路径走 deepcopy 防 mutation 共享（F-CR2-004 修复）。
    """
    fn = _make_spec_expander(run_state, env)
    rendered: dict = {}
    for key, helper in _SPEC_RENDER_MAP.items():
        if key in spec:
            rendered[key] = helper(spec[key] or [], fn)
    for key, val in spec.items():
        if key not in rendered:
            rendered[key] = copy.deepcopy(val)
    return rendered
