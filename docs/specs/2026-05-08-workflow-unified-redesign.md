# 工作流引擎统一改造设计

| 字段 | 值 |
|---|---|
| 状态 | DRAFT — 待用户 review |
| 版本 | v1 |
| 起草日期 | 2026-05-08 |
| 起草人 | huangjian + Claude（brainstorming 沉淀） |
| 参考实现 | Archon (`/Users/richardhuang/open-source/Archon`) |
| 影响范围 | 17 Skill / 25 Agent / 8 阶段硬编码 / 8 个 `/requirement:*` 命令 |
| 改造工作量预估 | ~5.5 周 |

---

## 0. 一句话目标

把当前"硬编码 8 阶段需求生命周期 + 多套散落 hook/gate"的工作流体系，改造成"DAG yaml-driven + 统一 `/workflow:*` 入口 + 多模板共存"的可配置引擎，参考 Archon 设计但保留 Claude Code 主对话调度形态。

---

## 1. 背景与动机

### 1.1 现状盘点

**8 阶段硬编码点（量化）**：

| 项 | 位置 | 改造成本 |
|---|---|---|
| 阶段枚举 | `meta-schema.yaml:38-47` 单一事实源 | ✅ 已配置化 |
| 阶段相邻性校验 | `phase_enum.py` 自动推导 | ✅ 已配置化 |
| 门禁 → 阶段映射 | `check_reviews.py:57-65` 硬编码 `PHASE_REQUIREMENTS` | ❌ 硬编码 |
| 产物必存性 | 分散在 8 个 checker 脚本 | ❌ 无统一表 |
| Agent → 阶段绑定 | 隐式靠 description 文本 | ❌ 无显式配置 |
| 阶段切换前置 hook | `scripts/gates/run.py` + registry.yaml | 🟡 半配置 |

**痛点**：
- 不能支持轻量需求（lite-3phase）/ 紧急修复（hotfix）等流程
- "阶段→产物→门禁→Agent" 的绑定关系散落 5+ 文件，易漂移
- `/requirement:*` 命名空间绑死，非需求 workflow（codex review-loop / release / extract-experience）无处挂载
- 多 workflow 并发跑没有统一视图

### 1.2 目标

| 目标 | 验证方式 |
|---|---|
| workflow yaml 可配置 | 改阶段顺序只改 1 个 yaml 文件，零代码改动 |
| 多 workflow 模板共存 | 至少 standard-8phase / lite-3phase / hotfix 三套 |
| 统一 `/workflow:*` 入口 | 11 个命令覆盖 run / list / status / continue / save / approve / reject / cancel / rollback / archive / submit |
| 跨会话恢复确定性 | 任意中断点，`/workflow:continue` 自动续跑无需用户告诉"刚才到哪" |
| 验证机制可组合 | output_format + when + approval + bash + critic 五种 lego |
| 节点级模型/推理档位配置 | yaml 节点字段 model/effort/thinking 覆盖工作流默认 |

### 1.3 非目标

- ❌ 多 provider 共存（MVP 仅 claude，codex/openai 后续）
- ❌ git worktree 强制隔离（用 git 分支即可）
- ❌ 独立 daemon 进程（保留 Claude Code 主对话调度形态）
- ❌ HTTP API server（无外部客户端需求）
- ❌ Web Dashboard（文件状态足够）
- ❌ PostgreSQL 持久化（文件 + jsonl 即可）

---

## 2. 参考与对照（Archon）

Archon 是 OpenAI 系（@openai/codex-sdk）+ Anthropic 系（claude-agent-sdk）双 provider 的 DAG workflow 引擎，per-run CLI 进程 + PostgreSQL，多入口（CLI / Web / Slack / Claude Code Skill）。完整调研见 brainstorming session 记录。

### 2.1 核心借鉴（直接搬）

| 设计点 | 来源 | 本项目采用 |
|---|---|---|
| DAG + 节点类型互斥 | `schemas/dag-node.ts` | ✅ |
| 三层模板发现（bundled→global→project） | `workflow-discovery.ts` | ✅ |
| 节点级 model / effort / thinking / maxBudgetUsd | `dag-node.ts:132-165` | ✅ |
| ApprovalNode + on_reject 重做循环 | `dag-executor.ts:2302-2440` | ✅ |
| 同层并发 Promise.allSettled | `dag-executor.ts:2554` | ✅（用 multi-Agent 调用） |
| 变量替换 `$nodeId.output[.field]` | `dag-executor.ts:274-325` | ✅ |
| 事件溯源跨进程恢复 | events 表 + `getCompletedDagNodeOutputs` | ✅（jsonl 替代表） |
| Loop 节点 4 种退出条件 | `loop.ts` | ✅ |
| 节点输出阈值切换 inline/外置 | 8KB 阈值 | ✅（调到 16KB） |
| Prompt 复用文件 | `.archon/commands/*.md` | ✅（叫 `prompt_file:`） |
| trigger_rule 三档（all_success/one_success/all_done） | DAG schema | ✅ |
| `--template=` 旗 + 模糊匹配 | `router.ts:223` | ✅ |
| 验证 5 lego（output_format/when/approval/bash/critic） | `maintainer-review-pr.yaml` 等 | ✅ |

### 2.2 不借鉴

| 设计点 | 不采纳原因 |
|---|---|
| PostgreSQL 持久化 | 破坏"git clone 即可工作"属性 |
| git worktree 强制隔离 | 单工程师场景过度设计 |
| 独立 CLI 进程 | 偏离 Claude Code 原生形态 |
| `archon serve` HTTP daemon | 无多客户端需求 |
| `maxBudgetUsd` 节点级硬熔断 | 当前 cost 监控不是核心痛点 |

### 2.3 Archon 的 3 层 command 启发

- 第 1 层 `.claude/commands/` — dogfood slash command（本项目对应已有）
- 第 2 层 `.archon/commands/*.md` — workflow 节点引用的 prompt 复用文件 → **本项目引入 `.claude/workflows/prompts/`**
- 第 3 层 `archon workflow run <name>` — CLI 入口 → 本项目对应 `/workflow:run <name>`

---

## 3. 总体架构

```
┌───────────────────────────────────────────────────────────────┐
│ 调度层 (Workflow Layer)                                        │
│   .claude/workflows/{requirement,review,release,...}/*.yaml    │
│   .claude/workflows/prompts/*.md  (长 prompt 复用)              │
└───────────────────────────┬────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────────┐
│ 引擎层 (Engine)                                                │
│   .claude/skills/workflow-engine/SKILL.md                      │
│   .claude/skills/managing-workflow-runs/SKILL.md (伞形)         │
│   .claude/skills/workflow-launcher/SKILL.md (关键词触发)         │
└───────────────────────────┬────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────────┐
│ 组件层 (Named Components)                                      │
│   skill: 调命名 Skill (复用现有 9 个通用 Skill)                  │
│   agent: 启 subagent (复用现有 25 个 Agent)                     │
│   prompt: 内联或 prompt_file 引用                              │
│   bash: shell 脚本                                              │
│   loop: AI 循环到条件满足                                       │
│   approval: 人工卡点                                            │
│   artifact: 产物校验（本项目特色节点）                           │
└───────────────────────────┬────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────────┐
│ 状态层 (Persistence)                                           │
│   runs/<run-id>/                                                │
│   ├── meta.yaml          快照（含 category 字段）               │
│   ├── run-state.jsonl    事件流（机器读）                       │
│   ├── process.txt        语义事件（仅 category=requirement）    │
│   ├── plan.md / notes.md 仅 category=requirement                 │
│   └── artifacts/ or output/ 视 category 而定                    │
└───────────────────────────────────────────────────────────────┘
```

**关键架构原则**：
1. **workflow.yaml 是唯一事实源**——删/改/重排节点 = 改 yaml
2. **主 Claude 既调度又执行**（保留 Claude Code 形态，无独立 daemon）
3. **统一 `/workflow:*` 入口**（无双轨命令体系）
4. **通过 `category` 字段做 workflow 分类**——需求是 workflow 的一种特化

---

## 4. 命令体系

### 4.1 统一 `/workflow:*` 入口（11 个命令）

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `/workflow:run [<name>] <args>` | 启动 workflow | `name` 缺省=默认；支持模糊匹配（`standard` → `standard-8phase`） |
| `/workflow:list [--filter=]` | 列所有 active runs | `--filter=requirement` / `--archived` |
| `/workflow:status [<run-id>]` | 查 run 状态 | `run-id` 缺省=git 分支推断 |
| `/workflow:continue [<run-id>]` | 续跑到下一停点 | 同上 |
| `/workflow:save [<run-id>] [comment]` | 写检查点 | 同上 |
| `/workflow:approve <run-id> [comment]` | 显式批准 approval 节点 | 必填 run-id |
| `/workflow:reject <run-id> --reason=<...>` | 显式拒绝（触发 on_reject） | 必填 run-id + reason |
| `/workflow:cancel <run-id>` | 终止（不可恢复） | 必填 run-id |
| `/workflow:rollback <run-id> --to-node=<id>` | 回退到历史节点 | 必填 run-id |
| `/workflow:submit <run-id>` | 触发 PR 提交子流程 | 必填 run-id |
| `/workflow:archive <run-id>` | 归档清理 | 必填 run-id |

### 4.2 自然语言路径（workflow-launcher Skill）

关键词匹配触发：

```yaml
# .claude/skills/workflow-launcher/SKILL.md
Triggers:
  "开个新需求 X" / "我要做 xxx" → /workflow:run "X"
  "跑下代码评审" → /workflow:run code-review-embedded
  "我要发版" → /workflow:run release-cut
  "继续之前的需求" → /workflow:continue
  "approve" / "approve, looks good"（在 approval 等待中）→ /workflow:approve <最近 run>
  "reject: <理由>" → /workflow:reject <最近 run> --reason=<...>
```

**关键设计原则（来自 Archon）**：
- Skill **不引入新能力**，只是把自然语言翻译成 `/workflow:*` 命令
- 多入口最终汇到同一个底层函数（避免功能漂移）

### 4.3 废弃命令

| 命令 | 处理 | 兼容期 |
|---|---|---|
| `/requirement:new` | 别名 → `/workflow:run [template]` | 3 个月 |
| `/requirement:continue` | 别名 → `/workflow:continue` | 3 个月 |
| `/requirement:status` | 别名 → `/workflow:status` | 3 个月 |
| `/requirement:list` | 别名 → `/workflow:list --filter=requirement` | 3 个月 |
| `/requirement:save` | 别名 → `/workflow:save` | 3 个月 |
| `/requirement:rollback` | 别名 → `/workflow:rollback` | 3 个月 |
| `/requirement:submit` | 别名 → `/workflow:submit` | 3 个月 |
| `/requirement:archive` | 别名 → `/workflow:archive` | 3 个月 |
| `/requirement:next` | **直接删除**（被 `:continue` 吸收） | 立即 |

兼容期内别名输出 deprecation warning，3 个月后移除。

---

## 5. 数据模型

### 5.1 ID 命名空间

**统一目录**：`runs/<run-id>/`

**ID 前缀承载 category 语义**：

| category | ID 模式 | 例子 |
|---|---|---|
| `requirement` | `REQ-{year}-{seq}` | `REQ-2026-009` |
| `release` | `REL-{year}-{seq}` | `REL-2026-002` |
| 其他 | `RUN-{date}-{time}-{hash4}` | `RUN-2026-05-08-1430-a3f2` |

### 5.2 目录结构

```
runs/
├── REQ-2026-005/                  # category=requirement
│   ├── meta.yaml                  # 含 category 字段
│   ├── plan.md                    # requirement 专属
│   ├── notes.md                   # requirement 专属
│   ├── process.txt                # requirement 专属（人读）
│   ├── run-state.jsonl            # 通用
│   ├── artifacts/                 # requirement 专属（用 artifacts/）
│   └── .run-logs/                 # 大输出外置（>16KB）
├── REQ-2026-009/
├── RUN-2026-05-08-1430-a3f2/      # category=review
│   ├── meta.yaml
│   ├── run-state.jsonl
│   └── output/                    # 通用类用 output/
└── REL-2026-002/                  # category=release
    └── ...

.claude/workflows/
├── requirement/
│   ├── standard-8phase.yaml
│   ├── lite-3phase.yaml
│   └── hotfix.yaml
├── review/
│   ├── code-review-embedded.yaml
│   ├── code-review-standalone.yaml
│   └── codex-review-loop.yaml
├── release/
│   └── release-cut.yaml
├── knowledge/
│   ├── extract-experience.yaml
│   └── generate-sop.yaml
├── pr/
│   └── pr-feedback-handle.yaml
├── assist/
│   └── general-assist.yaml
└── prompts/                        # 长 prompt 复用文件（参考 Archon .archon/commands/）
    ├── req-quality-review.md
    ├── tech-feasibility-assess.md
    └── ...
```

### 5.3 `meta.yaml` schema

**通用字段（所有 workflow 必填）**：
```yaml
run_id: REQ-2026-005
workflow_name: standard-8phase
workflow_category: requirement
workflow_status: paused          # running | paused | completed | failed | cancelled
current_node: req-quality-review
parent_run_id: null              # 嵌入式 workflow 的父 run
arguments: "支付订单状态机重构"
started_at: 2026-05-08T10:00:00Z
last_activity_at: 2026-05-08T14:23:00Z
gates_passed: [GATE-META-SCHEMA]
```

**`category=requirement` 额外字段（保留兼容）**：
```yaml
title: 支付订单状态机重构
phase: tech-research              # 兼容字段，从 current_node 反推
feature_area: payment-orders
change_type: refactor
affected_modules: [order-service, payment-gateway]
branch: feat/REQ-2026-005
reviews:
  definition: { latest: REV-..., conclusion: approved }
```

**`category=release` 额外字段**：
```yaml
release_bump: minor
target_branch: main
```

引擎按 `category` 决定处理差异。

### 5.4 `run-state.jsonl` schema

事件追加式，每行一个 JSON：

```jsonl
{"ts":"2026-05-08T10:00:00Z","type":"workflow_started","run_id":"REQ-2026-005","data":{"workflow_name":"standard-8phase","arguments":"..."}}
{"ts":"2026-05-08T10:00:01Z","type":"node_started","node_id":"req-input-normalize"}
{"ts":"2026-05-08T10:00:15Z","type":"node_completed","node_id":"req-input-normalize","data":{"output":"..."}}
{"ts":"2026-05-08T10:01:30Z","type":"approval_pending","node_id":"req-signoff","data":{"message":"...","capture_response":true}}
{"ts":"2026-05-08T14:23:00Z","type":"approval_approved","node_id":"req-signoff","data":{"comment":"approved by user"}}
{"ts":"2026-05-08T14:24:00Z","type":"loop_iteration_started","node_id":"fix-loop","data":{"iteration":1}}
{"ts":"2026-05-08T14:25:00Z","type":"loop_iteration_completed","node_id":"fix-loop","data":{"iteration":1,"output":"...","until_matched":false}}
```

13 种事件类型：

```
workflow_started | workflow_paused | workflow_completed
workflow_failed  | workflow_cancelled

node_started | node_completed | node_failed | node_skipped | node_retried

approval_pending | approval_approved | approval_rejected

loop_iteration_started | loop_iteration_completed
loop_completed | loop_max_iterations_exceeded
```

每事件至少包含：`{ts, type, run_id, node_id?, data?}`，`ts` 是 ISO 8601 UTC。

---

## 6. workflow.yaml Schema

### 6.1 顶层字段

```yaml
name: standard-8phase                          # 必填，工作流唯一标识
description: 标准 8 阶段需求生命周期             # 给人看
version: 1                                     # schema 版本

# 模板分类
category: requirement                          # requirement | review | release | knowledge | assist
default_for: requirement                       # 该 category 的默认模板

# 默认配置（节点级可覆盖）
provider: claude                               # MVP 锁 claude
model: sonnet
thinking: enabled
effort: medium

# 模板挑选辅助（loader 用，MVP 可不填）
applicable_when:
  change_type: [feature, refactor, enhancement]
  recommended: true

# 节点定义
nodes: [...]
```

### 6.2 节点类型（7 种互斥字段）

| 节点类型 | 互斥字段 | 一句话职责 |
|---|---|---|
| `skill` | `skill: <name>` | 调命名 Skill（git-feature / code-review-prepare 等） |
| `agent` | `agent: <name>` | 启 subagent（review-critic / requirement-quality-reviewer 等） |
| `prompt` | `prompt: \|<inline>` 或 `prompt_file: <path>` | 内联 prompt 或外部文件引用 |
| `bash` | `bash: \|<script>` | 跑 shell 脚本 |
| `loop` | `loop: { ... }` | AI 循环到条件满足 |
| `approval` | `approval: { ... }` | 人工卡点 |
| `artifact` | `artifact: { ... }` | 产物存在性 + schema 校验 |

### 6.3 节点公共字段

```yaml
- id: requirement-draft                        # 必填，kebab-case
  depends_on: [bootstrap]                      # 缺省=隐式接 yaml 上一节点
  when: "$gate.output.verdict == 'approved'"   # 条件路由
  trigger_rule: all_success                    # all_success | one_success | all_done
  
  # 模型/推理覆盖
  provider: claude
  model: opus[1m]
  effort: high
  thinking: { type: enabled, budgetTokens: 32000 }
  fallback_model: sonnet
  
  # 上下文与工具
  context: fresh                               # fresh | shared
  allowed_tools: [Read, Grep]
  denied_tools: [Bash]
  
  # 输出契约
  output_format:                               # JSON Schema
    type: object
    properties:
      verdict: { type: string, enum: [approved, needs-revision, rejected] }
    required: [verdict]
  
  # 健壮性
  retry:
    max_attempts: 2
    delay_ms: 3000
    on_error: transient
  idle_timeout: 300000
```

### 6.4 各节点类型字段详解

#### `prompt` 节点

```yaml
- id: req-quality-review
  prompt: |                                    # 内联（< 30 行用此）
    你是 reviewer，对 ... 做评审。
  # 或：
  prompt_file: prompts/req-quality-review.md   # 外部文件（> 100 行用此）
  
  context: fresh
  output_format: { ... }
```

`prompt` 与 `prompt_file` 互斥，loader 校验。

#### `bash` 节点

```yaml
- id: phase-transition-to-tech-research
  bash: |
    set -e
    yq e '.phase = "tech-research"' -i runs/$RUN_ID/meta.yaml
    yq e '.gates_passed += ["GATE-REQUIREMENT-SIGNOFF"]' -i runs/$RUN_ID/meta.yaml
  timeout: 30000
  depends_on: [req-signoff]
```

变量替换时**所有上游引用强制单引号转义**（`shellQuote` 同 Archon `dag-executor.ts:274`）。

#### `skill` 节点

```yaml
- id: prepare-review-scope
  skill: code-review-prepare
  args:
    mode: embedded
    feature_id: $current-feature.output.id
    diff_range: HEAD~3..HEAD
```

主 Claude 直接跑（不派 subagent，Skill 是给主 Claude 的指令书）。

#### `agent` 节点

```yaml
- id: rv-security
  agent: security-checker
  context: fresh                               # 自动派 subagent
  prompt_override: |
    针对 feature_id=$feat.output.id 做 OWASP Top 10 扫描。
  args:
    feature_id: $feat.output.id
```

引擎检测同层 ≥2 个 agent 节点 → 主 Claude 一次发出 multi-Agent 调用（同 Archon `Promise.allSettled`）。

#### `loop` 节点

```yaml
- id: testing-fix-loop
  loop:
    prompt: |
      $LOOP_PREV_OUTPUT
      修复直到 gate 通过。完成输出 "DONE"。
    until: "DONE"                              # AI 信号
    until_bash: |                              # 外部脚本（OR 语义）
      python3 scripts/gates/run.py phase-transition --check-only
    max_iterations: 3
    fresh_context: false                       # 每轮独立 subagent vs 累积上下文
    interactive: false                         # 每轮人工卡点
    gate_message: "本轮完成，approve / 反馈 / cancel"
```

4 种退出条件（OR）：
- `until` 字符串出现在输出
- `until_bash` 退出码 0
- `interactive=true` 且用户 "approve"
- `i == max_iterations`（视为失败）

**fresh_context=true 实现**：每轮派一个新 subagent（主 Claude 没有"重置自己上下文"的能力）。

**循环内变量**：`$LOOP_PREV_OUTPUT` / `$LOOP_USER_INPUT` / `$LOOP_ITERATION`。

#### `approval` 节点

```yaml
- id: req-signoff
  approval:
    message: |
      需求已起草，AI 评审：$req-quality-review.output.verdict
      Approve / Reject 给反馈 / cancel
    capture_response: true                     # 用户回复存为节点 output
    on_reject:
      prompt: |
        用户反馈：$REJECTION_REASON
        修订 $ARTIFACTS_DIR/requirement.md
      max_attempts: 3
  depends_on: [req-artifact-check]
```

执行流：
1. 写 `approval_pending` 事件 + meta.yaml `workflow_status=paused`
2. 主 Claude 输出 message，Skill 退出
3. 用户 `/workflow:approve <run-id>` / `/workflow:reject <run-id> --reason=...` / `/workflow:cancel <run-id>`
4. 拒绝时合成 prompt 节点 `<id>:on_reject:N`，AI 重做后再次进 approval（rejection_count 用尽 → workflow_cancelled）

#### `artifact` 节点

```yaml
- id: req-artifact-check
  artifact:
    must_exist:
      - $ARTIFACTS_DIR/requirement.md
    must_not_exist:
      - $ARTIFACTS_DIR/.tmp
    schema_check:
      - script: scripts/lib/check_sourcing.py
        args: [--strict, $ARTIFACTS_DIR/requirement.md]
        expected_exit_code: 0
    must_contain_sections:
      - file: $ARTIFACTS_DIR/requirement.md
        sections: [角色与场景, 验收标准, 待确认清单]
    must_match_regex:
      - file: $ARTIFACTS_DIR/requirement.md
        pattern: '^\| 角色 \|'
        min_count: 1
```

输出（`$node.output`）：
```json
{"passed": true, "checks_run": 4, "checks_failed": []}
```

实现：引擎调 `scripts/lib/run_artifact_checks.py` 执行所有 check，**纯校验，不写文件**（区别于 bash 节点）。

### 6.5 变量替换

| 变量 | 来源 | 示例 |
|---|---|---|
| `$<nodeId>.output` | 上游节点完整输出 | `$gate.output` |
| `$<nodeId>.output.<field>` | 上游 JSON 嵌套字段（解析失败返回空） | `$gate.output.verdict` |
| `$ARGUMENTS` | `/workflow:run` 后的参数 | `$ARGUMENTS` |
| `$1`...`$9` | 位置参数 | `$1` |
| `$RUN_ID` | 当前 run ID | `$RUN_ID` |
| `$ARTIFACTS_DIR` / `$OUTPUT_DIR` | 视 category | `$ARTIFACTS_DIR/requirement.md` |
| `$REPO_ROOT` | 仓库根 | `$REPO_ROOT/.claude/skills` |
| `$REJECTION_REASON` | approval 拒绝时用户反馈 | 仅 on_reject 节点可见 |
| `$LOOP_PREV_OUTPUT` | loop 上一轮输出（首轮空） | 仅 loop 节点可见 |
| `$LOOP_USER_INPUT` | interactive loop 上轮用户输入 | 仅 interactive loop 可见 |
| `$LOOP_ITERATION` | 当前轮次 | 1-indexed |
| `$LOG_DIR` | `.run-logs/` | 引擎日志目录 |

**注入防御**：
- bash 节点：所有上游引用强制 `'value'`（`'\''` 转义）
- prompt 节点：不防御（业务可控）
- 路径变量：必须落在 `$REPO_ROOT` 下，loader 强校验

### 6.6 `when` 表达式

支持 6 比较运算符（`==`、`!=`、`<`、`<=`、`>`、`>=`）+ 2 逻辑（`&&`、`||`）+ 括号。

```yaml
when: "$gate.output.verdict == 'approved'"
when: "$test.output.coverage >= 80"
when: "$gate.output.verdict == 'review' || $gate.output.verdict == 'needs_split'"
when: "$features.output.count > 0 && $design.output.complete == true"
```

未通过条件 → 节点状态 `skipped`（不是 failed）。

### 6.7 `trigger_rule` 三档

| 值 | 触发条件 | 用途 |
|---|---|---|
| `all_success`（默认） | 所有 depends_on 节点 state=completed | 普通节点 |
| `one_success` | 任一 depends_on state=completed | 容错综合（5 critic 里 1 个成就汇总） |
| `all_done` | 所有 depends_on 进入 terminal（completed/failed/skipped） | 清理节点 / 最终报告 |

### 6.8 失败传播

```
节点 state=failed
  → 下游 trigger_rule=all_success 的节点 → state=skipped
当前层继续跑完其他节点（失败隔离，不 fail-fast）
当前层结束后：
  - 还有可继续下游 → 继续推进
  - 没有可继续下游 → workflow 状态=failed，停止
```

### 6.9 retry 字段

```yaml
retry:
  max_attempts: 2          # 默认 2，0 不重试
  delay_ms: 3000           # 指数退避：delay × 2^attempt
  on_error: transient      # transient（默认）| all
```

`transient`：网络超时 / rate limit / 5xx。`fatal`（auth/quota/invalid_request）不重试。

### 6.10 节点超时

仅支持 `idle_timeout`（节点空闲时间，毫秒）。**不支持** `timeout`（总时长）—— LLM 思考时间难精确估算。

默认值：
- `prompt` / `agent` / `skill` 节点：300_000 ms
- `bash` 节点：60_000 ms
- `loop` 节点：单轮按上同；整体由 `max_iterations` 兜底

### 6.11 节点输出阈值

```
output ≤ 16KB → 直接写 run-state.jsonl 的 output 字段
output > 16KB → 写 .run-logs/<node-id>.txt
              jsonl 存 {"output_file": "..."}
              变量替换时引擎透明读文件
```

`.run-logs/` 加进 `.gitignore`。

### 6.12 `depends_on` 缺省行为

- 不写 `depends_on` → 隐式接 yaml 上一节点
- 写 `depends_on: []` → 明确无依赖（首层）
- 写 `depends_on: [...]` → 显式覆盖

**安全网**：loader 加载完写 `runs/<id>/.workflow-resolved.yaml`，把所有隐式依赖实例化为显式列表，方便调试。

### 6.13 默认值补全表

| 字段 | 默认 |
|---|---|
| `depends_on` | 上一节点 ID |
| `when` | `null`（无条件） |
| `trigger_rule` | `all_success` |
| `provider` / `model` / `effort` / `thinking` | workflow 顶层字段 |
| `context` | `shared`（prompt/loop 节点） |
| `idle_timeout` | 见 §6.10 |
| `retry` | `{max_attempts:2, delay_ms:3000, on_error:transient}` |
| `output_format` | `null` |
| `allowed_tools` / `denied_tools` | `null`（沿用 Skill/Agent 默认） |

### 6.14 loader 强校验（启动即拒）

加载 yaml 时 100% 必查：
- ✅ 节点 ID 唯一（kebab-case，1-60 字符）
- ✅ 所有 `depends_on` 引用的节点存在
- ✅ DAG 无环（Kahn 算法）
- ✅ 所有 `$nodeId.output` 引用的 nodeId 存在
- ✅ `when` 表达式语法合法
- ✅ `provider == claude`（MVP 锁死）
- ✅ 节点互斥字段七选一
- ✅ `loop.until_bash` / `artifact.must_exist` 路径必须落在仓库内
- ✅ `prompt` 与 `prompt_file` 互斥；`prompt_file` 必须在 `.claude/workflows/prompts/`
- ✅ `interactive: true` 必须配 `gate_message`

校验失败 → 引擎不启动，输出具体 yaml 行号 + 错误。

---

## 7. 引擎实现（workflow-engine Skill）

### 7.1 主流程

```
输入：run_id
  ↓
1. 加载 workflow.yaml（三层发现 + schema 校验）
2. 反扫 run-state.jsonl 重建 RunState（node_outputs Map + 当前位置）
3. 决策当前操作：
   - approval_pending → 提示用户响应，return
   - workflow_completed → 更新 meta，return
   - 其他 → 进入步骤 4
4. 执行当前层（Layer Execution）：
   a. 求值每节点的 when / trigger_rule
   b. 替换变量
   c. 决定执行方式（决策表）
   d. 跑节点 → 写 node_completed/failed
5. 进入下一层 → 回到 3
```

### 7.2 节点执行决策表

| 节点形态 | 执行方式 |
|---|---|
| `skill: xxx` | 主 Claude 直接跑（加载 SKILL.md 按指令执行） |
| `prompt:` 或 `prompt_file:` 无 `context: fresh` | 主 Claude 直接跑（继承上下文） |
| `prompt:` 或 `prompt_file:` + `context: fresh` | 派 subagent |
| `prompt:` 同层并发 ≥2 节点 | multi-Agent 一次启 N 个 subagent |
| `agent: xxx` | 派 subagent |
| `bash:` | 主 Claude 调 Bash 工具 |
| `artifact:` | 主 Claude 调 Bash 跑 `scripts/lib/run_artifact_checks.py` |
| `approval:` | 写状态文件 + 主 Claude 输出 message + Skill 退出 |
| `loop:` + `fresh_context: false` | 主 Claude 跑迭代（累积上下文） |
| `loop:` + `fresh_context: true` | 每轮派一个新 subagent |

### 7.3 同层并发实现

```
检测当前层 needs_subagent 节点 ≥ 2
  ↓
主 Claude 在同一响应里发出 N 个 Agent 工具调用：
  Agent({description, subagent_type, prompt}) × N
  ↓
Claude Code 框架天然 Promise.all 等价
  ↓
全部完成后回到主对话，混合结果（含失败的）
  ↓
引擎处理 layerResults，每节点写 node_completed / node_failed
```

### 7.4 跨会话恢复

```
用户敲 /workflow:continue [run-id]
  ↓
读 meta.yaml → run_id, workflow_name, workflow_status
  ↓
反扫 run-state.jsonl 所有事件 → 重建 RunState
  ↓
决策位置：
  - 最后是 approval_pending → 提示用户
  - 最后是 paused_in_loop → 输出 gate_message
  - 最后是 node_started 没匹配 completed → 该节点重跑
  - 当前层全部完成 → 进下一层
  ↓
主 Claude 自动接续，不需用户告诉"刚才到哪"
```

**幂等性假设**：节点跑两遍同 input 同 output。bash 节点的副作用由开发者负责（用 idempotent 命令、UPSERT 等）。

### 7.5 multi-run 隔离

每个 run 在独立目录 `runs/<run-id>/`，互不干扰：
- 主 Claude 同时跟踪 N 个 active runs
- `/workflow:list` 显示并发状态
- 引擎按 run-id 路由所有操作

主对话上下文压力估算（Opus 4.7 1M）：
- 单需求 30 节点 standard-8phase：50-100K token
- 同时 active 3 需求：150-300K token（够）

---

## 8. 节点产出验证机制（5 lego）

| 模式 | 节点配置 | 用途 |
|---|---|---|
| ① Schema 强类型 | `output_format: {type: object, properties:...}` | LLM 端结构化输出，下游 `$x.output.field` 取值 |
| ② 条件路由 | `when: "$x.output.verdict == 'approved'"` | 上游结果决定下游分支 |
| ③ 人工卡点 + AI 重做 | `approval: { on_reject: { prompt, max_attempts }}` | 人验证 → 拒绝触发 AI 重做 |
| ④ 后置文件校验 | `bash:` 或 `artifact:` 节点检查文件 | 兜底（LLM 骗 schema 但骗不了文件系统） |
| ⑤ 多 critic 并行 + 综合 | N×`agent` 同层 + 1×`agent` (`trigger_rule: one_success`) | 多视角评审 |

**5 种 lego 自由组合**——本项目 `code-review` 的 8 critic + critic 对抗 + synthesize 就是 ⑤ 的实例化。

---

## 9. 现有 Skill / Agent 的处理

### 9.1 Skill（17 个）

**8 个需求阶段 Skill 内联到 yaml**（prompt 部分抽到 `.claude/workflows/prompts/`）：
- `requirement-input-normalizer`
- `requirement-doc-writer`
- `requirement-progress-logger`
- `traceability-gate-checker`
- `code-review-prepare`
- `code-review-report`
- `task-context-builder`
- `feature-lifecycle-manager`

**9 个通用工具 Skill 保留作为节点可调用组件**：
- `git-feature` / `git-release` / `git-hotfix`
- `code-review` / `code-review-signoff`（最后一个上次决策"放弃 2"删除）
- `managing-knowledge` / `knowledge-*`
- `requirement-session-restorer`（改名为 `workflow-session-restorer`）
- `note`

`/code-review` 等命令内核改为 `/workflow:run code-review-embedded`。

### 9.2 Agent（25 个）

**全部保留**作为 yaml 节点 `agent: xxx` 可调用组件，零改动。

### 9.3 新增 Skill / 文件

```
.claude/skills/
├── workflow-engine/                           # 新增：DAG 执行核心
│   ├── SKILL.md
│   └── reference/
│       ├── node-execution-rules.md
│       ├── variable-substitution.md
│       ├── condition-evaluation.md
│       ├── topological-sort.md
│       ├── approval-state-machine.md
│       ├── loop-execution.md
│       └── examples/
├── managing-workflow-runs/                    # 新增：统一伞形 Skill
│   ├── SKILL.md
│   └── reference/
│       ├── category-rules/
│       │   ├── requirement.md
│       │   ├── review.md
│       │   ├── release.md
│       │   └── default.md
│       ├── id-generation.md
│       ├── meta-yaml-schema.md
│       └── command-implementations/
│           ├── run.md
│           ├── continue.md
│           ├── approve.md
│           └── ...
└── workflow-launcher/                         # 新增：自然语言入口
    └── SKILL.md

scripts/lib/
├── substitute_vars.py                         # 新增：变量替换
├── topological_sort.py                        # 新增：Kahn 算法
├── run_state.py                               # 新增：jsonl 读写 + RunState 重建
├── run_artifact_checks.py                     # 新增：artifact 节点 check
└── workflow_loader.py                         # 新增：yaml 加载 + 强校验
```

---

## 10. 暂停 / 恢复机制

### 10.1 5 类暂停时机

| 时机 | 风险 | 推荐度 |
|---|---|---|
| ① 隐式（Ctrl+C / 关 Claude Code） | 当前节点重跑 | 可接受 |
| ② `approval` 节点（设计鼓励） | 零风险 | ✅ 主推 |
| ③ `interactive loop` 每轮 | 零风险 | ✅ 主推 |
| ④ `/workflow:save` | 主动检查点 | UX 仪式感 |
| ⑤ workflow 终止态（completed/failed/cancelled） | 不可恢复 | 仅 rollback |

### 10.2 自动 vs 手动恢复

```
完全自动恢复（敲 /workflow:continue）：
  ✅ skill / agent / prompt / bash / artifact / loop（非 interactive）节点
  ✅ 同层并发节点（已完成跳过，未完成重跑）
  ✅ 子图（如 8 critic + synthesize 全部自动续）

需要用户响应（自动到那一步等输入）：
  🟡 approval 节点
  🟡 interactive loop

不能续跑（需 /workflow:rollback）：
  ❌ workflow_status = completed/cancelled/failed-fatal
```

### 10.3 暂停时长边界

| 边界 | 处理 |
|---|---|
| workflow.yaml 改了 | loader 校验已完成节点的 ID/depends_on 一致性，否则报错让用户决定迁移 |
| Skill / Agent 删了 | 引擎检测后报错，提示恢复或改 yaml |
| git 状态漂移 | 不强制处理；artifact 节点会重新校验 |
| 超过 30 天 | 无功能影响 |

---

## 11. 三种触发路径

| 路径 | 适合 | 例子 |
|---|---|---|
| ① 精确显式（slash） | 自动化 / 多 active runs | `/workflow:run standard-8phase "支付重构"` |
| ② 自然语言（Skill 触发） | 单 active run / 新用户 | `"开个新需求 支付重构"` → workflow-launcher 路由 |
| ③ 嵌套调用（yaml 内） | workflow 编排 | `sub_workflow: code-review-embedded` |

**所有路径汇到 `workflow-engine.start_or_continue(run_id)`**——避免功能漂移。

---

## 12. 改造路线图（5.5 周）

```
阶段 1：Schema + Loader（1.5 周）
  - workflow.yaml schema v1 定义
  - loader 实现（YAML 解析 + Zod-style 校验 + DAG 校验）
  - 三层模板发现机制
  - prompt_file 引用机制
  - 变量替换库 substitute_vars.py
  ✓ 验收：能加载 yaml 并报告语法/语义错误

阶段 2：workflow-engine Skill（1 周）
  - SKILL.md + reference/ 完整文档
  - 拓扑排序 + 节点执行决策
  - run-state.jsonl 读写 + RunState 重建
  - approval 状态机 + on_reject 重做循环
  - loop 节点完整执行
  ✓ 验收：能跑通 e2e-smoke.yaml（最小测试 workflow）

阶段 3：standard-8phase yaml 完整化（0.5 周）
  - 30+ 节点完整定义
  - 8 个需求阶段 Skill 的 prompt 抽到 .claude/workflows/prompts/
  - 老需求 meta.yaml 的 phase 字段映射逻辑
  ✓ 验收：现有 1 个老需求能用新引擎续跑

阶段 4：/workflow:* 命令 + managing-workflow-runs Skill（0.5 周）
  - 11 个新命令实现
  - 8 个 /requirement:* 别名
  - workflow-launcher 关键词触发 Skill
  ✓ 验收：用户可用新命令跑通需求生命周期

阶段 5：增加非需求 workflow（1 周）
  - lite-3phase / hotfix
  - codex-review-loop / code-review-embedded / code-review-standalone
  - release-cut
  - extract-experience / generate-sop
  ✓ 验收：3 个不同 category 的 workflow 都能跑

阶段 6：清理与文档（1 周）
  - 删除 PHASE_REQUIREMENTS / phase_enum.py
  - 删除 code_review_signoff.py（上次决策"放弃 2"）
  - 删除 /requirement:next 命令
  - CLAUDE.md / agentic-engineer-guide.md / 所有 SOP 文档更新
  - 兼容性别名 + 迁移工具
  ✓ 验收：旧文档无残留 /requirement: 引用，pre-commit hook 拦截
```

---

## 13. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 主对话上下文压力 | Opus 4.7 1M 缓解；Sonnet 200K 用户可用 `/workflow:save` 做检查点续接 |
| `fresh_context=true` 频繁派 subagent 启动开销 | 文档建议：能用 false 就用 false；仅评审/critic 类必要场景用 true |
| 节点幂等性假设失效（如 git commit） | 在 SKILL.md 强约束："bash 节点必须幂等或自带防重复" |
| workflow.yaml 修改引起的拓扑漂移 | loader 校验已完成节点 ID/depends_on 一致性，不一致报错 |
| jsonl 文件损坏 | 启动时校验 jsonl 可解析；坏行跳过并 warn；最坏退化到从头跑 |
| 兼容期内 `/requirement:*` 别名维护成本 | 3 个月固定期，过期自动删除；warning 倒逼用户迁移 |
| 用户误解 `category: requirement` 跟其他 category 的差异 | category-rules/ 下每个 category 一份 reference 文档；`/workflow:status` 输出明示 |

---

## 14. 未来扩展（不在 MVP）

| 扩展 | 触发条件 | 大致工作量 |
|---|---|---|
| `provider: codex` 支持 | 用户需要混用 GPT 系模型 | 1 周 |
| `provider: openai-direct` | 不走 Codex CLI，直调 API | 0.5 周 |
| git worktree 隔离 | 多 active runs 文件冲突 | 1 周 |
| HTTP API server（archon serve 类似） | IDE 插件 / Web UI 需求 | 2 周 |
| `maxBudgetUsd` 节点级硬熔断 | cost 监控痛点 | 0.5 周 |
| 多 provider 混用（同 yaml 内 claude + codex） | 同 codex 支持 | +0.5 周 |
| Web Dashboard | 团队共享视图 | 4 周 |
| `--no-start` 旗（创建不启动） | 批量预创建需求 | 0.5 天 |

---

## 15. 决策矩阵汇总

| 决策项 | 选择 | 锁定时间 |
|---|---|---|
| 改造野心 | DAG 引擎 + 多模板共存 | 2026-05-08 |
| 执行模型 | 主 Claude 会话调度（保留 Claude Code 形态） | 2026-05-08 |
| MVP 模板数量 | 1 套 standard + 扩展点文档化 | 2026-05-08 |
| 重构边界 | 需求阶段 Skill 内联 / 通用 Skill + Agent 全保留 | 2026-05-08 |
| 状态文件 | run-state.jsonl 新增 + process.txt 保留 | 2026-05-08 |
| Provider 范围 | 仅 claude（codex 后续） | 2026-05-08 |
| `tty 双校验` | 不保留（"放弃 2"决策） | 2026-05-08 |
| 命令体系 | 统一 `/workflow:*`，废弃 `/requirement:*`（3 月兼容期） | 2026-05-08 |
| 目录统一 | `runs/<id>/`，前缀 REQ-/RUN-/REL- 承载 category 语义 | 2026-05-08 |
| meta.yaml | 通用核心 + category 差异化字段 | 2026-05-08 |
| 单一伞形 Skill | `managing-workflow-runs` | 2026-05-08 |
| approve/reject 双通道 | 主对话自然语言 + slash 显式 | 2026-05-08 |
| `depends_on` 缺省 | 隐式接 yaml 上一节点 | 2026-05-08 |
| 输出阈值 | 16KB（Archon 是 8KB） | 2026-05-08 |
| `applicable_when` | schema 保留 MVP 不填 | 2026-05-08 |
| Prompt 复用 | `.claude/workflows/prompts/` + `prompt_file:` 字段 | 2026-05-08 |
| 节点类型数量 | 7 种（skill/agent/prompt/bash/loop/approval/artifact） | 2026-05-08 |
| 同层并发 | multi-Agent 调用 | 2026-05-08 |

---

## 16. 已检讨的设计 self-review

按 brainstorming skill 的 self-review checklist：

| 检查项 | 状态 |
|---|---|
| 占位符（TBD/TODO/vague） | ✅ 全部具体 |
| 内部一致性（架构 vs 字段定义） | ✅ 一致 |
| 范围检查（单 plan 可执行 vs 需要分拆） | ✅ 6 阶段可执行（约 5.5 周） |
| 模糊检查（同一需求两种解读） | ✅ 已逐项明确 |

**已识别的潜在歧义并解决**：
- "需求"vs"workflow"边界：通过 `category` 字段统一架构层 + 业务语义保留
- approve/reject 自然语言 vs slash：双通道并存，最终汇到同一函数
- `prompt:` vs `prompt_file:`：互斥字段 + loader 校验
- `fresh_context` 在主 Claude 模式下：自动派 subagent，schema 透明

---

## 17. 后续决策

需要用户 review 本 spec 后决定的 2 件事：

1. **是否走 `/requirement:new` 流程承载这次改造？**
   - 走：有完整需求生命周期追溯（dogfood 验证）
   - 不走：本 spec 直接进入实现，节奏快但缺验收链
   - 建议：走（既然这次改造的目的就是改这套，正好用现有版本验证）

2. **MVP 是否真只做 1 套 standard 模板？**
   - 是：周期 5.5 周，验证基础 schema
   - 否：MVP 含 lite + hotfix，周期 7 周
   - 建议：是（先验证再扩展，避免"建造太多没用的东西"）

---

## 18. Brainstorming 沉淀来源

本 spec 是 2026-05-08 brainstorming session 的设计沉淀，覆盖：
- Archon 项目全方位调研（执行模型 / 多模板 / 持久化 / 同层并发 / ApprovalNode / 变量替换 / Codex provider / Claude Code 集成）
- 本项目硬编码点盘点
- 7 种节点类型 + 5 种验证 lego
- Loop 节点完整状态机
- 命令体系演化（双轨 → 统一）
- 暂停 / 恢复语义

完整对话过程不入仓库，仅沉淀决策结论到本文档。
