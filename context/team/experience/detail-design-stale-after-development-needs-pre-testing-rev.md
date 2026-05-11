# detail-design.md 在 development 长跨度回填后必 stale，testing 切换前需重审

**沉淀原因**：跨需求会重复（A）+ 跨会话需保留（C）

## 问题

REQ-2026-009 phase-transition development → testing 触发 GATE-REVIEW-VERDICT R005：

```
reviews.detail-design: artifacts/detailed-design.md 已变更
（was 2025827d..., now 1f4526c4），review 已 stale，请重审
```

development 阶段 13 个 feature × 6 轮 review × ADR 回填，detailed-design.md 累计
**250 行 diff / 15 个 commit**：

| commit | 性质 |
|---|---|
| F-001 字面量统一（approval_granted → approval_approved）| 字面量小修 |
| F-005 §1.2.3 save 前置加 completed / §1.2.6 approve 状态流转 / exit 2→1 | 状态流转修订 |
| F-007 §6.1/§6.2/§6.3/§6.7 回写 + 异常类细化 + KI-step-1 测试 caplog | 章节回填 |
| F-008 §7.3.3+§7.5 目录结构同步 + acceptance pytest 路径 | acceptance 同步 |
| F-011 rev2 D-014 同模式扫描 6 项 minor | 文档跟进 |
| ... | ... |

## 根因

development 阶段是**实施视角对设计文档的 retroactive 回填**：

- 每个 feature 实现后发现 design.md 字面量与代码不一致 → 回填 design
- review-loop 抓到 design ≠ implementation → 回填 design
- ADR 决策记录后 design 章节需引用 → 回填 design
- 测试用例 acceptance 路径与 design §X.Y 文字不一致 → 回填 design

每次回填都改 design.md hash，detail-design 阶段的 review verdict 就 stale 了。
长跨度需求（13+ features × 多轮 review）必触发 R005。

## 解法

**testing 切换前预审 detail-design**（双轨：避免阻塞 + 保流程合规）：

### 路径 A（推荐，5-10 分钟）：派 detail-design-quality-reviewer 重审

```
派 subagent: detail-design-quality-reviewer
  prompt:
    - 重审目的：解锁 GATE-REVIEW-VERDICT R005
    - 必读背景：
      - rev N-1 已是 looks_clean approved
      - development 阶段 13/13 features 全 looks_clean sign-off
      - 250 行 diff / 15 commit 都是"实施级回填"（列具体 commit 类型）
      - 每条 commit 已通过对应 feature 的 design-consistency-checker
    - 评审重点：聚焦 250 行 diff，不要全文重新打分
      - consistency_with_outline / interface_completeness 是否仍对齐
      - sequence_correctness 状态流转修订是否文档自洽
      - feature_granularity 章节细化是否过度
    - 不纠 ADR 知识沉淀类（属 plan.md 决策记录范畴）
  expected: looks_clean ≥ 88，0 blocker
```

重审通过后用户 tty `approved` sign-off，phase-transition 重跑即可。

### 路径 B（3 分钟）：escape hatch 放行（仅 ADR / touches 回填场景）

```bash
python3 scripts/gates/triggers/submit.py --req=REQ-XXX \
  --bypass-review-blockers='detail-design 变更仅为 ADR 知识沉淀 / touches 回填，已通过各 feature 的 design-consistency-checker'
```

仅适用：变更 100% 都是 ADR 知识沉淀 + touches 回填，无任何状态流转 / 接口签名 / 异常码改动。
否则走路径 A 合规。

## 验证方法

```bash
# 1. 触发 phase-transition gate
python3 scripts/gates/run.py --trigger=phase-transition --req=<REQ-ID> \
  --from=development --to=testing

# 2. 看 GATE-REVIEW-VERDICT 是否还在 R005
tail -1 audit/.queue/$(date +%F).log | python3 -c "import sys, json; ..."

# 3. 解锁后重跑 → 期望 EXIT=0
```

**预防性 SOP**：testing 切换前主 Agent 自检 `meta.yaml.reviews.detail-design.stale`
字段——`stale: true` 时直接走路径 A，不要等 gate fail 才反应（节省 1 轮 push round-trip）。

## 引用来源

- `requirements/REQ-2026-009/process.txt` — 09:11 GATE-REVIEW-VERDICT fail R005 / 09:08 detail-design rev3 重审 / 09:10 sign-off / 09:15 phase-transition 通过
- `requirements/REQ-2026-009/reviews/detail-design-003.json` — rev3 verdict（looks_clean / score 92 / supersedes 002）
- `.claude/agents/detail-design-quality-reviewer.md` — reviewer agent 契约定义
