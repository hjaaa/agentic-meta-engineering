# 提取规则

## 从 features.json 提取

### JSON 结构约定

`features.json` 是阶段 5（详细设计）产出的权威清单，阶段 6/7/8 只读不改（阶段 7 可能追加 `status` 字段）。

```json
{
  "features": [
    {
      "id": "F-001",
      "title": "用户注册",
      "description": "支持邮箱+密码注册，自动发送验证邮件",
      "type": "feat",
      "interfaces": [
        {"name": "POST /api/users", "schema_ref": "detailed-design.md#user-create-api"}
      ],
      "interfaces_frozen": true,
      "depends_on_features": [],
      "depends_on_modules": ["email-service"],
      "touches": ["src/user/**", "src/auth/register.go"],
      "complexity": "medium",
      "shared_resources": ["db.schema.user"],
      "notes": "邮件模板和 email-service 对齐"
    }
  ]
}
```

### 字段说明

| 字段 | 必填 | 类型 | 语义 | 缺省 / 兼容 |
|---|---|---|---|---|
| `id` | ✅ | string | 唯一 feature 标识（`F-xxx`） | — |
| `title` | ✅ | string | 短名，< 30 字 | — |
| `description` | ✅ | string | 一句话描述，< 200 字 | — |
| `type` | 🟡 | enum | `feat` \| `fix` \| `refactor` \| `docs` \| `test` \| `chore` | 缺省 = `feat` |
| `interfaces` | 🟡 | array | 对外接口清单，每项 `{name, schema_ref}` | 缺省 = `[]` |
| `interfaces_frozen` | 🟡 | bool | 接口契约是否在详细设计中已冻结（未冻结 → 实现中仍可能改契约，subagent 派发会更保守） | 缺省 = `false` |
| `depends_on_features` | 🟡 | string[] | **依赖的其他 feature_id**（阶段 7 用于校验前置已 done） | 缺省 = `[]` |
| `depends_on_modules` | 🟡 | string[] | **依赖的外部/既有模块名**（仅用于上下文提示） | 缺省 = `[]` |
| `touches` | 🟡 | string[] | 该 feature 预计触及的文件/目录 glob（用于预测冲突与派发决策） | 缺省 = `[]`（视为"未知范围"→按保守策略处理） |
| `complexity` | 🟡 | enum | `low` \| `medium` \| `high`；决定 subagent 模型档位 | 缺省 = `medium` |
| `shared_resources` | 🟡 | string[] | 共享 DB 表 / schema / 配置键等 | 缺省 = `[]` |
| `notes` | 🟡 | string | 补充说明 | 缺省 = `""` |
| `dependencies` | ⚠️ deprecated | string[] | 旧字段，语义混杂模块名和 feature_id | 读取方应优先用 `depends_on_features` / `depends_on_modules`；仅当新字段全缺失时作回退 |

必填三项（`id`/`title`/`description`）是 `gate-checklist.md` 的 `detail-design → task-planning` 门禁卡口；其余为**可选增强**，不填不挡门禁，但阶段 7 的 subagent 派发判断会退化为最保守策略（串行 + medium 模型）。

### 提取规则

提取：`features.json` 中 `id == feature_id` 的那条完整对象（JSON stringify 即可）。

### 依赖字段的优先级

读取方（`feature-lifecycle-manager` / `task-context-builder`）解析依赖时：

1. 若存在 `depends_on_features` / `depends_on_modules` → 按新字段语义处理
2. 若仅存在旧 `dependencies` → 启发式判断（形如 `F-\d+` 归入 feature 依赖，其余归入模块依赖），并在输出里提示"建议升级到新字段"
3. 两者同时存在 → 以新字段为准，忽略旧字段

### complexity → 模型档位映射

`feature-lifecycle-manager` 派发 subagent 时按以下默认映射挑模型，允许用户覆盖：

| complexity | 默认模型 | 适用场景 |
|---|---|---|
| `low` | haiku | 单文件 / 规格完整 / 机械实现（CRUD、DTO 转换、配置项） |
| `medium` | sonnet | 多文件协同 / 需要模式匹配 / 常规业务逻辑 |
| `high` | opus | 需架构判断 / 跨模块集成 / 并发或事务设计 |

## 从 detailed-design.md 提取

匹配规则（优先级降序）：

1. HTML 锚点匹配：`schema_ref` 中的 `#xxx` 部分 → grep `<a id="xxx">` 或 `{#xxx}`
2. 标题匹配：查找包含 feature_id 的章节标题（如 `## F-001: 用户注册`）
3. 注释匹配：`<!-- @feature:F-001 -->` 块

提取整个段落（直到下一个同级标题）。

## 从代码库提取

**仅在开发阶段需要时**提取：

- grep 接口路径（如 `/api/users`）的现有实现
- grep 数据结构名（如 `UserCreateRequest`）
- `features.json.depends_on_modules` 列出的模块（grep 该模块目录）
- `features.json.touches` 列出的文件 glob（Read 少量关键文件，不要整目录 ls）

**不要**：

- 全量 `ls` 代码目录
- 读整个大文件

## 输出格式

```markdown
# F-001 · 用户注册 — 开发上下文

## 基本信息

- **复杂度**: medium → 建议模型档位 sonnet
- **接口契约冻结**: 是
- **触及范围**: `src/user/**`, `src/auth/register.go`
- **共享资源**: `db.schema.user`

## 需求描述

支持邮箱+密码注册，自动发送验证邮件。

## 接口

### POST /api/users

- 请求：`UserCreateRequest { email, password }`
- 响应：`UserCreateResponse { id, verificationSent }`
- 设计详情：see `artifacts/detailed-design.md:L120-L145`

## 依赖

### 依赖的 feature

- 无（或列出 F-ID 及其当前 status）

### 依赖的模块

- `email-service` — 邮件发送（已有接口 `SendEmail(template, to, data)`）

## 相关现有代码

- 用户实体：`src/entity/User.java:15`
- 邮箱验证旧流程（参考）：`src/service/EmailVerifier.java:88`

## 注意事项

邮件模板和 email-service 对齐（来自 features.json.notes）
```

输出里**必须带**「复杂度」「接口契约冻结」「触及范围」「依赖的 feature」四项——它们是 `feature-lifecycle-manager` 阶段 7 派发 subagent 时选模型档位、校验前置依赖、判独立性的机读入口。
