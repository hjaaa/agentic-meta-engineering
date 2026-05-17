# Worktree 隔离能力完整迁移设计

| 字段 | 值 |
|---|---|
| 状态 | DRAFT - 待审阅 |
| 版本 | v0.1 |
| 起草日期 | 2026-05-17 |
| 起草人 | huangjian + Codex |
| 参考实现 | obra/superpowers `using-git-worktrees` / `finishing-a-development-branch` |
| 关联文档 | `context/team/git-workflow.md` / `.claude/workflows/requirement/standard-8phase.yaml` / `scripts/lib/workflow_run.py` / `scripts/lib/workflow_bootstrap.py` |
| 影响范围 | `/workflow:run` bootstrap / `/workflow:continue` cwd 语义 / `/requirement:submit` 与 `/workflow:submit` / archive cleanup / `.gitignore` / onboarding |

---

## 0. 一句话目标

把 Superpowers 的 worktree 隔离机制完整迁移到本项目的 workflow 体系：新需求默认在隔离 worktree 中推进，已有 worktree 自动复用，创建后跑 setup 与基线验证，submit 后保留 worktree，archive 或 discard 时按 provenance 安全清理。

---

## 1. 背景与动机

### 1.1 当前现状

当前 requirement 类 workflow 的启动路径是：

1. `/workflow:run standard-8phase "<title>"` 调 `scripts/lib/workflow_run.py`
2. 生成 `REQ-YYYY-NNN`
3. 在主工作目录下创建 `requirements/<REQ-ID>/`
4. 调 `git checkout -b feat/req-YYYY-NNN <base_branch>`
5. 后续所有阶段都在同一个工作目录中继续

这个模型满足单需求串行开发，但在以下场景开始暴露问题：

| 场景 | 问题 |
|---|---|
| 多个 active requirements 并行推进 | 同一个工作目录只能 checkout 一个分支，切换分支会打断另一个 run |
| 长需求跨会话恢复 | 当前目录状态可能已经被其他任务改变，`/workflow:continue` 容易续到错误分支 |
| subagent / review-loop 修改同仓文件 | 多路 agent 共用一个 working tree，冲突由人肉识别 |
| archive / cleanup | 只知道 branch，不知道这个 branch 是否绑定隔离目录，无法安全清理 |

`context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md` 曾把 "git worktree 隔离" 列为未来扩展，触发条件是"多 active runs 文件冲突"。当前需求就是把该扩展提前转为一等能力。

### 1.2 Superpowers 能力拆解

本次迁移覆盖 Superpowers 的完整 worktree 能力，而不是只搬一段文档。

| 能力 | Superpowers 行为 | 本项目迁移目标 |
|---|---|---|
| 已有隔离检测 | 先比较 `git-dir` 与 `git-common-dir`，submodule 单独排除 | 新增统一检测函数，所有创建/清理前调用 |
| 原生工具优先 | 若 harness 有 native worktree tool，优先使用 | 已在外部 native worktree 中时复用；脚本 fallback 用 `git worktree` |
| 创建前征得意图 | 不隐式创建未授权 worktree | requirement workflow 默认启用；提供 `--no-worktree` 逃生 |
| 目录选择 | 显式偏好 > `.worktrees/` > `worktrees/` > legacy global | 项目配置 > `.worktrees/` > legacy `.claude/worktrees/` > `worktrees/` |
| ignore 校验 | 项目内 worktree 目录必须被 git ignore | `.worktrees/` 纳入仓库 `.gitignore`；运行时 fail-closed 校验 |
| 创建 worktree | `git worktree add "$path" -b "$BRANCH_NAME"` | requirement bootstrap 创建 `feat/req-*` worktree |
| setup | 按项目类型自动 install/build | 本项目先跑最小基线；通用 detector 兼容 Node/Rust/Python/Go |
| baseline tests | 创建后跑测试，失败停住 | 跑 `make gates-validate` 起步；可配置扩展到 `make ci-local` |
| finishing 选项 | merge / PR / keep / discard | submit 保留，archive/discard 才清理 |
| provenance cleanup | 只清理自己创建的 worktree | meta 记录 `owner=workflow`，路径白名单双重保护 |

### 1.3 目标

| 目标 | 验证方式 |
|---|---|
| requirement workflow 默认隔离 | 新建需求后 `git worktree list` 出现对应 `feat/req-*` worktree |
| 已在 worktree 中不再嵌套创建 | 在 linked worktree 内运行 `/workflow:run`，meta 记录 external/reused |
| submit 后保留 worktree | `/workflow:submit` 完成后 worktree 仍存在，可继续处理 PR feedback |
| archive/discard 安全清理 | 仅清理 `owner=workflow` 且路径在允许目录下的 worktree |
| 失败可回滚 | bootstrap 任一步失败后不残留半创建目录、branch、worktree |
| 跨会话恢复正确 | 在 worktree 内 `/workflow:continue` 能从分支推断正确 run_id |

### 1.4 非目标

- 不引入 daemon、数据库或 Web Dashboard。
- 不把每个 feature 拆成单独 worktree；隔离粒度是一个 workflow run / requirement。
- 不自动删除用户或 harness 创建的外部 worktree。
- 不强制所有 generic workflow 都用 worktree；MVP 只对 `category=requirement` 默认启用。
- 不在运行时自动创建 `.gitignore` commit；`.gitignore` 变更由本次迁移实现一次性落地，运行时只校验。

---

## 2. 关键设计决策

| 决策代号 | 决策 | 理由 |
|---|---|---|
| D-001 | worktree 粒度为 requirement run，不是 feature | 一个需求目录、branch、PR 对应一个隔离工作区，语义最简单 |
| D-002 | requirement workflow 默认启用 worktree | 用户明确要求完整迁移；并行需求是当前扩展触发条件 |
| D-003 | 默认目录使用 `.worktrees/` | 对齐 Superpowers；`.claude/worktrees/` 保留给 Claude dispatch legacy |
| D-004 | 已在 linked worktree 内运行时复用当前目录 | 避免 nested worktree，尊重 Codex/Claude harness 原生隔离 |
| D-005 | 脚本层 fallback 使用 `git worktree` | Python CLI 无法调用 harness native tool；检测 external worktree 即可兼容原生工具 |
| D-006 | worktree provenance 写入 `meta.yaml` | cleanup 必须知道谁创建、能不能删 |
| D-007 | submit / PR 后不清理 worktree | PR feedback 仍需要原工作区迭代 |
| D-008 | archive / discard 才清理 workflow-owned worktree | 对齐 Superpowers finishing 语义 |
| D-009 | 清理必须从主仓根执行 | 避免在将被删除的 worktree 内执行 `git worktree remove` |
| D-010 | 运行时 ignore 校验 fail-closed | 未 ignore 的项目内 worktree 会污染 git status，必须阻断 |
| D-011 | baseline 先用轻量命令，完整 CI 作为可配置项 | `make ci-local` 依赖安装和 bats，启动需求时不宜默认跑完整套 |
| D-012 | `--no-worktree` 只作为显式逃生阀 | 本项目默认隔离，但允许紧急修复本地兼容 |

---

## 3. 目标用户流程

### 3.1 新需求默认流程

```text
用户：/workflow:run standard-8phase "示例需求"
  ↓
检查当前是否 linked worktree
  ↓
普通主仓 checkout：
  1. 生成 REQ-ID
  2. 写 requirements/<REQ-ID>/ 初始文件
  3. 从 develop 创建 .worktrees/feat-req-YYYY-NNN
  4. 在 worktree 中 checkout feat/req-YYYY-NNN
  5. meta.yaml 写入 worktree provenance
  6. 跑 setup + baseline
  7. 提示用户 cd 到 worktree 或由命令输出下一步路径
```

输出示例：

```text
workflow run 已启动（requirement, worktree）
  req_id:   REQ-2026-014
  branch:   feat/req-2026-014
  worktree: .worktrees/feat-req-2026-014
  baseline: make gates-validate PASS
  下一步: cd .worktrees/feat-req-2026-014 && /workflow:continue REQ-2026-014
```

### 3.2 已在外部 worktree 中启动

如果 `git rev-parse --git-dir` 与 `git rev-parse --git-common-dir` 不同，且不是 submodule：

1. 不创建新 worktree
2. 当前路径作为 externally-managed worktree
3. 若当前分支不是目标 `feat/req-*`，仍创建或切换分支，但不拥有目录清理权
4. meta 写 `worktree.owner: external`

### 3.3 submit 与 PR feedback

`/workflow:submit` 或 `/requirement:submit` 成功后：

- 推送当前 `feat/req-*` 分支
- 创建或更新 PR
- 保留 worktree
- meta 可追加 `submitted_at` / `pr_url`
- 不调用 `git worktree remove`

### 3.4 archive / discard 收尾

archive 成功后：

1. 确认 PR 已合并或用户显式要求 archive
2. 跑 archive 现有门禁
3. 若 `worktree.owner=workflow` 且路径在 `.worktrees/` / `worktrees/` / `.claude/worktrees/` 白名单内：
   - 从主仓根执行 `git worktree remove <path>`
   - 执行 `git worktree prune`
4. 若 `owner=external` 或路径不在白名单：
   - 不删除
   - 输出 `worktree cleanup skipped: external`

---

## 4. 架构设计

### 4.1 新增模块

新增 `scripts/lib/worktree_manager.py`，集中封装 worktree 行为，避免逻辑散落在 run / submit / archive。

| 函数 | 职责 |
|---|---|
| `detect_worktree_state(repo_root: Path) -> WorktreeState` | 判断 normal repo / linked worktree / submodule / detached |
| `select_worktree_location(repo_root, branch, preference) -> Path` | 按优先级选择 worktree 目录 |
| `ensure_worktree_dir_ignored(repo_root, location) -> None` | 项目内目录 ignore 校验 |
| `create_worktree(repo_root, branch, base_branch, location) -> WorktreeInfo` | 执行 `git worktree add` |
| `run_worktree_setup(worktree_path, policy) -> SetupResult` | 自动 setup + baseline |
| `resolve_main_repo_root(worktree_path) -> Path` | 从 worktree 找主仓根，供 cleanup 使用 |
| `cleanup_worktree_if_owned(meta, repo_root) -> CleanupResult` | provenance + path 白名单后清理 |

数据类：

```python
@dataclass
class WorktreeState:
    is_git_repo: bool
    is_linked_worktree: bool
    is_submodule: bool
    is_detached: bool
    branch: str
    worktree_path: Path
    git_dir: Path
    git_common_dir: Path

@dataclass
class WorktreeInfo:
    path: Path
    branch: str
    base_branch: str
    owner: Literal["workflow", "external", "none"]
    created: bool
```

### 4.2 `meta.yaml` 扩展

在 `requirements/<REQ-ID>/meta.yaml` 增加 `worktree` 组。旧需求缺字段时视为 `enabled=false`，保持兼容。

```yaml
worktree:
  enabled: true
  owner: workflow              # workflow | external | none
  path: .worktrees/feat-req-2026-014
  absolute_path: /abs/path/.worktrees/feat-req-2026-014
  branch: feat/req-2026-014
  base_branch: develop
  created_at: "2026-05-17 20:30:00"
  baseline:
    command: make gates-validate
    status: passed             # passed | failed | skipped
    completed_at: "2026-05-17 20:30:10"
  cleanup:
    policy: owned-only         # owned-only | never
    removed_at: null
```

### 4.3 `workflow_started` 事件扩展

`run-state.jsonl` 的 `workflow_started.data` 增加 worktree 摘要，便于 `/workflow:status` 不读完整 meta 也能展示。

```json
{
  "type": "workflow_started",
  "run_id": "REQ-2026-014",
  "data": {
    "workflow_name": "standard-8phase",
    "title": "示例需求",
    "worktree": {
      "owner": "workflow",
      "path": ".worktrees/feat-req-2026-014",
      "branch": "feat/req-2026-014"
    }
  }
}
```

### 4.4 配置入口

MVP 先在 `standard-8phase.yaml` 顶层增加 worktree 配置；后续可推广到所有 workflow。

```yaml
worktree:
  enabled: true
  policy: auto                 # auto | never | require | current
  location: .worktrees
  setup:
    baseline:
      command: make gates-validate
      required: true
```

策略语义：

| policy | 行为 |
|---|---|
| `auto` | 默认；普通 repo 创建，linked worktree 复用 |
| `never` | 不创建 worktree，沿用当前分支模式 |
| `require` | 必须创建或复用 worktree；失败即终止 |
| `current` | 必须已经在 linked worktree 中，否则终止 |

CLI 逃生参数：

```text
/workflow:run standard-8phase "示例需求" --no-worktree
/workflow:run standard-8phase "示例需求" --worktree-policy=current
```

---

## 5. Bootstrap 详细流程

### 5.1 当前流程替换点

当前 `_bootstrap_requirement()` 中的第 5 步是：

```python
_checkout_feature_branch(req_id, repo_root, base_branch=base_branch)
```

迁移后替换为：

```text
detect_worktree_state(repo_root)
  ↓
如果已在 linked worktree：
  bind_current_worktree()
  ensure_or_create_branch_in_current_worktree()
否则：
  ensure_worktree_dir_ignored()
  git worktree add <path> -b <branch> <base_branch>
  write bootstrap artifacts into worktree view
  run setup + baseline inside worktree
```

注意：`requirements/<REQ-ID>/` 必须最终出现在 worktree 目录里，因为后续修改都发生在 worktree 内。主仓根中是否能看到该目录取决于分支 checkout，不作为运行入口。

### 5.2 写文件顺序

推荐顺序改为：

1. 在主仓根生成 REQ-ID，但暂不把文件写到主仓工作区
2. 选择并创建 worktree
3. 在 worktree 路径下创建 `requirements/<REQ-ID>/`
4. 写 `meta.yaml` / `plan.md` / `process.txt`
5. 写 `run-state.jsonl`
6. baseline 通过后输出成功

这样可以避免主仓工作区出现未提交的新需求目录。

### 5.3 rollback 顺序

bootstrap 任一步失败时按以下顺序 best-effort 回滚：

1. 如果创建了 workflow-owned worktree：
   - `cd <main_repo_root>`
   - `git worktree remove <worktree_path>`
   - `git worktree prune`
2. 删除新建分支 `git branch -D <branch>`，仅限 branch 已创建且未被 worktree 占用
3. 删除 `requirements/<REQ-ID>/` 残留目录，分别检查主仓根与 worktree path
4. 输出原始失败原因，不用 rollback 失败掩盖根因

---

## 6. Setup 与 Baseline

### 6.1 自动探测

通用探测规则保留 Superpowers 风格：

| 文件 | setup |
|---|---|
| `package.json` | 优先 `pnpm install`，无 lockfile 时 fallback `npm install` |
| `Cargo.toml` | `cargo build` |
| `requirements.txt` | `python3 -m pip install -r requirements.txt` |
| `pyproject.toml` | 若有 poetry lock，则 `poetry install` |
| `go.mod` | `go mod download` |
| `Makefile` | 不自动 install，只跑配置的 baseline |

### 6.2 本项目默认 baseline

本项目默认：

```bash
make gates-validate
```

理由：

- 速度快
- 不需要网络
- 能验证 gate registry 基本可用
- 不依赖 bats / ruff / pytest 环境完整性

完整验证仍在开发完成和 submit 前执行：

```bash
make ci-local
```

### 6.3 Baseline 失败处理

baseline 失败时：

1. worktree 保留
2. branch 保留
3. meta 写 `worktree.baseline.status=failed`
4. 命令退出非零
5. 输出修复建议：进入 worktree 路径后排查，或 archive/discard 清理

不自动删除失败 worktree。原因是失败现场对排查有价值。

---

## 7. Submit / Archive / Cleanup 语义

### 7.1 Submit

submit 不改变 worktree 生命周期。

| submit 结果 | worktree 行为 |
|---|---|
| PR 创建成功 | 保留 |
| PR 更新成功 | 保留 |
| Codex review-loop 通过 | 保留 |
| Codex review-loop 未通过 | 保留，供修复 |
| submit 门禁失败 | 保留 |

### 7.2 Archive

archive 是唯一默认 cleanup 入口。

cleanup 前置条件：

- archive 现有门禁通过
- `meta.worktree.enabled == true`
- `meta.worktree.owner == "workflow"`
- `meta.worktree.path` 在允许目录下
- 当前路径不是将被删除的 worktree，或已先切到主仓根

允许目录：

```text
<repo>/.worktrees/
<repo>/worktrees/
<repo>/.claude/worktrees/
~/.config/superpowers/worktrees/<project>/   # 只做 legacy 识别，不作为本项目默认创建位置
```

### 7.3 Discard

新增或复用 discard 语义时必须二次确认，确认内容包含：

- branch 名
- worktree 路径
- 将删除的本地提交范围
- `requirements/<REQ-ID>/` 状态

用户输入精确确认词后才执行。

---

## 8. 文档与协作规范改动

### 8.1 `context/team/git-workflow.md`

新增 "Worktree 隔离策略" 小节：

- 新需求默认创建 `.worktrees/feat-req-*`
- feature / docs / chore 直通路径也推荐 worktree，但不强制
- 不要手动删除 `.worktrees/*`，使用 archive/discard
- submit 后 worktree 保留直到 PR feedback 处理完成

### 8.2 README / onboarding

把当前：

```text
git checkout -b feat/example → 改 → /code-review
```

调整为：

```text
git worktree add .worktrees/<branch> -b <branch> develop → 改 → /code-review
```

并说明完整需求直接用 `/workflow:run standard-8phase`，不需要用户手写 worktree 命令。

### 8.3 common pitfalls

新增坑位：

| 坑 | 修复 |
|---|---|
| 在主仓根继续需求 | `cd .worktrees/feat-req-*` 后 `/workflow:continue` |
| 手动 `rm -rf .worktrees/x` | 用 `git worktree remove` 或 archive |
| submit 后找不到改动 | 确认当前在对应 worktree 和 branch |
| external worktree archive 未清理 | 这是预期；外部工具拥有清理权 |

---

## 9. 测试计划

### 9.1 单元测试

新增 `tests/lib/test_worktree_manager.py`：

| 用例 | 断言 |
|---|---|
| normal repo 检测 | `is_linked_worktree=false` |
| linked worktree 检测 | `is_linked_worktree=true` |
| submodule guard | submodule 不误判为 worktree |
| detached HEAD | `is_detached=true` 且不误删 |
| 目录选择 | `.worktrees/` 优先 |
| ignore 校验 | 未 ignore 返回 fail-closed |
| path provenance | 非白名单路径 cleanup skipped |
| cleanup owned worktree | 调用 `git worktree remove` 后列表消失 |

### 9.2 集成测试

新增临时 git repo 集成测试：

1. 初始化 repo，创建 `develop`
2. 复制最小 `.claude/workflows` 与 `scripts/lib`
3. 跑 `workflow_run.main(["standard-8phase", "测试需求"])`
4. 验证：
   - `.worktrees/feat-req-*` 存在
   - `git worktree list` 包含 branch
   - `requirements/<REQ-ID>/meta.yaml` 有 worktree 字段
   - `run-state.jsonl` 有 worktree 摘要
5. 模拟 baseline 失败，验证 worktree 保留
6. 模拟 archive cleanup，验证 owned worktree 被删除，external worktree 保留

### 9.3 手工验证

```bash
git status --short
/workflow:run standard-8phase "worktree 迁移冒烟"
git worktree list
cd .worktrees/feat-req-YYYY-NNN
/workflow:status
/workflow:continue REQ-YYYY-NNN
```

---

## 10. 迁移步骤

### Phase 1: 基础能力

- 新增 `worktree_manager.py`
- 加单元测试覆盖 detection / location / cleanup
- `.gitignore` 增加 `.worktrees/`

### Phase 2: Bootstrap 接入

- 改 `workflow_run.py` / `workflow_bootstrap.py`
- requirement workflow 默认 `worktree.enabled=true`
- meta.yaml 模板增加 worktree 空结构
- bootstrap rollback 支持 worktree

### Phase 3: Submit / Archive 接入

- submit 输出 worktree 保留提示
- archive 调 cleanup
- status/list 展示 worktree path

### Phase 4: 文档与自举验证

- 更新 Git 工作流、README、onboarding、common pitfalls
- 用本仓库新建一个真实小需求验证隔离流程
- 跑 `make ci-local`

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| bootstrap 写文件根路径错乱 | 需求目录落在主仓而非 worktree | 所有路径参数显式传 `active_repo_root`，测试覆盖 |
| cleanup 误删外部 worktree | 丢用户工作 | `owner=workflow` + 路径白名单 + 非 discard 不强删 |
| baseline 过重导致启动慢 | 新需求体验下降 | 默认 `make gates-validate`，完整 CI 延后 |
| 旧需求缺 worktree 字段 | status/archive 报错 | 缺字段视为 legacy in-place |
| Codex/Claude harness 自带 worktree | 双重创建、phantom state | 先检测 linked worktree，external owner 不清理 |
| `.worktrees/` 未 ignore | git status 污染 | 实现期直接更新 `.gitignore`，运行时校验 |

---

## 12. 验收标准

1. `/workflow:run standard-8phase "x"` 默认创建 `.worktrees/feat-req-*`。
2. 已在 linked worktree 中运行时不会创建 nested worktree。
3. `meta.yaml` 能明确区分 `workflow` / `external` / `none` 三种 owner。
4. bootstrap 失败不会残留半创建 worktree。
5. submit 后 worktree 保留。
6. archive 只清理 workflow-owned worktree。
7. 旧需求在无 worktree 字段时仍能 status / continue / submit。
8. 单元测试和集成测试覆盖 detection、creation、rollback、cleanup。

---

## 13. 后续开放问题

| 问题 | 默认处理 |
|---|---|
| 是否让直通分支也自动创建 worktree | 文档推荐，暂不自动化 |
| 是否 baseline 默认跑 `make ci-local` | 否，启动阶段只跑轻量门禁 |
| 是否支持 global worktree 目录 | 仅 legacy 识别；默认项目内 `.worktrees/` |
| 是否自动提交 bootstrap commit | 不在本次设计内；沿用当前 workflow 提交节奏 |
