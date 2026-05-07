# Claude Code PreToolUse 的 matcher 字符串 vs 实际 tool_name 别名映射

**沉淀原因**：跨需求重复（任何用 PreToolUse 钩 Task/Agent 派发的 hook）、AI 反复错（按文档/直觉用 matcher 字符串去比对 tool_name）、跨会话保留（属于 Claude Code 端实现细节，不读不知道）。

## 问题

REQ-2026-008 detail-design 期实采样发现：
- `.claude/settings.json` 写 `"matcher": "Task"` 命中 PreToolUse 钩子
- 但 hook stdin 收到的 JSON 里 `tool_name == "Agent"`（不是 `"Task"`）

按设计文档原假设的 `tool_name == "Task"` 判断会**全员漏放**——hook 起来了但内部 `if tool_name != "Task": return` 直接跳过校验逻辑，等于形同虚设。

## 根因

Claude Code 端在 matcher 字符串与 tool_name 之间存在**别名映射**：派发 subagent 的工具实际叫 `Agent`，但 settings.json 里写 `"Task"` 仍然命中（历史命名漂移；matcher 是模糊匹配，tool_name 是精确字段）。

## 解法

**hook 实现层 ≠ matcher 配置层**，两个分开看：

- `.claude/settings.json` 的 `matcher` 字段：保留官方文档约定字符串（如 `"Task"`），不要"修正"
- hook 内部的 tool_name 校验：以 stdin JSON 的实际值为准（`tool_name == "Agent"`）
- 实采样路径：派一次 subagent → 让 hook 把 stdin JSON `cat >&2` → 看 `tool_name` 实际是什么

## 验证方法

- 在 hook 里加一行 `print(f"tool_name={data.get('tool_name')}", file=sys.stderr)`（或 `cat $stdin >&2`），跑一次真实派发就能看到
- 单测 fixture 里 `tool_name` 字段必须用实采样到的值（`"Agent"`），不能照 matcher 字符串写 `"Task"`

## 引用来源

- `requirements/REQ-2026-008/notes.md`（2026-05-06 09:42 detail-design 首日 #2 实采样）
- `.claude/hooks/dispatch_precheck.py`（最终以 `tool_name == "Agent"` 实现）
- `requirements/REQ-2026-008/plan.md` D-007（实采样修订条目）
