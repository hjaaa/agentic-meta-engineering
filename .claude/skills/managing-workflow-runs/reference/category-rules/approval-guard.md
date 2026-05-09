# Approval 节点人机鉴别规则（D-006）

来源：requirements/REQ-2026-009/plan.md D-006（行 101-108）

## 核心原则

`approve` / `reject` 是**人类专属动作**，任何 AI Agent（主 Claude / subagent）在主对话或子 Agent 中禁止调用。

## 双层校验机制

### 第一层：Hook 拦截（F-013 落地）

pre-tool-use hook 识别调用方是 AI：

- 拦截条件：工具调用来源不是 tty 终端用户
- 动作：拒绝，exit 2，stderr `BLOCKED: approve/reject requires human in tty`

> F-013 落地前，hook 层仅做 mock。F-005 命令实现不依赖 hook 层功能性，只调 isatty 兜底。

### 第二层：isatty 兜底（F-005 范围，fail-closed）

`workflow_approve.py` / `workflow_reject.py` 入口文件内：

```python
import sys
if not sys.stdin.isatty():
    print("ERROR [E-WF-TTY-001]: approve/reject 需要 tty 终端（人类专属动作）", file=sys.stderr)
    sys.exit(2)
```

- 任何 AI shell / subprocess / pipe / heredoc 调用 → `sys.stdin.isatty()` 返回 False → exit 2
- 不得通过 fake-tty / pty / expect 等方式绕过

## 违规处理

- 人类发现 AI 绕过校验 → 回滚对应 `approval_approved` / `approval_rejected` 事件
- 在需求 notes.md 记录违规事件

## 测试策略（TC-F5-1 happy_path 相关）

- 测试 approve / reject 时 mock `sys.stdin.isatty()` 返回 True，模拟 tty 环境
- 测试 non-tty 路径时 mock 返回 False，验证 exit 2
