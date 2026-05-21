# 20260521-standard-8phase-bugs-batch-fix · Standard-8phase 流程残留 bug 批量修复

## 目标

让 standard-8phase workflow 模板可以从 bootstrap 一路自动跑到 archive 全程不依赖手工 workaround，把 REQ-20260519-context-usage-report 暴露的 14 处缺陷一次性根治。

## 范围

- 包含：
  - Bug-2 / 4 / 5 / 6 / 7 / 9 / 10 / 11 / 12 / 13 / 18 / 19 / 20 + 次生 bug（rollback）共 14 处
  - 新建 scripts/lib/append_process.py / summarize_tasks.py / meta_set.py 3 个 CLI
  - 修改 standard-8phase.yaml / workflow_status.py / workflow_dispatcher.py / workflow_loader.py / workflow_rollback_topology.py / check_task_frontmatter.py / audit.py / feature-task.md.tmpl / workflow_bootstrap.py
- 不包含：
  - F-006 ~ F-011 follow-up 系列（已在 REQ-20260519-context-usage-report 闭环）
  - 已修过的 Bug-1/3/8/14/15/16/17（commit 索引见 notes.md:881）
  - 不重构 workflow framework 本身（仅做外科手术修复）
  - 不引入新 workflow 模板（仅修复现有 standard-8phase）
  - 不重新设计 features.json schema（仅消除 prompt 与既定 schema 的漂移）

## 里程碑

| 阶段 | 预期完成 |
|---|---|
| definition | 2026-05-21（已完成） |
| tech-research | N/A（按用户路线"definition 后切修复模式"跳过） |
| outline-design | N/A |
| detail-design | N/A |
| task-planning | N/A |
| development | 2026-05-21（14 commit 已落盘） |
| testing | 2026-05-21（全量 pytest 1868 pass + CLI 冒烟通过） |

## 风险

- 风险 1：本需求自身修的 bug 影响 standard-8phase 流程 → 自己撞自己。应对：用 sandbox REQ-2099-* 跑端到端冒烟，关键 CLI（append_process / summarize_tasks / meta_set / check_task_frontmatter 目录模式 / 自动 project）已逐个手工验证通过。
- 风险 2：yq → meta_set.py 替换破坏现有 e2e 测试断言。应对：已同步更新 tests/e2e/test_standard_8phase_terminal_nodes.py::test_bash_uses_meta_set。

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 整体修复路径：1 个大需求打包 14 个 bug

- **Context**：14 个 bug 涉及 yaml / CLI / gate / loader 多文件，但都集中在 standard-8phase 流程；分散开成 N 个小需求会增加 N×（worktree+PR+review+归档）开销
- **Decision**：1 个 PR 含 14 个独立 commit，按 bug 拆分 commit 便于 review，但合并/归档统一
- **Consequences**：好处——一次 review 周期/一次 archive；坏处——PR 较大（21 文件 / +1700）
- **时间**：2026-05-21 14:30:00
- **Supersedes**：（无）

### D-002 走 definition 完成需求文档后切直接修复模式

- **Context**：standard-8phase 跑修自己 bug 会撞 ≥ 10 处自身缺陷，每节点 workaround 比修复更耗时
- **Decision**：workflow run 用于 definition 阶段产出 requirement.md + ledger，development/testing 阶段不走 yaml 节点而是直接在 worktree 内 commit
- **Consequences**：好处——速度快不被自身 bug 阻挡；坏处——8phases 完整性未端到端校验（用 sandbox REQ 冒烟兜底）
- **时间**：2026-05-21 14:45:00
- **Supersedes**：（无）

### D-003 Bug-5 选 meta_set.py 替换 yq 而非声明 yq 依赖

- **Context**：yq 是外部命令，本仓既有规范倾向 PyYAML（specs/2026-04-22-index-meta-validation §"实现选型"）
- **Decision**：新建 scripts/lib/meta_set.py（PyYAML 实现）替换全部 9 处 yq 调用，消除外部命令依赖
- **Consequences**：好处——onboarding 不撞 yq not found 墙、yaml/spec 双轨同步；坏处——meta_set.py 不支持 yq 全部能力（仅 set / set-json / append 三种，覆盖现有 yaml 用例足够）
- **时间**：2026-05-21 15:00:00
- **Supersedes**：（无）

### D-004 Bug-4 选改 yaml 而非改 check_sourcing 正则

- **Context**：「待确认清单」（yaml）与「待澄清清单」（check_sourcing 正则）二选一统一
- **Decision**：改 yaml 对齐到「待澄清清单」侧
- **Consequences**：好处——影响面最小（单 yaml 一行），历史 requirements 全部已用「待澄清清单」零迁移；坏处——（无）
- **时间**：2026-05-21 15:30:00
- **Supersedes**：（无）
