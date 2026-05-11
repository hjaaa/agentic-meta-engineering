---
name: workflow-engine
description: workflow-engine 引擎核心 Skill。负责 workflow yaml 加载校验、jsonl 反扫重建 RunState、节点拓扑排序与变量替换、artifact 节点产出验证。被 `/workflow:run` / `/workflow:continue` 等命令使用；本 Skill 不直接面对用户。
---

# workflow-engine

## 职责（节点派发决策的"做什么"）

把一份 workflow yaml + 一个 run-state.jsonl 翻译成"下一步该跑什么"。

| 模块 | 入口 | 输出 |
|---|---|---|
| `workflow_loader.py` | `load_workflow(path)` | `LoadResult{workflow, report, source_path}` |
| `workflow_loader.py` | `discover_workflows(...)` | `dict[name, DiscoveredWorkflow]` 三层模板发现 |
| `topological_sort.py` | `topological_layers(nodes)` | `[[layer0_ids], [layer1_ids], ...]` |
| `substitute_vars.py` | `substitute_vars(text, node_outputs, env, escape_for_bash)` | `str` 替换后文本 |
| `run_state.py` | `read_events(path)` / `RunState.rebuild(path)` / `append_event(path, event)` | jsonl 安全读写 + RunState |
| `run_state.py` | `_resolve_run_dir(run_id)`（内部，loader 调用） | `Path`：先 `requirements/<id>/`，否则 `runs/<id>/`（D-007） |
| `run_artifact_checks.py` | CLI：`python3 scripts/lib/run_artifact_checks.py <node-yaml.json>` | exit 0 / 1 + 失败明细 |

## 决策表（spec §7.2）

| 节点形态 | 派发方式 |
|---|---|
| `skill: xxx` | 主 Claude 直接跑（加载 SKILL.md 按指令执行） |
| `prompt:` / `prompt_file:` 无 `context: fresh` | 主 Claude 直接跑（继承上下文） |
| `prompt:` / `prompt_file:` + `context: fresh` | 派 subagent |
| `agent: xxx` | 派 subagent |
| `bash:` | 主 Claude 调 Bash 工具 |
| `artifact:` | 主 Claude 调 Bash 跑 `run_artifact_checks.py` |
| `approval:` | 写状态文件 + 输出 message + Skill 退出 |
| `loop:` + `fresh_context: false` | 主 Claude 跑迭代（累积上下文） |
| `loop:` + `fresh_context: true` | 每轮派一个新 subagent |

详细派发链路参见 `reference/dispatch-decision.md`。

## 错误码（W000~W153，14 类）

| 范围 | 含义 |
|---|---|
| W000 | yaml 文件不存在 |
| W001 | yaml 解析失败 / 顶层非 mapping |
| W100 | schema 缺必填字段（顶层 / 节点 / loop / approval / retry 等） |
| W110 | 节点同时声明 ≥2 个互斥类型字段（skill/agent/prompt/bash/loop/approval/artifact/sub_workflow） |
| W111 | 节点未声明任一类型字段 |
| W112 | 节点 ID 重复 |
| W120 | DAG 存在环 |
| W121 | depends_on 引用了未定义的节点 |
| W130 | when 表达式语法非法 |
| W131 | `$nodeId.output` 引用了不存在节点 |
| W140 | prompt 与 prompt_file 互斥违反（含 loop.prompt / loop.prompt_file） |
| W141 | prompt_file 路径不在 `.claude/workflows/prompts/` 内 |
| W142 | prompt_file 引用的文件不存在 |
| W150 | sub_workflow 嵌套深度 > 2 |
| W151 | sub_workflow 路径未找到 |
| W152 | sub_workflow 循环引用 |
| W153 | sub_workflow 解析失败 / 默认值补全错 |

## 字段优先级（spec §6.13 / 详细设计 §2.2.1）

`yaml workflow 节点字段` ＞ `prompt frontmatter` ＞ `workflow 顶层默认`。冲突时以 yaml 为准并 loader 输出 warning（不报 error）。

## RunState 重建（spec §5.4 / §13）

反扫 jsonl 重建 `RunState{node_outputs, current_node, state, ...}`。

兜底规则：
- 最后一行损坏 → 跳过 + warn（spec §13）
- `node_started` 无对应 `node_completed` → 视为残缺对、节点状态 = running（重启时该节点重跑）
- jsonl 写入用 `fcntl.LOCK_EX` + `O_APPEND` 原子追加

事件枚举见 `reference/dispatch-decision.md`。

## 不在 F-001 范围

- 主流程 main loop（spec §7.1）—— 由 F-002+ 实现
- 节点真正执行（subagent 派发 / loop 控制 / approval 状态机）—— 由 F-002+ 实现
- 命令实现（`/workflow:run` 等 9 命令）—— 由 F-005~F-007 实现

F-001 只交付：可加载 + 强校验 yaml + 反扫 jsonl + RunState 重建 + 拓扑排序 + 变量替换 + artifact_checks 节点执行器。
