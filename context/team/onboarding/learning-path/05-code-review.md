# Stage 5 · 用 /code-review 做增量审查

**完成时间**：1-2 小时
**前置**：Phase 2/3 完成
**可验证动作**：用 `/code-review` 拦截到至少 1 个真实问题

## 两种使用模式

### 独立模式（任何项目即可）

在任意 git 仓库里运行 `/code-review`。它会：

1. 取当前分支 vs master 的 diff 作为 ReviewScope
2. 并行跑 8 个 checker → `review-critic` 对抗验证 → `code-quality-reviewer` 三方裁决
3. 生成审查报告（含裁决明细段）

### 嵌入模式（Agentic Engineering 工作流）

阶段 7 功能点完成时，`feature-lifecycle-manager` Skill 自动调用 `/code-review`，范围限定到该功能点。

## 8 个 checker 维度

- design-consistency — 设计一致性
- security — 注入/鉴权/敏感日志
- concurrency — 并发/幂等
- complexity — 方法长度/圈复杂度
- error-handling — 异常/错误码
- auxiliary-spec — 命名/注释/格式
- performance — 热点 SQL/N+1
- history-context — git log/blame 识别近期改过的 bug 行、WORKAROUND/HACK，避免误判

## 三层验证机制

checker 并不是最终声音——`/code-review` 走三层来抑制误报：

1. **Checker**（并行）：8 维度各自给候选 finding，只对自己维度负责
2. **Critic**（review-critic，对抗式）：逐条尝试寻反证，给 `rejected / not_proven / not_rebutted`；找不到反证必须承认
3. **Judge**（code-quality-reviewer，opus）：独立调研 + 三方对比（checker 证据 / critic 反证 / 自己读码），最终处置分 `keep / downgrade / drop / follow-up`

报告中"裁决明细"段展示每条候选 finding 的三方过程，方便事后复盘。零 finding 时自动跳过 critic 和 Judge。

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
