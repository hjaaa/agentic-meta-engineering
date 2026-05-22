# /requirement:archive 执行细则

`/requirement:archive` 命令的子动作规则——伞形 Skill `managing-requirement-lifecycle` 在识别到「归档」意图时按本文执行。实现入口 `scripts/lib/archive_runner.py::archive_requirement`，签名见 `requirements/REQ-2026-007/artifacts/detailed-design.md` §3.1，**已 frozen**。

适用阶段：`phase ∈ {testing, completed}`。`testing → completed` 由 archive 命令推进（不走 `/workflow:next [F-012 待落地]`，因为含副作用动作）。

---

## 双阶段拓扑（F-001 / F-003）

archive 流程拆分为**两个阶段**，不可逆操作（分支删除 / worktree 清理）被整体推迟到阶段 2（finalize），确保 reviewer 对归档 commit 完成审查后再执行破坏性动作。

| 阶段 | 命令 | 执行内容 | 终止时机 |
|---|---|---|---|
| **阶段 1 archive** | `python3 scripts/lib/archive_runner.py <req_id>` | 写 meta.yaml + process.txt + 经验沉淀 → commit → push → 自动创建归档 PR → 写 archive_pr_number | 等 reviewer 审查、merge 归档 PR |
| **阶段 2 finalize** | `python3 scripts/lib/archive_runner.py <req_id> --finalize` | 校验归档 PR 已 merged → 删本地 feat 分支 → 删远程 feat 分支 → cleanup worktree | 终态（不可逆） |

**状态流转示意**（`archive_pr_number × phase`，来源：detailed-design §8.1）：

```text
phase=testing, pr_number=0
        │ archive_requirement()
        ▼
phase=completed, archive_pr_number=0   ← 半完成（可重跑 archive）
        │ idempotent 重跑 archive_requirement()
        ▼
phase=completed, archive_pr_number=42  ← 归档 PR 创建完成，等 merge
        │ finalize_requirement()（PR merged 后）
        ▼
phase=completed, archive_pr_number=42  ← 终态
worktree cleared, branches deleted
```

**关键约束**：
- 阶段 1 archive：写 meta + commit + push + 开 PR，**不**执行删除类动作
- 阶段 2 finalize：预检归档 PR 已 merged，才执行删本地分支 / 删远程分支 / cleanup worktree
- `--finalize` 在 `_delete_remote_branch` 下才生效的 `--legacy-resurrect-remote` 旗标（F-007）详见本文 §B

---

## 0. 何时调用 archive（主 Agent 行为约束）

archive 是**用户显式触发**的动作，不是 PR 合并的自动后置步骤。

### 0.1 「PR merged」≠「立刻 archive」

PR 合并只代表代码进入 base_branch，**不代表测试已闭环**。常态时间窗口：

```text
PR merged ──┐
            ├─→ 测试人员回归 / 验收
            ├─→ 发现 bug → 新一轮 hotfix（原 feat 分支或新 hotfix 分支补 commit）
            ├─→ 反复直到验收通过 ←─────┐
            └─→ 用户明确说"可以归档了" ┴─→ archive
```

修复期间 `phase` 仍停留在 `testing`，不应推进到 `completed`。

### 0.2 触发时机白名单（仅以下信号才调 archive）

1. 用户明确口头指令：「归档」「archive」「收尾」「关掉这个需求」
2. 用户显式确认测试反馈窗口已闭环：「测试通过没问题了」「可以归档了」「测试人员说没 bug 了」
3. `--force` 异常恢复路径（用户已知风险）

**禁止**：主 Agent 看到 `gh pr view` state=MERGED 就自动跑 archive。
**不确定**：主 Agent 必须问，不替用户判断"测试是否完成"。

**前置硬要求**（预检 5）：触发 archive 前 `meta.yaml.lessons_extracted` 必须为 True；
否则 archive_runner 在预检 5 直接 SystemExit(1)。意思是即使用户已说「可以归档了」，
若经验沉淀未跑或脚本未把字段翻为 True，archive 也不会进入 §2——是机器强制，
不是 AI 自觉判断。需要先跑 `/knowledge:extract-experience <req_id>` 完成沉淀。

### 0.3 分支位置约束

所有 archive bookkeeping 操作都在**原开发分支**（`meta.yaml.branch`，例 `feat/req-yyyy-nnn`）上进行；
**删本地分支是整个 archive 的最后一步**——archive_runner 自动 `git switch <base_branch>` 后再删，
用户不需要中途手动切分支也不需要分两次跑 archive 命令。

| 步骤 | 应在哪个分支 |
|---|---|
| §1 预检 / §2.1 写 meta.yaml / §2.2 写 process.txt / §2.3 经验沉淀 / §2.4 删远程分支 | **原开发分支**（`feat/req-yyyy-nnn`）|
| §2.4 删本地分支（最后一步） | archive_runner 内部自动 `git switch <base_branch>` 后删，无需用户操作 |

为什么经验沉淀也在原 feat 分支：保留 git blame / file history 视角与开发期一致；切到 base_branch 后 `claude /knowledge:extract-experience` 会丢失分支上下文。

为什么删本地分支放最后：删 feat 分支会强制离开 feat，把它放最后让前面的所有 bookkeeping
操作都能享受 feat 分支上下文（git history / 文件视图）。远程删则不需要切走，因此放在
本地删之前（§2.4 内 sub-step 顺序：远程 → 自动切 base → 本地）。

主 Agent **禁止**在调 `/requirement:archive` 前主动 `git checkout`：

- ❌ 错误：`PR merged → git checkout develop → /requirement:archive`
- ✅ 正确：`PR merged → 留在 feat 分支等用户触发 → archive 一次跑完 §1~§2.5（最后一步自动切 base + 删 feat）`

---

## 1. 5 项预检（硬门禁）

| # | 检查项 | 失败错误码 | 失败文案 |
|---|---|---|---|
| 1 | `phase ∈ {testing, completed}` | `R-ARCHIVE-PHASE` | `当前 phase=<X>，期望 testing 或 completed` |
| 2 | `git status --porcelain` 输出为空 | `R-ARCHIVE-DIRTY` | `工作目录有未提交改动；先 commit 再 archive` |
| 3 | `meta.yaml.pr_number` 非 0 且非空 | `R-ARCHIVE-NO-PR` | `meta.pr_number 缺失；先跑 /requirement:submit` |
| 4 | `gh pr view <pr_number> --json state` == `MERGED`（除非 `--force`） | `R-ARCHIVE-PR-NOT-MERGED` | `PR #<N> state=<X>，未合并；等 merge 或加 --force` |
| 5 | `meta.yaml.lessons_extracted is True` | `R-ARCHIVE-LESSONS-NOT-EXTRACTED` | `先跑 /knowledge:extract-experience <req_id>，Skill 收尾会调用 scripts/lib/mark_lessons_extracted.py 把字段翻为 True` |

任一预检失败 → `SystemExit(1)` + stderr 输出错误码与文案；不进入第 5 步。

`--force` 仅跳过预检 4（PR-merged，异常恢复用），**不**跳过预检 5（lessons_extracted）。
预检 5 的硬约束动机：归档时强制要求经验已沉淀，避免「跑完 archive 才发现忘了沉淀经验」的常见漏洞——
该规则用脚本保障（archive_runner 拦下 + mark_lessons_extracted.py 翻字段），不依赖 AI / 人工自觉。

`lessons_extracted` 字段的写入路径是单向且受控的：

- **写入**：只能由 `scripts/lib/mark_lessons_extracted.py` 在 `/knowledge:extract-experience` Skill
  收尾时调用；不允许 AI Edit / Write 工具或人工编辑直接翻
- **撤销**：通过 `git revert` 撤销当次 archive 元数据 commit，不提供 mark 脚本的 `--revert`

---

## 1.5 archive 前 CI gate 预检（D-002 / D-008）

5 项硬门禁过后、调 `archive_requirement` **之前**，主 Agent 必须先执行：

```bash
python3 scripts/gates/run.py --trigger=ci --strict
```

期望 `exit 0` 才继续 archive。**为什么需要这一步**：framework R-rule 全集（R001~R007）
仅在 `--trigger=ci` 下完整跑（来源：scripts/gates/registry.yaml），phase-transition / submit
触发的 R-rule 子集可能未覆盖所有 stale 场景；archive 推 chore PR 到 develop 后才在 CI 暴露
就是 hotfix（详见 `context/team/experience/archive-completed-triggers-framework-rule-fullset.md`）。

### refresh-only-current-req 处置原则（D-008）

`--trigger=ci` 不支持 `--req` filter（来源：scripts/gates/plugins/review_verdict.py）；预检会扫
**全仓所有需求**，可能暴露其它历史 REQ 的 R005 hash drift。处置：

1. 列出所有 R005 finding 对应的 REQ（按 finding 信息中的 `requirement_id` / `meta_path` 字段分类）
2. **当前正在归档的 REQ**：refresh hash（reviewer Agent 重审 + signoff），必须修
3. **其它历史 REQ**：单独记 follow-up 不强行修；若所有 R005 finding 都属于其它 REQ → 手动 ack 后继续 archive
4. 主 Agent 在 `notes.md` 追加一行记录手动 ack 的 REQ 列表 + 原因

### 升级路径（B1 / B2）

本步骤是 B3 路径——纯文档兜底 + 终端 reminder（D-002）。如果未来 archive 月频次显著上升导致
人执行流程不可靠，可升级为 B1（archive_runner 临时 yaml override 跑 R-rule 全集）或 B2（写后
rollback）路径。

---

## 2. 阶段 1 执行（预检通过后）

阶段 1 的职责：**写 meta + commit + push + 开归档 PR**。删除类不可逆动作（分支删除 / worktree 清理）已整体迁移到阶段 2（finalize，见本文 §A）。

### 2.1 原子写 meta.yaml

- 若 `phase` 不是 `completed`，改为 `completed`
- `archived_at` 写入「写入时刻的 Asia/Shanghai now」（格式 `YYYY-MM-DD HH:MM:SS`；详见 `context/team/engineering-spec/time-format.md`）
- **重跑安全**：`archived_at` 已非空时**保留旧值**（首次归档时间不被覆盖）
- 实现：写到 `meta.yaml.tmp` 后 `os.replace()` 覆盖（避免中间状态被 gate 读到）

### 2.2 追加 process.txt `[archived]` 事件

格式遵守 `requirement-progress-logger` SKILL.md 的硬约束：

```text
YYYY-MM-DD HH:MM:SS [archived] (PR #<num> merged at <archived_at>)
```

- 时间戳取 **append 那一刻** 的 Asia/Shanghai now（保证行序与时序一致）
- **幂等约束**（detailed-design §4.3）：append 前 grep 现有 `process.txt`，若已存在 `[archived]` 行则**跳过**——覆盖三场景：(1) 用户重跑 archive；(2) `--force` 强制重跑；(3) 双窗口并发误触
- 不允许直接 `>>` 走其他通道——本 Skill 是 process.txt 的唯一写入通道

### 2.3 经验沉淀（可选）

- 触发问句 `kind="experience"`，按 §3 交互通道决议
- 答 y → 调 `claude /knowledge:extract-experience <req_id>`（subprocess）
- 答 N（含默认 N）→ `outcome=no`
- `--no-experience` flag → 不问，`outcome=skipped`

**fail-soft**：subprocess 不可用 / 退出非零 → `outcome=failed` + `error_messages` 记原因，archive 仍 exit 0。

### 2.4 commit + push（archive metadata commit）

archive 阶段 1 在写完 meta / process.txt / 经验沉淀后，自动 commit 并 push（来源：`scripts/lib/archive_runner.py:1086`）：

**commit message 前缀约定**（`ARCHIVE_COMMIT_RE`，来源：`scripts/lib/archive_runner.py:128`）：

- 格式：`archive(<req_id>): metadata`
- 严格正则：`^archive\(<req_id>\): metadata$`
- 举例：`archive(20260521-archive-runner-auto-pr): metadata` ✓ / `chore(archive): metadata` ✗

**idempotent 跳过规则**：`HEAD commit subject` 命中 `ARCHIVE_COMMIT_RE(req_id)` → 整步跳过（archive 重跑安全）。

**非匹配不触发跳过**：如果 HEAD commit 用了其他格式（如 `chore(archive): metadata`），重跑时不识别为 idempotent，会新建 commit——这是故意的，防止非 archive 产生的 commit 被误认为已归档。

**commit 白名单范围**（来源：detailed-design §1.2，`C-1` 决策）：
- `requirements/<req_id>/meta.yaml` + `requirements/<req_id>/process.txt` + `requirements/<req_id>/notes.md` + `requirements/<req_id>/artifacts/`
- `context/team/experience/`（经验沉淀产物）
- `context/project/*/experience/`（项目经验产物）
- `context/INDEX.md` / `context/team/experience/INDEX.md`
- 非白名单 `context/` 改动 → fail-closed `R-ARCHIVE-CONTEXT-DIRTY`，exit 1

### 2.5 archive PR 自动创建语义

archive metadata commit push 成功后，`_create_archive_pr`（来源：`scripts/lib/archive_runner.py:929`）自动创建归档 PR：

```bash
gh pr create \
  --base develop --head feat/<req_id> \
  --title "archive(<req_id>): metadata + lessons" \
  --body-file <渲染后的 archive-pr-body>
```

**PR body 模板**：`.claude/skills/managing-requirement-lifecycle/templates/archive-pr-body.md.tmpl`，含三个占位符：

| 占位符 | 替换值 |
|---|---|
| `__REQ_ID__` | `req_id` 字符串 |
| `__PR_NUMBER__` | `meta["pr_number"]`（需求 PR number，非归档 PR number） |
| `__BRANCH__` | `meta["branch"]`（feat 分支名） |

**idempotent 处置**（先调 `gh pr list --head feat/<req_id> --base develop --state all`）：

| 状态 | 处置 |
|---|---|
| OPEN | 复用已有 PR number（`archive_pr_action="reused"`），不重建 |
| MERGED 且 `meta.archive_pr_number=0` | fail-closed `R-ARCHIVE-PR-ALREADY-MERGED`（归档 PR 已被手动 merge 但 number 未落地，需人工恢复） |
| CLOSED | fail-closed `R-ARCHIVE-PR-CLOSED`（用户手动关了 PR） |
| PR number 冲突 | `meta.archive_pr_number > 0` 且 != gh 返回 number → fail-closed `R-ARCHIVE-PR-NUMBER-MISMATCH`（C-3 决策） |
| 不存在 | 正常创建（`archive_pr_action="created"`） |

**后续流程**：PR 创建后，`archive_pr_number` 写入 `meta.yaml`（`_write_archive_pr_number`，来源：`scripts/lib/archive_runner.py`），等待 reviewer 审查 + merge 后，用户跑 `--finalize` 触发阶段 2。

### 2.6 终端反馈（6 行 + 可选 errors 段）

按 spec §5.3 第 5 步原样渲染：

```text
✅ REQ-YYYY-NNN archived
   phase: completed
   archived_at: 2026-05-04 19:30:00
   experience: ✅ yes / ⏭ no / ⏭ skipped / ❌ failed
   archive PR: #42 (https://github.com/.../pull/42)
```

任意 `outcome=failed` 时追加 `errors:` 段列出 `error_messages`，便于排查。

archive 命令始终 exit 0（除非 5 项预检挂）。

---

## 3. 三问交互通道（D-016 A 案锁死）

按交互通道决议优先级：

1. 若对应 `yes_<x>` flag 已设 True → 跳问，按 y 处理
2. 否则若 `prompts_callback` 注入 → 调 callback，由主 Agent 串行问
3. 否则（CLI 自动化无 callback）→ 默认按 N 处理（保守不删 / 不沉淀）

`callback` 入参为 `ArchivePrompt(kind, question, default=False)`，返回 `bool`。callback 抛异常视同回答 N（不抛出影响 archive 流程）。

主对话场景：伞形 Skill 装配 callback，把 `question` 渲染给用户、解析用户回复（y/n）后回填 callback 返回；CLI 自动化场景：调用方传 `yes_*` flag 跳问。

---

## 4. 错误降级矩阵（副作用动作）

| 动作 | 失败现象 | 降级策略 |
|---|---|---|
| 经验沉淀 | `claude /knowledge:extract-experience` 调用失败 / 退出非零 | 打印 stderr 原因 → `outcome=failed`，archive 仍 exit 0 |
| 本地分支 -d | git 拒绝（squash merge / 未合并 / `-d` 安全模式拒删） | 透传 git error → `outcome=failed` |
| 本地分支 -d | `<branch> == base_branch` | `outcome=failed`，不调 git（防误删 develop） |
| 本地分支自动切 base | `base_branch` 为空 | `outcome=failed` + 提示用户手动切；**不**自动 `-D` |
| 本地分支自动切 base | `git switch <base_branch>` 失败（base 本地缺失 / detached / 工作目录脏） | 透传 git error → `outcome=failed` |
| 远程分支删 | `remote ref does not exist` | 折叠为 `already-deleted`，**不报错** |
| 远程分支删 | 网络 / 401 / 403 | 透传 error → `outcome=failed` |

副作用动作 `outcome` 全部记录到 `ArchiveResult`。archive 命令始终 exit 0（除非 5 项预检挂）。

---

## 5. 与其他规则的关系

- `meta-schema.yaml.fields.archived_at`（context/team/engineering-spec/）：`archived_at` 写入仅当 phase=completed，本文 §2.1 是其唯一执行入口
- `requirement-progress-logger` SKILL.md：本文 §2.2 走的是 progress-logger 的格式约束（事件标签 `[archived]` 已加入白名单）
- `submit-rules.md`：archive 强依赖 `meta.pr_number` 已被 submit 回写，预检 3 失败时引导用户先跑 `/requirement:submit`

---

## 6. 测试与自举

- 单测：`tests/lifecycle/test_archive.py` 覆盖 TC-F3-1 ~ TC-F3-7（4 预检 + 三问 yes/no + 失败降级）
- finalize 单测：`tests/lifecycle/test_finalize.py` 覆盖 TC-F3-1 ~ TC-F3-18（happy path + 5 keep flag 组合 + --force / --legacy-resurrect-remote）
- 沙盒 e2e（V-01）：TC-F3-8，REQ-2099-007 走全链路
- 自举（V-08）：本需求 PR merge 后用 `/requirement:archive` 归档自身——`yq '.archived_at' meta.yaml` 非空 + `grep -c '\[archived\]' process.txt == 1`（幂等校验）

---

## §A. 阶段 2：`finalize_requirement`（三重保护 + keep flag）

阶段 2 负责执行所有不可逆动作（删本地 / 删远程 feat 分支 + cleanup worktree），在归档 PR merged 后由用户主动触发（来源：`scripts/lib/archive_runner.py:1887`）。

### §A.1 触发方式

```bash
# Skill 入口
/requirement:archive --finalize

# CLI 直接调用
python3 scripts/lib/archive_runner.py <req_id> --finalize
```

### §A.2 `--finalize` 及 5 个 keep flag

| flag | 默认 | 语义 / 适用场景 |
|---|---|---|
| `--finalize` | （无，需显式传入） | 触发阶段 2 收尾：检验 archive PR merged → 删本地 + 远程 feat 分支 → cleanup worktree |
| `--yes-finalize` | false | 跳过「确认删除本地+远程 feat + worktree」问询（CI / 自动化脚本使用） |
| `--keep-local-branch` | false | 跳过删本地 feat 分支（保留本地 git history 供事后查阅） |
| `--keep-remote-branch` | false | 跳过删远程 feat 分支（外部协作仍需可见、或远程已被 auto-delete 清掉） |
| `--keep-worktree` | false | 跳过 cleanup worktree（用户仍在 worktree 内继续操作时） |
| `--legacy-resurrect-remote` | false | 老需求兜底：扩大 already-deleted 识别到 `not found` / `unknown`（详见 §B） |

### §A.3 finalize 12 步顺序

```text
1. _rebind_to_main_repo          → REPO_ROOT 绑到主仓根
2. _load_meta                    → 读 meta.yaml
3. §3.4 警告文案                  → --force / --force+--yes-finalize 警告
4. _precheck_archive_pr_merged   → 校验 archive PR merged（--force 跳过）
5. 合并问询（kind="finalize"）    → --yes-finalize 跳过；N → exit 0
6. os.chdir(main_repo_root)      → fail-closed
7. git pull --ff develop          → fail-closed（R-FINALIZE-PULL-FAILED）
8. _cleanup_worktree_before_archive → --keep-worktree 跳过
9. _delete_local_branch(strict=True) → --keep-local-branch 跳过
10. _delete_remote_branch(legacy_resurrect=...) → --keep-remote-branch 跳过
11. _log_finalize_event           → 写 process.txt [finalized] 事件
12. _render_summary(stage="finalize") → 终端反馈
```

### §A.4 三重保护（worktree cleanup 条件）

`_cleanup_worktree_before_archive` 内的三件套**同时满足**才会真删（`os.chdir(主仓根)` 已在第 6 步完成，来源：detailed-design §3 C-2 决策）：

1. `owner=workflow`（external worktree 跳过）
2. `worktree.path` 命中路径白名单（`.worktrees/` 前缀）
3. **finalize 内部先 `chdir` 主仓根再 cleanup**（cwd ≡ 主仓根，D-003 决策）——防止 worktree 内 self-remove

任一条件失败 → cleanup 静默跳过 + log，不阻塞 finalize。

### §A.5 finalize process.txt 事件（C-7 定稿）

finalize 跑完后（`_log_finalize_event`，来源：`scripts/lib/archive_runner.py:625`）写入一行：

```text
2026-MM-DD HH:MM:SS [finalized] worktree=removed local_branch=deleted remote_branch=already-deleted [archive PR #<N>]
2026-MM-DD HH:MM:SS [finalized] worktree=kept   local_branch=kept    remote_branch=kept              [archive PR #<N>] (--keep-worktree --keep-local-branch --keep-remote-branch)
```

- 事件 tag 唯一：`[finalized]`（不拆细粒度 tag）
- keep flag 状态展开为 `worktree / local_branch / remote_branch` 三字段；keep flag 名以括号后缀附加便于检索
- idempotent：process.txt 末 10 行含 `[finalized]` → 跳追加

### §A.6 `--force` + `--yes-finalize` 组合警告（C-6 定稿）

| 组合 | 行为 |
|---|---|
| `--force` only | stderr 输出警告 + 调 callback 二次确认（N → exit 0 with "aborted by user"） |
| `--yes-finalize` only | 无额外警告，正常 happy path |
| `--force` + `--yes-finalize` | stderr 打印双重危险警告 + **直接继续**（不再调 callback） |
| `--force` + `--keep-*` | `--force` 警告 + 列出实际生效的 `--keep-*` flag |

### §A.7 finalize 预检错误码

| 错误码 | 触发条件 |
|---|---|
| `R-FINALIZE-ARCHIVE-PR-MISSING` | `meta.archive_pr_number ∈ {None, 0, ""}` |
| `R-FINALIZE-ARCHIVE-PR-FETCH-FAILED` | `gh pr view` 调用失败 |
| `R-FINALIZE-ARCHIVE-PR-NOT-MERGED` | archive PR state != "MERGED" |
| `R-FINALIZE-PULL-FAILED` | `git pull --ff develop` 返回非零 |
| `R-FINALIZE-CWD-FAILED` | `os.chdir(main_repo_root)` 抛 OSError |

---

## §B. `--legacy-resurrect-remote` 兜底（F-007）

`--legacy-resurrect-remote` 仅在 `--finalize` 子命令下生效（来源：`scripts/lib/archive_runner.py:1340`），用于历史 REQ 兜底：

**默认行为**（`legacy_resurrect=False`）：
- 远程分支不存在 → 仅命中 `remote ref does not exist` 文案 → 折叠为 `already-deleted`
- 其他 stderr 文案 → fail-soft + `outcome=failed`

**启用后行为**（`legacy_resurrect=True`，扩大识别集）：
- stderr 含 `remote ref does not exist` / `not found` / `unknown` 任一 → 视为 `already-deleted`，不写 `error_messages`

**适用场景**：历史需求（无归档 PR）走 `--finalize --force --legacy-resurrect-remote` 一次性补归档——远程分支可能早已被 GitHub auto-delete-head-branch 清掉，此时远程删除操作 stderr 包含非标准文案。
