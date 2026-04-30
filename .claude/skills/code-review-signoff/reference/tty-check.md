# tty 校验语义与双层防御

## 为什么 sign-off 需要 tty 校验

sign-off（卡点 B）是人类专属动作。AI Agent 运行在非交互式 shell 中，stdin 不是 tty。
通过 `sys.stdin.isatty()` 可以有效区分「真实人类在终端操作」与「AI 在管道/子 Agent 中调用」。

## `[ -t 0 ]` 与 `sys.stdin.isatty()` 的语义

| 检测方式 | 说明 |
|---|---|
| `[ -t 0 ]`（bash） | `test -t fd`：fd=0 时检测 stdin 是否为 tty |
| `sys.stdin.isatty()`（Python） | 等价调用，检测 `sys.stdin` 底层文件描述符的 `isatty()` 系统调用 |

两者语义相同：返回 True 表示 stdin 连接到真实终端，False 表示管道 / PIPE / 重定向。

## 双层校验（Command 预检 + Skill 二次校验）

```
用户终端
  │
  ├─ [Command 层] code-review/signoff.md
  │    └─ 预检：python3 scripts/lib/code_review_signoff.py --rev-id ...
  │         └─ _check_tty() ← 第一层校验
  │
  └─ [Skill 层] code-review-signoff/SKILL.md
       └─ 委托：python3 scripts/lib/code_review_signoff.py
            └─ _check_tty() ← 第二层校验（深防御）
```

**为什么两层都要检测**：

- Command 层是用户入口，理论上已校验 tty
- 但 Skill 可以被绕过 Command 直接调用（如 `python3 code_review_signoff.py --rev-id ...`）
- 二次校验确保：即便调用路径跳过 Command，非 tty 环境也会被拒绝
- 成本：一次系统调用（< 10ms），收益：封堵所有管道注入和 subagent 绕过

**禁止删除二次校验**——即便认为"Command 已经检查过了"，深防御不冗余。

## 禁止的旁路

以下任何形式的旁路均违反 D-003 红线：

```bash
# ❌ 禁止
FAKE_TTY=1 python3 code_review_signoff.py ...
SKIP_TTY_CHECK=1 python3 code_review_signoff.py ...
DRY_RUN=1 python3 code_review_signoff.py ...
```

F-002 教训：FAKE_TTY env var 曾在 code_review_routing.py 中被引入，后来被用户回炉删除。
本期（F-004a）从设计层面杜绝——脚本内部只读 `sys.stdin.isatty()`，不读任何 env var。

## 单测的 tty mock 方式

测试时需要模拟 tty 为 True 或 False，正确做法是 monkeypatch：

```python
# ✅ 正确：直接 mock 模块函数
monkeypatch.setattr(code_review_signoff, "_check_tty", lambda: True)

# ✅ 正确：subprocess 跑脚本，stdin=PIPE 自动为非 tty
result = subprocess.run([sys.executable, str(_SCRIPT), "--rev-id", "..."],
                        input="", capture_output=True, text=True)
assert result.returncode == 2

# ❌ 禁止：env var 旁路
os.environ["FAKE_TTY"] = "1"  # 不要这样做
```

## F-004b 关联（占位）

F-004b 实施后，`context/team/ai-collaboration.md` 将新增规则三（「sign-off 是人类专属动作」），
明确禁止 AI 通过任何手段（包括 fake tty / pipe trick / heredoc）绕过本校验。
届时可在此处补充引用：`context/team/ai-collaboration.md:规则三`。
