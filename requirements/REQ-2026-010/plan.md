# REQ-2026-010 · workflow 引擎 main loop 与 bootstrap 完整化

## 目标

完整化 workflow 引擎的 main loop 与 bootstrap 流程，落地 PR-68（Window B）遗留工作，确保阶段切换、门禁校验、状态持久化等核心路径稳定可用。

## 范围

来源：artifacts/requirement.md §范围

- 包含：
  - AC-01：`/workflow:run` bootstrap 完整化（load_workflow 校验 + REQ-YYYY-NNN 生成 + 切分支 + 建目录）
  - AC-02：`/workflow:continue` main loop 真派发 7 类节点（agent / skill / prompt / bash / approval / loop / sub_workflow）
  - AC-03：模板硬编码路径全部参数化（`standard-8phase.yaml` 7 处节点路径变量化）
  - AC-04：父子 run 路径收敛到 `run_dir/sub_runs/<node_id>/`
  - AC-05：替换 2 条占位 e2e（`test_code_review_embedded` / `test_sub_workflow_lifecycle`）为真 e2e（mock_agent_dispatch fixture 方案）
- 不包含：
  - 不重写 REQ-2026-009 已完成的模块（F-001 schema loader / F-007 rollback 核心 API / F-005 命令外壳 / F-010 rollback 命令层 hotfix）
  - 不动 `code-review-embedded.yaml` 模板自身逻辑（仅替换其 e2e）
  - 不做 `/workflow:next` 命令落地（F-012 阶段切换迁移作为独立 PR / 后续需求）
  - 不做 `requirements/` → `runs/` 历史目录物理迁移（D-007 双轨期延续）
  - 不处理并发触发 `/workflow:run` 的 REQ-ID 生成竞争场景（本期假设单进程顺序调用）

## 里程碑

| 阶段 | 预期完成 |
|---|---|
| definition | 2026-05-11 |
| tech-research | 2026-05-11 |
| outline-design | 2026-05-11 |
| detail-design | 2026-05-11 |
| task-planning | 2026-05-12 |
| development | 2026-05-12 |
| testing | 2026-05-12 |

## 风险

- 风险 1：**bootstrap 副作用回滚不彻底** / 调用 bootstrap 失败时若 mkdir 已建但 `meta.yaml` 未写 → 残留半成品目录；应对：F-002 `_bootstrap_rollback` 已覆盖三步反向撤销（删目录 / 切回原分支 / 释放 dispatch lock），通过 `tests/skills/test_workflow_bootstrap.py` 覆盖 IOError 场景
- 风险 2：**main loop 失败处理矩阵覆盖不全** / 7 类节点的失败路径差异大（bash 退出码 / agent dispatch 超时 / approval 永久 pending / sub_workflow 跨父子异常 / loop 计数器溢出 / skill 加载失败 / prompt 解析失败）；应对：F-008 detailed-design.md §6 失败处理矩阵冻结 5 类核心场景；剩余 2 类（loop 溢出 / prompt 解析）以 `[待用户确认]` 留待后续 PR 扩充
- 风险 3：**mock_agent_dispatch fixture 与真实 dispatcher 行为偏离** / fixture 返回固定 `{"output": "{verdict: passed}"}` 可能掩盖 dispatcher 真实链路 bug；应对：F-010 monkeypatch 仅介入 `_dispatch_agent_node` 单点，main loop / RunState / jsonl 写入全部走真实路径；AC-05 测试断言 `node_completed.output` 非空 + jsonl 事件序列完整

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 AC-05 采用 mock `_dispatch_agent_node` 方案，不走真实 Claude API
- **Context**：AC-05 要求"真派 Agent / 真跑节点"，但每条 e2e 走真实 LLM 单次约 sub-cent，CI flaky rate 上升与网络限流风险（详见 tech-research.md §1.5）
- **Decision**：mock `_dispatch_agent_node()` 的返回值（固定 `{"output": "..."}`），但 main loop / RunState / jsonl 写入全部走真实路径
- **Consequences**：好——CI 稳定 + 零 LLM 成本；坏——dispatcher 层内部 bug 不会被 e2e 暴露（依赖单测覆盖）
- **时间**：2026-05-11 13:15
- **Supersedes**：（无）

### D-002 PR-A / PR-B 拆分锁定为单 PR（实际未拆）
- **Context**：tech-research.md §3 建议拆两个 PR（PR-A=AC-01+AC-03 / PR-B=AC-02+AC-04+AC-05）控制合并风险
- **Decision**：实际推进时合并到单 PR（feat/req-2026-010），因 F-001~F-011 逐项 code-review signoff 已逐步落地、回滚单位足够细
- **Consequences**：好——避免拆 PR 引入的 base-branch 协调成本；坏——单 PR 体量 135 files / 16k+ insertions，review 体验较重
- **时间**：2026-05-12 14:30
- **Supersedes**：tech-research.md §3 PR 拆分建议
