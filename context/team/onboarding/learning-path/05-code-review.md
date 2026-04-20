# Stage 5 · 用 /code-review 做增量审查

**完成时间**：1-2 小时
**前置**：Phase 2/3 完成
**可验证动作**：用 `/code-review` 拦截到至少 1 个真实问题

## 两种使用模式

### 独立模式（任何项目即可）

在任意 git 仓库里运行 `/code-review`。它会：

1. 取当前分支 vs master 的 diff 作为 ReviewScope
2. 并行跑 7 个 checker + 1 综合 reviewer
3. 生成审查报告

### 嵌入模式（Agentic Engineering 工作流）

阶段 7 功能点完成时，`feature-lifecycle-manager` Skill 自动调用 `/code-review`，范围限定到该功能点。

## 7 个 checker 维度

- design-consistency — 设计一致性
- security — 注入/鉴权/敏感日志
- concurrency — 并发/幂等
- complexity — 方法长度/圈复杂度
- error-handling — 异常/错误码
- auxiliary-spec — 命名/注释/格式
- performance — 热点 SQL/N+1

## 练习

1. 在本仓库切一个 feature 分支，故意引入一个违规（如 `rm -rf $HOME/..` 类 Bash 命令）
2. 提交
3. 运行 `/code-review`
4. 确认 `security-checker` 报出这个问题

## 读审查报告

报告存在 `requirements/<id>/artifacts/review-YYYYMMDD-HHMMSS.md`，结论分：

- `approved` — 可合入
- `needs_revision` — 需修改
- `rejected` — 驳回

## 完成标志

- [ ] 成功拦截至少 1 个真实问题
- [ ] 理解双模使用（独立 vs 嵌入）
