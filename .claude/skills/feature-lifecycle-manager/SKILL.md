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
3. 拆分完成后**不自行修改 `meta.yaml.phase`**——阶段切换由用户通过 `/workflow:next [F-012 待落地]` 触发（F-012 后），走 standard-8phase yaml workflow phase-transition 节点

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
   - `python3 scripts/gates/run.py --trigger=post-dev --req=<REQ-ID> --feature=<F-xxx>`
   - 退出码 ≠ 0 → status 保持 `in-progress`，列出失败项让用户/subagent 修，**禁止进入下一步**
3. 触发 `/code-review` scope = 该 feature
4. 审查结果：
   - 调用 wrapper 脚本判定 sign-off 状态（不允许自行 grep / 一行式）：
       bash scripts/check-signoff.sh requirements/<id>/reviews/<rev-id>.json
   - 退出码 0 → human_signoff.decision ∈ {approved, approved-trivial} → 转 done
   - 退出码 1 → 未签字 / decision=rejected / 缺字段 → 保持 in-progress，提示开发者执行 /code-review:signoff
   - `needs_revision` / `blocked` → status 保持 `in-progress`，把 review 结果交给**同一 subagent 重派修复**（不是主 Agent 亲自修）
5. **转 done 后必须释放 dispatch lock**（hotfix REQ-2026-010 follow-up）：
   - `python3 scripts/lib/dispatch_state_cleanup.py --req-dir requirements/<REQ-ID>`
   - CLI 幂等，重复调安全；漏调会导致 `.dispatch-state.json.current_feature` 一直停在本 feature，后续主 Agent 任何 Edit 都会被 `touches_guard` 误记到该 feature.receipt.json，触发 `GATE-TOUCHES-VIOLATION` 硬挡 phase-transition / submit

## 硬约束

- ❌ 禁止跳过状态（不允许 pending 直接 done）
- ❌ 禁止在 `done` 后再退回（如需修改，走 `/requirement:rollback`）
- ❌ 禁止跳过 `post-dev-verify`——即便"只改了文档""只是小改动"也必须跑；这正是用脚本代替口头承诺的价值（命令：`python3 scripts/gates/run.py --trigger=post-dev --req=<REQ-ID> --feature=<F-xxx>`）
- ❌ 禁止主 Agent 代替 subagent 直接写实现代码（保守档的核心约束；例外：用户明确要求）
- ❌ 禁止并发派多个 implementer subagent（保守档约束；多 feature 逐个串行）
- ✅ 每个 task 文件必须有 `status`、`complexity`、`depends_on`、`created_at`、`updated_at` 字段
- ✅ `done` 必须附代码审查报告路径
- ✅ 每次派发/状态变更都在 `process.txt` 留一行

## 自动化拦截层（hook + gate）

### 派发时拦截（PreToolUse）

`dispatch_precheck.py` 在每次 Agent 工具调用时自动运行，校验链：

- **B-1**：task.md frontmatter `status == "pending"`（source of truth；非 pending → exit 2 阻断）
- **B-2**：`depends_on_features` 所有前置 feature 状态 `== "done"`（任一未 done → exit 2 阻断）
- **B-3**：dispatch-state.json `current_feature` 必须 null 或等于本 fid（保守档串行约束；已有其他 feature 在派 → exit 2 阻断）

**fail-open 策略**：stdin 解析失败 / task.md 不存在 / features.json 缺失 → 静默 exit 0 放行（仅对成功识别的 feature_id 生效强校验）。

### 开发期拦截（软记违规）

`touches_guard.py` PreToolUse 拦截 Edit / Write / MultiEdit 工具：

- 当前 feature 的 `touches` 字段来自 task.md frontmatter（经由 dispatch-state.json 找到 fid → 读 task.md）
- 越界写入**不阻断**，但追加 violation 记录到 `artifacts/tasks/<fid>.receipt.json` 的 `touches_violations[]`
- receipt.json 写入采用 `_flock_receipt_file` LOCK_EX 防并发覆盖（D-012）

### 阶段切换 / 提交时硬挡（gate）

4 个注册在 `scripts/gates/registry.yaml` 的 gate，`phase-transition` / `submit` 触发时运行：

| Gate | 触发条件 | 核心校验 |
|---|---|---|
| `GATE-POST-DEV-RECEIPT` | phase-transition / submit | features.json 中所有 done feature 必须有 receipt.json 且 status ∈ {DONE, DONE_WITH_CONCERNS} |
| `GATE-TOUCHES-VIOLATION` | phase-transition / submit | 所有 receipt.json 的 `touches_violations[]` 必须为空 |
| `GATE-FEATURES-SCHEMA` | pre-commit / phase-transition / submit / ci | features.json 符合 features-schema.yaml |
| `GATE-TASK-FRONTMATTER` | pre-commit / phase-transition / submit / ci | tasks/*.md frontmatter 符合 task-frontmatter-schema.yaml |

**注意**：4 个新 gate 不纳入 `legacy-bypass` tag，不被 meta.yaml `legacy: true` 豁免（D-005 #2；历史 completed REQ 由 trigger / changed_files 路径自然隔离，不依赖 legacy 短路）。

## 参考资源

- [`reference/feature-states.md`](reference/feature-states.md) — 状态定义与流转
- [`reference/subagent-dispatch.md`](reference/subagent-dispatch.md) — 派发前置校验 / 模型档位 / Prompt 模板 / 回执处理
- [`templates/feature-task.md.tmpl`](templates/feature-task.md.tmpl) — 任务文件模板
- `.claude/skills/task-context-builder/reference/extract-rules.md` — `features.json` 字段权威定义
