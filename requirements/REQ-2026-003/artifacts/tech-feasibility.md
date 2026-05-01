---
id: REQ-2026-003
title: 代码审查路由器·卡点 A · 技术可行性评估
created_at: "2026-04-30 11:09:09"
refs-tech-feasibility: true
---

# REQ-2026-003 · 技术可行性评估

## 总结

可行性：**high**。核心路径（path glob 匹配 + tty 热键确认 + yaml 规则加载）全部基于项目现有技术栈或低成本单一新依赖（pathspec），无平台级 bug 依赖。最大风险是 Python 3.11 标准库不支持 globstar 语法（fnmatch / PurePath.match 均不支持 `**` 跨目录匹配，来源：.github/workflows/quality-check.yml:22），以及 scope-schema.md 存在两处文档不一致（trivial 豁免旧描述 + skipped_checkers.reason 关键词遗留），需在同一 PR 修复。无 blocker 级阻碍。

总工作量估算：**6 人天**（design 1 + dev 3 + test 2）。

---

## 1. 关键技术选型

### 1.1 Q1：path glob 引擎选型

路由 yaml 的 must / suggest 段需要支持 `**/auth/**` 等跨任意深度的路径匹配（来源：requirements/REQ-2026-003/artifacts/requirement.md:85）。

**选型对比**：

| 方案 | globstar 支持 | 新增依赖 | 备注 |
|---|---|---|---|
| `fnmatch.fnmatch` | 不支持（`**` 视为普通通配符，不跨目录） | 无 | 无法表达 `**/auth/**` |
| `pathlib.PurePath.match` | Python 3.12+ 才支持；3.11 行为不正确 | 无 | CI 固定 3.11（来源：.github/workflows/quality-check.yml:22）不可用 |
| `pathspec` | 完整支持 gitignore glob 语法含 `**` | 需新增（MIT，~50 KB） | CI 当前仅 pyyaml ruamel.yaml（来源：.github/workflows/quality-check.yml:25） |
| 手写递归匹配 | 可实现 | 无 | 约 50-80 行，维护成本高 |

**结论**：选 `pathspec` 库。gitignore 兼容语法易于开发者理解；调用面收敛在 `PathSpec.from_lines` + `match_files`；单一新依赖，维护活跃，MIT license。prerequisite：修改 `.github/workflows/quality-check.yml:25` 的 pip install 行加入 `pathspec`（来源：.github/workflows/quality-check.yml:25）。

### 1.2 Q2：tty 校验同源性

卡点 B sign-off 的 D-003 深防御第三层在 `scripts/lib/save_review.py` 入口以 `sys.stdin.isatty()` 拒绝非 tty（来源：scripts/lib/save_review.py:406）。卡点 A routing.py 应复用同一模式：入口处执行 `if not sys.stdin.isatty(): sys.exit(2)` 退码 2（来源：requirements/REQ-2026-003/artifacts/requirement.md:58）。

跨终端行为：VS Code 内嵌终端和 SSH 交互式终端均分配 pty，`isatty()` 返回 True，行为正确。管道 / heredoc / subagent 调用中 stdin 非 tty，退码 2，符合预期。CI 非交互环境同样退码 2，阻止误触发。

使用 `sys.stdin.isatty()` 而非 `os.isatty(0)`（两者等价但风格不统一），与 `save_review.py:406` 保持语义完全一致，无新约束引入（来源：context/team/ai-collaboration.md:38）。

**结论**：复用 `sys.stdin.isatty()` 同源实现，零新增依赖，可行。

### 1.3 Q3：yaml 解析与 schema 校验

**yaml 解析**：路由 yaml 为只读配置，不做 round-trip，选 `pyyaml` 的 `yaml.safe_load`（与 `save_review.py` 中分工一致：ruamel.yaml 用于 round-trip 保留注释，pyyaml 用于只读配置读取，来源：scripts/lib/save_review.py:27）。

**schema 校验**：与 `check_meta.py` 手写校验一脉相承（来源：scripts/lib/check_meta.py:1），无新依赖。路由 yaml 结构简单，三段（must / suggest / trivial_whitelist），每段为路径 glob 字符串列表。加载时校验：must 段条目数不超过 5 条（来源：requirements/REQ-2026-003/artifacts/requirement.md:25）、每条为非空字符串、yaml 语法错（`yaml.YAMLError`）→ 退码 4（来源：requirements/REQ-2026-003/artifacts/requirement.md:67）。校验逻辑约 30-40 行，零新增依赖。

**容错性**：用户手改 yaml 时若遇语法错，fail-closed 退码 4 立刻被察觉（来源：requirements/REQ-2026-003/artifacts/requirement.md:109）；不静默降级。

**结论**：pyyaml safe_load + 手写校验，与现有项目风格完全对齐，可行。

### 1.4 Q4：`.review-scope.json` 兼容性与改动面

**现状消费点**：`.review-scope.json` 被以下 3 处使用（来源：.claude/commands/code-review.md:29）：

1. Step 2（行 29-38）：硬编码调 8 个 checker，不读 `checker_route`——是主要改动点
2. Step 3a（行 44）：传 scope 给 review-critic（来源：.claude/commands/code-review.md:44）——仅需在其前加 `skipped` 短路判断
3. Step 3b（行 50）：传 scope 给 code-quality-reviewer（来源：.claude/commands/code-review.md:50）——同上

`checker_route` / `routing_confirmed_by` 字段已在 scope-schema.md 的 F-002 节预先设计（来源：.claude/skills/code-review-prepare/reference/scope-schema.md:62），但 `skipped` 顶层布尔字段**尚未定义**，需在 C5 改动中补充。

**两处文档不一致**：

1. `scope-schema.md:65` 的 `skipped_checkers.reason` 示例为"diff 未命中 concurrency 关键字"（来源：.claude/skills/code-review-prepare/reference/scope-schema.md:65）——关键词扫描逻辑遗留描述，与已否决的关键词方案矛盾，C5 修改时需一并清理。
2. `SKILL.md:20` 描述 `--trivial` 不豁免卡点 A（来源：.claude/skills/code-review-prepare/SKILL.md:20），与已定稿的 trivial 100% 命中白名单跳过整个 review 的决策矛盾（来源：requirements/REQ-2026-003/artifacts/requirement.md:24），C4 修改时需对齐。

critic / judge / report 均为主 Agent 内联逻辑，无独立 SKILL 文件，`skipped=true` 短路在 code-review.md 主流程 Step 2 前由主 Agent 判断并跳过后续步骤（来源：requirements/REQ-2026-003/artifacts/requirement.md:99）。

**改动点清单**：

| 编号 | 文件 | 类型 | 说明 | LOC 估算 |
|---|---|---|---|---|
| C1 | `scripts/lib/code_review_routing.py` | 新增 | 路由引擎 + pyyaml 加载 + must ≤5 校验 + tty 卡点 + 4 档热键 + process.txt audit | ~250 行 |
| C2 | `.claude/code-review-routing.yaml` | 新增 | must(≤5) + suggest + trivial_whitelist 三段规则（来源：requirements/REQ-2026-003/artifacts/requirement.md:85）| ~40 行 |
| C3 | `.claude/commands/code-review.md` | 修改 | Step 2 前增 skipped 短路；Step 2 改为读 checker_route（来源：requirements/REQ-2026-003/artifacts/requirement.md:88）| ~15 行 |
| C4 | `.claude/skills/code-review-prepare/SKILL.md` | 修改 | trivial 100% 命中豁免，修正 SKILL.md:20 的旧描述 | ~5 行 |
| C5 | `.claude/skills/code-review-prepare/reference/scope-schema.md` | 修改 | 新增 `skipped` 顶层字段；清理 skipped_checkers.reason 关键词描述遗留（来源：.claude/skills/code-review-prepare/reference/scope-schema.md:53）| ~15 行 |

---

## 2. 风险清单

| # | 类别 | 描述 | 可能性 | 影响 | 缓解策略 |
|---|---|---|---|---|---|
| R-1 | tech | pathspec glob 语义边界：gitignore 模式中 `auth/**` 与 `**/auth/**` 语义不同（锚定 vs 任意深度），规则作者易混淆导致路径命中不如预期（来源：.claude/skills/code-review-prepare/reference/scope-schema.md:98）| medium | high | detail-design 阶段制定 yaml 书写规范（含通过/拒绝样例）；单元测试覆盖边界匹配场景 |
| R-2 | tech | scope-schema.md 版本漂移：F-002 节预设字段与 routing.py 实现若在不同 PR 合入，字段名不一致导致主 Agent 读空值（来源：.claude/skills/code-review-prepare/reference/scope-schema.md:53）| medium | high | C1/C3/C5 同一 PR 提交；PR checklist 要求 scope-schema.md 与 routing.py 字段名对照 |
| R-3 | tech | trivial 短路文档与代码分叉：SKILL.md:20 旧行为描述与新需求矛盾（来源：.claude/skills/code-review-prepare/SKILL.md:20），若 C4 未同步修改则指引误导 | medium | medium | C4 与 C1 同一 PR；code review checklist 包含 SKILL.md trivial 段落核对 |
| R-4 | business | must 规则初稿可能与实际目录不匹配：5 条草案（auth / payment / db migrations / api 契约 / sql）需对应本仓库实际目录结构，定稿前存在漏报/误报风险（来源：requirements/REQ-2026-003/artifacts/requirement.md:25）| medium | medium | detail-design 阶段比对 services 实际目录后定稿；testing 阶段跑含 must 路径的 diff 验证命中 |
| R-5 | ops | pathspec 未锁定版本：CI 加入 `pip install pathspec` 若不锁版本，未来破坏性更新导致 glob 语义漂移（来源：.github/workflows/quality-check.yml:25）| low | low | quality-check.yml 中锁定版本下界（如 `pathspec>=0.11`）；本地与 CI 版本一致 |
| R-6 | tech | trivial-skip 端到端测试缺口：兼容性改动需配套测试（来源：requirements/REQ-2026-003/artifacts/requirement.md:74），若测试未覆盖 trivial-only diff 路径，skipped=true 短路可能在主 Agent 流程中被忽视 | medium | high | testing 阶段端到端测试覆盖 trivial-only diff 与 mixed diff 两个场景 |

---

## 3. 工作量估算

**估算依据**：参考 REQ-2026-001/002 类似任务约 1-1.5 天/功能模块（来源：requirements/REQ-2026-002/artifacts/tech-feasibility.md:100）；routing.py 是核心模块（约 250 行，含路由逻辑、tty 卡点、热键处理、audit 写入），比单个 check_meta.py 复杂度高，估 1.5 天 dev。

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| F-A：routing.py 核心 + routing.yaml 初稿（C1+C2）| 0.5 | 1.5 | 1 | 3 |
| F-B：三处文档修改（C3+C4+C5）| 0.5 | 0.5 | 0.5 | 1.5 |
| F-C：集成/e2e 测试 + CI 依赖修改 | 0 | 1 | 0.5 | 1.5 |
| **总计** | **1** | **3** | **2** | **6** |

---

## 4. 前置条件

1. `pathspec` 加入 CI 依赖：修改 `.github/workflows/quality-check.yml:25`，`pip install pyyaml ruamel.yaml pathspec`；本地开发同步安装（来源：.github/workflows/quality-check.yml:25）。
2. must 规则 5 条草案需在 detail-design 阶段与实际 services 目录结构比对后定稿，确认 auth / payment / db migrations / api 契约 / sql 路径覆盖完整（来源：requirements/REQ-2026-003/artifacts/requirement.md:115）。
3. scope-schema.md 的 `skipped` 顶层字段定义（C5）需与 routing.py（C1）同一 PR 提交（来源：.claude/skills/code-review-prepare/reference/scope-schema.md:53）。
4. SKILL.md 的 trivial 豁免行为（C4）需与 routing.py（C1）同一 PR 提交，避免 SKILL.md 指引与实现分叉（来源：.claude/skills/code-review-prepare/SKILL.md:20）。
5. detail-design 阶段明确退码 3 的具体触发场景（需求关键决策表列出退码 3/4，但场景描述中只有退码 2 和退码 4 有明确对应，来源：requirements/REQ-2026-003/artifacts/requirement.md:109）。

---

## 5. 阻塞项

无 blocker 级阻碍。

---

## 待澄清清单

1. must 规则 5 条草案（auth / payment / db migrations / api 契约 / sql）是否与本仓库 services 目录约定完全匹配，detail-design 阶段比对后定稿（来源：requirements/REQ-2026-003/artifacts/requirement.md:115）[待用户确认]。
2. 退码 3 的具体触发场景：需求关键决策表提到"退码 3/4 终止"（来源：requirements/REQ-2026-003/artifacts/requirement.md:109），但场景描述只有退码 2（非 tty，来源：requirements/REQ-2026-003/artifacts/requirement.md:58）和退码 4（yaml 加载失败，来源：requirements/REQ-2026-003/artifacts/requirement.md:67）有明确对应，退码 3 对应的失败类型（如规则集为空/无规则命中）需 detail-design 明确 [待用户确认]。
3. trivial 白名单是否包含 `requirements/<id>/notes.md`（来源：requirements/REQ-2026-003/artifacts/requirement.md:116）[待用户确认]。
4. 自定义子集输入连续无效 3 次作为 abort 阈值是否合理，testing 阶段人工试用感受验收（来源：requirements/REQ-2026-003/artifacts/requirement.md:118）[待用户确认]。
5. pathspec 版本锁定策略 [待补充]
   - 内容：quality-check.yml 中 `pip install pathspec` 是否需要锁定版本下界（如 `pathspec>=0.11,<1.0`）
   - 依据：CI 当前对 pyyaml/ruamel.yaml 也未锁版本（来源：.github/workflows/quality-check.yml:25），风格一致；但 pathspec 是新引入依赖，锁定更稳健
   - 风险：不锁版本时未来 pathspec 破坏性更新可能导致 glob 语义漂移，routing.py 单测失败
   - 验证时机：detail-design 阶段在 CI 依赖修改 PR 中确认版本约束策略
