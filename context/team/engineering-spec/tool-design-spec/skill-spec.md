# Skill 设计规范

**Skill 是专业知识包，不是脚本执行器。**

## 硬约束

| 约束 | 数值 | 理由 |
|---|---|---|
| `SKILL.md` 大小 | < 2k token（约 500 汉字 + 代码） | Skill 进主对话上下文，必须轻量 |
| 内容类型 | 指令（灵活指导）/ 代码（确定性操作）/ 资源（模板） | 三种各司其职 |
| 资源层级 | "一跳可达" | 从 SKILL.md 直接链接到 reference/ 文件，不允许深层嵌套 |
| 默认假设 | "Claude 已经很聪明" | 只补充 Claude 没有的信息，不重复常识 |

## 渐进式披露架构

```
.claude/skills/<skill-name>/
├── SKILL.md          ← 入口 < 2k token。进入主对话上下文
├── reference/        ← 详细知识，Agent 按需读取
│   ├── rule-xxx.md
│   └── field-spec.md
├── templates/        ← 模板文件，复制-填值使用
│   └── xxx.md
└── scripts/          ← 确定性脚本
    └── validate.sh
```

## `SKILL.md` 骨架

```markdown
---
name: <skill-name>
description: 一句话说这个 Skill 做什么 + 在什么场景被触发
---

## 什么时候用这个 Skill

触发条件。和其他 Skill 的边界。

## 核心流程

三步以内概括。细节引用 reference/。

## 硬约束

3-5 条必须遵守的规则，用 ❌/✅ 对比显式给出。

## 参考资源

- [`reference/xxx.md`](reference/xxx.md) — 详细 X
- [`templates/yyy.md`](templates/yyy.md) — 模板 Y
```

## 三种内容类型

### 指令（Prose Instructions）

写在 SKILL.md 和 reference/*.md 里。告诉 Agent "做什么 + 注意什么"，不规定具体步骤。

### 代码（Deterministic Scripts）

写在 scripts/ 下。用于确定性操作（JSON 校验、文件格式转换、git 命令组合）。当步骤明确且可自动化时用脚本，比让 AI 推理可靠。

### 资源（Templates & References）

- templates/ — 让 AI 复制并填值（如 `requirement.md` 的骨架）
- reference/ — 让 AI 查（如字段类型表、枚举值表）

## 反面：Skill 不应该做的事

- 封装流程（"先做 A 再做 B 再做 C"）—— 应该封装知识
- 假设 AI 不懂常识（"如何写 Markdown" 之类）
- 跨 Skill 调用（Skill 之间通过主 Agent 协调）
