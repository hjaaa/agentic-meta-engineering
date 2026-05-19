---
name: development
node_id: dev-feature-loop
version: 1.0.0
---

# Feature 开发迭代（loop 节点 prompt）

> 此 prompt 在 loop 节点每轮被求值。
> 引擎已替换变量：`$LOOP_PREV_OUTPUT` / `$LOOP_USER_INPUT` / `$LOOP_ITERATION` / `$RUN_ID` / `$ARTIFACTS_DIR`

## 上轮结果

```
$LOOP_PREV_OUTPUT
```

## 上轮用户反馈（如有）

```
$LOOP_USER_INPUT
```

## 当前轮次

第 $LOOP_ITERATION 轮（max 50）

---

## 本轮任务

### 第 1 步：判断是否结束

读取 `$ARTIFACTS_DIR/features.json`：

```bash
jq '[.features[] | select(.status == "pending")] | length' $ARTIFACTS_DIR/features.json
```

- 如果返回 `0`：所有 feature 已 done，**输出 "ALL_FEATURES_DONE" 并结束本轮**
- 如果返回 ≥ 1：进入第 2 步

### 第 2 步：判断本轮是修订还是新 feature

如果上轮用户反馈非空（`$LOOP_USER_INPUT` 不为空字符串）：
- **修订模式**：本轮处理上一个 feature 的修订（不进新 feature）
- 找出 `features.json` 里 `status: in-progress` 的 feature
- 调用 `feature-lifecycle-manager` Skill 的 `revise` 模式
- 基于 `$LOOP_USER_INPUT` 修改实现代码
- 完成后输出 `FEATURE_REVISED: feat-XXX`

否则：
- **新 feature 模式**：进入第 3 步

### 第 3 步：选下一个 pending feature

```bash
jq '.features[] | select(.status == "pending")' $ARTIFACTS_DIR/features.json | jq -s 'first'
```

按 `depends_on` 拓扑顺序选——所有依赖已 done 的 pending feature 中，取 `id` 字典序最小的。

记下 feature_id（后续用）。

### 第 4 步：标记 in-progress

调用 `feature-lifecycle-manager` Skill 把这个 feature 状态改为 `in-progress`：

```
skill: feature-lifecycle-manager
args:
  mode: mark-status
  feature_id: <选中的 id>
  status: in-progress
```

### 第 5 步：构建开发上下文

调用 `task-context-builder` Skill 抽取这个 feature 的精准上下文：
- 读 `features.json` 此 feature 段
- 读 `detailed-design.md` 中相关章节
- 读相关代码文件
- 输出一份"开发上下文"给 subagent 当 prompt

```
skill: task-context-builder
args:
  feature_id: <选中的 id>
```

### 第 6 步：派 subagent 实现

```
agent: general-purpose
context: fresh
prompt: |
  你是 feature 开发 agent。基于以下上下文实现 feat-XXX：

  <task-context-builder 的输出>

  规则：
  - 仅修改本 feature 涉及的文件
  - 严格按 detailed-design.md 的接口签名
  - 写完代码同步写单元测试（覆盖正常 / 边界 / 异常）
  - 每个文件 ≤ 60 行新增（超出拆分）
  - 使用项目既有依赖，不引新库

  完成后输出：
  - 修改的文件列表
  - 测试覆盖情况
  - 任何待用户决策的开放问题

  最后一行输出 "FEATURE_IMPLEMENTED: feat-XXX"
```

### 第 7 步：触发 code-review

实现完成后立即跑代码审查（嵌入式 sub-workflow）：

```
/workflow:run code-review-embedded --parent=$RUN_ID --feature=<选中的 id>
```

子 workflow 会跑完整的 8 critic + critic-验证 + judge + report 流程。
等子 workflow 完成（含 review 报告生成 + 用户在主对话进行软确认）。

软确认分支（20260519-remove-human-signoff F-005）：
- `conclusion=looks_clean` 且无 required_fixes → 直接允许下一步 feature done
- `conclusion=needs_attention` → 默认要求修复并重审；若用户在主对话显式接受风险则继续
- `conclusion=blocked` → fail-closed，必须修复并重审，不可绕过

### 第 8 步：标记本 feature done

review 通过后调 `feature-lifecycle-manager` 把状态改为 `done`：

```
skill: feature-lifecycle-manager
args:
  mode: mark-status
  feature_id: <选中的 id>
  status: done
```

### 第 9 步：输出本轮总结

```
FEATURE_DONE: feat-XXX

修改文件：
- src/services/PaymentStateMachine.java（新增 60 行）
- src/test/.../PaymentStateMachineTest.java（新增 80 行）

测试：6/6 通过，覆盖率 92%
Code review：approved by judge

待办：
- 无
```

引擎拿到此输出后会进入 interactive 卡点，等用户决定下一步。

---

## 边界处理

### 如果某 feature 的依赖未 done 怎么办

跳过此 feature，选下一个 pending（依赖满足的）。如果所有 pending 的依赖都未满足，说明依赖图有环或前置 feature 卡住——输出 `BLOCKED: feat-XXX 依赖 feat-YYY，但 feat-YYY 状态为 <status>`。

### 如果 features.json 在 loop 中被改了

每轮重新读 features.json（不缓存）。如果用户在 interactive 卡点期间手动改了 features.json（加新 feature / 调整估算），下一轮会自动看到。

### 如果 subagent 实现失败

subagent 输出 `FAILED: <原因>` → 本轮输出 `FEATURE_FAILED: feat-XXX, reason: ...`，feature 状态回退到 `pending`。下一轮 interactive 卡点用户决定：approve（跳过此 feature）/ 反馈（重新尝试）/ cancel（终止）。

### 如果用户在 interactive 卡点输入"skip"或"跳过 feat-XXX"

视为本 feature 标 `skipped`（features.json 加状态值），下一轮选下一个 pending。
