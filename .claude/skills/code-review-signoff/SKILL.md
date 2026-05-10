---
name: code-review-signoff
description: 卡点 B——把 human_signoff 字段写入 verdict 文件（tty 校验 + trivial 路径白名单 + schema 校验）
---

## 什么时候用

`/code-review:signoff <REV-ID>` 触发，或 feature-lifecycle-manager 在 feature 完成时引导开发者执行 sign-off 时调用。

**只有人类可以触发。AI 禁止在主对话或子 Agent 中调用本 Skill**（见 ai-collaboration.md 规则三）。

## 核心流程

F-012 后的唯一入口（旧 `code_review_signoff.py` 已合并入 `save_review.py`）：

```bash
python3 scripts/lib/save_review.py signoff \
  --rev-id <REV-ID> \
  [--decision <approved|approved-trivial|rejected>] \
  [--trivial]
```

`--signed-by` / `--signed-at` 默认从 `git config user.email` / 当前 ISO8601 时间自动取；
脚本化场景仍可显式传入（如自动化测试 / 历史数据回填）。

脚本内部流程如下：

### 1. tty 校验（D-003 红线）

```python
sys.stdin.isatty()  # False → 退出码 2
```

成本 < 10ms，收益是阻断所有 pipe 注入与 subagent 绕过。
**禁止删除此校验**，**禁止引入任何 env var 旁路**（D-003 红线，FAKE_TTY / DRY_RUN_TTY 等已封禁）。

非 tty → 退出码 2，stderr：`signoff: stdin not a tty, refuse to sign for AI`

### 2. --decision 与 --trivial 互斥校验

```bash
# 合法
save_review.py signoff --rev-id <ID> --decision approved
save_review.py signoff --rev-id <ID> --trivial

# 非法（退出码 1）
save_review.py signoff --rev-id <ID> --decision approved --trivial
save_review.py signoff --rev-id <ID>            # 二者均缺
```

### 3. --trivial 路径白名单判定（仅 --trivial 模式）

```bash
git diff --name-only --diff-filter=ACMR main..HEAD
```

全部文件路径 ∈ `{*.md, docs/**, *.txt}` → `decision = "approved-trivial"`，继续
否则 → 退出码 3，stderr：`trivial: non-doc files detected: <paths>`

### 4. 取 git 身份 + 时间戳（自动填充）

- `git config user.email` → `signed_by`（CLI 未显式传入 `--signed-by` 时）
- `datetime.now(timezone.utc).astimezone().isoformat()` → `signed_at`（CLI 未显式传入 `--signed-at` 时）
- `"cli-tty"` → `source`（固定值，D-004 预留扩展点）

git email 无效 / 缺失 → 退出码 1，stderr：`signoff: 无法获取 git config user.email，请先配置`

### 5. 定位 verdict + 已签字预检 + 写入

- 定位 `requirements/<req>/reviews/<phase[-feature_id]>-NNN.json`
- 不存在 → 退出码 4
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
| 1 | 参数非法 / 缺 git email / CR-1~CR-8 校验失败 | `signoff: 必须指定 --decision ...` / `signoff: --trivial 与 --decision 不能同时...` / `signoff: 无法获取 git config user.email` / CR 详情 |
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

- [`reference/tty-check.md`](reference/tty-check.md) — tty 校验语义说明
- `scripts/lib/save_review.py` — F-012 后唯一入口（含 _check_trivial_paths / _get_git_email / _get_iso8601_now / _run_signoff）
