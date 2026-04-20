# Feature 状态定义

## 状态枚举

| 状态 | 含义 | 进入条件 |
|---|---|---|
| `pending` | 尚未开始 | 阶段 6 拆分时默认 |
| `in-progress` | 开发中 | 用户明确开始（或开始 commit 涉及该 feature 的代码） |
| `done` | 已完成且过审 | 代码 commit + /code-review approved |

## 合法流转

```
pending ──开始开发──→ in-progress ──审查通过──→ done
               │                     │
               └──（不可逆回退）────────┘
```

不允许：
- `pending` 直接到 `done`
- `done` 回退到 `in-progress`（需走 `/requirement:rollback`）
- `pending` 跳到 `in-progress` 但无代码变更（至少要有一次提及该 feature_id 的 commit）

## task 文件 frontmatter

```yaml
---
feature_id: F-001
title: 用户注册
status: pending
created_at: 2026-04-20T10:00:00Z
updated_at: 2026-04-20T10:00:00Z
review_report: null   # done 时填 artifacts/review-*.md 路径
---
```

## 状态变更时同步动作

| 变更 | 同步动作 |
|---|---|
| → `in-progress` | 更新 `updated_at`；写 `process.txt` [development] F-001 开始 |
| → `done` | 更新 `updated_at` + 填 `review_report`；写 `process.txt` [development] F-001 完成（review: xxx.md） |
