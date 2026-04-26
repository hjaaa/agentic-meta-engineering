# AI 在推进流程中漏记 notes.md（元经验）

**沉淀原因**：AI 反复错 + 跨需求重复 + 跨会话保留

## 问题

会话内连续踩坑（traceability fail / spec drift / CI strict / regex 严格性），AI 直接修复+commit+下一步，**整段会话结束 `notes.md` 仍为空模板**。本会话就是反例。

## 根因

1. **auto mode 偏好"立即行动"**——每解一个坑就推进
2. **`process.txt` 的假阳性安心感**——已记 `[gate:fail][gate:pass]` 流水，让 AI 误以为"记过了"。但流水 ≠ 经验
3. **跨需求复用感缺失**——会话内只踩一次没触发"这是规律"判定
4. **`/note` 同步性摩擦**——卡当前流，AI 倾向异步等 SessionEnd hook

## 解法

按强度递增三选一：
1. **流程嵌入**：`/requirement:next` 切阶段前主动问"本阶段有踩坑要 `/note` 吗"
2. **Hook 强校验**：写 PostToolUse hook 监测 `fixup` / `gate:fail` 关键词强制 `/note`
3. **依赖 SessionEnd 兜底**：`extract-experience` Hook（REQ-2026-001 产物）兜底自动抽取

## 验证方法

需求结束时 `notes.md` 非空 + 含至少一条对应坑的"症状/根因/修复"。

## 引用来源

- REQ-2026-001 整段会话；`requirements/REQ-2026-001/process.txt` 含 5+ gate 事件但 `notes.md` 空
- `.claude/hooks/extract-experience-worker.sh`（兜底机制本体）
