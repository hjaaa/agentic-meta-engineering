---
id: 20260521-standard-8phase-bugs-batch-fix
title: Standard-8phase 流程残留 bug 批量修复
created_at: 2026-05-21T14:31:12+08:00
refs-requirement: true
---

# 20260521-standard-8phase-bugs-batch-fix · Standard-8phase 流程残留 bug 批量修复

## 背景

`.claude/workflows/requirement/standard-8phase.yaml` 是本仓库需求驱动开发的主流程模板，覆盖 bootstrap → definition → tech-research → outline-design → detailed-design → task-planning → development → testing → archive 八个阶段。

在前一个需求 REQ-20260519-context-usage-report 的真实使用过程中，团队系统性记录了 standard-8phase 模板及其配套 CLI / gate / loader 的 14 处缺陷
（来源：requirements/20260519-context-usage-report/notes.md:1）。这些缺陷分散在 yaml 节点声明、bash 脚本依赖、CLI 工具实现、gate 判定逻辑等多个层面，导致：

- 走 standard-8phase 模板的需求每阶段都要手工 workaround 才能推进，自动化收益丧失。
- 关键节点（如 phase-to-* 切换、task-list-summary、pr-submit）因依赖未声明的外部命令或不存在的脚本而 100% 必败。
- gate 与 status CLI 输出存在误判，掩盖真实状态，让用户误信流程已通过。

本需求集中修复这 14 处缺陷，使 standard-8phase 流程不再需要手工 workaround，从 bootstrap 一路跑到 archive 全节点 exit=0。

## 目标

- **主目标**：standard-8phase 全流程 14 处已知 bug 全部根治，新建需求 `/workflow:run standard-8phase ...` 后 `/workflow:continue` 可连续推进到 archive 阶段，全程不依赖任何手工 workaround。
- **次要目标**：
  - 沉淀本次发现的工具层漂移模式（schema vs prompt、CLI 单文件 vs 目录、外部命令 vs Python+PyYAML 等），在 `context/team/engineering-spec/` 留下对应规范说明，避免再次发生。
  - 不破坏现有 requirements 的 `meta.yaml / process.txt / run-state.jsonl` 格式（向后兼容）。

## 角色与场景

### 场景 1：Bug-2 — bootstrap 时 meta.yaml `project:` 字段空导致 bootstrap-validate 必败
- 角色：走 standard-8phase 的需求开发者
（来源：requirements/20260519-context-usage-report/notes.md:324）
- 前置：本仓库 `context/project/agentic-meta-engineering/` 是当前唯一 project
（来源：context/project/agentic-meta-engineering/INDEX.md:1）
- 主流程：执行 `python3 scripts/lib/workflow_command_dispatcher.py run standard-8phase "..." --slug=...` → 自动生成 `meta.yaml` 骨架，`project:` 字段当前为空字符串；紧接 `/workflow:continue` 推进到 `bootstrap-validate` 节点跑 `check_meta.py` 必败（`empty: 流程组字段 project 不能为空`）。
- 期望结果：`workflow_run.py` 在唯一 project 时自动写入 `project: agentic-meta-engineering`；多 project 时让用户在 stdin 选；零 project 时保留空并由 `check_meta.py` 在 bootstrap 阶段放宽校验。bootstrap-validate 节点首次执行 exit=0。

### 场景 2：Bug-4 — 「待确认清单」vs「待澄清清单」工具命名冲突
- 角色：走 standard-8phase 的需求开发者
（来源：requirements/20260519-context-usage-report/notes.md:365）
- 前置：`requirement.md` 起草完毕进入 `req-artifact-check`
- 主流程：`standard-8phase.yaml req-artifact-check` 节点 `must_contain_sections` 要求 `requirement.md` 含「待确认清单」；`check_sourcing.py:52` 的 `RE_CLARIFY_HEADING` 只认「待澄清清单」。两工具同时校验导致章节命名无法二选一。
- 期望结果：统一对齐为「待澄清清单」侧——把 `.claude/workflows/requirement/standard-8phase.yaml` 的 `must_contain_sections` 改为「待澄清清单」（与历史 requirement.md 一致，影响面仅一行 yaml 改动）。`requirement.md` 单一章节名同时通过两工具校验。

### 场景 3：Bug-5 — phase-transition 节点强依赖未声明的 `yq`
- 角色：走 standard-8phase 的需求开发者
（来源：requirements/20260519-context-usage-report/notes.md:399）
- 前置：approval 通过后推进 `phase-to-tech-research` 等节点
- 主流程：`.claude/workflows/requirement/standard-8phase.yaml` 多个 phase-transition 节点的 bash 调用 `yq e '.field = "val"' -i "$META_PATH"`，本仓库 `context/team/tool-chain.md` / setup 未声明 yq 为硬依赖，macOS 默认未安装。`max_retries=3` retry 全部 fail → abort。
- 期望结果：新建 `scripts/lib/meta_set.py`（PyYAML 实现，等价 `yq e` 写入语义），把所有 yaml 中的 `yq e` 调用替换为 `python3 scripts/lib/meta_set.py`，消除外部命令依赖，统一用 Python+PyYAML。phase-transition 节点 bash exit=0。

### 场景 4：Bug-6 — `/workflow:status` 把 failed 节点也算进 "completed" 计数
- 角色：走 standard-8phase 的需求开发者 / 维护 worker
（来源：requirements/20260519-context-usage-report/notes.md:755）
- 前置：某节点写过 `node_failed` 且无后续 `node_completed`
- 主流程：调用 `python3 scripts/lib/workflow_command_dispatcher.py status <run_id>`，`scripts/lib/workflow_status.py:47` `_format_state_plain` 直接列出 `node_outputs.keys()` 无 state 过滤，failed 节点被混入 `completed (N)` 列表。
- 期望结果：`workflow_status.py:_format_state_plain` 改为按 `entry.state` 分桶为 `completed (N) / failed (M) / running (K)` 三段输出，复用 `_compute_terminal_ids` 切分逻辑。补 fixture：jsonl 含 `node_failed` 末位 → status 输出 failed 列表非空。

### 场景 5：Bug-7 — 所有 `phase-to-*` 节点引用不存在的 `scripts/lib/append_process.py`
- 角色：走 standard-8phase 的需求开发者
（来源：requirements/20260519-context-usage-report/notes.md:706）
- 前置：`yq` 已就绪或已被 Bug-5 修复方案替换
- 主流程：`.claude/workflows/requirement/standard-8phase.yaml` 多节点调用 `python3 scripts/lib/append_process.py "..."`；仓库实际只有 `scripts/lib/submit_codex.py` 和 `scripts/lib/archive_runner.py` 内的同名内部函数 `_append_process_event`，无公开 CLI。bash `set -e` 在调用处中断。
- 期望结果：新建 `scripts/lib/append_process.py`，参数 `<event_line>`，写当前需求 `requirements/<id>/process.txt`；`run_id` 通过 cwd 或 env `$RUN_ID` 推断；复用 `submit_codex._append_process_event` 逻辑封装成 CLI。`phase-to-*` 节点 bash exit=0。

### 场景 6：Bug-9 — `features-json-generate` prompt 描述的 schema 与 `check_features.py` / `features-schema.yaml` 实际期望严重不一致
- 角色：走 standard-8phase 的需求开发者
（来源：requirements/20260519-context-usage-report/notes.md:644）
- 前置：阶段 5 详细设计完毕，准备生成 `features.json`
- 主流程：`features-json-generate` 节点的 prompt 块
（来源：.claude/workflows/requirement/standard-8phase.yaml）写示例为 `feat-NNN / acceptance_criteria / estimated_hours / total_features`，而
（来源：context/team/engineering-spec/features-schema.yaml）实际要求 id 正则 `^F-\d{3}$`、字段名 `acceptance` / `estimate_days`、顶层 `schema_version` / `requirement_id`、complexity 枚举 `trivial/light/medium/heavy`。按 prompt 生成的 features.json 100% 撞 `detail-design-artifact-check` 节点的 `check_features.py` schema 校验失败。
- 期望结果：重写 `features-json-generate` prompt：直接引用 `context/team/engineering-spec/features-schema.yaml` 作为唯一事实源（让 AI 读 schema 文件），或把 schema 字段表 + 枚举 + 正则 inline 进 prompt 并加 CI 检查（grep yaml 是否含已废弃字段如 `feat-NNN` / `acceptance_criteria`）。按修复后 prompt 生成的 features.json 通过 `check_features.py`。

### 场景 7：Bug-10 — `task-frontmatter-check` 节点的 CLI 不支持目录扫描
- 角色：走 standard-8phase 的需求开发者
（来源：requirements/20260519-context-usage-report/notes.md:442）
- 前置：`task-decompose` 生成 `tasks/F-001.md ~ F-NNN.md`
- 主流程：yaml schema_check 把 `$ARTIFACTS_DIR/tasks/` 目录传给 `scripts/lib/check_task_frontmatter.py`；该脚本只接受单文件路径，目录路径报 `Is a directory` exit=1。
- 期望结果：`check_task_frontmatter.py` 增加双模——传文件时单文件校验；传目录时 rglob `*.md` 逐个校验并聚合 exit code（任一失败 exit 1）。`task-frontmatter-check` 节点 exit=0。补 fixture 覆盖目录路径用例。

### 场景 8：Bug-11 — `feature-task.md.tmpl` 缺 `schema_version` 字段
- 角色：走 standard-8phase 的需求开发者
（来源：requirements/20260519-context-usage-report/notes.md:613）
- 前置：Bug-10 已修通过 task-frontmatter-check 调用路径
- 主流程：`task-decompose` 用 `.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl` 渲染 `tasks/F-NNN.md`，但模板中无 `schema_version` 字段；
（来源：context/team/engineering-spec/task-frontmatter-schema.yaml）`required_fields` 含 `schema_version`，`check_task_frontmatter.py` 报「缺必填字段 schema_version」。
- 期望结果：`feature-task.md.tmpl` 第 1 行后注入 `schema_version: "1.0"`；补测试 fixture 覆盖模板渲染产物含 `schema_version` 字段。

### 场景 9：Bug-12 — `task-list-summary` 节点使用未注入变量 `$LOG_DIR`
- 角色：走 standard-8phase 的需求开发者
（来源：requirements/20260519-context-usage-report/notes.md:551）
- 前置：task-frontmatter-check 已通过
- 主流程：`.claude/workflows/requirement/standard-8phase.yaml` task-list-summary 节点 bash `ls $ARTIFACTS_DIR/tasks/*.md | wc -l > $LOG_DIR/task-count.txt`；`$LOG_DIR` 全仓无 producer，bash 解释为空字符串展开为 `... > /task-count.txt`，写根文件系统 `Read-only file system` 报错。
- 期望结果：workflow runner（`scripts/lib/workflow_dispatcher.py`）给 bash 节点 env 注入 `$LOG_DIR=requirements/<id>/logs/`，与现有 `$ARTIFACTS_DIR / $META_PATH / $RUN_ID / $BRANCH_NAME` 同源派发；首次注入时若目录不存在则 mkdir。节点 exit=0。

### 场景 10：Bug-13 — `task-list-summary` 节点引用的 `scripts/lib/summarize_tasks.py` 不存在
- 角色：走 standard-8phase 的需求开发者
（来源：requirements/20260519-context-usage-report/notes.md:580）
- 前置：Bug-12 LOG_DIR 已修
- 主流程：yaml 节点调用 `python3 scripts/lib/summarize_tasks.py $ARTIFACTS_DIR/tasks/`，文件不存在 exit=2（与 Bug-7 同性质）。
- 期望结果：新建 `scripts/lib/summarize_tasks.py`，参数 `<tasks_dir>`，输出 `total / by_complexity / by_status` 摘要到 stdout。节点 exit=0。

### 场景 11：Bug-18 — post-dev gate 在 GATE-SOURCING 非 strict 模式下把 R-WARNING-ONLY 升为 exit 1（误报）
- 角色：走 standard-8phase 的需求开发者 + gate 维护者
（来源：requirements/20260519-context-usage-report/notes.md:309）
- 前置：feature 完成后跑 `python3 scripts/gates/run.py --trigger=post-dev --req=<id>`，工作区只剩历史 W002/W003 warning（pre-existing，不在当前 feature diff 内）
- 主流程：stdout 显示 `Total: 0 error, 5 warning` 但 `scripts/gates/audit.py` `calc_exit_code` 按 GATE-SOURCING 注册的 severity=error 判定 exit=1；与 plugin 实际 Decision（warning-only 应 PASS）矛盾。
- 期望结果：`scripts/gates/audit.py` 在非 strict 模式下按 plugin 实际 decision + plugin 自身 severity 判定 exit code；warning-only 的 GATE-SOURCING 不再硬挡 post-dev（exit=0）。strict 模式行为不变。补 fixture：warning-only → exit 0。

### 场景 12：Bug-19 — `_resolve_prompt_file` 用模块级 `WORKFLOWS_PROMPTS_DIR` 常量导致测试 fixture 注入失效
- 角色：维护 workflow loader 的开发者
（来源：requirements/20260519-context-usage-report/notes.md:273）
- 前置：跑 `pytest tests/skills/test_workflow_dispatcher_bash_skill_prompt.py::test_prompt_node_prompt_file_reads_and_renders`
- 主流程：测试用 `tmp_path` 注入 `prompts/test.md` 作为 prompt_file 源；但 `scripts/lib/workflow_loader.py:117` 在 import 时硬编码 `WORKFLOWS_PROMPTS_DIR = REPO_ROOT / ".claude" / "workflows" / "prompts"`，`_resolve_prompt_file(pf_value)` 行 713 用该常量拼接 → 解析到真实仓库根的 `.claude/workflows/prompts/test.md`（不存在），`FileNotFoundError → WorkflowError`。生产路径不受影响。
- 期望结果：`_resolve_prompt_file(pf_value, repo_root: Path | None = None)`，默认值回退 `REPO_ROOT`；`scripts/lib/workflow_dispatcher.py:295` `_dispatch_prompt_node` 把已有 `root` 参数传进去（外科手术式修改，向后兼容）。该单测通过；补 `tmp_path → repo_root → prompts/` 端到端 fixture 锁住回归。

### 场景 13：Bug-20 — `standard-8phase.yaml` 的 `pr-submit` bash 节点引用 3 个未注入的 env 变量
- 角色：走 standard-8phase 的需求开发者
（来源：requirements/20260519-context-usage-report/notes.md:231）
- 前置：testing 阶段 `test-final-confirm` approved 后推进到 `pr-submit`
- 主流程：节点 bash 调用 `gh pr create --title "$PR_TITLE" --body-file "$PR_BODY_FILE" --base "$BASE_BRANCH"`；三个变量全仓无 producer；bash 接收到空字符串展开为 `--title "" --body-file ""`，gh CLI 报「must provide --title and --body」→ `node_failed` → max_retries=3 全 fail → 整 workflow run 卡死。
- 期望结果：把 `pr-submit` 节点 type 改为 `skill: requirement-submit`（语义对齐 ai-collaboration 三层架构「yaml 编排 / skill 工具 / agent 执行」，复用现有 `/requirement:submit` 完整路径含 PR 正文模板渲染 / title 推断 / gates 链 / codex review-loop）；`pr-merged-gate` 节点的 `$pr-submit.output.pr_url` 引用同步改成 `$requirement-submit.output.pr_url`。pr-submit 节点在 testing done 后可正常创建 PR。

### 场景 14：次生 bug — rollback 不识别 `.claude/workflows/<name>.yaml`
- 角色：执行 `/workflow:rollback` 的需求开发者
（来源：requirements/20260519-context-usage-report/notes.md:814）
- 前置：当前 worktree 内无 `workflow.yaml` 软链
- 主流程：`scripts/lib/workflow_rollback_topology.py` 的 `_find_workflow_yaml` 只查 `run_dir/workflow.yaml` 及 1-3 层父目录；本仓库标准布局下 workflow yaml 在 `.claude/workflows/requirement/standard-8phase.yaml`，rollback 找不到。
- 期望结果：`_find_workflow_yaml` 增加 fallback——读 jsonl `workflow_started` 事件取 `workflow_name`，然后查 `.claude/workflows/**/<workflow_name>.yaml`。补单测覆盖该 fallback 路径。

## 非功能需求

- 性能：不引入显著性能开销；本仓库 requirements/*.md 规模为 MB 级，相关 CLI 应在秒级完成
（来源：requirements/20260519-context-usage-report/artifacts/detailed-design.md:812）
- 兼容性：修复不得破坏现有 requirements 的 `meta.yaml / process.txt / run-state.jsonl / features.json / tasks/*.md` 文件格式；`check_sourcing.py` 已有历史 requirement 已使用「待澄清清单」章节命名
（来源：requirements/20260519-context-usage-report/artifacts/requirement.md）
- 安全/合规：无新增安全面；`meta_set.py` 仅允许通过 `--path` 显式指定的 yaml 路径写入，禁止任意路径遍历。具体白名单见「待澄清清单」第 7 项

## 范围

- 包含：
  - Bug-2 / 4 / 5 / 6 / 7 / 9 / 10 / 11 / 12 / 13 / 18 / 19 / 20 + 次生 bug（rollback）共 14 处
  - 新建：`scripts/lib/append_process.py` / `scripts/lib/summarize_tasks.py` / `scripts/lib/meta_set.py`
  - 修改：`.claude/workflows/requirement/standard-8phase.yaml` / `scripts/lib/workflow_status.py` / `scripts/lib/workflow_dispatcher.py` / `scripts/lib/workflow_loader.py` / `scripts/lib/workflow_rollback_topology.py` / `scripts/lib/check_task_frontmatter.py` / `scripts/gates/audit.py` / `.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl` / `scripts/lib/workflow_run.py`
  - 端到端冒烟：sandbox `REQ-2099-NNN` 走完整 standard-8phase 跑通验证
- 不包含：
  - F-006 ~ F-011 follow-up 系列（已在 REQ-20260519-context-usage-report 闭环
（来源：requirements/20260519-context-usage-report/notes.md:9））
  - REQ-20260519-context-usage-report 已修复的 Bug-1/3/8/14/15/16/17
（来源：requirements/20260519-context-usage-report/notes.md:881）
  - 不重构 workflow framework 本身（仅做外科手术修复）
  - 不引入新的 workflow 模板（仅修复现有 standard-8phase）
  - 不重新设计 features.json schema（仅消除 prompt 与既定 schema 的漂移）

## 验收标准

每条对应「角色与场景」中的一个 Bug，是 standard-8phase 完整跑通的硬验证点：

- **AC-1**：新建 standard-8phase 需求后 `bootstrap-validate` 节点首次执行 `exit=0`，不需要手工编辑 meta.yaml `project` 字段（Bug-2）
- **AC-2**：`requirement.md` 只用一个章节名「待澄清清单」可同时通过 `req-artifact-check` 和 `check_sourcing.py`（Bug-4）
- **AC-3**：任意 `phase-to-*` 节点在 yq 未安装环境执行 `exit=0`（Bug-5）
- **AC-4**：`/workflow:status` 输出中 failed 节点出现在独立 failed 列表，不混入 completed（Bug-6）
- **AC-5**：走 standard-8phase 到 `phase-to-*` 节点，bash `exit=0`（Bug-7）
- **AC-6**：按修复后 `features-json-generate` prompt 生成的 features.json 通过 `check_features.py`（Bug-9）
- **AC-7**：`task-frontmatter-check` 节点传目录路径时 `exit=0`，批量校验 `tasks/*.md`（Bug-10）
- **AC-8**：`feature-task.md.tmpl` 渲染的 task.md 含 `schema_version`，`check_task_frontmatter.py` `exit=0`（Bug-11）
- **AC-9**：`task-list-summary` 节点 bash `exit=0`，`task-count.txt` 写入合法路径（Bug-12）
- **AC-10**：`summarize_tasks.py` 存在且接受 tasks/ 目录参数（Bug-13）
- **AC-11**：post-dev gate 非 strict 模式下含历史 warning 不触发 `exit=1`（Total: 0 error, N warning → exit=0）（Bug-18）
- **AC-12**：`pytest tests/skills/test_workflow_dispatcher_bash_skill_prompt.py::test_prompt_node_prompt_file_reads_and_renders` 通过（Bug-19）
- **AC-13**：`pr-submit` 节点在 testing done 后可正常创建 PR，`gh pr create` 收到非空 `--title` 和 `--body`（Bug-20）
- **AC-14**：rollback 在仅有 `.claude/workflows/requirement/standard-8phase.yaml` 时可正常定位 workflow yaml（次生 bug）
- **AC-15**（端到端）：起 sandbox `REQ-2099-NNN` 走完整 standard-8phase，从 bootstrap 一路到 pr-submit 全节点 `exit=0`，不需要任何手工 workaround

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| Bug-4 章节命名统一方向 | A. 改 yaml 对齐「待澄清清单」 / B. 改 check_sourcing.py 正则支持双名 | A | 影响面最小（单 yaml 一行）；历史 requirements 已用「待澄清清单」零迁移 |
| Bug-5 yq 解决方向 | A. 在 tool-chain.md 声明 yq 硬依赖 / B. 新建 meta_set.py 替换所有 yq 调用 | B | 消除外部命令依赖，对齐复利工程「工具封装知识」原则；新人 onboarding 不再撞 yq not found 墙 |
| Bug-7 append_process | A. 新建 CLI / B. 把 yaml 改 echo 追加方案 | A | 与 `requirement-progress-logger` Skill 语义同源、可扩展事件类型校验，复用 `submit_codex._append_process_event` 既有逻辑 |
| Bug-12 LOG_DIR 落点 | A. 注入 `requirements/<id>/logs/` / B. 用 `$ARTIFACTS_DIR/.log/` / C. `runs/<id>/` | A | 与 meta.yaml `log_layout: split` 字段语义一致，首次注入时若目录不存在则 mkdir |
| Bug-13 summarize_tasks | A. 新建 CLI / B. 删 yaml 该行仅用 ls 统计 | A | 与 Bug-7 同模式；total / by_complexity / by_status 三维统计无法用 shell oneline 等价表达 |
| Bug-18 gate 修复范围 | A. 改 runner 按 plugin 实际 decision 判定 / B. 把 GATE-SOURCING 从 post-dev 触发器移除 | A | 不动 plugin 自身行为，最小侵入；strict 模式行为不变 |
| Bug-20 pr-submit 方案 | A. yaml 节点改 skill: requirement-submit / B. workflow_dispatcher 补 env producer | A | 复用现有 `/requirement:submit` 完整路径（含 PR 正文模板渲染 + title 推断 + gates 链 + codex review-loop），符合「yaml 编排 / skill 工具」职责分离 |
| 次生 bug 处置 | A. 纳入本次修复 / B. 单独立项 | A | 与 Bug-19 同源（都是路径/常量未参数化），合并修复减少 PR 数量 |
| 整体修复路径 | A. 一个大需求 14 个 feature / B. 拆 3 个小需求 / C. hotfix 模式直修 | A | 用户在主对话明确选择 A |

## 待确认清单

> 同 ## 待澄清清单（standard-8phase yaml 用「待确认清单」、check_sourcing.py 用「待澄清清单」，两章节同义。本 PR 修复 Bug-4 后将统一为「待澄清清单」单一名称，本文档为临时双章节并存以兼容两工具）

## 待澄清清单

1. **Bug-5 `meta_set.py` 接口形态**：参数语义 `--path meta.yaml --set .phase=tech-research --append .gates_passed=GATE-X` 是否需要支持 `--get` 读取？是否需要支持数组下标语法？[待用户确认] — 设计阶段细化]
2. **Bug-9 修复策略**：选「prompt 读取 features-schema.yaml 文件」还是「prompt 内联 schema 字段表 + CI grep 拦废弃字段」？后者维护成本更高但 yaml 自包含。[待用户确认] — 详细设计阶段决策]
3. **Bug-12 `requirements/<id>/logs/` 目录预创建时机**：避免运行时首次 mkdir 的竞态。[待补充] — 内容：bootstrap 时预创建 logs/ 目录；依据：现有 `artifacts/` `reviews/` 目录已在 bootstrap 预创建；风险：增加 bootstrap 复杂度；验证时机：详细设计 + 端到端冒烟]
4. **Bug-18 strict 与非 strict 模式语义边界**：`audit.py` 当前 strict / 非 strict 切换是 CLI 参数还是 env？[待补充] — 内容：核实 audit.py strict 模式入口；依据：`check_sourcing.py --strict` 既有，audit 是否同名待查；风险：实际可能是 registry 配置；验证时机：技术预研]
5. **端到端冒烟 sandbox REQ id 格式**：用 `REQ-2099-NNN` 纯数字格式（沿用本仓约定）。[待用户确认] — 是否沿用既有约定]
6. **safety_net**：本次 14 处 bug 修复期间 standard-8phase 是否会出现临时不可用窗口。建议 PR 合并前用 sandbox REQ 全程冒烟一遍。[待用户确认] — 是否需要在 PR 合并前禁止任何 standard-8phase run 启动？]
7. **meta_set.py 路径白名单**：限定只允许通过 `--path` 显式指定 `requirements/<id>/` 或 `runs/<id>/` 内 yaml，禁止改 `.claude/` 内 yaml。[待补充] — 内容详见非功能需求段

---

> 提示：定义阶段离开前请补齐 meta.yaml 语义字段：
> - `feature_area`: tooling-internal（建议；需查 `context/project/agentic-meta-engineering/areas.yaml` 白名单）
> - `change_type`: bugfix
> - `affected_modules`: workflow-yaml / workflow-dispatcher / workflow-loader / gates / templates / cli-scripts
> - `tags`: workflow-engine / standard-8phase / batch-fix
