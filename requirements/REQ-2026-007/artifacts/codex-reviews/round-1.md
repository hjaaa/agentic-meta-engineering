---
round: 1
triggered_at: "2026-05-05T17:04:03.473256+08:00"
verdict: not_passed
review_id: "4226641288"
reviewer: "chatgpt-codex-connector[bot]"
submitted_at: "2026-05-05T09:09:05Z"
state: COMMENTED
revised: true
revised_at: "2026-05-05T17:30:00+08:00"
revised_reason: "submit_codex.py 自身 P1 bug（字符串比时间戳）漏掉真实 codex 回评；人工核对 PR #57 review API 后改为 not_passed"
---

## 修订说明

第一轮跑 `submit_codex.py` 时脚本报 `verdict=timeout`，但实际 codex 在窗口期内（17:09:05 +08:00）已回评。
人工核对 `gh api repos/.../pulls/57/reviews` 与 inline comments 后，确认本轮 verdict 应为 **not_passed**：

- review id `4226641288` state=COMMENTED 落在 `[triggered_at, deadline]` 窗口内
- inline 3 条 finding（2 P1 + 1 P2，见下）

漏判的原因恰好被 codex 自己作为 P1 finding 标出——`scripts/lib/submit_codex.py:302` 把 `submitted_at`（`...Z`）与 `triggered_at`（`...+08:00`）做字符串字典序比对，offset 不同导致 17:09:05Z 被误判为早于 17:04:03+08:00。

## Codex 回评原文摘要（参考 PR #57 inline comments）

### F-1 [P1] `scripts/lib/submit_codex.py:302` — Compare review times as datetimes, not strings

> `_poll_codex` filters old reviews with a raw string comparison (`submitted_at <= triggered_at_iso`). This breaks when the two timestamps use different offsets (GitHub review timestamps are typically `...Z`, while `triggered_at` is written as `+08:00`): a newer review can be treated as older lexicographically, causing false timeouts and missed Codex results. Parse both values into timezone-aware `datetime` objects before comparing.

### F-2 [P1] `scripts/lib/submit_codex.py:225` — Handle paginated gh api output before JSON decoding

> The command uses `gh api ... --paginate` but then assumes `proc.stdout` is a single JSON document. Per `gh api` semantics, paginated output is emitted page-by-page unless `--slurp` is used, so multi-page review lists can produce invalid JSON for `json.loads`, which is then treated as repeated 5xx and aborts the polling loop. This will fail on PRs with enough reviews to paginate.

### F-3 [P2] `scripts/lib/list_requirements.py:76` — Normalize created_at timezone before sorting records

> `_parse_created_at` returns naive datetimes for `YYYY-MM-DD HH:MM:SS` but timezone-aware datetimes for ISO `...Z`. When both formats exist in the same repository, `records.sort(...)` compares naive and aware datetimes and raises `TypeError`, so listing requirements can crash instead of returning results. Convert both formats to a single normalized timezone representation before sorting.

## 修复落地

| Finding | 修复 commit | 关键改动 |
|---|---|---|
| F-1 | （本次提交） | 新增 `_parse_iso_to_aware`；`_poll_codex` 改为 tzaware datetime 比对；保留字符串兜底分支 |
| F-2 | （本次提交） | `gh api ... -q '.[]'` 把分页输出展平为 JSONL；新增 `_parse_jsonl_reviews` 兼容历史 mock 数组与 JSONL 两种格式 |
| F-3 | （本次提交） | `_parse_created_at` 永远返回 tzaware datetime；naive 注入 Asia/Shanghai；`datetime.min` 兜底也注入 tzinfo |

## 自举价值

F-004 自身验收（V-04 期望以外的副作用）暴露 F-004 实现层的 P1 bug——这是 dogfooding 的真实收益。
后续 round 2 验证：补 3 条回归 pytest，重跑 `submit_codex.py REQ-2026-007` 应能正确捕捉到 codex 后续回评。
