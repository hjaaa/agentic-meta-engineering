---
name: managing-requirement-lifecycle
description: 需求全生命周期管理伞形 Skill，被 7 个 /requirement:* 命令共用。负责阶段切换、门禁校验、状态持久化。
---

## 什么时候用

用户通过 `/requirement:*` 命令，或口头说"新建需求 / 继续需求 / 下一阶段 / 保存进度 / 查看状态 / 回退 / 列出需求"时。

## 核心流程

1. **识别意图**：映射到 7 个子动作之一
   - 新建 → bootstrap（创建分支+目录+meta.yaml）
   - 继续 → 委托 `requirement-session-restorer`
   - 下一阶段 → 门禁校验（见 `reference/phase-rules.md`）→ 更新 phase
   - 保存 → 委托 `requirement-progress-logger`
   - 查看状态 → 读 meta.yaml 输出阶段+最近动作
   - 回退 → 归档当前 artifacts + 改 phase + 写 notes.md
   - 列出 → 扫 `requirements/*/meta.yaml`，输出需求索引

2. **状态持久化**：每次阶段变更必须更新 `meta.yaml` 的 `phase` + 追加 `gates_passed`

3. **门禁校验**：阶段切换前必走 `reference/gate-checklist.md`

## 硬约束

- ❌ 禁止跳过门禁（例：从 `definition` 直接跳 `detail-design`）
- ❌ 禁止在非功能分支上 bootstrap（会被 Hook 拦截）
- ✅ `meta.yaml` 更新必须原子：先写临时文件再 mv（避免中间状态）
- ✅ 未知意图必须向用户澄清，不得"猜测"后擅自推进

## 参考资源

- [`reference/phase-rules.md`](reference/phase-rules.md) — 8 阶段定义 + 切换规则
- [`reference/gate-checklist.md`](reference/gate-checklist.md) — 各阶段门禁具体检查项
- [`templates/meta.yaml.tmpl`](templates/meta.yaml.tmpl) — 新建需求的 meta.yaml 模板
- [`templates/plan.md.tmpl`](templates/plan.md.tmpl) — 新建需求的 plan.md 模板
