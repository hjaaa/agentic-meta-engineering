# /requirement:archive 执行细则

`/requirement:archive` 命令的子动作规则——伞形 Skill `managing-requirement-lifecycle` 在识别到「归档」意图时按本文执行。实现入口 `scripts/lib/archive_runner.py::archive_requirement`，签名见 `requirements/REQ-2026-007/artifacts/detailed-design.md` §3.1，**已 frozen**。

适用阶段：`phase ∈ {testing, completed}`。`testing → completed` 由 archive 命令推进（不走 `/workflow:next [F-012 待落地]`，因为含副作用动作）。

---

## 0. 何时调用 archive（主 Agent 行为约束）

archive 是**用户显式触发**的动作，不是 PR 合并的自动后置步骤。

### 0.1 「PR merged」≠「立刻 archive」

PR 合并只代表代码进入 base_branch，**不代表测试已闭环**。常态时间窗口：

```
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
若经验沉淀未跑或脚本未把字段翻为 True，archive 也不会进入第 §2 步——是机器强制，
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

## archive 前 CI gate 预检（D-002 / D-008）

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

## 2. 5 步执行（预检通过后）

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

### 2.4 删远程分支 → 自动切 base → 删本地分支（可选）

两问串行（**先远程后本地**），任一为独立动作。`--keep-branch` flag 同时跳过两问，`outcome=skipped`。

顺序按 §0.3 规则：远程删不需要切走，故先做；本地删需要先 `git switch <base_branch>`，
放最后让 archive 所有 bookkeeping 操作都在 feat 分支完成后再离开。

**远程分支**（`kind="remote_branch"`，先做）：
- 答 y → `git push origin --delete <branch>`（仍在 feat 分支上执行）
- 远程已被 GitHub「Automatically delete head branches」清掉 → stderr 含 `remote ref does not exist` → 折叠为 `outcome=already-deleted`，不报错
- 网络 / 401 / 403 → 透传 error → `outcome=failed`

**本地分支**（`kind="local_branch"`，最后做）：
- 答 y → 若当前 HEAD == `<branch>`，archive_runner 自动跑 `git switch <base_branch>`，然后 `git branch -d <branch>`（safe delete；**不允许 `-D` 强删**，D-014）
- `base_branch` 为空 / `git switch` 失败 → `outcome=failed` + `error_messages` 提示用户手动切走，**不**自动 `-D` 强删（避免误删尚未合并的提交）
- `<branch> == base_branch`（如 develop / main）→ `outcome=failed` + `error_messages` 记拒因，跳过实际 git 调用
- git 拒绝（squash merge 后会被判 not fully merged）→ 透传 git 原始 error → `outcome=failed`

### 2.5 终端反馈（6 行 + 可选 errors 段）

按 spec §5.3 第 5 步原样渲染：

```text
✅ REQ-YYYY-NNN archived
   phase: completed
   archived_at: 2026-05-04 19:30:00
   experience: ✅ yes / ⏭ no / ⏭ skipped / ❌ failed
   local branch:  ✅ deleted / ⏭ kept / ⏭ skipped / ❌ failed
   remote branch: ✅ deleted / ⏭ kept / ⏭ skipped / ✅ already-deleted / ❌ failed
```

任意 `outcome=failed` 时追加 `errors:` 段列出 `error_messages`，便于排查。

archive 命令始终 exit 0（除非 4 项预检挂）。

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

副作用动作 `outcome` 全部记录到 `ArchiveResult`。archive 命令始终 exit 0（除非 4 项预检挂）。

---

## 5. 与其他规则的关系

- `meta-schema.yaml.fields.archived_at`（context/team/engineering-spec/）：`archived_at` 写入仅当 phase=completed，本文 §2.1 是其唯一执行入口
- `requirement-progress-logger` SKILL.md：本文 §2.2 走的是 progress-logger 的格式约束（事件标签 `[archived]` 已加入白名单）
- `submit-rules.md`：archive 强依赖 `meta.pr_number` 已被 submit 回写，预检 3 失败时引导用户先跑 `/requirement:submit`

---

## 6. 测试与自举

- 单测：`tests/lifecycle/test_archive.py` 覆盖 TC-F3-1 ~ TC-F3-7（4 预检 + 三问 yes/no + 失败降级）
- 沙盒 e2e（V-01）：TC-F3-8，REQ-2099-007 走全链路
- 自举（V-08）：本需求 PR merge 后用 `/requirement:archive` 归档自身——`yq '.archived_at' meta.yaml` 非空 + `grep -c '\[archived\]' process.txt == 1`（幂等校验）
