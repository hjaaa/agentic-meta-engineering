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
2. **旧 hook 测试指向已删除文件**：.claude/hooks/tests/test_protect-branch.sh:4 仍指向 .claude/hooks/protect-branch.sh，而该文件在仓库中已不存在 [待补充：内容 = 仓库根 ls 该路径返回 MISSING；依据 = 本次 bootstrap 阶段预检命令结果；风险 = 若 hook 路径在未来复活，本陈述失效；验证时机 = tech-research 阶段开篇与每次 PR 触发前各复跑一次]；该分支保护逻辑现已搬到 pre-tool-use-guard.sh 的 Edit/Write/MultiEdit 分支，调用 check_branch_protect 函数（来源：.claude/hooks/pre-tool-use-guard.sh:101）。
3. **依赖来源与 onboarding 漂移**：workflow 安装 pyyaml / ruamel.yaml / pathspec>=0.12,<1.0 / ruff / pytest（来源：.github/workflows/quality-check.yml:34），但 onboarding 文档只让新人装单个 pyyaml（来源：context/team/onboarding/learning-path/01-environment.md:25），且仓库内既无 requirements/ci.txt 也无 pyproject.toml `[optional-dependencies]` 把 CI/test 依赖固化下来。
4. **ruff 范围与剩余 F 债脱钩**：CI 仅 lint scripts/ 目录（来源：.github/workflows/quality-check.yml:82），ruff 配置为 select = ["F"] / line-length = 120（来源：pyproject.toml:11）。用户报告本地跑 `ruff check scripts tests --select=F` 在 tests/ 目录还有约 95 条 F 类问题 [待用户确认及在 CI 同版本 ruff 下复验] —— 若现在直接把 tests/ 纳入 lint 范围，CI 会立刻变红。
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
- **前置**：`scripts/lib/code_review_routing.py` 或 `scripts/lib/routing.yaml`（[待用户确认：实际 routing yaml 路径] —— `test_routing_e2e.sh` 内部以 `REPO_ROOT/scripts/lib/code_review_routing` 为 import 路径，对应的 yaml 路径在脚本中实际探查）发生变更
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

- **性能**：`make ci-local` 整体执行时间不应显著长于现有 CI workflow 的 wall time（`hyperfine` step 例外，本身就慢 [待用户确认是否纳入 `ci-local` 默认序列]）。
- **可维护性**：CI 依赖清单与本地依赖清单必须**单一事实源**——`.github/workflows/quality-check.yml` 不再直接写 `pip install pyyaml ...` 字面量，而是引用 `requirements/ci.txt` 或 `pyproject [optional-dependencies]`（具体选哪种见决策记录 D-001 占位）。
- **兼容性**：本次改动不破坏现有 .github/workflows/quality-check.yml 的触发条件 pull_request + push [main, develop]（来源：.github/workflows/quality-check.yml:7）和 step 顺序语义。
- **可回滚性**：6 个候选 feature（plan.md F-A ~ F-F）每个独立可回滚——单 PR + 单 commit 主体；尤其 F-D 清债 PR 必须可单独 revert 而不让 F-E 失效。
- **安全/合规**：不引入新的密钥、不修改 CI 触发的 secret 来源；新依赖清单必须固定版本范围（如 `pathspec>=0.12,<1.0` 这种形式），不允许 `latest`。

## 范围

- **包含**：
  1. `.github/workflows/quality-check.yml` 新增一个 step：`bash tests/lib/test_routing_e2e.sh`
  2. 处理 `.claude/hooks/tests/test_protect-branch.sh`：选项 A 改为针对 `.claude/hooks/pre-tool-use-guard.sh:101` 等价逻辑的测试；选项 B 直接删除并在 notes 记录原因（决策点 D-002 占位）；同步检查 `.claude/hooks/tests/test_protect-reviews.sh` 是否有同类陈旧引用
  3. 新建 `requirements/ci.txt` 或在 `pyproject.toml` 增加 `[project.optional-dependencies]` 表（决策点 D-001 占位）；workflow 与 onboarding 都改为引用同一份
  4. 清理 `scripts/` + `tests/` 的 ruff F 类问题至 0 条；同步把 `.github/workflows/quality-check.yml:82` 的 `ruff check scripts/ --select=F` 改为 `ruff check scripts tests --select=F`
  5. `Makefile` 新增 `ci-local` target：按 workflow step 顺序串行跑 gate runner / pytest / bats / hook 引用检查 / ruff / render check / routing e2e；非零退出即终止
  6. 同步更新 `context/team/onboarding/learning-path/01-environment.md`，把单条 `pip install pyyaml` 改为引用同一份依赖清单
  7. 在 `context/team/experience/` 评估是否需要追加一条「shell e2e 测试默认进 CI」的经验（[待用户确认是否值得沉淀 / 是否归并入 `auto-generated-artifact-needs-pre-commit-not-just-ci.md`]）

- **不包含**：
  - 切换 CI 平台、改触发条件、改 runner image 版本
  - 把 ruff `select` 扩到 `F` 之外（`E` / `W` / `E501` 等独立 PR / 独立需求）
  - 写任何新的业务测试用例
  - 把 `hyperfine` 等性能基准测试改成 CI 强校验（保留 best-effort 语义）
  - 重构 `.claude/hooks/pre-tool-use-guard.sh` 的内部结构

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| D-001 CI/test 依赖清单的事实源 | A. `requirements/ci.txt`；B. `pyproject.toml [project.optional-dependencies]` 加 `ci` / `test` extras | [待用户确认] | A 简单直观、对纯 Python 之外的工具（`bats` 之类）天然不冲突；B 与现代 Python 包管理统一，但本仓库当前 pyproject.toml 只配 ruff/pytest，没有 `[project]` 表（来源：pyproject.toml:1） |
| D-002 旧 hook shell 测试处理方式 | A. 全删除 + notes 解释；B. 迁移到 `pre-tool-use-guard.sh:101` 等价逻辑的测试 | [待用户确认] | 当前 `pre-tool-use-guard.sh` 的分支保护逻辑已有 bats 覆盖与否需 grep 验证（[待补充：跑 `grep -r "check_branch_protect\|protect-branch" tests/`] —— 若 bats 已覆盖则 A 优；若没有则 B 必须 |
| D-003 ruff 清债拆分粒度 | A. 单 PR 一次清完；B. 按子目录拆多个 PR | [待用户确认] | 用户报告基线 ≈ 95 条，但未拆解 import 重排 vs unused 类型；若 F821 跨文件多，B 更安全 |
| D-004 `make ci-local` 对慢 step 的处理 | A. 全跑（含 hyperfine / bench）；B. 默认跳过 hyperfine 类，提供 `make ci-local-full` 兜底 | [待用户确认] | 经验沉淀 `auto-generated-artifact-needs-pre-commit-not-just-ci.md:7` 倾向"本地校验必须能日常跑"，倾向 B；但语义偏离 CI 镜像，需用户拍板 |

## 验收标准（AC）

- **AC-1（routing e2e 入 CI）**：在 PR 触发的 `quality-check` workflow 日志中可见 `bash tests/lib/test_routing_e2e.sh` 这一 step，且输出包含 `PASS=3 FAIL=0`；本地 `make ci-local` 同 step 退出码 = 0
- **AC-2（旧 hook 测试不再红）**：`.claude/hooks/tests/test_protect-branch.sh`（及 `test_protect-reviews.sh`）要么已迁移为引用现存文件、要么物理删除并在 `.claude/hooks/tests/` 目录中无残留；`bats tests/hooks/` 与上述 shell 测试均 0 失败
- **AC-3（依赖单一事实源）**：`.github/workflows/quality-check.yml` 不再出现 `pip install pyyaml ruamel.yaml ...` 字面量列表；改为 `pip install -r requirements/ci.txt`（或 `pip install -e ".[ci]"`，视 D-001）；`context/team/onboarding/learning-path/01-environment.md:25` 指向同一份清单
- **AC-4（ruff F 清债 → 0）**：`ruff check scripts tests --select=F` 本地与 CI 均退出 0；`.github/workflows/quality-check.yml:82` 改为 `ruff check scripts tests --select=F`
- **AC-5（`make ci-local`）**：在 clean checkout 后跑 `make ci-local` 退出 0 = 等价于 CI `quality-check` job 全过；途中任一 step fail → make 退非 0 + 明确指明失败 step
- **AC-6（不破坏既有触发）**：`.github/workflows/quality-check.yml` 触发条件、runner image、env 注入均未变；diff 限于 install / ruff range / 新 step
- **AC-7（可回滚）**：6 个 feature 各自的 PR 单独 revert 后 CI 仍能跑通（即不存在「revert F-D 后 F-E 立刻红」这种隐性依赖未声明）

## 待澄清清单

> 以下条目在 definition 阶段或 tech-research 阶段闭环；不闭环不进入 outline-design。

1. **D-001 选哪个**：`requirements/ci.txt` 还是 `pyproject.toml [optional-dependencies]`？倾向？是否允许把 `bats` / `hyperfine` 这种非 Python 工具也写进同一份清单（注释 + apt-get 安装段）？
2. **D-002 选哪个**：把旧 `test_protect-branch.sh` / `test_protect-reviews.sh` 迁移到 `pre-tool-use-guard.sh` 的等价 bats 测试，还是直接删？现有 `tests/hooks/` 下是否已经覆盖 `check_branch_protect` 的等价场景？[待补充：跑 `grep -r "check_branch_protect" tests/`]
3. **D-003 工作量预估**：用户报告本地基线 ≈ 95 条 F 类问题，能否给一份拆解（unused-import / unused-var / F821 分别多少）？或在 tech-research 阶段由 AI 自己跑 `ruff check scripts tests --select=F --output-format=json | jq` 给出分布？
4. **D-004 `ci-local` 默认行为**：是否包含 `hyperfine` step？包含会让"日常 push 前跑一遍"变慢；不包含则与 CI 不完全镜像。
5. **routing e2e 在 CI runner 上的依赖**：脚本里用了 mktemp + git init + Python import 路径（来源：tests/lib/test_routing_e2e.sh:21）。CI Ubuntu image 默认有 git / bash / python3.11，但需要确认 `python -m scripts.lib.code_review_routing` 在 CI 工作目录下能正确 import [待补充：内容 = 在 ubuntu-latest runner 上跑 routing e2e 的实际退出码；依据 = 本地 PASS=3 FAIL=0 不必然在 CI 复现，因 PATH / locale 可能不同；风险 = 入 CI 当天直接红；验证时机 = F-A 实施时先在草稿 PR 上单 step 触发]。
6. **`change_type` 选择**：本次主体是新增 CI step / 新依赖清单 / 新 make target（feature 性），但也含旧测试清理（refactor 性）；当前 meta.yaml 写 feature（来源：requirements/REQ-2026-012/meta.yaml:17），用户是否认可？
7. **经验沉淀对接**：是否要在 `context/team/experience/` 加一条「外溢测试 / 派生产物默认进 CI」的轻经验，还是直接归并进 `auto-generated-artifact-needs-pre-commit-not-just-ci.md`？

## 引用源汇总

- `.github/workflows/quality-check.yml:14`-`88` — 当前 CI step 全貌
- `.github/workflows/quality-check.yml:34` — `pip install` 现状
- `.github/workflows/quality-check.yml:82` — ruff 现范围
- `tests/lib/test_routing_e2e.sh:1` — routing e2e shell 测试存在但未入 CI
- `.claude/hooks/tests/test_protect-branch.sh:4` — 指向已删除 `.claude/hooks/protect-branch.sh`
- `.claude/hooks/pre-tool-use-guard.sh:101` — Edit/Write/MultiEdit 分支保护逻辑现位置
- `pyproject.toml:11`-`15` — ruff 配置 `select=["F"]` / `line-length=120`
- `Makefile:1`-`9` — 现有入口仅 `gates-validate` / `gates-render`
- `context/team/onboarding/learning-path/01-environment.md:25` — onboarding `pip install pyyaml`
- `context/team/experience/auto-generated-artifact-needs-pre-commit-not-just-ci.md:7` — 本地校验缺失的经验沉淀
