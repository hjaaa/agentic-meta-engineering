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

## 候选 feature（待 definition 阶段固化为 features.json）

| 候选 ID | 名称 | 依赖 | 备注 |
|---|---|---|---|
| F-A | 将 `tests/lib/test_routing_e2e.sh` 纳入 CI 一个 step | 无 | 风险最低、信号最强，优先做 |
| F-B | 旧 hook shell 测试迁移到 `pre-tool-use-guard.sh` 或删除 | 无 | 不修就别进 CI，否则一进就红 |
| F-C | CI 依赖清单同源化（`requirements/ci.txt` 或 `pyproject [optional-dependencies]`） | 无 | 消除 workflow 与 onboarding 漂移 |
| F-D | `scripts/` + `tests/` 目录 ruff F 类清债（≈ 95 条） | 无 | F-E 的硬前置 |
| F-E | CI ruff 范围扩展至 `ruff check scripts tests --select=F` | F-D | 必须在 F-D 全部清理后才能开 |
| F-F | `make ci-local` 入口，按 workflow 顺序串联本地校验 | F-A / F-B / F-C 落地后产出可用，但脚本本身可与之并行 | 兼顾"本地过、CI 反复红"经验沉淀 |

> 顺序约束：F-D 必须先于 F-E。其它建议按 F-A → F-B → F-C → F-D → F-E → F-F 推进，便于每个 PR 独立可回滚。

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

- **ruff 清债工作量被低估**：本地试跑给出 ≈ 95 条 F 类问题，但若含跨文件 F821，修起来可能牵动 import 重组；应对：tech-research 阶段对 95 条做粗分类，超 1 天工作量则把 F-D 再拆。
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

<!-- 暂无决策。技术预研阶段若产生方向性选择（如 ci.txt vs pyproject extras）再补 D-001。 -->
