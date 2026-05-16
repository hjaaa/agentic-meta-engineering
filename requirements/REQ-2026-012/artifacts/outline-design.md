---
id: REQ-2026-012
phase: outline-design
title: "CI 工程化补强 · 概要设计"
created_at: 2026-05-16 21:25:00
refs-outline-design: true
inputs:
  - requirements/REQ-2026-012/artifacts/requirement.md
  - requirements/REQ-2026-012/artifacts/tech-feasibility.md
  - requirements/REQ-2026-012/plan.md
---

# REQ-2026-012 · 概要设计

> 仅覆盖**模块边界 / 模块间契约 / 技术选型 / 关键流程时序**。接口签名 / 数据结构 / Makefile 完整内容 / step-name 命名表归 detail-design 阶段。

## 1. 设计目标与约束回顾

回应 requirement.md 的 8 条 AC（来源：requirements/REQ-2026-012/artifacts/requirement.md）+ plan.md 的 9 条 ADR（D-001~D-009，来源：requirements/REQ-2026-012/plan.md）：

- AC-1 routing e2e 入 CI step；AC-2 旧 hook shell 测试清零；AC-3 依赖单一事实源；AC-4 ruff F 类清零 + 范围扩到 `scripts tests`；AC-5 `make ci-local` 镜像 CI 并支持 `FAIL: <step-name>` 自动断言；AC-6 触发条件不变；AC-7 7 feature 独立可回滚；AC-8 经验沉淀 `test-assets-must-be-wired-into-ci.md` 就位。
- 设计约束：不引入 Python 包管理重构（D-001+D-007）；ruff 拆 3 PR 推进（D-003）；草稿 PR 验证 Ubuntu runner（D-005）；step-name 命名留 detail-design 同步出表（D-009）。

## 2. 整体架构

### 2.1 模块视图

```
┌──────────────────────────────── CI 触发层 ─────────────────────────────────┐
│ .github/workflows/quality-check.yml                                       │
│   on: pull_request + push: [main, develop]    (触发条件不变 D-001)         │
│   steps: 9 个串行 step（含本次新增的 routing-e2e）                          │
└────────┬────────────┬─────────────┬─────────────┬──────────────────────────┘
         │            │             │             │
         ▼            ▼             ▼             ▼
   pip install -r   ruff check   pytest         bash tests/lib/
   requirements/    scripts      tests/         test_routing_e2e.sh
   ci.txt           tests        --ignore=      (F-A 新增)
   (F-C 新建)        (F-E 扩范围) benchmarks
         │            │
         │            └── 依赖 ─→  pyproject.toml [tool.ruff.lint]
         │                          select = ["F"]   (不动 D-008)
         ▼
   非 Python 工具：apt-get bats / hyperfine   (workflow yml 内保留)

┌──────────────────────────── 本地镜像入口层 ────────────────────────────────┐
│ Makefile     新增 ci-local + 8 个 ci-local-* 子 target                     │
│              每个子 target 失败时 stderr 末段写 `FAIL: <step-name>`        │
│              (step-name 表留 detail-design 同步定稿 D-009)                  │
└─────┬───────────┬────────────┬────────────┬──────────────────────────────┘
      │           │            │            │
      ▼           ▼            ▼            ▼
  workflow      ruff          pytest       routing-e2e
  同 step      同范围        同 ignore     同脚本
      ↑           ↑            ↑            ↑
      └───────────┴────────────┴────────────┘
             同源（消费同一份 requirements/ci.txt + pyproject.toml + .yml）

┌──────────────────────────── 测试资产层 ──────────────────────────────────┐
│ tests/lib/test_routing_e2e.sh         (F-A 入 CI)                       │
│ tests/hooks/test_pre_tool_use_guard.bats  (覆盖 V-01/V-03 + 14 redirect)│
│ .claude/hooks/tests/test_protect-branch.sh   (F-B 删除)                  │
│ .claude/hooks/tests/test_protect-reviews.sh  (F-B 删除)                  │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────── 经验沉淀层 ──────────────────────────────────┐
│ context/team/experience/test-assets-must-be-wired-into-ci.md             │
│   (F-F 落地后由 /knowledge:extract-experience 触发；新增并挂 INDEX.md)    │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.2 模块清单（PR 拆分对应）

| 模块 | 物理位置 | 本次改动 | 关联 feature |
|---|---|---|---|
| CI workflow | .github/workflows/quality-check.yml | 改 `pip install` 行；改 `ruff check` 范围；加 routing-e2e step | F-A / F-C / F-E |
| 依赖事实源 | requirements/ci.txt（新建） | 新建 5 行清单 | F-C |
| ruff 配置 | pyproject.toml | 不改（D-008 决议） | F-E（消费方） |
| Makefile | Makefile | 新增 ci-local + 8 个子 target | F-F |
| Hook 测试 | .claude/hooks/tests/ | 删 2 文件 | F-B |
| 业务测试 | tests/lib/ + tests/lifecycle/ | 4 处 import 补 + 89 处机械清理 | F-D1 / F-D2 |
| Onboarding | context/team/onboarding/learning-path/01-environment.md | 改 `pip install` 行 | F-C |
| 经验沉淀 | context/team/experience/test-assets-must-be-wired-into-ci.md | 新建 | F-F 收尾 |

## 3. 模块详细设计（概要）

### 3.1 CI workflow（.github/workflows/quality-check.yml）

**改动点**：
- step 4 `Install dependencies`（来源：.github/workflows/quality-check.yml:33）：`pip install pyyaml ruamel.yaml "pathspec>=0.12,<1.0" ruff pytest` → `pip install -r requirements/ci.txt`
- step 末加 `Run routing e2e shell tests`：`bash tests/lib/test_routing_e2e.sh`
- step `ruff lint`（来源：.github/workflows/quality-check.yml:82）：`ruff check scripts/ --select=F` → `ruff check scripts tests --select=F`

**不动**：触发条件、runner 镜像、git config 段、bats 安装段、hyperfine 安装段、pytest step、settings.json hook 引用检查 step、gate-checklist 同步 step。

**契约**：workflow 不感知 ci.txt 的内容形态，只通过 `pip install -r` 间接消费；ruff 不感知扩范围的具体目录，只读 CLI 参数。模块边界清晰。

### 3.2 依赖事实源（requirements/ci.txt）

**草案**（最终内容由 detail-design 阶段微调）：
```
pyyaml
ruamel.yaml
pathspec>=0.12,<1.0
ruff
pytest
```

**契约**：CI workflow + onboarding 文档 + `make ci-local-deps` 三方都通过 `pip install -r requirements/ci.txt` 消费；非 Python 工具（bats / hyperfine）不进此文件，由 apt-get / brew 通过 workflow yml + onboarding 文档独立说明（D-001）。

### 3.3 Makefile

**新增 target 树**（命名表留 detail-design 同步出，D-009）：
```
ci-local：聚合 target，按 workflow step 顺序串行依赖 8 个子 target
├── ci-local-deps          → pip install -r requirements/ci.txt
├── ci-local-gates         → python3 scripts/gates/run.py --trigger=ci --strict
├── ci-local-pytest        → pytest tests/ --ignore=tests/benchmarks/
├── ci-local-settings-check → 复用 workflow yml 中的 Python 内联校验
├── ci-local-bats          → bats tests/hooks/
├── ci-local-ruff          → ruff check scripts tests --select=F
├── ci-local-render-check  → python3 scripts/gates/migration/render-docs.py --check
└── ci-local-routing-e2e   → bash tests/lib/test_routing_e2e.sh
```

**FAIL 断言契约**：每个子 target 失败时 stderr 末段写一行 `FAIL: <step-name>`；`make ci-local 2>&1 | grep -E '^FAIL: '` 自动断言失败 step（AC-5）。step-name 列表在 detail-design 阶段固定为 Makefile 顶部的 `# FAIL labels:` 注释表，作为 contract 来源。

**跨平台依赖**：bats / hyperfine 在 macOS 用 `brew`，Ubuntu 用 `apt-get`；Makefile 不替开发者安装，子 target 启动前若命令缺失直接 fail 并提示 `brew install ...` / `apt-get install ...`。

### 3.4 测试资产层

- **F-A 新增**：`bash tests/lib/test_routing_e2e.sh` 入 CI step；脚本本身不动；草稿 PR 验证 Ubuntu runner 行为后再合入正式 step（D-005）。
- **F-B 删除**：`.claude/hooks/tests/test_protect-branch.sh` + `.claude/hooks/tests/test_protect-reviews.sh`；不补任何 bats（D-006）。
- **F-D1 机械清理**：89 处 F401 / F841 / F541，通过 `ruff check --fix` + 手工 review 完成；范围限 `tests/`（scripts/ 已 0 条）。
- **F-D2 语义清理**：4 处 F821 集中在 tests/lib/test_code_review_routing.py:396 / tests/lib/test_code_review_routing.py:732 / tests/lifecycle/test_submit_codex.py:744 / tests/lifecycle/test_submit_codex.py:790，仅补 typing import。

### 3.5 Onboarding（context/team/onboarding/learning-path/01-environment.md）

**改动**：单条 `pip install pyyaml`（来源：context/team/onboarding/learning-path/01-environment.md:25）改为 `pip install -r requirements/ci.txt`，并加一段"系统级依赖"说明：macOS `brew install bats-core hyperfine`、Ubuntu `apt-get install bats hyperfine`。

**契约**：onboarding 不重复列依赖名，永远指向 `requirements/ci.txt` 作为事实源。

### 3.6 经验沉淀（context/team/experience/test-assets-must-be-wired-into-ci.md）

**触发时机**：testing 阶段全部 PR 合入后，由 `/knowledge:extract-experience` 触发新增；不作为某个 F-* 任务的内置交付物，单独走经验沉淀流程。

**结构（草案）**：触发场景（shell / e2e / contract 测试创建）→ 原则（新增测试默认进 CI；不进 CI 必须说明原因 + 手跑命令）→ 反面案例引用本需求 F-A 经历。

**与 INDEX 联动**：新建后必须挂入 `context/team/experience/INDEX.md`（CI 门禁强制，来源：scripts/gates/plugins）。

## 4. 关键流程时序

### 4.1 `make ci-local` 调用链

```
开发者                Makefile             子 target          底层工具
   │                    │                     │                  │
   │  make ci-local     │                     │                  │
   │ ─────────────────► │                     │                  │
   │                    │ depends-on:         │                  │
   │                    │  ci-local-deps      │                  │
   │                    │ ──────────────────► │  pip install -r  │
   │                    │                     │ ──────────────► │ pip
   │                    │                     │  ◄────── OK ──── │
   │                    │  ci-local-gates     │                  │
   │                    │ ──────────────────► │  python3 ...     │
   │                    │                     │ ──────────────► │ gates runner
   │                    │       ...           │                  │
   │                    │  ci-local-routing-e2e                  │
   │                    │ ──────────────────► │  bash tests/lib  │
   │                    │                     │ ──────────────► │ shell e2e
   │                    │                     │                  │
   │  exit 0            │                     │                  │
   │ ◄──────────────────│                     │                  │
   │                                                              │
   │  [若任一子 target 失败]                                       │
   │  stderr 末段：FAIL: <step-name>                              │
   │  exit !=0                                                    │
```

### 4.2 F-A 草稿 PR 验证流程（D-005）

```
本地                       feat/req-2026-012             GitHub Actions
   │  改 workflow yml          │                                │
   │  bash tests/lib/...       │  push                          │
   │ ────────────────────────► │ ─────────────────────────────► │
   │                           │                                │  workflow 跑
   │  gh pr create --draft     │                                │  仅 routing-e2e
   │  --base develop           │                                │  step
   │ ────────────────────────► │                                │
   │                           │                                │  ✓ PASS=3 FAIL=0
   │                           │                                │  → 合入正式 step
   │                           │                                │  ✗ 失败
   │                           │                                │  → 调整后 reuse
   │                           │                                │     同分支推送
```

## 5. 技术选型 / ADR 回顾

| ADR | 选型结论 | 影响模块 |
|---|---|---|
| D-001 / D-007 | 依赖事实源用 `requirements/ci.txt`，不锁版本 | 依赖事实源 / CI workflow / Onboarding |
| D-002 / D-006 | 旧 hook shell 测试全删，不补 Read fail-open bats | 测试资产层（Hook 测试） |
| D-003 | ruff F 类按风险拆 F-D1 / F-D2 / F-E 共 3 个 PR | 测试资产层 / CI workflow |
| D-004 | `make ci-local` 默认镜像 CI 含 hyperfine，不跑 benchmarks | 本地镜像入口层（Makefile） |
| D-005 | F-A 入 CI 前先用草稿 PR 单 step 验证 Ubuntu runner | CI workflow + 流程 |
| D-008 | F-E 扩范围不加 `extend-exclude`（benchmarks 实测 0 条） | ruff 配置 |
| D-009 | Makefile step-name 命名表留 detail-design 同步出 | 本地镜像入口层（Makefile） |

## 6. 风险与回滚策略

| 风险 ID | 关联模块 | 回滚动作 |
|---|---|---|
| R-1 routing.py 私有 API 重构破坏 e2e | CI workflow / 测试资产层 | revert F-A 提交即可恢复原 workflow，不影响其它 step |
| R-2 ci.txt 切换后本地依赖膨胀 | 依赖事实源 / Onboarding | revert F-C；workflow 与 onboarding 同步回到字面量 |
| R-3 F401 自动删 import 误伤 re-export | 测试资产层 | revert F-D1 PR；F-D2 / F-E 因依赖顺序自动 stall |
| R-4 F-D2 F821 与 routing.py 真重命名 | 测试资产层 | revert F-D2，留 F-D1 成果 |
| R-5 benchmarks 未来加新文件触发 F 类 | ruff 配置 | 良性信号，按 D-008 设计语义不需回滚 |
| R-6 make ci-local 本地 wall time 过长 | 本地镜像入口层 | 单独开 ci-fast target；不需要 revert F-F |
| R-7 Ubuntu routing-e2e 行为分歧 | CI workflow / 测试资产层 | 草稿 PR 拦截，不进入正式 PR |

**整体回滚原则**：7 个 feature 各自独立 PR，逆序 revert 可线性回到 develop 当前状态；不存在跨 feature 的隐性数据迁移或不可逆配置变更。

## 7. detail-design 阶段后续动作

- 输出 `artifacts/detailed-design.md`：Makefile 完整内容 + step-name 命名表（D-009 兑现）；ci.txt 最终行；workflow yml diff；每个 feature 的 AC 细化到可机器断言；test-assets-must-be-wired-into-ci.md 完整内容。
- 输出 `artifacts/features.json`：F-A / F-B / F-C / F-D1 / F-D2 / F-E / F-F 7 项 + 各自 `touches[]` + AC 引用 + 依赖关系。
- 输出 `tasks/F-*.md`：每个 feature 一份 task frontmatter（含 `touches`）。

## 8. 引用源汇总

- requirements/REQ-2026-012/artifacts/requirement.md — 需求文档（含 AC-1~AC-8）
- requirements/REQ-2026-012/artifacts/tech-feasibility.md — 技术可行性（含 R-1~R-7 / 4.0 人时）
- requirements/REQ-2026-012/plan.md — D-001~D-009 ADR
- .github/workflows/quality-check.yml — CI workflow 入口
- .github/workflows/quality-check.yml:33 — Install dependencies step
- .github/workflows/quality-check.yml:82 — ruff lint step
- pyproject.toml:11 — ruff 配置入口
- Makefile:4 — 现有 target 列表
- tests/lib/test_routing_e2e.sh — routing e2e 测试
- tests/lib/test_code_review_routing.py:396 — F821 RoutingPlan 位置 1
- tests/lib/test_code_review_routing.py:732 — F821 RoutingPlan 位置 2
- tests/lifecycle/test_submit_codex.py:744 — F821 Any 位置 1
- tests/lifecycle/test_submit_codex.py:790 — F821 Any 位置 2
- tests/hooks/test_pre_tool_use_guard.bats:39 — bats V-01 / V-03 + 14 redirect 覆盖
- context/team/onboarding/learning-path/01-environment.md:25 — 现有 onboarding pip 指令
