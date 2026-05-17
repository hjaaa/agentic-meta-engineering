---
id: REQ-2026-012
title: "CI 工程化补强 · 技术可行性评估"
created_at: 2026-05-16 20:30:00
refs-tech-feasibility: true
---

# REQ-2026-012 · 技术可行性评估（tech-research 阶段）

## 评估目标

针对需求定义阶段确认的 7 个 feature（F-A / F-B / F-C / F-D1 / F-D2 / F-E / F-F），逐项判断在当前仓库的 CI 与本地工程栈上是否可落地、关键风险点在哪、单 feature 工作量约多少；为概要设计与详细设计阶段提供"可执行的工程边界"。本次不重新做需求层面的取舍，仅评估 D-001~D-005 决议在工程实现上的可行性。

## 上下文回顾

- CI 现状：单一 workflow `.github/workflows/quality-check.yml` 串 step 序列（来源：.github/workflows/quality-check.yml）；触发 `pull_request` + `push: main / develop`（来源：.github/workflows/quality-check.yml:7）；runner 为 `ubuntu-latest` + Python 3.11 + 单条 `pip install` 字面量（来源：.github/workflows/quality-check.yml:34）+ `apt-get install bats`（来源：.github/workflows/quality-check.yml:36）+ `apt-get install hyperfine`（来源：.github/workflows/quality-check.yml:42）；ruff 仅 lint `scripts/`（来源：.github/workflows/quality-check.yml:82）。
- 待入 CI 的 shell e2e：tests/lib/test_routing_e2e.sh 用 mktemp 起临时 git 仓库 + 切回 REPO_ROOT 调 `scripts.lib.code_review_routing` 的内部 API（来源：tests/lib/test_routing_e2e.sh:21）；脚本明确读 `.claude/code-review-routing.yaml` 绝对路径（来源：tests/lib/test_routing_e2e.sh）。
- 待删除的旧 shell 测试：原 .claude/hooks/tests/test_protect-branch.sh 与 test_protect-reviews.sh 均以 `HOOK=".claude/hooks/protect-branch.sh"` 硬编码已不存在路径（已在 definition 阶段经预检命令确认；现已于 F-002 commit d7624d2 整体删除，删前内容可经 `git show d7624d2~1:.claude/hooks/tests/test_protect-branch.sh` 取回）。
- bats 覆盖：tests/hooks/test_pre_tool_use_guard.bats 已 V-01 三分支阻断 + V-03 reviews 写保护 + 14 类 Bash 重定向（来源：tests/hooks/test_pre_tool_use_guard.bats:39）。
- ruff F 类基线：scripts/=0、tests/=95；F401×65 / F841×21 / F541×3 / F821×6；F821 真实位置见下文 F-D2 评估。
- Makefile 现状：仅 `gates-validate` / `gates-render` 两个 target（来源：Makefile:4）。

## 逐 feature 可行性

### F-A · 将 tests/lib/test_routing_e2e.sh 纳入 CI 一个 step

**结论**：可行，前提是先在草稿 PR 上单 step 跑一次确认 Ubuntu runner 行为（按 D-005 决议）。

**依赖核查**：
- `mktemp -d`：脚本只用 `-d` 标志（来源：tests/lib/test_routing_e2e.sh:21），GNU coreutils 与 BSD mktemp 都支持，ubuntu-latest 上无问题。
- `git init` / `git add` / `git commit`：CI workflow 已在 step 4 之前显式 `git config --global user.email "ci@example.com" / user.name "CI Runner"`（来源：.github/workflows/quality-check.yml:28），脚本内嵌的 `git config user.email "e2e@test.local"` 走 setup_work_dir 临时仓库（来源：tests/lib/test_routing_e2e.sh），不会与全局冲突。
- Python heredoc：脚本采用 `python3 - <<PYEOF` 模式喂代码（来源：tests/lib/test_routing_e2e.sh），bash 4+ 支持，ubuntu-latest 默认 bash 5.x，无兼容性风险。
- import 路径：脚本用 `sys.path.insert(0, REPO_ROOT)` 把仓库根插进搜索路径（来源：tests/lib/test_routing_e2e.sh），不依赖 `pip install -e .`，与现有 workflow 无 `pip install -e .` 一致。
- routing.yaml：通过 `$REPO_ROOT/.claude/code-review-routing.yaml` 绝对路径加载（来源：tests/lib/test_routing_e2e.sh），路径与项目内事实一致（来源：.claude/code-review-routing.yaml）。

**风险**：
- 单点风险——routing.py 内部 API（`_build_plan` / `_validate_schema` / `_load_yaml` / `_write_scope` / `_audit_log` / `RoutingDecision` / `_now_shanghai_display`）需保持 import 表稳定。若上游有重构动到这些私有名，e2e 会破。应对：在 routing.py 顶部加注释明确这是 e2e 测试入口，重命名前 grep `test_routing_e2e.sh`。
- locale 差异：脚本输出含中文，CI runner 系统 locale 为 C.UTF-8 兼容、Python 标准库 IO 编码沿用 utf-8（来源：.github/workflows/quality-check.yml:22），预期无 mojibake；草稿 PR 跑一次双重确认。

**工作量**：0.5 人时（workflow 加 1 个 step + 草稿 PR 验证 1 轮）。

### F-B · 删除两个旧 hook shell 测试

**结论**：可直接删除，无外部引用。

**依据**：
- 全仓 grep `test_protect-(branch|reviews)\.sh` 命中仅 requirement.md 自身（已在 definition 阶段验证；后续 commit 后会自我消除）。
- 两脚本均硬编码 `.claude/hooks/protect-branch.sh`，目标文件不存在，脚本本地执行直接 fail（已在 definition 阶段验证；脚本本身已于 F-002 commit d7624d2 删除）。
- bats 已覆盖等价场景：V-01 develop/main/master 分支阻断 + reviews 写保护 + 14 类 Bash redirect（来源：tests/hooks/test_pre_tool_use_guard.bats:39），与旧脚本断言 1:1 重合。

**负例缺口判断**：
- 旧 test_protect-branch.sh 包含两条 bats 未显式覆盖的用例（`main + Read → exit 0` / `develop + Read → exit 0`，删前内容可由 `git show d7624d2~1:.claude/hooks/tests/test_protect-branch.sh` 取回行 43 / 行 61）。
- 但这两条"非写操作 → 放行"的语义在 pre-tool-use-guard.sh 由 PreToolUse matcher 控制（matcher 不命中 Read 工具 → hook 根本不会被调用，来源：.claude/hooks/pre-tool-use-guard.sh:101），bats 模拟"Read on protected branch"会变成测试 settings.json matcher 配置而非 hook 本身——价值有限。
- detail-design 阶段评估：可选追加 1 条 bats 验证 `tool_name="Read"` 输入下 guard 直接 fail-open（无意义工具调用应快速放行），其它缺口为 0。

**风险**：删除后若 hooks/tests 目录变空可保留 `.gitkeep` 或直接删目录（detail-design 拍板）。

**工作量**：0.2 人时（删 2 文件 + 可能补 1 条 bats）。

### F-C · 新建 requirements/ci.txt 同源化依赖清单

**结论**：可行。本仓库 `pyproject.toml` 不含 `[project]` 段（来源：pyproject.toml:1），新建 `requirements/ci.txt` 走 pip `-r` 路径不动包结构。

**ci.txt 设计**（草案，detail-design 阶段最终化）：
```
# REQ-2026-012 F-C：CI / 本地共享的 Python 依赖清单
# 非 Python 工具（bats / hyperfine）由 workflow apt-get + onboarding 文档说明
pyyaml
ruamel.yaml
pathspec>=0.12,<1.0
ruff
pytest
```

**版本约束策略**：
- `pathspec>=0.12,<1.0` 保留现有上下界（来源：.github/workflows/quality-check.yml:34）。
- 其它包暂不锁版本——本次目标是"消除字面量漂移"，不是"锁定到精确版本"。若后续 CI 出现 ruff/pytest 大版本兼容问题，再开独立需求加锁。

**workflow 改动**：把 `pip install pyyaml ruamel.yaml "pathspec>=0.12,<1.0" ruff pytest`（来源：.github/workflows/quality-check.yml:34）改为 `pip install -r requirements/ci.txt`。

**onboarding 改动**：把单条 `pip install pyyaml`（来源：context/team/onboarding/learning-path/01-environment.md:25）改为 `pip install -r requirements/ci.txt`，并加一段说明 bats / hyperfine 走系统包管理器（macOS `brew install bats-core hyperfine`、Ubuntu `apt-get install bats hyperfine`）。

**风险**：本地原本只装 pyyaml 的开发者切换到 ci.txt 后会装更多依赖，磁盘占用增加（~30MB 级，可接受）。

**工作量**：0.5 人时（新建 ci.txt + 改 workflow yml + 改 onboarding + 本地 clean venv 验证 1 次）。

### F-D1 · ruff F 类机械清理（89 条）

**结论**：可行，单 PR 一次推进；mass-fix 比例高。

**分布固化**（基线时间 2026-05-16）：
| code | 数量 | 类型 | 自动修复（ruff --fix）覆盖 |
|---|---|---|---|
| F401 | 65 | unused import | 是 |
| F841 | 21 | unused local variable | 部分（仅简单赋值） |
| F541 | 3 | f-string without placeholder | 是 |

**推进路径**：
1. `ruff check scripts tests --select=F401,F541 --fix` 把 65+3=68 条自动修复，diff 主要是删除 import 行 / 把 `f"xxx"` 改 `"xxx"`。
2. F841 21 条用 `--fix` 仅修能确定无副作用的（如 `_ = subprocess.run(...)` 中变量未用）；剩余手工处理，多为 `result = ...` 后未使用 `result`。
3. 跑一次 `pytest tests/ --ignore=tests/benchmarks/`（来源：.github/workflows/quality-check.yml:57）确认无 import 残留导致的 NameError 风险（机械删未用 import 不应破坏运行时，但留个兜底）。

**风险**：
- F401 自动删 import 可能误删被 `__init__.py` re-export 的符号；应对：detail-design 阶段先全仓 `grep -rE "from <module> import"` 看是否被外部依赖。本仓库 tests/* 不在 site-packages 上，被外部依赖概率极低。
- F841 中可能存在"故意保留以方便 debug"的变量，删之前 review。

**工作量**：1 人时（含 review 修订）。

### F-D2 · ruff F 类语义清理（6 条 F821）

**结论**：可行，全部是缺少 typing import，非深层 fixture 问题。

**精确位置**：
- tests/lib/test_code_review_routing.py:396 — `RoutingPlan` 未导入（来源：tests/lib/test_code_review_routing.py:396）
- tests/lib/test_code_review_routing.py:732 — `RoutingPlan` 未导入（来源：tests/lib/test_code_review_routing.py:732）
- tests/lifecycle/test_submit_codex.py:744 — `Any` 未导入（来源：tests/lifecycle/test_submit_codex.py:744）
- tests/lifecycle/test_submit_codex.py:790 — `Any` 未导入（来源：tests/lifecycle/test_submit_codex.py:790）

注：ruff 在 744、790 各报 2 条同 message（语法位置不同列），实际唯一定位 2 处。

**修复路径**：
- test_code_review_routing.py：在文件顶部 import 区加 `from scripts.lib.code_review_routing import RoutingPlan`（具体类名以 routing.py 现行导出为准 [待补充：内容 = routing.py 是否真实导出 RoutingPlan 类；依据 = 396 行调用 `RoutingPlan(...)` 构造，必为现行符号；风险 = 若 routing.py 重构后类名已改为 Plan，需同步更新；验证时机 = F-D2 实施前 `grep -n "class RoutingPlan" scripts/lib/code_review_routing.py`]）。
- test_submit_codex.py：在 import 区加 `from typing import Any`，标准库无副作用。

**工作量**：0.2 人时。

### F-E · CI ruff 范围扩展

**结论**：可行，单行改动；F-D1 + F-D2 全部合并后才能开。

**改动点**：`.github/workflows/quality-check.yml:82` 行 `ruff check scripts/ --select=F` → `ruff check scripts tests --select=F`。

**额外考虑**：
- 缓存：现有 workflow 未配置 ruff cache，扩范围后单 step wall time 预计 +几秒，无需缓存配置。
- benchmarks 目录：`tests/benchmarks/` 是否会被纳入？需在 `pyproject.toml` 的 `[tool.ruff]` 段加 `extend-exclude = ["tests/benchmarks"]`（来源：pyproject.toml:11） [待补充：内容 = 现有 ruff 配置是否已隐式排除 benchmarks；依据 = pyproject.toml:11~15 当前仅 `select = ["F"]` 与 `line-length = 120`，无 exclude 段；风险 = benchmarks 含基准代码可能有 F 类问题；验证时机 = F-D1 实施时一并跑 `ruff check tests/benchmarks --select=F` 看分布，若有问题则在 F-E 前先加 extend-exclude]。

**风险**：F-E 单独 revert（即把 scripts/ tests 改回 scripts/）应让 CI 即时回绿，F-D1 / F-D2 清债成果保留；可控。

**工作量**：0.2 人时。

### F-F · make ci-local 入口

**结论**：可行，把现有 workflow 9 个 step 串行翻译为 Makefile target。

**Makefile 草案**（detail-design 最终化）：
```
.PHONY: ci-local

ci-local: ci-local-deps ci-local-git-config ci-local-gates ci-local-pytest \
          ci-local-settings-check ci-local-bats ci-local-ruff ci-local-render-check \
          ci-local-routing-e2e

ci-local-deps:
	@pip install -r requirements/ci.txt || { echo "FAIL: ci-local-deps" >&2; exit 1; }

ci-local-gates:
	@python3 scripts/gates/run.py --trigger=ci --strict || { echo "FAIL: ci-local-gates" >&2; exit 1; }

ci-local-pytest:
	@pytest tests/ --ignore=tests/benchmarks/ -v || { echo "FAIL: ci-local-pytest" >&2; exit 1; }

# ...（每个 step 同模式）

ci-local-routing-e2e:
	@bash tests/lib/test_routing_e2e.sh || { echo "FAIL: ci-local-routing-e2e" >&2; exit 1; }
```

**`FAIL: <step-name>` 断言契约**：
- 每个子 target 在失败路径用 `echo "FAIL: <step>" >&2` 写 stderr 末行。
- AC-5 中规定的 `make ci-local 2>&1 | grep -E '^FAIL: '` 自动断言模式可工作。
- detail-design 阶段需在 Makefile 顶部加注释列 step-name 命名表（reviewer v2 suggestion），避免后续新增 step 漂移。

**跨平台说明**：
- hyperfine：本地需 `brew install hyperfine`（macOS）或 `apt-get install hyperfine`（Ubuntu），onboarding 文档同步；若本地未装，`ci-local-hyperfine` 子 target fail 给提示而不是静默跳过。
- bats：同上，brew / apt 安装路径。

**风险**：
- 串行 wall time：CI 单 job 完整跑约 N 分钟 [待补充：内容 = ubuntu-latest 上 quality-check.yml 完整 wall time；依据 = 需查最近 PR 的 actions run summary；风险 = 若本地 wall time > 5 min 体感差；验证时机 = F-F 落地后实测一次 `time make ci-local`]。
- pytest 在本地 Python 版本 ≠ 3.11 时行为差异：建议 Makefile 头部明确 `PYTHON ?= python3` 并在 ci-local-deps 前打印 `python3 --version`。

**工作量**：1.5 人时（写 Makefile + 跨平台验证 + 与 workflow 输出对照）。

### D-005 · 草稿 PR 实战通道

**结论**：用 `gh pr create --draft` 即可，无需特殊基础设施。

**操作路径**：
1. F-A 实施时先在 `feat/req-2026-012` 上加一个 workflow step（仅 routing-e2e），commit + push。
2. `gh pr create --draft --base develop --title "[draft] F-A routing e2e CI 验证" --body "<...>"`。
3. workflow 自动触发，单 step 跑完拿到 PASS=3 FAIL=0 或失败 traceback。
4. 不合并草稿 PR；调整 step 后 reuse 同分支推送。

**风险**：草稿 PR 仍消耗 GitHub Actions 分钟数（自建 runner 不涉及），公司额度许可下可忽略。

**工作量**：含在 F-A 0.5 人时内。

## 整体风险与应对

| 风险 ID | 描述 | 影响面 | 应对 |
|---|---|---|---|
| R-1 | routing.py 私有 API 重构破坏 e2e | F-A 单点 | routing.py 顶加注释；refactor 前 grep e2e 引用 |
| R-2 | ci.txt 切换后本地依赖膨胀 | F-C 体感 | 文档明确说明；本地 venv 隔离 |
| R-3 | F401 自动删 import 误伤 __init__.py re-export | F-D1 修复风险 | detail-design 先 grep 跨文件引用；单 PR 跑全测验证 |
| R-4 | F-D2 F821 真实来自 routing.py 重命名 | F-D2 修复偏 | 实施前 `grep -n "class RoutingPlan"` 双确 |
| R-5 | benchmarks 目录被纳入 ruff | F-E 红 | F-D1 阶段试跑一次；必要时加 extend-exclude |
| R-6 | make ci-local 本地 wall time 过长导致开发者绕过 | F-F 实际效果 | 实测后若 > 5min 即拆 ci-fast |
| R-7 | Ubuntu runner 上 routing-e2e 与本地 macOS 行为分歧 | F-A 入 CI 当天 | 草稿 PR 先验证，不直接 push 正式 PR |

## 工作量估算

| feature | 估算（人时） | 备注 |
|---|---|---|
| F-A | 0.5 | 含草稿 PR 一轮验证 |
| F-B | 0.2 | 删 2 文件 + 可选 1 条 bats |
| F-C | 0.5 | ci.txt + workflow yml + onboarding |
| F-D1 | 1.0 | 含 review 修订 |
| F-D2 | 0.2 | 4 行 import |
| F-E | 0.2 | 1 行 + 可能 extend-exclude |
| F-F | 1.5 | Makefile 完整翻译 + 跨平台 |
| **合计** | **4.1** | 不含 review 等待与 PR round-trip |

## 待决问题（已闭环至 plan.md ADR）

> 4 项在 outline-design 阶段开始前一轮回灯全部闭环，相关 ADR 见 plan.md。

1. ✅ **F-B 不补 Read fail-open bats**：matcher 不命中 Read，hook 不会被调用；详见 plan.md D-006。
2. ✅ **F-C ci.txt 不锁版本**：保留 pathspec `>=0.12,<1.0`，其它包不锁；详见 plan.md D-007。
3. ✅ **F-E 不加 extend-exclude**：实测 `ruff check tests/benchmarks --select=F` 命中 **0 条**，直接扩范围安全；详见 plan.md D-008。
4. ✅ **F-F step-name 命名表**：留 detail-design 与 Makefile 同步出表，避免现在猜名后期返工；当前草案命名仅作参考；详见 plan.md D-009。

## 引用源汇总

- .github/workflows/quality-check.yml — CI workflow 入口
- .github/workflows/quality-check.yml:7 — 触发条件
- .github/workflows/quality-check.yml:28 — git config 段
- .github/workflows/quality-check.yml:34 — pip install 字面量
- .github/workflows/quality-check.yml:36 — bats 安装
- .github/workflows/quality-check.yml:42 — hyperfine 安装
- .github/workflows/quality-check.yml:57 — pytest --ignore=benchmarks
- .github/workflows/quality-check.yml:82 — ruff scripts/ 现范围
- tests/lib/test_routing_e2e.sh — routing e2e 全脚本
- tests/lib/test_routing_e2e.sh:21 — mktemp + git init 段
- tests/lib/test_code_review_routing.py:396 — F821 RoutingPlan 位置 1
- tests/lib/test_code_review_routing.py:732 — F821 RoutingPlan 位置 2
- tests/lifecycle/test_submit_codex.py:744 — F821 Any 位置 1
- tests/lifecycle/test_submit_codex.py:790 — F821 Any 位置 2
- tests/hooks/test_pre_tool_use_guard.bats:39 — bats V-01/V-03 覆盖入口
- .claude/hooks/tests/test_protect-branch.sh:4 — 旧 shell 测试硬编码已删 hook 路径
- .claude/hooks/tests/test_protect-branch.sh:43 — main + Read 用例（待评估是否补 bats）
- .claude/hooks/tests/test_protect-branch.sh:61 — develop + Read 用例
- .claude/hooks/pre-tool-use-guard.sh:101 — Edit/Write/MultiEdit 分支保护现位置
- .claude/code-review-routing.yaml — routing yaml 实际路径
- pyproject.toml:1 — 无 [project] 段
- pyproject.toml:11 — ruff 配置 select=["F"] / line-length=120
- Makefile:4 — 现仅 gates-validate / gates-render
- context/team/onboarding/learning-path/01-environment.md:25 — onboarding 单条 pip install pyyaml
