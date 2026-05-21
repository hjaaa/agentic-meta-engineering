# Claude Code 半自动 Workflow Runner 设计

## 背景

当前 workflow YAML 已经不是单纯提示词。`workflow_loader.py` 负责强校验，`workflow_continue.py` 负责恢复状态并推进 main loop，`workflow_scheduler.py` 负责 DAG ready 节点选择，`save_node_result.py` 负责把外部 Claude 动作回写为 `node_completed`。

问题出现在 `skill` / `agent` / `prompt` 节点：dispatcher 会写入 `node_ready`，并让 run 进入 `awaiting_claude_action`，但之后“当前 Claude Code 会话应该怎么执行、把结果写到哪里、用什么命令回写、回写后怎么继续”还没有一个明确的执行包。流程不会静默越过该节点，但 Claude Code 仍可能忘记回写或不知道下一步该做什么。

本设计目标是新增半自动 runner：不启动新的 Claude Code 子进程，只为当前 Claude Code 会话生成确定的下一步执行包，并把回写闭环标准化。

## 目标

1. 让 `/workflow:continue` 后的 `awaiting_claude_action` 有明确、可重复读取的 action package。
2. 让当前 Claude Code 会话按固定闭环执行：读取 action package → 完成当前节点 → 保存结果 → 调 `save_node_result.py` → 再次 drive。
3. 保持现有 workflow 引擎职责不变，runner 不重新实现 DAG 调度、失败矩阵、审批状态机。
4. 对 `skill` / `agent` / `prompt` 使用同一个“外部动作结果”语义，兼容现有 `skill_result`。
5. 所有状态不一致场景 fail-closed，不猜测、不跳过。

## 非目标

1. 不自动启动 `claude` CLI 子进程。
2. 不实现无人工参与的一键跑完整个 workflow。
3. 不重写 `workflow_continue.py` / `workflow_scheduler.py` 的调度逻辑。
4. 不改变 YAML schema 中节点类型和 DAG 语义。
5. 不让 runner 直接伪造 `node_completed`，所有结果仍走 `save_node_result.py`。

## 设计问题与边界

现有设计中，`node_ready` 是状态事件，但不是面向执行者的稳定接口。直接让 Claude Code 读 jsonl 会把内部事件格式暴露成操作协议，导致后续字段调整困难。

因此需要新增一个独立抽象：`ActionPackage`。它是内部 `node_ready` 事件到“当前 Claude Code 应执行事项”的投影。状态机仍以 jsonl 为事实源，action package 只是只读视图，不产生状态变更。

这个边界可以避免两个问题：

1. runner 不成为第二套 scheduler。它只问“当前是否等待外部动作”，不决定下一个 DAG 节点。
2. Claude Code 不需要理解 jsonl 细节。它只按 action package 做事，并调用给定回写命令。

## 推荐方案

新增两个脚本模块：

1. `scripts/lib/workflow_action.py`
2. `scripts/lib/workflow_drive.py`

`workflow_action.py` 负责生成 action package。`workflow_drive.py` 负责推进 workflow 到下一个停点，并在需要 Claude Code 执行时打印 action package。

### ActionPackage 字段

```json
{
  "run_id": "REQ-2026-014",
  "run_dir": "requirements/REQ-2026-014",
  "node_id": "req-draft",
  "node_kind": "skill",
  "instruction": "...",
  "contract": {
    "allowed_tools": [],
    "denied_tools": [],
    "mcp": [],
    "skills": [],
    "agents": [],
    "idle_timeout": null,
    "output_format": null
  },
  "result_file": "requirements/REQ-2026-014/artifacts/node-results/req-draft.json",
  "save_command": "python3 scripts/lib/save_node_result.py --run REQ-2026-014 --node req-draft --kind external_action_result --output @requirements/REQ-2026-014/artifacts/node-results/req-draft.json",
  "continue_command": "python3 scripts/lib/workflow_drive.py REQ-2026-014"
}
```

`instruction` 按节点类型生成：

- `skill`：说明需要调用哪个 skill，以及渲染后的 args。
- `agent`：说明需要按哪个 agent 角色完成任务，并附带 `agent` 名称。
- `prompt`：直接给出渲染后的 prompt 文本。

### workflow_action.py

职责：

1. 根据 run id 解析 run 目录。
2. 读取 `run-state.jsonl` 并用 `RunState.rebuild` 重建状态。
3. 校验 `state == awaiting_claude_action`。
4. 反扫最后一条节点级事件，要求它是当前节点的 `node_ready`。
5. 从 `node_ready.data` 生成 action package。
6. 支持 `--format text|json`，默认 text 面向 Claude Code，json 面向测试和后续工具。

fail-closed 规则：

- `state != awaiting_claude_action`：退出 1，说明当前没有待执行 Claude 动作。
- `current_node` 为空：退出 1。
- 末位节点级事件不是 `node_ready`：退出 2。
- 末位 `node_ready.node_id != current_node`：退出 2。
- `node_ready.data.node_kind` 不在 `skill|agent|prompt`：退出 1。

### workflow_drive.py

职责：

1. 解析 run id；缺省时复用 `infer_run_id_from_branch`。
2. 先读取当前 run state。
3. 根据状态决定是否调用 `workflow_continue.main([run_id])`：
   - `awaiting_claude_action`：不调用 continue，直接渲染当前 action package。
   - `approval_pending`：不调用 continue，直接提示人类 approve/reject。
   - `running` / `paused` / `failed`：调用 continue 推进状态机，再重新读取 run state。
   - `completed` / `cancelled` / `cancel_requested`：不调用 continue，直接输出终态或阻塞状态。
4. 根据最终状态输出下一步：
   - `awaiting_claude_action`：调用 `workflow_action` 渲染 action package，退出 0。
   - `approval_pending`：提示必须由人类执行 `/workflow:approve` 或 `/workflow:reject`，退出 0。
   - `completed`：输出已完成，退出 0。
   - `failed` / `cancelled` / `cancel_requested`：输出终态或阻塞状态，退出 1。
   - `running` 但没有停点：输出 warning，退出 1，避免静默空转。

`workflow_drive.py` 不直接循环执行 Claude 动作。每次跑到一个停点后退出，由当前 Claude Code 会话根据输出执行当前节点。

## 回写语义

现有 `save_node_result.py` 的 `--kind skill_result` 实际已经承载了 `skill` / `agent` / `prompt` 的外部动作结果。为了减少概念误导，新增别名：

```text
--kind external_action_result
```

行为与 `skill_result` 完全一致：

- 期望末位节点级事件为 `node_ready`。
- 写入 `node_completed`。
- `data.output` 来自 `--output` JSON object。

保留 `skill_result`，不破坏已有测试和历史命令。

## Claude Code 操作协议

当 `workflow_drive.py` 输出 action package 后，当前 Claude Code 会话必须按以下顺序执行：

1. 阅读 `instruction` 和 `contract`。
2. 完成当前节点要求的工作。
3. 将结构化结果写入 `result_file`，内容必须是 JSON object。
4. 执行 `save_command`。
5. 执行 `continue_command`，进入下一停点。

如果无法完成当前节点，不允许跳到后续节点。应写明失败原因，并让用户选择修复、回滚、取消或调整 workflow。

## 命令入口调整

新增 Claude Code 命令：

```text
/workflow:drive [<run-id>]
```

该命令委托 `managing-workflow-runs` 的 `drive` 子动作，实际调用：

```bash
python3 scripts/lib/workflow_drive.py [<run-id>]
```

实现时需要同步更新：

- `.claude/commands/workflow/drive.md`
- `.claude/skills/managing-workflow-runs/SKILL.md` 的子动作列表
- `.claude/skills/managing-workflow-runs/reference/command-implementations/drive.md`
- `scripts/lib/workflow_command_dispatcher.py` 的 `_CMD_MAP` 和合法命令集合
- `workflow_state_validator` 对 drive 的状态矩阵，允许 drive 在 `running` / `paused` / `failed` / `awaiting_claude_action` / `approval_pending` / `completed` / `cancelled` / `cancel_requested` 下运行，因为 drive 是观察 + 推进封装，而不是单纯 continue

同时更新 `/workflow:continue` 文档：`continue` 是底层状态机恢复命令，日常推荐使用 `/workflow:drive`，因为它会在 `node_ready` 时输出 Claude Code 可执行 action package。

兼容期内 `/requirement:continue` 可以继续指向旧恢复摘要，但文档应提示新流程优先使用 `/workflow:drive`。

## 测试策略

单元测试：

1. `workflow_action` 在 `node_ready(skill)` 下生成包含 `skill`、`args`、`save_command` 的 action package。
2. `workflow_action` 在 `node_ready(agent)` 下生成包含 agent 名称的 action package。
3. `workflow_action` 在 `node_ready(prompt)` 下生成 prompt 文本。
4. `workflow_action` 在 state 非 `awaiting_claude_action` 时失败。
5. `workflow_action` 在 current_node 与末位 node_ready 不一致时失败。
6. `save_node_result.py --kind external_action_result` 与 `skill_result` 行为一致。

集成测试：

1. 使用 fixture workflow：`bash -> prompt -> bash`。
2. `workflow_drive.py` 第一次推进到 prompt 节点并输出 action package。
3. 写入 result JSON 并调用 `save_node_result.py --kind external_action_result`。
4. 再次 `workflow_drive.py`，确认进入后续 bash 并最终完成。

回归测试：

1. 原有 `skill_result` 测试必须继续通过。
2. 原有 `workflow_continue.py` main loop 行为不变。
3. 原有 `node_ready` / `RunState.rebuild` 状态恢复测试不变。

## 迁移计划

1. 新增 `workflow_action.py` 和测试，不改现有命令。
2. 给 `save_node_result.py` 增加 `external_action_result` 别名和测试。
3. 新增 `workflow_drive.py` 和 fixture 集成测试。
4. 新增 `/workflow:drive` command 文档，更新 `managing-workflow-runs` skill 的子动作表和 dispatcher 命令表。
5. 更新 drive 状态矩阵，确保已处于 `awaiting_claude_action` / `approval_pending` 时不会误调用底层 continue。
6. 更新 `/workflow:continue` 文档，说明底层命令与推荐入口差异。
7. 试跑一个现有 requirement fixture，确认 action package 对 Claude Code 足够明确。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| runner 与 scheduler 逻辑重复 | runner 只调用 `workflow_continue`，不自行选择 DAG 节点 |
| Claude Code 忘记回写 | action package 明确 `save_command`，再次 drive 时若仍 awaiting 会继续显示同一节点 |
| `skill_result` 命名误导 | 新增 `external_action_result` 别名，旧名保留 |
| JSON output 不符合节点 `output_format` | MVP 只保证 JSON object；后续可增加 output_format 校验 |
| result 文件被覆盖 | 文件路径按 `node_id` 固定；重复执行同一节点允许覆盖，因为 jsonl 才是事实源 |
| approval 被 AI 越权处理 | 继续依赖现有 approve/reject hook 和 tty guard，drive 只提示人类操作 |

## 成功标准

1. Claude Code 不需要手读 jsonl，就能知道当前要执行哪个节点。
2. 每个外部动作节点都有固定 result 文件和固定回写命令。
3. 状态不一致时 runner 明确失败，不推进。
4. `/workflow:drive` 可以把 workflow 推进到 `awaiting_claude_action` / `approval_pending` / 终态，并给出下一步。
5. 现有 `/workflow:continue`、`save_node_result.py --kind skill_result` 行为保持兼容。
