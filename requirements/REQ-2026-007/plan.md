# REQ-2026-007 · submit Codex review-loop + archive 命令

## 目标

把 PR 阶段「触发 codex review → 等响应 → 落评论 → 通过判定」单轮循环命令化（`/requirement:submit --codex`），并补齐 PR 合并后的收尾闭环命令（`/requirement:archive`：phase=completed + archived_at + 经验沉淀 + 删本地+远程分支提示），消除当前需求生命周期里两段流程断裂——不再依赖手工后台轮询和手工三步 finalize commit。

## 范围

- 包含：
  - `/requirement:submit --codex` 子模式（同步轮询 + round-N.md 落地 + 精确字符串 `Didn't find any major issues.` 通过判定）
  - `/requirement:archive` 新命令（4 项预检 + 5 步执行 + 三问串行：经验 / 本地分支 / 远程分支）
  - submit 门禁放宽两条：GATE-AHEAD-OF-ORIGIN（同分支 open PR 时 skip）、GATE-REVIEW-VERDICT（`--draft` 时 skip）
  - `phase-rules.md` 补 #9 `completed` 阶段 + `archived_at` 字段语义
  - `/requirement:list` 加 `--all` / `--phase`，默认隐藏 `phase=completed`
  - 4 个新单测文件覆盖 submit-codex / archive / 两条放宽 gate
- 不包含：
  - 迁移 `requirements/<id>/` 目录到 archive/ 子目录
  - 新增 `phase=archived` 状态
  - 命令内多轮 codex 自循环
  - PR merged 后台自动检测进程
  - codex review 命中后自动改代码

## 里程碑

| 阶段 | 预期完成 | 实际完成 |
|---|---|---|
| definition | 2026-05-04 | 2026-05-04 ✓ |
| tech-research | 2026-05-05 | 2026-05-04 ✓ |
| outline-design | 2026-05-05 | 2026-05-04 ✓（reviewer 二审 looks_clean，13 项待办移交 detail-design）|
| detail-design | 2026-05-06 | 2026-05-04 ✓（reviewer 二审 looks_clean，sign-off approved，门禁就绪）|
| task-planning | 2026-05-06 | 2026-05-04 ✓（features.json 拆 4 个任务，依赖图 F-002→F-003 / F-001→F-004）|
| development | 2026-05-08 | — |
| testing | 2026-05-09 | — |

## 风险

- 风险 1：**Codex bot 通过用语漂移** / 应对：通过用语集中在 `submit-rules.md` 的 `CODEX_PASS_PHRASE` 常量；用户改一行配置即可调整（来源：spec §10）
- 风险 2：**`applies_when` 谓词扩展破坏既有 gate** / 应对：先跑历史需求回归（`python3 scripts/gates/run.py --trigger=submit --req=REQ-2026-001..006`）确认 exit code 不变，再合 PR
- 风险 3：**archive 误删远程分支** / 应对：默认 N + 显式确认 + 校验 `<branch> != base_branch`，禁止删 develop / main / master
- 风险 4：**squash merge 后本地分支 `git branch -d` 拒绝** / 应对：透传原始 error，提示用户手工处理；不允许 `-D` 强删
- 风险 5：**codex review 轮询限流（gh API 429）** / 应对：429 直接 timeout 退出不重试；最小轮询间隔 5s

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 codex review-loop 集成进 submit（不拆独立命令）
- **Context**：用户痛点是「submit 后能根据 ci 结果调整 + 触发 codex review」；候选方案三选一：集成 submit / 拆独立 review-iterate / 仅 submit 加 --kick-codex
- **Decision**：集成进 submit，引入 `--codex` 子模式（默认关，子模式开启时一条命令走完「推 PR + 评论 @codex review + 单轮轮询 + 落地评论 + 通过判定」）
- **Consequences**：好——用户一条命令搞定单轮迭代；差——submit 命令复杂度上升
- **时间**：2026-05-04 19:10:00

### D-002 命令内单轮，多轮交主对话推动
- **Context**：codex review 通过往往需要多轮（推改 → review → 改 → 推改 → review）；命令内不做无限自循环
- **Decision**：命令内**单轮**轮询；多轮由主对话 Agent 推动（看到 ⚠️ 摘要 → 改代码 → 用户再次 submit --codex）
- **Consequences**：好——超时模型简单、不会失控；差——多轮要人推动一下
- **时间**：2026-05-04 19:10:00

### D-003 通过判定用精确字符串
- **Context**：候选 4 选 1：review state=APPROVED / body 含关键字 / 该轮无 must-fix / 人判
- **Decision**：精确匹配 `Didn't find any major issues.`（codex bot 当前固定用语）
- **Consequences**：好——零歧义；差——bot 改用语会失效，集中常量化便于改一行
- **时间**：2026-05-04 19:10:00

### D-004 submit 门禁放宽走 applies_when
- **Context**：放宽方式可走 `applies_when` 字段或新加 escape hatch
- **Decision**：用 `applies_when`——它表达的是「设计上不该挂」而非「强制绕过」，语义更准
- **Consequences**：好——不污染 escape hatch；差——可能要扩 schema（备选 plugin 内自处理兜底）
- **时间**：2026-05-04 19:10:00

### D-005 archive 不动目录
- **Context**：候选 4 选 1：不动目录 / 迁 archive/ / 二阶段 / 仅状态标记
- **Decision**：不动目录，仅 meta.yaml 写 `archived_at`；list 默认按 phase 过滤
- **Consequences**：好——改动面最小；差——`requirements/` 目录会随时间膨胀（但能用 list 过滤掩盖）
- **时间**：2026-05-04 19:10:00

### D-006 不新增 phase=archived 状态
- **Context**：归档语义如何标记
- **Decision**：仅用 `archived_at` 字段；phase 终态保持 `completed`
- **Consequences**：好——phase 状态机不膨胀；可区分「完成但未归档」与「完成且归档」；差——查询时要双字段判断
- **时间**：2026-05-04 19:10:00

### D-007 archive 副作用动作全问人
- **Context**：archive 包含 3 个副作用动作（经验沉淀 / 删本地分支 / 删远程分支）
- **Decision**：三问串行，默认 N；`--no-experience` / `--keep-branch` 跳过提示
- **Consequences**：好——降低误删风险；差——多三个交互按键
- **时间**：2026-05-04 19:10:00

### D-008 codex review 落到 artifacts/codex-reviews/round-N.md
- **Context**：candidat 候选：artifacts 子目录 / process.txt 内联 / .review-scope.json
- **Decision**：单独 artifacts 子目录，每轮一个文件；frontmatter 带 round / triggered_at / verdict 等元数据
- **Consequences**：好——可追溯多轮调整；差——多一层目录
- **时间**：2026-05-04 19:10:00

### D-009 phase-rules.md 补 completed 阶段
- **Context**：8 阶段表里没列 `completed`，只在合法切换链里出现，文档自相矛盾
- **Decision**：8 阶段表加 #9 `completed`；切换链增补 `testing → completed`；`archived_at` 字段语义说明完整
- **Consequences**：好——文档一致；差——需要更新 INDEX 的同步引用
- **时间**：2026-05-04 19:10:00

### D-010 archive 也问远程分支，默认 N 不勾选不删
- **Context**：本地+远程对称；GitHub 仓库可能没勾「Automatically delete head branches」
- **Decision**：archive 串行问本地 → 远程；都默认 N；远程已删折叠为 `already-deleted`；安全校验 `<branch> != base_branch`
- **Consequences**：好——不依赖仓库设置；差——多一个交互问句
- **时间**：2026-05-04 20:00:00

### D-011 Codex bot 识别策略：双条件且关系
- **Context**：tech-research 阶段评估 Codex bot login 时发现 `user.type=Bot` 标识所有 GitHub App，单凭 type 无法区分 codex / dependabot / 其他 App；候选 4 选 1：login 全字符串匹配 / 正则 + type / 仅正则 / 仅 type
- **Decision**：双条件 AND——`user.type == "Bot"` **且** `user.login` 正则匹配 `/codex/i`；该判定写入 `submit-rules.md` 的 `CODEX_REVIEWER_LOGIN_PATTERN` + `CODEX_REVIEWER_USER_TYPE` 两个常量，detail-design 首日实测 `gh api .../reviews | jq '.[].user'` 校准
- **Consequences**：好——不锁死 login 字符串、对 bot 用户名漂移有韧性；差——需要在 detail-design 阶段联动确认两条常量，多一处实测步骤（V-01 沙盒 e2e 前置）
- **时间**：2026-05-04 19:56:21

### D-012 detail-design 推进策略：13 项待办按出处分组、V-01 沙盒 e2e 硬前置
- **Context**：outline-design 留下 13 项 detail-design 待办（§7）+ 4 条待澄清；要避免一次性塞 13 节降低评审可读性
- **Decision**：detail-design.md 按「契约 / 决议 / 实测 / 命令文案 / 规则修订」5 组组织——
  - **契约组**：#5（命令 markdown）+ #6（archive-rules.md）+ #7（submit-rules.md §7.5 + 三常量）
  - **决议组**：#1（applies_when 路径）+ #2（pr_open_for_branch 签名，依赖 #1）+ #12（squash merge 策略复评）
  - **实测组**：#3（Codex login 实测）+ #4（Codex App 安装确认，V-01 沙盒 e2e 硬前置）+ #11（F-001 回归基线快照）
  - **命令文案组**：参数表 / 示例 / 异常路径文案（合 #5 的扩展）
  - **规则修订组**：#8（phase-rules.md #9 completed patch）+ #9（run.py `--draft` flag 落点）+ #10（feature_area 主标）+ #13（round-N.md frontmatter 是否扩字段，可选）
  - V-01 沙盒 e2e（#4）作为本阶段硬前置，未确认则 detail-design 不出阶段
- **Consequences**：好——13 项有结构化归属，评审能按组逐节看；差——首日要先跑 V-01 沙盒 e2e，可能挤压契约组进度
- **时间**：2026-05-04 21:30:00
