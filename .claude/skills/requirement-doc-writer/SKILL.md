---
name: requirement-doc-writer
description: 撰写 artifacts/requirement.md（阶段 2 产出物），严格执行"刨根问底"——每条关键信息必须有来源、或标记待确认/待补充。
---

## 什么时候用

在 `definition` 阶段，用户要求撰写或修订需求文档时。

## 核心流程

1. **调用 `universal-context-collector` Agent**（Phase 3 前：主 Agent 自己按 `context/team/engineering-spec/design-guidance/context-engineering.md` 的优先级检索）
2. **先输出 3-5 条关键确认点**（见 `ai-collaboration.md` 渐进式输出规则）：
   - 已获取的关键上下文来源
   - 需要用户确认的信息
   - 涉及选择的决策点
3. **用户确认后**，基于 `templates/requirement.md.tmpl` 撰写正式文档
4. **刨根问底**：按 `reference/sourcing-rules.md` 的三态规则标注每条关键信息
5. **本地自检**：成稿后跑 `bash scripts/check-sourcing.sh --requirement <REQ-ID>`，期望退出码 = 0；有 error 必须修复后再进入下一阶段（`/requirement:next` 门禁会再跑一次）
6. **提示补 meta.yaml 语义字段**：requirement.md 成稿后，提醒用户补齐 `meta.yaml` 的语义组（`feature_area / change_type / affected_modules / tags`）——这些字段是跨需求检索的基础，bootstrap 阶段为空，离开 definition 阶段前必须补齐

## 硬约束

- ❌ 禁止出现"没来源但看起来合理就写了"的第四种状态
- ❌ 禁止一次性输出完整长文档（必须先出关键确认点）
- ❌ 禁止跳过"提示补语义字段"这一步——后续 `/requirement:next` 门禁会校验，不提示会让用户在门禁处被卡住
- ✅ 每条事实性信息必须是三态之一：有引用 / `[待用户确认]` / `[待补充]`
- ✅ `[待补充]` 必须附假设（内容、依据、风险、验证时机）

## meta.yaml 语义字段速查（用于提示用户）

| 字段 | 含义 | 合法值来源 |
|---|---|---|
| `feature_area` | 所属业务域 | `context/project/<project>/areas.yaml` 白名单 |
| `change_type` | 变更类型 | `context/team/engineering-spec/meta-schema.yaml` 枚举（feature/bugfix/refactor/perf/security） |
| `affected_modules` | 涉及模块 | 自由词，建议与 `services` 子模块对齐 |
| `tags` | 细粒度标签 | 自由词，可选 |

## 参考资源

- [`reference/sourcing-rules.md`](reference/sourcing-rules.md) — 三态规则与示例
- [`templates/requirement.md.tmpl`](templates/requirement.md.tmpl) — 需求文档模板
