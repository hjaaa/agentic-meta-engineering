# 刨根问底三态规则

需求文档里的每条**关键事实信息**（业务规则、接口约定、数据结构、性能指标等）必须属于以下三态之一：

## 状态 1：有引用 ✅

有项目内文件或外部官方来源可以追溯。

**格式**：在事实后紧跟引用 `（来源：context/project/X/api-spec.md:42）`

**示例**：
> 用户登录失败后需延迟 5 秒再允许重试（来源：context/project/auth-service/security.md:88）。

## 状态 2：[待用户确认] ⚠️

业务规则合理但无项目内来源，需用户提供依据或确认。

**格式**：事实后加 `[待用户确认]`，并在文档末尾"待澄清清单"列出。

**示例**：
> 密码长度不少于 12 位 [待用户确认]。

**文档末尾清单**：
```
## 待澄清清单

1. 密码长度 12 位的依据（是公司统一安全规范还是本需求独有？）
```

## 状态 3：[待补充] 🚧

连假设依据都不清晰，但如果无此条件则无法推进。必须给出完整"假设记录"。

**格式**：
```markdown
> 本需求假设 QPS 峰值不超过 1000 [待补充]
> - 内容：QPS ≤ 1000
> - 依据：类似业务场景的历史经验估算
> - 风险：如实际 > 5000，当前架构无法支撑
> - 验证时机：灰度发布首周
```

## 严格禁止的第四态 ❌

**"没来源但看起来合理就写了"** —— 这是幻觉的来源。评审时发现即标记 `needs_revision`。

## 评审依据

`requirement-quality-reviewer` Agent（Phase 3）会扫描文档里所有关键信息是否标注了三态之一。Phase 2 期间由主 Agent 自检。

## 可执行校验

三态规则已下沉为脚本，不再只靠语义 reviewer：

- `bash scripts/check-sourcing.sh <path.md>` — 单文件自检
- `bash scripts/check-sourcing.sh --requirement <REQ-ID>` — 扫该需求所有 artifacts
- `bash scripts/check-sourcing.sh --all --strict` — CI 全量强校验

检查项（代码见 `scripts/lib/check_sourcing.py`）：

| 码 | 严重度 | 描述 |
|---|---|---|
| E001 | error | `[待补充]` 段落缺假设四要素（内容/依据/风险/验证时机 ≥3）|
| E002 | error | `（来源：...）` 引用路径不存在 |
| E003 | error | `（来源：path:N）` 行号超出目标文件 |
| W001 | warning | 含 `[待用户确认]`/`[待补充]` 但缺 `## 待澄清清单` 章节 |
| W002 | warning | 强约束数字断言但整段无三态标记（疑似第四态幻觉）|
| W003 | warning | 待澄清清单条目数 < 标记总数 |

`definition → tech-research` 阶段门禁强制 error = 0；warning 由 CI 的 `--strict` 兜底。
