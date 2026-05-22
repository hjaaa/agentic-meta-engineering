# plan.md 不包含段必用缩进子条目，不能写 inline

**沉淀原因**：跨需求 · AI 反复错 · 跨会话

## 问题

CI quality-check 跑 `python3 scripts/gates/run.py --trigger=ci --strict`，`--strict` 把 W003 从 warning 升 error 拦 PR。bootstrap 模板默认 inline 写法 `- 不包含：A；B；C`，被 plan_freshness plugin 判为「'不包含' 无子条目（scope 防守缺口）」。

## 根因

`scripts/lib/check_plan.py:71` 的 `RE_SCOPE_EXCLUDE` 只识别 `^- 不包含\s*[：:]?\s*$`（行尾冷决，无内容），后跟多个缩进 bullet。inline 写法被视为单一顶级 bullet 自身，子条目计数为 0 → 触发 W003。

## 解法

模板写法：

```
- 不包含：
  - 其他 runner 的改造
  - CI 流水线变更
  - meta-schema 既有字段语义变更
```

要点：
- `- 不包含：` 后不跟内容（冷决）
- 子条目用 2 空格或 tab 缩进
- 至少 1 条；本地 `python3 scripts/gates/run.py --trigger=ci --strict` 可验证

## 验证方法

bootstrap 后在 plan.md 范围段写一条错误的 inline 格式 → 本地 strict CI 必报 W003。按子条目重写后重跑 → warning 消失（exit 0）。

## 引用来源

- `scripts/lib/check_plan.py:71` RE_SCOPE_EXCLUDE
- `scripts/lib/check_plan.py:98` `_scope_exclude_items`
- `requirements/20260521-archive-runner-auto-pr/plan.md:28-37`（修复后正例）
- `.github/workflows/quality-check.yml`（CI 走 --strict）
