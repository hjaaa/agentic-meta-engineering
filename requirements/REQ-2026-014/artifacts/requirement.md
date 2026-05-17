---
id: REQ-2026-014
title: worktree 隔离能力完整迁移
created_at: 2026-05-17T15:45:44Z
refs-requirement: true
---

# REQ-2026-014 · worktree 隔离能力完整迁移

> 设计权威单源：`context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md` v0.2（DRAFT，huangjian + Codex 起草于 2026-05-17）。
> 本文档为 v0.2 设计稿在 requirement 层的语义化引用与验收落地；如发现偏差，按 plan.md D-000 决策反修 spec → bump 到 v0.3。

## 背景

当前 requirement workflow 的启动路径是 `/workflow:run standard-8phase "<title>"`：在主工作目录下创建 `requirements/REQ-YYYY-NNN/`，调 `git checkout -b feat/req-YYYY-NNN`，后续所有阶段都在同一个工作目录中继续（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:26）。

该模型满足单需求串行开发，但在以下 7 类场景暴露问题（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:34）：多 active requirements 并行被分支切换打断；数字递增 ID 依赖 max+1 扫描带来全局竞争；`REQ-YYYY-NNN` 无法从路径看出需求主题；长需求跨会话恢复容易续到错误分支；subagent / review-loop 共用同一 working tree；archive 不知道目录是否绑定隔离工作区。

`context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md` 曾把 "git worktree 隔离" 列为未来扩展，触发条件为"多 active runs 文件冲突"（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:46）。本需求把该扩展提前转为一等能力，参考实现为 obra/superpowers 的 `using-git-worktrees` 与 `finishing-a-development-branch`（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:10）。

## 目标

- 主目标：把 Superpowers 的 worktree 隔离机制完整迁移到本项目 workflow 体系，对 requirement 类模板默认启用；新需求默认在隔离 worktree 中推进；已有 worktree 自动复用；创建后跑 setup 与基线；submit 后保留 worktree；archive/discard 才按 provenance 安全清理（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:16）。

- 次要目标：
  - requirement 目录命名从 `REQ-YYYY-NNN` 改为 `YYYYMMDD-<slug>` 可读格式，并兼容历史 ID（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:103）。
  - 已在外部 worktree（Codex / Claude harness）中运行时复用当前目录，不嵌套创建（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:94）。
  - bootstrap 失败自动 best-effort 回滚未留半成品 worktree / branch / 目录（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:429）。
  - submit/PR 后保留 worktree 供 PR feedback；archive/discard 才清理 workflow-owned worktree（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:494）。
  - 启动阶段 baseline 用轻量 `make gates-validate`，完整 `make ci-local` 延后到 submit 前（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:457）。

## 用户场景

### 场景 1：开发者新建需求默认隔离

- 角色：requirement 开发者
- 前置：当前在主仓 develop（非 linked worktree）且工作区 clean
- 主流程（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:197）：
  1. 跑 `/workflow:run standard-8phase "示例需求"`（或带 `--slug`）
  2. 系统经 `detect_worktree_state` 判定当前为普通 repo（非 linked）
  3. 生成 `requirement_key = YYYYMMDD-<slug>`（冲突时追加 `-NN`）
  4. 从 `base_branch=develop` 创建 `.worktrees/feat-req-<requirement_key>` 并 checkout `feat/req-<requirement_key>`
  5. 在 worktree 路径下写 `requirements/<requirement_key>/meta.yaml / plan.md / process.txt / run-state.jsonl`
  6. 跑 setup + baseline (`make gates-validate`)
  7. 输出 `cd .worktrees/feat-req-<requirement_key> && /workflow:continue <requirement_key>` 提示
- 期望结果：`git worktree list` 包含新 worktree；`meta.worktree.owner=workflow`；后续 `/workflow:continue` 在该 worktree 内能正常推进（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:213）。

### 场景 2：已在外部 worktree 中启动需求

- 角色：在 Codex / Claude harness 自带 worktree 中工作的开发者
- 前置：`git rev-parse --git-dir` 与 `git rev-parse --git-common-dir` 不同且非 submodule（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:225）
- 主流程：
  1. 跑 `/workflow:run standard-8phase "..."`
  2. 系统检测到 linked worktree → 不嵌套创建（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:226）
  3. 复用当前路径；若分支非目标 `feat/req-*` 则创建或切换分支，但不拥有目录清理权
  4. meta 写 `worktree.owner=external`
- 期望结果：不出现 nested worktree；后续 archive 时不清理外部 worktree（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:231）。

### 场景 3：submit 后保留 worktree 处理 PR feedback

- 角色：requirement 开发者
- 前置：需求开发完成，准备提 PR
- 主流程（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:233）：
  1. 跑 `/requirement:submit` 或 `/workflow:submit`
  2. 系统推送 `feat/req-<requirement_key>` 分支并创建/更新 PR
  3. **不**调用 `git worktree remove`
  4. meta 可追加 `submitted_at` / `pr_url`
- 期望结果：worktree 保留，开发者可在同一隔离工作区继续迭代 PR feedback；即便 Codex review-loop 未通过、submit 门禁失败、PR 仅更新——worktree 状态都保持不变（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:498）。

### 场景 4：archive 安全清理 workflow-owned worktree

- 角色：完成 PR 合并的开发者
- 前置：PR 已合并；phase ∈ {testing, completed}
- 主流程（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:243）：
  1. 跑 `/requirement:archive`
  2. 先过 archive 现有门禁
  3. 校验 `worktree.owner=workflow` 且 `worktree.path` 在白名单：`.worktrees/` / `worktrees/` / `.claude/worktrees/`
  4. **从主仓根**执行 `git worktree remove <path>` + `git worktree prune`
  5. 若 owner=external 或路径不在白名单 → 输出 `worktree cleanup skipped: external`，不删除
- 期望结果：只清理自己创建的 worktree；外部 worktree 保留供 harness 自行管理。

## 非功能需求

- 性能：
  - bootstrap baseline 命令固定为 `make gates-validate`，要求不依赖网络、不依赖 bats / ruff / pytest 环境完整性（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:457）。
  - 完整验证 `make ci-local` 不在 bootstrap 默认范围内（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:467）。

- 兼容性（关键）：
  - 旧需求目录 `REQ-YYYY-NNN` 与 `feat/req-YYYY-NNN` 分支不迁移；新旧 key 在 status / list / submit / archive 同时可用（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:104）。
  - 旧需求 meta.yaml 缺 `worktree` 字段时视为 `enabled=false`，不报错（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:309）。
  - 分支前缀保持 `feat/req-` 不变（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:105）。
  - `infer_run_id_from_branch` 必须同时识别 `feat/req-YYYYMMDD-<slug>` 与 `feat/req-YYYY-NNN`（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:651）。

- 安全 / 合规：
  - cleanup 必须从主仓根执行；禁止在将被删除的 worktree 内 `git worktree remove`（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:99）。
  - cleanup 三重保护：`owner=workflow` + 路径在白名单 + 非 discard 不强删（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:669）。
  - `.worktrees/` 必须被 git ignore；运行时 fail-closed 校验未 ignore 即终止（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:100）。
  - 不自动删除用户或 harness 创建的外部 worktree（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:81）。
  - baseline 失败时保留 worktree（不自动删失败现场）（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:478）。

## 范围

- 包含：
  - 新增模块 `scripts/lib/worktree_manager.py`（detect / select / ignore-check / create / setup / cleanup）与 `scripts/lib/requirement_naming.py`（slug 规则 + key 生成 + legacy 兼容）（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:259）
  - 改 `scripts/lib/workflow_run.py` / `workflow_bootstrap.py`：默认 worktree + 新 key 命名 + meta.worktree 块 + rollback 顺序（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:638）
  - 改 `/workflow:submit` / `/requirement:submit` 输出与 archive cleanup 接入（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:647）
  - `.claude/workflows/requirement/standard-8phase.yaml` 顶层增加 `worktree` 配置组（policy=auto/never/require/current 四种）（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:355）
  - `.gitignore` 一次性加入 `.worktrees/`；运行时 fail-closed 校验（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:594）
  - `run-state.jsonl` 的 `workflow_started` 事件扩展 worktree 摘要（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:333）
  - 文档：`context/team/git-workflow.md` / README / onboarding / common pitfalls 增加 worktree 章节（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:541）
  - 测试：`tests/lib/test_worktree_manager.py` 单测 + 临时 repo 集成测试（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:585）

- 不包含：
  - 历史 `REQ-YYYY-NNN` 目录迁移；现有目录保持 legacy in-place（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:104）
  - 直通分支（feature / docs / chore）默认 worktree——仅文档推荐，不自动化（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:82）
  - daemon / DB / Web Dashboard（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:79）
  - feature 级隔离；粒度是 run / requirement（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:80）
  - 自动清理用户或 harness 创建的外部 worktree（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:81）
  - bootstrap 自动 commit（沿用当前 workflow 提交节奏，由开发者控制何时入库）（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:698）
  - 启动阶段默认跑 `make ci-local`；baseline 只跑 `make gates-validate`（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:467）

## 关键决策记录

按 spec §2 摘录 D-001~D-015（决策权威单源在 spec）：

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| worktree 粒度 | requirement run / feature / project | requirement run | spec D-001（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:91） |
| 默认启用范围 | requirement-only / 全部 workflow / 不默认 | requirement-only | spec D-002（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:92） |
| 默认 worktree 目录 | `.worktrees/` / `worktrees/` / 全局目录 | `.worktrees/` | spec D-003（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:93） |
| 已在 linked worktree 时行为 | 嵌套 / 复用 / 报错 | 复用 | spec D-004（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:94） |
| 脚本层 fallback | native tool / `git worktree` | `git worktree` | spec D-005（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:95） |
| provenance 记录位置 | meta.yaml / 单独文件 | meta.yaml | spec D-006（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:96） |
| submit 后 worktree 行为 | 立即清理 / 保留 | 保留 | spec D-007（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:97） |
| archive cleanup 范围 | 全部 / owner=workflow | owner=workflow | spec D-008（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:98） |
| cleanup 执行位置 | worktree 内 / 主仓根 | 主仓根 | spec D-009（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:99） |
| ignore 校验态度 | warning / fail-closed | fail-closed | spec D-010（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:100） |
| baseline 命令 | gates-validate / ci-local / 自定义 | `make gates-validate` | spec D-011（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:101） |
| 默认 / 逃生阀 | 强制 / 默认+开关 / 可选 | 默认 + `--no-worktree` | spec D-012（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:102） |
| key 命名格式 | `REQ-YYYY-NNN` / `YYYYMMDD-<slug>` | `YYYYMMDD-<slug>` | spec D-013（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:103） |
| 历史 ID 处理 | 迁移 / 兼容 | 兼容 legacy in-place | spec D-014（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:104） |
| 分支前缀 | `feat/req-` 保留 / 新前缀 | 保留 | spec D-015（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:105） |

## 验收（spec §13 直引 9 条 → 可测试断言）

1. `/workflow:run standard-8phase "x"` 在普通 repo 中默认创建 `requirements/YYYYMMDD-<slug>/` 与 `.worktrees/feat-req-YYYYMMDD-<slug>`；`git worktree list` 包含该 worktree（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:679）。
2. 已在 linked worktree 中运行时不会创建 nested worktree；meta `worktree.owner=external`（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:680）。
3. `meta.yaml` 能明确区分 `workflow` / `external` / `none` 三种 owner（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:681）。
4. bootstrap 任一步失败不残留半创建 worktree / branch / requirement 目录（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:682）。
5. submit 完成后 `git worktree list` 仍包含该 worktree（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:683）。
6. archive 只清理 `worktree.owner=workflow` 且路径在白名单的 worktree；外部 worktree 不被删除（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:684）。
7. 旧 `REQ-YYYY-NNN` 需求在 meta 无 worktree 字段时仍能 status / continue / submit（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:685）。
8. 同日同 slug 并行创建时，第二个目录稳定落到 `-02` 后缀（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:686）。
9. 单元测试和集成测试覆盖 naming / detection / creation / rollback / cleanup（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:687）。

## 待澄清清单

按确认点默认推进；当前所有"关键事实"都已绑定 spec 行号引用，本清单仅列执行级遗留项，留待技术预研 / 详细设计闭环：

1. CI / hook 维护者角色是否在用户场景中显式建模——当前默认未单列 `protect-branch` hook 的兼容性测试为独立场景，仅作为非功能需求一部分，由技术预研阶段验证 `git worktree add` 是否触发 hook 拦截。[待用户确认]

2. 完整 CI 触发时机——spec §7.2 提到 `make ci-local` 在 submit 前执行，但未明确"自动跑 / 手工触发"。默认假设：开发者手工跑；submit 门禁不强制阻塞，但 PR CI 会强制（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:471）。[待用户确认]

3. `--worktree-policy=current` 的 fail 行为细节 [待补充]
   - 内容：`policy=current` 但当前非 linked worktree → exit 1，stderr 输出 `worktree policy=current 要求在 linked worktree 中运行，当前在 normal repo`
   - 依据：对齐 spec §5.4 其他 policy 的 fail-closed 风格（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:370）
   - 风险：错误信息不够引导用户切到 worktree
   - 验证时机：detail-design 阶段在 `worktree_manager.create_worktree` 单测中覆盖
