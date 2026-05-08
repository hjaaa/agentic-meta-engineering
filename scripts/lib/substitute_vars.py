"""变量替换库：把 `$nodeId.output[.field]` 与 `$ENV_VAR` 替换为运行时值。

支持的变量语法：
- `$nodeId.output`           上游节点完整 stdout
- `$nodeId.output.field`     上游 stdout 解析为 JSON 后取 field
- `$ENV_VAR`                 环境变量（含 `$RUN_ID` / `$ARTIFACTS_DIR` / `$ARGUMENTS`
                             / `$LOOP_OUTPUT` / `$LOOP_PREV_OUTPUT` / `$LOOP_ITERATION`
                             / `$REJECTION_REASON` 等）

转义模式（escape_for_bash=True）：
- 字符串/数字/布尔 → 单引号 + `'\\''` 转义
- 数组/对象        → JSON 序列化后单引号
- null             → 空字符串单引号

设计取舍：
- 节点引用 pattern 比环境变量更具体（含 `.output`），先做节点替换再做 env，避免 `$LOOP_OUTPUT`
  之类的 ENV_VAR 误匹配为 `$LOOP.output_OUTPUT`（实际上 ENV_VAR_RE 不会匹配含 `.output` 的）
- 找不到节点 / JSON 解析失败 / 字段缺失 → 一律返回空字符串（spec §6.5）；不抛异常以便
  loader 层的 W131 校验先于运行时阻止"引用不存在节点"的情况。
"""
from __future__ import annotations

import json
import re
from typing import Any

# `$nodeId.output` 或 `$nodeId.output.field`
# nodeId: 小写字母开头 + 小写字母/数字/连字符（与 schema pattern 对齐）
# field:  英文字母/下划线开头 + 字母数字下划线
VAR_REF_RE = re.compile(
    r"\$(?P<node>[a-z][a-z0-9-]*)\.output(?:\.(?P<field>[a-zA-Z_][a-zA-Z0-9_]*))?"
)
# `$ENV_VAR`：全大写字母/数字/下划线，但**不**能后跟 `.output`（避免和节点引用冲突）
ENV_VAR_RE = re.compile(r"\$([A-Z_][A-Z0-9_]*)(?!\.output)")


def shell_quote(value: str) -> str:
    """把字符串包成单引号，内部 `'` 转为 `'\\''`。"""
    return "'" + value.replace("'", "'\\''") + "'"


def _serialize_for_substitution(value: Any, escape_for_bash: bool) -> str:
    """节点 output 值序列化策略——与 spec §6.5 注入防御一致。"""
    if value is None:
        return shell_quote("") if escape_for_bash else ""
    if isinstance(value, bool):
        rendered = "true" if value else "false"
        return shell_quote(rendered) if escape_for_bash else rendered
    if isinstance(value, (int, float)):
        rendered = str(value)
        return shell_quote(rendered) if escape_for_bash else rendered
    if isinstance(value, str):
        return shell_quote(value) if escape_for_bash else value
    if isinstance(value, (list, dict)):
        rendered = json.dumps(value, ensure_ascii=False)
        return shell_quote(rendered) if escape_for_bash else rendered
    rendered = str(value)
    return shell_quote(rendered) if escape_for_bash else rendered


def substitute_vars(
    text: str | None,
    node_outputs: dict[str, dict[str, Any]] | None,
    env: dict[str, str] | None,
    escape_for_bash: bool = False,
) -> str:
    """替换文本中所有 `$nodeId.output[.field]` 与 `$ENV_VAR`。

    - `node_outputs`：`{node_id: {"output": str, ...}}`；其中 output 是节点的 stdout。
    - `env`：环境/ARGUMENTS/LOOP_OUTPUT 等扁平 KV。

    注意：未匹配到的引用一律返回空字符串（bash 模式下是 `''`）。
    """
    if not text:
        return text or ""

    no = node_outputs or {}
    ev = env or {}

    def replace_node_ref(match: re.Match[str]) -> str:
        node_id = match.group("node")
        field = match.group("field")
        node = no.get(node_id)
        if node is None:
            return shell_quote("") if escape_for_bash else ""
        output_str = node.get("output", "")
        if field is None:
            # 整体输出（视为字符串）
            if isinstance(output_str, str):
                return shell_quote(output_str) if escape_for_bash else output_str
            return _serialize_for_substitution(output_str, escape_for_bash)
        # 字段提取需要把 output 当 JSON 解析
        try:
            parsed = json.loads(output_str) if isinstance(output_str, str) else output_str
        except (json.JSONDecodeError, TypeError):
            return shell_quote("") if escape_for_bash else ""
        if not isinstance(parsed, dict):
            return shell_quote("") if escape_for_bash else ""
        if field not in parsed:
            return shell_quote("") if escape_for_bash else ""
        return _serialize_for_substitution(parsed[field], escape_for_bash)

    def replace_env(match: re.Match[str]) -> str:
        name = match.group(1)
        value = ev.get(name, "")
        return shell_quote(value) if escape_for_bash else value

    # 节点引用先替换（更具体），环境变量后替换
    result = VAR_REF_RE.sub(replace_node_ref, text)
    result = ENV_VAR_RE.sub(replace_env, result)
    return result
