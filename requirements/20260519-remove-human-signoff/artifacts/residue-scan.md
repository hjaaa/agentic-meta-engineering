# 残留扫描分类报告 · 20260519-remove-human-signoff

执行时间：2026-05-19 12:00:00（Asia/Shanghai）
执行命令：`rg "human_signoff|code-review:signoff|check-signoff|sign-off|signoff" scripts .claude context tests requirements`
总命中数：**2196 行**

按 spec §验证命令 第 3 条，残留分四类。**类 D（有效指令）应为 0**。

## 类 A：历史白名单（保留）

| 路径 | 命中 | 说明 |
|---|---|---|
| `requirements/REQ-2026-001 ~ REQ-2026-014/**` | 大量 | archived completed 需求历史 review JSON / plan.md / notes.md / artifacts，按 spec §review JSON 历史内容 + F-008 决议保留 |
| `context/team/experience/**` | 多个 | experience 历史事故记录，spec §文档清理 明确"保留为历史机制" |
| `context/team/engineering-spec/specs/2026-04-30-code-review-human-checkpoints.md` | 多个 | F-007 已加废弃声明；文体保留 |

## 类 B：本期变更注释（保留）

| 路径 | 行数 | 说明 |
|---|---|---|
| `scripts/lib/save_review.py` | 6 | F-002 commit 内的"F-002（remove human sign-off）：CR-X 已删除..."注释，留作变更历史 |
| `scripts/lib/check_reviews.py` | 3 | F-002 内的同模注释 |
| `context/team/engineering-spec/review-schema.yaml` | 3 | F-001 头部变更历史注释 |
| `context/team/ai-collaboration.md` | 1 | F-007 规则三历史背景段，提及"sign-off 是人类专属动作"已下线 |
| `context/team/engineering-spec/design-guidance/gate-system-architecture.md` | 5 | F-007 历史机制注释 + reviews/*.json 直写保护规则（语义转为"标准写盘" + hook 防绕过 save-review.sh） |

## 类 C：历史迁移脚本（保留作历史白名单）

| 路径 | 行数 | 说明 |
|---|---|---|
| `scripts/lib/migrate_review_v2.py` | 12 | review schema v1→v2 历史迁移脚本，描述包含"清空 human_signoff"动作；本期未触及该脚本（不在 features.json 任一 touches 内），保留作为历史工具 |
| `tests/migration/fixtures/R003/{happy,failure,boundary}.yaml` | 多个 | R003 历史测试 fixture，含 `with_signoff: true/false` 标记；本期未触及（不在 features.json 任一 touches 内），用于 migration 子系统回归 |
| `scripts/lib/save_review_validation.py` | 多个 | F-012 rev6 D-017 ADR 路径预留模块的 docstring 提及 "signoff.py → save_review_validation.py"，是 docstring lag（无实际 import），不影响运行 |
| `scripts/lib/check_sourcing.py` | 1 | 注释 "已 sign-off 的评审结论" 描述 sourcing 白名单，是过去叙事，本期未必要清理 |

## 类 D：有效指令（应为 0）

**0 命中**。无任何当前流程、命令、schema、gate 或模板中仍以 sign-off 作为有效指令的位置。

- `.claude/commands/code-review/signoff.md` — F-003 已删
- `.claude/skills/code-review-signoff/` — F-003 已删
- `scripts/lib/signoff.py` — F-003 已删
- `scripts/check-signoff.sh` — F-003 已删
- `scripts/lib/save_review.py` 的 `signoff` 子命令 parser — F-002 已删
- `scripts/lib/check_reviews.py` 的 `is_signed_off` / R003-R007 签字判定 — F-002 已删
- `.claude/skills/feature-lifecycle-manager/SKILL.md` 的 `check-signoff wrapper 判定` — F-005 已改
- `.claude/skills/code-review-report/SKILL.md` 与模板的 `待 sign-off 提示` — F-005 已改
- `.claude/agents/code-quality-reviewer.md` 的 `human_signoff 是卡点 B 专属字段` 禁写说明 — F-005 已改
- `.claude/workflows/requirement/standard-8phase.yaml` 6 个 `*-signoff` 节点 — F-006 已改 `*-confirm`

## 结论

**类 D = 0**，spec §验证命令 第 3 条达成。AC-9 通过。

## 后续 follow-up（不阻塞本期）

1. `scripts/lib/save_review_validation.py` docstring 提及已删的 `signoff.py`，可在下个 minor 清理。
2. `scripts/lib/migrate_review_v2.py` 是 review schema v1→v2 历史迁移脚本，描述提及人工 sign-off 重签；本期未在 features.json 范围内，但 human_signoff 已下线后该脚本的"清空 human_signoff"动作变得 trivially 满足（字段已无），可在 follow-up 评估是否退役。
3. `tests/migration/fixtures/R003/` 三 yaml 包含 `with_signoff` 字段；migration 子系统是否要同步更新参考结构，留作 follow-up。
