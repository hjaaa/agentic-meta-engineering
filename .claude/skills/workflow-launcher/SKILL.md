---
name: workflow-launcher
description: 用户用自然语言描述意图（继续/审/新建/批准/驳回/发版）时，按 D-008 三步仲裁翻译为 /workflow:* 命令并调用
---

## 什么时候用

用户用口头自然语言表达工作流相关操作意图时，例如：
- "继续之前的需求"、"接着做"
- "帮我 code review 一下"、"跑下代码评审"
- "开个新需求：xxx"、"新建需求"
- "approve"、"批准"、"通过"
- "reject: 理由太弱"、"不通过"、"驳回"
- "我要发版"、"打版本"（Post-MVP）

**本 Skill 仅做意图翻译**，不执行命令，不改写 RunState。翻译结果：

```
(command, args, conflict)
```

若 `conflict` 非空，则向用户 ask 并等待二次输入（不引入轮次状态）。
若三项均为 None，表示本 Skill 不接管，直接透传给正常对话。

## 三步仲裁逻辑（D-008）

### Step 1 — state tiebreaker

扫描活跃 run 列表，若存在任何 `state == "approval_pending"` 的 run，则先尝试在 `approve` / `reject` 两类关键词中匹配。命中即立即返回，跳过后续步骤。

### Step 2 — 最长匹配（贪婪）

对所有关键词按 `length` 降序排列，取所有命中。
取最长那条（`hits[0]`）。

### Step 3 — 等长冲突兜底

若命中列表最头部两条 `length` 相等，视为等长冲突，不擅自决策。
向用户输出 ask 模板（见下）并等待二次澄清。

**等长冲突 ask 模板**：

```
我同时检测到以下 N 个意图（关键词长度都为 K）：
  1. "<kw1>" → <command1>
  2. "<kw2>" → <command2>
  ...
请明示要执行哪一个，或换一种说法。
```

## 关键词与路由

详细关键词清单、长度排序表、匹配语义见：
→ [`reference/keyword-matching.md`](reference/keyword-matching.md)

核心匹配逻辑实现：`keyword_matcher.py`（本目录）

## 调用下游

翻译成功后，调用对应的 `/workflow:*` 命令：

| 类 | 映射命令 |
|---|---|
| continue | `/workflow:continue` |
| review | `/workflow:run code-review-embedded` |
| new | `/workflow:new standard-8phase "<title>"` |
| approve | `/workflow:approve` |
| reject | `/workflow:reject <reason>` |
| release | `/workflow:run release-cut`（Post-MVP） |

## 注意事项

- `new` 类命令：从用户输入中提取标题（去除关键词后的剩余文本），若无法提取则提示用户补充标题
- `reject` 类命令：从 `reject:` 冒号后取 reason；`不通过` / `驳回` 类若无 reason 则提示用户补充
- ASCII 词边界匹配（`\b`）防止 `approved` / `releases` 误命中
- 本 Skill 不引入轮次状态，等长冲突 ask 后用户回复直接送回 launcher 二次匹配

## 硬约束

- ❌ 禁止直接执行 Bash / 改 RunState / 写 jsonl
- ❌ 禁止自行决策等长冲突（必须 ask 用户）
- ❌ 无命中时不接管（透传给对话）
- ✅ state tiebreaker 优先于最长匹配
