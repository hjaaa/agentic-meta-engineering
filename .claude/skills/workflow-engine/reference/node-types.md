# 8 种节点类型字段速查

引擎层支持 8 种节点类型字段（`prompt` 与 `prompt_file` 在引擎层等价，合并视作一种）。
每个节点**必须恰好声明 1 个**类型字段，多于 1 个 → W110；零个 → W111。

## 字段总览

| 类型字段 | 默认 idle_timeout (ms) | 默认派发方 | 说明 |
|---|---|---|---|
| `agent` | 300_000 (5min) | subagent | 派 `.claude/agents/<name>.md` 子代理执行 |
| `skill` | 300_000 | 主 Claude | 主 Claude 加载 SKILL.md 并按指令执行 |
| `prompt` | 300_000 | 主 Claude（默认 `context: shared`） | 内联 prompt；`context: fresh` 时改派 subagent |
| `prompt_file` | 300_000 | 同 `prompt` | 外置 prompt 文件，路径必须落在 `.claude/workflows/prompts/` 内（W141 / W142） |
| `bash` | 60_000 (1min) | 主 Claude 调 Bash 工具 | shell 命令；变量经 shellQuote 转义注入 |
| `approval` | 86_400_000 (24h) | 主 Claude 写状态文件后退出 | 用户响应慢，超时阈值放大 |
| `loop` | 300_000 | 主 Claude（`fresh_context: true` 时每轮派 subagent） | `loop.max_iterations` 必填；`interactive: true` 必配 `gate_message` |
| `sub_workflow` | 1_800_000 (30min) | 子 run（独立 jsonl + RunState） | 嵌套深度 ≤ 2（W150）；循环引用拒绝（W152） |
| `artifact` | 30_000 | 主 Claude 调 Bash 跑 `run_artifact_checks.py` | 静态产物校验（schema / 路径 / 字段） |

> 默认 idle_timeout 来自 `scripts/lib/workflow_loader.py::NODE_TYPE_DEFAULT_TIMEOUT_MS`；
> 派发决策见 `dispatch-decision.md` 与 SKILL.md 决策表。

## 互斥规则（W110 / W111 / W140）

- **W110**：同节点声明 ≥ 2 个不同类型字段（如 `skill: foo` + `bash: 'echo'`）→ ERROR
- **W111**：节点未声明任一类型字段（孤儿节点）→ ERROR
- **W140**：`prompt` 与 `prompt_file` 同节点共存 → ERROR（两者引擎层等价，二选一）
- 互斥分组定义见 `workflow_loader.py::NODE_TYPE_GROUPS`：
  `(skill,) (agent,) (prompt, prompt_file) (bash,) (loop,) (approval,) (artifact,) (sub_workflow,)`

## 嵌套约束（W150 / W151 / W152 / W153）

仅 `sub_workflow` 类型有嵌套语义；常量 `MAX_SUB_WORKFLOW_DEPTH = 2`：

| 错误码 | 触发场景 |
|---|---|
| W150 | 子 yaml 再嵌套 sub_workflow，总深度 > 2 |
| W151 | `sub_workflow:` 引用的 yaml 未找到 |
| W152 | sub_workflow 循环引用（A → B → A） |
| W153 | 嵌套子 yaml 解析失败 / 默认值补全错 |

边界值（深度 = 2）必须通过；测试见 `tests/lib/test_node_types.py::test_nest_depth_limit_accepts_depth_2_boundary`。

## 类型示例（每类型 1 个最小 yaml）

```yaml
# agent：派子代理跑 ESLint 审查
- id: lint-check
  agent: code-reviewer
  inputs: [diff_range]
```

```yaml
# skill：主 Claude 加载 Skill 推进阶段
- id: phase-next
  skill: managing-requirement-lifecycle
  args: { sub_intent: next }
```

```yaml
# prompt（内联 + 默认 context: shared）
- id: write-summary
  prompt: |
    根据 $upstream.output 写 200 字摘要。
```

```yaml
# prompt_file（外置；context: fresh 时派 subagent）
- id: cr-checker-security
  prompt_file: prompts/code-review-embedded/cr-checker-security.md
  context: fresh
```

```yaml
# bash：主 Claude 调 Bash 工具
- id: pr-submit
  bash: |
    set -e
    git push origin "feat/req-$RUN_ID"
```

```yaml
# approval：写状态文件后退出，等用户 /workflow:approve
- id: pr-merged-gate
  approval:
    gate_message: 'PR 已合并？approve 进入归档。'
```

```yaml
# loop：循环跑直到 until_bash 退出 0
- id: ralph-loop
  loop:
    max_iterations: 5
    prompt: '继续推进任务，使用 $LOOP_PREV_OUTPUT 作为上轮上下文。'
    until_bash: 'test -f .done'
```

```yaml
# sub_workflow：子 run 透传 args
- id: review-each
  sub_workflow: code-review-embedded
  args:
    feature_id: $upstream.output.id
  on_subworkflow_failure: fail
```

```yaml
# artifact：跑产物校验脚本
- id: validate-meta
  artifact:
    checks:
      - type: yaml_schema
        path: $RUN_DIR/meta.yaml
        schema: meta-schema.yaml
```

## 与 SKILL.md 决策表对齐

| 节点形态 | 派发方式 |
|---|---|
| `skill: xxx` | 主 Claude 直接跑 |
| `prompt` / `prompt_file` 默认 | 主 Claude 直接跑（继承上下文） |
| `prompt` / `prompt_file` + `context: fresh` | 派 subagent |
| `agent: xxx` | 派 subagent |
| `bash:` | 主 Claude 调 Bash 工具 |
| `artifact:` | 主 Claude 调 Bash 跑 `run_artifact_checks.py` |
| `approval:` | 写状态文件 + 输出 message + Skill 退出 |
| `loop` + `fresh_context: false` | 主 Claude 跑迭代（累积上下文） |
| `loop` + `fresh_context: true` | 每轮派一个新 subagent |
| `sub_workflow:` | 引擎递归调 `/workflow:run` 子模板，子 run 独立 jsonl |

详见 `.claude/skills/workflow-engine/reference/dispatch-decision.md`。
