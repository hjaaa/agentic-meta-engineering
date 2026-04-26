# `/requirement:submit` 执行规则

`submit` 是在 `development` 或 `testing` 阶段内部的一次"推分支 + 开 PR"动作，**不改变 phase**。设计意图：把需求 artifacts 沉淀出的信息自动灌到 PR 正文，并把 PR 元数据回写到 `meta.yaml`。

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--draft` | false | 开草稿 PR |
| `--target <branch>` | 自动推断 | 覆盖 PR base |
| `--skip-rebase` | false | 跳过 rebase（冲突时用户手动处理后重跑） |
| `--reviewer <user>` | — | 可多次，追加 reviewer |
| `--force-with-blockers` | false | 允许在有 blocker 级审查问题时仍开 PR（需显式） |

## 步骤

### 1. 解析目标分支（base）

按优先级取第一个可用：

1. `--target` 参数
2. `meta.yaml.base_branch`
3. `origin/develop` 存在 → `develop`
4. 兜底 `main`

### 2. 前置门禁

全部通过方可继续。清单见 `gate-checklist.md` 的"`/requirement:submit` 前置门禁"小节。任一失败立即终止，不污染任何文件。

### 3. 同步 base

- `git fetch origin <base>`
- 非 `--skip-rebase`：`git rebase origin/<base>`
- 冲突 → 打印冲突文件清单 + 提示 `rebase --continue` 后重跑 submit。**不**自动写 meta.yaml。

### 4. 推送

```bash
git push -u origin <branch>
```

若 push 被远端保护规则拒绝（如缺少 reviewer / 缺少 CI 通过），按原始 error 提示用户处理，不 swallow。

### 5. 构建 PR 正文

- 渲染 `templates/pr-body.md.tmpl`，占位符来源：

| 占位符 | 来源 |
|---|---|
| `__REQ_ID__` | `meta.yaml.id` |
| `__REQ_TITLE__` | `meta.yaml.title` |
| `__PHASE__` | `meta.yaml.phase` |
| `__FEATURES_SUMMARY__` | `artifacts/features.json` 里 `status=done` 的每条一行 |
| `__SERVICES__` | `meta.yaml.services`，join `, ` |
| `__FILES_STAT__` | `git diff --stat origin/<base>..HEAD` |
| `__TEST_STRATEGY__` | `artifacts/detailed-design.md` 的"测试策略"段（读不到则填 `见详细设计`） |
| `__REVIEW_REPORTS__` | `artifacts/review-*.md` 相对路径列表（由 `/code-review` 命令产出） |
| `__RISK__` | `artifacts/requirement.md` 的"风险/回滚"段（读不到则填 `无已知风险`） |

### 6. 推断 PR 标题

- 主 type 从 `features.json` 的 type 字段聚合：
  - 全 feat → `feat`
  - 全 fix → `fix`
  - 混合 → `feat`（主）
- scope = `meta.yaml.id`（如 `req-2026-042`）
- title 格式：`<type>(<scope>): <meta.yaml.title>`

### 7. 开 PR / 更新 PR

- 先检查是否已存在同分支 PR：`gh pr list --head <branch> --state open --json number,url`
- 若存在：`gh pr edit <num> --body-file <rendered>`（幂等更新）
- 若不存在：`gh pr create --base <base> --title "..." --body-file <rendered> [--draft] [--reviewer ...]`

### 8. 回写 meta.yaml

原子写入（先写临时文件再 mv）：

```yaml
pr_url: https://github.com/.../pull/<num>
pr_number: <num>
```

### 9. 记录 process.txt

追加一行：

```
[YYYY-MM-DD HH:MM:SS] submitted PR #<num> → <base> (<url>)
```

### 10. 终端反馈

```
✅ PR #<num>: <url>
   base:     <base>
   title:    <title>
   phase:    <phase>（未变更）
   reviewers: @<list>
```

## 失败处理矩阵

| 场景 | 行为 |
|---|---|
| 门禁任一项失败 | 打印缺口清单，不改任何文件，退出 1 |
| rebase 冲突 | 提示冲突文件 + 恢复命令（`git rebase --abort` / `--continue`），退出 1 |
| `gh` 未安装 | 打印安装链接 + 等价 `gh pr create` 命令供用户手动跑，退出 1 |
| `gh` 未登录 | 提示 `gh auth login`，退出 1 |
| 存在 blocker 级审查问题 | 默认阻止；`--force-with-blockers` 显式放行，同时在 PR 正文顶部加 `⚠️ 含未解决 blocker` |
| 同分支 PR 已合并 | 阻止（不能向已合并的 PR push 新 commit），提示用户切分支或改基点 |

## 和追溯链的关系

`submit` **不**调用 `traceability-gate-checker`。追溯链是 `development → testing` 的硬门禁，PR 开出时代码可能还在补单测；submit 只要求"已有 review 报告且无 blocker"即可。PR 合并后再由 `/requirement:next` 驱动追溯链校验。
