---
id: REQ-2026-007
title: submit Codex review-loop + archive 命令 · 技术可行性评估
created_at: 2026-05-04T21:00:00+08:00
phase: tech-research
refs-design: true
---

# REQ-2026-007 · 技术可行性评估

## 1. 引言与评估方法

本文评估 REQ-2026-007「submit Codex review-loop + archive 命令」的实施可行性，覆盖 5 个重点技术问题和需求生命周期的工作量拆分。

**可行性结论：high**。无 blocker 级阻碍。核心不确定点是 Codex bot 的 `user.login` 实际值（需实跑 GitHub API 确认）和 Codex GitHub App 是否已安装到目标仓库。两项均可在 detail-design 阶段首日解决，不阻断整体进度。

**评估方法**：
- 读取 spec（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:1）和需求文档（来源：requirements/REQ-2026-007/artifacts/requirement.md:1）
- 读取门禁实现：`scripts/gates/registry.py`、`scripts/gates/run.py`、`scripts/gates/registry.yaml`、`scripts/gates/plugins/ahead_of_origin.py`、`scripts/gates/plugins/review_verdict.py`
- 读取现有规则：`.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md`、`phase-rules.md`
- 参照历史类似需求：`requirements/REQ-2026-006/artifacts/tech-feasibility.md`（门禁系统 A+B 重构，同样涉及 gate 系统改动）
- WebSearch 核查 GitHub Codex App 真实 bot login 名称

---

## 2. 五项重点技术评估

### 2.1 Codex bot `user.login` 识别

#### 现状

spec（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:113）使用 `/codex/i.test(r.user.login)` 作为 bot 识别条件，但未指定确切的 login 字符串。requirement.md 的「待澄清清单」（来源：requirements/REQ-2026-007/artifacts/requirement.md:147）列出三个候选名：`chatgpt-codex-connector[bot]` / `codex-bot[bot]` / `openai-codex[bot]`。

#### 不确定点与调查结论

WebSearch 确认 GitHub App 的注册名称为 `chatgpt-codex-connector`（GitHub Marketplace URL：`github.com/apps/chatgpt-codex-connector`）。按 GitHub Bot 命名规则，安装该 App 后 bot 账号的 `user.login` 应为 `chatgpt-codex-connector[bot]`，`user.type` 应为 `Bot`。

`/codex/i` 正则可命中 `chatgpt-codex-connector[bot]`（字符串含 "codex" 子串）。但以下场景存在误判风险：

- **漏判**：若 OpenAI 将来更换 App 名称（如换成 `openai-pr-reviewer[bot]`），正则失效
- **误判**：若有其他第三方 bot login 中恰好包含 "codex" 字样，会被错误识别为 Codex bot 的 review

**[待用户确认]**：需在 detail-design 阶段首日执行：

```bash
gh api repos/<owner>/<repo>/pulls/<pr_number>/reviews | jq '.[].user | {login, type}'
```

建议使用 REQ-2026-006 PR #54 的 reviews API 抓取真实 `user.login` 值，然后将结果硬编码到 `CODEX_REVIEWER_LOGIN_PATTERN` 常量。

#### 推荐方案

采用**双条件匹配**：`user.type == "Bot"` AND `/codex/i.test(user.login)`，而非单一正则。双条件更安全：即使 login 中含 "codex" 字样的人类账号（理论上可能），也因 `user.type != "Bot"` 被排除。

常量命名建议：

```python
CODEX_REVIEWER_LOGIN_PATTERN = re.compile(r"(?i)codex")
CODEX_REVIEWER_USER_TYPE = "Bot"
```

判定条件：`CODEX_REVIEWER_USER_TYPE == r.user.type and CODEX_REVIEWER_LOGIN_PATTERN.search(r.user.login)`

常量放在 `.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md` 的 `CODEX_PASS_PHRASE` 常量附近，便于用户一行配置调整。

#### 备选

- 精确字符串匹配 `user.login == "chatgpt-codex-connector[bot]"`：最严格，但 App 改名即失效，需要配置更新
- 仅 `/codex/i` 单条件：当前 spec 设计，够用但有低概率误判风险

#### 风险

| 风险 | 概率 | 影响 |
|---|---|---|
| Codex App 改名导致 login 不含 "codex" | 低 | 高（review 永远 timeout） |
| 其他含 "codex" bot 触发误判 | 低 | 中（错误判定为 passed/not_passed） |

---

### 2.2 `applies_when` 谓词扩展可行性

#### 现状

spec（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:65）设计方案 A：在 `GATE-AHEAD-OF-ORIGIN` 的 `applies_when.requires` 中加 `"!pr_open_for_branch"` 谓词。

经代码审查，当前 `applies_when.requires` 实现为纯 `meta.` 字段存在性检查：

- S9 校验（来源：scripts/gates/registry.py:1）：`requires` 每项必须以 `'meta.'` 开头，加载时即拒绝不符合此规则的项
- `_match_requires` 函数（来源：scripts/gates/run.py:1）：仅做 meta 字段存在性/非空检查，无布尔逻辑（`!`）、无动态调用

因此，`"!pr_open_for_branch"` 这种自由谓词**当前不支持**，在 `registry.yaml` 加载时就会被 S9 校验拒绝抛 `RegistryError`。

#### 方案对比

| 方案 | 改动范围 | 风险 | 工期估算 |
|---|---|---|---|
| A：扩展 schema + 谓词解释器 | S9 校验（registry.py）、`_match_requires`（run.py）、新增 `ContextResolver` 类调用 `gh pr list` | 中（schema 扩展向后兼容、测试覆盖要求高） | +1 人天 |
| B：plugin precheck 自处理 | `AheadOfOriginGate.precheck`（scripts/gates/plugins/ahead_of_origin.py:1）加 `gh pr list` 调用，Open PR 时 return Skip；`ReviewVerdictGate.precheck`（scripts/gates/plugins/review_verdict.py:1）加 `ctx.cli_flags.get("draft")` 判断，draft=true 时 return Skip；`run.py` parse_args 加 `--draft` flag，`build_context` 把 `draft` 塞入 `cli_flags` | 低（不改 schema，不影响其他 gate，最小侵入） | 约 0.3 人天 |

**推荐方案 B**。spec（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:75）已明确"最小变更优先：可改成 plugin 内自处理"；spec（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:90）也明确 GATE-REVIEW-VERDICT 采用方案 B。两个 gate 均走方案 B 实现一致，不引入双重修改路径。

#### 方案 B 实现路径（具体）

**GATE-AHEAD-OF-ORIGIN**（在 `scripts/gates/plugins/ahead_of_origin.py:1` 的 `precheck` 中）：

```python
def precheck(self, ctx: GateContext) -> Optional[Skip]:
    if ctx.trigger != "submit":
        return Skip(...)
    # 新增：同分支已有 open PR 时跳过（刷 PR 正文场景）
    branch = ctx.meta.get("branch") or _get_current_branch()
    if _has_open_pr_for_branch(branch):
        return Skip(f"同分支 {branch!r} 已有 open PR；跳过 ahead-of-origin（gate skipped: pr_open_for_branch）")
    return None
```

**GATE-REVIEW-VERDICT**（在 `scripts/gates/plugins/review_verdict.py:1` 的 `precheck` 中追加一个早退条件）：

```python
# draft 模式跳过 review verdict 校验
if ctx.cli_flags.get("draft"):
    return Skip("--draft 模式跳过 review-verdict 校验（gate skipped: draft mode）")
```

`run.py` parse_args 加 `--draft` flag。`build_context` 在 `cli_flags` dict 中加入 `"draft": args.draft`。

#### 备选（方案 A）

扩展 `applies_when.requires` 支持 `!` 前缀逻辑非和 `pr_open_for_branch` 上下文键。需要：S9 规则放宽、新增 `ContextKeyResolver` 类（封装 `gh pr list` 调用）、`_match_requires` 中加逻辑非判断。对未来其他"基于运行时状态 skip"诉求有复用价值，但当前无此诉求，YAGNI。

---

### 2.3 gh API 速率限制与轮询策略

#### 现状

GitHub REST API（authenticated user）速率限制：5000 请求/小时 [待用户确认]（GitHub 官方文档当前公开值，假设：本仓库使用 personal access token 走 authenticated 配额；依据：开发者使用 `gh auth login` 登录后即默认 authenticated；风险：若仓库切换至 GitHub App / Fine-grained token 配额体系不同；验证时机：detail-design 首日跑 `gh api rate_limit` 实测）。

`submit --codex` 单次轮询上限：`timeout / interval = 600s / 15s = 40` 次请求。

#### 多用户场景分析

| 场景 | 每小时请求数 |
|---|---|
| 单人频繁使用（每 20 分钟跑一次 submit --codex） | 3 × 40 = 120 次 |
| 10 人团队同时开发，每人每小时 1 次 | 10 × 40 = 400 次 |

实际场景（单人或小团队）远低于 5000/小时上限，无触限风险。轮询 `gh api` 使用的是当前登录用户的 token，不同用户独立计数，团队协作无相互影响。

#### 429 处理策略

spec（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:364）已定：429 直接 timeout 退出，不重试。这是正确策略：轮询期间遇到 429 说明用户其他操作占用了大量配额，静默退出比无限等待更好。

#### WebSocket/GraphQL subscription 可行性

GitHub GraphQL API 同样有速率限制（5000 points/hour），不比 REST 更宽松。GitHub 不提供 PR review 的 WebSocket 实时推送——需要 GitHub App webhook 推送机制，这需要服务器端监听能力，在本地 CLI 场景下不适用。评估结论：**YAGNI**，轮询策略已够用，webhook 方案需要独立服务器，超出本需求范围，列为 future-work。

---

### 2.4 PR 评论触发 @codex review 的前置条件

#### 现状

`gh pr comment <num> --body "@codex review"` 命令本身无需特殊前提条件（gh CLI 已授权即可执行）。但 Codex bot 响应此评论，需要以下前提：

1. **GitHub App 已安装**：`chatgpt-codex-connector` App 需要被安装到目标仓库/组织
2. **用户账号有 Codex 权限**：需要 ChatGPT Plus/Pro 账号，并完成 GitHub OAuth 授权

#### 当前仓库安装状态

检查 `.github/workflows/` 目录和现有 PR 历史未发现 Codex bot 活动迹象。当前仓库尚无法确认是否已安装 `chatgpt-codex-connector` App。

**[待用户确认]**：

1. 执行 `gh api repos/<owner>/<repo>/installation` 或访问 `https://github.com/<owner>/<repo>/settings/installations` 确认 App 安装状态
2. 若未安装，安装路径：`https://github.com/marketplace/chatgpt-codex-connector` → Install → 选择目标仓库/组织
3. 安装所需权限：仓库 admin 权限（Pull requests: Read and write）

#### 影响评估

若 App 未安装：`gh pr comment` 可以成功执行，评论会出现在 PR 上，但 Codex bot 不会响应。轮询会一直等到 timeout（默认 600s）（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:101），退出码 0 + 打印 timeout 提示。这是 **graceful degradation**，不会造成错误，但用户会困惑为何没有 review。

**前置条件** [待用户确认]：App 安装必须在 V-01 沙盒 e2e 测试前完成，否则 `submit --codex` 的 passed/not_passed 路径无法验证（V-01 是本评估约定的沙盒 e2e 验证项 ID，正式定义将在 detail-design 阶段写入 features.json）。

---

### 2.5 archive 删本地分支 squash merge 场景

#### 现状

spec（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:223）明确：squash merge 后本地分支会被 git 判为"未合并"，`git branch -d <branch>` 失败，透传原始 error 提示用户手工处理（`git branch -D` 或 rebase 后再删）。

#### 技术原理

squash merge 将 feature 分支的所有 commit 压缩为 base 分支上一个新 commit。该新 commit 的 SHA 与 feature 分支上任何 commit 都不同。git 的 safe delete 逻辑（`-d` 标志）检查"本分支 tip 是否为 HEAD 的祖先"，squash merge 后该条件不成立，因此拒绝删除。

#### 方案对比

| 方案 | 实现 | 用户体验 | 安全性 |
|---|---|---|---|
| 当前 spec：透传 error | git 原始错误消息（英文）| 对 squash merge 不熟悉的用户困惑 | 高（不会误删） |
| 友好提示：检测 squash 场景 | 检测 `gh pr view --json mergeCommit` 的 PR merge 方式，若为 squash 则给出专项提示 | 好（提示明确，给出操作建议） | 高 |
| 自动转 -D：检测后直接强删 | 同上检测后执行 `git branch -D` | 好（无需用户额外操作） | 中（违反 spec "不允许 -D" 硬约束） |

**推荐方案**：**友好提示**（检测 squash 场景 + 给出明确提示）。具体实现：当 `git branch -d` 返回"not fully merged"错误时，执行 `gh pr view <pr_number> --json mergeStateStatus,mergedAt` 检测是否为 squash merge，若是则输出：

```
本地分支删除失败：检测到 squash merge，git 认为该分支"未合并"。
建议：先 git fetch origin && git rebase origin/<base>（或直接 git branch -D <branch>）。
```

此方案不改变 spec 的"不允许 -D 强删"硬约束，仅提升 UX。

**[需用户复评]**：自动转 `-D` 方案违反 requirement.md 第 74 行的"不允许 `-D`"硬约束（来源：requirements/REQ-2026-007/artifacts/requirement.md:74）。若用户认为 squash merge 场景下强删是安全的（因 PR 已合并，代码已在 base 分支），可在 detail-design 阶段重新评估此约束。需要明确：强删后的数据丢失风险（本地有 stash 或 WIP 的场景）。

---

## 3. 风险矩阵

| 风险 | 来源 | 概率 | 影响 | 缓解策略 | detail-design 待办 |
|---|---|---|---|---|---|
| R1: Codex bot 通过用语漂移 | requirements/REQ-2026-007/plan.md:37 | 中 | 高（review 永远判 not_passed，循环卡死） | 通过用语集中在 `CODEX_PASS_PHRASE` 常量（submit-rules.md），用户改一行配置即可调整 | 确认常量格式和位置；沙盒 e2e 验证精确字符串匹配路径 |
| R2: applies_when 谓词扩展破坏既有 gate | requirements/REQ-2026-007/plan.md:38 | 中 | 高（历史需求 submit 门禁链挂掉） | 采用方案 B（plugin precheck 自处理），不改 schema；先跑回归 `python3 scripts/gates/run.py --trigger=submit --req=REQ-2026-001..006` 确认 exit code 不变 | 确认方案 B 实现路径；补充回归测试用例 |
| R3: archive 误删远程分支 | requirements/REQ-2026-007/plan.md:39 | 低 | 高（PR 历史指向丢失，不可恢复） | 默认 N + 显式确认 + 校验 `<branch> != base_branch`，拒绝删 develop/main/master；操作前打印分支名请用户再次确认 | 安全校验逻辑单测（含 develop/main/master 拒绝用例） |
| R4: squash merge 后本地分支 `git branch -d` 拒绝 | requirements/REQ-2026-007/plan.md:40 | 高（squash merge 是本项目常见合并方式） | 低（用户手工处理即可，数据无损失） | 友好提示策略：检测 squash 场景后给出明确操作建议；不自动 `-D` | 确认友好提示的实现方式（gh pr view 检测）；[需用户复评] 是否允许 auto -D |
| R5: codex review 轮询限流 (gh API 429) | requirements/REQ-2026-007/plan.md:41 | 低 | 中（单次 submit --codex 超时退出，用户需重试） | 429 直接 timeout 退出不重试；最小轮询间隔 5s（非功能需求，来源：requirements/REQ-2026-007/artifacts/requirement.md:81） | 单测 mock 429 响应，验证 timeout 路径和 process.txt 写入 |
| R6（新增）: Codex GitHub App 未安装 | 本评估 §2.4（来源：requirements/REQ-2026-007/artifacts/tech-feasibility.md:142） | 中（尚未确认安装状态） | 高（`submit --codex` 的 passed/not_passed 路径无法验证；V-01 沙盒 e2e 无法跑通） | detail-design 首日确认安装状态；若未安装，需 admin 介入安装 App | 确认安装状态（必须在 V-01 之前完成） |

---

## 4. 工作量估算

类比参照：REQ-2026-006（门禁系统 A+B 重构）约 5.9 人天（来源：requirements/REQ-2026-006/artifacts/tech-feasibility.md:1），该需求的 bash/bats 脚本量与本需求的 Python CLI 量相近。

### F-001：submit 门禁放宽（GATE-AHEAD-OF-ORIGIN + GATE-REVIEW-VERDICT）

| 子任务 | 改动量 | dev | test |
|---|---|---|---|
| `ahead_of_origin.py` precheck 加 `gh pr list` 调用 + Skip 返回 | ~15 行 | 0.3 | - |
| `review_verdict.py` precheck 加 `draft` 判断 | ~5 行 | 0.1 | - |
| `run.py` parse_args 加 `--draft`，`build_context` 透传 | ~10 行 | 0.2 | - |
| `tests/gates/test_ahead_of_origin.py` 新增 open PR skip 用例 | ~30 行 | - | 0.3 |
| `tests/gates/test_review_verdict.py` 新增 draft skip 用例 | ~25 行 | - | 0.3 |
| **小计** | ~85 行 | **0.6** | **0.6** |

### F-002：submit `--codex` 子模式

| 子任务 | 改动量 | dev | test |
|---|---|---|---|
| `submit-rules.md` 第 7.5 步 codex 子模式逻辑文档 | ~80 行 | 0.3 | - |
| `submit.md` 命令文档加 `--codex` 参数说明 | ~20 行 | 0.1 | - |
| `gh pr comment` + 轮询逻辑 + round-N.md 落地（Skill 实现） | ~100 行 | 0.8 | - |
| process.txt 事件写入 | ~15 行 | 0.1 | - |
| `tests/lifecycle/test_submit_codex.py` 新增（passed/not_passed/timeout + round 自增） | ~80 行 | - | 0.7 |
| **小计** | ~295 行 | **1.3** | **0.7** |

### F-003：`/requirement:archive` 新命令

| 子任务 | 改动量 | dev | test |
|---|---|---|---|
| `archive.md` 命令定义 | ~40 行 | 0.2 | - |
| `archive-rules.md` 执行规则文档（4 预检 + 5 步 + 错误矩阵） | ~100 行 | 0.4 | - |
| `SKILL.md` 子动作清单更新 | ~10 行 | 0.1 | - |
| `tests/lifecycle/test_archive.py` 新增（4 预检 × 2 + 3 副作用 × 3 路径） | ~120 行 | - | 0.9 |
| **小计** | ~270 行 | **0.7** | **0.9** |

### F-004：phase-rules.md 文档修复 + list 命令增强

| 子任务 | 改动量 | dev | test |
|---|---|---|---|
| `phase-rules.md` 8 阶段表加 #9 completed + archived_at 语义 | ~20 行 | 0.2 | - |
| `list.md` 加 `--all` / `--phase` 参数说明 | ~20 行 | 0.1 | - |
| **小计** | ~40 行 | **0.3** | **0** |

### F-005：沙盒 e2e + 回归验证

| 子任务 | dev | test |
|---|---|---|
| 沙盒 e2e REQ-2099-001 完整 8 步（需 Codex App 已安装） | 0.2 | 0.5 |
| 回归：历史需求 REQ-2026-001..006 submit gate exit code 不变 | - | 0.3 |
| **小计** | **0.2** | **0.8** |

### 总计

| Feature | design | dev | test | 合计 |
|---|---|---|---|---|
| F-001 门禁放宽 | 0.2 | 0.6 | 0.6 | 1.4 |
| F-002 submit --codex | 0.3 | 1.3 | 0.7 | 2.3 |
| F-003 archive 命令 | 0.3 | 0.7 | 0.9 | 1.9 |
| F-004 文档修复 | 0.1 | 0.3 | 0 | 0.4 |
| F-005 e2e + 回归 | 0 | 0.2 | 0.8 | 1.0 |
| **合计** | **0.9** | **3.1** | **3.0** | **7.0** |

**挂钟工期约 5 天**（plan.md 里程碑 development: 2026-05-08，testing: 2026-05-09，符合，来源：requirements/REQ-2026-007/plan.md:21）。F-003 和 F-002 可在 detail-design 确定后并行推进；F-001 依赖 registry.py / run.py 的改动面确定后再实施。

---

## 5. 建议（detail-design 阶段必须先决议的事项）

1. **Codex bot login 实测**（最高优先级）：在 detail-design 首日执行 `gh api repos/<owner>/<repo>/pulls/<pr_number>/reviews | jq '.[].user | {login, type}'`，使用 REQ-2026-006 PR #54 的历史 review 记录确认 `user.login` 实际值；将结果写入 `submit-rules.md` 的 `CODEX_REVIEWER_LOGIN_PATTERN` 常量。如 PR #54 无 Codex review 记录，需先跑一次真实的 Codex review 触发流程。

2. **Codex GitHub App 安装确认**（V-01 沙盒 e2e 的前置条件）：确认 `chatgpt-codex-connector` App 已安装到目标仓库；若未安装，联系仓库 admin 安装（需 Pull requests: Read and write 权限）。安装完成前 V-01 无法验证 passed/not_passed 路径。

3. **方案 B 实现接口确认**：确认 `AheadOfOriginGate.precheck`（来源：scripts/gates/plugins/ahead_of_origin.py:1）和 `ReviewVerdictGate.precheck`（来源：scripts/gates/plugins/review_verdict.py:1）的改动方向均采用方案 B；确认 `run.py` parse_args 加 `--draft` flag 的位置不与既有 flag 冲突。

4. **squash merge 场景策略复评**：决议 archive 命令是否在检测到 squash merge 后仅给友好提示（推荐）还是允许自动 `-D` 强删（需要用户明确放宽 requirement.md 第 74 行的"不允许 -D"约束，来源：requirements/REQ-2026-007/artifacts/requirement.md:74）。

5. **feature_area 主标确认**：本需求横跨 `lifecycle`（archive 命令）和 `gate-system`（submit 门禁放宽）两个 area（来源：context/project/agentic-meta-engineering/areas.yaml:18）。建议主标 `lifecycle`，在 meta.yaml 的 affected_modules 字段同时列出 `gate-system`。需用户确认是否符合项目 meta.yaml schema 要求。

6. **回归测试基线**：detail-design 阶段确定 F-001 方案 B 实现后，立即补充 `tests/gates/test_ahead_of_origin.py` 和 `tests/gates/test_review_verdict.py` 的回归基线，作为 F-001 改动的安全网。

---

## 待澄清清单

1. **Codex bot 实际 `user.login` 值**（对应 §2.1 行 41）：候选 `chatgpt-codex-connector[bot]`，需 detail-design 首日实跑 `gh api repos/<owner>/<repo>/pulls/<pr_number>/reviews` 确认；最终值写入 `CODEX_REVIEWER_LOGIN_PATTERN` 常量。

2. **Codex GitHub App 安装状态**（对应 §2.4 行 144）：当前仓库尚未确认 `chatgpt-codex-connector` App 是否安装；执行 `gh api repos/<owner>/<repo>/installation` 或访问仓库 Settings → Installations 查看；未安装需 admin 介入。V-01 沙盒 e2e 的硬前置条件。

3. **GitHub API 速率限制配额体系**（对应 §2.3 行 137）：5000 req/hour 是 personal access token / authenticated user 的公开值；若仓库切换 GitHub App / Fine-grained token 配额规则不同；detail-design 首日跑 `gh api rate_limit` 实测确认。

4. **squash merge 场景下 archive 删本地分支策略**（对应 §2.5 行 197 [需用户复评]）：spec 现行约束「不允许 -D 强删」，但 squash merge 后 git safe delete 必然拒绝；推荐保留约束 + 加友好提示；如用户认为强删安全可在 detail-design 阶段放宽 requirement.md:74 约束。
