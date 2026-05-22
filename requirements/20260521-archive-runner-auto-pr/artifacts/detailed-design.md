---
id: 20260521-archive-runner-auto-pr
phase: detail-design
created_at: 2026-05-21 16:00:06
title: archive_runner 自动开归档 PR + 单需求单分支闭环 · 详细设计
---

# 详细设计 · 20260521-archive-runner-auto-pr

> 上承 outline-design.md 双阶段拓扑（来源：requirements/20260521-archive-runner-auto-pr/artifacts/outline-design.md:12）。本文档落实 7 features 的函数签名、错误码、idempotent 检查正则、状态机与测试用例骨架；不重复 outline 的拓扑图与选型理由。

## 0. 关键决策（detail-design 阶段拍板）

| ID | 决策 | 取代 / 关闭项 |
|---|---|---|
| **C-1** | `_commit_archive_metadata` 的 `git add` 范围 = `requirements/<id>/{meta.yaml,process.txt,notes.md,artifacts/}` + 白名单 `context/team/experience/*.md` / `context/project/*/experience/*.md` / `context/INDEX.md` / `context/team/experience/INDEX.md`；非白名单 `context/` 改动 → fail-closed exit 1 | outline §7 待澄清 #7 |
| **C-2** | `cleanup_worktree_if_owned` **不**新增 `require_main_repo_cwd` 参数；保护由 finalize 顶层 `_rebind_to_main_repo` + `os.chdir(main_repo_root)` 双保险负责 | outline §7 待澄清 #8 |
| **C-3** | idempotent 重跑时 `gh pr list` 返回 number ≠ `meta.archive_pr_number` → fail-closed exit 1（错误码 `R-ARCHIVE-PR-NUMBER-MISMATCH`） | outline §7 待澄清 #9 |
| **C-4** | meta.yaml 中 `archive_pr_number` 物理位置 = 紧跟 `pr_number: 0` 下一行（流程组内 PR 类元信息聚合） | outline §8 AC-A3 |
| **C-5** | F-002 PR body 模板内容定稿（见 §2.3） | outline §7 待澄清 #1（继承自 tech-research §detail-design 阶段处理项 #1，来源：requirements/20260521-archive-runner-auto-pr/artifacts/tech-research.md:284） |
| **C-6** | `--force` + `--yes-finalize` 组合的 stderr 警告文案定稿（见 §3.4） | outline §7 待澄清 #2（继承自 tech-research §detail-design 阶段处理项 #2，来源：requirements/20260521-archive-runner-auto-pr/artifacts/tech-research.md:285） |
| **C-7** | `--keep-local-branch` / `--keep-remote-branch` / `--keep-worktree` 三 flag 触发的 process.txt 事件命名（见 §3.5） | outline §7 待澄清 #6（继承自 tech-research §detail-design 阶段处理项 #6，来源：requirements/20260521-archive-runner-auto-pr/artifacts/tech-research.md:289） |

---

## 1. F-001：archive 主流程双阶段化

**范围**：改造 `scripts/lib/archive_runner.py::archive_requirement`（来源：scripts/lib/archive_runner.py:733）让阶段 1 仅做 metadata commit + push + archive PR 创建；删除类不可逆操作（分支删 + worktree 清）整体推迟到 `finalize_requirement`。

### 1.1 改造点清单

| 子项 | 现状（行号） | 改造 |
|---|---|---|
| 1-A | `_precheck_dirty`（scripts/lib/archive_runner.py:180） | 主仓 dirty 检查路径加 `requirements/<id>/` 前缀白名单——白名单内的未提交改动不阻塞（idempotent 重跑必备） |
| 1-B | `_precheck_phase`（scripts/lib/archive_runner.py:149） | 允许 `phase ∈ {testing}` **OR** `(phase=completed AND archive_pr_number=0)`——后者是半完成重跑入口 |
| 1-C | `_atomic_write_meta`（scripts/lib/archive_runner.py:291） | idempotent 已具备（保留旧 archived_at / completed_at / outcome）；新增 archive_pr_number 字段保留语义（已写非 0 时不覆盖） |
| 1-D | `_append_process_event`（scripts/lib/archive_runner.py:325） | idempotent 已具备（process.txt 含 `[archived]` 跳） |
| 1-E | `_run_experience`（scripts/lib/archive_runner.py:387） | idempotent 已具备（meta.lessons_extracted=True 由 _precheck_lessons_extracted 前置拦截） |
| 1-F | **新增** `_commit_archive_metadata` | 见 §1.2 |
| 1-G | **新增** `_push_feat_branch` | 见 §1.3 |
| 1-H | 删本地 `_delete_local_branch` / 删远程 `_delete_remote_branch` / worktree cleanup 从 archive 主流程**搬迁**到 finalize_requirement | F-003 接管，本期 archive 主流程不再调用 |

### 1.2 新增函数：`_commit_archive_metadata`

```python
def _commit_archive_metadata(req_id: str, result: ArchiveResult) -> None:
    """Step 6：把归档元信息 + 经验产物 commit 到 feat 分支。

    Idempotent：HEAD commit message 命中正则 ARCHIVE_COMMIT_RE 则跳过。
    白名单：requirements/<id>/ 全量 + context/ 经验类文件 4 路径白名单。
    非白名单 context/ 改动 → fail-closed exit 1（R-ARCHIVE-CONTEXT-DIRTY）。

    raises: SystemExit(1) — 非白名单 dirty / git add 失败 / git commit 失败
    """
```

- **idempotent 正则**：`ARCHIVE_COMMIT_RE = re.compile(rf"^archive\({re.escape(req_id)}\): metadata$")`，匹配 `git log -1 --format=%s`。命中即跳过整步。
- **白名单实现**（伪代码）：

  ```python
  ALLOWED_CONTEXT_PREFIXES = (
      "context/team/experience/",
      "context/project/",   # 子串再过滤 "/experience/"
      "context/INDEX.md",
      "context/team/experience/INDEX.md",
  )

  changed = _run(["git", "status", "--porcelain"], cwd=REPO_ROOT).stdout
  for line in changed.splitlines():
      path = line[3:].strip()  # porcelain: "XY path"
      if path.startswith(f"requirements/{req_id}/"):
          continue
      if path.startswith("context/team/experience/") or \
         (path.startswith("context/project/") and "/experience/" in path) or \
         path in {"context/INDEX.md", "context/team/experience/INDEX.md"}:
          continue
      _abort("R-ARCHIVE-CONTEXT-DIRTY",
             f"非白名单文件存在未提交改动：{path}（归档 commit 拒绝携带）", req_id)
  ```

- **git 操作**：
  ```bash
  git add requirements/<id>/meta.yaml requirements/<id>/process.txt \
          requirements/<id>/notes.md requirements/<id>/artifacts/
  git add context/team/experience/ context/project/ context/INDEX.md context/team/experience/INDEX.md  # 仅 add 改动文件
  git commit -m "archive(<req_id>): metadata"
  ```
  `git add` 用绝对路径列表传 `-A` 等价的子树（用具体路径而非 `-A` 避免误带其他 untracked 文件）；commit message 严格匹配 C-5 prefix（来源：requirements/20260521-archive-runner-auto-pr/artifacts/outline-design.md:123）。

- **错误码**：
  - `R-ARCHIVE-CONTEXT-DIRTY`：非白名单 context/ 改动
  - `R-ARCHIVE-COMMIT-FAILED`：`git commit` 返回非零（透传 stderr）

### 1.3 新增函数：`_push_feat_branch`

```python
def _push_feat_branch(meta: dict[str, Any], req_id: str, result: ArchiveResult) -> None:
    """Step 7：把 feat 分支推到 origin（archive PR 创建前置）。

    Idempotent：HEAD commit sha == origin/feat/<id> HEAD sha 则跳过。
    远程不存在分支也走 push（首次归档场景）。

    raises: SystemExit(1) — push 失败（透传 stderr）
    """
```

- **idempotent 检查**：
  ```python
  local = _run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).stdout.strip()
  remote = _run(["git", "rev-parse", f"origin/{branch}"], cwd=REPO_ROOT)
  if remote.returncode == 0 and remote.stdout.strip() == local:
      logger.info("push skipped: HEAD == origin/%s", branch)
      return
  ```
- **push**：`git push origin <branch>`（不带 `--force`；归档 commit 是 feat 分支末端追加，永远 fast-forward）。
- **错误码**：`R-ARCHIVE-PUSH-FAILED`。

### 1.4 流程顺序锁定（在 `archive_requirement` 内插入新步骤）

```
rebind → load_meta → 5 precheck （含 dirty 白名单 + phase 半完成允许）
  → atomic_write_meta → append_process_event → run_experience
  → _commit_archive_metadata   ★ 新增（step 6）
  → _push_feat_branch          ★ 新增（step 7）
  → _create_archive_pr         ★ 新增（step 8，见 §2）
  → _write_archive_pr_number   ★ 新增（step 9，见 §2）
  → _render_summary
```

> 现有 step 4-5（删本地 / 删远程分支）+ worktree cleanup 从 archive 主流程**搬迁**到 finalize（§3）。
> archive 主流程**不再调用** `_delete_local_branch` / `_delete_remote_branch` / `_cleanup_worktree_before_archive`。

---

## 2. F-002：自动创建归档 PR

**范围**：新增 `_create_archive_pr` / `_write_archive_pr_number` + 模板文件 `.claude/skills/managing-requirement-lifecycle/templates/archive-pr-body.md.tmpl`。

### 2.1 新增函数：`_create_archive_pr`

```python
def _create_archive_pr(meta: dict[str, Any], req_id: str, result: ArchiveResult) -> int:
    """Step 8：调 `gh pr create` 开归档 PR；返回 PR number。

    Idempotent：先 `gh pr list --head feat/<id> --base develop --json number,state`：
      - OPEN：取 number；写入 result.archive_pr_action="reused"；return number
      - MERGED：abort R-ARCHIVE-PR-ALREADY-MERGED（异常：归档 PR 已 merged 但 archive_pr_number 未写）
      - CLOSED：abort R-ARCHIVE-PR-CLOSED（异常：用户手工关 PR）

    存在性检查后才 create。create 失败抛 R-ARCHIVE-PR-CREATE-FAILED。

    冲突检查：若 meta.archive_pr_number > 0 且 != 当前 gh 返回 number → fail-closed
    R-ARCHIVE-PR-NUMBER-MISMATCH（C-3 决策）。

    raises: SystemExit(1) — 任一异常路径
    returns: int — 新建或复用的 PR number
    """
```

- **gh pr list 命令**：
  ```bash
  gh pr list --head feat/<id> --base develop --state all --json number,state --limit 1
  ```
- **gh pr create 命令**：
  ```bash
  gh pr create \
    --base develop --head feat/<id> \
    --title "archive(<id>): metadata + lessons" \
    --body-file <tmp 写入 archive-pr-body 渲染产物>
  ```
- **错误码**：
  - `R-ARCHIVE-PR-CREATE-FAILED`：`gh pr create` 返回非零
  - `R-ARCHIVE-PR-ALREADY-MERGED`：gh pr list state=MERGED 但 meta.archive_pr_number=0（说明用户手动 merge 了归档 PR 但 archive 流程没落地 number——必须手工恢复）
  - `R-ARCHIVE-PR-CLOSED`：gh pr list state=CLOSED
  - `R-ARCHIVE-PR-NUMBER-MISMATCH`：meta.archive_pr_number != gh 返回 number（C-3）

### 2.2 新增函数：`_write_archive_pr_number`

```python
def _write_archive_pr_number(req_id: str, meta: dict[str, Any], pr_number: int) -> None:
    """Step 9：把 archive_pr_number 落回 meta.yaml。

    Idempotent：meta.archive_pr_number == pr_number 时跳过写盘。
    """
```

- **写入策略**：复用 `_atomic_write_meta` 模式（tmp + os.replace），但只改单字段；其余字段维持。

### 2.3 PR body 模板内容（C-5 定稿）

文件：`.claude/skills/managing-requirement-lifecycle/templates/archive-pr-body.md.tmpl`

采用 `__VAR__` 双下划线占位符风格（与同目录 `pr-body.md.tmpl` 一致，详 `.claude/skills/managing-requirement-lifecycle/templates/pr-body.md.tmpl:1`）。模板含 3 个占位符：

- `__REQ_ID__` ← `req_id` 字符串
- `__PR_NUMBER__` ← `meta["pr_number"]`（需求 PR number，非归档 PR number）
- `__BRANCH__` ← `meta["branch"]`（feat 分支名）

完整内容见 `.claude/skills/managing-requirement-lifecycle/templates/archive-pr-body.md.tmpl`（F-002 落地）。模板结构：

- 顶部一行身份声明（"归档 commit，仅含 metadata + lessons"）
- "改动范围" 列出 5 类受影响路径（meta / process / artifacts / experience / INDEX）
- "校验提示" 给 reviewer 决策准则（看到代码改动 → 关 PR；正常归档 → 通过）
- "关联" 3 个跳转链接（需求 PR / 需求目录 / detailed-design）
- "Merge 后步骤" 给用户复制粘贴的 `--finalize` 命令

**渲染实现**：`_create_archive_pr` 内做字符串替换（不引入 jinja2 依赖；用 `str.replace` 三次足够，避免 `format_map` 与原文中 `{`/`}` 冲突）：

```python
def _render_archive_pr_body(req_id: str, pr_number: int, branch: str) -> str:
    tmpl_path = REPO_ROOT / ".claude/skills/managing-requirement-lifecycle/templates/archive-pr-body.md.tmpl"
    content = tmpl_path.read_text(encoding="utf-8")
    return (content
        .replace("__REQ_ID__", req_id)
        .replace("__PR_NUMBER__", str(pr_number))
        .replace("__BRANCH__", branch))
```

渲染产物写临时文件（`tempfile.NamedTemporaryFile(suffix=".md", delete=False)`）后传给 `gh pr create --body-file <tmp_path>`，调用结束 unlink。

---

## 3. F-003：`finalize_requirement` 子命令

**范围**：新增 `finalize_requirement` 函数 + CLI `--finalize` 子命令 + 5 个新 flag。

### 3.1 新增函数签名

```python
def finalize_requirement(
    req_id: str,
    *,
    yes_finalize: bool = False,
    force: bool = False,
    keep_local_branch: bool = False,
    keep_remote_branch: bool = False,
    keep_worktree: bool = False,
    legacy_resurrect_remote: bool = False,
    prompts_callback: Optional[Callable[[ArchivePrompt], bool]] = None,
) -> ArchiveResult:
    """finalize 子动作入口；详见 detail-design §3。

    顺序：
      1. _rebind_to_main_repo
      2. _load_meta
      3. _precheck_archive_pr_merged（--force 跳过）
      4. 合并问询 ArchivePrompt(kind="finalize")（--yes-finalize 跳过）
      5. os.chdir(main_repo_root)（fail-closed）
      6. git pull --ff develop（fail-closed）
      7. _cleanup_worktree_before_archive（--keep-worktree 跳过）
      8. _delete_local_branch(strict=True)（--keep-local-branch 跳过）
      9. _delete_remote_branch(legacy_resurrect=...)（--keep-remote-branch 跳过）
      10. _render_summary(stage="finalize")
    """
```

### 3.2 新增预检：`_precheck_archive_pr_merged`

```python
def _precheck_archive_pr_merged(meta: dict[str, Any], req_id: str, *, force: bool) -> int:
    """finalize 前置：校验 archive_pr_number 字段 + gh pr view state=MERGED。

    三路径全 fail-closed（D-008 镜像）：
      - meta.archive_pr_number 缺失 / 0 → R-FINALIZE-ARCHIVE-PR-MISSING
      - gh pr view 调用失败 → R-FINALIZE-ARCHIVE-PR-FETCH-FAILED
      - state != MERGED → R-FINALIZE-ARCHIVE-PR-NOT-MERGED

    --force 跳过全部 3 路径（仅用于异常恢复，并触发 §3.4 警告文案）。

    returns: int — archive_pr_number（用于后续 _render_summary 展示）
    """
```

错误码定义：

| 错误码 | 触发条件 | stderr 文案 |
|---|---|---|
| `R-FINALIZE-ARCHIVE-PR-MISSING` | `meta.archive_pr_number ∈ {None, 0, ""}` | `meta.archive_pr_number=<value> 缺失；先跑 archive_runner <req_id>（无 --finalize）创建归档 PR` |
| `R-FINALIZE-ARCHIVE-PR-FETCH-FAILED` | `gh pr view` 调用 OSError / 返回非零 | `gh pr view <number> 调用失败：<stderr>；检查网络 / gh auth；--force 可跳过此预检（高风险）` |
| `R-FINALIZE-ARCHIVE-PR-NOT-MERGED` | gh 返回 state != "MERGED" | `归档 PR #<number> state=<state>，未 merged；等 reviewer merge 后再跑 finalize` |

### 3.3 改造现有函数：`_delete_local_branch` / `_delete_remote_branch` / `_render_summary`

对照 outline §8 AC-A1 / AC-A2 锁定决策：

**`_delete_local_branch`**（scripts/lib/archive_runner.py:430）签名扩展：

```python
def _delete_local_branch(
    branch: str,
    base_branch: str,
    *,
    keep_branch: bool,
    yes_local: bool,
    callback: Optional[Callable[[ArchivePrompt], bool]],
    result: ArchiveResult,
    strict: bool = False,   # ★ 新增
) -> None:
    """strict=True：所有 fail-soft 改 fail-closed（finalize 调用方传）。
       strict=False：保留现有 fail-soft 行为（archive 主流程历史调用方默认值）。
    """
```

但注意：F-003 落地后 archive 主流程**不再调用** `_delete_local_branch`，所以 strict=False 分支只剩单测覆盖，没有运行时调用方（保留 default value 是为单测可读性）。

**`_delete_remote_branch`**（scripts/lib/archive_runner.py:546）签名扩展：

```python
def _delete_remote_branch(
    branch: str,
    base_branch: str,
    *,
    keep_branch: bool,
    yes_remote: bool,
    callback: Optional[Callable[[ArchivePrompt], bool]],
    result: ArchiveResult,
    legacy_resurrect: bool = False,   # ★ 新增（F-007）
) -> None:
    """legacy_resurrect=True：remote not-found 视为 already-deleted（F-007）。
       现有 `remote ref does not exist` 路径（scripts/lib/archive_runner.py:607）保留。
       network / auth 失败 → fail-soft + append manual_recovery_commands。
    """
```

**`_render_summary`**（scripts/lib/archive_runner.py:614）签名扩展：

```python
def _render_summary(result: ArchiveResult, *, stage: Literal["archive", "finalize"] = "archive") -> str:
    """stage 决定首行标题与展示项：
       - archive：标题 `✅ <req_id> archived` + 展示 archive_pr_number / archive_pr_url
       - finalize：标题 `✅ <req_id> finalized` + 展示 worktree_removed / manual_recovery_commands
    """
```

### 3.4 `--force` + `--yes-finalize` 组合警告文案（C-6 定稿）

| 组合 | stderr 警告文案（finalize 启动时一次性 print，再继续执行） |
|---|---|
| `--force` only | `⚠️  finalize: --force 已启用——跳过 archive_pr_number 校验。即将无视归档 PR 状态删除 feat 分支与 worktree。Y/N？` （prompts_callback Y → 继续，N → exit 0 with "aborted by user"） |
| `--yes-finalize` only | 无额外警告（正常 happy path 用户已确认） |
| `--force` + `--yes-finalize` | `⚠️  finalize: --force + --yes-finalize 同时启用——双重危险组合（跳过 PR 校验 + 跳过合并问询）。请确认你正在做异常恢复且已手工核对归档 PR 状态。继续执行。` （**不**再问 prompts_callback；直接打印警告 + 继续） |
| `--force` + `--keep-worktree` 等 | `--force` 警告 + 列出实际生效的 `--keep-*` flag |

实现：在 `finalize_requirement` 入口、`_precheck_archive_pr_merged` 之前打印。

### 3.5 `--keep-*` 三 flag 的 process.txt 事件（C-7 定稿）

finalize 跑完后 `_render_summary` 之前，调用 `_log_finalize_event` 写入 process.txt：

```
2026-MM-DD HH:MM:SS [finalized] worktree=removed local_branch=deleted remote_branch=already-deleted [archive PR #<N>]
2026-MM-DD HH:MM:SS [finalized] worktree=kept   local_branch=kept    remote_branch=kept              [archive PR #<N>] (--keep-worktree --keep-local-branch --keep-remote-branch)
```

**事件 tag 唯一**：`[finalized]`（无 `[finalize-kept-*]` 类细粒度 tag）。三 keep 状态全展开为 worktree / local_branch / remote_branch 三个字段；keep flag 信息以括号后缀附加方便检索。

idempotent：process.txt 末 10 行含 `[finalized]` tag 跳追加。

---

## 4. F-004：meta-schema + check_meta 状态机

**范围**：`context/team/engineering-spec/meta-schema.yaml` 新增字段 + `scripts/lib/check_meta.py` 新增状态机校验。

### 4.1 meta-schema.yaml 字段新增（C-4 落点）

```yaml
optional_fields:
  - reviews
  - archived_at
  - legacy
  - archive_pr_number   # ★ 新增（来源：outline-design.md:258）

fields:
  archive_pr_number:
    type: int
    required: false
    description: >
      归档 PR number（archive 阶段 1 创建后写入；finalize 阶段读取校验 MERGED）；
      0 / 缺失视同未创建。状态机：phase=completed 且字段>0 → 已完成归档；
      phase=completed 且字段=0 → 半完成可重跑 archive；phase!=completed 且字段>0 → 非法。
```

physical 位置：紧跟 `pr_number: 0` 后一行（templates/meta.yaml.tmpl 同步更新）。

### 4.2 check_meta.py 新增状态机

新增函数 `_check_archive_pr_number_state_machine`，对照 `_check_archived_at_state_machine`（来源：scripts/lib/check_meta.py:150）模式：

```python
def _check_archive_pr_number_state_machine(
    meta: dict[str, Any], report: Report, file_label: str
) -> None:
    """archive_pr_number 状态机：

    | phase     | archive_pr_number   | 校验结果 |
    | ---       | ---                 | ---      |
    | != completed | 0 / 缺失           | PASS     |
    | != completed | > 0                | FAIL（state-machine） |
    | == completed | 0 / 缺失           | PASS（兼容历史 + 半完成重跑） |
    | == completed | > 0                | PASS（正常完成） |

    非法 case：phase != completed 但已写 archive_pr_number → 说明流程被人工
    干预；fail 提示用户先恢复 phase=completed 再跑 finalize。
    """
    pr_num_raw = meta.get("archive_pr_number", 0)
    try:
        pr_num = int(pr_num_raw or 0)
    except (TypeError, ValueError):
        pr_num = 0
    phase = meta.get("phase", "")

    if pr_num > 0 and phase != "completed":
        report.add(
            file_label,
            Severity.ERROR,
            "state-machine",
            f"archive_pr_number={pr_num} 但 phase={phase!r}，"
            "仅 phase=completed 时允许写入 archive_pr_number",
        )
```

调用注入点：与 `_check_archived_at_state_machine` 同位置（main 函数内顺序追加）。

### 4.3 历史 completed REQ 兼容

15 个历史 completed REQ 的 meta.yaml 不含 `archive_pr_number` 字段——状态机表格场景 3 PASS（缺失 = 0）。**不需要 backfill 脚本**。

finalize 子命令读 `archive_pr_number=0` 直接 fail-closed `R-FINALIZE-ARCHIVE-PR-MISSING`（详 §3.2），保护历史 REQ 不被误 finalize（它们也没有归档 PR 可校验）。

---

## 5. F-005：测试用例骨架

**features-schema 约束** F-NNN 三位数字，故 F-005a/F-005b/F-005c 合并为单一 **F-005**；3 个测试文件在 F-005 内并存，PR 拆分以 commit 粒度承载（PR-A commit test_check_meta_archive_pr_number.py / PR-B commit test_archive_runner.py / PR-C commit test_finalize.py）。

| 测试文件 | PR 归属 | feature 依赖 | 测试范围 |
|---|---|---|---|
| `tests/lifecycle/test_archive_runner.py` | PR-B | F-001 + F-002 | archive 阶段 1 单测（_commit_archive_metadata / _push_feat_branch / _create_archive_pr / _write_archive_pr_number 4 函数 + idempotent 路径） |
| `tests/lifecycle/test_finalize.py` | PR-C | F-003 + F-007 | finalize 子命令 e2e + 组合矩阵（--force / --keep-* 五维 / --legacy-resurrect-remote） |
| `tests/lib/test_check_meta_archive_pr_number.py` | PR-A | F-004 | _check_archive_pr_number_state_machine 4 场景 |

### 5.1 test_archive_runner.py 测试矩阵（F-005a）

| TC ID | 场景 | 断言 |
|---|---|---|
| TC-F1-1 | _commit_archive_metadata idempotent — HEAD commit message 含 `archive(<id>): metadata` | 函数提前 return；git log unchanged |
| TC-F1-2 | _commit_archive_metadata 白名单 — 仅 `requirements/<id>/` + `context/team/experience/` 改动 | 正常 commit；commit message == `archive(<id>): metadata` |
| TC-F1-3 | _commit_archive_metadata 非白名单 — `scripts/lib/foo.py` dirty | SystemExit(1) + stderr 含 `R-ARCHIVE-CONTEXT-DIRTY` |
| TC-F1-4 | _push_feat_branch idempotent — HEAD == origin/feat/<id> | 函数提前 return；git push 不调用 |
| TC-F1-5 | _push_feat_branch 首次 push — origin 无该分支 | git push origin <branch> 成功；result.archive_pr_action 不触动 |
| TC-F2-1 | _create_archive_pr idempotent OPEN — gh pr list 返回 OPEN PR | 函数返回该 PR number；archive_pr_action="reused"；不调 gh pr create |
| TC-F2-2 | _create_archive_pr idempotent MERGED — gh pr list 返回 MERGED PR 但 meta.archive_pr_number=0 | SystemExit(1) + stderr 含 `R-ARCHIVE-PR-ALREADY-MERGED` |
| TC-F2-3 | _create_archive_pr idempotent CLOSED — gh pr list 返回 CLOSED PR | SystemExit(1) + stderr 含 `R-ARCHIVE-PR-CLOSED` |
| TC-F2-4 | _create_archive_pr 冲突 — meta.archive_pr_number=42 但 gh 返回 number=99 | SystemExit(1) + stderr 含 `R-ARCHIVE-PR-NUMBER-MISMATCH` |
| TC-F2-5 | _create_archive_pr 正常创建 — gh pr list 空 | gh pr create 调用一次；返回新 PR number；archive_pr_action="created" |
| TC-F2-6 | _write_archive_pr_number idempotent — meta.archive_pr_number 已等于目标 | 不调 _atomic_write_meta |
| TC-F2-7 | _write_archive_pr_number 写入 — meta.archive_pr_number=0 → 42 | 文件原子更新；其余字段不变 |
| TC-F2-8 | PR body 渲染 — 模板含 `__REQ_ID__` / `__PR_NUMBER__` / `__BRANCH__` | 渲染产物 3 占位符替换正确 |

### 5.2 test_finalize.py 测试矩阵（F-005b）

| TC ID | 场景 | 断言 |
|---|---|---|
| TC-F3-1 | finalize happy path — archive PR MERGED + user Y | local/remote 分支删；worktree removed；result.experience="aborted by user" not set |
| TC-F3-2 | finalize 预检 MISSING — meta.archive_pr_number=0 | SystemExit(1) + `R-FINALIZE-ARCHIVE-PR-MISSING` |
| TC-F3-3 | finalize 预检 FETCH-FAILED — gh pr view 返回 1 | SystemExit(1) + `R-FINALIZE-ARCHIVE-PR-FETCH-FAILED` |
| TC-F3-4 | finalize 预检 NOT-MERGED — gh 返回 state=OPEN | SystemExit(1) + `R-FINALIZE-ARCHIVE-PR-NOT-MERGED` |
| TC-F3-5 | finalize --force 跳预检 + user Y | 警告文案 stderr 输出（§3.4 行 1）；不调 gh pr view |
| TC-F3-6 | finalize --force + --yes-finalize | 警告文案 stderr 输出（§3.4 行 3）；不问 callback |
| TC-F3-7 | finalize 合并问询 N — user 答 N | result.experience="aborted by user" + exit 0；无删除动作 |
| TC-F3-8 | finalize cwd in main repo — chdir 不变 | 流程正常 |
| TC-F3-9 | finalize cwd in linked worktree — _rebind + chdir 到主仓 | 流程正常；REPO_ROOT 已切主仓 |
| TC-F3-10 | finalize cwd 删的 worktree 之外的目录 | OSError 兜底；chdir 跳过；fail-closed |
| TC-F3-11 | finalize git pull --ff develop 失败（非 fast-forward） | SystemExit(1) + `R-FINALIZE-PULL-FAILED` |
| TC-F3-12 | finalize --keep-worktree | worktree 保留；local/remote 仍删；process.txt 含 `(--keep-worktree)` |
| TC-F3-13 | finalize --keep-local-branch | local 保留；remote/worktree 仍处理 |
| TC-F3-14 | finalize --keep-remote-branch | remote 保留；local/worktree 仍处理 |
| TC-F3-15 | finalize 三 keep 全开 | 三件套全 skipped；process.txt 含三 flag 后缀 |
| TC-F3-16 | finalize --legacy-resurrect-remote — remote 不存在 | result.remote_branch="already-deleted"；不写 error_messages |
| TC-F3-17 | finalize remote network 失败 fail-soft | result.remote_branch="failed"；manual_recovery_commands 含 `git push origin --delete <branch>` |
| TC-F3-18 | finalize _delete_local_branch strict=True — squash merge 不能删 | SystemExit(1) + transport stderr |

### 5.3 test_check_meta_archive_pr_number.py 测试矩阵（F-004）

| TC ID | meta.phase | archive_pr_number | 期望 |
|---|---|---|---|
| TC-F4-1 | testing | 0 | PASS |
| TC-F4-2 | testing | 42 | FAIL state-machine |
| TC-F4-3 | completed | 0 | PASS（兼容历史） |
| TC-F4-4 | completed | 42 | PASS |
| TC-F4-5 | development | (missing) | PASS |
| TC-F4-6 | completed | "abc"（非法类型） | int() 转换失败 → 当 0 → PASS（fallback） |

---

## 6. F-006：文档更新

### 6.1 `.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md`

需新增段落：

1. **双阶段拓扑章节**（顶部）：archive（不可逆操作前停止） + finalize（merge 后执行）
2. **archive PR 自动创建语义**：archive 步骤产出含 PR number 的 meta；reviewer 通过后用户跑 finalize
3. **`--finalize` flag + 5 keep flag 详解**：每个 flag 的语义 / 默认 / 适用场景
4. **commit message 前缀约定**：`archive(<req_id>): metadata` 严格匹配；非匹配不触发 idempotent 跳过
5. **三重保护移到 finalize 章节调整**：把现有 archive-rules.md 里"删本地 / 删远程 / cleanup worktree 三件套"的描述整体迁移到 finalize 子标题下

### 6.2 `.claude/commands/requirement/archive.md`

补 finalize 子命令的入口说明 + 与 `/requirement:archive` 关系：

- `/requirement:archive` 仍调 `archive_runner.py <id>`（阶段 1）
- `/requirement:archive --finalize` 或直接 `python3 scripts/lib/archive_runner.py <id> --finalize`（阶段 2，独立 slash 暂不开）

---

## 7. F-007：`--legacy-resurrect-remote` 兜底

**范围**：`_delete_remote_branch` 接 `legacy_resurrect: bool` 参数；finalize CLI 加 `--legacy-resurrect-remote` flag。

**行为**：
- `legacy_resurrect=False`（默认）：remote 不存在 → 仅命中现有 `remote ref does not exist` 文案识别（来源：scripts/lib/archive_runner.py:607），other failures → fail-soft
- `legacy_resurrect=True`：扩大 already-deleted 判定——任何 stderr 含 `remote ref does not exist` / `not found` / `unknown` → 都视为 already-deleted，不写 error_messages

用于：历史 REQ（无归档 PR）走 `--finalize --force --legacy-resurrect-remote` 一次性补归档（远程分支可能早被 GitHub auto-delete-head-branch 删了）。

---

## 8. 状态机视图

### 8.1 archive_pr_number × phase 状态机

```
                                    ┌─ phase=testing ─┐
                                    │ pr_number=0     │
                                    └────────┬────────┘
                                             │ archive_requirement()
                                             ▼
                                    ┌─ phase=completed ─┐
                                    │ pr_number=0       │  ← 半完成（archive 主流程跑了一半）
                                    └────────┬──────────┘
                                             │ idempotent 重跑 archive_requirement()
                                             ▼
                                    ┌─ phase=completed ─┐
                                    │ pr_number=42      │  ← 归档 PR 创建完成
                                    └────────┬──────────┘
                                             │ finalize_requirement() (等 PR merged)
                                             ▼
                                    ┌─ phase=completed ─┐
                                    │ pr_number=42      │  ← 不可逆删除完成（终态）
                                    │ worktree cleared  │
                                    │ branches deleted  │
                                    └───────────────────┘
```

### 8.2 finalize cwd 状态机

```
                ┌─ user invokes from anywhere ─┐
                └──────────────┬───────────────┘
                               │ _rebind_to_main_repo
                               ▼
                ┌─ REPO_ROOT == main repo root ─┐
                └──────────────┬────────────────┘
                               │ os.chdir(main_repo_root)
                               ▼
                ┌─ cwd == main repo root ────┐
                └──────────────┬─────────────┘
                               │ git pull --ff develop
                               ▼
                ┌─ working tree synced ──────┐
                └──────────────┬─────────────┘
                               │ cleanup_worktree (删 .worktrees/<sub>) ← cwd 不变
                               ▼
                ┌─ worktree gone, cwd 仍主仓 ─┐
                └──────────────┬─────────────┘
                               │ delete_local + delete_remote
                               ▼
                            （finalize 完成）
```

---

## 9. 待澄清（detail-design 阶段未关闭项）

本阶段所有 outline §7 待澄清（#1-#9）均已关闭（§0 决策表 C-1 ~ C-7 + §3.5）。

下游阶段补：

- **task-planning 阶段**：3 个 PR 内部 commit 顺序（每个 feature 是否独立 commit / 拆几个 commit）
- **development 阶段**：`gh pr create --body-file` 在 CI 沙盒环境的 mock 策略（影响 F-005a TC-F2-5）

---

## 10. 验收指标

详细设计完成的硬性指标：

- [x] 7 features 全部有完整函数签名 + 错误码 + idempotent 检查实现要点
- [x] outline §7 待澄清 9 条全部关闭并落入 §0 决策表
- [x] PR body 模板内容定稿
- [x] 37 条测试用例骨架（TC-F1-1~5 共 5 + TC-F2-1~8 共 8 + TC-F3-1~18 共 18 + TC-F4-1~6 共 6 = 37）
- [x] check_meta 状态机 4 场景表格
- [x] archive_pr_number × phase 状态机图
- [x] finalize cwd 状态机图
