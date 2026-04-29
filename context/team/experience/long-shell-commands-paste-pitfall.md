# 长 shell 命令粘贴在 zsh 易被切碎导致 permission denied

**沉淀原因**：AI 给用户终端命令时反复用反斜杠续行 / 单行超长，跨人/跨终端环境会重复。本会话同款问题踩了 2 次（不同文件名都报 `permission denied`）。

## 问题

AI 给用户的终端命令含反斜杠续行（`\`）或单行超过 ~200 字符。用户复制粘贴到 zsh 时：
- 某些终端的 bracketed paste 在续行符附近裁断
- 单行超长时窗口宽度限制可能让 zsh 误把后续行当新命令

zsh 把"非命令的文件路径"当 first word 执行 → `permission denied: tests/gates/test_runner.py`（因为 .py 文件没有执行位）。原意是 `git checkout --ours tests/gates/test_runner.py` 但 zsh 看到的是裸的 `tests/gates/test_runner.py`。

## 根因

终端的复制粘贴 + 行续行符 + 自动换行三者交互不可预测。AI 给用户的终端命令应当：
- 字符总长 < 200（避免单行被截断）
- 不依赖 `\` 续行（粘贴时易丢失）
- 多步骤拆成多行各自独立短命令

## 解法

给用户的终端命令优先级：

1. **最优**：单条短命令 + 多次粘贴（< 80 字符 / 行，无续行符）
2. **次优**：把复杂命令封装到一个临时 shell 脚本里，让用户跑 `bash /tmp/x.sh`
3. **慎用**：`&&` 链式（不加续行符的单行），仅当总长 < 150 字符时
4. **禁用**：反斜杠续行的多行复合命令、超过 200 字符的单行

debug 时如果用户报 `permission denied: <某个 .py/.yaml/.md 文件>`，**不是权限问题** —— 是粘贴被切碎让 zsh 把数据文件当命令执行。建议用户复制更短的命令。

## 验证方法

- 让用户跑 `git merge --abort`（12 字符短命令）成功后，对比之前 200 字符 git checkout 命令报错的输出
- AI 自检：给用户的命令包含 `\\\n` 或单行 > 200 字符 → 重写为多行短命令

## 引用来源

- `requirements/REQ-2026-002/process.txt` 2026-04-29 14:34~14:43 段（2 次 permission denied）
- 反例：`git checkout --ours requirements/.../process.txt scripts/.../review_verdict.py ... && \ git add ...`（被切碎）
- 正解：`git merge --abort`（12 字符，零冲突）
