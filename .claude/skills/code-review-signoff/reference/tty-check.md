# tty 校验语义

## 为什么 sign-off 需要 tty 校验

sign-off（卡点 B）是人类专属动作。AI Agent 运行在非交互式 shell 中，stdin 不是 tty。
通过 `sys.stdin.isatty()` 可以有效区分「真实人类在终端操作」与「AI 在管道/子 Agent 中调用」。

## `[ -t 0 ]` 与 `sys.stdin.isatty()` 的语义

| 检测方式 | 说明 |
|---|---|
| `[ -t 0 ]`（bash） | `test -t fd`：fd=0 时检测 stdin 是否为 tty |
| `sys.stdin.isatty()`（Python） | 等价调用，检测 `sys.stdin` 底层文件描述符的 `isatty()` 系统调用 |

两者语义相同：返回 True 表示 stdin 连接到真实终端，False 表示管道 / PIPE / 重定向。

## 校验位置（F-012 后简化为单一入口）

```
用户终端
  │
  └─ [Command 层 + Skill 层] code-review/signoff.md / code-review-signoff/SKILL.md
       └─ 委托：python3 scripts/lib/save_review.py signoff --rev-id ...
            └─ sys.stdin.isatty() ← 唯一 tty 校验（在 _run_signoff 流程步骤 0）
```

F-012 重构前曾有 **双层** 校验（Command 与 Skill 两层均跑 _check_tty()）；F-012 之后入口
合并到 `save_review.py signoff` 单层——因为：

- 入口收敛后无第二条调用路径可绕过
- 入口本身在 `_run_signoff` 第 0 步就 isatty 校验，全部下游分支都在它之后
- 减少代码重复（D-002 单一事实源 + 上下文工程"位置即语义"）

成本：仍是一次系统调用（< 10ms），收益：封堵所有管道注入和 subagent 绕过。

## 禁止的旁路

以下任何形式的旁路均违反 D-003 红线：

```bash
# 禁止
FAKE_TTY=1 python3 save_review.py signoff ...
SKIP_TTY_CHECK=1 python3 save_review.py signoff ...
DRY_RUN=1 python3 save_review.py signoff ...
```

F-002 教训：FAKE_TTY env var 曾在 code_review_routing.py 中被引入，后被用户回炉删除。
F-004a 起从设计层面杜绝——脚本内部只读 `sys.stdin.isatty()`，不读任何 env var。

## 单测的 tty mock 方式

测试时需要模拟 tty 为 True 或 False，正确做法是 monkeypatch：

```python
# 正确：直接 mock 模块函数
monkeypatch.setattr(save_review.sys.stdin, "isatty", lambda: True)

# 正确：subprocess 跑脚本，stdin=PIPE 自动为非 tty
result = subprocess.run([sys.executable, str(_SCRIPT), "signoff", "--rev-id", "..."],
                        input="", capture_output=True, text=True)
assert result.returncode == 2

# 禁止：env var 旁路
os.environ["FAKE_TTY"] = "1"  # 不要这样做
```

## ai-collaboration.md 关联

`context/team/ai-collaboration.md` 规则三明确禁止 AI 通过任何手段（包括 fake tty / pipe trick / heredoc）
绕过本校验。违反视为流程违规——人类发现即回滚 verdict 字段并在需求 notes.md 记录。
