---
id: REQ-2026-010
phase: tech-research
title: workflow 引擎 main loop 与 bootstrap 完整化 · 技术预研
---

# REQ-2026-010 · 技术预研报告

## 1. 技术选型确认（5 条 AC 的核心技术决策）

### AC-01：bootstrap 完整化——load_workflow 挂入 + 切分支策略

**load_workflow 挂入点**：`workflow_run.py` 在 `main()` 中仅做模板文件 glob 查找，找到后立即调用 `_generate_run_id()`，不经过 `load_workflow` 做 schema 校验（来源：scripts/lib/workflow_run.py:87）。需要在 glob 成功后、`_generate_run_id()` 之前插入一次 `load_workflow(template_path)` 调用；若 `result.report.errors > 0` 则 exit 1 并打印报告——无需新增模块，约 10 行。

**已有 load_workflow**：签名 `load_workflow(path: Path) -> LoadResult`，返回 `LoadResult.workflow` 与 `LoadResult.report`，接口契约完整（来源：scripts/lib/workflow_loader.py:139）。结论：挂入技术无阻碍，直接复用。

**REQ-ID 格式不一致**：现有 `_generate_run_id()` 生成的是 `RUN-YYYYMMDD-NNN` 格式（来源：scripts/lib/workflow_run.py:29），而 AC-01 要求需求类 bootstrap 生成 `REQ-YYYY-NNN`。需要新增一个 `_generate_req_id()` 函数，扫描 `requirements/` 下现有 `REQ-YYYY-NNN` 目录取 max+1，同样用 EEXIST 重试保护。工作量约 0.5 天。

**切分支策略：subprocess git 还是 GitPython**：项目现有全部 git 操作均通过 `subprocess.run(["git", ...])` 实现（来源：scripts/lib/common.py:38）；仓库中无 GitPython 依赖。沿用 `subprocess git checkout -b feat/req-<id>` 不引入新依赖，风险最低。切分支失败需触发回滚（已建目录的反向撤销）。

**plan.md 生成**：`bootstrap-validate` 节点的 `must_exist` 检查 `$ARTIFACTS_DIR/../plan.md`（来源：.claude/workflows/requirement/standard-8phase.yaml:55），但当前 `workflow_run.py` 不建 `plan.md`，main loop 一启动 bootstrap-validate 就会立即失败。bootstrap 副作用必须包含写一个最小 `plan.md` 骨架。

**结论**：AC-01 技术选型成立，需补齐 3 个缺口（REQ-ID 格式、切分支、plan.md 骨架），无新技术依赖。

### AC-02：main loop dispatcher——单文件 vs 拆模块

**现状**：`workflow_continue.py` 的 `_main_loop_stub` 仅打印状态，注释明确"F-006 待落地"（来源：scripts/lib/workflow_continue.py:23）。

**7 类节点 dispatcher 复杂度差异大**：bash 节点只需调 `subprocess.run`；approval 节点需要写 `approval_pending` 事件并 return；sub_workflow 节点需要派 Agent 并 poll；loop 节点需要状态机跟踪迭代计数。

**单文件 vs 拆模块**：参考已有 `workflow_rollback.py` 的拆法（主文件 + 4 个子模块：`_lock` / `_archive` / `_subrun` / `_topology`，来源：scripts/lib/workflow_rollback.py:14），REQ-2026-009 详细设计已给出 7 类节点的执行决策表（来源：requirements/REQ-2026-009/artifacts/detailed-design.md:366）。建议从单文件写起（`workflow_dispatcher.py`），把每类节点的处理逻辑拆成独立函数，后续按需升级为子模块。MVP 阶段单文件约 300-400 行，可维护。

**variable substitution + shellQuote**：`substitute_vars.py` 已完整实现，包含 `shell_quote()` / `substitute_vars()` 以及节点 output 序列化策略，与 detailed-design §2.3 规划完全对齐（来源：scripts/lib/substitute_vars.py:61）。dispatcher 直接复用现有 `substitute_vars()` 即可，无需重写。

**结论**：AC-02 技术选型成立，建议单文件 dispatcher 起步。

### AC-03：模板变量参数化——env 注入 vs 字符串预替换

**现状**：`standard-8phase.yaml` 中硬编码 `runs/$RUN_ID/...` 的节点有 7 处（`phase-to-tech-research` / `phase-to-outline-design` / `phase-to-detail-design` / `phase-to-task-planning` / `phase-to-development` / `phase-to-testing` / `archive-finalize`，来源：.claude/workflows/requirement/standard-8phase.yaml:703）。全部是 bash 节点。

**两种方案对比**：
- **方案 A（bash subprocess env 注入）**：引擎派发 bash 节点时向 subprocess 的 `env` 字典注入 `RUN_DIR`/`META_PATH`/`ARTIFACTS_DIR` 等变量，bash 脚本内 `$RUN_DIR` 直接展开。优点：bash 变量语义自然；缺点：`$RUN_DIR` 在 `artifact: must_exist` 这类非 bash 字段下不生效。
- **方案 B（字符串预替换）**：引擎在加载节点时对所有字符串字段统一 `substitute_vars()` 替换，把 `$RUN_DIR`/`$META_PATH` 替换成字面路径。优点：统一、已有 `substitute_vars` 实现可直接用；缺点：bash 节点内 `$RUN_DIR` 如果被 `shellQuote` 包单引号，shell 脚本会收到字面字符串而非变量展开，需要在 bash 节点特殊处理（`escape_for_bash=False` 注入路径字面值）。

**结论**：推荐方案 B，与现有 `substitute_vars` 设计意图一致（来源：requirements/REQ-2026-009/artifacts/detailed-design.md:335）；`$RUN_DIR` 和 `$META_PATH` 作为引擎内置变量，在 `substitute_vars` 的 `env` 字典中注入，不使用 bash subprocess 环境变量（与 `$ARGUMENTS` / `$ARTIFACTS_DIR` 同一注入机制）。

### AC-04：父子路径收敛——向后兼容性问题

**路径分裂现状**：
- `workflow_status.py`：扫 `run_dir/nodes/*/run_id`（来源：scripts/lib/workflow_status.py:41）
- `workflow_rollback_subrun.py`：策略 2 扫 `run_dir/sub_runs/<node_id>/` 直挂目录（来源：scripts/lib/workflow_rollback_subrun.py:79）

**向后兼容分析**：当前没有任何历史 run 使用了 `nodes/<id>/run_id` 路径——这是 `status.py` 中一段未运行过的"展望代码"，尚无实际 sub_workflow 运行产物（因为 main loop 从未真正派发 sub_workflow 节点；依据：requirement.md 第 18 行明确"引擎核心 main loop 与 bootstrap 副作用未落地"）。

**结论**：`workflow_status.py` 中 `nodes/` 路径是未实际运行过的逻辑，改为扫 `sub_runs/` 无历史兼容问题。改法：把 `status.py` 的 `nodes_dir = run_dir / "nodes"` 改为 `sub_runs_dir = run_dir / "sub_runs"`，直接迭代子目录即可，无需读文件取 run_id（目录名即子 run_id）。

### AC-05：真 e2e——LLM 派发成本与稳定性

**占位测试已定位**（grep 二次确认，闭环 requirement.md 待澄清清单第 3 条）：
- `tests/e2e/test_code_review_embedded.py:8`：文件头注释"外部依赖（subagent 调用）全部通过 monkeypatch / fixture 隔离，不真实启 subagent"
- `tests/e2e/test_sub_workflow_lifecycle.py:12`：文件头注释"不真派 Agent（MockSubAgent + monkeypatch）"

**成本测算** [待用户确认]：若必须走真实 LLM，每次 e2e 估算消耗数百到数千 token（input），按 claude-sonnet 当前定价单次约 sub-cent 量级；两个测试以日常 CI 频度运行，月成本量级单位为美元个位数，财务可接受。具体数字属阶段 3 时点的估算（详见待澄清清单条目 1 关于 mock 方案的最终决定），最终以实际计费为准。

**稳定性风险更关键**：LLM output 格式不确定（即使有 `output_format` 约束），网络超时与限流是非零概率事件，会导致 CI flaky rate 上升 [待用户确认]——具体抖动率以实际接入后 CI 统计为准。

**替代方案**：mock `_dispatch_agent_node()` 的返回值，让它返回固定的 `{"output": "{\"verdict\": \"passed\", ...}"}` 结构，同时完整走 main loop 路径（jsonl 写入 → RunState 重建 → `node_completed` 断言）。这满足 AC-05 的"断言 jsonl 含 `node_completed` 且 output 非空"要求，且 CI 完全稳定。

**结论**：`[待用户确认]` AC-05 的"真派 Agent"是否允许 mock LLM dispatcher 层（仅 mock `_dispatch_agent_node` 的返回值，不走真实 Claude API），验证 dispatcher 整条链路。若必须走真实 LLM，建议标记 `@pytest.mark.slow` 并从 CI 默认套件中排除。

## 2. 风险识别（按严重度排序）

### R-01：阻塞型——bootstrap-validate 在 plan.md 未生成时必定 FAIL

- **类别**：tech
- **描述**：`bootstrap-validate` 节点的 `must_exist` 检查 `$ARTIFACTS_DIR/../plan.md`（来源：.claude/workflows/requirement/standard-8phase.yaml:55），当前 bootstrap 副作用不建 plan.md。若先实现 main loop 但不补齐 bootstrap，AC-02 的 e2e 在第一个节点就会失败。
- **可能性**：high / **影响**：high
- **缓解**：AC-01 bootstrap 完整化必须先于 AC-02 main loop e2e；bootstrap 副作用补全包含建 `requirements/<id>/{plan.md, artifacts/}` + 写 meta.yaml + 切分支

### R-02：阻塞型——yaml 大量 bash 节点硬编码 `runs/$RUN_ID/`，与 D-007 双轨期冲突

- **类别**：tech + compat
- **描述**：所有 yq 写 meta.yaml 的 bash 节点路径都是 `runs/$RUN_ID/meta.yaml`（来源：.claude/workflows/requirement/standard-8phase.yaml:703）。在 D-007 双轨期，需求类 run 目录在 `requirements/<id>/`（来源：scripts/lib/run_state.py:319），若 bash 节点 yq 去写 `runs/<id>/meta.yaml` 而实际路径在 `requirements/<id>/`，每个 `phase-to-xxx` 节点都会失败
- **可能性**：high / **影响**：high
- **缓解**：AC-03 参数化改造必须在 main loop 通跑之前完成；引擎注入 `$RUN_DIR` 和 `$META_PATH` 为实际解析后的绝对路径

### R-03：兼容型——status 与 rollback_subrun 路径分歧导致 rollback 后 status 看到空子 run 树

- **类别**：tech
- **描述**：`workflow_status.py:41` 扫 `nodes/`；`workflow_rollback_subrun.py:79` 扫 `sub_runs/`。AC-04 场景 3 要求"status 输出的父子树与 rollback 看到的子 run 集合完全一致"
- **可能性**：medium / **影响**：high
- **缓解**：AC-04 同时修改 `workflow_status.py`，把 `nodes/` 改为 `sub_runs/` 路径

### R-04：测试稳定性——AC-05 真 e2e 若走真实 LLM 会引入 flaky test

- **类别**：tech + ops
- **描述**：网络超时 / API 限流 / 模型输出格式变化都可能导致 CI 非确定性失败
- **可能性**：medium / **影响**：medium
- **缓解**：mock LLM dispatcher 层（详见 AC-05 评估）；若用户要求真实调用，标记 `@pytest.mark.slow`

### R-05：安全/兼容——切分支 subprocess 失败时的回滚不完整

- **类别**：tech + security
- **描述**：若 `mkdir requirements/<id>/` 成功但 `git checkout -b` 失败，需要 `shutil.rmtree` 删已建目录。若删目录本身又 IOError，会留下残留目录
- **可能性**：low / **影响**：high
- **缓解**：bootstrap 副作用用 try/except 包裹，参考 `workflow_rollback.py` 的 `.in_progress` 标记模式（来源：scripts/lib/workflow_rollback.py:14）；失败时至少 rm -rf 已建目录，打 ERROR 日志后 exit 1

### R-06：性能——dispatcher 延迟目标可达性

- **类别**：tech
- **描述**：requirement.md NFR 要求"单节点 dispatcher overhead ≤ 200ms"（来源：requirements/REQ-2026-010/artifacts/requirement.md:70）。dispatcher 本身是纯 Python 文件 IO（jsonl append + read + substitute_vars），无网络调用。单次 jsonl append 约 1-5ms（来源：scripts/lib/run_state.py:268），`substitute_vars` 约 0.1-1ms。总 overhead 约 10-30ms 量级，远低于 200ms
- **可能性**：low / **影响**：low
- **缓解**：无需特别优化；阶段 8 用 `time.perf_counter()` 做一次微基准确认（50 次采样取 P95）写入测试报告即可，不建议为此在 CI 增加性能断言（过于脆弱）

## 3. 工作量估算

### 按 AC 粗估

| AC | 内容 | design | dev | test | 合计（天）|
|---|---|---:|---:|---:|---:|
| AC-01 | bootstrap 完整化：load_workflow + REQ-ID + 切分支 + plan.md + 回滚 | 0.5 | 1 | 0.5 | **2** |
| AC-02 | main loop 真派发 7 类节点（含 approval 写 `approval_pending` return）| 0.5 | 2 | 1 | **3.5** |
| AC-03 | yaml 硬编码路径参数化：7 处 `$RUN_ID` → `$RUN_DIR`/`$META_PATH` | 0.3 | 0.5 | 0.5 | **1.3** |
| AC-04 | 父子路径收敛：改 status + rollback 共用 `sub_runs/`，e2e 验证 | 0.3 | 0.5 | 0.7 | **1.5** |
| AC-05 | 替换 2 条占位 e2e（推荐 mock dispatcher）| 0.2 | 0.5 | 0.8 | **1.5** |

**合计：约 9.8 天**（design 1.8 / dev 4.5 / test 3.5）

类比依据：REQ-2026-009 详细设计中"main loop"相关 Plan 估算 15 人天（来源：requirements/REQ-2026-009/artifacts/tech-feasibility.md:255），本需求是其子集（只做 main loop 框架，不含 sub_workflow 父子联动、loop 完整实现），估 9.8 天合理。

### 关键路径

```
AC-01（bootstrap 完整化）→ AC-03（yaml 路径参数化）→ AC-02（main loop e2e 通跑）
                                                          ↓
                                                    AC-04（路径收敛，可并行 AC-02 dev）
                                                    AC-05（占位 e2e 替换，依赖 AC-02 dispatcher 接口）
```

关键路径深度：AC-01 → AC-03 → AC-02 → AC-05（约 8.3 天串行）。AC-04 可与 AC-02 dev 并行。

### PR 拆分建议

- **PR-A**：AC-01（bootstrap 完整化）+ AC-03（yaml 路径参数化）——纯 bootstrap 侧改动，risk 独立，可单独上绿
- **PR-B**：AC-02（main loop）+ AC-04（路径收敛）+ AC-05（e2e 替换）——引擎执行侧，依赖 PR-A 合并后才能 e2e 通跑

## 4. 关键预研结论（针对 requirement.md 待澄清清单 4 条）

### 待澄清 1：dispatcher 延迟硬指标是否可达

**结论：技术上完全可达，建议定位为软约束（SLO）**

依据：dispatcher 核心操作为 jsonl append（fcntl.LOCK_EX + os.write，约 1-5ms）+ `substitute_vars`（纯字符串替换，约 0.1-1ms）+ yaml 节点 meta 读取（已加载入内存，0ms）。总计远低于 200ms。

**建议**：将 200ms 定位为软约束（SLO），验证时机阶段 8 用 `time.perf_counter()` 做一次微基准确认。不在 CI 加硬断言（机器性能差异可能导致 flaky）

### 待澄清 2：LLM 真派发 e2e 成本测算

**结论：建议 mock LLM dispatcher 层**——满足 AC-05 断言要求，且 CI 完全稳定；若必须走真实 LLM 则用 `@pytest.mark.slow` 排除常规 CI

`[待用户确认]` 是否同意 mock dispatcher 层的方案

### 待澄清 3：占位测试具体行号 grep 定位

✅ 已闭环：`tests/e2e/test_code_review_embedded.py:8` 与 `tests/e2e/test_sub_workflow_lifecycle.py:12`（详见 AC-05 评估）

### 待澄清 4：NFR 性能基准验证时机

**结论：阶段 8 测试验收前做一次微基准跑批，不做 CI 增量断言**

理由：dispatcher overhead 是宽松上限，日常 CI 只需功能断言；性能基准属于一次性验证（架构不变则数据稳定）。建议阶段 8 写 `tests/perf/test_dispatcher_perf.py`（50 次采样，P95 < 200ms），标 `@pytest.mark.perf` 排除常规 CI，验收报告中附一份基准数据即可

## 5. 技术可行性总体结论

**feasibility: high**

无阻塞级技术障碍。所有核心依赖（`load_workflow` / `substitute_vars` / `run_state.RunState.rebuild` / `append_event` / `_resolve_run_dir`）均已完整落地，接口契约清晰：

- `load_workflow` 接口（来源：scripts/lib/workflow_loader.py:139）
- `substitute_vars` 实现（来源：scripts/lib/substitute_vars.py:61）
- `append_event` 锁机制（来源：scripts/lib/run_state.py:268）

主要工作量集中在 AC-02 main loop dispatcher 框架与 AC-01 bootstrap 副作用补全，合计预估见 §3 工作量估算表（人天数字属预估，详见待澄清清单条目 2）。

**关键风险点** [待用户确认]：bootstrap、main loop、yaml 路径参数化三项的协同依赖顺序（bootstrap 副作用必须先于 main loop e2e）；建议拆两个 PR 控制合并风险。D-007 双轨期下父子路径分裂（`nodes/` vs `sub_runs/`）是已知的代码不一致，改动量小且无历史兼容负担。

## 待澄清清单

本阶段新增的待澄清条目（用户已于阶段 3 末确认锁定）：

1. **AC-05 mock dispatcher**：✅ 锁定为 mock `_dispatch_agent_node` 返回值方案，不走真实 Claude API；阶段 4 详细设计时落实 mock fixture 与断言写法
2. **工作量预估**：✅ 9.8 天估算锁定为阶段 4 起点
3. **PR-A / PR-B 拆分**：✅ PR-A=AC-01+AC-03，PR-B=AC-02+AC-04+AC-05；阶段 4 概要设计需明确两个 PR 的模块边界
4. **dispatcher 延迟目标**：✅ 200ms 定位为软约束（SLO），阶段 8 micro-bench 一次性验证，不入 CI 硬断言
