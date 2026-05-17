# REQ-2026-014 · worktree 隔离能力完整迁移

> 设计来源：`context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md` v0.2
> 参考实现：obra/superpowers — `using-git-worktrees` / `finishing-a-development-branch`

## 目标

把 Superpowers 的 worktree 隔离机制完整迁移到本项目的 workflow 体系：新需求默认在隔离 worktree 中推进；requirement 目录从 `REQ-YYYY-NNN` 改为 `YYYYMMDD-<slug>`；已有 worktree 自动复用；创建后跑 setup 与基线验证；submit 后保留 worktree，archive/discard 时按 provenance 安全清理。

## 范围

- 包含：
  - 新增 `scripts/lib/worktree_manager.py`（detect / select / ignore-check / create / setup / cleanup）
  - 新增 `scripts/lib/requirement_naming.py`（slug 规则 + key 生成 + legacy 兼容）
  - 改 `workflow_run.py` / `workflow_bootstrap.py`：默认 worktree + 新 key 命名 + meta.worktree 块 + 失败回滚
  - 改 `/workflow:submit` / `/requirement:submit`：成功后保留 worktree
  - 改 archive 流程：provenance + 路径白名单 cleanup
  - `standard-8phase.yaml` 顶层增加 `worktree` 配置组（policy=auto / never / require / current）
  - `.gitignore` 增加 `.worktrees/`；运行时 fail-closed 校验
  - `run-state.jsonl` 的 `workflow_started` 事件增加 worktree 摘要
  - 文档：`context/team/git-workflow.md` / README / onboarding / common pitfalls
  - 测试：`tests/lib/test_worktree_manager.py` 单测 + 临时 repo 集成测试

- 不包含：
  - 历史 `REQ-YYYY-NNN` 目录迁移（沿用 legacy in-place）
  - 直通分支（feature/docs/chore）默认 worktree（仅文档推荐）
  - daemon / DB / Web Dashboard
  - feature 级隔离（粒度是 run / requirement）
  - 自动清理用户或 harness 创建的外部 worktree
  - 启动阶段默认跑 `make ci-local`（baseline 只跑 `make gates-validate`）

## 里程碑

| 阶段 | 预期完成 | 说明 |
|---|---|---|
| definition | | 把 spec 的目标/边界/验收落成 artifacts/requirement.md |
| tech-research | | 验证 `git worktree` 在本仓 + Codex/Claude harness 下的行为差异 |
| outline-design | | 概要：模块切分 / 数据契约 / 状态机 |
| detail-design | | 详细：接口签名 / 字段 schema / 事件 payload / features.json |
| task-planning | | 拆 Phase 1-4 的 features 并排期 |
| development | | 按 Phase 1→4 推进；本仓自举验证 |
| testing | | 单测 + 集成测试 + 自举跑 `make ci-local` |

## 风险

- 命名重构波及面广：旧代码硬编码 `REQ-YYYY-NNN` 的位置（status / list / submit / hook / Skill 文档）容易遗漏 → 抽 `requirement_naming.py` 做统一入口，新旧 key 并测；先在 spec 第 6.1 节列出的入口逐个回归。
- bootstrap 路径写错：requirement 目录可能落到主仓而非 worktree → 所有路径参数显式传 `active_repo_root`，集成测试断言落点。
- 中文标题纯脚本启动缺 slug：体验下降 → 命令层先生成 slug；脚本层 fail-closed 并提示 `--slug short-english-name`。
- cleanup 误删外部 worktree：丢失用户工作 → `owner=workflow` + 路径白名单 + 非 discard 不强删（三重保护）。
- baseline 过重启动慢：默认 `make gates-validate`，完整 CI 延后到 submit 前。
- Codex/Claude harness 自带 worktree：双重创建、phantom state → 先 `detect_worktree_state` 判 linked，external owner 不清理。
- `.worktrees/` 未 ignore：git status 污染 → 实现期一次性更新 `.gitignore`，运行时 fail-closed 校验。
- 旧需求缺 `worktree` 字段：status / archive 报错 → 视为 legacy in-place（enabled=false）。

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-000 设计稿先行 → 阶段并行压缩

- **Context**：spec 文件 `2026-05-17-worktree-isolation-migration-design.md` v0.2 已经覆盖目标 / 决策 / 架构 / 接口 / 测试计划 / 迁移步骤，相当于一份"detail-design 强度"的草稿。直接走完整 8 阶段会有大量重复劳动。
- **Decision**：以 spec 为蓝本，将 definition / tech-research / outline-design / detail-design 四阶段串行压缩——每阶段产出物对照 spec 抽取相应章节并补足缺口（业务术语 / 风险细化 / 接口签名 / features.json），而不是从零撰写。代码命名 / 数据契约 / 测试矩阵以 spec 内 D-001~D-015 为权威。
- **Consequences**：
  - 好处：节省前期文档时间；保持 spec 内决策追溯链单一来源。
  - 坏处：若 spec 有遗漏，可能延迟到 detail-design 才暴露。需要在 definition 阶段先做一次完整性 review。
- **时间**：2026-05-17 23:40:00
