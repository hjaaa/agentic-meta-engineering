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
feature_id: F-xxx
你是 feat/req-<REQ-ID> 分支上的 feature 实现者。当前任务 F-xxx · <title>。

## 上下文（由 task-context-builder 产出，只含当前 feature 相关信息）

<粘贴 task-context-builder 输出全文>

## 你的任务

1. 按上方上下文实现 F-xxx，严格限制在以下触及范围内（与 task .md frontmatter touches 一致）：
   <粘贴 touches 字段；若为空数组写"未声明 touches，保守处理：仅改与本 feature 直接相关的文件；任何越界写入会被 touches_guard.py 软记入 receipt">

2. 实现规范严格遵守（仓库根 CLAUDE.md + 项目 CLAUDE.md 已加载）：
   - 小步提交，先最小可行
   - 单方法 ≤ 80 行
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

6. **写 receipt.json**（commit 之前或之后皆可，与对话回执同步——回执说 DONE 就要写 status=DONE）：

   路径：`requirements/<REQ-ID>/artifacts/tasks/<F-xxx>.receipt.json`
   schema：`context/team/engineering-spec/receipt-schema.yaml`（11 必填字段）
   该文件在 touches_guard 白名单（`_is_process_artifact` 第 1 类），写不触发越界。

   DONE 示例：
   ```json
   {
     "schema_version": "1.0",
     "feature_id": "F-xxx",
     "status": "DONE",
     "commit_sha": "<7-40 位 sha 或 HEAD>",
     "files_changed": ["相对仓库根的文件路径列表"],
     "test_summary": "60 passed in 1.2s（pytest）或 N/A（纯数据/yaml 改造）",
     "touches_violations": [],
     "concerns": [],
     "missing_context": "",
     "block_reason": "",
     "timestamp": "2026-05-11T20:33:25+08:00"
   }
   ```

   字段约定（来自 receipt-schema.yaml conditional_required）：
   - `status=DONE` → `concerns` 必须为空 list；`missing_context`/`block_reason` 留空字符串
   - `status=DONE_WITH_CONCERNS` → `concerns` 必须非空 list
   - `status=NEEDS_CONTEXT` → `missing_context` 必须非空字符串
   - `status=BLOCKED` → `block_reason` 必须非空字符串
   - `touches_violations` 由 touches_guard hook 维护；subagent 写时若文件已存在则先 read，保留 hook 已 append 的元素，仅覆盖其余字段（_read_receipt_from_fd 已保证 merge 语义）

7. 完成后按下方状态契约回执（回执内容与 receipt.json 字段一一对应）。

## 回执状态契约

以**下列四选一**开头，再附详情：

- `DONE`：实现完成，测试通过，已 commit，receipt.json 写完。附 commit SHA、改动文件列表、测试结果、receipt.json 路径。
- `DONE_WITH_CONCERNS`：完成但有疑虑（如发现设计疏漏、边界不清），receipt.status=DONE_WITH_CONCERNS 且 concerns 列表已填。附疑虑清单。
- `NEEDS_CONTEXT`：缺关键上下文无法继续，receipt.status=NEEDS_CONTEXT 且 missing_context 已填。明确说缺什么。
- `BLOCKED`：无法完成，receipt.status=BLOCKED 且 block_reason 已填。说明根因（技术阻塞 / 需求不清 / 触及范围不够）。

禁止无状态开头的自由散文回执；禁止回执 DONE 但不写 receipt.json（phase-transition / submit 时 GATE-POST-DEV-RECEIPT 按 schema 全集校验会硬挡）。
```

## 回执处理

| 状态 | 主 Agent 动作 |
|---|---|
| `DONE` | 转入"完成触发"流程（`python3 scripts/gates/run.py --trigger=post-dev` + `/code-review`，见 `SKILL.md`） |
| `DONE_WITH_CONCERNS` | 先把疑虑清单给用户看，用户判断：接受疑虑继续走完成流程，或派修复 subagent |
| `NEEDS_CONTEXT` | 补充缺失上下文（可能需要用户回答），**同模型重派**；不要主 Agent 代替 subagent 写代码 |
| `BLOCKED` | 三选一：(1) 技术阻塞 → 升级模型档位重派；(2) 需求不清 → 问用户；(3) 触及范围不够 → 与用户协商扩大 `touches` 或拆子 feature。**禁止原模型原上下文重试**。 |

## 红线

- ❌ 禁止主 Agent 代替 subagent 直接写代码（除非用户明确要求"别派 subagent，我/你直接写"）
- ❌ 禁止同时派多个 implementer subagent（保守档约束；多 feature 仍串行逐个做）
- ❌ 禁止把整份 `detailed-design.md` / 整份 `features.json` 塞进 prompt——必须走 `task-context-builder` 精简
- ✅ 每次派发前读最新 task 文件（状态可能被 `/requirement:rollback` 改过）
- ✅ 每次派发都在 `process.txt` 留一行 `[development] F-xxx 派发（model=<x>）`

### 派发 Prompt 首行格式红线（D-005 #3 / D-007）

`feature_id: F-xxx` 必须**独占 prompt 首行**，行首不能有任何前缀：

- ✅ 合法：`feature_id: F-007`（第 1 行就是这一行）
- ❌ 非法：`# feature_id: F-007`（加了 `#` 前缀）
- ❌ 非法：`DISPATCH: feature_id: F-007`（嵌在其他内容同行）
- ❌ 非法：首行是任何其他内容，`feature_id: F-007` 出现在第 2 行以后（parse_feature_id 只扫前 5 行，但首行约束是硬规范）

**根本原因**：`dispatch_precheck.py` 用正则 `^feature_id:\s*(F-\d{3})\s*$`（MULTILINE）解析；任何前缀都会导致 regex 失败 → `parse_feature_id` 返回 None → fail-open 放行，派发链三校验（B-1/B-2/B-3）形同虚设。（来源：D-005 #3 + D-007，详见 requirements/REQ-2026-008/plan.md）

### Rev N 修复派发的特殊要求（D-014 / trend-G-meta 终结经验）

**触发场景**：仅适用于 `/code-review` 评审给出 `needs_attention` / `blocked` 后派 **rev2 / rev3 修复 subagent** 的场景。首次派发（rev1）不适用；`NEEDS_CONTEXT` / `BLOCKED` 重派走原回执处理流程不适用。

**硬规则**：rev N 修复派发的 prompt **必须**显式包含一条指令：

> **rev N-1 keep finding 修复后必须全文搜同模式 + 同 helper 风格不一致**——不许"只改 reviewer 报告点出的具体行"。

**展开为可执行动作（subagent 必须做）**：

1. **同模式扫描**：修一处 `yaml.safe_load` 缺 try/except → grep 全文件 `yaml.safe_load` + `json.loads`，看是否还有同模式遗漏
2. **同 helper 风格扫描**：修一处 ValueError 消息缺 path → grep 该函数 / 同模块的所有 `raise ValueError`，看是否模板一致
3. **同语义类别区分**：明确区分"任务定义边界内的同模式"（必修）和"任务定义边界外的相邻代码"（不修但 notes 备注）——避免 scope 蔓延但消除一致性盲区

**违反后果**：人检查发现违规 → rev N+1 review 把"修复反引入新问题 / 风格双标"当 keep finding 计入下轮 → 触发 `trend-G-meta` 反模式（rev1 修复反引入 → rev2 修一项又引入新一项的恶性循环）。

**历史教训（trend-G-meta 演进）**：

| 范围 | rev1 → rev2 行为 | trend-G-meta 状态 |
|---|---|---|
| F-009 rev1 → rev2 | 修复反引入（修一项又引入新一项） | 起点 |
| F-010 rev1 → rev2 | 同模式复发 | 加剧 |
| F-011 rev1 → rev2 | 3 minor 自引入（docstring + 风格双标 + 模板三分） | 三连 |
| **F-011 rev2 → rev3** | **3 项 minor 全闭合 + 0 自引入新 minor**（dispatch prompt 加本规则后） | **首次终结** |

**根本原因**：reviewer 报告通常是"指出具体行"，subagent 默认按字面理解"修这几行"——但 rev1 引入的"风格不一致"是横向蔓延的（同函数 / 同模块 / 同 helper），仅修被指出的具体行后剩余蔓延实例会在 rev N+1 被新 reviewer 检出。预防成本（一句 dispatch prompt 指令）远低于事后修复成本（数小时三方裁决）。

**关联工程动作**：

- 主 Agent 派发 rev2/rev3 时，prompt 模板末尾追加该指令
- review-critic 判定 finding 时，把"既有 vs rev N 引入"的区分基于 `git blame` 而非 reviewer 措辞
- Judge 处置既有问题时，drop 而非 follow-up——避免 trend monitor 信号被既有问题污染

（来源：D-014 + F-011 rev3 经验总结，详见 requirements/REQ-2026-009/plan.md）
