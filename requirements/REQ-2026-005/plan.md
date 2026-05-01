# REQ-2026-005 · 门禁系统加固：strict 失效 / Hook 覆盖 / submit 门禁等 10 项缺陷修复

## 目标

修复经对抗式 review-critic 验证后成立的 10 条门禁系统缺陷（F1/F2/F4-F11），消除 strict 模式 warning 被吞、MultiEdit Hook 未被拉起、phase 相邻校验缺失、escape hatch 无 tag 限定、submit 门禁参数链路不通等高优问题，使门禁系统真正能拦截应拦截的场景。

## 范围

- 包含：F1（strict warning 吞没）、F2（MultiEdit Hook 覆盖缺失，仅修 .claude 侧）、F4（registry 条件零消费）、F5（phase 相邻表校验）、F6（escape hatch tag 限定）、F7（submit 门禁参数链路）、F8（reviews_consistency CI 覆盖）、F9（traceability 仅 testing 阶段）、F10（pr_state gh 失败处理）、F11（quality-check.yml 门禁步骤补全）
- 不包含：F3（已被 review-critic 驳回，不入本需求）

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

- 风险 1：escape hatch / phase 校验改动可能影响现有合法流程，需回归所有已有需求的门禁通过路径
- 风险 2：MultiEdit Hook 覆盖依赖 .claude/settings.json matcher 语法，需确认 Claude Code 版本行为一致性
- 风险 3：submit 参数链路涉及多文件协同（submit.md / submit.py / base_reachable.py），改动面较宽

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 不复用 REQ-2026-004 序号
- **Context**：REQ-2026-004 曾被分配后通过 git reset 撤销，目录已删除，但序号一旦分配不复用
- **Decision**：直接分配 REQ-2026-005，跳过 004
- **Consequences**：序号不连续（004 空缺），但避免历史混淆
- **时间**：2026-05-01 17:56:29
