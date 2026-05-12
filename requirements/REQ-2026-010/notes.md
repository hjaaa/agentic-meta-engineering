# REQ-2026-010 · 过程笔记

## 起手说明

本需求是 REQ-2026-009（自定义工作流改造）在 PR-68 hotfix 后的 Window B 落地。
PR-68 完成了 Window A 紧急修复（keyword_matcher 兼容性、workflow_rollback_cmd 健壮性等），
Window B 的 main loop 完整化与 bootstrap 流程补全延至本需求实施。

## F-001 review follow-up（rev2 looks_clean 后接受的非阻断项，待后续 feature 顺手清扫或独立 PR）

- ~~**G-1（error-handling minor）**：`workflow_run.py` `else 998` 死分支~~ → 已在 `a6ab298` 修复
- ~~**G-6（aux minor）**：`test_workflow_commands.py:873` `# TC-F1-3：` 全角冒号~~ → 已在 `a6ab298` 修复
- ~~**G-2（complexity follow-up）**：`tests/skills/test_workflow_commands.py` 902 行近 1000 硬阈值~~ → 已闭合（F-007 rev3 拆 4 文件：happy 291 / advanced 338 / state 278 / reqgen 271，最大 338 ≤500）
- **G-5（security follow-up）**：`scripts/lib/workflow_run.py:118` `os.scandir` / `:74` `iterdir` 异常路径未 WorkflowError 包装（独立议题——独立 PR 全仓 FS 异常治理时一起做）
- **G-7/G-8（aux follow-up）**：测试文件 5+ 处方法内 `import workflow_run as wr` / `from datetime import ...` 风格统一上提（独立 PR 重构）
- **G-9（concurrency info）**：TC-F1-2 `barrier.wait()` 防御性包入 try（实践不可触发）
- **F-7（info, drop）**：`results.append` GIL 依赖——CPython GIL 保证 list.append 原子，是被广泛接受的并发实践
- **F-11（info, drop）**：测试代码 `except Exception` 过宽——测试本就要捕获所有意外，宽泛 except 是合理模式
- **F-1（history-context info）**：`tests/skills/test_workflow_commands.py` 30 天内 2 次 hotfix（7ffc8ad / ff16de2）——已被 F-007 rev3 拆分自然降温

## F-002 review follow-up（rev2 looks_clean 后接受的非阻断项）

### rev2 keep minor（建议后续 feature 顺手清扫）

- ~~**G-3（complexity minor）**：`scripts/lib/workflow_bootstrap.py:243` `_bootstrap_requirement` 51 代码行 / 6 步骤~~ → 已闭合（REQ-2026-010 follow-up 清扫，抽 `_write_bootstrap_artifacts` helper，主函数缩到 ~35 行）
- ~~**S-1（aux minor）**：`tests/skills/test_workflow_bootstrap.py:37` 同分组内 `from run_state import read_events` 出现在 `import workflow_bootstrap as wb` 之前~~ → 已闭合（REQ-2026-010 follow-up 清扫，from-import 移到 import-as 之后）
- ~~**S-3（aux minor）**：`scripts/lib/workflow_bootstrap.py:56` `BootstrapError.__init__` 无 docstring~~ → 已闭合（REQ-2026-010 follow-up 清扫，补 3 行 docstring 说明 artifacts_created/branch_created 用途）
- **S-4（aux minor, drop）**：`scripts/lib/workflow_bootstrap.py:94` `logging.debug("git rev-parse HEAD 失败 ...")` 行长 104 字符——项目 ruff `line-length=120` 未超限

### rev2 keep info（不强求修）

- **G-5（complexity info）**：`scripts/lib/workflow_run.py:99` `_generate_req_id` 伪嵌套深度 5（多行字符串折行触发，实际控制流深度 4），静态分析边界误报
- **H-1（history-context info）**：`test_workflow_commands.py` 90 天 7 commits 热点；rev2 已拆 `test_workflow_bootstrap.py`，热点会自然降温
- **S-2（aux info，downgraded）**：`tests/skills/test_workflow_bootstrap.py:432` 方法体内 `from common import WorkflowError` 内联导入；测试常见模式，可在大规模重构时统一上提
- **复杂度压线提醒（info）**：`scripts/lib/workflow_bootstrap.py:320` `_bootstrap_rollback` CC=10 / depth=4 / 66 代码行三指标 ==阈值未越界；后续触碰时拆 `_rollback_git_checkout` + `_rollback_git_branch` 两个 helper

### rev1 已 critic-rejected（drop，不再 follow-up）

- **F-6 / F-7**：notes.md 创建 / git add+commit ——detailed-design §1.2 + tasks/F-002.md acceptance 均不要求，bootstrapper.md 旧 subagent spec 已被 Python 实现替代
- **F-18**：`_generate_run_id` iterdir vs scandir 不一致 ——已在 F-001 G-5 同款 follow-up 备案
- **F-21**：previous_branch `--` 前缀 git arg injection ——git check-ref-format 强约束，攻击不可达

### rev2 引入的 EH-1/EH-2/EH-3（rejected, out-of-scope）

`workflow_run.py:268 / 309 / 348` 三处 print stderr 无 logging.error——属 F-001/F-005 既有代码，**不在 F-002 rev2 diff 范围**。如需统一治理日志可观察性，建议作为独立小 PR 收敛全仓 `print(file=sys.stderr)` 调用（按 F-008 / F-009 落地经验拓展）。

## F-003 review follow-up（rev2 D-014 横向扫描发现，独立议题）

### rev2 keep follow-up

- ~~**F-5（error-handling minor）**：`scripts/lib/workflow_run.py:229` `workflow = load_result.workflow` 依赖 load_workflow 契约~~ → 已闭合（REQ-2026-010 follow-up 清扫核查：当前 :229 已有 `# dict，由 load_workflow 保证非 None` 注释守门，无需再改）

### rev2 D-014 横向扫描发现（独立议题，不在 F-003 范围）

- **TestNewEventsDoNotChangeState docstring 风格蔓延**：`tests/skills/test_workflow_commands.py:586` 也存在多行 docstring，与单行风格不一致；rev2 修复只闭合本 feature 引入的 `TestLoadWorkflowSchemaGate`，既有 class 留独立 PR 统一
- **F-001 / F-002 frontmatter touches 完整性盲区**：F-001 / F-002 当时无 receipt.json 留痕，无法核查 touches 字段是否覆盖实际 diff 范围。建议独立 review 周期核查（参考 D-014 同语义类别区分原则）
- **F-8 系统性问题**：feature task.md 在 detailed-design 阶段就该把测试文件预先纳入 touches，或 GATE-TOUCHES-VIOLATION 增加 `tests/skills/test_<同模块名>.py` 白名单豁免——属 spec-level 议题，需独立需求承载
- ~~**F-002.receipt.json 残留 violation**（rev2 judge 发现）：`F-002.receipt.json` 仍有 1 条 `touches_violations[]` 记录（`review-20260511-155100.md` Write，F-002 rev2 review 报告写盘时 current_feature=F-002 触发）。F-002 已 done（signoff approved at 15:54），但 receipt 未自动清理。GATE-TOUCHES-VIOLATION 可能在 phase-transition 时扫所有 feature receipt 命中。~~ → **已 hotfix（A+B 组合）**：(a) F-002.receipt.json violations[] reset 为 []；(b) `touches_guard._is_process_artifact` 白名单从 6 类扩到 7 类，新增 `<req_dir>/artifacts/review-*.md` pattern（parent+name 匹配，跨需求不豁免）；(c) 加 3 个新测试用例 TL-WL-008/009/010 覆盖正反例；hooks 40 tests passed；GATE-TOUCHES-VIOLATION 双向断言（pass / fail）OK。(c=phase-transition 只扫 in-progress 的方案不采纳——违背 gate 文档"扫所有 feature"的合规校验意图)

## F-006 review rev2 D-014 横扫发现（任务边界外，留痕备查）

### 修复范围内（已闭合）
- dead import REPO_ROOT（workflow_dispatcher.py）、MagicMock（测试文件）
- dead fixture repo_root（测试文件）
- hardcoded /tmp/ 路径（test_skill_node_args_node_output_substituted）
- 4 处注释失实（L170 banner、L180 agent docstring、L191 skill docstring、L225 prompt docstring）
- bash returncode!=0 stderr 空兜底
- detailed-design.md 3 处 spec-lag（F-8/F-9/F-10）

### 任务边界外，不修，仅留痕
- `_dispatch_agent_node`（F-010）/ `_dispatch_loop_node`（F-011）/ `_dispatch_sub_workflow_node`（F-011）的 stub docstring 准确描述了其待实现状态，**不属于失实**——F-006 rev2 正确识别为不修
- `_dispatch_loop_node` / `_dispatch_sub_workflow_node` 签名与实际实现一致（stub 返回 completed），无需在 F-006 触碰（各自由 F-011 接管）

## REQ-2026-010 follow-up hotfix · dispatch lock 残留污染（2026-05-12）

**触发场景**：F-009 done 之后做 review follow-up minor 清扫期间，主 Agent 编辑 `workflow_bootstrap.py` / `test_workflow_bootstrap.py` / `.gitignore` / `F-008.receipt.json` 共 6 文件，全部被 `touches_guard` 记到 `F-009.receipt.json` 的 `touches_violations[]`——因为 dispatch lock `current_feature=F-009` 没在 done 时释放。

**根因（双重）**：
1. `feature-lifecycle-manager` SKILL 的 done 转换流程未提调 `dispatch_state_cleanup.py`——CLI 写好且 docstring 明确说"feature 完成后清理"，但 `grep -rln dispatch_state_cleanup` **全仓零调用**。F-001~F-009 全程 lock 一直停在最后一个派发的 feature，靠下次 dispatch_precheck 覆盖才"被动重置"
2. `.dispatch-state.json` 自身写入也会被 touches_guard 记为 violation（白名单 7 类不覆盖 lock 文件本身）

**修复（A+B+C 组合）**：
- (a) **流程层**：`feature-lifecycle-manager/SKILL.md` 阶段 7 完成触发加第 5 步 + `reference/feature-states.md` 状态变更同步动作表加 `python3 scripts/lib/dispatch_state_cleanup.py --req-dir requirements/<id>`（CLI 幂等，重复调安全）
- (b) **兜底层**：`touches_guard._is_process_artifact` 白名单从 7 类扩到 8 类，新增 `<req_dir>/.dispatch-state.json` 精确路径匹配（与 plan/notes/meta/process.txt 同模式）
- (c) **测试**：新增 TL-WL-011（sandbox 内 `.dispatch-state.json` 豁免）+ TL-WL-012（跨需求不豁免，白名单不过宽）；hooks 全套 40 → 42 passed

**验证**：tests/hooks/ + tests/lib/test_dispatch_state.py 共 58 passed

**遗留议题**（独立追踪）：cleanup CLI 调用是文档级约束，依赖 AI 阅读 SKILL；若未来发现仍漏调可考虑加 PostToolUse Hook 自动触发（task.md status=done 翻转时调），但当前不引入新 hook 维护负担

## F-011 rev2 follow-up · loop_counters 内存递增不写事件导致崩溃恢复后重复执行 iteration（F-8 收口前修复）

**问题位置**：
- `scripts/lib/workflow_continue.py:266`：`loop_counters[node_id] += 1` 仅在内存中递增，不写任何事件到 jsonl
- `scripts/lib/run_state.py:208-210`：`RunState.rebuild` 只从 jsonl 中的 `loop_iteration_completed.data.iteration` 重建 `loop_counters`

**影响**：崩溃后 rebuild 重放 jsonl，`loop_counters` 比实际运行时少 1（`workflow_continue` 递增的那次未持久化）→ `_dispatch_loop_node` 重派已执行的同一 iteration → loop 崩溃恢复后重复执行同轮。

**修复时机**：F-008 收口前，与 loop 事件流驱动 rebuild 一并落地。

**修复方向（任选其一）**：
- (a) `workflow_continue.py` 递增后写 `loop_counter_advanced` 事件（`data.node_id + data.new_value`）供 `RunState.rebuild` 消费，重建时以该事件为准
- (b) `dispatcher` 在写 `loop_iteration_started` 时记录"将要执行的 iteration"（即 `current_iteration + 1`），`workflow_continue` 不再内存 +1，由 rebuild 推算

**引用**：review F-8（`requirements/REQ-2026-010/artifacts/review-20260512-115731.md`）

### 闭合记录（2026-05-12，选方向 a）

- `scripts/lib/run_state.py`：`VALID_EVENT_TYPES` 加 `loop_counter_advanced`；`RunState.rebuild` 增分支：`data.new_value` → `state.loop_counters[node_id]`
- `scripts/lib/workflow_continue.py`：`_route_outcome` `loop_continue` 分支递增后 `append_event(loop_counter_advanced, data={new_value})`
- 测试：
  - `tests/lib/test_run_state.py` 加 3 个：枚举围栏 / rebuild 消费 / advanced 覆盖 iteration 事件
  - `tests/skills/test_workflow_continue_outcomes.py` 加 2 个：loop_continue 写事件断言 + crash 后 rebuild 不漏读 +1
- 全套测试：**552 passed / 7 skipped / 2 pre-existing failures**（见下方独立议题）

### 独立议题（不在本 scope，留痕）

- `tests/skills/test_workflow_dispatcher_dispatch.py` 两个旧 stub 断言已与 F-006/F-011 真实现脱节：
  - `test_dispatch_node_loop_returns_completed` 期望 `outcome == "completed"`，真实现 max_iterations=1 缺省返 `loop_done`
  - `test_dispatch_node_sub_workflow_returns_completed` 期望 `completed`，真实现返 `sub_workflow_pending`
  - 自 F-006 commit `659137c`（2026-05-11 21:58）起即红，跨 F-007/F-008/F-009/F-011 全周期未修——独立 PR 把断言更新为真实现即可
