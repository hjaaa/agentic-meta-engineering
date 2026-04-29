# Hook Fail-Open 规范

## 原则

任何 PreToolUse / PreCommit / 类似的"工具调用前置拦截器"hook，**必须区分**两类故障并采用不同退出码语义：

| 故障类别 | 退出码语义 | 行为 |
|---|---|---|
| **业务规则失败**（gate FAIL，规则确实拒绝该操作） | hook exit 2（阻断） | 透传 stderr 给用户，让用户改 |
| **基础设施自身故障**（runner 崩、import 失败、registry 损坏、conflict marker、依赖不可用） | hook exit 0（放行）+ WARNING | 打 WARNING 到 stderr，工具调用照常进行 |

**禁止**：把 `rc != 0` 一刀切翻译为阻断。这等于把"门禁系统"变成"DOS 武器"——任何 runner 自身的问题都会瘫痪整个工具链。

## 为什么 fail-open

### 反例：fail-closed 死锁

```
git merge → run.py 含 <<<<<<< HEAD 冲突 marker
   ↓
Claude 调任何工具
   ↓
PreToolUse hook 触发 → python3 scripts/gates/run.py
   ↓
import 阶段 SyntaxError → exit 1
   ↓
hook 看到 rc != 0 → 阻断
   ↓
工具调用被拒 → 无法用 Edit/Bash/Write 解冲突 → 死锁
```

REQ-2026-002 F-004 round-4 实测踩中此坑（process.txt 2026-04-29 14:30 段）；F-003 14:34 也踩过（H5 半成品 plugin → 同一死锁模式）。修一次没修架构就会复发。

### 正解：infra-failure fail-open + WARNING

- 业务规则失败仍然阻断（`rc=1`），用户拿到清晰错误，能改
- runner 自身崩了（`rc=2` 或信号终止）就放行，但打 stderr WARNING——用户立刻看到"门禁系统坏了"，但工具链不被自身锁死
- WARNING 不会被静默：`stderr` 在 Claude Code 中可见，hook 自检也能监听

## 实现要点

### 退出码翻译矩阵（推荐模板）

```bash
RUNNER_ERR=$(mktemp -t gate-runner-err.XXXXXX)
python3 <runner> --trigger=<...> 2>"$RUNNER_ERR"
rc=$?
case "$rc" in
    0)
        rm -f "$RUNNER_ERR"
        exit 0  # 全过 → 放行
        ;;
    1)
        cat "$RUNNER_ERR" >&2  # 业务级 fail：透传规则失败原因
        rm -f "$RUNNER_ERR"
        exit 2  # 阻断（Hook 协议）
        ;;
    *)
        # 含 rc=2 (runner 自身异常) / 130 (Ctrl+C) / 137 (OOM kill) 等
        echo "WARNING <hook-name> runner 自身故障 (rc=$rc)，fail-open 放行避免锁死工具链：" >&2
        cat "$RUNNER_ERR" >&2
        rm -f "$RUNNER_ERR"
        exit 0  # 不阻断
        ;;
esac
```

### Runner 端的责任

Hook fail-open 是**最后一道防线**，不是借口。Runner 仍然必须：

- **退出码语义干净**：业务 fail 必须 `rc=1`，自身异常必须 `rc=2`（不要混用）
- **stderr 可读**：异常时输出"故障类别 + 修复 hint"，不只是 traceback
- **registry 加载快**：基础设施级故障应在 import 阶段被捕获，不要在 plugin run 时才崩

REQ-2026-002 的 `scripts/gates/run.py` 在 F-004 round-3 G-5 已经统一了退出码（参考 `run.py:131-135` docstring），符合本规范。

### 监控与告警

fail-open 不是"假装一切正常"。要补：

1. **审计日志**：每次 fail-open 写一行到长期保留的日志（如 audit/）
2. **冷自检**：cron / CI 每天跑一次 `--validate-registry`，runner 永久损坏时主动告警
3. **PR review 焦点**：改 hook 协议、改 runner 自检逻辑的 PR 必须 review 关注 fail-open 是否被绕过

## 适用范围

- `.claude/hooks/*.sh` 系列
- `scripts/git-hooks/pre-commit` 等本地 git hook
- CI pipeline 里的"前置拦截"step（虽然 CI 失败可重跑，但仍建议同协议保持一致）

**不适用**：post-action 检查器（`PostToolUse` 等）。post 类 hook 失败本身就不能阻断已完成的操作，fail-open 是默认行为。

## 反模式

❌ `rc != 0 → exit 2` 一刀切  
❌ 用 `set -e` 让 hook 在任何错误时崩溃  
❌ 把 hook 装到 runner 自身依赖的目录（自举陷阱）  
❌ fail-open 时静默放行（无 WARNING）  

## 来源

- REQ-2026-002 F-004 round-4 实战教训（process.txt 2026-04-29 14:30~14:43）
- REQ-2026-002 F-003 H5 改造死锁（process.txt 2026-04-28 14:34）
- 落地实现：`scripts/gates/triggers/pre_tool_use.sh:63-90`（F-004 round-4 加固）
