# REQ-2026-012 · CI 工程化补强：纳入 routing e2e、清理陈旧 hook 测试、统一依赖清单、ruff 范围扩展、本地 CI 镜像入口

## 目标

把已有但游离于 CI 之外的工程能力（routing e2e shell 测试、本地校验入口、ruff 规则扩展、依赖来源）正式纳入 CI，并清理与现状脱节的旧 hook 测试与依赖漂移，让"本地能跑过 = CI 能跑过"成为可重复的工程事实，而不再依赖 review 阶段口头确认。

## 范围

- 包含：
  - 把 `tests/lib/test_routing_e2e.sh` 纳入 GitHub Actions 一个 step（本地 PASS=3 FAIL=0）
  - 处理 `.claude/hooks/tests/test_protect-branch.sh` 等指向已删除 hook 的 shell 测试：迁移到 `pre-tool-use-guard.sh` 的等价测试，或删除并在 notes 记原因
  - 新增 `requirements/ci.txt`（或在 `pyproject.toml` 声明 CI/test extras），让 workflow 与本地从同一份清单安装依赖
  - 清理 `scripts/` + `tests/` 目录的 ruff F 类问题（基线 ≈ 95 条，含未用变量/导入与 F821），通过后把 CI 的 `ruff check` 范围从 `scripts/` 扩到 `ruff check scripts tests --select=F`
  - 在 `Makefile` 增加 `ci-local` target，按 workflow 顺序串联 gate / pytest / bats / ruff / render check / routing e2e

- 不包含：
  - 切换 CI 平台或重排 workflow 触发条件
  - ruff 规则集在 `F` 之外的扩张（独立后续需求）
  - 撰写新的业务测试用例
  - 把本需求拆出的 5 个候选 feature 之外的 CI 项（例如 lighthouse / bench 等）

## 候选 feature（已与用户在 definition 一轮回灯对齐；features.json 在 task-planning 阶段固化）

| 候选 ID | 名称 | 依赖 | 备注 |
|---|---|---|---|
| F-A | 将 `tests/lib/test_routing_e2e.sh` 纳入 CI 一个 step | 无 | 风险最低、信号最强，优先做。入 CI 前先开**草稿 PR** 单 step 验证 Ubuntu runner 行为（D-005 决议） |
| F-B | 删除 `.claude/hooks/tests/test_protect-branch.sh` + `test_protect-reviews.sh`；如有缺口补 0-2 条 bats | 无 | bats V-01/V-03 已覆盖三分支阻断 + reviews 写保护 + 14 类 Bash redirect；不再维护指向旧 hook 名的 shell 测试（D-002 选 A） |
| F-C | 新建 `requirements/ci.txt` 收敛 CI/test pip 清单；workflow + onboarding 同源引用；非 Python 工具（bats / hyperfine）仍由 `apt-get` 走 workflow + 文档（D-001 选 A） | 无 | 不动 `pyproject.toml [project]` 表，避免顺手引入包结构改造 |
| F-D1 | ruff F 类**机械清理**：F401×65 + F841×21 + F541×3 = 89 条 | 无 | 大量条目、低 review 强度，单 PR 一次清完；tech-research 阶段先固化 ruff 版本基线 |
| F-D2 | ruff F 类**语义清理**：F821×6 条（`RoutingPlan` / `Any` 未导入） | F-D1（可重叠 review 但合并顺序固定 D1→D2） | review 强度高，多为 `from typing import Any` / 测试 fixture 漏导入 |
| F-E | CI ruff 范围扩展至 `ruff check scripts tests --select=F`（改 `.github/workflows/quality-check.yml:82`） | F-D1 + F-D2 全部合并 | F-E 单独 revert 时 ruff 范围回退 `scripts/`，清债成果保留（AC-7） |
| F-F | `make ci-local` 入口：默认镜像 CI（含 hyperfine、`pytest --ignore=tests/benchmarks/`），含 routing e2e step | F-A 起步可用 | 后续若日常推 PR 太慢再补 `ci-fast`（D-004 决议） |

> 顺序约束：F-D1 → F-D2 → F-E 是硬链；F-A / F-B / F-C / F-F 间无强依赖，建议按 F-A → F-B → F-C → F-D1 → F-D2 → F-E → F-F 推进，便于每个 PR 独立可回滚。
> 经验沉淀任务在 testing 阶段闭环时由 `/knowledge:extract-experience` 触发，新增 `context/team/experience/test-assets-must-be-wired-into-ci.md`，不放进 feature 列表（视为本需求的副产物）。

## 里程碑

| 阶段 | 预期完成 |
|---|---|
| definition | 待 requirement.md 评审通过 |
| tech-research | 评估 ruff 清债工作量；决策 `requirements/ci.txt` vs `pyproject extras` |
| outline-design | 给出 6 个 feature 的高层方案与依赖图 |
| detail-design | 每个 feature 的接口签名 / 文件级 touches / AC |
| task-planning | features.json + tasks/*.md |
| development | 按 F-A→F-F 顺序合并 |
| testing | 跑通 ci-local + 实际 PR 触发 workflow 验证 |

## 风险

- **ruff 清债基线已固化**（2026-05-16 实测）：`ruff check scripts tests --select=F` 命中 95 条 F 类问题，`scripts/` 已 0 条，95 条全在 `tests/`。分布 F401×65 / F841×21 / F541×3 / F821×6 —— F-D1 机械范围 = 89 条（F401+F841+F541），F-D2 语义范围 = 6 条（F821，集中在 `tests/lib/test_code_review_routing.py` 的 `RoutingPlan` 与 `tests/lib/test_submit_codex.py` 的 `Any`）。子目录 top 3：`tests/lib/` 35 / `tests/gates/` 28 / `tests/e2e/` 9。tech-research 阶段在 ubuntu-latest 同版本 ruff 复跑确认基线不漂移后才开 F-D1 任务。
- **旧 hook 测试还有别处引用**：单纯删除可能漏掉文档 / Skill / Hook 配置中残留的引用；应对：删除前 grep 全仓引用，迁移优先于删除。
- **CI 环境依赖缺失**：`tests/lib/test_routing_e2e.sh` 可能依赖本地存在的 `jq` / `bash` 版本 / Python 路径；应对：纳入 CI 前先在 workflow runner image 上单跑一次确认。
- **依赖清单切到 pyproject 后破坏本地直装习惯**：现有 onboarding 写的是 `pip install pyyaml`；应对：无论选哪种方案，同步更新 `context/team/onboarding/`。
- **F-D 清债与正在进行的其它需求文件级冲突**：若同期有 PR 触碰 scripts/tests，rebase 成本高；应对：清债拆成多个小 PR，按子目录推进。

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 CI/test 依赖事实源选 `requirements/ci.txt`
- **Context**：workflow 现写 `pip install pyyaml ruamel.yaml "pathspec>=0.12,<1.0" ruff pytest`（字面量），onboarding 只装 `pyyaml`，两者漂移；CI 又含 `bats` / `hyperfine` 这类非 Python 工具
- **Decision**：A 案 `requirements/ci.txt`；B 案 `pyproject.toml [project.optional-dependencies]` 拒绝
- **Consequences**：好：实现成本低、对非 Python 工具不冲突、不动 `pyproject.toml [project]` 表；差：与"现代 Python 包管理统一"风格略偏离
- **时间**：2026-05-16 20:10:00

### D-002 旧 hook shell 测试选"全删除 + 必要时补 bats"
- **Context**：`.claude/hooks/tests/test_protect-branch.sh` 与 `test_protect-reviews.sh` 均指向已不存在的 `.claude/hooks/protect-branch.sh`；外部无引用（grep 仅命中本需求文档自身）
- **Decision**：A 案"删除 + 必要时补 0-2 条 bats"；B 案"迁移到 pre-tool-use-guard.sh 等价测试"拒绝
- **Consequences**：好：消除指向已死路径的测试源；差：依赖 detail-design 阶段一次性 grep 校验，确认 bats 不缺口
- **时间**：2026-05-16 20:10:00

### D-003 ruff 清债按风险拆 3 个 PR（F-D1 / F-D2 / F-E）
- **Context**：本地基线约 95 条 F 类问题，其中机械项（unused import / unused var / f-string）与语义项（F821 等）review 强度差异大
- **Decision**：C 案"按风险拆 3 个 PR"——F-D1 机械清理 → F-D2 语义清理 → F-E 扩范围；A "单 PR 一口气" 与 B "按子目录拆" 均拒绝
- **Consequences**：好：每 PR 独立可 revert，F-E 单独回退不打翻 F-D1/F-D2 成果；差：PR 数量增加、需更多 review round-trip
- **时间**：2026-05-16 20:10:00

### D-004 `make ci-local` 默认镜像 CI（含 hyperfine）
- **Context**：`make ci-local` 是"本地 CI 镜像入口"，若默认跳过慢 step，名字与行为不一致
- **Decision**：A 案"默认含 hyperfine 路径、不跑 `tests/benchmarks/`"；B 案"默认跳 hyperfine + ci-local-full 兜底"拒绝
- **Consequences**：好：本地 / CI 严格 1:1，无隐性 step 缺口；差：日常 push 前慢一点；后续如需快速校验可单独补 `ci-fast`
- **时间**：2026-05-16 20:10:00

### D-005 routing e2e 入 CI 前先在草稿 PR 单 step 验证
- **Context**：用户报告本地 macOS PASS=3 FAIL=0，但 Ubuntu runner 上 PATH / locale / bash 版本可能影响 mktemp + git init + Python import 路径
- **Decision**：F-A 实施时先开草稿 PR、单 step 跑 `bash tests/lib/test_routing_e2e.sh`，确认 Ubuntu 结果后再合入正式 step
- **Consequences**：好：避免正式 PR 当场红；差：F-A 至少 2 个 commit（草稿验证 + 合入正式）
- **时间**：2026-05-16 20:10:00
