# schema/CR 规则升级必须配套迁移或 legacy escape

**沉淀原因**：跨需求会重复（任何 schema/CR 规则升级都涉及）、跨会话需保留（架构原则）。

## 问题

REQ-2026-003 commit `e3e0131`（F-004b）升级 R003/R007 规则——要求所有 review verdict 必须有 `human_signoff.decision ∈ {approved, approved-trivial}`。但**REQ-2026-002 已 completed 的旧 schema review 文件**（10 个）：

- `conclusion: 'approved'`（旧枚举，新枚举是 `looks_clean / needs_attention / blocked`）
- 缺 `human_signoff` 字段（旧 schema 没这字段）

升级合并后，CI `--strict` 把 REQ-2026-002 整套 review 判为 R002/R003 失败 —— 9 errors，CI 红。

时序：
- 2026-04-29：develop CI 仍 success（旧 R003 不查 human_signoff）
- 2026-04-30 09:02：commit `e3e0131` 在 feat 分支引入新 R003/R007
- 2026-05-01：本 PR 走 CI 时新规则首次扫到 REQ-2026-002 旧数据 → 失败

## 根因

新规则在新需求里 happy path 闭合，但**对历史数据是破坏性变更**。引入时只考虑"新需求遵守新规则"，没考虑"完成态老需求被反向追溯破坏"。`/code-review` 系列升级很容易踩这种坑——评审规则的影响是全仓的。

## 解法

**升级 schema / CR 规则前必须明确两条路径之一**：

1. **数据迁移**：写 `migrate_*_v2.py` 干跑脚本（参考 `scripts/lib/migrate_review_v2.py`），扫历史数据，要么字面量平移（如 `approved → looks_clean`）要么强制人工重判。本仓库已建立的安全约束：迁移脚本**不写 `human_signoff`**，强制重新人工 sign-off。

2. **legacy escape**：给旧需求 meta.yaml 加 `legacy: true`，门禁短路（`scripts/lib/check_reviews.py:367-370` 已实现）。**用途明确文档化**——`context/team/engineering-spec/meta-schema.yaml` 把 legacy 字段限定为"PR3 之前 completed 的历史 REQ"。REQ-2026-001 / REQ-2026-002 都用此路径。

**反例（错误做法）**：升级规则后等 CI 红再补救——已经造成 PR 阻塞、用户困扰、紧急修复压力。

## 验证方法

- 升级 PR 必须包含一项：迁移脚本 OR legacy escape 加注 OR "新规则不向后追溯"明确说明
- CI 跑全仓 `--strict`，不能只跑当前需求 scope；R002/R003/R007 绿才算闭环
- 升级后跑一次 `python3 scripts/lib/check_reviews.py --req <历史 REQ-ID> --target-phase completed` 直接验

## 引用来源

- `requirements/REQ-2026-003/process.txt` 2026-05-01 13:36~14:37（Codex Review 后修复）
- 落实：`requirements/REQ-2026-002/meta.yaml:5-8`（新增 `legacy: true`）
- 设计：`context/team/engineering-spec/meta-schema.yaml`（legacy 字段语义）
- 工具：`scripts/lib/migrate_review_v2.py`（干跑迁移）
