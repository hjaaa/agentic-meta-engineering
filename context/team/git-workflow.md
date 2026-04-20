# Git 工作流规范

## 分支策略

- `main` — 受保护分支，禁止直接提交（由 `.claude/hooks/protect-branch.sh` 拦截）
- `feat/<requirement-id>` — 功能分支，`/requirement:new` 自动创建
- `hotfix/*` — 紧急修复
- `release/*` — 发版分支

## 提交规范（Conventional Commits）

格式：`<type>(<scope>): <subject>`

常用 type：

| type | 含义 |
|---|---|
| feat | 新功能 |
| fix | Bug 修复 |
| docs | 文档 |
| refactor | 重构（无行为变化） |
| test | 测试 |
| chore | 构建/配置 |

subject 用祈使句、简体中文、不超过 50 字符。

## PR 规范

- 标题 = 一句话描述，遵循上面的 Conventional Commits 格式
- 正文包含：**变更摘要 / 影响范围 / 验证方式 / 风险与回滚**（与全局 CLAUDE.md §11 一致）
- 至少 1 个 reviewer 通过才能合入
- 合入方式：Squash merge（保持 main 线性历史）

## 禁用操作

以下操作被 `.claude/settings.json` 的 deny 规则直接阻止：

- `rm -rf` 类批量删除
- `git reset --hard`
- `git push --force`

如确需，改到 feature 分支上本地操作，不允许在 main 上进行。
