# REQ-2026-002 · 统一门禁系统 · 全周期复盘

**生成时间**：2026-04-29 16:25:00 (Asia/Shanghai)
**总周期**：2026-04-27 19:50 → 2026-04-29 16:14（约 44 小时跨 3 天，纯工作时长 ~16h）
**最终状态**：`completed / shipped`
**合入 PR**：#44（F-001+F-002）+ #45（F-003+F-004）+ #46（归档 chore）

---

## 1. 周期数据

### 阶段时长（vs 预期）

| 阶段 | 预期完成 | 实际完成 | 偏差 |
|---|---|---|---|
| definition | 2026-04-28 | 2026-04-27 | 提前 1 天 |
| tech-research | 2026-04-28 | 2026-04-27 | 提前 1 天 |
| outline-design | 2026-04-29 | 2026-04-27 | 提前 2 天 |
| detail-design | 2026-04-30 | 2026-04-27 | 提前 3 天 |
| task-planning | 2026-04-30 | 2026-04-27 | 提前 3 天 |
| development | 2026-05-07 | 2026-04-29 | 提前 8 天 |
| testing | 2026-05-08 | 2026-04-29 | 提前 9 天 |

> 说明：tech-research 估的 27 人天（单人串行）是按"传统人工开发"基线给的；实际靠 AI subagent 并行 + 复利化的工具链显著压缩。但如下"教训"段会列出隐性成本（hook 死锁 2 次 + spec drift 重审 4 次等）。

### 工作量

| 项 | 数量 |
|---|---|
| Code commit | ~95 个（PR #44 内 + PR #45 内）|
| Code review 轮次 | 9（F-001×1 / F-002×3 / F-003×3 / F-004×5 含 round-4/5）|
| Spec review 轮次 | 10（requirement×4 / outline×2 / detail×4）|
| 新增/重构 单测 | 211 passed（从 0）|
| 新增 plugin | 11（registry 13 gate − 2 个旧 PR4 已有）|
| 删除旧脚本 | 11（7 个 check-*.sh + post-dev-verify.sh + 5 个 lib/check_*.py）|
| 设计文档新增段 | 13（含 §2.2 helper / §2.3 audit / §3.1 模块拆分 / §3.4 RE_WRITE_OPS / §4.2 等）|

---

## 2. 关键技术亮点

### F-001：runner 骨架 + Gate 基类
- **graphlib.TopologicalSorter** 拓扑排序，无第三方依赖
- **Gate 基类**：precheck / run / commit_staged_writes / rollback 四段协议
- **registry.yaml schema 校验**：S1~S10 加载期硬校验，CycleError 早爆

### F-002：全量 7 plugin + adapter 化
- 旧 7 个 check-*.sh 改造为 plugin（行为等价，单测覆盖）
- pre-commit / post-dev-verify / CI 切到 runner，**5 step → 1 step**
- snapshot 行为契约（capture-baseline.sh + normalize-stderr.sh）保证零回归

### F-003：H1/H3/H4/H5 四个高优先级缺口
- **H1 R005 事务化**：staged_writes 暂存 + commit_staged_writes 失败统一走 GateFailed 回滚
- **H3 submit/next 同源**：submit trigger 复用 phase-transition gate 集合 + 多挂 PR-MERGED-STATE
- **H4 PR 状态闭环**：GATE-PR-MERGED-STATE 防向已合 PR 推新 commit
- **H5 Bash 写保护**：12 类写法正则覆盖（echo / heredoc / tee / dd / awk / sed -i / sponge / rsync / install / pathlib）+ 双轨白名单（SAVE_REVIEW_PID env + 父进程链）

### F-004：渲染产物 + escape_hatch + 旧入口删除
- **gate-checklist.md 改为 render-docs.py 渲染产物**（D-007 强校验，CI render --check diff 非空即 PR 失败）
- **--force-with-blockers escape_hatch**：CLI reason 三段校验（非空 / ≤1024 / 控制字符过滤）+ 退出码归 2 + audit log escape_used/escape_reason 双写
- **GATE-GH-AUTH + GATE-BASE-REACHABLE**：submit 完整化
- **删 11 个旧脚本** + adapter 清零

### F-004 round-4：C-009 hook fail-open
本会话期间踩坑后立即修复并立成规范：
- pre_tool_use.sh 加 `python3 -m py_compile scripts/gates/run.py` pre-check（~50ms/调用）
- 退出码翻译矩阵：rc=0 放行 / rc=1 业务 fail 阻断 / 其他 fail-open + WARNING
- 落规范 `context/team/engineering-spec/design-guidance/hook-fail-open.md`

### F-004 round-5：Codex review 反馈修复
PR #45 后 Codex 自动 review 给 3 条真实 finding：
- **P1**：submit.py 把 --force-with-blockers 转 env var 但 run.py 不读 → escape_hatch 在 submit 入口完全非功能性 ✅ 修
- **P3**：audit.exit_code 与 calc_exit_code 在非 strict 下 warning fail 不一致 ✅ 修（与本仓库 C-002 carry-over 相同发现，二次确认）
- **P2**：base_reachable 缺 main fallback → C-011 carry-over

---

## 3. 关键教训（必看）

### 教训 1：Hook 自指系统的死锁（踩了 2 次）

**第 1 次**（F-003 round 1+2）：subagent 先 commit 半成品 plugin → registry import 失败 → hook 自身崩溃 → 工具链全部锁死。**用户终端 escape 解锁**。

**第 2 次**（F-004 round-4 中、本会话）：git merge 在 run.py 留 `<<<<<<<` marker → 同款死锁。**本次靠 C-009 v1（py_compile pre-check）**修复，规范化为 design-guidance/hook-fail-open.md。

**第 3 次（同会话内）**：改 `_finalize_audit` 函数签名漏改 call site → TypeError → 死锁第 3 次。**C-009 v1 抓不到 runtime 异常**，只抓静态 syntax。**C-009 v2 (C-012) 待补**：trigger 抓 stderr 含 Traceback + run.py 顶层 try/except → exit 2 区分。

**核心教训**：
- 修过一次的死锁问题给"假安全感"——下次重构同一层时必复发
- fail-open 防御不能假设单一检测覆盖所有故障类型
- 必须分层独立兜底：L1 静态（py_compile）+ L2 runtime（顶层 try/except）+ L3 stderr 兜底（grep Traceback）+ L4 用户终端 escape

### 教训 2：R005 hash drift 重审 4 次

整个周期 detail-design review 跑了 **4 轮**，definition + outline-design 各跑 **4 / 2 轮**，主要原因：

- F-003 round-3 修 spec → R005 stale → detail-design 重审
- F-004 round-2/3 修 spec → R005 stale → detail-design 重审
- F-004 round-3 修 requirement.md 5 处 sourcing → R005 stale → definition + outline 重审

**根因**：R005 用 sha256 比对，**无法识别"语义等价"修改**（路径同源映射 / 错别字 / 标点 / 空行）。设计内的"严格性 vs 误报"折衷。

**对策**：
- 短期：escape_hatch 是设计内的解决方案（知情绕过 + audit）
- 长期：R005 优化（diff-only 模式 / escape_reason 升级 review 元数据 / reviewer agent 自动重算 hash）—— F-007 候选

### 教训 3：squash-merged 后 rebase 必撞冲突

PR #44 squash-merge 后，分支保留继续做 F-003+F-004。`/requirement:submit` 默认 rebase origin/develop → 87 个旧 commit 与 squash 后的单 commit 在同一文件互撞 → 冲突遍地。

**对策**：
- 改用 `git merge` 或 `--skip-rebase`（已沉淀到 experience）
- `/requirement:submit` 应加 detection：base 分支有 squash-merge 历史就 skip rebase

### 教训 4：长 shell 命令粘贴在 zsh 易切碎

给用户的复杂终端命令（含反斜杠续行 / 超长单行）粘贴时被 zsh 切碎，把数据文件名当命令执行报 `permission denied`。

**对策**：给用户的终端命令优先级：
1. 单条短命令多次粘贴（< 80 字符 / 行，无续行符）
2. 封装到 /tmp/x.sh 让用户跑 `bash /tmp/x.sh`
3. `&&` 链式（不加续行）仅当总长 < 150 字符
4. **禁用** 反斜杠续行多行复合命令

---

## 4. 经验沉淀（永久资产）

跨需求级别（`context/team/experience/`）：

| 文件 | 来源教训 |
|---|---|
| `hook-self-import-deadlock.md` | 教训 1 |
| `squash-merged-branch-cannot-be-rebased.md` | 教训 3 |
| `long-shell-commands-paste-pitfall.md` | 教训 4 |

体系规范级别（`context/team/engineering-spec/design-guidance/`）：

| 文件 | 内容 |
|---|---|
| `hook-fail-open.md` | Hook 必须区分业务 fail 与基础设施故障；后者 fail-open + WARNING |

### 已立但 v2 待补的规范

- C-009 v1 解了静态 syntax 死锁；v2 待加 runtime 检测（C-012）

---

## 5. Carry-over 清单（C-002 ~ C-012）

11 条登记到 plan.md 给后续需求消化：

| ID | 类别 | 摘要 | 候选归属 |
|---|---|---|---|
| C-002 | runner bug | runner stdout EXIT 与 audit.exit_code 不同步 | **F-004 round-5 已修** |
| C-003 | spec | features.json F-004.acceptance 仅 4 条未补 round 子项 | F-005 启动前 |
| C-004 | security | render-docs.py main --check 路径未 relative_to | F-005 |
| C-005 | security | reason stderr 脱敏策略统一 | F-005 |
| C-006 | architecture | scripts/gates/run.py 726 行 > 500 阈值 → 拆 cli.py RFC | F-005 启动前 |
| C-007 | governance | run.py 30 天 22 commits 高频热区 → 稳定化窗口 | 软约定 |
| C-008 | governance | 同 feature 连续 round 12h 静默期约定 | 软约定 |
| ~~C-009~~ | hook-deadlock | hook 自身 import 死锁 | **F-004 round-4 已修** |
| C-010 | gate-system | testing → completed 弱门禁加固（GATE-COMPLETION-FIELDS / GATE-TEST-REPORT-EXISTS / GATE-PR-MERGED）| **F-006 候选**（已在 requirement.md:141 列入"不包含但已规划"）|
| C-011 | gate-system | base_reachable.py 缺 main fallback（Codex P2）| F-005 候选 |
| C-012 | hook-protocol | C-009 v2 layered fail-open（trigger 抓 stderr Traceback + run.py 顶层 try/except）| F-005 候选 |

### D-013 业务价值锚点推迟

D-008 立的"新增门禁工时 ≤ 0.5 人天"业务价值验收，本需求范围明确不新增门禁，无法 dogfooding。按 D-013 决策推迟到下次实际新增门禁的需求实测。

---

## 6. 流程改进建议（针对 Agentic Engineering 框架）

### B-1：retrospective 文档应作为 testing 阶段必产出
- 当前 phase-rules.md testing 必产出 `test-report.md` + 追溯链；本周期临时手写 retrospective.md
- 建议立 `retrospective.md` 为 testing 必产出（与 test-report.md 并列），用 template 引导

### B-2：reviewer agent 接到"修 spec" must_fix 时应自动跟重审任务
- F-003/F-004 多次发生：code review 要求改 spec → 改完触发 R005 stale → 主 Agent 手动派 detail-design reviewer 重审
- 自动化：reviewer agent 输出 verdict 时如含 spec 修改建议，调度自动登记"重审 spec"为后续 task

### B-3：R005 增 `--allow-stale` 或 ctx.cli_flags 旁路
- development 阶段允许 stale=true 时 R005 降级 ERROR → WARNING（不阻断当前阶段流程）
- 与 escape_hatch 协议组合，避免 spec 修改在阶段内被 R005 阻断

### B-4：hook fail-open 协议升级到 C-009 v2
- 已立 design-guidance/hook-fail-open.md，但 v2 章节待补
- F-005 实施 C-012 同时更新规范文档

### B-5：feature-lifecycle-manager Skill 加 12h 静默期 soft check
- 同 feature 连续 round < 12h 触发下一轮时给 warning（C-008）
- 有助于 reviewer 与 implementer 各自有清空缓存窗口

### B-6：give-user-shell-commands 规范化
- 立"AI 给用户的终端命令必须 < 80 字符 / 行，无反斜杠续行"硬约束
- 复杂命令封装到 /tmp/*.sh 脚本让用户跑

---

## 7. 复盘结论

### 成功（值得固化）

1. **8 阶段规范** + 强门禁体系真正驱动开发节奏，无人为跳步骤
2. **多 Agent 并行**（review-critic + code-quality-reviewer 三方裁决 + 8 checker 并行）显著降低误报
3. **escape_hatch + audit log** 设计在第 4 轮 R005 重审中体现真实价值（虽然本次最终选择重审而非 escape）
4. **dogfooding 闭环**：F-004 round-4 的 hook fail-open 修复立刻保护本会话第二次 merge 的工具链不死锁——复利工程的范例

### 失败（教训沉淀）

1. **C-009 v1 给假安全感**：解决一次死锁问题不等于架构上消除死锁可能性
2. **R005 误报** 4 次额外 review 工时累积约 30 分钟，应早做"语义等价"路径
3. **submit.py force-with-blockers 整套链路非功能性**直到 Codex review 才被发现，**自测覆盖盲区**：测试 runner 直跑 escape_hatch 时绕过了 submit.py 包装层
4. **rebase vs merge 选择不科学**：默认 rebase 在 squash-merge 项目里必撞冲突，应作为 git workflow 默认决策

### Codex review 反思

PR #45 后 Codex 给的 3 条 P1+P2+P3 finding 全部成立。其中：
- **P3 与 C-002 完全一致**：人工提前发现 = AI 提前发现，二次验证有效
- **P1 暴露我们的自测盲区**：单测覆盖 runner 直跑路径 + escape_hatch 校验，但漏测"submit.py 这一层是否真的把参数透传"
- **P2 是当前仓库不踩的潜在 bug**：单仓库测试无法发现的多仓库场景

**改进**：以后所有"参数透传链"必须有 e2e 测试覆盖端到端调用路径，不能只测中间层。

---

**复盘完成。REQ-2026-002 工作正式结束。**
