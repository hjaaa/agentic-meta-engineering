---
name: feature-lifecycle-manager
description: 阶段 6（任务规划）拆分 features.json 为功能点任务；阶段 7（开发实施）派 subagent 实现单个 feature_id 并管理状态流转（pending → in-progress → done）。Done 转换时触发 /code-review scoped 到该 feature。
---

## 什么时候用

- **阶段 6**：用户进入任务规划阶段，或说"拆分功能点"时
- **阶段 7**：用户说 "F-xxx 开始做 / F-xxx 实现 / F-xxx 完成了"时

## 核心流程

### 阶段 6：任务拆分

1. 读 `artifacts/features.json`
2. 对每个 feature_id，基于 `templates/feature-task.md.tmpl` 生成 `artifacts/tasks/<id>.md`，状态初始化为 `pending`
   - 把 `features.json` 的 `complexity` / `depends_on_features` 映射到 task frontmatter 的 `complexity` / `depends_on`
   - 缺省值：`complexity: medium`，`depends_on: []`
3. 拆分完成后**不自行修改 `meta.yaml.phase`**——阶段切换由用户通过 `/requirement:next` 触发，交给 `managing-requirement-lifecycle` 走门禁校验

### 阶段 7：feature 生命周期

状态流转（严格，见 `reference/feature-states.md`）：

```
pending → in-progress → done
```

#### 开始开发（派 subagent）

当用户说 "F-xxx 开始做" 或 "F-xxx 实现"：

1. 按 `reference/subagent-dispatch.md` 的**派发前置校验**把关：
   - task 文件 `status == pending`
   - `depends_on` 里每条前置 feature 都 `status == done`
   - 任一失败 → 停止派发，列出阻塞项
2. 调 `task-context-builder` skill 构造精简上下文
3. 按 `complexity` 选模型档位（见派发指引的映射表）
4. 用 Agent 工具派一个 fresh implementer subagent，prompt 用 `reference/subagent-dispatch.md` 的**派发 Prompt 模板**
5. 更新 task 文件 `status: in-progress`，`updated_at`；写 `process.txt [development] F-xxx 开始（model=<x>）`
6. 按**回执处理**表处理 subagent 返回的 `DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED`

#### 完成触发（回执 DONE 后）

1. 确认当前 feature 代码已 commit（`git log` 含 F-xxx）
2. **跑脚本级总门禁 `post-dev-verify`**（在 `/code-review` 之前，过不了直接挂，省 AI 审查成本）：
   - `bash scripts/post-dev-verify.sh --requirement <REQ-ID> --feature <F-xxx>`
   - 退出码 ≠ 0 → status 保持 `in-progress`，列出失败项让用户/subagent 修，**禁止进入下一步**
3. 触发 `/code-review` scope = 该 feature
4. 审查结果：
   - `approved` → 更新 task 文件 status 到 `done`，记录 review 报告路径；`process.txt` 追加 `[development] F-xxx 完成（review: xxx.md）`
   - `needs_revision` / `rejected` → status 保持 `in-progress`，把 review 结果交给**同一 subagent 重派修复**（不是主 Agent 亲自修）

## 硬约束

- ❌ 禁止跳过状态（不允许 pending 直接 done）
- ❌ 禁止在 `done` 后再退回（如需修改，走 `/requirement:rollback`）
- ❌ 禁止跳过 `post-dev-verify`——即便"只改了文档""只是小改动"也必须跑；这正是用脚本代替口头承诺的价值
- ❌ 禁止主 Agent 代替 subagent 直接写实现代码（保守档的核心约束；例外：用户明确要求）
- ❌ 禁止并发派多个 implementer subagent（保守档约束；多 feature 逐个串行）
- ✅ 每个 task 文件必须有 `status`、`complexity`、`depends_on`、`created_at`、`updated_at` 字段
- ✅ `done` 必须附代码审查报告路径
- ✅ 每次派发/状态变更都在 `process.txt` 留一行

## 参考资源

- [`reference/feature-states.md`](reference/feature-states.md) — 状态定义与流转
- [`reference/subagent-dispatch.md`](reference/subagent-dispatch.md) — 派发前置校验 / 模型档位 / Prompt 模板 / 回执处理
- [`templates/feature-task.md.tmpl`](templates/feature-task.md.tmpl) — 任务文件模板
- `.claude/skills/task-context-builder/reference/extract-rules.md` — `features.json` 字段权威定义
