---
id: REQ-2026-014
title: "tech-feasibility · worktree 隔离能力完整迁移"
created_at: "2026-05-18"
refs-tech-feasibility: true
---

# REQ-2026-014 · 技术可行性评估

**可行性结论：high**。全部 4 个 Phase 无 blocker 级阻碍。两个新模块（`worktree_manager.py` / `requirement_naming.py`）均基于 Python 标准库，无新重依赖；关键替换点（`_checkout_feature_branch`、`_generate_req_id`、`archive_requirement` 内部步骤）已精确定位；`infer_run_id_from_branch` 已在 commit #899b45f 落地新旧双格式（来源：scripts/lib/common.py:27）；5 条待澄清项技术层面均有确定答案。

---

## 1. 模块可行性

### 1.1 `scripts/lib/requirement_naming.py`（新增）

**实现路径**：6 个纯函数，标准库（`re` / `datetime` / `os.path`），约 150 行，无外部依赖。`derive_slug_from_title` 对中文标题返回 `None`，不引入 pinyin / slugify 库（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:170）。`generate_requirement_key` 用原子 `mkdir(exist_ok=False)` 探测冲突，逻辑与现有 `_generate_req_id` 一致（来源：scripts/lib/workflow_run.py:100）。`is_legacy_requirement_key` 复用 `_REQ_ID_PATTERN = re.compile(r"^REQ-(\d{4})-(\d{3})$")` 正则（来源：scripts/lib/workflow_run.py:31）。

**可行性：high**。

---

### 1.2 `scripts/lib/worktree_manager.py`（新增）

**实现路径**：7 个函数 + 2 个 dataclass，约 250 行，`subprocess` + git 子命令。

- `detect_worktree_state`：执行 `git rev-parse --git-dir` 与 `--git-common-dir`，两值不同且不包含 `modules` 路径则为 linked worktree（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:225）。本仓已有大量 subprocess 范式（来源：scripts/lib/workflow_bootstrap.py:91）。
- `ensure_worktree_dir_ignored`：检查 `.gitignore` 是否包含目标目录；`.gitignore` 已有 `.claude/worktrees/`（来源：.gitignore:32），`.worktrees/` 一次性追加一行。
- `create_worktree`：调用 `git worktree add <path> -b <branch> <base_branch>`，错误包装为 `BootstrapError`，对齐 `_checkout_feature_branch` 模式（来源：scripts/lib/workflow_bootstrap.py:234）。
- `cleanup_worktree_if_owned`：三重保护——`owner=workflow` + 路径白名单 + 从主仓根执行（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:669）。
- `run_worktree_setup`：调用 `make gates-validate`（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:457），解析 exit code；`gates/run.py` 用 `Path(__file__).resolve().parents[2]` 定位 REPO_ROOT（来源：scripts/gates/run.py:65），不受 cwd 影响。

**关键技术风险**：`detect_worktree_state` 对 submodule 判定（`.git/modules/` 路径）需单测覆盖，防止误判为 linked worktree。

**可行性：high**。

---

### 1.3 `workflow_run.py` / `workflow_bootstrap.py` 改造

**替换点**：
1. `workflow_run.py::_generate_req_id`（来源：scripts/lib/workflow_run.py:100）→ `requirement_naming.generate_requirement_key`（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:641）。
2. `workflow_bootstrap.py::_checkout_feature_branch`（来源：scripts/lib/workflow_bootstrap.py:234）→ `worktree_manager.create_worktree` 路径（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:395）。
3. 写文件顺序改为：先创建 worktree → 在 worktree 路径下写产物，避免主仓工作区出现未提交目录（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:416）。
4. `_bootstrap_rollback`（来源：scripts/lib/workflow_bootstrap.py:348）新增步骤：`git worktree remove <path>` 先于 `git branch -D`，因 worktree 占用 branch（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:429）。

**关键技术风险**：写产物时 `active_repo_root` 必须传 worktree 路径而非主仓根，否则 requirement 目录落到主仓。detail-design 阶段集成测试断言落点。

**可行性：high**。

---

### 1.4 `/requirement:submit` 改造

**改造范围**：Skill 文档层（`managing-requirement-lifecycle` + submit.md），无独立 Python submit 脚本（来源：.claude/commands/requirement/submit.md）。改造内容：成功提示后追加 `worktree retained at <path>; use /requirement:archive to clean up`，约 5 行 Markdown 修改。submit 不调用 `git worktree remove`（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:494）。

**可行性：high**，改动极小。

---

### 1.5 `/requirement:archive` 改造

**改造范围**：`archive_runner.py::archive_requirement` 内部插入 `cleanup_worktree_if_owned(meta, REPO_ROOT)` 步骤，位于 5 项预检通过后、写 meta.yaml 之前。`meta` 变量在 line 641 已加载，无需改接口签名（来源：scripts/lib/archive_runner.py:614）。接口契约 frozen（来源：.claude/commands/requirement/archive.md:69），内部添加步骤不破坏向后兼容。外部 worktree 跳过清理并输出 `worktree cleanup skipped: external`（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:252）。

**可行性：high**。

---

### 1.6 `standard-8phase.yaml` worktree 配置组

**改造范围**：顶层追加 `worktree` 块（policy=auto/never/require/current）（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:355）。`workflow_loader.py` 的 `_validate_schema_top` 只校验 `TOP_REQUIRED=("name","version","category","nodes")`，不拒绝额外顶层字段（来源：scripts/lib/workflow_loader.py:98），不触发 W100。`result.workflow = raw` 透传完整 dict，`workflow.get("worktree")` 可直接使用（来源：scripts/lib/workflow_loader.py:188）。

**可行性：high**，无 schema 修改风险。

---

## 2. 待澄清消化

### #1 protect-branch hook 兼容性（来源：requirements/REQ-2026-014/artifacts/requirement.md:184）

**技术结论**：`pre-tool-use-guard.sh` 的 `main()` case 只处理 `Agent/Edit/Write/MultiEdit/Bash` 工具（来源：.claude/hooks/pre-tool-use-guard.sh:93）。`git worktree add` 通过 Python `subprocess.run` 调用，不触发 hook。即使通过 Bash 工具调用，`check_branch_protect` 检查当前分支（worktree 内为 `feat/req-*`，不命中 main/master/develop），`check_bash_writes_review` 只检查 reviews/*.json 写入——均不拦截。

**消化决策**：技术上不冲突，维持"不新增独立场景"。**必须产出**：`tests/integration/test_worktree_protect_branch.bats`——在临时 git repo 中创建 `.worktrees/feat-req-smoke`，模拟 Edit 工具调用（stdin JSON），断言 hook rc=0 且 stderr 为空（验证 `check_branch_protect` 在 worktree 内不误触发）。

---

### #2 完整 CI 触发时机（来源：requirements/REQ-2026-014/artifacts/requirement.md:194）

**技术结论**：`make ci-local` 包含 `ci-local-deps`（pip install，来源：Makefile:36），依赖网络，不适合 bootstrap 强制跑。submit 门禁当前无 `make ci-local` 检查（来源：.claude/commands/requirement/submit.md:22）。

**消化决策**：确认手工触发；submit 门禁不强制阻塞 `make ci-local`；PR CI 强制。维持需求默认假设。

---

### #3 `policy=current` fail 行为（来源：requirements/REQ-2026-014/artifacts/requirement.md:196）

**消化决策**：当 `policy=current` 但当前为普通 repo 时，exit 1，stderr 输出 `worktree policy=current 要求在 linked worktree 中运行，当前在 normal repo；请先 cd 到 .worktrees/feat-req-<key> 目录后重试`。对齐 fail-closed 风格（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:370）。detail-design 阶段在 `worktree_manager` 单测中覆盖。

---

### #4 外部 worktree dirty workspace 处理（来源：requirements/REQ-2026-014/artifacts/requirement.md:202）

**消化决策**：`git status --porcelain` 非空则 fail-closed，exit 1，stderr 提示 `当前外部 worktree 存在未提交改动，请先 commit / stash / discard 后重试，或加 --no-worktree 显式逃生`（来源：requirements/REQ-2026-014/artifacts/requirement.md:203）。untracked `.worktrees/` / `.claude/` 目录通过路径前缀白名单豁免，避免误判。自动 stash 风险过高，不采用（来源：requirements/REQ-2026-014/artifacts/requirement.md:204）。

---

### #5 `/workflow:submit` / `/workflow:archive` 新建（来源：requirements/REQ-2026-014/artifacts/requirement.md:208）

**消化决策**：本需求**不新建** workflow:* slash command，仅改 `/requirement:*` 兼容入口（来源：requirements/REQ-2026-014/artifacts/requirement.md:210）。**上线前必须**同步反修 spec → v0.3，标注 "workflow:submit/archive 留作后续"，避免 spec line 13 与实际范围不一致。

---

## 3. SLA 实测

**目标**：bootstrap 端到端 ≤ 60s（来源：requirements/REQ-2026-014/artifacts/requirement.md:100）。

**基于代码分析的合理预估**（未实测）：

- `git worktree add .worktrees/feat-req-smoke develop`：1-5s（本地 SSD）
- `python3 scripts/gates/run.py --validate-registry`（`make gates-validate` 实际内容，来源：Makefile:7）：1-3s（纯 Python 文件/YAML 校验）
- 目录创建 + meta.yaml 写入 + jsonl 事件：< 2s

**合计预估 < 15s**，远低于 60s 基准，有充分余量。

**实测方案** [待补充]：
- 内容：Phase 2 完成后，在 macOS 主仓 develop 状态下 `time python3 scripts/lib/workflow_run.py standard-8phase "sla-smoke" --slug sla-smoke` 观察 wall-clock
- 依据：实测值为 plan.md SLA 终值唯一可信来源（来源：requirements/REQ-2026-014/artifacts/requirement.md:101）
- 风险：`make gates-validate` 在 worktree 内若有路径依赖，需传 `CLAUDE_GATES_AUDIT_ROOT` 等环境变量（来源：scripts/gates/run.py:47）
- 验证时机：Phase 2 实施后，plan.md 回写实测值

---

## 4. 风险表（基于 spec §12 R1~R8 重评）

| ID | 风险 | 概率 | 影响 | 现状 | 缓解 |
|---|---|---|---|---|---|
| R1 | bootstrap 写产物 active_repo_root 传错，req dir 落主仓 | 中 | 高 | 真实风险；写文件顺序改造（先 worktree）缓解（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:416） | 集成测试断言落点；显式传 active_repo_root |
| R2 | 中文标题纯脚本入口缺 slug，fail-closed 体验差 | 中 | 低 | 已设计 --slug 逃生（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:168） | 命令层生成 slug；脚本层 fail-closed + 提示 |
| R3 | 旧代码硬编码 REQ-YYYY-NNN 遗漏（Skill 文档 / status / list） | 中 | 中 | infer_run_id_from_branch 已缓解（来源：scripts/lib/common.py:27）；仍需全仓排查 | 抽 requirement_naming.py 统一入口；新旧 key 并测 |
| R4 | 同日同 slug 跨进程并发创建竞争 | 低 | 低 | 原子 mkdir 重试与现有 _generate_req_id 一致（来源：scripts/lib/workflow_run.py:133） | 单进程充分；跨进程极端场景留 detail-design 精确化 |
| R5 | cleanup 误删外部（harness 自有）worktree | 低 | 高 | 三重保护设计完整（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:669） | owner=workflow + 路径白名单 + 非 discard 不强删 |
| R6 | make gates-validate 在 worktree 内 REPO_ROOT 解析偏差 | 中 | 中 | gates/run.py 用 __file__ 定位（来源：scripts/gates/run.py:65），不受 cwd 影响 | Phase 2 实测验证；偏差时用环境变量覆盖 |
| R7 | 旧需求 meta.yaml 缺 worktree 字段 → status/archive KeyError | 低 | 低 | 已设计 enabled=false 兼容（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:309） | 防御性 `meta.get("worktree", {})` |
| R8 | Codex/Claude harness 自带 worktree 嵌套创建 | 中 | 中 | detect_worktree_state 先检测（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:225） | 场景 2 集成测试覆盖；harness 冒烟 |

---

## 5. 4 阶段工时估算

基于 spec §11 4 阶段功能清单（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:631）：

| Phase | 主要内容 | 估算（h） |
|---|---|---|
| Phase 1：命名与基础能力 | requirement_naming.py（6h）+ worktree_manager.py（14h）+ 单测 11 用例（8h）+ .gitignore（0.5h） | 28.5 |
| Phase 2：Bootstrap 接入 | workflow_run key 替换（3h）+ bootstrap worktree 路径（6h）+ rollback 改造（3h）+ meta 模板 + yaml 配置组（3h） | 15 |
| Phase 3：Submit / Archive 接入 | submit 文档改造（2h）+ archive_runner cleanup（5h）+ status/list 展示（3h） | 10 |
| Phase 4：文档与自举验证 | 文档更新（4h）+ 集成测试（6h）+ protect-branch bats（2h）+ 自举 ci-local（2h） | 14 |
| **合计** | | **67.5h（≈ 8.5 人天）** |

**人天 breakdown**：设计 1.0d + 开发 6.0d + 测试 1.5d = **8.5d**

---

## 6. GO / NO-GO

**结论：GO**

所有模块均有清晰实现路径，无外部新依赖，无 blocker。

**上线前必须解决**：
1. spec 反修 → v0.3（标注 /workflow:submit / /workflow:archive 留作后续），避免范围漂移（详见 §2 待澄清消化 #5）
2. `.worktrees/` 追加至 `.gitignore`（Phase 1 第一个 commit 完成）
3. `tests/integration/test_worktree_protect_branch.bats` 产出并通过（详见 §2 待澄清消化 #1）

---

## 待澄清清单

本预研阶段遗留以下执行级待澄清项，留待 detail-design / Phase 2 阶段闭环：

1. SLA 实测值（详见 §3 [待补充] 块）
   - 内容：Phase 2 完成后实测 `time python3 scripts/lib/workflow_run.py standard-8phase ...` wall-clock
   - 依据：预估 <15s 远低于 60s 基准，但需实测确认作为 plan.md SLA 终值
   - 风险：worktree 内 REPO_ROOT 解析可能需 `CLAUDE_GATES_AUDIT_ROOT` 环境变量覆盖
   - 验证时机：Phase 2 实施后
