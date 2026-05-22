---
description: PR 合并后做收尾闭环——phase=completed + archived_at + 经验沉淀 + 删本地+远程分支（提示）
---

> [DEPRECATION] /requirement:archive 已纳入 3 月兼容期（截至 2026-08-08）。
> 请改用：新引擎语义由 archive-finalize 节点承载。
> 本次仍执行旧实现以保证兼容；Plan 6 自举验证通过 + 兼容期到期后将物理删除。
> 详见：context/team/engineering-spec/migration/2026-XX-runs-rename.md
>
> **例外保留说明（不转发到 /workflow:archive）**：保留旧实现；新引擎语义由 archive-finalize 节点承载。

## 用途

PR 合并后做收尾闭环：phase=completed + archived_at + 经验沉淀 + 删本地+远程分支（提示）。

不做：迁移 `requirements/<req_id>/` 目录、阶段状态机膨胀（D-005 / D-006 已锁定）。

## 何时跑（前置约束 — 主 Agent 必读）

**「PR merged」≠「立刻 archive」**。PR 合并只代表代码进入 develop，**不代表测试已闭环**。
合并后通常还有：

- 测试人员对合并版本做回归 / 验收
- 反馈 bug 后需要新一轮 hotfix（在原 feat 分支或新 hotfix 分支补 commit、再开 PR、再合并）
- 修复期间 `phase` 仍停留在 `testing`

**主 Agent 不得在 PR merged 后自动调用 `/requirement:archive`**。等且仅等以下信号其一发生才触发：

1. 用户明确说「归档 / archive / 收尾 / 关掉这个需求」
2. 测试反馈窗口已经被用户显式确认结束（"测试通过没问题了"、"可以归档了" 等）

不确定时主动问，**不要替用户判断"测试是否完成"**。

## 分支位置（主 Agent 必读）

archive 流程的副作用动作分布：

| 步骤 | 应在哪个分支 |
|---|---|
| 预检 / 写 meta.yaml / 写 process.txt / 经验沉淀 | **原开发分支**（`meta.yaml.branch`，例 `feat/req-yyyy-nnn`）—— 让经验沉淀和 git blame 视角保持一致 |
| 删本地分支（archive 内部 §2.4） | 必须**先**切到 `meta.yaml.base_branch`（例 `develop`），否则 `git branch -d` 报 "used by worktree"——`archive_runner` 会给出可执行错误指引 |

主 Agent **禁止**在 archive 调用前主动 `git checkout` 切走原开发分支。
切到 base_branch 是删本地分支这一步的内嵌行为，不是 archive 的"准备动作"。

## 参数

| 参数 | 默认 | 语义 |
|---|---|---|
| `--force` | false | 跳过 PR merged 校验（异常恢复用） |
| `--keep-branch` | false | （已被 F-003 弃用，阶段 1 不再删分支；保留兼容 CLI 参数签名）|
| `--no-experience` | false | 跳过经验沉淀提示 |
| `--yes-experience` | false | 经验问跳问，等价用户答 y（CLI 自动化场景） |
| `--yes-local-branch` | false | 本地分支问跳问，等价用户答 y |
| `--yes-remote-branch` | false | 远程分支问跳问，等价用户答 y |

## Finalize 子命令（阶段 2）

`/requirement:archive` 执行的是阶段 1（写 meta + commit + push + 自动开归档 PR）。归档 PR 被 reviewer merge 后，用户需要跑阶段 2（finalize）完成不可逆收尾动作：

```bash
# Skill 入口（推荐）
/requirement:archive --finalize

# CLI 直接调用
python3 scripts/lib/archive_runner.py <req_id> --finalize
```

**阶段 1 → 阶段 2 接力关系**：

| 阶段 | 命令 | 动作 |
|---|---|---|
| 阶段 1 archive | `/requirement:archive` | 写 meta.yaml + process.txt + 经验沉淀 → commit → push → 创建归档 PR → 写 archive_pr_number |
| 阶段 2 finalize | `/requirement:archive --finalize` | 校验归档 PR merged → 删本地 feat 分支 → 删远程 feat 分支 → cleanup worktree |

**触发时机**：archive PR 被 reviewer 通过且 merged 后——不要在 PR merge 前跑 `--finalize`，finalize 有预检会拦截 state != MERGED（除非加 `--force`）。

**5 个 keep flag**（finalize 专用，阶段 1 archive 不认识这些 flag）：

| flag | 默认 | 语义 / 适用场景 |
|---|---|---|
| `--yes-finalize` | false | 跳过「确认删除」问询（CI / 自动化脚本使用） |
| `--keep-local-branch` | false | 跳过删本地 feat 分支（保留 git history 查阅） |
| `--keep-remote-branch` | false | 跳过删远程 feat 分支（外部协作仍需可见时） |
| `--keep-worktree` | false | 跳过 cleanup worktree（用户仍在 worktree 内操作时） |
| `--legacy-resurrect-remote` | false | 历史 REQ 兜底：扩大 already-deleted 识别到 `not found` / `unknown`（远程已被 GitHub auto-delete-head-branch 清掉的老需求） |

完整 finalize 规则见 [`reference/archive-rules.md` §A](../../skills/managing-requirement-lifecycle/reference/archive-rules.md)。

## 预检（5 项硬门禁，任一 fail → exit 1）

1. `phase ∈ {testing, completed}` —— 错误码 `R-ARCHIVE-PHASE`
2. `git status --porcelain` 为空 —— 错误码 `R-ARCHIVE-DIRTY`
3. `meta.yaml.pr_number` 存在且 > 0 —— 错误码 `R-ARCHIVE-NO-PR`
4. `gh pr view <pr_number> --json state` == `MERGED`（除非 `--force`）—— 错误码 `R-ARCHIVE-PR-NOT-MERGED`
5. `meta.yaml.lessons_extracted is True` —— 错误码 `R-ARCHIVE-LESSONS-NOT-EXTRACTED`（**`--force` 不豁免**；先跑 `claude /knowledge:extract-experience <req_id>`，Skill 会调用 `scripts/lib/mark_lessons_extracted.py` 把字段翻为 True）

## 委托

调用 Skill `managing-requirement-lifecycle` 的 archive 子动作；执行细节见 [`reference/archive-rules.md`](../../skills/managing-requirement-lifecycle/reference/archive-rules.md)。

实现入口：`scripts/lib/archive_runner.py::archive_requirement`（接口契约见 `requirements/REQ-2026-007/artifacts/detailed-design.md` §3.1，已 frozen）。

## worktree cleanup 三重保护（D-008 / D-009）

worktree cleanup 已迁移到阶段 2（`--finalize`）执行，不在阶段 1 archive 中触发。finalize 内的三重保护：

1. `owner=workflow`（external worktree 跳过）
2. `worktree.path` 命中路径白名单（`.worktrees/` 前缀）
3. finalize 内部先 `chdir` 主仓根再 cleanup（防止 worktree 内 self-remove，D-003）

任一条件失败 → cleanup 静默跳过 + log，不阻塞 finalize。

## 三问串行（默认 N）

**阶段 1 archive** 预检通过后，按交互通道决议触发的 1 问（F-001 后分支删除迁移到 finalize）：

1. 经验沉淀：`是否沉淀经验到 context/team/experience/？`

**阶段 2 finalize** 合并问询（`kind="finalize"`）：

- 一次性问「即将 finalize（删 worktree + feat 本地/远程分支），确认继续？」
- `--yes-finalize` 跳过此问

通道优先级（D-016 A 案）：

1. `--yes-<x>` flag 已设 → 跳问，按 y 处理
2. 主对话场景注入 `prompts_callback` → 调 callback，由主 Agent 串行问
3. CLI 自动化无 callback → 默认按 N 处理（保守不删 / 不沉淀）

阶段 1：`--no-experience` 跳过经验沉淀问。`--keep-branch` 已被 F-003 弃用（阶段 1 archive 不再删分支），仅保留 CLI 参数签名兼容。

## 终端反馈格式（spec §5.3 第 5 步）

```text
✅ REQ-YYYY-NNN archived
   phase: completed
   archived_at: 2026-05-04 19:30:00
   experience: ✅ yes / ⏭ no / ⏭ skipped / ❌ failed
   local branch:  ✅ deleted / ⏭ kept / ⏭ skipped / ❌ failed
   remote branch: ✅ deleted / ⏭ kept / ⏭ skipped / ✅ already-deleted / ❌ failed
```

任意 outcome=failed 时追加 `errors:` 段。

## 退出码

- `0` —— 正常完成（含副作用动作 failed；详情看终端反馈）
- `1` —— 5 项预检任一失败

## 错误降级矩阵

详见 [`reference/archive-rules.md`](../../skills/managing-requirement-lifecycle/reference/archive-rules.md) §4。

要点：副作用失败（经验调用挂 / 本地 -d 拒绝 / 远程网络挂）均不影响 archive 退出码——archive 始终 exit 0（除非预检挂）。
