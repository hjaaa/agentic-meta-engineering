---
name: feature-lifecycle-manager
description: 阶段 6（任务规划）拆分 features.json 为功能点任务；阶段 7（开发实施）管理每个 feature_id 的状态流转（pending → in-progress → done）。Done 转换时触发 /code-review scoped 到该 feature。
---

## 什么时候用

- **阶段 6**：用户进入任务规划阶段，或说"拆分功能点"时
- **阶段 7**：用户说"F-xxx 开始做 / F-xxx 完成了"时

## 核心流程

### 阶段 6：任务拆分

1. 读 `artifacts/features.json`
2. 对每个 feature_id，基于 `templates/feature-task.md.tmpl` 生成 `artifacts/tasks/<id>.md`，状态初始化为 `pending`
3. 拆分完成后**不自行修改 `meta.yaml.phase`**——阶段切换由用户通过 `/requirement:next` 触发，交给 `managing-requirement-lifecycle` 走门禁校验

### 阶段 7：feature 生命周期

状态流转（严格，见 `reference/feature-states.md`）：

```
pending → in-progress → done
```

**完成触发**：

当用户说 "F-xxx 完成"：
1. 调 `task-context-builder` 确认当前 feature 代码已 commit
2. **跑脚本级总门禁 `post-dev-verify`**（在 `/code-review` 之前，过不了直接挂，省 AI 审查成本）：
   - `bash scripts/post-dev-verify.sh --requirement <REQ-ID> --feature <F-xxx>`
   - 退出码 ≠ 0 → status 保持 `in-progress`，列出失败项让用户修，**禁止进入下一步**
3. 触发 `/code-review` scope = 该 feature
4. 审查结果：
   - `approved` → 更新 task 文件 status 到 `done`，记录 review 报告路径
   - `needs_revision` / `rejected` → status 保持 `in-progress`，通知用户修改

## 硬约束

- ❌ 禁止跳过状态（不允许 pending 直接 done）
- ❌ 禁止在 `done` 后再退回（如需修改，走 `/requirement:rollback`）
- ❌ 禁止跳过 `post-dev-verify`——即便"只改了文档""只是小改动"也必须跑；这正是用脚本代替口头承诺的价值
- ✅ 每个 task 文件必须有 `status`、`created_at`、`updated_at` 字段
- ✅ `done` 必须附代码审查报告路径

## 参考资源

- [`reference/feature-states.md`](reference/feature-states.md) — 状态定义与流转
- [`templates/feature-task.md.tmpl`](templates/feature-task.md.tmpl) — 任务文件模板
