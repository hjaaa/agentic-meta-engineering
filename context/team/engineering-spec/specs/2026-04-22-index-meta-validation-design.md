# INDEX 自动校验 + meta.yaml 字段扩展 · 设计记录

**日期**：2026-04-22
**作者**：huangjian
**状态**：已落地（2026-04-22 用户主动触发前置实施，非规模信号驱动）。落地结果见 `context/team/engineering-spec/roadmap.md` 的"S2 当前档位评估"段
**关联文档**：
- `context/team/engineering-spec/design-guidance/context-engineering.md`（检索哲学来源）
- `.claude/skills/managing-knowledge/reference/organize-index.md`（现有人工整理流程）
- `.claude/skills/managing-requirement-lifecycle/templates/meta.yaml.tmpl`（当前 meta schema）

---

## 1. 背景与问题

### 1.1 当前体系如何检索知识

项目采用 **agentic search** 而非 RAG——Agent 按 `context-engineering.md` 第 3 条"渐进式披露"原则，先读 INDEX.md 决定去哪，再按路径深入。这套机制在当前规模（< 100 份 md / < 10 个需求）跑得好。

### 1.2 规模到 S3（300+ 份 md / 50+ 需求）会断的两个点

1. **INDEX 腐化**
   - 新增 md 忘了挂到 INDEX
   - INDEX 里的链接因文件重命名失效
   - INDEX.md 超过"< 200 行"的设计红线
   - 后果：Agent 第一跳看不全，或读到过期入口

2. **meta.yaml 缺乏语义标签**
   - 当前字段全是**流程类**（`phase / branch / pr_url / ...`），没有"这个需求是什么"的结构化标签
   - `/requirement:list` 只能按 `phase` 筛
   - Agent 想找"所有登录相关历史需求"→ 没字段可查，只能扫 title 字符串
   - 后果：跨需求复用失效，经验无法结构化沉淀

### 1.3 为什么现在写下来而不是等以后

- 这两件事**到了规模再做代价指数上升**：历史需求回填工作量大、INDEX 已积累大量腐化条目、团队已形成"反正不维护"的习惯
- 方案本身不复杂，但涉及多个 skill 的协同（`managing-knowledge` / `managing-requirement-lifecycle` / `requirement-bootstrapper`），需要提前拉通
- 留一份设计记录，真要启动时直接照做，避免重新讨论

---

## 2. 设计目标与非目标

### 2.1 做什么（机械校验）

| 能力 | 归属 |
|---|---|
| INDEX 条目 ↔ 文件系统一致性校验 | INDEX 校验 |
| INDEX.md 体检（行数、孤岛 md 检测） | INDEX 校验 |
| meta.yaml schema 校验（必填 / 枚举 / 格式） | meta 校验 |
| meta.yaml 语义字段（支持反向索引的基础） | meta 扩展 |

### 2.2 不做什么（守哲学）

| 不做 | 理由 |
|---|---|
| 不自动改 INDEX.md | "遗漏"有 3 种语义（真漏 / 故意不列 / 未来占位），机器分不清；自动改会变成"狼来了" |
| 不检查 INDEX 描述词质量 | 属于 LLM 判断，不适合 CI |
| 不强制每份 md 都被 INDEX 引用 | 有些 md 是 reference 级被上层引用，不进主入口是合理的 |
| 不检查 md 内容结构 | 属于 review 环节 |
| 不对历史需求强制回填新字段 | 增量改造，以后改哪个补哪个 |
| 不引入 JSON Schema / 向量库 / 外部索引服务 | 保持"所有配置即易读 YAML/MD"，对齐"文档即记忆"原则 |

---

## 3. 方案一：INDEX 自动校验

### 3.1 检查项清单

| 检查项 | 类别 | 判定方式 |
|---|---|---|
| 实际存在但 INDEX 未列 | **遗漏**（warning） | 扫 INDEX 所在目录的 md 和一级子目录，对比 INDEX 链接集合 |
| INDEX 列了但文件不存在 | **腐化**（error） | 解析 INDEX 里的相对链接 → fs 检查 |
| INDEX 指向文件但路径已改 | **腐化**（error） | 同上（fs 层面就是"文件不存在"） |
| INDEX 内锚点 `file.md#sec` 的 section 不存在 | **软腐化**（warning） | 读 md 提取 H2/H3 标题对比 |
| 全局存在但无任何 INDEX 引用的 md | **孤岛**（warning） | 全局反查所有 INDEX 的链接集合 |
| INDEX.md 超过 200 行 | **违反设计红线**（warning） | wc -l |

### 3.2 工具结构

```
scripts/
├── check-index.sh         # 入口（0 / 1 退出码），包一层 python
└── lib/
    ├── check_index.py     # 核心扫描逻辑
    └── index-config.yaml  # 白名单、忽略规则
```

**选 Python 而非纯 Bash**：markdown 链接解析、锚点提取需要正则 + 结构化处理，bash 写起来易错。

### 3.3 `index-config.yaml` 的作用

```yaml
ignore:
  # 不进主入口也合法的 md（被其他 md 引用即可）
  - "context/team/engineering-spec/**/_draft/*.md"
  - "requirements/**/notes.md"
  - "CLAUDE.md"
  - "README.md"

warn_line_limit: 200      # INDEX.md 超过此行数告警
scan_roots:
  - context/
  - requirements/
```

### 3.4 命令行契约

```
# 日常：全量校验
bash scripts/check-index.sh

# CI：只输出错误级，不输出 warning
bash scripts/check-index.sh --strict

# 开发：输出"建议补丁"但不落盘
bash scripts/check-index.sh --dry-run-fix
```

### 3.5 输出样例

```
context/team/INDEX.md
  ❌ 腐化: ./onboarding/learning-path/ 不存在
  ⚠️  遗漏: ./rollout/embedded-push-playbook.md 存在但未列

context/team/engineering-spec/INDEX.md
  ⚠️  孤岛: plans/active/draft.md 全局无引用
  ⚠️  超长: 共 215 行 > 200

Total: 1 error, 3 warnings
```

### 3.6 CI 接入：三种姿势对比

| 方式 | 载体 | 优点 | 缺点 |
|---|---|---|---|
| **A** pre-commit git hook | 本地 | 零基础设施、即时反馈 | 可被 `--no-verify` 绕过 |
| **B** GitHub Actions | 云端 | 强制、有记录、权威 | 需新建 `.github/workflows/`（项目当前没有） |
| **C** Claude Code PostToolUse hook | `.claude/hooks/` | 和项目 hook 体系统一 | Agent 每改一次 md 都跑，代价高 |

**决策：A + B 双轨。**
- A 覆盖日常反馈
- B 兜底，PR 红叉绕不过
- **不采用 C**：Agent 改 md 频繁，每次都跑 check 会拖慢对话

### 3.7 与现有 `/knowledge:organize-index` 的关系

- `/knowledge:organize-index`：**人工触发的修复工具**，生成修复建议并让人确认（保留"语义判断"能力）
- `check-index.sh`：**自动化的告警工具**，只报告不修改
- 两者协同：CI 发现 → 人用 `/knowledge:organize-index` 修

---

## 4. 方案二：meta.yaml 字段扩展

### 4.1 当前 schema 的问题

```yaml
# templates/meta.yaml.tmpl 现状
id: __REQ_ID__
title: __TITLE__
phase: bootstrap
created_at: __ISO8601__
branch: __BRANCH__
base_branch: __BASE_BRANCH__
project: __PROJECT__
services: []
gates_passed: []
pr_url: ""
pr_number: 0
```

**全是流程元数据，零个语义标签。** 规模 50+ 需求时：
- 跨需求查找只能靠 title 字符串匹配
- 没有"业务域 / 变更类型 / 结果"维度
- 无法为反向索引提供锚点

### 4.2 扩展后的 schema

字段分三组：

```yaml
# ============ 流程组（现有，不动） ============
id: REQ-2026-001
title: "接入短信登录"
phase: development
created_at: 2026-04-22T10:00:00Z
branch: feat/req-2026-001
base_branch: develop
project: yh-platform
services: [yh-user, yh-gateway]
gates_passed: [requirement, design]
pr_url: ""
pr_number: 0

# ============ 语义组（新增，检索用） ============
feature_area: auth              # 必填，枚举，从项目 areas.yaml 选
change_type: feature            # 必填，枚举（全局）
affected_modules: [user, sms]   # 必填，自由词（建议与 services 子模块对齐）
tags: [sms, otp, third-party]   # 可选，自由词

# ============ 结果组（新增，done 时才填） ============
outcome: ""                     # shipped | abandoned | rolled-back
completed_at: ""                # done 时填
lessons_extracted: false        # /knowledge:extract-experience 是否已跑
```

### 4.3 字段设计细节

#### `feature_area`（强约束枚举 · 项目级定义）
- 必填，值必须在 `context/project/<project>/areas.yaml` 白名单里
- 每个业务项目自己定义域（auth / payment / report / infra / ...）
- **这是未来反向索引 `by-area.json` 的基础**

为什么放项目级而非团队级：业务域是项目维度的事，团队级是通用规范，不应该知道具体业务——对齐"位置即语义"原则。

#### `change_type`（强约束枚举 · 团队级定义）
- 必填，五选一：`feature / bugfix / refactor / perf / security`
- 白名单放 `context/team/engineering-spec/meta-schema.yaml`（新建）
- 跨项目统一，用于团队级统计和 PR 模板

#### `affected_modules`（弱约束）
- 必填但不校验值
- 建议和 `services` 下的子模块对齐，做不到不阻塞
- 给 grep 和反向索引用

#### `tags`（完全自由）
- 长尾细粒度标签
- 不归一化（S4 阶段做术语表时再归一）

#### `outcome`（结果字段）
- 三值：`shipped / abandoned / rolled-back`
- **这是经验沉淀最值钱的字段**：`abandoned` 和 `rolled-back` 的需求往往藏着最深的教训
- 当前 `phase` 机制无法区分"做完了"和"做完了但翻车了"

#### `lessons_extracted`（布尔标志）
- 配合未来的"done 前强制 `/knowledge:extract-experience`"机制
- 先记录，不强制——留给 S4 阶段再加强制性

### 4.4 Schema 定义文件

**新增 `context/team/engineering-spec/meta-schema.yaml`**（团队级）：

```yaml
# 组名用英文（process / semantic），与脚本实现保持一致
required_fields:
  process:  [id, title, phase, created_at, branch, base_branch, project, services]
  semantic: [feature_area, change_type, affected_modules]

# phase 枚举的权威来源是 .claude/skills/managing-requirement-lifecycle/reference/phase-rules.md
# 此处仅同步一份供脚本直接读取，不作为独立事实源
enums:
  phase:
    - bootstrap
    - definition
    - tech-research
    - outline-design
    - detail-design
    - task-planning
    - development
    - testing
    - completed
  change_type: [feature, bugfix, refactor, perf, security]
  outcome: [shipped, abandoned, rolled-back]

format:
  created_at: iso8601
  completed_at: iso8601
  id: ^REQ-\d{4}-\d{3}$

# 条件必填：bootstrap 允许语义组为空，其它阶段必填；completed 阶段回写结果组
conditional_required:
  - when: { phase_not: [bootstrap] }
    non_empty: [feature_area, change_type, affected_modules]
  - when: { phase: completed }
    non_empty: [outcome, completed_at]

# feature_area 的白名单来自项目目录下的 areas.yaml（由 check-meta 按 meta.project 路径加载）
project_scoped_enums:
  feature_area:
    source: "context/project/{project}/areas.yaml"
    key: areas
```

**新增 `context/project/<project>/areas.yaml`**（项目级，每项目一份）：

```yaml
# yh-platform 业务域白名单
areas:
  - auth
  - payment
  - order
  - report
  - infra
  - gateway
```

### 4.5 校验工具：`scripts/check-meta.sh`

```bash
# 单文件
bash scripts/check-meta.sh requirements/REQ-2026-001/meta.yaml

# 全量（CI 用）
bash scripts/check-meta.sh --all

# --strict：phase=completed 但 outcome 为空算 error
bash scripts/check-meta.sh --all --strict
```

**实现选型**：Bash 壳 + `python3 + pyyaml`。不引入 `yq` 等新二进制依赖——pyyaml 在 CI 和本地已是默认可用，与 INDEX 校验共享 `scripts/lib/common.py`。

### 4.6 接入现有流程

| 接入点 | 做什么 |
|---|---|
| `requirement-bootstrapper` agent | 新建时生成带 `__PLACEHOLDER__` 的完整骨架（语义组字段先留空） |
| `requirement-doc-writer` skill | 阶段 2 写完 requirement.md 后，提示用户补语义组字段 |
| `managing-requirement-lifecycle` 的 gate-checklist | `/requirement:next` 进入下一阶段前跑 check-meta，未通过阻断 |
| CI（GitHub Actions） | PR 时批量校验所有 meta.yaml |

**关键约束**：`check-meta` 在 gate-checklist 里是"**硬门禁**"——meta 不合法不给过阶段切换；CI 是"**软兜底**"——防止绕过门禁的脏数据进主干。

---

## 5. 落地顺序与工作量

| Step | 内容 | 工作量 | 依赖 |
|---|---|---|---|
| 1 | 扩 meta.yaml schema：改模板 + 建 meta-schema.yaml + 建 areas.yaml 示例 | 半天 | 无 |
| 2 | 写 `check-meta.sh`，接入 gate-checklist | 半天 | Step 1 |
| 3 | 写 `check-index.sh` + index-config.yaml | 1 天 | 无 |
| 4 | 接 pre-commit hook + GitHub Actions workflow | 半天 | Step 2、3 |
| 5 | 历史数据回填（不强制，增量改） | 持续 | Step 1-4 |

**总计**：2-3 天 × 可分 3-5 个 PR 合入。

**推荐首 PR 顺序**：Step 1 → Step 2 → Step 3 → Step 4。
Step 1 是所有后续的基础，但单独落地不影响现网（只改模板和新建 schema）。

---

## 6. 关键设计决策及理由

### 6.1 为什么 INDEX 校验"只报告不自动改"

"遗漏"有 3 种语义机器区分不了：
1. **真遗漏**：作者忘挂 → 应该加
2. **故意不列**：内部引用的 reference 文件 → 不该加
3. **未来占位**：先写骨架等规划 → 暂不加

自动改会混淆三者，久之变成"工具太吵，关掉"。**让工具只做它能做对的事。**

### 6.2 为什么 meta.yaml 新字段分强 / 弱约束

| 强制 | 弱约束 |
|---|---|
| `feature_area / change_type / affected_modules` — 反向索引的基础，不强制就白搭 | `tags / outcome / lessons_extracted` — 低频用，强制增加摩擦但收益边际 |

守的原则：**凡对"未来可检索性"有直接影响的字段强制，否则不强制。**

### 6.3 为什么业务域 `areas.yaml` 放项目级而非团队级

- 业务域是项目维度的事，团队级不应知道具体业务
- 对齐"位置即语义"：`context/project/<X>/` 就是 X 项目的知识
- 允许不同项目有不同业务域划分，不强行统一

### 6.4 为什么不引入 JSON Schema / Pydantic

- 项目哲学是"配置即易读 YAML/MD"，不增加"只有开发能读懂"的层
- 团队成员学习成本
- 自写 bash 校验脚本对当前规模够用；未来真到瓶颈（schema 涨到 50+ 字段）再切
- 原则："**不预先引入复杂度**"

### 6.5 为什么 CI 用 A+B 双轨而非单轨

- 只有 A（pre-commit）：容易被 `--no-verify` 绕过
- 只有 B（GitHub Actions）：本地看不到红叉，修复反馈慢
- 两个一起：日常快反馈 + 关键兜底，代价只多一个 workflow 文件

### 6.6 为什么不做 Claude Code PostToolUse hook（方案 C）

- Agent 改 md 频繁（一个会话可能 20+ 次），每次都跑 check 会显著拖慢对话
- Agent 场景本来就有 review 机制，不需要即时校验
- 保留这个位置给"更轻量的工具级检查"（目前已有 `auto-progress-log`）

---

## 7. 触发条件：什么时候真正启动这个 plan

不要因为本设计记录存在就立即动手。触发信号如下（满足任一即可开工）：

| 信号 | 说明 |
|---|---|
| PR review 中连续 3 次发现 INDEX 未更新 | 手工维护已失效 |
| `context/**/*.md` 总数 > 100 | 腐化概率显著上升 |
| `requirements/` 总数 > 30 | 跨需求查询出现痛点 |
| 同一个坑被不同 REQ 踩 2 次 | `outcome` 字段 + 经验抽取成为刚需 |
| Agent 读 10+ 份 md 仍未命中目标 | 第一跳精度不足 |

**当前（2026-04-22）评估**：以上信号均未出现，但用户选择**主动前置**实施（优先建基建而非等信号），所以 Step 1-4 已全部落地，触发信号表此后作为"第二次评估是否需要额外演进"的参考（例如"治理 warning → 切 CI --strict"、"引入反向索引 by-area.json"等 S3 级增量）。

---

## 8. 相关文档

| 文档 | 相关性 |
|---|---|
| `context/team/engineering-spec/design-guidance/context-engineering.md` | 四条核心原则的来源，本方案严格遵守 |
| `context/team/engineering-spec/design-guidance/four-layer-hierarchy.md` | 四层架构定义，本方案的工具属于"工具层" |
| `.claude/skills/managing-knowledge/reference/organize-index.md` | 人工整理流程，本方案的 CI 与其互补 |
| `.claude/skills/managing-requirement-lifecycle/templates/meta.yaml.tmpl` | 待改的模板 |
| `.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md` | 待接入 check-meta 的门禁位置 |
| `.claude/skills/managing-requirement-lifecycle/reference/phase-rules.md` | phase 枚举的权威来源 |

---

## 9. 未决事项及启动决策

设计阶段识别 4 个待决问题，2026-04-22 启动实施时一并拍板：

| # | 问题 | 决策 | 理由 |
|---|---|---|---|
| 1 | `areas.yaml` 变更流程 | 普通 PR 合入即可，不设架构组门禁 | 骨架项目无架构组；业务域由项目自身维护，符合"位置即语义" |
| 2 | 历史需求回填是否提供 `migrate-meta.sh` | **不提供**；需要时按附录 A 手工补 | 当前 `requirements/` 为空，无负担；脚本化后反而鼓励"回填了事，不反思"的习惯 |
| 3 | `outcome = abandoned / rolled-back` 是否归档到 `requirements/archived/` | **暂不做**；保持单一路径 | 目录层级分化会让 `/requirement:list` 等工具需要同时扫两个根；S3+ 规模再评估 |
| 4 | pre-commit hook 是否默认 setup | **不默认**，`onboarding/agentic-engineer-guide.md` 引导 `git config core.hooksPath scripts/git-hooks` 一键启用 | 避免克隆即改 git 配置；本地 hook 未启用时有 CI 兜底 |

以上 4 条决策的执行痕迹落在本 spec 对应段落（例如 §4.6 引用 onboarding 指引、`scripts/git-hooks/pre-commit` 的内联注释等），后续变更请同步回本表。

---

## 附录 A：字段迁移指南（未来回填时用）

给历史需求补字段的最小操作：

```yaml
# 新增 3 个必填
feature_area: infra          # 如果记不起来，选 infra 兜底
change_type: refactor        # 保守选 refactor
affected_modules: [unknown]  # 允许 unknown

# done 的需求补：
outcome: shipped             # 绝大多数历史需求都是 shipped
completed_at: <git log 最后一次 commit 的时间>
lessons_extracted: false     # 未跑过就填 false
```

补字段本身不触发任何业务逻辑，仅让校验通过。

---

## 附录 B：反向索引（S4 阶段方案，本次不做）

本方案的 meta.yaml 扩展是**反向索引的前置条件**。等 S4 阶段（300+ 需求）时，可基于新 schema 自动生成：

```
context/indexes/
├── by-area.json       # { "auth": ["REQ-2025-003", "REQ-2026-001", ...] }
├── by-module.json     # { "yh-user": [...] }
├── by-outcome.json    # { "rolled-back": [...] }  ← 经验金矿
└── by-change-type.json
```

Agent 查"所有 auth 相关历史需求"直接读 `by-area.json`，O(1) 拿到 REQ id 列表。**不是向量库，是精确反向索引。**
