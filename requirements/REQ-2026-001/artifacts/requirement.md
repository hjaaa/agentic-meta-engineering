---
id: REQ-2026-001
title: 添加骨架使用 Common Pitfalls
created_at: 2026-04-20T15:10:00Z
refs-requirement: true
---

# REQ-2026-001 · 添加骨架使用 Common Pitfalls

## 背景

Agentic Engineering 骨架刚上线，新人 clone 后上手过程中会反复踩到一些可预见的坑（来源：`context/team/onboarding/agentic-engineer-guide.md:1-30` 描述了新人路径）。把这些坑集中在 `CLAUDE.md` 里，避免每个新人独立踩一遍。

## 目标

- 主目标：新人在 30 分钟内能通过 CLAUDE.md 识别自己遇到的常见问题
- 次要目标：随着用户反馈积累，Common Pitfalls 段可以由 `/knowledge:*` 命令自动扩充

## 用户场景

### 场景 1：新人 clone 后第一次跑 /requirement:new
- 角色：骨架新用户
- 前置：已完成 `learning-path/01-environment.md`
- 主流程：读 CLAUDE.md → 发现 Common Pitfalls → 避免试错
- 期望结果：少踩一次坑，少一次来回

## 非功能需求

- 性能：无
- 兼容性：与现有 CLAUDE.md Markdown 风格一致（标题级别、表格格式）
- 安全/合规：无

## 范围

- 包含：新增 `## Common Pitfalls` 段，5 条，每条含症状/原因/修复
- 不包含：重构 CLAUDE.md 现有内容、修改 `learning-path/*`

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| 坑的数量 | 3 / 5 / 10 | 5 | 既全面又不会淹没主索引（CLAUDE.md 硬约束 < 200 行） |
| 放置位置 | CLAUDE.md 根 / 单独文件 | CLAUDE.md 根 | 新人第一次读的就是 CLAUDE.md，单独文件降低发现性 |
| 每条格式 | 自由散文 / 固定三段 | 固定三段（症状/原因/修复） | 便于检索和扩充；与 `context/team/experience/` 的经验文档格式一致 |

## 待澄清清单

（无 `[待用户确认]` 和 `[待补充]`——所有信息在 requirement 中已闭环）
