# 溢出区三文件重定义 · 设计

- **日期**：2026-04-24
- **状态**：Proposed（待用户审阅）
- **背景文档**：`context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md` §6

## 1. 背景与问题

当前三层记忆架构（工作记忆 → 溢出区 → 长期记忆）在溢出区定义了四个文件 + 一份工具日志：

- `meta.yaml`：阶段元数据
- `process.txt`：**混杂承载** phase-transition / review / gate / decision / issue / blocker / save / SESSION_END / tool= 9 种事件
- `process.tool.log`：v2 分层下工具调用日志（Hook 写）
- `notes.md`：随手记
- `plan.md`：目标 / 范围 / 里程碑 / 风险

下游项目反馈的问题：

1. **process.txt 噪音过重**：`auto-progress-log` Hook 每次 Edit/Write/Bash 都追加一行，每次需求产生数百到数千行 `tool=Edit` / `tool=Bash`，淹没语义事件，session-restorer tail 50 行时信号密度极低
2. **process.tool.log 是补丁**：为解决噪音问题加了 v2 `split` 分层，但带来 `log_layout` 字段的 v1/v2 分支逻辑，复杂度外溢到 Skill 和 Hook
3. **plan.md 缺失决策载体**：需求周期内的关键决策（架构 / 契约 / 选型）目前散落在 `process.txt [decision]` 行中，tail 走 50 行后就找不到，也无法跟踪"D-002 废弃了 D-001"这类演进关系
4. **process.txt 职责不清**：既是"进度节点"，又是"评审结论"，又是"决策记录"，再加工具噪音，实际用途没有一个清晰的 slogan

## 2. 重定义目标

三个文件各自一句话：

| 文件 | 新 slogan |
|---|---|
| `process.txt` | 做到哪了 + 遇到了什么阻塞 |
| `notes.md` | 过程中发现的经验 + 待沉淀的知识 |
| `plan.md` | 当前计划 + 决策记录 |

附带产物：

- 删除 `process.tool.log` 与 `log_layout` 分层机制
- 删除 `auto-progress-log.sh` 和 `stop-session-save.sh` 两个 Hook
- `plan.md` 新增结构化「决策记录」段（ADR 小卡集）

## 3. 三文件职责（规范级定义）

### 3.1 process.txt — 时间线状态事件流

**语义**：时间线上发生过的、对**推进/停滞**有意义的事件流。

**写入形态**：append-only，时间戳行。

**格式**：

```
YYYY-MM-DD HH:MM:SS [phase] [tag] 简述
```

**事件标签白名单**：

| Tag | 含义 | 触发方 |
|---|---|---|
| `[phase-transition]` | 阶段切换 | `managing-requirement-lifecycle` → logger |
| `[save]` | 用户显式存档节点 | `/requirement:save` → logger |
| `[review:approved|needs_revision|rejected]` | 评审结论 | 评审 Agent → logger |
| `[gate:pass|fail]` | 门禁结果 | `managing-requirement-lifecycle` → logger |
| `[blocker]` | 阻塞发生：现象 + 初步判断/下一步 | 主 Agent → logger |
| `[blocker-resolved]` | 阻塞解除：根因 + 解决方式 | 主 Agent → logger |

**硬约束**：

- 每行 ≤ 100 字符；阻塞展开超长就拆多条追加
- `phase` 字段必须与 `meta.yaml.phase` 一致（phase-transition 事件单次例外）
- 时间戳：Asia/Shanghai 时区，`TZ=Asia/Shanghai date +"%Y-%m-%d %H:%M:%S"`
- 禁止覆盖写入，禁止预计算时间戳

**唯一写入通道**：`requirement-progress-logger` Skill。删除 Hook 后无其他写入路径。

### 3.2 notes.md — 跨需求可复用知识池

**语义**：跨需求可复用的发现。是 `/knowledge:extract-experience` 的原料池。

**写入形态**：append-only，Markdown 无序列表。

**格式**：

```markdown
- [YYYY-MM-DD HH:MM:SS] [phase] <内容>
```

**内容类别**（语义清单，不强制分段）：

- 踩过的坑
- 验证过的假设 / 被推翻的假设
- 工具/框架细节
- 待澄清清单

**判断口诀**：「这条将来会被 `/knowledge:extract-experience` 提到 `context/team/experience/` 吗？」会 → notes.md。

**写入通道**：

1. `/note <内容>` 命令（直接 append，不委托 Skill）
2. 主 Agent 自主识别"可复用经验"时追加

### 3.3 plan.md — 活档案（快照 + 决策流水）

**语义**：本需求的活档案——当前计划快照 + 所有关键决策的 ADR 流水。

**写入形态**：

- 上半（目标/范围/里程碑/风险）：**可覆盖**，主 Agent 阶段对齐时刷新
- 下半（决策记录）：**append-only**，每个决策一个小节

**结构**：

```markdown
# <REQ-ID> · <标题>

## 目标
（一句话）

## 范围
- 包含：
- 不包含：

## 里程碑
| 阶段 | 预期完成 |
|---|---|
| definition | |
| tech-research | |
| outline-design | |
| detail-design | |
| task-planning | |
| development | |
| testing | |

## 风险
- 风险 1：描述 / 应对

---

## 决策记录

<!--
记录对本需求架构、契约、工期、依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
-->

### D-001 <决策标题>
- **Context**：做决策时的背景/约束
- **Decision**：选了什么，没选什么
- **Consequences**：好的后果、不好的后果
- **时间**：YYYY-MM-DD HH:MM:SS
- **Supersedes**：D-NNN（废弃前一决策时才有）
```

**ADR 写入规则**：

- 新决策 append 新 section（D-NNN 自增，不复用）
- 废弃旧决策**不回删**，新开一条带 `Supersedes: D-NNN`
- **哪些决策必须写 ADR**：影响架构 / 契约 / 工期 / 依赖的选择
- **哪些不写**：目录命名、纯文档风格、临时测试策略
- **兼容老 plan.md**：若目标 plan.md 没有「## 决策记录」标题，追加第一条 ADR 时一并补上该标题 + HTML 注释块

**写入通道**：主 Agent 在决策发生时 append，不走 Skill。

## 4. 写入通道总览

```
┌─ process.txt ─────────────────────────────────────────────┐
│  唯一写入：requirement-progress-logger Skill              │
│  调用方：                                                  │
│    - managing-requirement-lifecycle                        │
│      （phase-transition / gate:pass|fail）                 │
│    - /requirement:save（save）                             │
│    - 评审 Agent（review:xxx）                              │
│    - 主 Agent（blocker / blocker-resolved）                │
└───────────────────────────────────────────────────────────┘

┌─ notes.md ────────────────────────────────────────────────┐
│  通道 1：/note <内容>（直接 append）                       │
│  通道 2：主 Agent 自主 append                              │
└───────────────────────────────────────────────────────────┘

┌─ plan.md ─────────────────────────────────────────────────┐
│  通道 1：主 Agent 阶段对齐时覆盖上半（目标/范围/里程碑/    │
│          风险）                                            │
│  通道 2：主 Agent 决策时 append 一个 ### D-NNN section     │
└───────────────────────────────────────────────────────────┘
```

## 5. 主 Agent 的 blocker 行为约定

不新建命令。写进 `managing-requirement-lifecycle` 参考文档。

**触发 `[blocker]`**（满足任一则主 Agent 主动委托 logger 写入）：

- 用户明确说"我卡住了" / "不知道怎么办" / "这里过不去"
- 主 Agent 连续 2 次（含）以上尝试同一问题未解决
- 外部依赖不可用（接口超时、文档缺失、授权问题）

**触发 `[blocker-resolved]`**：

- 用户说"搞定了" / "解决了" / "可以继续了"
- 主 Agent 验证问题消失（重跑成功、接口通了）

**格式约束**：

- blocker：`[blocker] <现象 30 字内> / <初步判断或下一步>`
- blocker-resolved：`[blocker-resolved] <根因或解决方式>`

**判断原则**：不确定是否要记时**倾向写**。漏记比误记代价高。

## 6. 组件改动清单

### 6.1 Skill 改动（4 个）

| Skill | 改动 |
|---|---|
| `requirement-progress-logger` | 更新事件标签白名单（删 SESSION_END / tool= / decision / issue，新增 blocker / blocker-resolved）；删除 log_layout 分支逻辑；写入目标固定为 process.txt |
| `requirement-session-restorer` | 删 process.tool.log 可选读取；删 log_layout 判断；删 SESSION_END 过滤；新增"读 plan.md 决策记录段取最近一条 ADR"写入恢复摘要 |
| `managing-requirement-lifecycle` | 审核所有 process.txt 写入点收敛到 logger；补 blocker 行为约定段 |
| `/note` 命令 | 命令体不变；`.claude/commands/note.md` 文档补充"blocker 不走 /note，交由主 Agent 委托 logger" |

### 6.2 模板改动（2 个）

- `plan.md.tmpl`：追加「## 决策记录」段 + 一个空 ADR 骨架
- `meta.yaml.tmpl`：删除 `log_layout: split` 字段

### 6.3 Hook 删除（2 个）

- `.claude/hooks/auto-progress-log.sh` — 删文件
- `.claude/hooks/stop-session-save.sh` — 删文件
- `.claude/settings.json` — 移除这两个 Hook 的 PostToolUse / Stop 注册
- `protect-branch.sh` 保留

### 6.4 配置清理

- `.gitignore` — 移除 `process.tool.log` 的 ignore 条目

### 6.5 spec 主文档同步

`context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md`：

- §6.1 三层记忆结构图 — "四个文件" → "三个文件 + 一份元数据"
- §6.2 重写为"三个溢出文件"，删 process.tool.log 行，删布局切换段
- §6.3 process.txt 格式 — 更新事件标签白名单
- §6.4 跨会话恢复流程 — 删 process.tool.log tail 步骤
- §6.6 .gitignore 策略 — 删 process.tool.log 相关说明
- §7.1 Hook 清单 — 从 3 个减到 1 个（保留 protect-branch）

## 7. 老需求兼容策略

**原则**：规范换新，历史文件留原样，**不回刷**。

| 情况 | 处理 |
|---|---|
| 老 process.txt 含 `tool=` / `SESSION_END` / `[decision]` / `[issue]` 行 | 保留，不动 |
| 老 process.tool.log 文件 | 保留文件；仅从 .gitignore 移除条目 |
| 老 meta.yaml 含 `log_layout` 字段 | 保留，Skill 不再读 |
| 老 plan.md 无「决策记录」段 | 保留；主 Agent 首次追加 ADR 时顺便补上 `## 决策记录` 标题 |
| 老 notes.md | 不变，格式一致 |

**显式不做**：

- 不写迁移脚本回刷老需求
- 不写"旧格式 warning"
- session-restorer 读老文件时遇到非白名单 tag 直接忽略，不报错

**理由**：老需求多数已 testing 或合并，回刷收益低、风险高。

## 8. 错误处理

**Skill 层面**（`requirement-progress-logger`）：

- 目录/文件不存在 → 创建后再写
- meta.yaml.branch 匹配不到当前分支 → stderr warning，不写入，但不中断主流程
- 时间戳命令失败 → 降级 Python `datetime.now(tz)`，时区仍为 Asia/Shanghai
- phase 字段缺失 → 写入 `[unknown]`，不阻断

**主 Agent 层面**：

- blocker 判断不确定时倾向写
- 连续同类 blocker 合并成一条

**不做的防御**：

- 不校验 `[tag]` 白名单（规范问题，不是运行时问题）
- 不校验行长度

## 9. 验证方式

**规范一致性**：

```bash
grep -oE '\[(phase-transition|save|review:\w+|gate:\w+|blocker|blocker-resolved)\]' \
  context/team/engineering-spec/specs/*.md \
  .claude/skills/requirement-progress-logger/SKILL.md | sort -u
```

**Hook 已删**：

```bash
test ! -f .claude/hooks/auto-progress-log.sh
test ! -f .claude/hooks/stop-session-save.sh
! grep -q 'auto-progress-log\|stop-session-save' .claude/settings.json
```

**端到端冒烟**：

1. `/requirement:new 测试` → process.txt 应有 `[phase-transition]`，**无** `tool=`
2. 改文件 → process.txt **不增行**
3. `/requirement:save 测试节点` → 多一条 `[save]`
4. 模拟 blocker → 多一条 `[blocker]`，notes.md 不变
5. 关闭再 `/requirement:continue` → 恢复摘要无 SESSION_END 噪音、能识别 ADR 最近一条

## 10. 回滚策略

一个 PR 打包。回滚 = `git revert <merge_commit>`。

**回滚后**：

- Hook 恢复，继续写 process.tool.log / SESSION_END
- 老需求 revert 期间产生的新格式 process.txt 行与恢复后 Hook 共存于同一文件，不互斥
- 已追加的 ADR 小卡保留（老逻辑不读就不读）

**不回滚的**：

- revert 期间 `process.tool.log` 丢失的内容永久丢失（代价可接受）

## 11. 风险清单

| 风险 | 影响 | 应对 |
|---|---|---|
| 主 Agent 忘记写 blocker | 过程不可追溯 | 行为准则写进 Skill 参考文档；`/requirement:save "[blocker] ..."` 可兜底 |
| 老需求的 session-restorer 见到 `[decision]` 不知归属 | 恢复摘要出现"未知 tag" | 非白名单 tag 直接忽略，不报错 |
| spec 文档和 Skill 不同步 | 规范漂移 | 本次 PR 强制一并改；长期由 `auxiliary-spec-checker` 做规范审查 |
| 用户习惯了老 process.txt 的完整日志 | 过渡期不适 | 在 spec §6.2 注明"工具调用不再记录、请用 git log 回看" |

## 12. 决策要点回顾

本次 brainstorming 的关键选择（供后续追溯）：

- **Q1**：plan.md 决策记录形态？ → **B. 结构化 ADR 小卡**
- **Q2**：process.txt 形态？ → **A. 保留追加式时间戳日志，收窄事件集合**
- **Q3**：review/gate 事件归属？ → **A. 留在 process.txt（进度判定）**
- **Q4**：notes.md 与 plan.md 决策边界？ → **A. 严格二分（可复用知识 vs 本需求选择）**
- **Q5**：blocker 归属？ → **process.txt（符合 slogan "遇到了什么阻塞"）**
- **Q6**：SESSION_END 保留？ → **删除（零信息量）**
- **Q7**：工具日志保留？ → **删除 process.tool.log 与 auto-progress-log Hook（噪音源）**
