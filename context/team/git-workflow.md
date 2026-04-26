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

### 开分支前的标准动作（硬性要求）

**所有 `feat/* / feature/* / fix/* / docs/* / chore/*` 分支必须从最新 `develop` 切出**，不得从 `main` 切。
原因：`main` 与 `develop` 在每次 `release/*` 发版后会形成**两条平行历史**（内容一致但 commit 哈希不同）。从 `main` 切出的分支 PR 到 `develop` 时，会把 `main` 那一整条平行历史拖进 PR，造成大面积虚假冲突。

开分支前统一执行这三行：

```bash
git fetch origin
git checkout develop && git pull --ff-only
git checkout -b <type>/<desc>     # type = feat / feature / fix / docs / chore
```

> 已经从 `main` 切了分支并提交了怎么办？
> ```bash
> git fetch origin
> git rebase --onto origin/develop $(git merge-base HEAD origin/main) HEAD
> git push --force-with-lease
> ```
> 效果：把你的 commit 直接落到 `origin/develop` 之上，丢掉中间那段平行历史，PR 冲突立刻消失。

### 首次启用 develop（仓库初始化）

克隆本仓库即自带 develop。**从零搭建**新仓库时按以下步骤启用：

```bash
git checkout -b develop main
git push -u origin develop
gh api -X PATCH repos/<owner>/<repo> -f default_branch=develop
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
- 自动引用 `artifacts/review-*.md` 审查报告和追溯链
- 自动把 `meta.yaml.pr_url / pr_number` 写回

### 发版路径实战注意（release → main）

本仓库 **main 严禁直接 push**，全局 `git-release` skill 默认的"本地 `git merge --no-ff release/* && git push origin main`"路径会被 hook 拦；必须走 PR。以下是完整顺序：

1. 在 `release/vX.Y.Z` 上完成 VERSION bump、测试等 → push `release/*`
2. `gh pr create --base main --head release/vX.Y.Z` → 合并方式选 **Merge commit**（不是 Squash）
3. 合并后本地 `git pull main` → `git tag -a vX.Y.Z` → `git push origin vX.Y.Z`
4. `gh release create vX.Y.Z` 发布 GitHub Release
5. 在 release 分支上补 `docs: 更新 CHANGELOG vX.Y.Z` commit → push
6. 开两个平行 PR：
   - release → main：同步 CHANGELOG（参考 v1.0.0 #21、v1.2.0 #29），可 Squash
   - release → develop：回合 VERSION + CHANGELOG + merge 记录，用 Merge commit

### 发版必踩的两个坑

#### 坑 1：squash merge 平行历史导致 "整份 diff 冲突"

feature PR → develop 用 Squash，每次 develop → release → main 又都是 Merge commit 节点。结果：**main 上每个 release tag 都是一个独立的 squash commit**，和 develop 分出的新 `release/*` 分支没有共同近祖，PR 看起来会有几十个文件"冲突"——实则内容一致，只是 commit 哈希不同。

复用 v1.1.0 时沉淀下来的化解方案（在 release 分支本地执行）：

```bash
git checkout release/vX.Y.Z
git merge origin/main -X ours --no-ff \
  -m "release: 合并 origin/main 到 release/vX.Y.Z（保留 release 侧内容）"
git push origin release/vX.Y.Z
```

`-X ours` 只处理 modify/modify 冲突（保留 release 侧），**不处理 modify/delete 冲突**（见坑 2）。push 后 PR 自动变成 mergeable。

#### 坑 2：modify/delete 冲突不会被 `-X ours` 自动解决

场景：release 周期内某 PR 删除了文件 F（比如废弃 Hook），但上版 main 的 squash commit 里 F 仍以"修改"形式存在。merge 时出现 `DU（deleted by us, modified by them）`——git 需要人类判断是"恢复"还是"保持删除"。

策略：**按原始 PR 的意图决定**。删除是有意的就保留删除：

```bash
git rm <path/to/file>   # 保留删除决定
git commit               # 完成 merge commit
```

在 commit 前再检查一次：
- `grep` 一下 `.claude/settings.json` 和其他 registry 文件，确认没有残留引用
- 看看原 PR 的设计说明，理解为什么要删
- 不要为了"让 merge 通过"而盲目 `git checkout --theirs` 恢复文件——那等于悄悄撤销了原 PR

> 补充：权限系统会拦"没点名的 `git rm`"，所以在让 AI 执行这一步时要显式授权："授权删除 A/B/C 三个已废弃文件完成 merge"。

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
