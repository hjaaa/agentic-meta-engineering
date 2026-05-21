# Python 模块级路径常量阻碍测试 fixture 注入

**沉淀原因**：跨需求会重复（A）+ AI 反复错（B）+ 跨会话需保留（C）

## 问题

20260519-context-usage-report 期间复发 Bug-19：

```python
# scripts/lib/workflow_loader.py
WORKFLOWS_PROMPTS_DIR = REPO_ROOT / ".claude" / "workflows" / "prompts"

def _resolve_prompt_file(pf_value: str) -> Path:
    cleaned = pf_value
    if cleaned.startswith("prompts/"):
        cleaned = cleaned[len("prompts/"):]
    return (WORKFLOWS_PROMPTS_DIR / cleaned).resolve()
```

测试 `tests/skills/test_workflow_dispatcher_bash_skill_prompt.py::test_prompt_node_prompt_file_reads_and_renders` 用 `tmp_path / "prompts" / "test.md"` 注入，但 `_resolve_prompt_file` 仍解析到真实仓库根的 `.claude/workflows/prompts/test.md` → `FileNotFoundError`。

调用方 `_dispatch_prompt_node` 持有 `root: Path` 参数（已经是测试可注入的根），但**没透传给 `_resolve_prompt_file`** —— typical "API 签名缺失"，且单元测试**无路绕过**（除非 monkeypatch 模块级常量，但这破坏黑盒测试边界）。

## 根因

`WORKFLOWS_PROMPTS_DIR = REPO_ROOT / ...` 在模块 `import` 时求值并固化为绝对路径，**模块全生命周期不可变**。Python 单元测试要注入临时路径，只能 `monkeypatch.setattr(module, "WORKFLOWS_PROMPTS_DIR", tmp_path)`——这种做法：

1. 破坏黑盒边界（测试需要知道实现细节）
2. 与"显式优于隐式"原则相违（参数 vs monkeypatch）
3. 多线程 / 多 fixture 并发时易出竞态

模块级常量是 Python 常见的"看似简洁但暗藏"反模式：写出来代码短一行，但测试边界 + 多实例使用场景全卡死。

## 解法

**修法**（已落到本期 Fix）：

```python
def _resolve_prompt_file(pf_value: str, repo_root: Optional[Path] = None) -> Path:
    if repo_root is not None:
        # 注入模式：直接相对 repo_root 解析
        return (repo_root / pf_value).resolve()
    # 生产模式：剥离 "prompts/" 前缀以兼容两种写法
    cleaned = pf_value
    if cleaned.startswith("prompts/"):
        cleaned = cleaned[len("prompts/"):]
    return (WORKFLOWS_PROMPTS_DIR / cleaned).resolve()
```

调用方透传 `root`：

```python
prompt_path = _resolve_prompt_file(node["prompt_file"], repo_root=root)
```

**通用模式**：

- 模块级路径常量保留（生产场景便利），但**所有暴露 API 必须接收 `repo_root: Path | None = None` 可选参数**
- `repo_root=None` 时回退到模块级常量（向后兼容）
- 测试 fixture 显式传 `repo_root=tmp_path`

也可考虑更进一步——**模块级路径完全函数化**：

```python
def _workflows_prompts_dir(root: Path | None = None) -> Path:
    return (root or REPO_ROOT) / ".claude" / "workflows" / "prompts"
```

代价是改动面大；本期采"加可选参数"轻量修法。

## 反模式信号

代码评审时遇到以下模式 → 考虑加 `repo_root` 参数：

- 模块顶部 `_CONST_DIR = REPO_ROOT / "..."` / `_CONFIG = json.loads(open(REPO_ROOT / "config.json").read())`
- 函数体直接引用模块级 path 常量
- 单元测试用 `monkeypatch.setattr(module, "_CONST_DIR", tmp_path)` 而不是函数参数注入

## 验证方法

- `tests/skills/test_workflow_dispatcher_bash_skill_prompt.py::test_prompt_node_prompt_file_reads_and_renders`——fixture 写 `tmp_path / "prompts" / "test.md"`，调 `_dispatch_prompt_node(root=tmp_path)`，断言 `node_ready` 写出且含 prompt 文本
- 同 module 旧调用（`repo_root=None` 默认）不应改变生产行为

## 引用来源

- `requirements/20260519-context-usage-report/notes.md` Bug-19
- PR #84 commit `6898733`（_resolve_prompt_file 加 repo_root 参数）
- 关联经验：
  - `cli-explicit-input-normalize-fail-fast.md`（同款"显式优于隐式"原则在 CLI 入口的版本）
  - `cross-language-pipeline-path-anchor.md`（同款路径锚定漂移，跨语言版）
