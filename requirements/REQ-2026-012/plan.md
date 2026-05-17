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

### D-006 F-B 不补 Read fail-open bats 用例
- **Context**：tech-feasibility 评估指出 PreToolUse matcher 不命中 Read 工具，hook 根本不会被调用；bats 模拟 Read 等于在测 settings.json matcher 配置而非 hook 逻辑（来源：.claude/hooks/pre-tool-use-guard.sh:101）
- **Decision**：F-B 任务仅删除 `.claude/hooks/tests/test_protect-branch.sh` + `.claude/hooks/tests/test_protect-reviews.sh`，不补任何 bats；负例缺口判定为 0
- **Consequences**：好：F-B 工作量从 0.2 人时降到 ~0.1；差：若未来 settings.json matcher 配置回退、bats 不能立即提示——但该风险与本需求 scope 无关
- **时间**：2026-05-16 21:21:02

### D-007 F-C ci.txt 不锁版本
- **Context**：本仓库现在写 `pip install pyyaml ruamel.yaml "pathspec>=0.12,<1.0" ruff pytest`（来源：.github/workflows/quality-check.yml:34），pathspec 已带上下界，其它无锁；用户偏好"先 CI 可用，不引入包管理重构"
- **Decision**：requirements/ci.txt 保留 pathspec 现有 `>=0.12,<1.0` 范围、其它包不锁；若后续 CI 因 ruff/pytest 大版本变更红，开独立需求加锁（lock-file 方案在该需求里再评估）
- **Consequences**：好：当前 scope 干净，无包管理风格改造；差：CI 严格可重现性低一档，依赖大版本上线可能踩坑
- **时间**：2026-05-16 21:21:02

### D-008 F-E 不加 `extend-exclude = ["tests/benchmarks"]`
- **Context**：tech-research 阶段实测 `ruff check tests/benchmarks --select=F` 命中 **0 条**；当前 `tests/benchmarks/` 只有 `__init__.py` + `test_routing_perf.py`（来源：tests/benchmarks），后者无 F 类违规
- **Decision**：F-E 把 ruff 范围扩到 `scripts tests --select=F` 时不动 `pyproject.toml` 的 ruff `[tool.ruff.lint]` 段（来源：pyproject.toml:11），不加 extend-exclude
- **Consequences**：好：配置面更小、改动可逆；差：若未来 benchmarks 加新文件触发 F 类，CI 当场红——但这是良性信号，便于贡献者立即看到
- **时间**：2026-05-16 21:21:02

### D-009 F-F Makefile step-name 命名表留 detail-design 同步出
- **Context**：reviewer v2 suggestion 建议在 Makefile 顶部固化 step-name 命名表；命名本身依赖 Makefile 实现稿，预先猜测有漂移风险
- **Decision**：不在 outline-design 阶段预定 step-name；detail-design 阶段与 Makefile 验证同步出表，作为 F-F 任务的内置交付物；当前 tech-feasibility 中的草案命名（`ci-local-deps` / `ci-local-gates` / `ci-local-pytest` / `ci-local-settings-check` / `ci-local-bats` / `ci-local-ruff` / `ci-local-render-check` / `ci-local-routing-e2e`）仅作参考
- **Consequences**：好：避免现在猜名后期返工；差：F-F 任务的设计与实现必须共同 owner，命名漂移会在同一 PR 内自我修正
- **时间**：2026-05-16 21:21:02

### D-010 detail-design.artifact_hashes 三处 refresh 不视为重审
- **Context**：F-001 草稿 PR 触发 ubuntu CI 后 GATE-REVIEW-VERDICT R005 命中 3 处 stale：
  - `artifacts/requirement.md`（a043bb97 → 8c5b8bc7）：来源是 commit 6aacaca（fix(req-2026-012): F-002 副作用 dangling 引用修复）——F-002 删除旧 hook shell 测试后，requirement.md L15 引用 `test_protect-branch.sh:4` 变 dangling，被改写为 `F-002 commit d7624d2 删除（删前内容可由 git show 取回）`叙述；commit 体已注明"上游 reviewer hash 因此 stale；本次不重审，归入需求结束时统一处理或 submit 阶段一并冲洗"
  - `artifacts/tasks/F-001.md`（21887888 → 3f96a108）：来源是本次 F-001 派发把 frontmatter `status: pending` 改为 `in-progress`、`updated_at` 推进；任务内容未变
  - `artifacts/tasks/F-002.md`（cfb8adfe → 126e9367）：来源是 F-002 完整生命周期（pending → in-progress → done）的 frontmatter status / updated_at 推进；任务内容未变
- **Decision**：把 meta.yaml.reviews.detail-design.artifact_hashes 中这 3 个文件 hash 刷新到当前值；**不重审 detail-design**——design 内容（detailed-design.md / features.json / outline-design.md / 7 个 task.md 主体）未变；task.md frontmatter status 字段在 dev 阶段必然演进，把它纳入 review 钉 hash 范围是 reviewer artifact 选择的过度收敛（结构性问题），但本需求 scope 内不修系统性 bug。
- **Consequences**：好：解锁 F-001 草稿 PR 的 ubuntu CI 验证（D-005 / AC-1 #2）；其余 6 个 feature（F-003~F-007）后续派发都会触发同样的 R005，先在 F-001 这里把 3 处 dangling refresh 掉，后续 5 次 task.md hash 演进按"实施 feature 时同步刷新"模式处理。差：semantic 上把"hash refresh"和"实际重审"混在同一 reviewer attestation 下；缓解措施是本 ADR 显式记录每处变更的根因 + 引用 commit。
- **后续动作**：本需求归档时考虑独立开 hotfix 需求修结构性 bug——reviewer Agent artifact 选择规则需排除会随 dev 阶段演进的 task.md frontmatter；或 R005 校验放宽到只比对文件 body（忽略 frontmatter status 字段）。
- **时间**：2026-05-17 14:55:00
