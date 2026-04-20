# Stage 6 · 知识沉淀与复利

**完成时间**：30 分钟 + 持续积累
**前置**：Stage 4 完成（跑通过一个需求）
**可验证动作**：向 `context/project/` 提交 1 份经验文档 PR

## 复利路径

```
需求中产生新知识
    ↓ /note 或 AI 自动追加到 notes.md
    ↓
需求验收后（/knowledge:extract-experience）
    ↓
context/project/<X>/ 或 context/team/experience/
    ↓
下一个需求 universal-context-collector 自动检索到
```

## 5 个 /knowledge:* 命令

- `/knowledge:extract-experience` — 从 notes.md 提取经验
- `/knowledge:generate-sop` — 生成标准操作流程
- `/knowledge:generate-checklist` — 生成检查清单
- `/knowledge:optimize-doc` — 优化已有文档结构
- `/knowledge:organize-index` — 整理 context/ 索引

## 什么值得沉淀

见 `context/team/engineering-spec/design-guidance/compounding.md`。必要条件：

- 跨需求/跨项目重复出现
- AI 反复犯同类错误
- 跨会话/跨人需要保留的状态

**至少满足一条才沉淀。**

## 练习

1. 在你刚跑完的需求的 `notes.md` 里找一条"踩过的坑"
2. 运行 `/knowledge:extract-experience`
3. 它会提议一份经验文档，让你确认落到 `context/project/<项目>/experience/` 还是 `context/team/experience/`
4. 确认后提 PR

## 完成标志

- [ ] 理解沉淀的三个必要条件
- [ ] 成功提交 1 份经验文档 PR
