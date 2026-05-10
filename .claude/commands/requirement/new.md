---
description: 创建新需求——自动建分支、目录、meta.yaml 骨架
argument-hint: <需求标题>
---

> [DEPRECATION] /requirement:new 已纳入 3 月兼容期（截至 2026-08-08）。
> 请改用：/workflow:run standard-8phase "<title>"
> 本次仍执行旧实现以保证兼容；Plan 6 自举验证通过 + 兼容期到期后将物理删除。
> 详见：context/team/engineering-spec/migration/2026-XX-runs-rename.md
>
> **ARGUMENTS 透传规则**：`$@` 拼空格作 title，如 `/workflow:run standard-8phase "用户注册优化"`

## 用途

开始一个新需求开发周期。会创建：

- 新分支 `feat/req-<ID>`（优先从 `develop` 切出，仓库未启用 develop 时降级到 `main`）
- 需求目录 `requirements/<ID>/`
- 骨架文件：`meta.yaml` / `plan.md` / `process.txt`（空）/ `notes.md`（空）

## 预检

1. 工作目录 clean（无 uncommitted changes）：`git status --porcelain` 为空
2. 当前分支为起点分支（`develop` / `main` / `master`），不能从某个既有 `feat/req-*` 派生
3. 参数 `<需求标题>` 非空

预检不通过立即返回错误并终止。

## 委托

调用 Skill `managing-requirement-lifecycle` 的 **bootstrap** 流程：

- 生成唯一 REQ-ID（格式 `REQ-YYYY-NNN`，NNN 按现有 requirements/ 下序号 +1）
- 从 `templates/meta.yaml.tmpl` 和 `templates/plan.md.tmpl` 生成初始文件
- 切分支并做 bootstrap commit
- 输出需求 ID 与下一步提示
