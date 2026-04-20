---
description: 整理指定目录的 INDEX.md 索引
argument-hint: "[目录路径]（可选，默认当前目录）"
---

## 用途

INDEX.md 与实际文件不符时（新增未列 / 重命名链接失效 / 删除遗留），触发整理。

## 预检

1. 如用户提供路径：目录存在
2. 如未提供：默认用当前需求的 `artifacts/`

## 委托

调用 Skill `managing-knowledge`，子意图 **organize-index**：

- 加载 `reference/organize-index.md` 规则
- 扫目录 + 下一级文件
- 对比 INDEX.md 与实际 → 输出 diff 报告（遗漏/腐化/重命名）
- 用户确认后修正 INDEX.md
- 对每条新增/删除写一句理由
