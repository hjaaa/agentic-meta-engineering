# REQ-2026-003 · 测试报告

**生成时间**：2026-05-01 12:43 (Asia/Shanghai)
**当前 commit**：`01eac9f` (feat/req-2026-003)（pytestmark skip 提交后会刷新）
**meta.yaml.phase**：`testing`

## 1. 测试范围

本报告覆盖 REQ-2026-003「代码审查人类必经卡点（路由确认 + 结论 sign-off）」全 4 feature
（F-001 / F-002 / F-003 / F-004）的功能与非功能验收。

| 维度 | 来源 | 状态 |
|---|---|---|
| **A** 单元 + 集成 + e2e + benchmark 全过 | 本报告 §2 | ✅ |
| **B** 4 feature acceptance 闭环 | 本报告 §3 | ✅ |
| **C** Phase-transition 7 gate 全跑（含 GATE-TRACEABILITY 首次实跑） | 本报告 §4 | ✅ |
| **D** stale 测试清理（F-002 重构遗留） | 本报告 §5 | ✅ |

## 2. A 块 — 测试套件全过

执行命令与结果（2026-05-01 12:42 ~ 12:43）：

| 步骤 | 命令 | 结果 |
|---|---|---|
| 全量 pytest | `python3 -m pytest -q` | **370 passed, 7 skipped, 0 failed** in 13.30s |
| e2e bash | `bash tests/lib/test_routing_e2e.sh` | **PASS=3 / FAIL=0**（E1 主动 skip，E2-E4 通过） |
| Benchmark | `python3 -m pytest tests/benchmarks/test_routing_perf.py` | **3/3 PASS**，P95 全部远低于阈值（详见 §6） |
| Phase-transition 全 gate | `python3 scripts/gates/run.py --trigger=phase-transition --to=testing --req=REQ-2026-003` | **0 error / 9 warning**（W002 advisory），EXIT=0 |

### 测试覆盖统计（本需求新增/修改）

```
tests/lib/
├── test_code_review_routing.py            (F-001 + F-002 核心：U1-U10 / T1-T6 / U11-U12 / U-INV-1)
├── test_routing_e2e.sh                    (F-004 E1-E4 端到端)
├── test_save_review_signoff_subcommand.py (F-003+F-004 衍生：signoff 子命令)
├── test_is_signed_off.py                  (F-003+F-004 衍生：is_signed_off helper)
└── ...

tests/skills/
├── test_code_review_report_routing_section.py  (F-003 报告 routing 段)
├── test_code_review_signoff_skill.py           (F-003 signoff skill)
├── test_report_skipped_contract.py             (F-004 T-REPORT-1 防御性 contract)
└── test_code_review_prepare_routing.py         (整文件 SKIP，详见 §5)

tests/agents/
├── test_judge_skipped_contract.py         (F-004 T-JUDGE-1)
└── test_critic_skipped_contract.py        (F-004 T-CRITIC-1)

tests/commands/
└── test_signoff_command.py                (F-003 /code-review:signoff slash)

tests/benchmarks/
└── test_routing_perf.py                   (F-004 B1-B3，pytest-benchmark)
```

## 3. B 块 — 4 feature acceptance 闭环

详见 `reviews/code-F-001-002` / `code-F-002-002` / `code-F-003-001` / `code-F-004-002` 全部 approved。

### F-001 routing.py 核心引擎（looks_clean 90）

| # | 验收 | 验证方式 | 状态 |
|---|---|---|---|
| 1 | yaml 不存在/语法错/编码错 → 退码 4；schema V1/V3/V5 违反 → 退码 3；pathspec 锚定边界 | `TestLoadYaml*` / `TestValidateSchema*` / `TestBuildPlanPathspecAnchor` | ✅ |
| 2 | `_build_plan` 12 文件 mixed must=2/suggest=3/trivial=4/灰色=3 | `TestBuildPlanMixed::test_should_correctly_count_categories_for_mixed_12_files` | ✅ |
| 3 | `_build_plan` 5 文件全 .md → trivial_only=True | `TestBuildPlanTrivialOnly` | ✅ |
| 4 | RoutingConfig/RoutingPlan dataclass frozen + asdict 序列化 | dataclass 定义 frozen=True 直读源码确认 | ✅ |
| 5 | U-INV-1 契约：INV-PLAN-1/2 闭环 | `TestBuildPlanInvariants`（3 用例） | ✅ |

### F-002 tty 卡点 + 4 档热键 + audit + 写盘（needs_attention 78，2 keep major 已转 F-003 收口）

| # | 验收 | 验证方式 | 状态 |
|---|---|---|---|
| 1 | T1-T5 pty 集成（enter/a/1,3/q/3 次无效） | `TestPtyIntegration`（5 用例 真实 pty） | ✅ |
| 2 | T6 非 tty stdin → 退码 2，stderr 含 §6 文案 | `TestNonTtyRejection` | ✅ |
| 3 | U11-U12：'1, 3' / ' 1 ,3 ' 容错；must 强制保留 | `TestParseCustomInput` + `TestParseCustomInputMustForced` | ✅ |
| 4 | trivial-only 短路：不读 stdin / 写 skipped=true + audit 行 | `tests/lib/test_code_review_routing.py::TestTrivialOnlyShortCircuit`（pty 集成 T-A0） | ✅ |
| 5 | `_write_scope` I1-I8 八条不变量 | `_assert_scope_invariants` 在写盘前自检（运行时 assert，被所有 pty 测用例覆盖） | ✅ |

### F-003 routing.yaml + 三处文档同步（looks_clean 92）

| # | 验收 | 验证方式 | 状态 |
|---|---|---|---|
| 1 | routing.yaml 通过 `_validate_schema` V1-V7 | F-001 `TestValidateSchema*` 全过 | ✅ |
| 2 | must 5 条规则命中关系符合详设 §4 表格 | F-001 `TestBuildPlanMixed` 用样例验证 + 人工对表 | ✅ |
| 3 | code-review.md Step 2 不含硬编码 8 checker；含 skipped 短路 | grep `'不含硬编码'` + 文档检视 | ✅ |
| 4 | SKILL.md 无 `不豁免` 字串 | `grep -c '不豁免'` = 0 | ✅ |
| 5 | scope-schema.md 无 `concurrency 关键字`；新增 skipped + routing_decision；删除 mode_hint | `grep -c 'concurrency 关键字'` = 0 / skipped 命中 13 / routing_decision 命中 12 / mode_hint 命中 0 | ✅ |
| 6 | 4 处文档与 routing.py 字段名一一对应 | 文本检视 | ✅ |

### F-004 CI + e2e + benchmark + contract test（looks_clean 90）

| # | 验收 | 验证方式 | 状态 |
|---|---|---|---|
| 1 | E1-E4 端到端 | `bash tests/lib/test_routing_e2e.sh` E2-E4 PASS；E1 主动 skip（pty 单测覆盖） | ✅ |
| 2 | B1-B3 benchmark 阈值 | `tests/benchmarks/test_routing_perf.py` 3/3 PASS（详见 §6） | ✅ |
| 3 | quality-check.yml pip install 含 `pathspec>=0.12,<1.0` | grep 命中第 25 行 | ✅ |
| 4 | T-CRITIC-1 / T-JUDGE-1 / T-REPORT-1 contract test | 3 个文件 共 14 用例全过 | ✅ |
| 5 | develop 分支 routing.py --feature-id 透传链完整 | F-001/F-002/F-003 done 时已自举验证（3 次嵌入模式 review 走通） | ✅ |

## 4. C 块 — Phase-transition 7 gate 全跑

development → testing 切换走完整 7 gate（含 GATE-TRACEABILITY 首次实跑深度校验需求 → 设计 → 代码 → 测试链）：

| Gate | 结果 | 备注 |
|---|---|---|
| GATE-META-SCHEMA | PASS | meta.yaml schema 完整 |
| GATE-INDEX-INTEGRITY | PASS | INDEX.md 索引齐全 |
| GATE-SOURCING | PASS（9 W002 advisory） | 数字断言三态标记缺失，advisory 不阻断 |
| GATE-WORKSPACE-CLEAN | PASS | workspace 无未提交残留 |
| GATE-REVIEW-VERDICT | PASS | 4 feature 全部最新 review approved + signed off |
| GATE-TRACEABILITY | PASS | 需求/设计/代码/测试链路完整（首次实跑） |
| GATE-PLAN-FRESHNESS | PASS | plan.md 与 process.txt 同步 |

audit log 见 `requirements/REQ-2026-003/.audit/`，meta.yaml.gates_passed 已追加 testing 条目。

## 5. D 块 — stale 测试清理（F-002 重构遗留）

**发现**：testing 阶段首次跑 `pytest -q` 报 6 个 failure，全部集中在 `tests/skills/test_code_review_prepare_routing.py`。

**根因**：F-002 期间（commits `4502752` → `3d46fcb`）重构了 `code_review_routing.py` 的 CLI 与 tty 校验函数，旧测试 mock `_is_tty` / 调 `_run_default_mode` / CLI `--scope-out --all`，**重构后这些符号全部不存在**，但当时漏改这一个测试文件——核心 `tests/lib/test_code_review_routing.py` 已同步重写过、所以 F-001/F-002 review 时未发现。

**覆盖等价性**：
- TC-A1..A4（tty 4 档热键）≡ `tests/lib/test_code_review_routing.py::TestPtyIntegration`（T1-T5 真实 pty 集成，更接近真实路径）
- TC-A5/A6（非 tty rc=2）≡ `TestNonTtyRejection`（T6 端到端）
- TC-A7 一直为 `@pytest.mark.skip`，F-003 已落地，本就不再需要

**处理**：testing 阶段暂以 `pytestmark = pytest.mark.skip(reason=...)` 整文件 SKIP，文件保留为占位；后续经用户授权用 `git rm` 删除整文件。pytest 跑成 370 passed / 7 skipped / 0 failed。

**经验沉淀**（写入 notes.md）：
> 重构核心模块（改函数名 / 改 CLI 必填参数）时，**全仓库 grep 一遍待删/改的符号名 + 旧 CLI flag**——
> 单测目录可能有等价重复测试因路径偏离（`tests/lib/` vs `tests/skills/`）而被漏改。
> 后续机制：phase-transition 切 testing 时跑全套 pytest 强制门禁（不只是依赖前置 review 的局部跑），可在 testing 入口快速定位类似问题。

## 6. Benchmark 实测 P95

| 场景 | Mean (μs) | Max (μs) | 阈值 | 余量 |
|---|---|---|---|---|
| B1：trivial-only 50 文件 | 436 | 588 | < 100 ms | **170×** |
| B2：mixed 200 文件 | 1,416 | 1,605 | < 200 ms | **125×** |
| B3：large 2000 文件 | 12,928 | 13,788 | < 200 ms | **15×** |

3 档全部 PASS，无性能风险。

## 7. 已知 Carry-over（不阻塞 completed）

无。本需求范围内所有验收闭环；唯一 carry 是"`tests/skills/test_code_review_prepare_routing.py`
经用户授权后 `git rm`"——已用 SKIP 兜底，不影响 testing 通过。

## 8. 验收结论

**testing 阶段验收通过**，可切 testing → completed。

依据：
1. A 块测试套件全过（370 passed / 7 skipped / 0 failed / e2e 3 PASS / benchmark 3 PASS）
2. B 块 4 feature 22 条 acceptance 全部闭环（4 个 review 全 approved + tty signoff）
3. C 块 phase-transition 7 gate 全跑全过（含 GATE-TRACEABILITY 首次实跑）
4. D 块 stale 测试清理走 SKIP 兜底，覆盖等价物已在 `tests/lib/`

---

**审查链路**（4 feature 最终 round）：
- F-001：`reviews/code-F-001-002` looks_clean 90（supersedes -001）
- F-002：`reviews/code-F-002-002` needs_attention 78（2 keep major 已在 F-003 routing.yaml v1 收口）
- F-003：`reviews/code-F-003-001` looks_clean 92（trivial signoff）
- F-004：`reviews/code-F-004-002` looks_clean 90（supersedes -001）
- detail-design：`reviews/detail-design-003` looks_clean 90（纯 sourcing 修订）
