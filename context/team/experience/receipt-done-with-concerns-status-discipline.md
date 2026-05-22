# receipt.json status 选用：DONE 与 DONE_WITH_CONCERNS 不可混用

**沉淀原因**：跨需求 · AI 反复错 · 跨会话

## 问题

testing 阶段 submit 门禁 `GATE-POST-DEV-RECEIPT` 拦死：`receipt.status="DONE"` 但 `concerns` 非空。schema 严格要求 `DONE` 必 `concerns=[]`，否则该用 `DONE_WITH_CONCERNS`。本期 F-002 / F-005 两份 receipt 同时撞这个门禁，submit 失败 exit 1。

## 根因

subagent 写 receipt 时：
- 对「有留下边界外 follow-up」的任务依然填 `DONE`（默认原因：concerns 被当作"补充说明"而非状态修饰）
- 不看 `scripts/gates/plugins/post_dev_receipt.py` 的 schema 严格处罚规则
- dispatch prompt 未显式枚举 status 选用规则

## 解法

subagent dispatch prompt 必显式写明枚举选用：

- `concerns == []` → `status = DONE`
- `concerns != []` → `status = DONE_WITH_CONCERNS`
- `BLOCKED` 仅在任务未走完时使用；`DONE_WITH_CONCERNS` 不是"失败 alias"

什么内容入 concerns：边界外 follow-up（不在本 feature touches 范围内）/ 未彻底闭合的 hotfix 动作 / 显式接受的已知限制。

## 验证方法

submit 之前本地跑：

```bash
python3 scripts/gates/run.py --trigger=submit --req=<id>
```

退出 0 即过。修 dispatch prompt 后复跑下一个有 follow-up 场景的 feature，receipt 应自动转 `DONE_WITH_CONCERNS`。

## 引用来源

- `requirements/20260521-archive-runner-auto-pr/artifacts/tasks/F-002.receipt.json`
- `requirements/20260521-archive-runner-auto-pr/artifacts/tasks/F-005.receipt.json`
- `scripts/gates/plugins/post_dev_receipt.py`（R-RECEIPT-MISSING-OR-INVALID）
- `requirements/20260521-archive-runner-auto-pr/process.txt`（19:07-19:08 submit gates 两轮调试）
