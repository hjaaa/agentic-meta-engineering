# Workflow Engine Plan 1：Schema + Loader 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 workflow yaml schema 定义 + loader（解析 + 校验 + 三层发现）+ 变量替换库 + 拓扑排序。完成后能加载任意 workflow yaml 并报告语法/语义错误，但**不**能执行节点（执行属于 Plan 2）。

**Architecture:** 沿用本仓库 Python 风格——`scripts/lib/` 下纯函数模块 + `tests/lib/` 下 pytest 测试。每模块单一职责：`workflow_loader.py` 加载 + 校验，`substitute_vars.py` 变量替换，`topological_sort.py` Kahn 算法。所有错误归集到既有 `Report`（来自 `common.py`），退出码沿用 0/1/2 约定。

**Tech Stack:**
- Python 3.10+（项目既有版本，`from __future__ import annotations` 风格）
- PyYAML（解析 yaml）— 检查是否已装
- jsonschema（JSON Schema 校验）— 可能要新增
- pytest（测试）— 已装
- ruff（lint，select=F）— 已装

**Spec 参考:** `docs/specs/2026-05-08-workflow-unified-redesign.md`（v2，APPROVED）

**本 Plan 范围 = Spec §6（schema）+ §11.3（rollback 不实现，仅 schema 校验）+ §13 风险中的 loader 校验项**
**不在范围**：节点执行、run-state.jsonl 读写、命令实现、引擎主循环（这些在 Plan 2-4）

---

## File Structure

### 新建文件

```
.claude/workflows/                       # 模板目录（Plan 1 只建空目录占位）
├── bundled/                              # bundled 默认模板（占位）
├── requirement/                          # category 子目录
├── review/
├── release/
└── prompts/                              # prompt 复用文件目录

scripts/lib/
├── workflow_schema.json                  # JSON Schema 定义（v1）
├── workflow_loader.py                    # 加载 + 校验主入口
├── substitute_vars.py                    # 变量替换 + 转义
└── topological_sort.py                   # Kahn 算法

tests/lib/
├── fixtures/
│   └── workflows/
│       ├── valid-minimal.yaml            # 最小合法 yaml
│       ├── valid-full.yaml               # 全字段合法 yaml
│       ├── invalid-no-nodes.yaml         # 无 nodes
│       ├── invalid-mutex.yaml            # 节点字段互斥违反
│       ├── invalid-circular.yaml         # DAG 有环
│       ├── invalid-missing-dep.yaml      # depends_on 引用不存在
│       ├── invalid-bad-when.yaml         # when 表达式语法错
│       ├── invalid-bad-var-ref.yaml      # $nodeId.output 引用不存在节点
│       ├── invalid-bad-prompt-file.yaml  # prompt_file 路径不存在
│       ├── invalid-deep-nest.yaml        # sub_workflow 嵌套 > 2
│       └── sub-fixtures/                 # 嵌套 yaml fixtures
│           └── child.yaml
├── test_workflow_loader.py               # loader 主测试（最大文件）
├── test_substitute_vars.py
└── test_topological_sort.py
```

### 不修改的文件

- `scripts/lib/common.py` — 复用 `REPO_ROOT / Report / Severity / paint / rel`，**不改**
- `pyproject.toml` — 可能需要在 `[tool.ruff]` 之外加 `[project.optional-dependencies]`，但**优先尝试不改**（PyYAML / jsonschema 若已在系统 Python 可直接 import）

---

## Task 1: 项目结构搭建 + JSON Schema 骨架

**Files:**
- Create: `.claude/workflows/{bundled,requirement,review,release,prompts}/.gitkeep`
- Create: `scripts/lib/workflow_schema.json`
- Modify: `.gitignore` — 加 `runs/*/.run-logs/`

- [ ] **Step 1: 建目录骨架**

```bash
mkdir -p .claude/workflows/{bundled,requirement,review,release,prompts}
for d in bundled requirement review release prompts; do
  touch ".claude/workflows/$d/.gitkeep"
done
mkdir -p tests/lib/fixtures/workflows/sub-fixtures
```

- [ ] **Step 2: 写 `workflow_schema.json`（JSON Schema v1）**

文件 `scripts/lib/workflow_schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://internal/workflow-schema-v1",
  "title": "Workflow Definition v1",
  "type": "object",
  "required": ["name", "version", "category", "nodes"],
  "additionalProperties": false,
  "properties": {
    "name": { "type": "string", "pattern": "^[a-z][a-z0-9-]{0,49}$" },
    "description": { "type": "string" },
    "version": { "type": "integer", "const": 1 },
    "category": {
      "type": "string",
      "enum": ["requirement", "review", "release", "knowledge", "pr", "assist"]
    },
    "default_for": { "type": "string" },
    "provider": { "type": "string", "enum": ["claude"] },
    "model": { "type": "string" },
    "thinking": {
      "oneOf": [
        { "type": "string", "enum": ["adaptive", "enabled", "disabled"] },
        {
          "type": "object",
          "required": ["type"],
          "properties": {
            "type": { "type": "string", "enum": ["adaptive", "enabled", "disabled"] },
            "budgetTokens": { "type": "integer", "minimum": 1 }
          }
        }
      ]
    },
    "effort": { "type": "string", "enum": ["low", "medium", "high", "max"] },
    "applicable_when": {
      "type": "object",
      "properties": {
        "change_type": { "type": "array", "items": { "type": "string" } },
        "recommended": { "type": "boolean" }
      }
    },
    "nodes": {
      "type": "array",
      "minItems": 1,
      "items": { "$ref": "#/$defs/node" }
    }
  },
  "$defs": {
    "node": {
      "type": "object",
      "required": ["id"],
      "properties": {
        "id": { "type": "string", "pattern": "^[a-z][a-z0-9-]{0,59}$" },
        "depends_on": { "type": "array", "items": { "type": "string" } },
        "when": { "type": "string" },
        "trigger_rule": { "type": "string", "enum": ["all_success", "one_success", "all_done"] },
        "provider": { "type": "string", "enum": ["claude"] },
        "model": { "type": "string" },
        "effort": { "type": "string", "enum": ["low", "medium", "high", "max"] },
        "thinking": { "$ref": "#/properties/thinking" },
        "fallback_model": { "type": "string" },
        "context": { "type": "string", "enum": ["fresh", "shared"] },
        "allowed_tools": { "type": "array", "items": { "type": "string" } },
        "denied_tools": { "type": "array", "items": { "type": "string" } },
        "output_format": { "type": "object" },
        "retry": {
          "type": "object",
          "properties": {
            "max_attempts": { "type": "integer", "minimum": 0 },
            "delay_ms": { "type": "integer", "minimum": 0 },
            "on_error": { "type": "string", "enum": ["transient", "all"] }
          }
        },
        "idle_timeout": { "type": "integer", "minimum": 1 },

        "skill": { "type": "string" },
        "agent": { "type": "string" },
        "prompt": { "type": "string" },
        "prompt_file": { "type": "string" },
        "prompt_override": { "type": "string" },
        "args": { "type": "object" },
        "bash": { "type": "string" },
        "timeout": { "type": "integer", "minimum": 1 },
        "loop": {
          "type": "object",
          "required": ["max_iterations"],
          "properties": {
            "prompt": { "type": "string" },
            "prompt_file": { "type": "string" },
            "until": { "type": "string" },
            "until_bash": { "type": "string" },
            "max_iterations": { "type": "integer", "minimum": 1 },
            "fresh_context": { "type": "boolean" },
            "interactive": { "type": "boolean" },
            "gate_message": { "type": "string" }
          }
        },
        "approval": {
          "type": "object",
          "required": ["message"],
          "properties": {
            "message": { "type": "string" },
            "capture_response": { "type": "boolean" },
            "on_reject": {
              "type": "object",
              "required": ["prompt", "max_attempts"],
              "properties": {
                "prompt": { "type": "string" },
                "max_attempts": { "type": "integer", "minimum": 1 }
              }
            }
          }
        },
        "artifact": {
          "type": "object",
          "properties": {
            "must_exist": { "type": "array", "items": { "type": "string" } },
            "must_not_exist": { "type": "array", "items": { "type": "string" } },
            "schema_check": { "type": "array" },
            "must_contain_sections": { "type": "array" },
            "must_match_regex": { "type": "array" }
          }
        },
        "sub_workflow": { "type": "string" },
        "output_capture": { "type": "string" },
        "on_subworkflow_failure": { "type": "string", "enum": ["fail", "continue", "skip"] }
      }
    }
  }
}
```

- [ ] **Step 3: 验证 JSON Schema 自身合法**

```bash
python3 -c "
import json, jsonschema
with open('scripts/lib/workflow_schema.json') as f:
    schema = json.load(f)
jsonschema.Draft202012Validator.check_schema(schema)
print('schema 自身合法')
"
```

Expected: `schema 自身合法`

- [ ] **Step 4: 加 .gitignore 条目**

```bash
grep -q "^runs/\*/\.run-logs/" .gitignore || echo "runs/*/.run-logs/" >> .gitignore
grep -q "^runs/\*/\.archived/" .gitignore || echo "runs/*/.archived/" >> .gitignore
```

- [ ] **Step 5: Commit**

```bash
git add .claude/workflows/ scripts/lib/workflow_schema.json .gitignore tests/lib/fixtures
git commit -m "feat(workflow): scaffold workflow yaml schema v1 + directory structure"
```

---

## Task 2: 基础 yaml 加载（loader 入口 + 顶层字段）

**Files:**
- Create: `scripts/lib/workflow_loader.py`
- Create: `tests/lib/fixtures/workflows/valid-minimal.yaml`
- Create: `tests/lib/test_workflow_loader.py`

- [ ] **Step 1: 写 fixture `valid-minimal.yaml`**

```yaml
# tests/lib/fixtures/workflows/valid-minimal.yaml
name: minimal-test
description: minimal valid workflow
version: 1
category: assist
provider: claude
model: sonnet

nodes:
  - id: only-node
    bash: echo "hello"
```

- [ ] **Step 2: 写测试 `test_workflow_loader.py::test_load_minimal_workflow`**

```python
# tests/lib/test_workflow_loader.py
"""workflow_loader 测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 将 scripts/lib 加入 sys.path（项目惯用方式）
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from workflow_loader import load_workflow, LoadResult  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "lib" / "fixtures" / "workflows"


def test_load_minimal_workflow_returns_parsed_dict():
    result = load_workflow(FIXTURES / "valid-minimal.yaml")
    assert isinstance(result, LoadResult)
    assert result.report.errors == 0
    assert result.workflow is not None
    assert result.workflow["name"] == "minimal-test"
    assert result.workflow["version"] == 1
    assert result.workflow["category"] == "assist"
    assert len(result.workflow["nodes"]) == 1
    assert result.workflow["nodes"][0]["id"] == "only-node"
```

- [ ] **Step 3: 跑测试看 fail**

```bash
cd /Users/richardhuang/learnspace/agentic-meta-engineering
python3 -m pytest tests/lib/test_workflow_loader.py::test_load_minimal_workflow_returns_parsed_dict -v
```

Expected: FAIL，错误 `ModuleNotFoundError: No module named 'workflow_loader'`

- [ ] **Step 4: 写最小实现 `workflow_loader.py`**

```python
# scripts/lib/workflow_loader.py
"""Workflow yaml 加载与校验。

输入：workflow yaml 文件路径
输出：LoadResult（含 workflow dict + Report）

使用：
  from workflow_loader import load_workflow
  result = load_workflow(Path('.claude/workflows/requirement/standard-8phase.yaml'))
  if result.report.errors:
      print(result.report.render())
      sys.exit(1)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from common import REPO_ROOT, Report, Severity, rel

SCHEMA_PATH = Path(__file__).parent / "workflow_schema.json"


@dataclass
class LoadResult:
    """workflow_loader 返回值。"""

    workflow: dict[str, Any] | None
    report: Report = field(default_factory=Report)
    source_path: Path | None = None


def load_workflow(path: Path) -> LoadResult:
    """加载并校验单个 workflow yaml。

    错误码语义：
      W001 yaml 解析失败
      W100 yaml 缺少必填字段（name/version/category/nodes）
    """
    result = LoadResult(workflow=None, source_path=path)
    file_label = rel(path)

    if not path.exists():
        result.report.add(file_label, Severity.ERROR, "W000", f"文件不存在: {path}")
        return result

    try:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        result.report.add(file_label, Severity.ERROR, "W001", f"yaml 解析失败: {exc}")
        return result

    if not isinstance(raw, dict):
        result.report.add(file_label, Severity.ERROR, "W001", "yaml 顶层必须是 mapping")
        return result

    result.workflow = raw
    return result
```

- [ ] **Step 5: 跑测试看 pass**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py::test_load_minimal_workflow_returns_parsed_dict -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/workflow_loader.py tests/lib/test_workflow_loader.py tests/lib/fixtures/
git commit -m "feat(workflow): add basic yaml loader returning LoadResult"
```

---

## Task 3: JSON Schema 校验集成

**Files:**
- Modify: `scripts/lib/workflow_loader.py`
- Modify: `tests/lib/test_workflow_loader.py`
- Create: `tests/lib/fixtures/workflows/invalid-no-nodes.yaml`

- [ ] **Step 1: 写 fixture `invalid-no-nodes.yaml`**

```yaml
# tests/lib/fixtures/workflows/invalid-no-nodes.yaml
name: no-nodes-workflow
version: 1
category: assist
nodes: []
```

- [ ] **Step 2: 加测试 `test_load_rejects_empty_nodes` + `test_load_rejects_missing_required`**

```python
# 加到 tests/lib/test_workflow_loader.py 末尾

def test_load_rejects_empty_nodes_array():
    result = load_workflow(FIXTURES / "invalid-no-nodes.yaml")
    assert result.report.errors > 0
    codes = [code for _, _, code, _ in result.report.findings()]
    assert "W100" in codes


def test_load_rejects_missing_name_field(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\ncategory: assist\nnodes:\n  - id: x\n    bash: 'echo'\n")
    result = load_workflow(bad)
    assert result.report.errors > 0
    codes = [code for _, _, code, _ in result.report.findings()]
    assert "W100" in codes
```

- [ ] **Step 3: 跑测试看 fail**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v -k "rejects"
```

Expected: 2 FAIL（`W100` 不在 findings 中——loader 还没做 schema 校验）

- [ ] **Step 4: 改 `workflow_loader.py` 集成 jsonschema**

替换 `load_workflow` 函数为：

```python
import jsonschema

_SCHEMA: dict[str, Any] | None = None


def _get_schema() -> dict[str, Any]:
    global _SCHEMA
    if _SCHEMA is None:
        with SCHEMA_PATH.open("r", encoding="utf-8") as f:
            _SCHEMA = json.load(f)
    return _SCHEMA


def load_workflow(path: Path) -> LoadResult:
    """加载并校验单个 workflow yaml。"""
    result = LoadResult(workflow=None, source_path=path)
    file_label = rel(path)

    if not path.exists():
        result.report.add(file_label, Severity.ERROR, "W000", f"文件不存在: {path}")
        return result

    try:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        result.report.add(file_label, Severity.ERROR, "W001", f"yaml 解析失败: {exc}")
        return result

    if not isinstance(raw, dict):
        result.report.add(file_label, Severity.ERROR, "W001", "yaml 顶层必须是 mapping")
        return result

    # JSON Schema 校验
    schema = _get_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(raw), key=lambda e: e.absolute_path)
    for err in errors:
        path_str = "/".join(str(p) for p in err.absolute_path) or "(root)"
        result.report.add(
            file_label, Severity.ERROR, "W100",
            f"schema 校验失败 @{path_str}: {err.message}",
        )

    if not result.report.errors:
        result.workflow = raw
    return result
```

- [ ] **Step 5: 跑测试看 pass（新加的 + 之前的都要过）**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v
```

Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/workflow_loader.py tests/lib/
git commit -m "feat(workflow): integrate jsonschema validation, emit W100 on schema failures"
```

---

## Task 4: 节点类型互斥校验（8 选 1）

**Files:**
- Modify: `scripts/lib/workflow_loader.py`
- Modify: `tests/lib/test_workflow_loader.py`
- Create: `tests/lib/fixtures/workflows/invalid-mutex.yaml`

- [ ] **Step 1: 写 fixture `invalid-mutex.yaml`（节点同时配 skill 和 prompt）**

```yaml
name: mutex-violation
version: 1
category: assist
nodes:
  - id: bad-node
    skill: foo
    prompt: bar
```

- [ ] **Step 2: 写测试**

```python
def test_node_type_fields_are_mutually_exclusive():
    result = load_workflow(FIXTURES / "invalid-mutex.yaml")
    assert result.report.errors > 0
    codes = [code for _, _, code, _ in result.report.findings()]
    assert "W110" in codes


def test_node_must_have_at_least_one_type_field():
    """没写 skill/agent/prompt/bash/loop/approval/artifact/sub_workflow 任一字段。"""
    result = load_workflow(FIXTURES / "invalid-no-type.yaml")
    assert result.report.errors > 0
    codes = [code for _, _, code, _ in result.report.findings()]
    assert "W111" in codes
```

写第二个 fixture `invalid-no-type.yaml`:

```yaml
name: no-type
version: 1
category: assist
nodes:
  - id: orphan
    depends_on: []
```

- [ ] **Step 3: 跑测试看 fail**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v -k "mutex or at_least_one"
```

Expected: 2 FAIL

- [ ] **Step 4: 加互斥校验逻辑到 workflow_loader.py**

在 `load_workflow` 末尾（schema 校验通过后）加调用，并新增函数：

```python
NODE_TYPE_FIELDS = (
    "skill", "agent", "prompt", "bash", "loop", "approval", "artifact", "sub_workflow"
)


def _validate_node_type_mutex(workflow: dict[str, Any], report: Report, file_label: str) -> None:
    """每个节点必须恰好有 1 个 NODE_TYPE_FIELDS。"""
    for idx, node in enumerate(workflow.get("nodes", [])):
        node_id = node.get("id", f"<node #{idx}>")
        present = [f for f in NODE_TYPE_FIELDS if f in node]
        if len(present) > 1:
            report.add(
                file_label, Severity.ERROR, "W110",
                f"节点 {node_id} 同时声明了 {present}，节点类型字段必须互斥",
            )
        elif len(present) == 0:
            report.add(
                file_label, Severity.ERROR, "W111",
                f"节点 {node_id} 必须声明 1 个节点类型字段：{NODE_TYPE_FIELDS}",
            )


# 在 load_workflow 内 schema 校验之后加：
def load_workflow(path: Path) -> LoadResult:
    # ... 前面不变 ...
    if not result.report.errors:
        _validate_node_type_mutex(raw, result.report, file_label)
    if not result.report.errors:
        result.workflow = raw
    return result
```

- [ ] **Step 5: 跑测试看 pass**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v
```

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/workflow_loader.py tests/lib/
git commit -m "feat(workflow): enforce node type field mutual exclusion (W110/W111)"
```

---

## Task 5: 节点 ID 唯一性校验

**Files:**
- Modify: `scripts/lib/workflow_loader.py`
- Modify: `tests/lib/test_workflow_loader.py`

- [ ] **Step 1: 写 fixture `invalid-dup-id.yaml`**

```yaml
name: dup-id
version: 1
category: assist
nodes:
  - id: a
    bash: "echo 1"
  - id: a
    bash: "echo 2"
```

- [ ] **Step 2: 写测试**

```python
def test_node_ids_must_be_unique():
    result = load_workflow(FIXTURES / "invalid-dup-id.yaml")
    assert result.report.errors > 0
    codes = [code for _, _, code, _ in result.report.findings()]
    assert "W112" in codes
```

- [ ] **Step 3: 跑测试看 fail**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v -k "unique"
```

Expected: FAIL

- [ ] **Step 4: 加唯一性校验**

```python
def _validate_node_id_uniqueness(workflow: dict[str, Any], report: Report, file_label: str) -> None:
    seen: dict[str, int] = {}
    for idx, node in enumerate(workflow.get("nodes", [])):
        nid = node.get("id")
        if not nid:
            continue
        if nid in seen:
            report.add(
                file_label, Severity.ERROR, "W112",
                f"节点 ID '{nid}' 重复（首次在 #{seen[nid]}，再次在 #{idx}）",
            )
        else:
            seen[nid] = idx


# load_workflow 内串联调用：
_validate_node_type_mutex(raw, result.report, file_label)
_validate_node_id_uniqueness(raw, result.report, file_label)
```

- [ ] **Step 5: 跑测试看 pass**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v
```

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/workflow_loader.py tests/lib/
git commit -m "feat(workflow): enforce node id uniqueness (W112)"
```

---

## Task 6: 拓扑排序 + DAG 无环 + depends_on 引用校验

**Files:**
- Create: `scripts/lib/topological_sort.py`
- Create: `tests/lib/test_topological_sort.py`
- Modify: `scripts/lib/workflow_loader.py`
- Modify: `tests/lib/test_workflow_loader.py`

- [ ] **Step 1: 写 `test_topological_sort.py`**

```python
# tests/lib/test_topological_sort.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from topological_sort import topological_layers, CycleError  # noqa: E402


def test_should_return_layers_for_simple_chain():
    nodes = [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": ["a"]},
        {"id": "c", "depends_on": ["b"]},
    ]
    layers = topological_layers(nodes)
    assert layers == [["a"], ["b"], ["c"]]


def test_should_group_independent_nodes_in_same_layer():
    nodes = [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": []},
        {"id": "c", "depends_on": ["a", "b"]},
    ]
    layers = topological_layers(nodes)
    assert sorted(layers[0]) == ["a", "b"]
    assert layers[1] == ["c"]


def test_should_raise_on_cycle():
    nodes = [
        {"id": "a", "depends_on": ["b"]},
        {"id": "b", "depends_on": ["a"]},
    ]
    with pytest.raises(CycleError):
        topological_layers(nodes)


def test_should_handle_implicit_depends_on_previous():
    """yaml 加载阶段已展开 depends_on=上一节点，此函数只接受显式 depends_on。"""
    nodes = [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": ["a"]},
        {"id": "c", "depends_on": ["b"]},
    ]
    layers = topological_layers(nodes)
    assert len(layers) == 3
```

- [ ] **Step 2: 跑测试看 fail**

```bash
python3 -m pytest tests/lib/test_topological_sort.py -v
```

Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `topological_sort.py`**

```python
# scripts/lib/topological_sort.py
"""Kahn 拓扑排序，生成可并发执行的 layer 列表。

每个 layer 内的节点彼此独立、可并发；layer 间严格串行（layer N 必须等 layer N-1 全部 terminal）。
"""
from __future__ import annotations

from typing import Any


class CycleError(Exception):
    """DAG 发现环。"""

    def __init__(self, remaining_nodes: list[str]) -> None:
        super().__init__(f"DAG 中存在环，剩余节点: {remaining_nodes}")
        self.remaining_nodes = remaining_nodes


def topological_layers(nodes: list[dict[str, Any]]) -> list[list[str]]:
    """Kahn 算法。返回 [[layer0_node_ids], [layer1_node_ids], ...]。

    输入 nodes 必须已经把 depends_on 展开为显式列表（即不依赖隐式接上一节点的语法糖）。
    """
    in_degree: dict[str, int] = {}
    successors: dict[str, list[str]] = {}
    all_ids: set[str] = set()

    for n in nodes:
        nid = n["id"]
        all_ids.add(nid)
        deps = n.get("depends_on", []) or []
        in_degree[nid] = len(deps)
        for d in deps:
            successors.setdefault(d, []).append(nid)

    layers: list[list[str]] = []
    ready = sorted(nid for nid in all_ids if in_degree[nid] == 0)

    while ready:
        layers.append(ready)
        next_ready: list[str] = []
        for nid in ready:
            for succ in successors.get(nid, []):
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    next_ready.append(succ)
        ready = sorted(next_ready)

    processed = sum(len(l) for l in layers)
    if processed != len(all_ids):
        remaining = [nid for nid in all_ids if in_degree[nid] > 0]
        raise CycleError(remaining)

    return layers
```

- [ ] **Step 4: 跑测试看 pass**

```bash
python3 -m pytest tests/lib/test_topological_sort.py -v
```

Expected: 4 PASS

- [ ] **Step 5: 集成到 workflow_loader.py + 加 fixtures + 测试**

写 fixtures：

```yaml
# tests/lib/fixtures/workflows/invalid-circular.yaml
name: circular
version: 1
category: assist
nodes:
  - id: a
    bash: "echo"
    depends_on: [b]
  - id: b
    bash: "echo"
    depends_on: [a]
```

```yaml
# tests/lib/fixtures/workflows/invalid-missing-dep.yaml
name: missing-dep
version: 1
category: assist
nodes:
  - id: a
    bash: "echo"
    depends_on: [nonexistent]
```

加测试：

```python
def test_load_rejects_circular_dependency():
    result = load_workflow(FIXTURES / "invalid-circular.yaml")
    codes = [c for _, _, c, _ in result.report.findings()]
    assert "W120" in codes  # cycle detected


def test_load_rejects_missing_depends_on_target():
    result = load_workflow(FIXTURES / "invalid-missing-dep.yaml")
    codes = [c for _, _, c, _ in result.report.findings()]
    assert "W121" in codes  # missing dep
```

集成到 loader：

```python
from topological_sort import topological_layers, CycleError


def _expand_implicit_depends_on(workflow: dict[str, Any]) -> None:
    """depends_on 缺省时取上一节点 id，写回原 dict（mutate in place）。"""
    nodes = workflow.get("nodes", [])
    prev_id: str | None = None
    for node in nodes:
        if "depends_on" not in node:
            node["depends_on"] = [prev_id] if prev_id else []
        prev_id = node.get("id")


def _validate_dag(workflow: dict[str, Any], report: Report, file_label: str) -> None:
    nodes = workflow.get("nodes", [])
    all_ids = {n["id"] for n in nodes if "id" in n}

    for n in nodes:
        for d in n.get("depends_on", []):
            if d not in all_ids:
                report.add(
                    file_label, Severity.ERROR, "W121",
                    f"节点 {n.get('id')} 的 depends_on 引用了不存在的节点 '{d}'",
                )

    if report.errors:  # 有 missing dep 时不再跑拓扑（会误报）
        return

    try:
        topological_layers(nodes)
    except CycleError as exc:
        report.add(
            file_label, Severity.ERROR, "W120",
            f"DAG 存在环：{exc.remaining_nodes}",
        )


# load_workflow 内调用顺序（schema → 互斥 → ID 唯一 → 展开 implicit → DAG）：
_validate_node_type_mutex(raw, result.report, file_label)
_validate_node_id_uniqueness(raw, result.report, file_label)
if not result.report.errors:
    _expand_implicit_depends_on(raw)
    _validate_dag(raw, result.report, file_label)
```

- [ ] **Step 6: 跑全部测试**

```bash
python3 -m pytest tests/lib/test_topological_sort.py tests/lib/test_workflow_loader.py -v
```

Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/topological_sort.py scripts/lib/workflow_loader.py tests/lib/
git commit -m "feat(workflow): add topological_sort + DAG/cycle validation (W120/W121)"
```

---

## Task 7: when 表达式语法校验 + 变量引用合法性

**Files:**
- Modify: `scripts/lib/workflow_loader.py`
- Modify: `tests/lib/test_workflow_loader.py`
- Create: `tests/lib/fixtures/workflows/invalid-bad-when.yaml`
- Create: `tests/lib/fixtures/workflows/invalid-bad-var-ref.yaml`

- [ ] **Step 1: 写 fixtures**

```yaml
# tests/lib/fixtures/workflows/invalid-bad-when.yaml
name: bad-when
version: 1
category: assist
nodes:
  - id: a
    bash: "echo"
  - id: b
    bash: "echo"
    when: "$$$$$ broken syntax"
```

```yaml
# tests/lib/fixtures/workflows/invalid-bad-var-ref.yaml
name: bad-var-ref
version: 1
category: assist
nodes:
  - id: a
    bash: "echo $nonexistent.output.field"
  - id: b
    bash: "echo"
    when: "$missing.output.x == 'y'"
```

- [ ] **Step 2: 写测试**

```python
def test_load_rejects_invalid_when_syntax():
    result = load_workflow(FIXTURES / "invalid-bad-when.yaml")
    codes = [c for _, _, c, _ in result.report.findings()]
    assert "W130" in codes


def test_load_rejects_var_reference_to_nonexistent_node():
    result = load_workflow(FIXTURES / "invalid-bad-var-ref.yaml")
    codes = [c for _, _, c, _ in result.report.findings()]
    assert "W131" in codes
```

- [ ] **Step 3: 跑测试看 fail**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v -k "when or var_reference"
```

Expected: 2 FAIL

- [ ] **Step 4: 实现 when 语法校验 + 变量引用提取**

加到 `workflow_loader.py`：

```python
import re

# $nodeId.output 或 $nodeId.output.field 或 $ENV_VAR
VAR_REF_RE = re.compile(
    r"\$(?P<node>[a-z][a-z0-9-]*)\.output(?:\.(?P<field>[a-zA-Z_][a-zA-Z0-9_]*))?"
)
ENV_VAR_RE = re.compile(r"\$([A-Z_][A-Z0-9_]*)")

# when 语法：$x.output[.field] OP 'literal' (&& / ||) ...
# 简化：用宽松正则验证整体形态
WHEN_TOKEN_RE = re.compile(
    r"""
    \s*
    (?:
        \$ [a-z][a-z0-9-]* \.output (?:\.[a-zA-Z_][a-zA-Z0-9_]*)?
      | '[^']*'
      | -? \d+ (?:\.\d+)?
      | true | false | null
    )
    \s*
    (?: == | != | <= | >= | < | > )?
    \s*
    """,
    re.VERBOSE,
)
WHEN_LOGIC_RE = re.compile(r"\s*(?:&&|\|\|)\s*")


def _validate_when_expression(expr: str) -> bool:
    """当前 when 语法支持：6 比较 + 2 逻辑 + 括号 + 字符串/数字/布尔字面量。

    简易解析：剥离括号后按 (term OP term) 分段（&& / || 分隔）。
    """
    if not expr or not expr.strip():
        return False
    # 去外层括号
    s = expr.strip()
    while s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    # 按 && / || 切，每段必须是合法的 (term OP term) 或单个 boolean term
    segments = re.split(r"\s*(?:&&|\|\|)\s*", s)
    for seg in segments:
        seg = seg.strip().lstrip("(").rstrip(")")
        if not seg:
            return False
        # 至少匹配 1 token；允许 2 token + 1 OP 形式
        if not WHEN_TOKEN_RE.match(seg):
            return False
    return True


def _collect_referenced_node_ids(text: str) -> set[str]:
    return {m.group("node") for m in VAR_REF_RE.finditer(text or "")}


def _validate_when_and_var_refs(
    workflow: dict[str, Any], report: Report, file_label: str
) -> None:
    nodes = workflow.get("nodes", [])
    all_ids = {n["id"] for n in nodes if "id" in n}

    def scan(text: str | None, owner: str, kind: str) -> None:
        if not text:
            return
        # 变量引用合法性
        for ref in _collect_referenced_node_ids(text):
            if ref not in all_ids:
                report.add(
                    file_label, Severity.ERROR, "W131",
                    f"节点 {owner} 的 {kind} 引用了不存在的节点 ${ref}.output",
                )

    for node in nodes:
        nid = node.get("id", "<unknown>")

        # when 语法校验
        when_expr = node.get("when")
        if when_expr is not None:
            if not _validate_when_expression(when_expr):
                report.add(
                    file_label, Severity.ERROR, "W130",
                    f"节点 {nid} 的 when 表达式语法错误: {when_expr!r}",
                )
            scan(when_expr, nid, "when")

        # 各类型节点的文本字段扫描
        for fld in ("prompt", "prompt_override", "bash"):
            scan(node.get(fld), nid, fld)
        # loop 内字段
        if "loop" in node:
            for lf in ("prompt", "until_bash", "gate_message"):
                scan(node["loop"].get(lf), nid, f"loop.{lf}")
        # approval 内字段
        if "approval" in node:
            scan(node["approval"].get("message"), nid, "approval.message")
            if "on_reject" in node["approval"]:
                scan(node["approval"]["on_reject"].get("prompt"), nid, "approval.on_reject.prompt")
        # args 字段（dict）值扫描
        for v in (node.get("args") or {}).values():
            if isinstance(v, str):
                scan(v, nid, "args")


# 在 load_workflow 里 DAG 校验之后追加：
_validate_when_and_var_refs(raw, result.report, file_label)
```

- [ ] **Step 5: 跑全部测试看 pass**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v
```

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/workflow_loader.py tests/lib/
git commit -m "feat(workflow): validate when expression syntax + var ref existence (W130/W131)"
```

---

## Task 8: prompt 与 prompt_file 互斥 + prompt_file 路径校验

**Files:**
- Modify: `scripts/lib/workflow_loader.py`
- Modify: `tests/lib/test_workflow_loader.py`
- Create: `tests/lib/fixtures/workflows/invalid-bad-prompt-file.yaml`

- [ ] **Step 1: 写 fixtures**

```yaml
# tests/lib/fixtures/workflows/invalid-bad-prompt-file.yaml
name: bad-prompt-file
version: 1
category: assist
nodes:
  - id: a
    prompt: "inline"
    prompt_file: prompts/nonexistent.md   # 互斥违反 + 文件不存在
```

```yaml
# tests/lib/fixtures/workflows/invalid-prompt-file-out-of-tree.yaml
name: out-of-tree
version: 1
category: assist
nodes:
  - id: a
    prompt_file: "../../etc/passwd"   # 越仓库
```

- [ ] **Step 2: 写测试**

```python
def test_prompt_and_prompt_file_are_mutually_exclusive():
    result = load_workflow(FIXTURES / "invalid-bad-prompt-file.yaml")
    codes = [c for _, _, c, _ in result.report.findings()]
    assert "W140" in codes


def test_prompt_file_path_must_be_inside_workflows_prompts_dir():
    result = load_workflow(FIXTURES / "invalid-prompt-file-out-of-tree.yaml")
    codes = [c for _, _, c, _ in result.report.findings()]
    assert "W141" in codes
```

- [ ] **Step 3: 跑测试看 fail**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v -k "prompt"
```

Expected: 2 FAIL

- [ ] **Step 4: 实现校验**

```python
WORKFLOWS_PROMPTS_DIR = REPO_ROOT / ".claude" / "workflows" / "prompts"


def _validate_prompt_files(workflow: dict[str, Any], report: Report, file_label: str) -> None:
    for node in workflow.get("nodes", []):
        nid = node.get("id", "<unknown>")
        # prompt 节点本身的检查
        if "prompt" in node and "prompt_file" in node:
            report.add(
                file_label, Severity.ERROR, "W140",
                f"节点 {nid} 同时配置了 prompt 与 prompt_file，必须互斥",
            )
        # 检查 loop.prompt 与 loop.prompt_file 互斥
        loop = node.get("loop") or {}
        if "prompt" in loop and "prompt_file" in loop:
            report.add(
                file_label, Severity.ERROR, "W140",
                f"节点 {nid} 的 loop.prompt 与 loop.prompt_file 互斥",
            )
        # prompt_file 路径校验
        for pf_owner, pf_value in [
            (f"{nid}.prompt_file", node.get("prompt_file")),
            (f"{nid}.loop.prompt_file", loop.get("prompt_file")),
        ]:
            if not pf_value:
                continue
            target = (WORKFLOWS_PROMPTS_DIR / pf_value.replace("prompts/", "", 1)).resolve()
            try:
                target.relative_to(WORKFLOWS_PROMPTS_DIR.resolve())
            except ValueError:
                report.add(
                    file_label, Severity.ERROR, "W141",
                    f"{pf_owner} = {pf_value!r} 必须指向 .claude/workflows/prompts/ 内",
                )
                continue
            if not target.exists():
                report.add(
                    file_label, Severity.ERROR, "W142",
                    f"{pf_owner} 引用的文件不存在: {pf_value}",
                )


# 在 load_workflow 里追加：
_validate_prompt_files(raw, result.report, file_label)
```

- [ ] **Step 5: 跑测试看 pass**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v
```

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/workflow_loader.py tests/lib/
git commit -m "feat(workflow): validate prompt/prompt_file mutex + path constraints (W140-142)"
```

---

## Task 9: sub_workflow 嵌套深度 ≤ 2 校验

**Files:**
- Modify: `scripts/lib/workflow_loader.py`
- Modify: `tests/lib/test_workflow_loader.py`
- Create: `tests/lib/fixtures/workflows/invalid-deep-nest.yaml`
- Create: `tests/lib/fixtures/workflows/sub-fixtures/level1.yaml`
- Create: `tests/lib/fixtures/workflows/sub-fixtures/level2.yaml`

- [ ] **Step 1: 写 fixtures（3 层嵌套：根→level1→level2）**

```yaml
# tests/lib/fixtures/workflows/invalid-deep-nest.yaml
name: deep-root
version: 1
category: assist
nodes:
  - id: call-l1
    sub_workflow: sub-fixtures/level1
```

```yaml
# tests/lib/fixtures/workflows/sub-fixtures/level1.yaml
name: deep-l1
version: 1
category: review
nodes:
  - id: call-l2
    sub_workflow: sub-fixtures/level2
```

```yaml
# tests/lib/fixtures/workflows/sub-fixtures/level2.yaml
name: deep-l2
version: 1
category: assist
nodes:
  - id: leaf
    bash: "echo leaf"
```

- [ ] **Step 2: 写测试**

```python
def test_sub_workflow_nesting_must_not_exceed_two_levels():
    result = load_workflow(FIXTURES / "invalid-deep-nest.yaml")
    codes = [c for _, _, c, _ in result.report.findings()]
    assert "W150" in codes


def test_sub_workflow_path_must_resolve():
    """sub_workflow: nonexistent → 报 W151"""
    fixture = FIXTURES / "invalid-bad-subref.yaml"
    fixture.write_text(
        "name: bad-sub\nversion: 1\ncategory: assist\nnodes:\n"
        "  - id: x\n    sub_workflow: nonexistent/missing\n"
    )
    try:
        result = load_workflow(fixture)
        codes = [c for _, _, c, _ in result.report.findings()]
        assert "W151" in codes
    finally:
        fixture.unlink()
```

- [ ] **Step 3: 跑测试看 fail**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v -k "sub_workflow"
```

Expected: 2 FAIL

- [ ] **Step 4: 实现嵌套深度校验**

```python
WORKFLOWS_ROOT = REPO_ROOT / ".claude" / "workflows"
MAX_SUB_WORKFLOW_DEPTH = 2


def _resolve_sub_workflow_path(ref: str, search_root: Path) -> Path | None:
    """支持相对路径与省略 .yaml 后缀。"""
    candidates = [
        search_root / f"{ref}.yaml",
        search_root / ref,
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _validate_sub_workflow_depth(
    workflow: dict[str, Any],
    report: Report,
    file_label: str,
    search_root: Path,
    depth: int = 1,
    visited: set[Path] | None = None,
) -> None:
    """递归加载子 workflow，校验嵌套深度 ≤ MAX_SUB_WORKFLOW_DEPTH。"""
    if visited is None:
        visited = set()

    for node in workflow.get("nodes", []):
        sub_ref = node.get("sub_workflow")
        if not sub_ref:
            continue
        sub_path = _resolve_sub_workflow_path(sub_ref, search_root)
        if sub_path is None:
            report.add(
                file_label, Severity.ERROR, "W151",
                f"节点 {node.get('id')} 的 sub_workflow '{sub_ref}' 未找到（搜索 {search_root}）",
            )
            continue
        if depth >= MAX_SUB_WORKFLOW_DEPTH:
            report.add(
                file_label, Severity.ERROR, "W150",
                f"节点 {node.get('id')} 嵌套子 workflow 超过最大深度 {MAX_SUB_WORKFLOW_DEPTH}",
            )
            continue
        if sub_path in visited:  # 防递归引用
            report.add(
                file_label, Severity.ERROR, "W152",
                f"节点 {node.get('id')} 出现 sub_workflow 循环引用: {sub_path}",
            )
            continue
        visited.add(sub_path)
        try:
            with sub_path.open("r", encoding="utf-8") as f:
                sub_yaml = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            report.add(
                file_label, Severity.ERROR, "W153",
                f"嵌套 sub_workflow {sub_path} 解析失败: {exc}",
            )
            continue
        if isinstance(sub_yaml, dict):
            _validate_sub_workflow_depth(
                sub_yaml, report, file_label, search_root, depth + 1, visited
            )


# load_workflow 内调用，search_root 取 yaml 文件所在目录的"workflows 根"
def _infer_workflows_search_root(yaml_path: Path) -> Path:
    """yaml 在 .claude/workflows/<sub>/<file>.yaml 时，根 = .claude/workflows/。
    fixtures 则用 fixtures 自身目录。"""
    parts = yaml_path.resolve().parts
    if "workflows" in parts:
        idx = parts.index("workflows")
        return Path(*parts[: idx + 1])
    return yaml_path.parent


# 在 load_workflow 内追加：
search_root = _infer_workflows_search_root(path)
_validate_sub_workflow_depth(raw, result.report, file_label, search_root)
```

- [ ] **Step 5: 跑测试看 pass**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v
```

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/workflow_loader.py tests/lib/
git commit -m "feat(workflow): validate sub_workflow nesting depth ≤ 2 (W150-153)"
```

---

## Task 10: 三层模板发现 + 同名覆盖

**Files:**
- Modify: `scripts/lib/workflow_loader.py`
- Modify: `tests/lib/test_workflow_loader.py`

- [ ] **Step 1: 写测试**

```python
def test_discover_workflows_loads_from_three_layers(tmp_path, monkeypatch):
    """三层加载顺序：bundled → ~/.claude/workflows → .claude/workflows，后覆盖前。"""
    from workflow_loader import discover_workflows

    bundled = tmp_path / "bundled"
    home = tmp_path / "home" / ".claude" / "workflows"
    project = tmp_path / "project" / ".claude" / "workflows"
    for d in [bundled, home, project]:
        d.mkdir(parents=True)

    # bundled / wf-a 与 wf-b
    (bundled / "wf-a.yaml").write_text(
        "name: wf-a\nversion: 1\ncategory: assist\nnodes:\n  - id: x\n    bash: 'echo bundled-a'\n"
    )
    (bundled / "wf-b.yaml").write_text(
        "name: wf-b\nversion: 1\ncategory: assist\nnodes:\n  - id: x\n    bash: 'echo bundled-b'\n"
    )
    # home 覆盖 wf-a
    (home / "wf-a.yaml").write_text(
        "name: wf-a\nversion: 1\ncategory: assist\nnodes:\n  - id: x\n    bash: 'echo home-a'\n"
    )
    # project 覆盖 wf-b
    (project / "wf-b.yaml").write_text(
        "name: wf-b\nversion: 1\ncategory: assist\nnodes:\n  - id: x\n    bash: 'echo project-b'\n"
    )

    discovered = discover_workflows(
        bundled_dir=bundled,
        home_dir=home,
        project_dir=project,
    )
    assert "wf-a" in discovered
    assert "wf-b" in discovered
    assert discovered["wf-a"].source == "home"
    assert discovered["wf-a"].workflow["nodes"][0]["bash"] == "echo home-a"
    assert discovered["wf-b"].source == "project"
    assert discovered["wf-b"].workflow["nodes"][0]["bash"] == "echo project-b"
```

- [ ] **Step 2: 跑测试看 fail**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v -k "three_layers"
```

Expected: FAIL（discover_workflows 不存在）

- [ ] **Step 3: 实现 `discover_workflows`**

```python
@dataclass
class DiscoveredWorkflow:
    name: str
    workflow: dict[str, Any]
    source: str  # "bundled" | "home" | "project"
    source_path: Path


def discover_workflows(
    bundled_dir: Path | None = None,
    home_dir: Path | None = None,
    project_dir: Path | None = None,
) -> dict[str, DiscoveredWorkflow]:
    """三层模板发现。后者覆盖前者（同名静默 override，对应 design doc §5.2）。"""
    if bundled_dir is None:
        bundled_dir = REPO_ROOT / ".claude" / "workflows" / "bundled"
    if home_dir is None:
        home_dir = Path.home() / ".claude" / "workflows"
    if project_dir is None:
        project_dir = REPO_ROOT / ".claude" / "workflows"

    discovered: dict[str, DiscoveredWorkflow] = {}

    def scan(directory: Path, source: str) -> None:
        if not directory.exists():
            return
        for yaml_path in directory.rglob("*.yaml"):
            # 跳过 bundled/ 下还放在子目录的（避免重复扫）
            if source == "project" and yaml_path.is_relative_to(bundled_dir):
                continue
            if source == "project" and yaml_path.parent.name == "prompts":
                continue
            result = load_workflow(yaml_path)
            if result.report.errors or result.workflow is None:
                continue
            name = result.workflow["name"]
            discovered[name] = DiscoveredWorkflow(
                name=name,
                workflow=result.workflow,
                source=source,
                source_path=yaml_path,
            )

    scan(bundled_dir, "bundled")
    scan(home_dir, "home")
    scan(project_dir, "project")
    return discovered
```

- [ ] **Step 4: 跑测试看 pass**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v -k "three_layers"
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/workflow_loader.py tests/lib/
git commit -m "feat(workflow): discover_workflows() three-layer load with override semantics"
```

---

## Task 11: 默认值补全表

**Files:**
- Modify: `scripts/lib/workflow_loader.py`
- Modify: `tests/lib/test_workflow_loader.py`

- [ ] **Step 1: 写测试**

```python
def test_defaults_applied_when_optional_fields_missing():
    """node 不写 trigger_rule / retry / idle_timeout 时，loader 自动填默认值。"""
    fixture = FIXTURES / "valid-defaults.yaml"
    fixture.write_text(
        "name: defaults\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: sonnet\n"
        "nodes:\n  - id: a\n    bash: 'echo'\n"
    )
    try:
        result = load_workflow(fixture)
        assert result.report.errors == 0
        node = result.workflow["nodes"][0]
        assert node["trigger_rule"] == "all_success"
        assert node["retry"]["max_attempts"] == 2
        assert node["retry"]["delay_ms"] == 3000
        assert node["retry"]["on_error"] == "transient"
        assert node["idle_timeout"] == 60000  # bash 节点
    finally:
        fixture.unlink()


def test_node_inherits_workflow_level_provider_and_model():
    fixture = FIXTURES / "valid-inherit.yaml"
    fixture.write_text(
        "name: inherit\nversion: 1\ncategory: assist\n"
        "provider: claude\nmodel: opus\neffort: high\n"
        "nodes:\n  - id: a\n    bash: 'echo'\n"
    )
    try:
        result = load_workflow(fixture)
        node = result.workflow["nodes"][0]
        assert node["provider"] == "claude"
        assert node["model"] == "opus"
        assert node["effort"] == "high"
    finally:
        fixture.unlink()
```

- [ ] **Step 2: 跑测试看 fail**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v -k "defaults or inherit"
```

Expected: 2 FAIL

- [ ] **Step 3: 实现默认值补全**

```python
DEFAULT_RETRY = {"max_attempts": 2, "delay_ms": 3000, "on_error": "transient"}
DEFAULT_TRIGGER_RULE = "all_success"
NODE_TYPE_DEFAULT_TIMEOUT_MS = {
    "skill": 300_000,
    "agent": 300_000,
    "prompt": 300_000,
    "bash": 60_000,
    "loop": 300_000,
    "approval": 86_400_000,        # 24h（用户响应可能慢）
    "artifact": 30_000,
    "sub_workflow": 1_800_000,     # 30min
}


def _infer_node_type(node: dict[str, Any]) -> str | None:
    for f in NODE_TYPE_FIELDS:
        if f in node:
            return f
    return None


def _apply_defaults(workflow: dict[str, Any]) -> None:
    """补全缺省字段。直接 mutate workflow（in-place）。"""
    wf_provider = workflow.get("provider", "claude")
    wf_model = workflow.get("model")
    wf_effort = workflow.get("effort")
    wf_thinking = workflow.get("thinking")

    for node in workflow.get("nodes", []):
        node.setdefault("trigger_rule", DEFAULT_TRIGGER_RULE)
        node.setdefault("retry", dict(DEFAULT_RETRY))
        # retry 字段补全（部分提供）
        retry = node["retry"]
        for k, v in DEFAULT_RETRY.items():
            retry.setdefault(k, v)
        # provider / model / effort / thinking 继承
        node.setdefault("provider", wf_provider)
        if wf_model:
            node.setdefault("model", wf_model)
        if wf_effort:
            node.setdefault("effort", wf_effort)
        if wf_thinking:
            node.setdefault("thinking", wf_thinking)
        # idle_timeout 按节点类型默认
        nt = _infer_node_type(node)
        if nt and "idle_timeout" not in node:
            node["idle_timeout"] = NODE_TYPE_DEFAULT_TIMEOUT_MS[nt]


# 在 load_workflow 末尾、result.workflow = raw 之前调用：
if not result.report.errors:
    _apply_defaults(raw)
```

- [ ] **Step 4: 跑测试看 pass**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py -v
```

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/workflow_loader.py tests/lib/
git commit -m "feat(workflow): apply default values for trigger_rule/retry/idle_timeout/inheritance"
```

---

## Task 12: substitute_vars.py 基础变量替换

**Files:**
- Create: `scripts/lib/substitute_vars.py`
- Create: `tests/lib/test_substitute_vars.py`

- [ ] **Step 1: 写测试**

```python
# tests/lib/test_substitute_vars.py
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from substitute_vars import substitute_vars  # noqa: E402


def test_should_substitute_node_output_string():
    node_outputs = {"a": {"output": "hello"}}
    assert substitute_vars("$a.output", node_outputs, env={}) == "hello"


def test_should_substitute_node_output_field():
    node_outputs = {"gate": {"output": '{"verdict": "approved"}'}}
    assert substitute_vars("$gate.output.verdict", node_outputs, env={}) == "approved"


def test_should_substitute_env_variable():
    env = {"RUN_ID": "REQ-2026-001"}
    assert substitute_vars("$RUN_ID/foo", node_outputs={}, env=env) == "REQ-2026-001/foo"


def test_should_return_empty_string_when_node_missing():
    assert substitute_vars("$missing.output", node_outputs={}, env={}) == ""


def test_should_return_empty_string_when_field_not_in_json():
    node_outputs = {"x": {"output": '{"a": 1}'}}
    assert substitute_vars("$x.output.b", node_outputs, env={}) == ""


def test_should_handle_non_json_output_for_field_access():
    node_outputs = {"x": {"output": "plain text"}}
    assert substitute_vars("$x.output.field", node_outputs, env={}) == ""


def test_should_preserve_non_var_text():
    node_outputs = {"a": {"output": "X"}}
    assert substitute_vars("before $a.output after", node_outputs, env={}) == "before X after"
```

- [ ] **Step 2: 跑测试看 fail**

```bash
python3 -m pytest tests/lib/test_substitute_vars.py -v
```

Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `substitute_vars.py`**

```python
# scripts/lib/substitute_vars.py
"""变量替换库：把 $nodeId.output[.field] 与 $ENV_VAR 替换为运行时值。

变量语法：
  $nodeId.output         上游节点完整 stdout
  $nodeId.output.field   上游 stdout 解析为 JSON 后的字段
  $ENV_VAR               环境变量（含 $RUN_ID / $ARTIFACTS_DIR / $REPO_ROOT 等）

转义模式（escape_for_bash=True）：
  string/num/bool → 单引号 + '\\'' 转义
  array/object    → JSON 序列化后单引号
  null            → 空字符串
"""
from __future__ import annotations

import json
import re
from typing import Any

VAR_REF_RE = re.compile(
    r"\$(?P<node>[a-z][a-z0-9-]*)\.output(?:\.(?P<field>[a-zA-Z_][a-zA-Z0-9_]*))?"
)
ENV_VAR_RE = re.compile(r"\$([A-Z_][A-Z0-9_]*)")


def shell_quote(value: str) -> str:
    """单引号包裹，内部 ' 转为 '\\''."""
    return "'" + value.replace("'", "'\\''") + "'"


def _serialize_for_substitution(value: Any, escape_for_bash: bool) -> str:
    """节点 output 值序列化策略。"""
    if value is None:
        return shell_quote("") if escape_for_bash else ""
    if isinstance(value, str):
        return shell_quote(value) if escape_for_bash else value
    if isinstance(value, bool):
        s = "true" if value else "false"
        return shell_quote(s) if escape_for_bash else s
    if isinstance(value, (int, float)):
        s = str(value)
        return shell_quote(s) if escape_for_bash else s
    if isinstance(value, (list, dict)):
        s = json.dumps(value, ensure_ascii=False)
        return shell_quote(s) if escape_for_bash else s
    s = str(value)
    return shell_quote(s) if escape_for_bash else s


def substitute_vars(
    text: str,
    node_outputs: dict[str, dict[str, Any]],
    env: dict[str, str],
    escape_for_bash: bool = False,
) -> str:
    """替换文本中的所有 $nodeId.output[.field] / $ENV_VAR。

    node_outputs 形态：{"a": {"output": "..."}, "b": {"output": '{"x": 1}'}, ...}
    env 形态：{"RUN_ID": "...", "ARTIFACTS_DIR": "..."}
    """
    if not text:
        return text or ""

    def replace_node_ref(m: re.Match[str]) -> str:
        node_id = m.group("node")
        field = m.group("field")
        node = node_outputs.get(node_id)
        if node is None:
            return shell_quote("") if escape_for_bash else ""
        output_str = node.get("output", "")
        if field is None:
            # 整体 output（字符串）
            return shell_quote(output_str) if escape_for_bash else output_str
        # 字段提取需要 JSON 解析
        try:
            parsed = json.loads(output_str)
        except (json.JSONDecodeError, TypeError):
            return shell_quote("") if escape_for_bash else ""
        if not isinstance(parsed, dict):
            return shell_quote("") if escape_for_bash else ""
        if field not in parsed:
            return shell_quote("") if escape_for_bash else ""
        return _serialize_for_substitution(parsed[field], escape_for_bash)

    def replace_env(m: re.Match[str]) -> str:
        name = m.group(1)
        value = env.get(name, "")
        return shell_quote(value) if escape_for_bash else value

    # 先处理节点引用（更具体的 pattern），再处理环境变量
    result = VAR_REF_RE.sub(replace_node_ref, text)
    result = ENV_VAR_RE.sub(replace_env, result)
    return result
```

- [ ] **Step 4: 跑测试看 pass**

```bash
python3 -m pytest tests/lib/test_substitute_vars.py -v
```

Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/substitute_vars.py tests/lib/test_substitute_vars.py
git commit -m "feat(workflow): substitute_vars supports node_output + env_var, with field extraction"
```

---

## Task 13: substitute_vars 转义模式（bash 安全）

**Files:**
- Modify: `tests/lib/test_substitute_vars.py`

- [ ] **Step 1: 写测试**

```python
def test_should_escape_string_with_single_quotes_when_bash():
    node_outputs = {"a": {"output": "hello; rm -rf /"}}
    assert substitute_vars("$a.output", node_outputs, env={}, escape_for_bash=True) == "'hello; rm -rf /'"


def test_should_escape_internal_single_quote():
    node_outputs = {"a": {"output": "it's a test"}}
    result = substitute_vars("$a.output", node_outputs, env={}, escape_for_bash=True)
    assert result == "'it'\\''s a test'"


def test_should_serialize_array_field_to_json_when_bash():
    node_outputs = {"a": {"output": '{"modules": ["pay", "order"]}'}}
    result = substitute_vars(
        "$a.output.modules", node_outputs, env={}, escape_for_bash=True
    )
    assert result == "'[\"pay\", \"order\"]'"


def test_should_serialize_object_field_to_json_when_bash():
    node_outputs = {"a": {"output": '{"meta": {"k": "v"}}'}}
    result = substitute_vars(
        "$a.output.meta", node_outputs, env={}, escape_for_bash=True
    )
    assert result == "'{\"k\": \"v\"}'"


def test_should_handle_null_field_as_empty_quoted_string():
    node_outputs = {"a": {"output": '{"x": null}'}}
    result = substitute_vars(
        "$a.output.x", node_outputs, env={}, escape_for_bash=True
    )
    assert result == "''"


def test_should_escape_env_var_in_bash_mode():
    env = {"RUN_ID": "REQ; touch /tmp/hack"}
    result = substitute_vars("$RUN_ID", node_outputs={}, env=env, escape_for_bash=True)
    assert result == "'REQ; touch /tmp/hack'"
```

- [ ] **Step 2: 跑测试**

```bash
python3 -m pytest tests/lib/test_substitute_vars.py -v
```

Expected: 上面 6 个新测试 PASS（实现已经在 Task 12 一并写好）。如有 fail，调整 `_serialize_for_substitution`。

- [ ] **Step 3: Commit**

```bash
git add tests/lib/test_substitute_vars.py
git commit -m "test(workflow): cover bash-escape mode for substitute_vars (string/array/object/null)"
```

---

## Task 14: loader CLI 入口（独立可调用）

**Files:**
- Modify: `scripts/lib/workflow_loader.py`
- Create: `tests/lib/test_workflow_loader_cli.py`

- [ ] **Step 1: 写 CLI 测试**

```python
# tests/lib/test_workflow_loader_cli.py
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_cli_returns_zero_for_valid_workflow():
    result = subprocess.run(
        ["python3", "scripts/lib/workflow_loader.py",
         "tests/lib/fixtures/workflows/valid-minimal.yaml"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_cli_returns_one_for_invalid_workflow():
    result = subprocess.run(
        ["python3", "scripts/lib/workflow_loader.py",
         "tests/lib/fixtures/workflows/invalid-mutex.yaml"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "W110" in result.stdout or "W110" in result.stderr


def test_cli_returns_two_for_missing_file(tmp_path):
    result = subprocess.run(
        ["python3", "scripts/lib/workflow_loader.py", str(tmp_path / "nope.yaml")],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode in (1, 2)
```

- [ ] **Step 2: 跑测试看 fail**

```bash
python3 -m pytest tests/lib/test_workflow_loader_cli.py -v
```

Expected: FAIL（CLI 入口不存在）

- [ ] **Step 3: 加 CLI 入口到 `workflow_loader.py`**

文件末尾追加：

```python
def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Validate a workflow yaml.")
    parser.add_argument("path", help="path to workflow yaml")
    parser.add_argument("--strict", action="store_true", help="warning 视为失败")
    parser.add_argument("--quiet", action="store_true", help="无错误时静默")
    args = parser.parse_args()

    target = Path(args.path)
    result = load_workflow(target)
    if not args.quiet or result.report.errors > 0:
        print(result.report.render())
    return result.report.exit_code(args.strict)


if __name__ == "__main__":
    sys.exit(main())
```

文件顶部加 `import sys`。

- [ ] **Step 4: 跑测试看 pass**

```bash
python3 -m pytest tests/lib/test_workflow_loader_cli.py -v
```

Expected: 3 PASS

- [ ] **Step 5: 手动验证 CLI 体验**

```bash
python3 scripts/lib/workflow_loader.py tests/lib/fixtures/workflows/valid-minimal.yaml
echo "exit=$?"
# Expected: ✓ 无问题 / exit=0

python3 scripts/lib/workflow_loader.py tests/lib/fixtures/workflows/invalid-mutex.yaml
echo "exit=$?"
# Expected: 错误信息含 W110 / exit=1
```

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/workflow_loader.py tests/lib/test_workflow_loader_cli.py
git commit -m "feat(workflow): add CLI entry to workflow_loader (exit codes per common.py)"
```

---

## Task 15: 验证 Plan 1 完整性 — 跑既有完整 yaml

**Files:**
- 验证 `.claude/workflows/requirement/standard-8phase.yaml`（已在 spec 阶段写完）能通过 loader

- [ ] **Step 1: 跑 standard-8phase.yaml 通过 loader**

```bash
python3 scripts/lib/workflow_loader.py .claude/workflows/requirement/standard-8phase.yaml
```

Expected: 输出可能含若干校验 warning/error（因 prompt_file 引用的 prompts/req-quality-review.md 等可能未写完整），但**不应有 W001/W100/W110/W120 这类 schema 级错误**。

- [ ] **Step 2: 修复 standard-8phase.yaml 中 loader 暴露的真问题**

如果 loader 报：
- `W141: prompt_file 必须指向 .claude/workflows/prompts/ 内` → 检查 yaml 里 prompt_file 路径
- `W142: prompt_file 引用的文件不存在` → 创建占位 prompts/*.md 文件（最简单：`echo "# placeholder" > .claude/workflows/prompts/<name>.md`）
- `W131: 引用了不存在的节点` → 检查 yaml 节点 ID 拼写

**任何 W100 schema 错都必须修——它代表 yaml 不符合 schema。**

修复后再跑一遍：

```bash
python3 scripts/lib/workflow_loader.py --strict .claude/workflows/requirement/standard-8phase.yaml
echo "exit=$?"
# Expected: exit=0
```

- [ ] **Step 3: 写集成测试 `test_load_real_standard_8phase`**

```python
# 加到 tests/lib/test_workflow_loader.py 末尾

def test_load_real_standard_8phase_yaml():
    """spec 阶段写的 standard-8phase.yaml 必须能被 Plan 1 的 loader 接受。"""
    target = REPO_ROOT / ".claude" / "workflows" / "requirement" / "standard-8phase.yaml"
    if not target.exists():
        pytest.skip("standard-8phase.yaml 未就绪")
    result = load_workflow(target)
    if result.report.errors:
        print(result.report.render())
    assert result.report.errors == 0
    assert result.workflow["name"] == "standard-8phase"
    assert result.workflow["category"] == "requirement"
    assert len(result.workflow["nodes"]) >= 30
```

- [ ] **Step 4: 跑测试**

```bash
python3 -m pytest tests/lib/test_workflow_loader.py::test_load_real_standard_8phase_yaml -v
```

Expected: PASS

- [ ] **Step 5: 跑全套测试 + lint**

```bash
python3 -m pytest tests/lib/ -v
ruff check scripts/lib/workflow_loader.py scripts/lib/substitute_vars.py scripts/lib/topological_sort.py
```

Expected: 全部 PASS / lint 0 errors

- [ ] **Step 6: Commit + Plan 1 完成标记**

```bash
git add tests/lib/test_workflow_loader.py .claude/workflows/
git commit -m "test(workflow): integration test loading real standard-8phase.yaml

Plan 1 (schema + loader) complete. 全部 14 任务通过。
- workflow_loader.py: yaml 解析 + JSON Schema 校验 + 节点互斥
  + DAG 校验 + when 语法 + 变量引用 + prompt_file + sub_workflow
  嵌套深度 + 三层发现 + 默认值补全
- substitute_vars.py: \$nodeId.output / \$ENV_VAR + bash 转义
- topological_sort.py: Kahn 算法
- 验证 standard-8phase.yaml 能被加载

下一步：Plan 2 (engine core)
"
```

---

## Plan 1 完成验收

跑这些命令应该全部成功：

```bash
# 1. 全部测试通过
python3 -m pytest tests/lib/test_workflow_loader.py tests/lib/test_substitute_vars.py tests/lib/test_topological_sort.py -v

# 2. CLI 验证 standard-8phase.yaml
python3 scripts/lib/workflow_loader.py --strict .claude/workflows/requirement/standard-8phase.yaml

# 3. CLI 拒绝坏 yaml
python3 scripts/lib/workflow_loader.py tests/lib/fixtures/workflows/invalid-mutex.yaml
# 退出码非零

# 4. lint
ruff check scripts/lib/workflow_loader.py scripts/lib/substitute_vars.py scripts/lib/topological_sort.py
# 0 errors
```

**Plan 1 交付物**：
- 3 个 Python 模块（workflow_loader / substitute_vars / topological_sort）
- 14 类校验错误码（W001 / W100 / W110-112 / W120-121 / W130-131 / W140-142 / W150-153）
- 三层模板发现 + 默认值补全
- 16 项 yaml fixture 覆盖正反场景
- 集成测试通过 standard-8phase.yaml
- CLI 入口（python3 scripts/lib/workflow_loader.py）

**Plan 1 不交付**（留给 Plan 2-4）：
- 节点执行（任何 skill/agent/prompt/bash/loop/approval/artifact/sub_workflow 节点跑起来）
- run-state.jsonl 读写
- managing-workflow-runs Skill
- workflow-engine Skill
- /workflow:* 命令
- 实际 workflow 跑通

---

## 后续 Plan

完成 Plan 1 后另起：

- **Plan 2**: workflow-engine Skill 实现（节点执行 + run-state.jsonl + RunState 重建 + approval 状态机 + loop + sub_workflow 父子联动）
- **Plan 3**: /workflow:* 11 个命令 + managing-workflow-runs 伞形 Skill + workflow-launcher 自然语言 Skill + code-review-embedded.yaml 完整化
- **Plan 4**: 自举验证 + 旧代码清理（PHASE_REQUIREMENTS / phase_enum / code_review_signoff / /requirement:next / 文档批量更新）

---

## Plan 1 Self-Review

按 writing-plans skill self-review checklist：

**1. Spec 覆盖**：
- ✅ §6.1 顶层字段（name/version/category/provider/...） — Task 1+3
- ✅ §6.2 8 种节点类型互斥 — Task 4
- ✅ §6.3 节点公共字段 schema — Task 1
- ✅ §6.4 各节点字段（含 sub_workflow） — Task 1（schema 层）
- ✅ §6.5 变量替换 + 转义 — Task 12+13
- ✅ §6.6 when 表达式语法 + 已知限制 — Task 7
- ✅ §6.7 trigger_rule schema 校验 — Task 1
- ✅ §6.8 失败传播 — 不在 Plan 1（属于执行期，归 Plan 2）
- ✅ §6.9 retry — Task 1+11
- ✅ §6.10 idle_timeout 默认 — Task 11
- ✅ §6.11 输出阈值 — 不在 Plan 1（执行期）
- ✅ §6.12 depends_on 缺省 — Task 6
- ✅ §6.13 默认值补全表 — Task 11
- ✅ §6.14 loader 强校验 10 项 — Task 2-9 全覆盖
- ✅ §5.2 三层模板发现 — Task 10

**2. Placeholder 扫描**：
- 无 "TBD" / "TODO" / "implement later"
- 所有测试代码完整
- 所有实现代码完整
- 错误码（W001-W153）每个都给了具体含义

**3. 类型一致性**：
- `LoadResult` / `Report` / `DiscoveredWorkflow` 命名贯穿
- `topological_layers` / `CycleError` / `substitute_vars` / `shell_quote` 在测试和实现中名字一致
- `node_outputs` 字典结构 `{node_id: {"output": str}}` 在 Task 12 / 13 一致

**4. 模糊性检查**：
- depends_on 缺省语义：Task 6 明示"取上一节点 id（首节点为空数组）"
- prompt_file 路径范围：Task 8 明示"必须在 .claude/workflows/prompts/ 内"
- sub_workflow 深度：Task 9 明示"≤ 2"
- 节点输出 JSON 解析失败 → 字段提取返回空字符串：Task 12 测试覆盖

✅ 通过。
