---
description: 完成代码审查的人类卡点 B——把 human_signoff 字段写入 verdict 文件
argument-hint: "<REV-ID> [--decision=<approved|approved-trivial|rejected>] [--trivial]"
---

## 用途

完成代码审查的人类卡点 B：把 `human_signoff` 字段写入 verdict 文件。

**只有人类可以执行此命令。** AI Agent 在主对话或子 Agent 中禁止调用（见 F-004b ai-collaboration.md 规则三）。

## 用法

```
/code-review:signoff <REV-ID> [--decision=<v>] [--trivial]
```

- `<REV-ID>`：verdict 的 review_id，如 `REV-REQ-2026-003-definition-001`
- `--decision`：sign-off 决策，可选值 `approved` / `approved-trivial` / `rejected`
- `--trivial`：纯文档变更快速通道（与 --decision 互斥；自动设 decision=approved-trivial）

## 委托

此 Command 不含业务逻辑——预检与执行全部委托给入口脚本：

```bash
python3 scripts/lib/code_review_signoff.py \
  --rev-id <REV-ID> \
  [--decision <v>] \
  [--trivial]
```

Claude Code 在调用本 Command 时，必须运行上述脚本，不得自行解析参数或直接写 verdict 文件。

## 预检（脚本内部执行，全部失败立即 exit）

| 序号 | 预检项 | 失败退出码 | stderr 子串 |
|---|---|---|---|
| 1 | stdin 是 tty（`sys.stdin.isatty()`） | 2 | `signoff: stdin not a tty, refuse to sign for AI` |
| 2 | REV-ID 对应 verdict 文件存在 | 4 | `signoff: verdict <REV-ID> not found` |
| 3 | `verdict.human_signoff` 未填 | 5 | `signoff: already signed by <email> at <time>` |
| 4 | `--decision` 合法 | 1 | `signoff: invalid decision <x>, expected one of [approved, approved-trivial, rejected]` |

## Skill 委托

预检通过后，脚本内部调用 Skill `code-review-signoff` 的等价逻辑：

1. 二次 tty 校验（深防御，防 Skill 被绕过 Command 直接调用）
2. `--trivial` 路径白名单判定（git diff 全部 ∈ `*.md` / `docs/**` / `*.txt` 才放行）
3. 取 `git config user.email` → `signed_by`；ISO8601 含时区 → `signed_at`
4. 调 `save_review.py signoff` 子命令写盘 + CR-1~CR-8 全量校验 + append `process.txt`

## 退出码速查

| 退出码 | 含义 |
|---|---|
| 0 | 签字成功 |
| 1 | 参数非法（--decision 非法值 / 互斥参数） |
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
