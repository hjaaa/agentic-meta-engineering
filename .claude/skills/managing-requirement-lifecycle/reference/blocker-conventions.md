# 阻塞事件行为约定

主 Agent 识别与记录阻塞（blocker）和阻塞解除（blocker-resolved）的行为准则。本文档由 `managing-requirement-lifecycle` Skill 引用。

## 触发 `[blocker]`（满足任一即主 Agent 委托 logger 写入）

- 用户明确说"我卡住了" / "不知道怎么办" / "这里过不去"
- 主 Agent 连续 2 次（含）以上尝试同一问题未解决
- 外部依赖不可用（接口超时、文档缺失、授权问题）

## 触发 `[blocker-resolved]`

- 用户说"搞定了" / "解决了" / "可以继续了"
- 主 Agent 验证问题消失（重跑成功、接口通了）

## 格式约束

- blocker：`[blocker] <现象 30 字内> / <初步判断或下一步>`
- blocker-resolved：`[blocker-resolved] <根因或解决方式>`
- 整行 ≤ 100 字符；单行装不下时拆多条 `[blocker]` 追加（每条一个关键节点）

## 判断原则

- 不确定是否要记时**倾向写**。漏记比误记代价高
- 连续同类 blocker（同一原因反复触发）合并成一条，避免刷屏
- 阻塞详情**只走 process.txt**；过程中提炼出的可复用知识另行 append `notes.md`（非 1:1 对应）

## 示例

```
2026-04-24 10:20:10 [definition] [blocker] DB 主键冲突 / 怀疑唯一索引重复
2026-04-24 10:35:40 [definition] [blocker] XX 表索引正常 / 方向转向数据层
2026-04-24 11:45:00 [definition] [blocker-resolved] batchInsert 没去重 / 已补 distinct
```

## 不走 /note

用户使用 `/note` 只写 notes.md（跨需求可复用经验）。blocker 是**当前需求的时间线状态**，不属于 notes.md 的语义，也不应该走 `/note`。
