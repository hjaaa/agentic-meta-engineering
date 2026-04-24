# Subagent 派发指引（阶段 7）

## 为什么派 subagent 而不是主 Agent 亲自实现

每个 feature 的实现是**可隔离的独立任务**。主 Agent 只做"编排 + 评审 + 用户对话"，把实际写代码交给 fresh subagent，好处：

- 主对话上下文不被代码细节污染，多 feature 切换不串味
- 每个 feature 可按 `complexity` 选模型档位（haiku/sonnet/opus）控成本
- subagent 失败时，主 Agent 还能冷静地补上下文 / 升级模型 / 拆小任务

本项目**保守档**：只串行派发，不并发（参考 superpowers `subagent-driven-development` 的 Red Flag "Never dispatch multiple implementation subagents in parallel"）。并发能力留给后续演进。

## 派发前置校验

收到用户 "F-xxx 开始做" 或 "F-xxx 实现" 后：

1. **读 task 文件** `artifacts/tasks/F-xxx.md`
   - `status` 必须是 `pending`（若已 `in-progress` 且有进行中 subagent → 拒绝重派；若 `done` → 走 `/requirement:rollback`）
2. **校验前置依赖**：遍历 task frontmatter 的 `depends_on` 数组
   - 每一条前置 `F-yyy.md` 的 `status` 必须是 `done`
   - 任一前置未 done → 停止派发，列出阻塞项让用户先做前置
3. **构造上下文**：调 `task-context-builder` skill，传 `feature_id`
   - 产出含"基本信息 / 需求 / 接口 / 依赖 / 相关代码 / 注意事项"的精简上下文（< 3000 token）
4. **状态流转**：更新 task 文件 `status: in-progress`，`updated_at`，写 `process.txt [development] F-xxx 开始（派 subagent: <model>）`

## 模型档位选择

按 task 文件的 `complexity` 字段（源自 `features.json.complexity`）：

| complexity | 默认 `subagent_type` | 建议 `model` 参数 |
|---|---|---|
| `low` | `general-purpose` | `haiku` |
| `medium` | `general-purpose` | `sonnet` |
| `high` | `general-purpose` | `opus` |

未填或值非法 → fallback `medium + sonnet`。

用户若显式指定（"这个用 opus"）以用户为准，并在 process.txt 记录。

## 派发 Prompt 模板

调 Agent 工具，参数：

- `subagent_type`: `general-purpose`
- `model`: 上表推导
- `description`: `实现 F-xxx · <title>`
- `prompt`: 按下方模板

```
你是 feat/req-<REQ-ID> 分支上的 feature 实现者。当前任务 F-xxx · <title>。

## 上下文（由 task-context-builder 产出，只含当前 feature 相关信息）

<粘贴 task-context-builder 输出全文>

## 你的任务

1. 按上方上下文实现 F-xxx，严格限制在以下触及范围内：
   <粘贴 touches 字段，如为空则写"未声明，保守处理：仅改与本 feature 直接相关的文件，新增文件优先"）

2. 实现规范严格遵守（仓库根 CLAUDE.md + 项目 CLAUDE.md 已加载）：
   - 小步提交，先最小可行
   - 单方法 ≤ 60 行
   - 异常不吞没
   - 日志带业务主键，禁敏感信息
   - 金额用项目对应的高精度类型

3. 测试：为核心逻辑至少写一个单元测试；外部依赖必须 mock。

4. 提交：用 Conventional Commits 格式，scope 带 F-xxx，例如
   `feat(F-001): 实现用户注册接口`
   commit 前跑一次项目的 lint / 编译。

5. 禁止：
   - ❌ 改动触及范围之外的文件（包括 docs、配置、其他 feature 的代码）
   - ❌ 重构无关代码
   - ❌ 跳过测试
   - ❌ 直接推远程（只 commit，不 push）
   - ❌ 修改 `.claude/` 或 `context/` 下任何文件

6. 完成后按下方状态契约回执。

## 回执状态契约

以**下列四选一**开头，再附详情：

- `DONE`：实现完成，测试通过，已 commit。附 commit SHA、改动文件列表、测试结果。
- `DONE_WITH_CONCERNS`：完成但有疑虑（如发现设计疏漏、边界不清）。附疑虑清单。
- `NEEDS_CONTEXT`：缺关键上下文无法继续。明确说缺什么。
- `BLOCKED`：无法完成。说明根因（技术阻塞 / 需求不清 / 触及范围不够）。

禁止无状态开头的自由散文回执。
```

## 回执处理

| 状态 | 主 Agent 动作 |
|---|---|
| `DONE` | 转入"完成触发"流程（`post-dev-verify` + `/code-review`，见 `SKILL.md`） |
| `DONE_WITH_CONCERNS` | 先把疑虑清单给用户看，用户判断：接受疑虑继续走完成流程，或派修复 subagent |
| `NEEDS_CONTEXT` | 补充缺失上下文（可能需要用户回答），**同模型重派**；不要主 Agent 代替 subagent 写代码 |
| `BLOCKED` | 三选一：(1) 技术阻塞 → 升级模型档位重派；(2) 需求不清 → 问用户；(3) 触及范围不够 → 与用户协商扩大 `touches` 或拆子 feature。**禁止原模型原上下文重试**。 |

## 红线

- ❌ 禁止主 Agent 代替 subagent 直接写代码（除非用户明确要求"别派 subagent，我/你直接写"）
- ❌ 禁止同时派多个 implementer subagent（保守档约束；多 feature 仍串行逐个做）
- ❌ 禁止把整份 `detailed-design.md` / 整份 `features.json` 塞进 prompt——必须走 `task-context-builder` 精简
- ✅ 每次派发前读最新 task 文件（状态可能被 `/requirement:rollback` 改过）
- ✅ 每次派发都在 `process.txt` 留一行 `[development] F-xxx 派发（model=<x>）`
