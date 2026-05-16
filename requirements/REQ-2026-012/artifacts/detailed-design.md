---
id: REQ-2026-012
phase: detail-design
title: "CI 工程化补强 · 详细设计"
created_at: 2026-05-16 21:35:00
refs-detail-design: true
inputs:
  - requirements/REQ-2026-012/artifacts/requirement.md
  - requirements/REQ-2026-012/artifacts/tech-feasibility.md
  - requirements/REQ-2026-012/artifacts/outline-design.md
  - requirements/REQ-2026-012/plan.md
---

# REQ-2026-012 · 详细设计

> 落实到接口签名 / 文件级 diff / Makefile 完整内容 / AC 机器断言 / experience.md 全文 / hyperfine 二选一定稿。features.json + tasks/F-*.md 在同一阶段同步出。

## 1. 编号映射（plan.md 字母编号 → features.json 数字编号）

上游 plan.md / requirement.md / outline-design.md / tech-feasibility.md 已 signoff，沿用 F-A~F-F 字母编号；本阶段 features.json + tasks/ 切到 schema 要求的数字编号：

| plan.md | features.json | 名称 |
|---|---|---|
| F-A | F-001 | tests/lib/test_routing_e2e.sh 入 CI |
| F-B | F-002 | 删两个旧 hook shell 测试 |
| F-C | F-003 | requirements/ci.txt 同源化 CI/test pip 清单 |
| F-D1 | F-004 | ruff F 类机械清理（89 处） |
| F-D2 | F-005 | ruff F 类语义清理（4 处 F821） |
| F-E | F-006 | CI ruff 范围扩到 scripts + tests |
| F-F | F-007 | make ci-local 入口 + experience.md 沉淀 |

## 2. 文件级 diff 设计

### 2.1 requirements/ci.txt（F-003 新建）

完整内容：

```
# REQ-2026-012 F-003：CI / 本地共享的 Python 依赖清单
# 非 Python 工具 (bats / hyperfine) 由 workflow apt-get + onboarding 文档说明
pyyaml
ruamel.yaml
pathspec>=0.12,<1.0
ruff
pytest
```

**版本约束**：仅 pathspec 保留 `>=0.12,<1.0` 现行范围（来源：.github/workflows/quality-check.yml:34）；其它包不锁版本（D-007）。

### 2.2 .github/workflows/quality-check.yml（F-001 / F-003 / F-006）

精确 3 处改动：

**改动 A**（F-003，行 33-34 区域）：
```diff
-      - name: Install dependencies
-        run: pip install pyyaml ruamel.yaml "pathspec>=0.12,<1.0" ruff pytest
+      - name: Install dependencies
+        run: pip install -r requirements/ci.txt
```

**改动 B**（F-006，行 82 区域）：
```diff
-      - name: ruff lint
-        run: ruff check scripts/ --select=F
+      - name: ruff lint
+        run: ruff check scripts tests --select=F
```

**改动 C**（F-001，行 87 之后追加新 step）：
```yaml
      - name: Run routing e2e shell tests
        run: bash tests/lib/test_routing_e2e.sh
```

step 顺序：放在 `Check gate-checklist.md is in sync with registry` step 之后（来源：.github/workflows/quality-check.yml:87），workflow 末尾；与现有 bats / pytest 同属"测试"段，独立 step 便于失败定位。

**不动**：触发条件（line 7-12）/ runner image / git config 段（line 28）/ bats 安装段（line 36）/ hyperfine 安装段（line 42）/ Verify settings.json hook references step / bats step / pytest step / render check step。

### 2.3 Makefile（F-007 新增 8 子 target + 顶部 FAIL labels 表）

文件末尾追加（保留现有 `gates-validate` / `gates-render`）：

```makefile
# ============ ci-local：本地镜像 CI 入口（F-007 / D-004 D-009）============
#
# FAIL labels（detail-design 同步出表，与下方子 target 名 1:1；
# 任一子 target 失败时 stderr 末段写一行 `FAIL: <label>`，AC-5 自动断言模式
# `make ci-local 2>&1 | grep -E '^FAIL: '` 依赖此契约）：
#
#   ci-local-deps           ci-local-pytest         ci-local-bats
#   ci-local-gates          ci-local-settings-check ci-local-ruff
#   ci-local-render-check   ci-local-routing-e2e
#
# hyperfine 路径：嵌在 ci-local-bats 内由 bats V-06 触发，不单独立 target
# （D-008 二选一兜底：若 V-06 实际不跑 hyperfine 则补 ci-local-hyperfine）。
# benchmarks 目录：与 CI 一致由 pytest --ignore=tests/benchmarks/ 跳过。

.PHONY: ci-local ci-local-deps ci-local-gates ci-local-pytest \
        ci-local-settings-check ci-local-bats ci-local-ruff \
        ci-local-render-check ci-local-routing-e2e

ci-local: ci-local-deps ci-local-gates ci-local-pytest \
          ci-local-settings-check ci-local-bats ci-local-ruff \
          ci-local-render-check ci-local-routing-e2e
	@echo "ci-local: ALL PASS"

ci-local-deps:
	@pip install -r requirements/ci.txt \
	  || { echo "FAIL: ci-local-deps" >&2; exit 1; }

ci-local-gates:
	@python3 scripts/gates/run.py --trigger=ci --strict \
	  || { echo "FAIL: ci-local-gates" >&2; exit 1; }

ci-local-pytest:
	@pytest tests/ --ignore=tests/benchmarks/ -v \
	  || { echo "FAIL: ci-local-pytest" >&2; exit 1; }

ci-local-settings-check:
	@python3 -c "import json, os, sys; \
	  s = json.load(open('.claude/settings.json')); \
	  missing = [f'{evt}: {h[\"command\"]}' for evt, hooks in s.get('hooks', {}).items() \
	    for hg in hooks for h in hg.get('hooks', []) \
	    if h.get('command') and not os.path.isfile(h['command'])]; \
	  sys.exit(1 if missing else 0)" \
	  || { echo "FAIL: ci-local-settings-check" >&2; exit 1; }

ci-local-bats:
	@command -v bats >/dev/null \
	  || { echo "FAIL: ci-local-bats (bats missing; brew install bats-core / apt-get install bats)" >&2; exit 1; }
	@bats tests/hooks/ \
	  || { echo "FAIL: ci-local-bats" >&2; exit 1; }

ci-local-ruff:
	@ruff check scripts tests --select=F \
	  || { echo "FAIL: ci-local-ruff" >&2; exit 1; }

ci-local-render-check:
	@python3 scripts/gates/migration/render-docs.py --check \
	  || { echo "FAIL: ci-local-render-check" >&2; exit 1; }

ci-local-routing-e2e:
	@bash tests/lib/test_routing_e2e.sh \
	  || { echo "FAIL: ci-local-routing-e2e" >&2; exit 1; }
```

**契约**：
- `ci-local` 是聚合 target，按 workflow step 顺序声明 prerequisite，串行依赖；任一子 target fail → make 立即停止。
- 每个子 target 失败路径用 `|| { echo "FAIL: <label>" >&2; exit 1; }` 模板；`<label>` 与 target 名 1:1。
- `ci-local-bats` 在跑 bats 前先 `command -v bats` 检测命令缺失，提示 `brew install` / `apt-get install`，避免开发者排查工具不存在。
- `ci-local-settings-check` 把 workflow yml 中的内联 Python 校验脚本（来源：.github/workflows/quality-check.yml）原样移到 Makefile（避免引入新文件）。

### 2.4 .claude/hooks/tests/（F-002 删除）

**操作**：`git rm .claude/hooks/tests/test_protect-branch.sh .claude/hooks/tests/test_protect-reviews.sh`。

**目录处理**：删后 `.claude/hooks/tests/` 变空。检查目录是否仅这两个文件；若是，整目录 `git rm -r .claude/hooks/tests/`。

**不补 bats**（D-006）。

### 2.5 tests/lifecycle/test_submit_codex.py（F-005）

**改动**：文件顶部 import 区追加 `from typing import Any`（若已有 `from typing import` 行则合并）。

**预期效果**：行 744 / 行 790 的 `Any` 类型注解不再报 F821。

### 2.6 tests/lib/test_code_review_routing.py（F-005）

**改动**：文件顶部 import 区追加 `from scripts.lib.code_review_routing import RoutingPlan`（若已有 `from scripts.lib.code_review_routing import ...` 行则合并）。

**前置验证**（detail-design 实施前必跑）：`grep -n "class RoutingPlan\|^RoutingPlan" scripts/lib/code_review_routing.py` 确认类名仍是 `RoutingPlan`（来源：tests/lib/test_code_review_routing.py:396）。若 routing.py 重构后类名已改，对应修复 import 名。

**预期效果**：行 396 / 行 732 不再报 F821。

### 2.7 tests/* 89 处 F401 / F841 / F541（F-004）

**自动修复路径**：`ruff check scripts tests --select=F401,F541 --fix` 一键修 68 条；剩余 21 条 F841 用 `ruff check ... --select=F841 --fix` 部分自动 + 手工 review（部分 F841 可能是"故意保留 debug 用变量"，需逐条判断）。

**分布固化**（来源：requirements/REQ-2026-012/plan.md）：
- tests/lib/ 35 / tests/gates/ 28 / tests/e2e/ 9 / tests/integration/ 7 / tests/skills/ 6 / tests/lifecycle/ 5 / tests/agents/ 2 / tests/hooks/ 2 / tests/workflows/ 1

**清债后断言**：`ruff check scripts tests --select=F` 退码 0；`pytest tests/ --ignore=tests/benchmarks/` 全过（确保自动删 import 没误伤运行时）。

### 2.8 context/team/onboarding/learning-path/01-environment.md（F-003）

**改动**（line 25 区域）：

```diff
-pip install pyyaml
+# Python 依赖（与 CI workflow 同源）
+pip install -r requirements/ci.txt
+
+# 系统级工具（CI 由 apt-get 安装，本地按 OS 选）：
+#   macOS:  brew install bats-core hyperfine
+#   Ubuntu: sudo apt-get install bats hyperfine
```

**契约**：onboarding 不再列具体包名，永远指向 `requirements/ci.txt` 作为事实源。

### 2.9 context/team/experience/test-assets-must-be-wired-into-ci.md（F-007 收尾）

**新建文件全文**：

```markdown
# 测试资产创建后必须接入执行入口

**沉淀原因**：跨需求重复（任何"新加 shell / e2e / contract 测试但忘了接 CI"都会撞）、AI 反复错（写测试只测一遍即提 PR，忘记把"日常 push 触发"的钩子接上）、跨会话保留（review 阶段需要立刻能定位测试入口）。

## 问题

REQ-2026-012 F-A 前置发现：tests/lib/test_routing_e2e.sh 是 routing 路径的真实 E2E shell 测试（本地 PASS=3 FAIL=0），但 `.github/workflows/quality-check.yml` 没有任何 step 调用它。这意味着 routing.py 上线之后任何回归都不会被 CI 拦——开发者本地"还记得跑"才能保住。

## 根因

新增测试资产时只看"这个测试本身能跑过"，没看"它会不会被 CI / 本地 make 入口自动触发"。这是"工具封装知识，不封装流程"的反例——测试存在但不被自动消费，等同于 dead code。

**通用规律**：凡是「新建 shell / e2e / contract / property-based 测试」+「希望它在 PR / push 时强制执行」的组合，必须同时接入 CI workflow step + 本地镜像入口（make ci-local 之类）；不接入则必须显式说明原因和手跑命令。

## 解法

**两条约束**：

1. **新增测试默认进 CI**：每次提 PR 引入 shell / e2e / contract 测试时，对应 PR 必须同时改 `.github/workflows/quality-check.yml`（或等价配置）添加 step。reviewer 必查。
2. **不进 CI 必须说明**：若测试有合理理由不进 CI（如需要昂贵资源、跨日批处理、人为决策），PR 描述必须写明：
   - 为何不进 CI（性能 / 资源 / 业务原因）
   - 手跑命令（命令行 + 预期输出 + 频率）
   - 持有者（owner，谁负责按频率手跑）

## 反面案例

- REQ-2026-012 F-A 前：test_routing_e2e.sh 存在 4 个月未入 CI，期间 routing.py 经历过 3 次重构（来源：git log），靠运气没破。
- 与 `auto-generated-artifact-needs-pre-commit-not-just-ci.md` 是邻问题——前者是"派生产物 / CI 兜底同步"，本经验是"测试资产接入执行入口"；两条原则共同对抗"本地过 = CI 过"幻觉。

## 关联

- `context/team/experience/auto-generated-artifact-needs-pre-commit-not-just-ci.md` — 派生产物侧
- `context/team/ai-collaboration.md` § 验证清单 — review 时此条作为强制检查项
```

**INDEX 联动**：新建后必须在 `context/team/experience/INDEX.md` 加一行（一句话索引），由 CI `check-index.sh` 强制（来源：scripts/lib/check_sourcing.py）。

## 3. 验收标准（AC 机器断言形式）

回应 requirement.md 的 8 条 AC：

| AC | 机器断言命令 | 通过条件 |
|---|---|---|
| AC-1 | `gh run view <run-id> --log \| grep -E 'Run routing e2e shell tests.*PASS=3 FAIL=0'` | grep 命中 |
| AC-2 | `ls .claude/hooks/tests/test_protect-*.sh 2>/dev/null \| wc -l` | 输出 `0` |
| AC-3 | `grep -E 'pip install (pyyaml ruamel|-r requirements/ci.txt)' .github/workflows/quality-check.yml` | 只命中 `-r requirements/ci.txt` 形态 |
| AC-4 | `ruff check scripts tests --select=F; grep -E 'ruff check scripts tests --select=F' .github/workflows/quality-check.yml` | ruff exit 0 + grep 命中 |
| AC-5 | `make ci-local; echo $?` 与 `make ci-local-deps && false 2>&1 \| grep -E '^FAIL: ci-local-deps'`（强制失败模拟） | 前者 exit 0；后者 grep 命中 |
| AC-6 | `git diff develop .github/workflows/quality-check.yml \| grep -E '^[+-]on:\|^[+-]\s*pull_request\|^[+-]\s*push:'` | 输出空（触发段未变） |
| AC-7 | 各 feature PR 单独 `git revert <sha>` 后 `make ci-local` 仍 exit 0 | 7 次 revert 全过 |
| AC-8 | `test -f context/team/experience/test-assets-must-be-wired-into-ci.md && grep -F 'test-assets-must-be-wired-into-ci' context/team/experience/INDEX.md` | 两条命令均 exit 0 |

## 4. PR 拆分顺序

```
F-002 ┐
F-001 ┼── 并行可推（无依赖）
F-003 ┘                            ┌── F-004 ── F-005 ── F-006
                                   │   (机械)   (语义)   (扩范围)
F-007 ── 依赖 F-003（消费 ci.txt） ┤
                                   │
                                   └── 与 F-A~F-F 互独立可并行
```

- **建议顺序**：F-002（删旧测试，热身）→ F-001（routing e2e 入 CI，含草稿 PR 验证 D-005）→ F-003（ci.txt + workflow + onboarding）→ F-004 → F-005 → F-006 → F-007（含 experience.md 沉淀）。
- 每个 feature 一个独立 PR，符合 AC-7 可回滚约束。

## 5. 风险复盘（来自 outline-design R-1~R-7）

无新增风险；R-1~R-7 的 revert 路径已在 outline-design.md §6 明示，本阶段不重复。

**新增提醒**：F-004 执行 `ruff --fix` 后必须立即跑 `pytest tests/` 全集，及早发现"自动删 import 误伤运行时"（R-3）。

## 6. 引用源汇总

- requirements/REQ-2026-012/artifacts/requirement.md — 上游需求与 AC-1~AC-8
- requirements/REQ-2026-012/artifacts/tech-feasibility.md — 7 feature 评估 + R-1~R-7
- requirements/REQ-2026-012/artifacts/outline-design.md — 模块视图 + 时序图
- requirements/REQ-2026-012/plan.md — D-001~D-009 ADR
- .github/workflows/quality-check.yml — 当前 CI workflow
- .github/workflows/quality-check.yml:34 — 现 pip install 字面量
- .github/workflows/quality-check.yml:82 — 现 ruff lint 范围
- .github/workflows/quality-check.yml:87 — 现 render check step（routing-e2e 在它之后追加）
- tests/lib/test_routing_e2e.sh — routing e2e 脚本
- tests/lib/test_code_review_routing.py:396 — F-005 RoutingPlan 修复点 1
- tests/lib/test_code_review_routing.py:732 — F-005 RoutingPlan 修复点 2
- tests/lifecycle/test_submit_codex.py:744 — F-005 Any 修复点 1
- tests/lifecycle/test_submit_codex.py:790 — F-005 Any 修复点 2
- tests/hooks/test_pre_tool_use_guard.bats:39 — F-002 等价覆盖证据
- context/team/onboarding/learning-path/01-environment.md:25 — 现 onboarding pip 指令
- context/team/experience/auto-generated-artifact-needs-pre-commit-not-just-ci.md:7 — 经验沉淀邻问题
