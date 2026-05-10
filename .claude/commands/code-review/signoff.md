---
description: 完成代码审查的人类卡点 B——把 human_signoff 字段写入 verdict 文件
argument-hint: "<REV-ID> [--decision=<approved|approved-trivial|rejected>] [--trivial]"
---

## 用途

完成代码审查的人类卡点 B：把 `human_signoff` 字段写入 verdict 文件。

**只有人类可以执行此命令。** AI Agent 在主对话或子 Agent 中禁止调用（见 ai-collaboration.md 规则三）。

## 用法

```
/code-review:signoff <REV-ID> [--decision=<v>] [--trivial]
```

- `<REV-ID>`：verdict 的 review_id，如 `REV-REQ-2026-003-definition-001`
- `--decision`：sign-off 决策，可选值 `approved` / `approved-trivial` / `rejected`
- `--trivial`：纯文档变更快速通道（与 --decision 互斥；自动设 decision=approved-trivial）

## 委托

此 Command 不含业务逻辑——预检与执行全部委托给入口脚本（F-012 后唯一用户入口）：

```bash
python3 scripts/lib/save_review.py signoff \
  --rev-id <REV-ID> \
  [--decision <v>] \
  [--trivial]
```

Claude Code 在调用本 Command 时，必须运行上述脚本，不得自行解析参数或直接写 verdict 文件。

`--signed-by` / `--signed-at` 默认从 `git config user.email` / 当前 ISO8601 时间自动取（F-012 简化）；
脚本化场景仍可显式传入。

## 预检（脚本内部执行，全部失败立即 exit）

| 序号 | 预检项 | 失败退出码 | stderr 子串 |
|---|---|---|---|
| 1 | stdin 是 tty（`sys.stdin.isatty()`） | 2 | `signoff: stdin not a tty, refuse to sign for AI` |
| 2 | --decision 与 --trivial 互斥；二者必择一 | 1 | `signoff: --trivial 与 --decision 不能同时使用` / `必须指定 --decision` |
| 3 | `--trivial` 通道：git diff 全部 ∈ `*.md` / `docs/**` / `*.txt` | 3 | `trivial: non-doc files detected: <paths>` |
| 4 | git config user.email 存在 + 格式合法（未传 --signed-by 时） | 1 | `signoff: 无法获取 git config user.email` |
| 5 | REV-ID 对应 verdict 文件存在 | 4 | `signoff: verdict <REV-ID> not found` |
| 6 | `verdict.human_signoff` 未填 | 5 | `signoff: already signed by <email> at <time>` |

## 执行流程（脚本内部）

预检通过后：

1. tty 校验（深防御，绝不允许 FAKE_TTY 等 env var 旁路）
2. `--trivial` 路径白名单判定（git diff 全部 ∈ `*.md` / `docs/**` / `*.txt` 才放行）→ 强制 decision=approved-trivial
3. 自动取 `git config user.email` → `signed_by`；ISO8601 含时区 → `signed_at`
4. 写 verdict.human_signoff 字段 + 全量重跑 CR-1~CR-8 + append `process.txt`

## 退出码速查

| 退出码 | 含义 |
|---|---|
| 0 | 签字成功 |
| 1 | 参数非法（--decision / --trivial 互斥冲突 / 缺 git email / CR 校验失败） |
| 2 | 非 tty stdin，拒绝 AI 代签 |
| 3 | --trivial 通道检测到非文档文件 |
| 4 | verdict 文件不存在 |
| 5 | 已签字，禁止重复签名 |

## 示例

```bash
# 普通 sign-off
/code-review:signoff REV-REQ-2026-003-code-F-004a-001 --decision=approved

# 纯文档变更快速通道
/code-review:signoff REV-REQ-2026-003-definition-001 --trivial
```
