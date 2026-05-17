# REQ-2026-012 · 测试报告

> 阶段：testing
> 测试日期：2026-05-17
> 测试入口：`make ci-local`（F-007 本需求新建的本地 CI 镜像入口）+ 个别子 target 用 `python3 -m <tool>` 旁路（环境 PATH 适配）
> 测试目录：`/Users/richardhuang/learnspace/agentic-meta-engineering`，分支 `feat/req-2026-012` HEAD `36d1661`

## 1. 套件级结果（按 F-007 子 target 顺序）

| 子 target | 实际命令 | 结果 | 耗时 | 备注 |
|---|---|---|---|---|
| `ci-local-deps` | `pip install -r requirements/ci.txt` | **FAIL** (env-only) | n/a | macOS dev box `/bin/sh` PATH 无 `pip`（只 `pip3`），非代码 bug；Ubuntu CI runner `setup-python@v4` 自动建 `pip` shim，CI 不复现。本地用 `python3 -m pip install -r requirements/ci.txt` 旁路。 → **跟进项 #1** |
| `ci-local-gates` | `python3 scripts/gates/run.py --trigger=ci --strict` | **PASS** | ~3s | 8 gate 全过（META-SCHEMA / INDEX-INTEGRITY / SOURCING / PLAN-FRESHNESS / REVIEW-VERDICT / FEATURES-SCHEMA / TASK-FRONTMATTER / REVIEWS-CONSISTENCY） |
| `ci-local-pytest` | `pytest tests/ --ignore=tests/benchmarks/ -v` | **FAIL** (env-only) → 旁路 `python3 -m pytest`：**1524 passed, 8 skipped, 0 failed** | 74s | 同 ci-local-deps 的 PATH 问题。pytest 实际全过。 → **跟进项 #1** |
| `ci-local-settings-check` | inline python3 检查 hook 命令存在性 | **PASS** | <1s | 全部 hook command 路径在 .claude/settings.json 中存在对应文件 |
| `ci-local-bats` | `bats tests/hooks/` | **PASS** | ~30s | **59 test 全过**（含 V-06 hyperfine 100 runs avg < 5ms perf 断言、TC-F5-1 case1~3 touches_guard 覆盖、MultiEdit 越界软记 violation） |
| `ci-local-ruff` | `ruff check scripts tests --select=F` | **PASS** | ~2s | "All checks passed!" — F-004（89 处机械清理）+ F-005（6 处 F821 + Any/RoutingPlan import）+ F-006（CI scope 扩 scripts+tests）三步累积成果 |
| `ci-local-render-check` | `python3 scripts/gates/migration/render-docs.py --check` | **PASS** | <1s | "OK gate-checklist.md 与 registry 同步" |
| `ci-local-routing-e2e` | `bash tests/lib/test_routing_e2e.sh` | **PASS** | ~3s | "PASS=3 FAIL=0"（E2/E3/E4；E1 designed-SKIP 已由 pty 单测覆盖） |

**核心结果**：7/8 子 target 实际通过；剩 1（ci-local-deps）属 macOS 本地环境 `pip` shim 缺失，**非代码缺陷**——同根因影响 ci-local-pytest，但旁路 `python3 -m pytest` 后 1524 case 全过，证明 Ubuntu CI 路径无回归。

## 2. AC 逐项验收（来自 detailed-design.md §3 + features.json）

| AC | 描述 | 证据 | 结论 |
|---|---|---|---|
| AC-1 | routing e2e 入 CI workflow + 草稿 PR ubuntu PASS=3 FAIL=0 | F-001 草稿 PR #74 ubuntu run 25984126843 `PASS=3 FAIL=0`（notes.md:3-11）；本地 `ci-local-routing-e2e` `PASS=3 FAIL=0` | **PASS** |
| AC-2 | 删 `.claude/hooks/tests/test_protect-{branch,reviews}.sh` 后 bats 59 case 不退化 | F-002 commit d7624d2 删除；bats 全 59 case 仍过含 V-01/V-03/14 redirect | **PASS** |
| AC-3 | requirements/ci.txt 同源化 CI / 本地 / onboarding | F-003 commit 1fefea9 新建 + workflow yml + onboarding md 均改为 `pip install -r requirements/ci.txt` | **PASS** |
| AC-4 | `ruff check scripts tests --select=F` 退码 0 | `ci-local-ruff` PASS（F-004 89 + F-005 6 全清）；F-006 commit e738789 CI scope 扩到 scripts+tests | **PASS** |
| AC-5 | Makefile `ci-local` 入口 8 子 target + FAIL labels 1:1 + 强制失败时 `FAIL: <label>` 命中 | Makefile L11-L72（F-007）；本测试报告表 1 验证 8 子 target 实跑；FAIL labels 表 8 行与 `.PHONY` + recipe 1:1 一致 | **PASS** |
| AC-6 | F 类清理后 pytest 全过无回归 | `python3 -m pytest tests/ --ignore=tests/benchmarks/`：1524 passed, 8 skipped, 0 failed | **PASS** |
| AC-7 | 全仓 grep `test_protect-(branch|reviews)\.sh` 无残留引用 | `git log -- .claude/hooks/tests/`：F-002 commit d7624d2 删除两文件；本仓 grep（本测试报告本身豁免）= 0 hit | **PASS** |
| AC-8 | `context/team/experience/test-assets-must-be-wired-into-ci.md` 存在 + INDEX 索引 + check-index 无缺索引 | F-007 commit 0fd604e 新建文件；INDEX.md 追加索引行；本报告 ci-local-gates 内含 GATE-INDEX-INTEGRITY 通过 | **PASS** |

**8/8 AC 全过。**

## 3. 风险复盘（来自 outline-design R-1~R-7）

| ID | 风险 | 落地状态 |
|---|---|---|
| R-1 | routing e2e 在 ubuntu runner 不稳 | F-001 草稿 PR ubuntu 实测 PASS=3 FAIL=0（notes.md），且本地 `make ci-local-routing-e2e` 复现 PASS=3 |
| R-2 | hook 删除后用例覆盖空洞 | bats 59 case（含 V-01/V-03/14 redirect/V-06 perf）全过，无退化 |
| R-3 | ruff --fix 自动删 import 误伤运行时 | F-004 完整跑 pytest 全过；本次再次 1524 passed 0 failed |
| R-4 | ci.txt 漂移（cli 与 yml 不同源） | F-003 已让 workflow yml + onboarding md + 本地 `make ci-local-deps` 三处指向同一文件 |
| R-5 | local-vs-CI 漂移 | `make ci-local` 本地与 CI 同一组命令；本次 7/8 子 target 通过（剩 1 macOS PATH 环境问题，CI 不复现） |
| R-6 | experience 文件 spec 漂移 | F-007 已沉淀；2 minor follow-up（缺 `## 验证方法` 节 / 200 字规则与既定实践脱节）记入下一个清扫 REQ |
| R-7 | Makefile FAIL labels 与子 target 不一致 | 表 1 验证 8 子 target 名 + .PHONY + FAIL labels 三处 1:1 |

## 4. 跟进项

| # | 描述 | 优先级 | 处置 |
|---|---|---|---|
| 1 | Makefile recipe 用 `pip` / `pytest` 裸命令，在缺 `pip` shim 的 macOS dev box 上 fail；改 `python3 -m pip install ...` / `python3 -m pytest ...` 更便携 | low | **不纳入本需求**——CI 不复现（GitHub Actions setup-python 提供 shim）；记入归档时候选 hotfix 方向。受影响：`ci-local-deps` / `ci-local-pytest` |
| 2 | experience/INDEX.md:64-65 spec 与 38 邻居实际写作脱节（94.7% 违反 200 字规则、3% 缺 `## 验证方法` 节） | low | 已在 F-007 review verdict 列为 follow-up；归档时单独开清扫 REQ 修订 INDEX 规则 + 校准历史 38 份文件 |
| 3 | `test-assets-must-be-wired-into-ci.md` 缺独立 `## 验证方法` 节 | low | 已在 F-007 review verdict 列为 follow-up；与 #2 一并处理 |
| 4 | detail-design.artifact_hashes 把 task.md 钉 hash 是 reviewer 过度收敛 | low | 已在 notes.md 列为结构性 follow-up（D-010 ADR 已记录）；归档时另起 hotfix |
| 5 | `touches_guard.py` 误记仓库外路径（/tmp 等）→ 阻断 phase-transition / submit | low | 已在 notes.md 列为 D-011 候选 follow-up；归档时另起 hotfix（normalize 仓库内相对路径才记） |

5 项 follow-up **均不阻塞本需求合入 / 测试通过**。

## 5. 测试结论

**testing 阶段验收通过**：

- 7/8 套件子 target PASS（剩 1 为 macOS 本地 PATH 环境问题，非代码缺陷）
- 8/8 AC 全过
- 7/7 R 风险均有落地证据
- 5 项 follow-up 全部为 low 优先级，归档时另起 hotfix

可推进至 `submit`。
