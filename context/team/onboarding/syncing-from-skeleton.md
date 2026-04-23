# 从骨架同步更新（下游仓库升级指南）

> 最近更新：2026-04-23
>
> 适用对象：**基于本骨架派生出去的下游项目仓库**。骨架指 `github.com/hjaaa/agentic-meta-engineering` 本身。

本仓库是 Agentic Engineering 骨架。当骨架升级（新增 Skill、修复 Hook、完善规范）后，下游仓库要定期把公共部分同步下来，又要保护自己的项目私有产出不被覆盖。

核心策略：**upstream merge + 受管目录清单 + 硬约定**。

## 1. 一次性配置

在下游仓库里执行：

```bash
# 添加骨架为 upstream
git remote add upstream git@github.com:hjaaa/agentic-meta-engineering.git
git fetch upstream

# 验证
git remote -v
# origin    <你的下游仓库>                                      (fetch/push)
# upstream  git@github.com:hjaaa/agentic-meta-engineering.git  (fetch/push)
```

## 2. 受管目录清单（同步边界）

### 2.1 同步的（骨架公共部分，下游不要改）

| 路径 | 内容 |
|---|---|
| `.claude/commands/` `.claude/skills/` `.claude/agents/` `.claude/hooks/` | 工具定义 |
| `context/team/engineering-spec/` | 体系规范（设计指导 / 工具规范 / 迭代 SOP） |
| `context/team/onboarding/` | 入门指南与学习路径 |
| `context/team/ai-collaboration.md` | AI 协作准则 |
| `context/team/git-workflow.md` | 分支/提交规范 |
| `context/team/tool-chain.md` | 工具链约定 |
| `context/team/INDEX.md` | 根索引 |

### 2.2 不同步的（下游私有）

| 路径 | 内容 |
|---|---|
| `context/project/` | 下游项目专属知识 |
| `requirements/` | 下游需求全周期产出 |
| `.claude/settings.local.json` | 本地权限/模型配置 |

### 2.3 冲突敏感的（人工判断）

| 路径 | 处理策略 |
|---|---|
| `CLAUDE.md` | 骨架基线 + 下游扩展。**建议：骨架版保持不动，下游扩展写到 `CLAUDE.local.md` 或 `context/project/<X>/CLAUDE.md` 并用 `@path` 引用进来** |
| `.claude/settings.json` | 下游可能追加 hook/权限，手工合并时保留双方 |
| `README.md` | 下游通常会完全重写为自己的项目 README，同步时 `git checkout --ours` |

## 3. 日常同步流程

```bash
# 1. 保持主干干净
git checkout develop && git pull

# 2. 建升级分支
git checkout -b chore/sync-skeleton-$(date +%Y%m%d)

# 3. 拉最新骨架
git fetch upstream

# 4. 合并（no-ff 保留合并痕迹，便于日后追溯）
git merge upstream/main --no-ff -m "chore: sync skeleton from upstream"

# 5. 处理冲突
#    - 只应在"冲突敏感"那几个文件发生
#    - 其他路径有冲突 → 说明下游违反约定动了骨架文件，走第 4 节冲突裁决

# 6. 本地验证
#    - 跑一次 /agentic:help 确认 commands 正常加载
#    - 跑一次 /requirement:status 确认 hooks 正常
#    - 浏览 CHANGELOG / git log 的骨架更新，关注是否有破坏性变更

# 7. 提 PR
git push -u origin HEAD
gh pr create --base develop \
  --title "chore: sync skeleton from upstream" \
  --body "同步骨架更新至 upstream/main @ $(git rev-parse --short upstream/main)"
```

## 4. 冲突裁决

当冲突发生在"同步的"路径（即下游违反约定改过骨架文件），按以下顺序判断：

| 情景 | 处理 |
|---|---|
| 下游那改其实是通用改进 | **回流骨架**：先把改动 PR 到 upstream，合并后再 `git fetch upstream && git merge` 过来，冲突自然消失 |
| 下游是临时/项目特化 workaround | **迁移到私有路径**：把改动挪到 `context/project/<X>/` 或下游独立 Skill/Command 里，然后 `git checkout --theirs <骨架文件>` 用骨架版覆盖 |
| 下游改动是误操作 | 直接 `git checkout --theirs <骨架文件>` 用骨架版覆盖 |

**不要用 `--ours` 让下游版本胜出**——这会让下游永远卡在旧骨架，后续冲突滚雪球。

## 5. 四条硬约定（避免反复冲突）

1. **骨架文件只在骨架仓库改**
   下游发现 bug / 想加 Skill，先给骨架仓库提 PR，合并后再 sync，不要在下游直接改。这是整个方案能跑起来的前提。

2. **CLAUDE.md 的下游扩展写在独立文件**
   骨架的 `CLAUDE.md` 保持原样。项目级规范写到 `context/project/<X>/CLAUDE.md`，并在 `CLAUDE.md` 里用 `@context/project/<X>/CLAUDE.md` 引用，骨架升级不冲突。

3. **每次 sync 独立一个 PR**
   不要和业务改动混在一起。回滚、代码审查、责任归属都会清晰很多。

4. **sync 频率建议**
   - 骨架发布新版本（看 tag）后一周内同步一次
   - 遇到明显需要的新 Skill / Hook 修复，按需即时同步
   - 长期不 sync（> 3 个月）会导致冲突面指数扩大，强烈不建议

## 6. 破坏性变更检查清单

每次 sync 前，在骨架仓库看 `CHANGELOG.md` 和 `git log upstream/main` 里这几类提交：

- `BREAKING:` 前缀
- `.claude/hooks/` 目录改动（可能改变自动行为）
- `.claude/commands/` 删除或重命名（可能让下游脚本失效）
- `context/team/engineering-spec/tool-design-spec/` 改动（可能影响下游自建 Skill 的合法性）

遇到破坏性变更，把 sync PR 的描述里列出影响点，便于团队复核。

## 7. 出错时如何回退

```bash
# 如果 merge 后发现问题，还没 push：
git merge --abort                             # 撤销未完成的合并
git reset --hard HEAD@{1}                     # 已提交但没 push，退回合并前

# 已经 push 并合入 develop（最坏情况）：
# 在下游仓库走 revert 流程，不要 force push
git revert -m 1 <merge-commit-sha>
```

---

**相关文档**
- [`git-workflow.md`](../git-workflow.md) — 分支策略与提交规范
- [`../engineering-spec/iteration-sop.md`](../engineering-spec/iteration-sop.md) — 骨架自身的迭代 SOP（骨架维护者视角）
