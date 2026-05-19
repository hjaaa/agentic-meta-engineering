# CLI 显式输入必须在入口 normalize + fail-fast

**沉淀原因**：满足「跨需求复用 / AI 反复错」两条。

## 问题

`workflow_run._run_requirement` 处理 `--slug` 参数时直接使用 `args.slug`：

```python
slug = args.slug or requirement_naming.derive_slug_from_title(title)
```

`derive_slug_from_title()` 内部用 regex 自动过滤非法字符，但用户**显式输入**路径完全跳过校验。`--slug "FEAT/BAD"` 会一路传到：

1. `generate_requirement_key(date, "FEAT/BAD")` → req_id = `20260518-FEAT/BAD`
2. `feat/req-20260518-FEAT/BAD` 分支名
3. `git checkout -b` → git 报 "invalid reference"

错误信息对用户不友好，且 rollback 成本高（worktree 已部分创建）。

## 根因

CLI 入口的输入校验责任分两路：

- **派生路径**（`derive_slug_from_title`）：内置 regex 过滤，永远返合法值或 None；
- **显式路径**（`args.slug` 直传）：跳过校验，假设用户输入合法。

派生路径合规、显式路径不合规——这是常见漏洞：「我已经在派生路径做了校验，显式路径用户自己负责」。但用户**永远不应该被信任为合法 normalizer**。

下游函数（`generate_requirement_key`、`_bootstrap_requirement`）通常假设输入已经 normalized，导致非法字符传到 git/subprocess 层才 fail，错误信息无法回溯到根因。

## 解法

**所有 CLI 显式输入必须在入口处经过 normalize + fail-fast**：

```python
if args.slug:
    try:
        slug = requirement_naming.normalize_slug(args.slug)
    except requirement_naming.SlugError as exc:
        print(
            f"ERROR: --slug 校验失败：{exc}\n"
            "  合法 slug 字符集：a-z 0-9 - （连字符），长度 ≤ 64",
            file=sys.stderr,
        )
        return 1
else:
    slug = requirement_naming.derive_slug_from_title(title)
```

**设计原则**：

- normalize 可以**自动规范化**（空格→连字符、大写→小写、下划线→连字符）——这些是用户友好的预处理；
- normalize 必须**拒绝**规范化后仍非法的输入（非 ASCII / 特殊字符 / 全连字符 / 超长）；
- 下游函数文档/类型注解明确「假设输入已 normalized」，单元测试覆盖 normalize 各类边界。

## 验证方法

- 参数化测试覆盖各类非法输入：`@pytest.mark.parametrize("bad_slug, expected_substring", [...])`（参考 `tests/lib/test_workflow_run_worktree_args.py::test_run_requirement_explicit_slug_invalid_fails_fast`）。
- 错误信息断言含「`--slug`」字样（用户能定位到是哪个参数错），不能是 git 层的 generic error。
- code review 时 grep `args\.\w+` / `parser.add_argument` 入口，确认每个用户输入参数都过了 normalize 或显式类型 cast。

## 关联

- PR #80 commit `6d5a441`（codex P2 F-2 fix）
- `scripts/lib/requirement_naming.py:normalize_slug` / `SlugError`
- `scripts/lib/workflow_run.py:_run_requirement`
