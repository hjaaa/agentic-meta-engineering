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

| 阶段 | 预期完成 |
|---|---|
| definition | 2026-04-28 |
| tech-research | 2026-04-28 |
| outline-design | 2026-04-29 |
| detail-design | 2026-04-30 |
| task-planning | 2026-04-30 |
| development | 2026-05-07（4 个 PR 串行 / 部分并行） |
| testing | 2026-05-08 |

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
