---
name: code-review-signoff
description: 卡点 B——把 human_signoff 字段写入 verdict 文件（tty 双校验 + trivial 路径白名单 + schema 校验）
---

## 什么时候用

`/code-review:signoff <REV-ID>` 触发，或 feature-lifecycle-manager 在 feature 完成时引导开发者执行 sign-off 时调用。

**只有人类可以触发。AI 禁止在主对话或子 Agent 中调用本 Skill**（见 F-004b ai-collaboration.md 规则三）。

## 核心流程

实际执行委托给 `scripts/lib/code_review_signoff.py`，Claude Code 调用本 Skill 时必须运行：

```bash
python3 scripts/lib/code_review_signoff.py \
  --rev-id <REV-ID> \
  [--decision <approved|approved-trivial|rejected>] \
  [--trivial]
```

脚本内部流程如下：

### 1. 二次 tty 校验（深防御）

```python
sys.stdin.isatty()  # False → 退出码 2
```

即便 Command 层已做过 tty 预检，Skill 层**必须**再做一次——防止 Skill 被绕过 Command 直接调用。
成本 < 10ms，收益是阻断所有 pipe 注入与 subagent 绕过。
**禁止删除此校验**，**禁止引入任何 env var 旁路**（D-003 红线）。

非 tty → 退出码 2，stderr：`signoff: stdin not a tty, refuse to sign for AI`

### 2. --trivial 路径白名单判定（仅 --trivial 模式）

```bash
git diff --name-only --diff-filter=ACMR <base>..HEAD
```

全部文件路径 ∈ `{*.md, docs/**, *.txt}` → `decision = "approved-trivial"`，继续
否则 → 退出码 3，stderr：`trivial: non-doc files detected: <paths>`

### 3. 取 git 身份 + 时间戳

- `git config user.email` → `signed_by`
- `datetime.now(timezone.utc).astimezone().isoformat()` → `signed_at`（ISO8601 含时区）
- `"cli-tty"` → `source`（固定值，D-004 预留扩展点）

### 4. 调 save_review.py signoff 子命令

```bash
python3 scripts/lib/save_review.py signoff \
  --rev-id <REV-ID> \
  --decision <decision> \
  --signed-by <email> \
  --signed-at <iso8601> \
  --source cli-tty
```

`save_review.py signoff` 内部：
- 定位 `requirements/<req>/reviews/<phase[-feature_id]>-NNN.json`
- 检查 verdict 是否已签（防重复）→ 退出码 5
- 写 `human_signoff = {decision, signed_at, signed_by, source}`
- 全量重跑 CR-1 ~ CR-8
- 通过 → 写盘 + append `requirements/<req>/process.txt`：
  `<ts> [signoff] <REV-ID> <decision> by <email>`
- 失败 → 退出码 1 + stderr CR 详情

## 退出码完整矩阵

| 退出码 | 触发场景 | stderr 子串 |
|---|---|---|
| 0 | 签字成功 | — |
| 1 | 参数非法 / CR-1~CR-8 校验失败 | `signoff: invalid decision ...` / CR 详情 |
| 2 | stdin 非 tty | `signoff: stdin not a tty, refuse to sign for AI` |
| 3 | --trivial 含非文档文件 | `trivial: non-doc files detected: <paths>` |
| 4 | verdict 文件不存在 | `signoff: verdict <REV-ID> not found` |
| 5 | 已签字，禁止重复 | `signoff: already signed by <email> at <time>` |

## 硬约束

- ❌ 禁止绕过 tty 校验（不允许 FAKE_TTY / DRY_RUN_TTY 等 env var）
- ❌ 禁止 AI 在主对话或子 Agent 中调用本 Skill
- ❌ 禁止直接写 verdict JSON 文件（必须走 `save_review.py signoff`）
- ✅ tty 校验细节见 [`reference/tty-check.md`](reference/tty-check.md)

## 参考资源

- [`reference/tty-check.md`](reference/tty-check.md) — tty 校验语义与双层防御说明
- `scripts/lib/code_review_signoff.py` — 本 Skill 实际入口脚本
- `scripts/lib/save_review.py` — signoff 子命令实现（含 CR-1~CR-8 + process.txt）
