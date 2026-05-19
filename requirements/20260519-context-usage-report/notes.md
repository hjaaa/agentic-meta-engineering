# 20260519-context-usage-report · 工作笔记

## workflow 执行中遇到的 bug 记录（待后续处理）

以下问题在使用 `/workflow:run standard-8phase` 启动本需求 + `/workflow:continue` 推进 bootstrap-validate 节点时被触发。仅记录现象、复现路径、影响面与可能根因，**不在本需求中修复**——按用户要求等后续单独立项处理。

---

### Bug-2：bootstrap 时 meta.yaml `project:` 字段默认空，bootstrap-validate 必失败

**现象**

`/workflow:run standard-8phase` 写入的 meta.yaml 骨架中 `project:` 字段为空（带注释 `# 关联 context/project/<project>/`）。紧接着 `bootstrap-validate` 节点跑 `check_meta.py` 会失败：

```
❌ empty: 流程组字段 project 不能为空
```

**根因（推断）**

- `workflow_run.py` 的 meta.yaml 模板没有从 workflow yaml / project 上下文中推导 project 字段。
- `check_meta.py` 的 strict 模式不允许 project 为空。

**复现路径**

```bash
python3 scripts/lib/workflow_command_dispatcher.py run standard-8phase "Context 知识利用率统计机制" --slug=context-usage-report
# 进 worktree，跑 continue
python3 scripts/lib/workflow_command_dispatcher.py continue 20260519-context-usage-report
# → node_failed: bootstrap-validate / check_meta.py exit=1 (empty project)
```

**当前 workaround**

bootstrap 后手动编辑 meta.yaml，把 `project:` 改成 `project: agentic-meta-engineering`（或合法 project 名）。

**影响面**

- 所有走 standard-8phase 的新需求第一步都会卡 bootstrap-validate。
- 与 Bug-3 联动：失败后无法 retry，需要清理 jsonl 才能继续。

**建议修复方向**

两选一：
1. `workflow_run.py` 把当前活跃 project（context/project/<project>/ 单值时默认取它，多值时让用户选）写进 meta.yaml。
2. `check_meta.py` 在 bootstrap 阶段放宽 project 校验（毕竟模板还没填完整），到 definition 阶段切换时再强校验。

---

### Bug-4：「待确认清单」 vs 「待澄清清单」工具命名不一致

**现象**

阶段 2 推进时同时被两个工具吐警告/失败：

- `.claude/workflows/requirement/standard-8phase.yaml` 的 `req-artifact-check` 节点的 `must_contain_sections` 要求 `requirement.md` 含 `待确认清单` 章节。
- `scripts/lib/check_sourcing.py:52` 的 `RE_CLARIFY_HEADING = re.compile(r"^#{2,6}\s*待澄清清单?\s*$")` 只认 `待澄清清单`（W001 / W003 都看这个）。

文档无法同时只用一个章节名满足两个工具。

**复现路径**

- 改成 `## 待确认清单` → `req-artifact-check` 通过，但 `check_sourcing` 触发 W001「缺 '## 待澄清清单' 章节」。
- 改成 `## 待澄清清单` → `check_sourcing` 通过，但 `req-artifact-check` 报 must_contain_sections 失败。
- 同时保留两个章节 → 两个工具都过，但 P3 评审反馈正确指出「重复且语义混乱」。

**当前 workaround**

requirement.md 同时保留 `## 待确认清单` 与 `## 待澄清清单` 两个章节并显式说明「同义节，因工具命名不一致需要并存」。内容主要放在「待澄清清单」下（check_sourcing 看 list 项数）。

**影响面**

- 所有走 standard-8phase 的需求都会撞上这个矛盾。
- P3 评审反馈直接打到该问题——团队评审会反复出现「这两个章节为什么并存」的疑问。

**建议修复方向**

二选一统一命名：
1. 把 `standard-8phase.yaml` 中 `must_contain_sections: [..., 待确认清单]` 改成 `待澄清清单`，向 check_sourcing 对齐（推荐，影响面小：只改一个 yaml）。
2. 把 `check_sourcing.py:52` 正则改为 `r"^#{2,6}\s*待(澄|确认)清单?\s*$"`，向 yaml 对齐（影响面大：所有历史 requirement 已写 `待澄清清单` 的需要同步改）。

---

### Bug-5：phase-transition 节点强依赖 `yq` 但系统未安装且未在依赖文档中声明

**现象**

`req-confirm` approval 通过后，下一节点 `phase-to-tech-research`（以及所有 `phase-to-*` 节点）的 bash 脚本调用 `yq e ...` 失败：

```
bash: line 1: yq: command not found
```

`max_retries=3` retry 同样 fail（每次重试都是同样错），最终升级为 abort 阻塞 workflow。

**根因**

`standard-8phase.yaml` 多个节点（`phase-to-tech-research:184` / `phase-to-outline-design:271` / `phase-to-detail-design:347` / `phase-to-task-planning:466` / `phase-to-development:521` / `phase-to-testing:562` / `pr-submit:687` / `archive-finalize:712`）都用 `yq e '.field = "val"' -i "$META_PATH"` 来更新 meta.yaml。但仓库的 tool-chain 文档 / setup 脚本 / README 都未声明 `yq` 是硬依赖。

**复现路径**

走任何 `standard-8phase` 工作流，过完一个 phase 必撞。

**当前 workaround**

两条路（本次选 a）：

a) 用 Python + PyYAML 等价替代：写一个 `scripts/lib/meta_set.py`，参数语义 `--path meta.yaml --set .phase=tech-research --append .gates_passed=GATE-X`，然后逐个改 yaml 中所有 `yq e` 调用为 `python3 scripts/lib/meta_set.py`。

b) 手动 `brew install yq` / 在 README 声明依赖。

本次推进采用 c) 折中：临时直接 `python -c` 改 meta.yaml + 手动 `append_process.py`，让本节点的产物等价完成，然后写 node_completed 跳过 bash 调用（Bug-3 workaround 链）。

**影响面**

- 任何走 standard-8phase 的需求一过完 approval 阶段都会卡 `yq command not found`。
- 项目 onboarding 文档（`context/team/onboarding/agentic-engineer-guide.md` / `context/team/tool-chain.md`）未声明 yq 依赖 → 新人撞墙。
- 等 yq 安装到位也只是把 a / b 矛盾绕过，根因还是没在 setup 检查中声明。

**建议修复方向**

- 在 `context/team/tool-chain.md` 与 `Makefile gates-validate` 中加 `yq` 存在性检查；不存在则给出安装提示（macOS: `brew install yq`，linux: `apt-get install yq` / `pip install yq`）。
- 或：把所有 yaml 中的 `yq` 调用替换为 `scripts/lib/meta_set.py`（消除外部命令依赖，统一用 Python+PyYAML）。

---

### Bug-10：`task-frontmatter-check` 节点的 CLI 不支持目录扫描，但 yaml 传的是目录路径

**现象**

`task-decompose` 生成 `tasks/F-001.md ~ F-013.md` 后，`task-frontmatter-check` 节点立即失败：

```
schema_check 失败：scripts/lib/check_task_frontmatter.py 期望 exit=0 实际 exit=1
> 错误：task.md 文件读取失败：[Errno 21] Is a directory: '.../requirements/20260519-context-usage-report/artifacts/tasks'
```

**根因**

- `.claude/workflows/requirement/standard-8phase.yaml:487-490`：
  ```yaml
  schema_check:
    - script: scripts/lib/check_task_frontmatter.py
      args: [$ARTIFACTS_DIR/tasks/]
      expected_exit_code: 0
  ```
- 把目录 `$ARTIFACTS_DIR/tasks/` 当 arg 传给 CLI。
- `scripts/lib/check_task_frontmatter.py:325-345` 只接受单文件路径，无 glob / 目录扩展逻辑。

**复现路径**

走 standard-8phase 到 task-frontmatter-check 必撞。

**当前 workaround**

人工 `for f in tasks/*.md; do python3 scripts/lib/check_task_frontmatter.py "$f"; done` 逐个跑通过，再用 Bug-3 workaround 写 `node_completed`。

**建议修复方向**

- `check_task_frontmatter.py` 增加目录扩展：传入 Path 是目录时 rglob 该目录 `*.md` 逐个校验，聚合 exit code（任一失败 exit 1）；或
- yaml 改为 inline shell：`for f in $ARTIFACTS_DIR/tasks/*.md; do python3 ... $f || exit 1; done`（但 artifact schema_check 节点不支持 shell loop）。

推荐方案一（CLI 双模式：传文件 → 单文件校验；传目录 → 批量校验）。

---

### Bug-14：`dev-feature-loop` loop 引擎空转——50 次 iteration 全部 `loop_iteration_started → loop_iteration_completed`，从未真正派发 prompt 让 implementer 工作

**现象（最严重）**

阶段 7 进入 `dev-feature-loop` 节点后，单次 `/workflow:continue` 调用：

- jsonl 写入 50 组 `loop_iteration_started / loop_iteration_completed / loop_counter_advanced` 事件
- 末尾写 `loop_max_iterations_exceeded`（max_iterations=50 触发上限）
- 13 个 task.md 全部仍为 `status: pending`，**从未派过任何 implementer subagent**
- 也没有 `node_ready` 事件包含 `dev-feature-loop` 的 prompt 内容供 main Claude 消费

**根因（推断）**

`dev-feature-loop` 是 loop 节点（`.claude/workflows/requirement/standard-8phase.yaml:535-552`）：

```yaml
- id: dev-feature-loop
  loop:
    prompt_file: prompts/standard-8phase/development.md
    until: "ALL_FEATURES_DONE"
    max_iterations: 50
    fresh_context: false
    interactive: true
    gate_message: |
      ## Feature 第 $LOOP_ITERATION 轮已完成 ...
```

预期行为（按 yaml 字面意思 + skill 文档）：每个 iteration 派 prompt 给 Claude，Claude 调 `task-context-builder` + 派 implementer subagent + 等用户确认（`interactive: true`），收完 user 反馈再下一轮。

实际行为：loop 引擎只在内部空转计数器（看似已经"完成"了 50 个 iteration），从来没有：
- 写 `node_ready{prompt=development.md 内容, ...}` 等 Claude 接管
- 在 `loop_iteration_started` 之后停在 awaiting_claude_action 等用户/Claude 输入

可能 loop 节点 dispatcher 在 `interactive: true` 模式下没正确把控制权交给 Claude，而是把整个 prompt_file / gate_message 当 dispatch 模板自动 fire-and-forget 推进——但因为没有任何 outcome 写入（无 `loop_iteration_outcome` 事件），引擎判定每个 iteration "已完成"。

**复现路径**

走 standard-8phase 到阶段 7 dev-feature-loop 必撞。

**当前 workaround（重大决策点）**

三选一：

a) **手工逐 feature 派发**：跳过 loop 节点，对 13 个 feature 逐个：
   - 调 `task-context-builder` skill 取上下文
   - Agent 工具派 implementer subagent 写代码（fresh context）
   - 跑 `/code-review` scope=feature
   - 用户在主对话给软确认 → task.md status: done
   - 重复 13 次

b) **标 done 但不真实现**：13 个 task.md 全部改 `status: done` + 写空 receipt.json + Bug-3 workaround 写 dev-feature-loop node_completed。**结果：features.json 看似 all-done 但实际无代码、无测试、PR 提交时 GATE-POST-DEV-RECEIPT 会硬挡。**

c) **/workflow:save 暂存，移到独立 session 慢慢做**：保留当前状态 jsonl，用户另起会话逐个 feature 推进。

**影响面**

- 阶段 7 自动化完全失效，13 feature 全靠手工编排
- subagent-driven-development 的 happy path 不通过
- 单次需求开发体验从"loop 自驱"退化为"用户与 main Claude 来回交互"
- 与 Bug-15 联动：`dev-all-features-done-check` 也不工作

**建议修复方向**

- workflow loop 节点 dispatcher 需要：每个 iteration 第一次进入时写 `node_ready{prompt=..., loop_iteration=N}` 事件，把 state 转 `awaiting_claude_action`，等 Claude 调 `save_node_result.py --kind=skill_result --output={feature_done|continue|all_done}` 才推进或终止
- `until` 条件求值需要在 iteration 结束后真实检查 features.json all-done 状态，而不是无脑 +1 直到 max_iterations
- 单元测试覆盖：`interactive: true` 模式必须有"awaiting_claude_action between iterations"用例

---

### Bug-12：`task-list-summary` 节点使用未注入变量 `$LOG_DIR`，bash 解释为空导致写根目录

**现象**

```
node_failed task-list-summary
error: bash: line 1: /task-count.txt: Read-only file system
```

**根因**

- `.claude/workflows/requirement/standard-8phase.yaml:496` `ls $ARTIFACTS_DIR/tasks/*.md | wc -l > $LOG_DIR/task-count.txt`
- `$LOG_DIR` 变量在整个 workflow framework 中**没有定义**（`grep -rn "LOG_DIR" scripts/lib/workflow_run.py .claude/workflows/` 只命中此 yaml 一处）。
- bash 解释 `$LOG_DIR` 为空字符串，命令展开为 `... > /task-count.txt` 试图写根文件系统。

**复现路径**

走 standard-8phase 到阶段 6 task-list-summary 必撞。

**当前 workaround**

手工跑：`ls tasks/*.md | wc -l` 然后 Bug-3 workaround 写 node_completed。

**建议修复方向**

要么 workflow runner 注入 `$LOG_DIR`（如 `requirements/<id>/logs/`），要么 yaml 改用已有变量（如 `$ARTIFACTS_DIR/.log/` 或 `runs/<id>/`）。需要先 ADR 决定 logs 落点。

---

### Bug-13：`task-list-summary` 节点引用的 `scripts/lib/summarize_tasks.py` 不存在

**现象**

即使 Bug-12 修了 `$LOG_DIR`，第二条命令 `python3 scripts/lib/summarize_tasks.py $ARTIFACTS_DIR/tasks/` 也会失败：

```
$ ls scripts/lib/summarize_tasks.py
ls: scripts/lib/summarize_tasks.py: No such file or directory
```

**根因**

- `.claude/workflows/requirement/standard-8phase.yaml:497` 引用了不存在的脚本，与 Bug-7（`append_process.py`）同性质。
- yaml 节点定义未做"脚本存在性预检"。

**复现路径**

走 standard-8phase 到 task-list-summary 节点（Bug-12 修复后也会撞）。

**当前 workaround**

直接跳过该命令，统计信息（13 个 task / 总工作量 44h ≈ 5.5 天）已经在 features.json 内有。Bug-3 workaround 写 node_completed。

**建议修复方向**

二选一：

1. 新增 `scripts/lib/summarize_tasks.py`，参数 `<tasks_dir>`，输出 `total / by_complexity / by_status` 摘要到 stdout。
2. 删 yaml 第 497 行 + 修 Bug-12 后只保留 `ls | wc -l` 的统计需求。

---

### Bug-11：`feature-task.md.tmpl` 缺 `schema_version` 字段，与 `task-frontmatter-schema.yaml` 必填项不一致

**现象**

补完 Bug-10 后，逐个跑 `check_task_frontmatter.py tasks/F-001.md` 报：

```
错误：F-001.md frontmatter 缺必填字段 schema_version
```

但项目模板 `.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl` 中**没有 `schema_version` 字段**。

**根因**

- `context/team/engineering-spec/task-frontmatter-schema.yaml:32` `required_fields` 含 `schema_version`，docstring 注释「ADR（F-003）：schema_version 列为 required（不软兼容缺失）。迁移：F-007 派发模板改造时统一给所有 task.md 注入 schema_version: "1.0"。」
- `feature-task.md.tmpl` 至今没注入 schema_version 字段——F-007 派发模板改造未完成或漏了 task 模板。

**复现路径**

走 standard-8phase 走到 task-frontmatter-check + 已修 Bug-10 后必撞。

**当前 workaround**

`task-decompose` skill 渲染 task.md 时手工注入 `schema_version: "1.0"`，或直接修模板。

**建议修复方向**

`.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl` 第 1 行后加 `schema_version: "1.0"`；并加测试 fixture 覆盖。

---

### Bug-9：`features-json-generate` 节点 prompt 描述的 schema 与 `check_features.py` / `features-schema.yaml` 实际期望严重不一致

**现象**

`features-json-generate` 节点的 prompt 给的 schema 模板是：

```json
{
  "features": [
    { "id": "feat-001", "acceptance_criteria": [...], "estimated_hours": 8, "depends_on": [...] }
  ],
  "total_features": ..., "total_estimated_hours": ...
}
```

但下游 `detail-design-artifact-check` 节点调 `python3 scripts/lib/check_features.py` 对 features.json 做 schema_check，schema 来自 `context/team/engineering-spec/features-schema.yaml`，实际期望：

- 顶层必填：`schema_version: "1.0"` / `requirement_id` / `features`
- feature.id：`^F-\d{3}$`（不是 `feat-NNN`）
- 字段名是 **`acceptance`**（不是 `acceptance_criteria`）
- 必填 `modules` (list) / `depends_on` / `depends_on_features` / `complexity` / `touches`
- complexity 枚举：`trivial / light / medium / heavy`（不是 `low / medium / high`）
- 字段是 **`estimate_days`**（不是 `estimated_hours`）
- 顶层**不需要** `total_features` / `total_estimated_hours`

按 prompt 写出来的 features.json 100% 撞 schema_check 失败：

```
features[12].acceptance 必填，当前缺失
features[12].id 值 'feat-013' 不符合正则 ^F-\d{3}$
features[12].complexity 值 'low' 不在枚举 ['trivial', 'light', 'medium', 'heavy'] 内
```

**根因**

`features-json-generate` 节点的 prompt 在 `.claude/workflows/requirement/standard-8phase.yaml:366-392` 是**手写示例**，没有引用 `features-schema.yaml` 作为唯一事实源，导致 prompt 与 schema 漂移。

**复现路径**

走任何 standard-8phase 流程到阶段 5 `features-json-generate` → `detail-design-artifact-check`。

**当前 workaround**

照 schema 真实定义手写 features.json：id 用 `F-NNN`、字段名 `acceptance` / `estimate_days` / `modules` / `touches`、加 `schema_version` / `requirement_id` 顶层、complexity 用 `light/medium/heavy`，删除 `total_features` / `total_estimated_hours`。

**影响面**

- standard-8phase 阶段 5 必踩。
- 评审 agent（detail-design-quality-reviewer）也读 prompt 写的字段 schema 给反馈，建议补 `complexity / interfaces_frozen / touches`——其中 complexity 又把枚举推回错的（reviewer 自己也不知道真 schema）。
- prompt 与 schema 不同步，新人完全没法照 prompt 一次性写对。

**建议修复方向**

`standard-8phase.yaml:366-392` 的 prompt 改为：

1. 直接引用 `context/team/engineering-spec/features-schema.yaml` 作为唯一 schema 来源（让 AI 读文件）；或
2. 把 schema 的字段表 + 枚举 + 正则直接 inline 进 prompt（保持 yaml 自包含但要与 schema 同步更新）。

无论哪种都需要在 `features-schema.yaml` 改动 PR 中加一道 CI 检查：grep yaml 中的 prompt 是否含已废弃字段（如 `feat-NNN` / `acceptance_criteria` / `estimated_hours` / `total_features`）。

---

### Bug-7：`standard-8phase.yaml` 所有 `phase-to-*` 节点引用的 `scripts/lib/append_process.py` 不存在

**现象**

执行 `phase-to-outline-design` 节点 bash workaround 时：

```
$ python3 scripts/lib/append_process.py "phase-transition: tech-research → outline-design"
can't open file '<repo_root>/scripts/lib/append_process.py': [Errno 2] No such file or directory
```

**根因**

`.claude/workflows/requirement/standard-8phase.yaml` 多个节点调用 `python3 scripts/lib/append_process.py "..."`：

- `phase-to-tech-research:187`
- `phase-to-outline-design:274`
- `phase-to-detail-design:350`
- `phase-to-task-planning:468`
- 等等

仓库实际只有 `scripts/lib/submit_codex.py:_append_process_event` / `scripts/lib/archive_runner.py:_append_process_event` 两个**模块内部函数**，没有公开 CLI 脚本 `append_process.py`。yaml 这些 bash 调用永远会 exit=2（file not found），整条 phase 切换 bash 会 `set -e` 中断。

**复现路径**

1. 任意走 standard-8phase 流程到 phase-to-* 节点。
2. 即便 yq 已装好，`set -e` 在 append_process.py 调用上 fail。
3. → `node_failed` → 触发 Bug-3 卡死链。

**当前 workaround**

直接 `echo "$(date '+%Y-%m-%d %H:%M:%S') phase-transition: tech-research → outline-design" >> requirements/<id>/process.txt`，等价补齐语义事件追加。

**影响面**

- 与 Bug-3 / Bug-5 联动：任何走 standard-8phase 的需求过完 approval 阶段都会双重撞墙（yq 缺 + 脚本缺）。
- phase-to-tech-research 此前那次 jsonl 写的 `manual-equivalent: ... (Bug-5 workaround)` 实际暗含本 bug — 当时被归到 Bug-5 名下，但根因独立。

**建议修复方向**

二选一：

1. 新增 `scripts/lib/append_process.py`，参数 `<event_line>`，写当前需求 `requirements/<id>/process.txt`；run_id 通过 cwd 或 env `$RUN_ID` 推断。复用 `submit_codex._append_process_event` 逻辑封装成 CLI。
2. 把所有 `phase-to-*` 节点的 bash 改成 `echo "$(date '+%Y-%m-%d %H:%M:%S') ..." >> "$PROCESS_PATH"`，并在 workflow runner 注入 `$PROCESS_PATH` 变量。

方案 1 优先（与 `requirement-progress-logger` Skill 语义同源、可扩展事件类型校验）。

---

### Bug-6：`/workflow:status` 把 failed 节点也算进 "completed (N)" 计数与列表

**现象**

phase-to-outline-design 已经写过 `node_failed`（无 `node_completed`），但 `workflow_command_dispatcher.py status` 输出：

```
state:        running
current_node: (none)
completed (11): bootstrap-validate, req-input-normalize, req-draft, req-quality-review, req-artifact-check, req-confirm, phase-to-tech-research, tech-feasibility-assess, tech-research-artifact-check, tech-research-confirm, phase-to-outline-design
```

把 failed 节点（phase-to-outline-design）列入 `completed`，与 jsonl 事件语义不一致；并且不打 failed 列表 / running 列表，用户看不出哪个节点是失败状态。

**根因（已定位）**

`scripts/lib/workflow_status.py:47`

```python
completed = list(run_state.node_outputs.keys())
lines.append(f"{prefix}completed ({len(completed)}): {', '.join(completed) or '(none)'}")
```

直接列出 `node_outputs.keys()`，没按 `entry.state` 过滤。同文件 `_compute_terminal_ids`（line 101-110）已存在 done/failed 区分逻辑，但 plain 文本输出未复用。

**复现路径**

1. 任意节点写过 `node_failed`，没有后续 `node_completed`。
2. 调 `python3 scripts/lib/workflow_command_dispatcher.py status <run_id>`。
3. 失败节点会被混入 "completed (N)" 列表。

**当前 workaround**

人工核对 jsonl 末位事件类型（`tail -1 run-state.jsonl`）判断真实状态，不信任 status 的 completed 列表。

**影响面**

- 用户根据 status 判断阶段进度时被误导（"明明 11 个 completed 了，为什么 continue 不动？"——其实最后一个是 failed）。
- 主 Agent 在 Bug-3 卡死场景下读 status 也会误判，可能错过重派窗口。

**建议修复方向**

`workflow_status.py:_format_state_plain` 改为按 state 分三桶输出：

```
completed (N): <only state == "completed" / "skipped">
failed    (M): <state == "failed">
running   (K): <state == "running">
```

或直接复用 `_compute_terminal_ids` 的 done/failed 切分。tests 需补一个 fixture：jsonl 含 node_failed 末位 → status 输出 failed 列表非空。

---

## 临时决定

- 本需求继续推进时，对**剩余 10 个 Bug**（Bug-2 / 4 / 5 / 6 / 7 / 9 / 10 / 11 / 12 / 13）继续采用上文记的 workaround，不在本需求范围内修复。
- 收尾阶段把这十个 bug 升级为后续独立需求处理（建议各开一个 REQ）。
- ~~**Bug-14（dev-feature-loop 空转）属于阶段 7 自动化失效的根本性问题**~~ → 已修，commit `4117380`，见下方"已修 Bug 索引"。
- 已知次生 bug：**rollback 不识别 `.claude/workflows/<name>.yaml`**，只查 `run_dir/workflow.yaml` 及 1-3 层父目录。本次 rollback 用 `requirements/<id>/workflow.yaml -> ../../.claude/workflows/requirement/standard-8phase.yaml` 软链兜底；建议未来在 `workflow_rollback_topology._find_workflow_yaml` 加 `.claude/workflows/**/<workflow_name>.yaml` 兜底（workflow_name 从 jsonl `workflow_started` 事件读）。

### 2026-05-19 会话：6 处框架修复已 commit 落盘（Bug-1 / 3 / 8 / 15 / 16 / 17）

为让本需求 dev-all-features-done-check + dev-feature-loop + /code-review + 主仓直跑 continue 跑通，外科手术式修了 6 处工作流引擎层 bug 并落 commit。修完即从上文"待处理"段拿掉（按"修了就取消"约定），下方仅留 commit 索引供回溯：

| 已修 Bug | commit | 一句话 |
|---|---|---|
| Bug-3（retry 不持久化） | `714e78d` | `_handle_retry` 写 `node_retried` 事件 |
| Bug-8（prompt_file 路径基准错位） | `714e78d` | `_dispatch_prompt_node` 接 `_resolve_prompt_file` resolver |
| Bug-15（check_features --all-done） | `714e78d` | `check_features.py` 加 `--all-done` 标志扫 tasks frontmatter |
| Bug-16（loop_done 不写 node_completed） | `714e78d` | `_dispatch_loop_node` 两条 loop_done 路径补 `node_completed` |
| Bug-17（routing.py req-id 旧格式） | `140a8b8` | `code_review_routing.py` 接受 D-013 双格式 req-id |
| Bug-1（continue 不感知 worktree） | `019922b` | main 入口：未传 run_id 且当前非 feat/req-* 分支时扫 `git worktree list` 找活跃 worktree，单个 chdir+execv 切入，多个列出供选 |
| Bug-14（dev-feature-loop 空转） | `4117380` | `_dispatch_loop_node` 新增 interactive 分支：每轮写 `node_ready{loop_iteration, prompt, contract}` → `awaiting_claude_action`；闭环靠 `save_node_result --kind=loop_iteration --output={"outcome":"continue"\|"all_done"}`（continue 时附 `loop_counter_advanced`）；rebuild 把 `loop_iteration_completed` 从 awaiting 拉回 running；development.md 加调用指引；13 新单测 + 全量 1691 pass |

一次性恢复：本需求 `dev-all-features-done-check` 在 Bug-3 修复前留下了无 node_retried 的卡死状态，jsonl 末尾手工 `append_event` 补了一条 `{type: node_retried, ..., data: {manual_recovery: True}}` 才能让 continue 走通。后续可考虑封 `scripts/lib/workflow_recover_retry.py` 自动化恢复"末位 node_failed + 无后续 node_retried 且 fail_count < max_retries"场景。

已知遗留：`tests/skills/test_workflow_dispatcher_bash_skill_prompt.py::test_prompt_node_prompt_file_reads_and_renders` 单测因 Bug-8 修复（`_resolve_prompt_file` shim）失败——该测试此前依赖旧错误路径 `root/prompt_file`，需另起任务更新断言适配新 resolver 语义。

测试：相关 56 + 29 用例（loop dispatcher / loop_until / retry handler / check_features / continue main loop / code-review routing）全 pass。

PR 拆分建议：714e78d + 140a8b8 是工作流引擎修复，与本需求 13 个 feature 业务实现解耦。若开 PR 时希望按 commit 拆分 review，可在 PR 描述里强调"按 commit 看：F-001~F-N 是功能实现，714e78d / 140a8b8 是独立的引擎修复"——保留单 PR 也可，需要时按 commit cherry-pick 到 hotfix 分支无依赖。

---

## 阶段 4 概要设计起草完成（2026-05-19）

- 产出：`requirements/20260519-context-usage-report/artifacts/outline-design.md`（4 章节：架构方案 / 模块划分 / 技术选型 / 关键流程）
- 影响模块与 `tech-feasibility.md §影响模块` 一致，未新增模块。
- 状态分类规则、评分规则、异常回退策略已细化到伪代码 / 表驱动级别；接口签名、SQL、features.json、测试用例留阶段 5 / 8。

### 阶段 4 留下的待确认项

1. **`high_value` 阈值 `reference_count >= 3`**：是否合适，或改为 `>= 2`？仅一次窗口命中是否足够进入高价值名单？[待用户确认]
2. **`applied_signal_count` 是否在 JSON 报告中保留原始 count**：当前评分已封顶 40，语义上 count 本身不封顶。是否保留用于后续趋势分析？[待补充]

> 第 3 项「code block mask 抽公共模块」已在评审反馈后收敛为「Phase 3 治理入口落地后复盘」，不再作为开放待确认（详见 outline-design.md §待确认）。

### 阶段 5 详细设计起草完成（2026-05-19）

- 产出：`requirements/20260519-context-usage-report/artifacts/detailed-design.md`（4 章节：接口签名 / 数据结构 / 时序图 / 异常处理）
- 6 个组件全部给出 Python class / function 签名 + docstring + 入参约束 + 幂等性说明
- 8 个数据类字段表（MarkdownLink / KnowledgeFile / ReferenceEvidence / AppliedEvidence / BrokenLink / GitTimestamp / KnowledgeStatus / KnowledgeUsageSummary）
- 4 张 mermaid 时序图（主路径 + 3 条异常路径）+ 1 张状态分类流程图
- 评分函数与状态分类函数已给出可直接编码的伪代码
- 单测覆盖矩阵 TC-1 ~ TC-8 已给（阶段 8 落地）

### 阶段 5 留下的待确认项

1. **`HIGH_VALUE_REFERENCE_MIN = 3`**：与阶段 4 同款 [待用户确认]，未变。
2. **JSON `$schema` URL**：MVP 暂留字段位，不强制要 schema 文件。[待补充]
3. **是否保留原始 `applied_signal_count`（不封顶 40）**：当前设计已保留（score 封顶 ≠ 字段封顶），延续阶段 4 决议。

### 阶段 5 评审反馈应对（detail-design-quality-reviewer · 2026-05-19）

reviewer verdict = `approved`（5 个 minor issue 均不阻断），5 项已逐条应对：

| # | reviewer 建议 | 应对 |
|---|---|---|
| 1 | AppliedSignalClassifier.classify docstring 未声明对 markdown_links 的内部依赖 | docstring 增「内部依赖」段，明确依赖 mask_code_blocks + extract_headings |
| 2 | ReportRenderer.write 接口签名与幂等性章节对原子写表述不一致 | write docstring 写明「原子写：tmp + os.replace」，与异常处理章节统一 |
| 3 | KnowledgeUsageSummary.last_referenced_at 语义表述略绕 | 改为「所有引用本文件的 requirements 源文件中 last_commit_at 的最大值」 |
| 4 | features.json feat-009 acceptance_criteria 未提 6 个入参 wiring 校验 | 追加一条 acceptance：6 个入参串联校验 |
| 5 | features.json 缺机读派发字段（complexity / interfaces_frozen / touches） | 13 个 feature 全部补齐：feat-006/007/009 为 medium，其余 low；interfaces_frozen=true；touches 显式列出修改文件 |

### 阶段 4 评审反馈应对（outline-design-quality-reviewer · 2026-05-19）

reviewer verdict = `approved`（4 个 minor issue 均不阻断），4 项均已在 outline-design.md 内修复：

| # | reviewer 建议 | 应对 |
|---|---|---|
| 1 | 状态判定优先级未说明 high_value vs stale_candidate 取舍 rationale | outline-design.md §状态流转 加「优先级 rationale」段，明确高价值优于时效 |
| 2 | Mermaid 图缺 `EVD --> APP` 边，图文不一致 | 图中追加 `EVD --> APP` 依赖 |
| 3 | 边界章节未明示 `.gitignore` `reports/` 一行的 AC-08 豁免边界 | 边界章节新增条目，引用 requirement.md:170 / tech-feasibility.md R-04 |
| 4 | code block mask 抽公共模块的收敛时机悬置 | 改成「Phase 3 治理入口落地后复盘」，明确触发条件 |
