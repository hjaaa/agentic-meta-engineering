# REQ-2026-002 · 统一门禁系统

## 目标

把当前散落在 9 层（PreToolUse Hook / pre-commit / Skill 阶段清单 / submit 清单 / CI / 各 check 脚本 / verdict R 规则 / 追溯链 / post-dev-verify）的门禁体系，收敛到「单一 registry + 单一 runner + 多个 adapter plugin」的统一执行通道，同时关闭已知的 4 个高优先级缺口（H1/H3/H4/H5）。

业务价值：新增门禁的成本从「改 4 个文件 + 跑通 3 套清单」降到「填 9 字段 + 写 1 个类 + 写 3 个测试」；门禁系统自身可被审计、可观测、可回滚。

## 范围

- 包含：
  - `scripts/gates/` 新目录：runner / Gate 基类 / registry.yaml / plugins / triggers / audit
  - 把现有 check-meta / check-index / check-sourcing / check-reviews / check-plan / post-dev-verify / traceability-gate 全部以 adapter 形式接入新通道（行为等价）
  - pre-commit / phase-transition（next）/ submit / CI / PreToolUse（含 Bash 写保护）切到 runner
  - `gate-checklist.md` 改为渲染产物，注册表为唯一 SoR
  - 关闭 H1（R005 写回事务化）、H3（submit 与 next 同源）、H4（PR 状态闭环）、H5（Bash 写 reviews/*.json 拦截）
  - escape hatch 收敛到 registry，强制 reason + audit log

- 不包含：
  - H2 rollback 门禁（中优先级，下一轮迭代）
  - testing → completed 弱门禁加固（中优先级）
  - 新增门禁规则——本次纯收敛已有逻辑
  - 跨需求 governance 类门禁（如 legacy 数量上限）

## 里程碑

| 阶段 | 预期完成 | 实际完成 |
|---|---|---|
| definition | 2026-04-28 | 2026-04-27（review-003 approved，score=90） |
| tech-research | 2026-04-28 | 2026-04-27（feasibility=high，27 人天，无 blocker） |
| outline-design | 2026-04-29 | 2026-04-27（review-001 approved，score=86） |
| detail-design | 2026-04-30 | 2026-04-27（review-002 approved，score=90） |
| task-planning | 2026-04-30 | 2026-04-27（features.json 4 个 feature → tasks/F-001~F-004.md，全 pending） |
| development | 2026-05-07（4 个 PR 串行 / 部分并行） | — |
| testing | 2026-05-08 | — |

## tech-research 结论锚点

- **可行性**：high（来源：requirements/REQ-2026-002/artifacts/tech-feasibility.md:11）
- **总工作量**：27 人天（来源：requirements/REQ-2026-002/artifacts/tech-feasibility.md:127）
  - F-001 骨架：9 天
  - F-002 全量 adapter + CI 切换：9 天
  - F-003 关闭 H1/H3/H4/H5：6.5 天
  - F-004 渲染产物 + 删旧入口：2.5 天
- **关键技术选型**：graphlib（拓扑） + shutil.copy2（事务） + 自写 normalize-stderr + 双轨进程链/env 白名单 + 裸 Python 渲染 + 手写 schema 校验，全部零新增依赖
- **关键风险**：R-1 adapter 行为偏移（high/high，靠 snapshot 契约缓解）、R-2 Bash 写保护跨平台（medium/high，靠双轨白名单 + dry-run 缓解）

## 风险

- **R-1 行为等价性回归**：adapter 化后行为偏移导致 CI 红。应对：每个 PR 合入前跑 snapshot 行为契约测试（`scripts/gates/migration/capture-baseline.sh` 抓基线，迁移后 normalize-stderr 后逐行 diff），归一化后 ERROR/WARNING/✗ 等关键前缀行 diff 必须为空。
- **R-2 R005 事务化引入新 bug**：写回 stale 改成事务后可能错过本应触发的 stale 标记。应对：单测覆盖「中途失败回滚」「全过提交」「单独 R005 失败」三种路径。
- **R-3 改造期实施路径**：旧入口与新 runner 同时存在导致结果矛盾。应对：旧入口在兼容期（F-001 ~ F-003）改造为**薄壳**直接 `exec` runner；不做"双跑"路径。验收依赖 R-1 的 snapshot 契约测试，不依赖 CI 双跑日志比对。
- **R-4 Bash 写保护误伤**：拦 `requirements/*/reviews/*.json` 的 Bash 写命令时正则过严，挡住合法路径（如 `mv tmp/x.json requirements/...`）。应对：白名单允许 `save-review.sh` 启动的子进程，并在 dry-run 模式跑一周。
- **R-5 文档渲染产物被误改**：`gate-checklist.md` 渲染后被人手改回。应对：文件头加 `<!-- generated, do not edit -->` 标记 + CI 校验渲染产物未被手工修改。

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 4 个 PR 增量切换，旧入口保留兼容期
- **Context**：本次改造触面广（CI / Hook / 所有 check 脚本 / 文档生成器），一次性大爆炸切换风险高。
- **Decision**：拆 4 个 PR（F-001 骨架 / F-002 全量 adapter / F-003 缺口修补 / F-004 文档渲染 + 旧入口删除）。前 3 个 PR 保留旧入口转调 runner，F-004 才删旧入口。
- **Consequences**：
  - 好：每个 PR 都可独立回滚；CI 双跑可对齐结果
  - 不好：兼容期内代码路径稍重复（旧入口包薄壳）
- **时间**：2026-04-27 19:55:00

### D-002 Registry 是配置但不做"配置驱动一切"
- **Context**：容易把 registry 写成动态规则引擎，导致复杂逻辑在 YAML 里"编程"。
- **Decision**：registry.yaml 只承担"开关 + 适配条件 + 严重度 + 失败提示"四类元数据；具体检查逻辑全部在 plugin 代码里。
- **Consequences**：
  - 好：plugin 易写易测；registry 易读易审
  - 不好：新增门禁仍然需要写 Python（不是纯配置）——但这是有意为之
- **时间**：2026-04-27 19:55:00

### D-003 runner 性能不立硬性 SLA，CI 时间作隐式上限
- **Context**：requirement.md 性能段需明确"端到端 ≤ 现状"是否升级为 95p ≤ Xms 等硬指标。
- **Decision**：本次不立硬性 SLA。tech-research 阶段抓现状基线（quality-check.yml 5 个 step 耗时）作为 runner 不可超过的隐式上限。如未来 CI 时间显著退化，再开 ADR 立硬指标。
- **Consequences**：
  - 好：避免在 definition 阶段拍脑袋数字；tech-research 用真实测量做依据
  - 不好：runner 性能退化无显式断言，靠 CI 时间监控
- **时间**：2026-04-27 20:15:00

### D-004 audit log 保留 90 天，按月分目录
- **Context**：每次 trigger 都写 audit JSON，长期会膨胀。需明确保留期与归档结构。
- **Decision**：路径 `scripts/gates/audit/<YYYY-MM>/<event>-<timestamp>.json`（按月分目录，与原始设计中按日分目录的口径合并到月级），保留 90 天；超期由 governance 工具（下一轮迭代落地）自动清理。当前周期内由 PR review 关注 audit/ 目录大小。
- **Consequences**：
  - 好：检索与归档简单（按月 ls 即可）
  - 不好：单月文件数仍可能上千；governance 工具补齐前需人工关注
- **时间**：2026-04-27 20:15:00

### D-005 escape_hatch 本轮不做 RBAC，仅强制 reason + audit
- **Context**：`--force-with-blockers` 等逃生口当前只要 reason，是否需要"审批人字段"或权限分级。
- **Decision**：本轮不做 RBAC。所有 escape 必须带 `reason` 字段，写入 audit log + process.txt。RBAC 列入下一轮迭代（与 H2 rollback 门禁等中优先级一并）。
- **Consequences**：
  - 好：避免本次范围爆炸；reason + audit 已足以追责
  - 不好：滥用 escape 仍可能发生，依赖 PR review 把关
- **时间**：2026-04-27 20:15:00

### D-006 Bash 写 reviews/*.json 白名单双轨：进程链 + 环境变量
- **Context**：H5 拦截 Bash 写 `reviews/*.json` 时如何识别合法调用方（如 save-review.sh 自身的子进程）。
- **Decision**：双轨判定：
  1. 识别父进程链（`ps -o ppid,comm`），命中 `save-review.sh` 即放行
  2. 显式环境变量 `CLAUDE_GATES_BYPASS=1` + 必填 `CLAUDE_GATES_BYPASS_REASON` 才生效，每次写入 audit log
- **Consequences**：
  - 好：覆盖正常子进程 + 异常情况下的人工豁免
  - 不好：父进程链识别在容器/沙箱环境可能失效，需 detail-design 验证
- **时间**：2026-04-27 20:15:00

### D-007 gate-checklist.md 渲染产物强约束：registry 改动必须附渲染 diff
- **Context**：gate-checklist.md 改为渲染产物后，需防止"改 registry 但忘改产物"或"手工改产物绕过 registry"。
- **Decision**：CI 强校验——`scripts/gates/render-docs.py --check` 重新渲染并 diff 当前产物，diff 非空即 PR 失败。任何改 `registry.yaml` 的 PR 必须同时 commit 重新渲染的 `gate-checklist.md`。
- **Consequences**：
  - 好：产物与 SoR 永不漂移；CI 自动把关
  - 不好：开发者忘记重渲染会被 CI 拦，需 README 提示 `make gates-render`
- **时间**：2026-04-27 20:15:00

### D-008 新增门禁成本目标 ≤ 0.5 人天
- **Context**：requirement.md 次要目标提到"成本基线对比"，需要锚定数字以便 testing 阶段做效果验收。
- **Decision**：当前基线（粗估）= 1-2 人天（改 4 文件 + 跑通 3 套清单）；改造后目标 ≤ 0.5 人天（填 9 字段 + 写 1 个类 + 写 3 个测试）。testing 阶段以"实际新增一条门禁的工时"做验收。
- **Consequences**：
  - 好：有可测量的业务价值锚点
  - 不好：粗估数字主观；首次新增门禁的人需如实记录工时
- **时间**：2026-04-27 20:15:00

### D-009 development 阶段 4 个 feature 严格串行推进
- **Context**：features.json 中 F-002 / F-003 / F-004 都 depends_on 前序 feature，理论上 F-003 与 F-004 在某些子模块上有并行空间，但骨架未稳前并行风险高。
- **Decision**：本轮严格按 F-001 → F-002 → F-003 → F-004 串行推进，每个 feature 完成（status=done）后才启动下一个；每个 feature 单独提 PR，merge 后再切下一个。
- **Consequences**：
  - 好：每个 PR blast radius 最小，CI 双跑可对齐 baseline；R-1 行为偏移问题逐 PR 验证
  - 不好：总工期偏长（27 人天纯串行），无法压缩
- **时间**：2026-04-27 22:10:00
