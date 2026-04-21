# Git 工作流规范

本仓库采用 **git-flow** 模型。`main` 代表生产，`develop` 代表集成，功能/修复/发版通过短生命周期分支进入 `develop`，再由 `release/*` 汇入 `main` 并打 Tag。

## 分支策略

```
 main                ← 生产环境，只接收 release/* 与 hotfix/* 合入
  ↑ tag v1.x.x
 release/vX.Y.Z       ← 发版分支，从 develop 切出，发版后合入 main 并回合 develop
  ↑
 develop             ← 集成分支，所有 feat/* 合入这里
  ↑
 feat/req-YYYY-NNN    ← 需求功能分支（/requirement:new 自动创建）
 feature/<desc>       ← 通用功能分支（全局 git-feature skill 创建）
 hotfix/<desc>        ← 紧急修复，从 main 切出；修复后合入 main + 回合 develop
```

### 分支用途速查

| 分支 | 来源 | 去向 | 保护 |
|---|---|---|---|
| `main` | — | — | ✅ Hook 拦截 Edit/Write |
| `develop` | `main`（一次性初始化）| 持续接收 `feat/*` 合入 | ✅ Hook 拦截 Edit/Write |
| `feat/req-*` | `develop` | PR → `develop` | ❌ |
| `feature/*` | `develop` | PR → `develop` | ❌ |
| `release/*` | `develop` | PR → `main`，合并后 merge 回 `develop`，打 Tag | ❌ |
| `hotfix/*` | `main` | PR → `main`，合并后 merge/cherry-pick 回 `develop` | ❌ |

### 首次启用 develop（仓库初始化）

`scripts/migrate-to-develop.sh` 给出一次性迁移命令。核心操作：

```bash
git checkout -b develop main
git push -u origin develop
# GitHub 仓库设置 → Default branch 改为 develop
```

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

- **目标分支**：
  - feature / feat/req-* → **develop**
  - release/* → **main**（发版后再开一个 PR 合 develop）
  - hotfix/* → **main**（合并后再开一个 PR 合 develop，或 cherry-pick）
- 标题 = 一句话描述，遵循 Conventional Commits 格式
- 正文包含：**变更摘要 / 影响范围 / 验证方式 / 风险与回滚**（与全局 CLAUDE.md §11 一致）
- 至少 1 个 reviewer 通过才能合入
- 合入方式：
  - feature → develop：Squash merge（保持 develop 线性）
  - release → main：Merge commit（保留 release 节点）
  - hotfix → main：Merge commit（保留 hotfix 节点）
  - release/hotfix 回合 develop：Merge commit

### 需求驱动的 PR

开发完成后推荐使用 `/requirement:submit` 自动提 PR：

- 自动从 `meta.yaml` 取需求信息拼装 PR 正文
- 自动引用 `artifacts/code-review-reports/` 和追溯链
- 自动把 `meta.yaml.pr_url / pr_number` 写回

## 和全局 git-* Skill 的关系

`git-feature` / `git-release` / `git-hotfix` 是**用户级**全局 Skill，默认行为已对齐本仓库 git-flow：

- `git-feature`：默认从 develop 切 `feature/*`
- `git-release`：走 `develop → release/* → main` + 回合 develop
- `git-hotfix`：main 切出，修完合 main + cherry-pick 回 develop

项目内 `/requirement:*` 命令走**需求驱动**路径（`feat/req-*` 前缀），与全局 skill 并存。两条路径都合入 develop。

## 禁用操作

以下操作被 `.claude/settings.json` 的 deny 规则直接阻止：

- `rm -rf` 类批量删除
- `git reset --hard`
- `git push --force`

Hook `.claude/hooks/protect-branch.sh` 对 **main / master / develop** 三条分支拦截直接 Edit / Write / MultiEdit。如确需，改到 feature 分支上本地操作。
