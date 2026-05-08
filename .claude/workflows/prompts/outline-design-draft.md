# 概要设计起草（prompt 节点）

> 此 prompt 由阶段 4 outline-design-draft 节点引用。
> 引擎已替换变量：`$RUN_ID` / `$ARTIFACTS_DIR` / `$tech-feasibility-assess.output.*`

## 任务

基于已有的需求文档和技术预研结论，撰写概要设计文档 `$ARTIFACTS_DIR/outline-design.md`。

## 输入素材

### 需求文档
$ARTIFACTS_DIR/requirement.md

### 技术预研结论
- 可行性：$tech-feasibility-assess.output.feasibility
- 影响模块：$tech-feasibility-assess.output.affected_modules
- 风险清单：$tech-feasibility-assess.output.risks
- 工作量估算：$tech-feasibility-assess.output.estimated_person_days 人天

详细预研报告：$ARTIFACTS_DIR/tech-feasibility.md

## 产出规格

`$ARTIFACTS_DIR/outline-design.md` 必须包含 4 个章节（H2）：

### # 架构方案

- 整体架构图（mermaid 或 ASCII）
- 数据流向（从 API 入口到持久化）
- 关键组件职责说明（≤ 200 字 / 组件）

### # 模块划分

- 涉及哪些既有模块（列出 file:line 范围）
- 新增哪些模块（如有）
- 模块间的依赖关系（不能有环）
- 每个模块的"对内对外"接口轮廓（不要细节，那是阶段 5 干的）

### # 技术选型

- 用什么框架/库（限定项目既有）
- 为什么这样选（对比至少一个替代方案）
- 引入的新依赖（如有）— 必须给迁移成本估算

### # 关键流程

- 主路径的时序图（mermaid sequenceDiagram，≥ 3 个 actor）
- 异常路径的回退策略
- 状态流转（如有状态机）

## 引用要求

每条技术决策必须有依据：
- 引用现有代码：`src/path/file.java:行号`
- 引用 requirement.md 的具体章节：`requirement.md §3.2 验收标准`
- 引用 tech-feasibility.md 的具体段落：`tech-feasibility.md §风险评估`
- 引用外部权威文档：`<URL>` 或 `<规范名 §章节>`

无依据的决策必须标注 `[待补充]` 或 `[待确认]`，并在 `notes.md` 加一条 TODO。

## 边界

不要做的事：
- ❌ 写接口签名（那是阶段 5 详细设计的事）
- ❌ 写 SQL 字段（那是阶段 5）
- ❌ 写测试用例（阶段 8）
- ❌ 写 features.json（阶段 5）
- ❌ 详细的错误码（阶段 5）

要做的事：
- ✅ 把"做什么 / 怎么组织"讲清楚
- ✅ 风险与权衡显式化
- ✅ 模块边界与职责清晰

## 完成动作

1. 写完 `$ARTIFACTS_DIR/outline-design.md`
2. 在 `runs/$RUN_ID/notes.md` 末尾追加：
   - "概要设计起草完成"
   - 任何待用户决策的 [待确认] 项
3. 输出本节点的 stdout：
   - 产出文件列表
   - 待确认项清单（如有）
   - 字符 "DRAFT_COMPLETE"

引擎拿到 stdout 后进入 outline-design-review 节点（agent: outline-design-quality-reviewer）做评审。
