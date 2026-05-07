# 临时 hook 采样要绕开 self-modification 防护

**沉淀原因**：跨需求重复（任何要在设计阶段做 hook / dispatch 实采样的 REQ）、AI 反复错（直觉路径——直接 Edit `.claude/settings.local.json` 注入临时 hook——会被防护连续拒绝）、跨会话保留（Claude Code 自我修改防护是默认开启的边界，不知道就会反复撞墙）。

## 问题

REQ-2026-008 detail-design 期需要实采样 PreToolUse Task 派发的 stdin JSON 长什么样（确认 `tool_name` 实际值）。

直觉路径是临时往 `.claude/settings.local.json` 注入一个 cat-and-exit 的 hook，跑一次派发，删除 hook。但 Claude Code 的"self-modification 防护"会拒绝 AI 直接 Edit 这类 hook 配置文件——连续两次都被拦下，而且越尝试越触发警报。

## 根因

`.claude/settings.local.json` / `.claude/hooks/*` 是 AI 自身行为的来源。Claude Code 把它们标记为"AI 不可自我修改"——AI Edit 这些文件 ≈ AI 改自己的"宪法"，安全策略默认阻断。

## 解法

走"用户授权"路径，不走"AI 自动注入"路径：

1. **临时一次性命令**：把 hook 逻辑写成一行 Python，让用户在终端敲 `! python3 -c "..."` 跑（或用户复制黏贴到自己的 shell）。`!` 前缀是 Claude Code 让用户主动跑命令的合规通道
2. **常驻 hook（采样多次）**：明确告知用户"我需要安装一个临时 hook 到 X，跑完会让你删"，让用户**自己** Edit settings.local.json，跑完用户**自己**清掉
3. 不要重试 AI 直接 Edit `.claude/settings.local.json`——它是设计上不可绕的防护

## 验证方法

- AI Edit 防护文件被拒后，立即停手切到上述两条路径之一
- 实采样 SOP 应在设计文档（如 `subagent-dispatch.md` 附录"采样自检流程"）明确这两条合规路径

## 引用来源

- `requirements/REQ-2026-008/notes.md`（2026-05-06 09:42 detail-design 首日 #2 实采样）
- 配套经验：`claude-code-tool-name-matcher-alias.md`（实采样揭示的具体内容）
