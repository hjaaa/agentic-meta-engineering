---
id: REQ-2026-005
title: "门禁系统加固：strict 失效 / Hook 覆盖 / submit 门禁等 10 项缺陷修复"
created_at: "2026-05-01 18:01:30"
refs-requirement: true
---

# REQ-2026-005 · 门禁系统加固

## 背景

本仓库的门禁系统（`scripts/gates/` + `.claude/settings.json` Hook 链 + `.github/workflows/quality-check.yml`）承担"代码改动前 / 提交前 / 阶段切换前 / PR 提交前 / CI"五道关卡的合规校验，是项目"AI 自动化协作 + 人类卡点"模式的核心强制层。

经一轮对抗式 review-critic 验证（10 条 finding 全部 `not_rebutted`，1 条 F3 被驳回），发现 5 类系统性弱化：

1. **strict 模式形同虚设**：CI 用 `--strict` 期望把 warning 也 FAIL，但插件把 warning 装进 `Decision.PASS` 的 `vars["warnings"]`，runner `calc_exit_code` 从不读这个字段（来源：scripts/gates/audit.py:111）。
2. **Hook matcher 漏 MultiEdit**：Claude Code 端 hook 配置 `matcher: "Bash|Edit|Write"`，但 `protect_branch.py` 内部的 `WRITE_TOOLS` 已支持 `MultiEdit`（来源：scripts/gates/plugins/protect_branch.py:27）；Hook 不被拉起则 plugin 永远没机会运行（来源：.claude/settings.json:27）。
3. **registry SoR 失效**：`filter_gates` 只按 `trigger` 过滤，`applies_when` 下的 `changed_files / target_phase / current_phase_in / transition / requires` 字段在 runner 主流程零消费（来源：scripts/gates/run.py:281）；语义靠 plugin 内部各自实现，registry 不是真正的 Single Source of Records。
4. **escape hatch 命名误导**：`--force-with-blockers` 字面像"只绕过 review blocker"，但 `_handle_escape_hatch` 命中后任何 `error` 级 gate 失败一律返 0（来源：scripts/gates/run.py:516）；对比 `legacy-requirement` 有 `skips_gates_with_tag: [review-verdict]` 限定（来源：scripts/gates/registry.yaml:307）。
5. **submit/CI/降级路径松懈**：submit.md 列了 7 条门禁但 `submit.py` 仅透传 `--trigger=submit --req=<id>`（来源：scripts/gates/triggers/submit.py:74）；`base_reachable.py` 不读 `cli_flags.target`（来源：scripts/gates/plugins/base_reachable.py:58）；`reviews_consistency` 只在 pre-commit 跑无 CI 兜底（来源：scripts/gates/plugins/reviews_consistency.py:21）；`pr_state` gh 失败/CLOSED 都降级 PASS（来源：scripts/gates/plugins/pr_state.py:82）；`traceability` 仅 `to_phase=="testing"` 真跑（来源：scripts/gates/plugins/traceability.py:39）；CI workflow 仅 5 step 无 build/test/lint（来源：.github/workflows/quality-check.yml:31）。

被驳回的 F3（"Bash 多行命令绕过"）核查后发现前提错误（pre_tool_use.sh 用 `json.load(stdin)` 整体解析，不按行切），不入本次范围。

## 目标

- **主目标**：使门禁系统真正能拦截"应拦截"的场景——消除 strict 模式 warning 被吞、Hook matcher 漏匹配、registry 字段零消费、escape hatch 范围过宽、submit/CI 关键 gate 缺失五类缺陷。
- **次要目标**：补齐 CI 的 build/test/lint 兜底（roadmap.md G1/G4 自承待办，来源：context/team/engineering-spec/roadmap.md:138）；为 `--force-with-blockers` 引入更准确的别名 `--bypass-review-blockers`，6 个月（**2026-11-01**）后删除旧名。

## 用户场景

### 场景 1：CI 跑 `--strict` 必须能拦下 warning

- **角色**：项目维护者 / CI 系统
- **前置**：某 PR 的 plan.md 触发 W003（"不包含"段无子条目）
- **主流程**：CI 跑 `python3 scripts/gates/run.py --trigger=ci --strict`
- **期望结果**：退出码 = 1，PR 红灯阻止合并；不再出现"声称 strict 但实际 warning 被吞→exit 0"的当前行为（来源：scripts/gates/audit.py:111）

### 场景 2：开发者在 develop 分支误操作要被全方位拦下

- **角色**：开发者（Claude Code 用户）
- **前置**：当前在 `develop / main / master` 分支
- **主流程**：调用 MultiEdit 批量改代码
- **期望结果**：被 `protect_branch` plugin 拦截并提示切 feature 分支；当前行为是 hook 不被拉起→改动直接落地（来源：.claude/settings.json:27）（来源：scripts/gates/plugins/protect_branch.py:27）

### 场景 3：从 bootstrap 直接跳 testing 必须被拒

- **角色**：开发者 / lifecycle Skill
- **前置**：需求 phase = `bootstrap`
- **主流程**：执行 `python3 scripts/gates/run.py --trigger=phase-transition --from=bootstrap --to=testing --req=<id>`
- **期望结果**：runner 查相邻表后报 `INVALID-PHASE-TRANSITION` 错误并 exit 1；当前行为是 `_validate_phase_args` 仅查 phase 是否在 canonical 集合内，跨阶段跳跃放行（来源：scripts/gates/run.py:333）

### 场景 4：`--force-with-blockers` 不应放过非 review-blocker 类 error

- **角色**：开发者
- **前置**：某 phase-transition 因 `GATE-WORKSPACE-CLEAN`（工作区脏）失败
- **主流程**：开发者带 `--force-with-blockers="<reason>"` 重试
- **期望结果**：不放行（理由：该参数语义是"绕过 review blocker"，与 workspace 脏无关）；当前行为是任意 error gate 失败一律返 0（来源：scripts/gates/run.py:516）（来源：scripts/gates/registry.yaml:313）

### 场景 5：submit 时漏关键门禁要拦下

- **角色**：开发者执行 `/requirement:submit`
- **前置**：当前分支 ≠ `meta.branch`（误推到非配套分支）
- **主流程**：跑 submit 流程
- **期望结果**：被 `GATE-BRANCH-MATCH`（新增）拦下；当前行为是 submit.py 仅透传 trigger，无独立 gate 校验分支匹配（来源：scripts/gates/triggers/submit.py:74）

### 场景 6：CI 跑出 Python 静态错误 / 测试失败 / lint 异常要拦下

- **角色**：CI 系统
- **前置**：PR 改动了 `scripts/gates/plugins/`
- **主流程**：CI workflow 跑全套门禁
- **期望结果**：除门禁 runner 外，还跑 `pytest tests/gates/`（已存在 16 个测试文件，来源：tests/gates/ 目录）+ `ruff check scripts/`（新增依赖）；任一失败即 PR 红灯。当前行为是 quality-check.yml 仅 5 step 无 build/test/lint（来源：.github/workflows/quality-check.yml:31）

## 非功能需求

- **性能**：门禁 runner 单次执行（含全部 plugin）耗时不应因本次改动增加 > 20%（CI 关键路径，已知 [待用户确认]——目前 runner 实际耗时无 baseline 数据）
- **兼容性**：
  - 已合入 develop 的历史 PR/commit 在改动后**不应**因 strict 升级被回溯报错（仅约束未来行为）
  - `--force-with-blockers` 旧名保留 alias，旧 alias 命中时 stderr 打印 `[DEPRECATED] use --bypass-review-blockers instead, removed at 2026-11-01`
  - registry.yaml 现有 21 条 gate 定义（来源：scripts/gates/registry.yaml）：F4 改动后所有现存 gate 必须能继续通过门禁，不许出现"配置语义变了 plugin 没跟上"的回归
- **安全/合规**：
  - F2 修复后 develop/main/master 分支上 MultiEdit 必须被拦——这是项目"分支保护"约束的硬底线
  - F6 改名后 6 个月（2026-11-01）删除旧名，到期由 `/schedule` 提醒（**待补充：删除策略**）
    - 内容：旧名删除时间点 2026-11-01 [待补充]
    - 依据：业界 deprecation 6 个月窗口惯例
    - 风险：部分 CI 脚本/文档若未及时切换会破
    - 验证时机：2026-08-01 中期审视一次旧名调用频次

## 范围

### 包含（按 5 个 feature 组归并）

- **FG-001 strict 模式 + CI 兜底**（覆盖 F1 + F8）
  - 修 `scripts/gates/audit.py:111` `calc_exit_code`：strict 模式下遍历 `r.vars.get("warnings")`，非空即升级为 `has_warning_fail`
  - 把 `GATE-REVIEWS-CONSISTENCY` 加入 CI trigger（修 `scripts/gates/registry.yaml` 的 `triggers:` + `scripts/gates/plugins/reviews_consistency.py:21` 的 trigger 校验）

- **FG-002 Hook matcher 覆盖**（覆盖 F2，仅 .claude 侧）
  - 修 `.claude/settings.json:27` matcher 加 `MultiEdit`
  - 不修改 `.codex/hooks.json`（项目决策不维护 codex 双轨）
  - 复用 `protect_branch.py:27` 既有 `WRITE_TOOLS` 集合（无需改插件代码）

- **FG-003 registry SoR + phase 相邻表**（覆盖 F4 + F5）
  - 修 `scripts/gates/run.py:281` `filter_gates`：消费 `applies_when.changed_files / target_phase / current_phase_in / transition / requires`
  - 一刀切删除各 plugin 内部的 changed_files 过滤逻辑（来源：scripts/gates/plugins/meta_schema.py:54）（来源：scripts/gates/plugins/sourcing.py:48）（来源：scripts/gates/plugins/index_integrity.py:49）（来源：scripts/gates/plugins/plan_freshness.py:52）；为防漂移彻底单源
  - 在 `scripts/lib/phase_enum.py` 或 phase-rules.md 新增 `ADJACENT_PHASES` 数据；修 `scripts/gates/run.py:333` `_validate_phase_args` 校验 from→to 必须在邻接表中

- **FG-004 escape hatch + submit 门禁链路**（覆盖 F6 + F7）
  - F6：`registry.yaml:313` 的 `force-with-blockers` escape hatch 加 `skips_gates_with_tag: [review-verdict]`；新增 alias `--bypass-review-blockers`；旧名命中打 stderr deprecation warning
  - F7：新增三个 plugin：
    - `GATE-BRANCH-MATCH`（校验 `git branch --show-current == meta.branch`）
    - `GATE-PHASE-IN-SET`（submit 时 phase ∈ {development, testing}）
    - `GATE-AHEAD-OF-ORIGIN`（本地 commit 数 > 远端）
  - F7：修 `scripts/gates/plugins/base_reachable.py:58` `_resolve_base_branch` 优先读 `ctx.cli_flags.get("target")` fallback 到 `ctx.meta.get("base_branch")`；修 `scripts/gates/triggers/submit.py:74` 透传 `--target` 参数

- **FG-005 降级路径收紧 + CI build/test/lint**（覆盖 F9 + F10 + F11）
  - F9：扩展 `scripts/gates/plugins/traceability.py:39-49`：submit trigger 也跑（不再只 testing）；`_feature_mentioned`（line 160）从纯 `re.search` 升级为"段落级 + feature_id 单词边界"匹配以减少误报
  - F10：修 `scripts/gates/plugins/pr_state.py:82-93`：gh 失败时 fall through 到本地 `git ls-remote` 检查；CLOSED 状态从 PASS 改为 `WARNING + 提示用户确认是否重开 PR`；MERGED 仍保持 FAIL
  - F11：在 `.github/workflows/quality-check.yml:31` 后追加两个 step：
    - `pytest tests/gates/ -v`
    - `ruff check scripts/`（新增 ruff 依赖到 install 步骤；ruff 配置写入 `pyproject.toml`，规则集 `[E, W, F]` 起步）

### 不包含

- **F3**（已被 review-critic 驳回，pre_tool_use.sh 用 `json.load(stdin)` 整体解析无多行绕过路径，前提错误）
- **`.codex/` 双轨同步**（项目决策不维护，前面 chore 同步入库的 commit 已撤销）
- **G2/G3/G5 等 roadmap 列出但本轮 review-critic 未覆盖的项**（来源：context/team/engineering-spec/roadmap.md）；待后续需求处理
- **门禁 runner 性能优化**（即便存在性能瓶颈也不在本次范围；本次只动正确性）

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| 修复颗粒度 | 10 个 feature / 5 组归并 / 3 组按优先级 | 5 组（FG-001~FG-005） | 同主题 finding 共享代码路径（如 F1+F8 都在 audit.py + reviews_consistency 改 trigger），分开会重复修改文件；用户已确认 |
| F4 plugin 内部 changed_files 处理 | 删除 / 保留双轨 / runner 优先 plugin fallback | 一刀切删除 | 双轨易漂移；registry 上移后再保留 plugin 内副本会出现"配置改了 plugin 没跟上"的同步成本；用户已确认 |
| F6 旧名处理 | 立即删 / 永远保留 / deprecate 6 个月 | deprecate 6 个月（**2026-11-01** 删） | 业界 deprecation 惯例；保留 alias 让 CI 脚本/文档有迁移窗口；用户已确认 |
| F11 build/test 工具选型 | pytest only / pytest + mypy / pytest + ruff / pytest + ruff + mypy | pytest + ruff | pytest 已配（pyproject.toml）；ruff 是事实标准 lint，零配置启动；mypy 留待未来需求；用户已确认 |
| F2 codex 侧是否同步修 | 同步修 / 仅修 .claude / 删 .codex 配置 | 仅修 .claude | 项目决策不维护 codex 双轨（依据：本会话用户决议；已撤销 chore commit）；用户已确认 |

## 待澄清清单

1. **runner 单次耗时基线**：当前无量化数据，FG-003 改动（registry 字段消费、相邻表查询）可能引入耗时增长。**建议在 FG-003 实施前用 `time` 抓 baseline；超 20% 即降级方案** [待用户确认]
2. **F11 ruff 规则集严格度**：起步用 `[E, W, F]`（基础语法/警告/pyflakes），但是否要顺带启用 `I`（isort 顺序）/ `UP`（pyupgrade）/ `B`（bugbear）？过严会导致首次 PR 大量 reformat [待用户确认]
3. **F6 旧名 deprecation 删除时机**：2026-11-01 是建议时间，是否要绑定一个"`--bypass-review-blockers` 在 CI 调用 ≥ 1 次"的硬指标作为前提？还是无条件按时删？ [待用户确认]
4. **F10 CLOSED → WARNING 改造**：当前是 PASS+`gh_call_failed: True`；改成 WARNING 后，CI 在 `--strict` 下会因 FG-001 升级而 FAIL——这是预期行为吗？还是 CLOSED 应该是 INFO 级（不参与 strict 升级）？ [待用户确认]
5. **F9 traceability submit trigger 加入后回归**：现有所有完成态 REQ（REQ-2026-001~003）执行 submit 时会重新跑 traceability，若历史 features.json/detailed-design.md 不满足新校验逻辑会回溯报错。**是否需要 grandfather 机制（meta.legacy=true 跳过）？** [待用户确认]
6. **runner 单次耗时基线方法**：[待补充]
   - 内容：用 `time python3 scripts/gates/run.py --trigger=<all> --req=REQ-2026-005` 跑 5 次取中位数作为 baseline
   - 依据：本仓 plugin 数量（21 条）+ 单次 IO 主要为读 yaml/md，耗时本身应在 1~3s 量级
   - 风险：若 baseline 实际 > 5s，FG-003 改动后即便 +10% 也会拖慢 CI
   - 验证时机：FG-003 实施前与实施后各跑一次对比

---

## 备注

- 本文档严格遵循三态规则（详见 .claude/skills/requirement-doc-writer/reference/sourcing-rules.md）。
- 评审通道：`requirement-quality-reviewer` Agent 将在 `/requirement:next` 进入 tech-research 前对本文档做六维评审。
- meta.yaml 语义字段补齐计划：`feature_area: gate-system`、`change_type: bugfix`、`affected_modules: [scripts/gates, .claude/settings.json, .github/workflows]`、`tags: [gate-hardening, p0-fixes]`（在结束 definition 前必须 commit）。
