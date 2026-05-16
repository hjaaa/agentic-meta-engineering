---
id: REQ-2026-012
title: "CI 工程化补强：纳入 routing e2e、清理陈旧 hook 测试、统一依赖清单、ruff 范围扩展、本地 CI 镜像入口"
created_at: 2026-05-16 19:56:00
refs-requirement: true
---

# REQ-2026-012 · CI 工程化补强：纳入 routing e2e、清理陈旧 hook 测试、统一依赖清单、ruff 范围扩展、本地 CI 镜像入口

## 背景

本仓库的 CI 走 .github/workflows/quality-check.yml 单一 workflow，把 gate runner / pytest / bats / ruff / render check 等校验串成一条 step 序列（来源：.github/workflows/quality-check.yml）。在长期演进中累计出几处「工程债 / 工程能力外溢」的具体表现：

1. **有真实测试但游离于 CI 之外**：tests/lib/test_routing_e2e.sh 是 F-004 routing 路径的真 E2E shell 测试（真 routing.py + 真 routing.yaml + 假 git diff，来源：tests/lib/test_routing_e2e.sh:1），目前 CI 任何 step 都没跑它——quality-check workflow 中未出现该脚本名（来源：.github/workflows/quality-check.yml）。
2. **旧 hook 测试指向已删除文件**：.claude/hooks/tests/test_protect-branch.sh:4 仍以 `HOOK=".claude/hooks/protect-branch.sh"` 形式硬编码已删除路径（来源：.claude/hooks/tests/test_protect-branch.sh:4）；该分支保护逻辑现已搬到 pre-tool-use-guard.sh 的 Edit/Write/MultiEdit 分支，调用 check_branch_protect 函数（来源：.claude/hooks/pre-tool-use-guard.sh:101）。tech-research 阶段开篇 / F-A 草稿 PR / F-B 实施时各复验一次 `ls .claude/hooks/protect-branch.sh` 仍返回 MISSING，避免 hook 路径若意外复活后陈述失效。
3. **依赖来源与 onboarding 漂移**：workflow 安装 pyyaml / ruamel.yaml / pathspec>=0.12,<1.0 / ruff / pytest（来源：.github/workflows/quality-check.yml:34），但 onboarding 文档只让新人装单个 pyyaml（来源：context/team/onboarding/learning-path/01-environment.md:25），且仓库内既无 requirements/ci.txt 也无 pyproject.toml `[optional-dependencies]` 把 CI/test 依赖固化下来。
4. **ruff 范围与剩余 F 债脱钩**：CI 仅 lint scripts/ 目录（来源：.github/workflows/quality-check.yml:82），ruff 配置为 select = ["F"] / line-length = 120（来源：pyproject.toml:11）。本地跑 `ruff check scripts tests --select=F` 实测命中 95 条 F 类问题——`scripts/` 已 0 条，95 条全在 `tests/`；分布 F401×65（unused import）/ F841×21（unused var）/ F541×3（f-string 无占位符）/ F821×6（undefined name，集中在 tests/lib/test_code_review_routing.py 的 `RoutingPlan` 与 tests/lib/test_submit_codex.py 的 `Any`） [tech-research 阶段在 ubuntu-latest + workflow 同版本 ruff 复验，固化为 F-D1/F-D2 切分基线]。若现在直接把 tests/ 纳入 lint 范围，CI 会立刻变红。
5. **缺本地 CI 镜像入口**：`Makefile:4` 只暴露 `gates-validate` / `gates-render`，没有「把整条 workflow 在本地按序跑一遍」的统一入口；这正是经验沉淀 `context/team/experience/auto-generated-artifact-needs-pre-commit-not-just-ci.md:7` 所记录的「派生产物只靠 CI 兜底」场景的近邻问题——本地过 / CI 反复红的根因之一。

这些问题单独看都很小，但叠加起来会让"本地能跑过 ≠ CI 能跑过"成为隐性常态，浪费 review round-trip 并削弱新人 onboarding 体验。本需求一次性把它们规整到位。

## 目标

- **主目标**：让 CI 工作流真实覆盖仓库现有 shell e2e、ruff 全量 F 类检查、本地一致的依赖清单，并提供 `make ci-local` 入口让开发者在 push 前以同序同源跑完全部门禁。
- **次要目标**：
  - 清理与现状脱节的旧 hook shell 测试，避免新加入者按文件名误以为 `.claude/hooks/protect-branch.sh` 仍存在。
  - 把 onboarding 文档（`pip install pyyaml` 之类）与 CI 依赖清单收敛到同一份事实源。
  - 为后续逐步扩 ruff 规则集（`E` / `W` / `I` 等）打基础，但本次只动 `F`。

## 用户场景

### 场景 1：开发者修改 routing 配置或 routing.py 后提 PR
- **角色**：仓库贡献者
- **前置**：scripts/lib/code_review_routing.py 或 .claude/code-review-routing.yaml 发生变更（test_routing_e2e.sh 内部以 REPO_ROOT/scripts/lib/code_review_routing 为 import 路径，yaml 实际由 routing.py 加载，来源：.claude/code-review-routing.yaml）
- **主流程**：本地跑 `make ci-local` → 包含 `bash tests/lib/test_routing_e2e.sh` → 输出 `PASS=3 FAIL=0` → 推 PR → workflow 同一 step 复跑 → 一致结论
- **期望结果**：routing 路径回归不需要靠人工记得手跑 shell 脚本；CI 与本地结论 1:1

### 场景 2：贡献者删了 hook 文件但忘了清理对应 shell 测试
- **角色**：仓库贡献者
- **前置**：某个 `.claude/hooks/xxx.sh` 被合并进 `pre-tool-use-guard.sh` 并物理删除
- **主流程**：CI workflow 跑到 hook shell 测试 step → 立即失败 + 指明缺失文件
- **期望结果**：删 hook 与改测试是同一 PR 内的强约束；不再出现"本地直接 fail、CI 没跑、悄悄留下来"的中间态

### 场景 3：新人按 onboarding 装环境后跑测试
- **角色**：第一次 clone 仓库的新人
- **前置**：按 `context/team/onboarding/learning-path/01-environment.md` 装好 Python + 单一 `pip install pyyaml`
- **主流程**：跑 `pytest tests/` 或 `make ci-local` → 立刻报缺 `ruamel.yaml` / `pathspec` / `ruff` / `pytest`
- **期望结果**：onboarding 指令应能让所有 CI step 直接在本地跑通；不再有「装完 onboarding 还要去翻 workflow yaml 才知道差什么」的环节

### 场景 4：维护者扩 ruff 规则集
- **角色**：仓库维护者
- **前置**：F-D 已经把 `scripts/` + `tests/` 的现存 F 类问题清零
- **主流程**：维护者把 CI ruff 范围从 `scripts/` 改成 `scripts tests` → CI 仍绿
- **期望结果**：扩范围的动作本身不引入红 build；过程可逆——拆 PR 的清债与扩范围两步独立可回滚

## 非功能需求

- **性能**：`make ci-local` 默认与 CI workflow 等价镜像，含 `hyperfine` 路径；不跑 `tests/benchmarks/`（CI 当前即 `pytest --ignore=tests/benchmarks/`，来源：.github/workflows/quality-check.yml:57）。整体 wall time 因此约等于 CI workflow，若后续日常推 PR 觉得太慢，再补 `ci-fast` 子集入口。
- **可维护性**：CI 依赖清单与本地依赖清单必须**单一事实源**——`.github/workflows/quality-check.yml` 不再直接写 `pip install pyyaml ...` 字面量，而是引用 `requirements/ci.txt`（D-001 选 A，见决策记录）；非 Python 工具（`bats` / `hyperfine`）继续由 workflow 安装段 + onboarding 文档说明 `apt-get install`，不写进 pip 清单。
- **兼容性**：本次改动不破坏现有 .github/workflows/quality-check.yml 的触发条件 pull_request + push [main, develop]（来源：.github/workflows/quality-check.yml:7）和 step 顺序语义。
- **可回滚性**：7 个 feature（plan.md F-A / F-B / F-C / F-D1 / F-D2 / F-E / F-F，详见 plan.md 候选 feature 表）每个独立可回滚——单 PR + 单 commit 主体；尤其 F-D1（ruff 机械清债）与 F-D2（ruff 语义清债 / F821）合并后再开 F-E，确保 F-E 单独 revert 不让 CI 红。
- **安全/合规**：不引入新的密钥、不修改 CI 触发的 secret 来源；新依赖清单必须固定版本范围（如 `pathspec>=0.12,<1.0` 这种形式），不允许 `latest`。

## 范围

- **包含**：
  1. `.github/workflows/quality-check.yml` 新增一个 step：`bash tests/lib/test_routing_e2e.sh`
  2. 删除 `.claude/hooks/tests/test_protect-branch.sh` 与 `.claude/hooks/tests/test_protect-reviews.sh`（均指向已不存在的 `.claude/hooks/protect-branch.sh`，外部仅本需求 requirement.md 自身引用——来源：grep 全仓 `test_protect-(branch|reviews)\.sh` 仅命中本文件）；当前 bats `tests/hooks/test_pre_tool_use_guard.bats` 已覆盖 develop/main/master 三分支阻断（V-01）、reviews 写保护、14 类 Bash redirect 拦截（来源：tests/hooks/test_pre_tool_use_guard.bats:39），detail-design 阶段如发现负例缺口可补 0-2 条 bats，不再保留旧 shell 测试
  3. 新建 `requirements/ci.txt`（D-001 选 A），把 workflow `pip install` 字面量收敛为 `pip install -r requirements/ci.txt`；`pyproject.toml` 不动 `[project]` 表，避免顺手引入包结构改造
  4. 按风险拆 3 步推进 ruff 清债与扩范围：F-D1 机械清理 `tests/` + `scripts/` 的 unused import / unused var / f-string 类 → F-D2 处理 F821 等语义类 → F-E 把 `.github/workflows/quality-check.yml:82` 改为 `ruff check scripts tests --select=F`
  5. `Makefile` 新增 `ci-local` target：默认按 workflow step 顺序串行跑 gate runner / pytest（含 `--ignore=tests/benchmarks/`）/ bats / hook 引用检查 / ruff / render check / routing e2e / hyperfine 路径；非零退出即终止
  6. 同步更新 `context/team/onboarding/learning-path/01-environment.md`，把单条 `pip install pyyaml` 改为 `pip install -r requirements/ci.txt`
  7. 新增 `context/team/experience/test-assets-must-be-wired-into-ci.md`：「新增 shell / e2e / contract 测试默认进 CI；不进 CI 必须说明原因和手跑命令」（与 `auto-generated-artifact-needs-pre-commit-not-just-ci.md` 并列，问题域不同：前者是"测试资产创建后必须接入执行入口"，后者是"派生产物 / CI 兜底同步"）

- **不包含**：
  - 切换 CI 平台、改触发条件、改 runner image 版本
  - 把 ruff `select` 扩到 `F` 之外（`E` / `W` / `E501` 等独立 PR / 独立需求）
  - 写任何新的业务测试用例
  - 把 `hyperfine` 等性能基准测试改成 CI 强校验（保留 best-effort 语义）
  - 重构 `.claude/hooks/pre-tool-use-guard.sh` 的内部结构

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| D-001 CI/test 依赖清单的事实源 | A. `requirements/ci.txt`；B. `pyproject.toml [project.optional-dependencies]` 加 `ci` / `test` extras | **A** | 当前 pyproject.toml 只有 tool 配置、没有 `[project]` 表（来源：pyproject.toml:1），上 extras 等于顺手引入 Python 包结构改造；非 Python 工具 `bats` / `hyperfine` 仍由 workflow `apt-get` + onboarding 文档说明（来源：.github/workflows/quality-check.yml:36） |
| D-002 旧 hook shell 测试处理方式 | A. 全删除 + 必要时补 bats；B. 迁移到 `pre-tool-use-guard.sh:101` 等价逻辑的测试 | **A** | bats 已覆盖 develop/main/master 三分支阻断、reviews 写保护、14 类 Bash redirect 拦截（来源：tests/hooks/test_pre_tool_use_guard.bats:39）；旧 `test_protect-branch.sh` / `test_protect-reviews.sh` 的负例与 bats V-01/V-03 重合；若 detail-design 发现缺口补 0-2 条 bats 即可 |
| D-003 ruff 清债拆分粒度 | A. 单 PR 一次清完；B. 按子目录拆；**C. 按风险类型拆 3 个 PR**（机械清理 → 语义清理 → 扩范围） | **C** | 95 条中既有大量机械项（unused import / unused var / f-string），也有 F821 这类语义项；机械与语义需要不同 review 强度；C 让每个 PR 单独可 revert，且 F-E 单独红时可只回退 F-E 不打翻清债成果 |
| D-004 `make ci-local` 对慢 step 的处理 | A. 全跑（含 hyperfine / bench）；B. 默认跳过 hyperfine 类 | **A**（默认镜像 CI、含 hyperfine、不跑 `tests/benchmarks/`） | 名字叫 ci-local 就应等价 workflow；当前 CI 安装 hyperfine 并在 bats V-06 中使用，应保留；`tests/benchmarks/` 本来被 CI ignore（来源：.github/workflows/quality-check.yml:57），不纳入；若后续日常推 PR 觉得慢，再补 `ci-fast` 子集入口 |

## 验收标准（AC）

- **AC-1（routing e2e 入 CI）**：在 PR 触发的 `quality-check` workflow 日志中可见 `bash tests/lib/test_routing_e2e.sh` 这一 step，且输出包含 `PASS=3 FAIL=0`；本地 `make ci-local` 同 step 退出码 = 0
- **AC-2（旧 hook 测试不再红）**：`.claude/hooks/tests/test_protect-branch.sh`（及 `test_protect-reviews.sh`）要么已迁移为引用现存文件、要么物理删除并在 `.claude/hooks/tests/` 目录中无残留；`bats tests/hooks/` 与上述 shell 测试均 0 失败
- **AC-3（依赖单一事实源）**：`.github/workflows/quality-check.yml` 不再出现 `pip install pyyaml ruamel.yaml ...` 字面量列表；改为 `pip install -r requirements/ci.txt`；`context/team/onboarding/learning-path/01-environment.md:25` 指向同一份清单；`bats` / `hyperfine` 等非 Python 工具仍由 workflow `apt-get install` 段安装，不进 pip 清单
- **AC-4（ruff F 清债 → 0）**：`ruff check scripts tests --select=F` 本地与 CI 均退出 0；`.github/workflows/quality-check.yml:82` 改为 `ruff check scripts tests --select=F`；分 3 个 PR 推进——F-D1 机械清理 → F-D2 语义清理（F821 等）→ F-E 扩范围
- **AC-5（`make ci-local`）**：在 clean checkout 后跑 `make ci-local` 退出 0 = 等价于 CI `quality-check` job 全过（含 hyperfine 路径、`pytest --ignore=tests/benchmarks/`）；途中任一 step fail → make 退非 0 且 stderr 末段必须包含 `FAIL: <step-name>` 单行断言（step-name 与 Makefile target 内 `@echo` 一致，便于回归用 `make ci-local 2>&1 \| grep -E '^FAIL: '` 自动断言失败 step）
- **AC-6（不破坏既有触发）**：`.github/workflows/quality-check.yml` 触发条件、runner image、env 注入均未变；diff 限于 install / ruff range / 新 step
- **AC-7（可回滚）**：7 个 feature（F-A / F-B / F-C / F-D1 / F-D2 / F-E / F-F）各自的 PR 单独 revert 后 CI 仍能跑通；特别地，F-E 单独 revert 时 ruff 范围回退到 `scripts/` 而 F-D1 / F-D2 的清债产出保留
- **AC-8（经验沉淀就位）**：`context/team/experience/test-assets-must-be-wired-into-ci.md` 已创建并挂入 INDEX.md；内容包含触发场景、原则、不进 CI 时的强制说明 + 手跑命令格式

## 待澄清清单

> 以下条目均已在 definition 阶段一轮回灯闭环；保留为决策档案。tech-research 阶段会基于 D-003 真实拆解再决定 F-D1/F-D2 边界。

1. ✅ **D-001 选 A**：`requirements/ci.txt`，理由见决策表 D-001。
2. ✅ **D-002 选 A**：删除 `.claude/hooks/tests/test_protect-branch.sh` 与 `test_protect-reviews.sh`；bats `tests/hooks/test_pre_tool_use_guard.bats` 现有用例已覆盖 V-01 三分支 + V-03 reviews 写保护 + 14 类 Bash redirect（来源：tests/hooks/test_pre_tool_use_guard.bats:39）；detail-design 阶段若发现 0-2 个负例缺口，单独追加 bats 用例。
3. ✅ **D-003 选 C**：按风险拆 3 个 PR——F-D1 机械（unused import / unused var / f-string）→ F-D2 语义（F821 等）→ F-E 扩 ruff CI 范围；具体每类条数分布在 tech-research 阶段用 `ruff check scripts tests --select=F --output-format=json` 给出。
4. ✅ **D-004 选 A**：`make ci-local` 默认镜像 CI、含 hyperfine 路径、不跑 `tests/benchmarks/`；后续若日常推 PR 太慢再补 `ci-fast`。
5. ✅ **routing e2e 入 CI 前**：先用草稿 PR 触发一次单 step 验证 Ubuntu runner 行为（用户决议：本地 macOS PASS 不等于 Ubuntu PASS；来源：tests/lib/test_routing_e2e.sh:21）；该验证由 F-A 任务本身承担，不另立 feature。
6. ✅ **`change_type` 认可 feature**：主体是新增 CI step / 新依赖事实源 / 新 `make ci-local` 能力，旧测试清理 / ruff 清债是支撑项；保留 meta.yaml `change_type: feature`（来源：requirements/REQ-2026-012/meta.yaml:17）。
7. ✅ **经验沉淀新增**：在 `context/team/experience/` 创建 `test-assets-must-be-wired-into-ci.md`（与 `auto-generated-artifact-needs-pre-commit-not-just-ci.md` 并列、不归并），问题域为「测试资产创建后必须接入执行入口」。
8. ✅ **routing yaml 路径事实修正**：实际为 `.claude/code-review-routing.yaml`，**不是** `scripts/lib/routing.yaml`（来源：.claude/code-review-routing.yaml）；场景 1 前置及引用源汇总已同步。

## 引用源汇总

- .github/workflows/quality-check.yml — 当前 CI workflow 全貌
- .github/workflows/quality-check.yml:34 — `pip install` 字面量现状
- .github/workflows/quality-check.yml:36 — bats `apt-get install` 现位置
- .github/workflows/quality-check.yml:57 — `pytest --ignore=tests/benchmarks/` 现位置
- .github/workflows/quality-check.yml:82 — ruff 现范围 `scripts/`
- .github/workflows/quality-check.yml:7 — 触发条件 `pull_request` + `push [main, develop]`
- tests/lib/test_routing_e2e.sh:1 — routing e2e shell 测试存在但未入 CI
- tests/lib/test_routing_e2e.sh:21 — 临时 git 仓库构建 + Python import 路径
- .claude/hooks/tests/test_protect-branch.sh:4 — 指向已删除 `.claude/hooks/protect-branch.sh`
- .claude/hooks/pre-tool-use-guard.sh:101 — Edit/Write/MultiEdit 分支保护逻辑现位置
- tests/hooks/test_pre_tool_use_guard.bats:39 — bats V-01 三分支阻断 / reviews 写保护 / 14 类 Bash redirect 覆盖
- .claude/code-review-routing.yaml — routing yaml 实际路径（修正：不是 scripts/lib/routing.yaml）
- pyproject.toml:11 — ruff 配置 `select=["F"]` / `line-length=120`
- pyproject.toml:1 — 仅 tool 配置，无 `[project]` 表
- Makefile:1 — 现有入口仅 `gates-validate` / `gates-render`
- context/team/onboarding/learning-path/01-environment.md:25 — onboarding 单条 `pip install pyyaml`
- context/team/experience/auto-generated-artifact-needs-pre-commit-not-just-ci.md:7 — 派生产物 CI 兜底经验（与新增 `test-assets-must-be-wired-into-ci.md` 并列）
