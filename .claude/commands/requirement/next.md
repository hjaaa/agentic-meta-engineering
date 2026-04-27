---
description: 前进到下一阶段（含强制门禁检查）
---

## 用途

当前阶段工作完成，要切到下一阶段。会触发该阶段切换的门禁检查。

## 预检

1. 当前分支对应 `requirements/*/meta.yaml` 存在
2. `meta.yaml.phase` 不是最终态 `completed`

## 委托

调用 Skill `managing-requirement-lifecycle` 的 **next** 流程：

- 查 `reference/gate-checklist.md` 中"当前阶段 → 下一阶段"段的全部检查项
- **逐条执行**（不允许"读清单自答通过"）：
  - 形如 `- [ ] bash scripts/...` 的命令型检查项：**必须用 Bash 工具真实执行该命令**，以退出码判定通过/失败
  - 形如 `- [ ] <文件> 存在` / `- [ ] <字段> 非空` / `- [ ] 无 <标记> 遗留` 的状态检查项：必须用 Read / Grep 真验证，不凭印象
- 任一失败 → 列出缺口（含失败命令的 stderr 关键行 / 缺失文件路径）并终止，不修改 phase
- 全部通过 → 更新 `meta.yaml.phase` + `gates_passed` 追加一条
- 委托 `requirement-progress-logger` 写 `[phase-transition]` 日志
- 输出新阶段的首个动作提示
