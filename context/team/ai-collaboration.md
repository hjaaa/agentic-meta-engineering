# 和 AI 协作的基本准则

本文档是所有人和所有 Agent 共享的协作规范。Agent 会自动引用；人类第一次读一次即可。

## 核心认知转变

你的核心工作从"写代码"变成"引导上下文 + 验证结果"。

```
代码输出质量 = AI 能力 × 上下文质量
```

瓶颈在**上下文**，不在 AI。规范已预制，无需告诉 AI "怎么做"，只需告诉它"做什么"和"业务背景"。

## 两条硬规则（Agent 必须遵守）

### 规则一：刨根问底（Source-or-Mark）

Agent 写入 `requirements/<id>/artifacts/*.md` 的每条关键信息必须属于三种状态之一：

| 状态 | 处理 |
|---|---|
| 有项目内引用 | 直接引用，格式 `路径:行号` |
| 无引用但可确认 | 标记 `[待用户确认]` 并列入待澄清清单 |
| 完全无法确认 | 标记 `[待补充]`，给出假设（内容/依据/风险/验证时机） |

**不允许第四种状态**："没来源但看起来合理就写了"。这是幻觉的来源。

### 规则二：渐进式输出（Progressive Disclosure）

文档类输出必须分步：

1. 先输出 **3-5 条关键确认点**（摘要 / 决策点 / 待确认项）
2. 等用户确认方向后再输出正式文档

禁止一次性输出完整长文档。

### 规则三：sign-off 是人类专属动作

**Sign-off 唯一入口**（人类在 tty 终端执行）：

```bash
python3 scripts/lib/code_review_signoff.py --rev-id <REV-ID> --decision <approved|approved-trivial|rejected>
# slash command 糖（等价）：/code-review:signoff <REV-ID> --decision=<v>
```

Agent 在主对话或子 Agent 中，**禁止**调用上述入口，也**禁止**调用其底层实现以防绕过 tty 校验深防御层：

- `python3 scripts/lib/code_review_signoff.py ...`（唯一用户入口）
- `/code-review:signoff <REV-ID>`（slash command 糖，最终也调上面入口）
- `python3 scripts/lib/save_review.py signoff ...`（底层实现，绕过 code_review_signoff.py 的预检层）

> 注：`scripts/save-review.sh` 是**写 verdict** 的入口（reviewer Agent 用），不接受 `signoff` 子命令；用户不要把它当作 sign-off 入口。

调用前的 tty 校验（`sys.stdin.isatty()`）会拒绝 AI shell，但 AI 不得通过假 tty / pipe trick / heredoc 等方式绕过。
违反视为流程违规——人类发现即回滚 verdict 字段并在需求 notes.md 记录。

**Approval 唯一入口**（人类在 tty 终端执行）：

```bash
/workflow:approve   # slash command 形式（最终调 workflow_approve.py）
/workflow:reject <reason>
```

底层实现 `python3 scripts/lib/workflow_approve.py` / `workflow_reject.py` 同样禁止 AI 调用。
hook 层（`.claude/hooks/pre-tool-use-guard.sh`）已加 D-006 拦截；CLI 层 `sys.stdin.isatty()` fail-closed 兜底。

## 人的最小行动路径（5 步）

1. **说出场景** — "我要开发一个新需求" / "继续之前的需求" / "帮我审查一下这段代码"
2. **提供业务上下文** — Jira/TAPD 链接、关键业务规则、关注的代码位置
3. **让 AI 按规范推进** — 它会自动阶段检查、更新状态
4. **验证与纠偏** — 检查输出，有问题就具体反馈（不要"感觉不对"，要"在 X 文件 Y 行，期望 Z 但看到 W"）
5. **确认沉淀** — `notes.md` 和 `context/` 是否按需更新了

## 验证清单（每次重要输出后）

- [ ] 能编译（若涉及代码）
- [ ] 测试通过
- [ ] 核心逻辑符合预期
- [ ] 边界条件处理了
- [ ] 无安全隐患
- [ ] 日志足够定位问题且不泄露敏感

## 纠偏示范

❌ 不好：「这段代码有问题，改一下」
✅ 好：「在 `service/UserService.java:42`，当 userId 为 null 时会 NPE。期望返回空列表。要求最小改动修复，不要重构其他逻辑。」

## 成长路径参考

| 阶段 | 时间 | 标志 |
|---|---|---|
| 入门 | 1-2 周 | 能用 AI 完成简单需求，流程顺畅 |
| 熟练 | 1-2 月 | 复杂需求也能高效完成，project 级上下文丰富 |
| 精通 | 3+ 月 | 能优化规范、设计可复用 Skill、帮助团队成员上手 |
