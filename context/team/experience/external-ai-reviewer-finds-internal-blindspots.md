# 外部 AI reviewer 抓内部 checker 链漏掉的 P1

**沉淀原因**：跨需求会重复（A）+ 跨会话需保留（C）

## 问题

REQ-2026-006 PR #54 经过完整内部审查链：8 个专项 checker（complexity / concurrency / security / performance / error-handling / design-consistency / history-context / auxiliary-spec）+ review-critic 对抗验证 + code-quality-reviewer Judge 综合裁决，全部 looks_clean。submit 后 Codex 一句话抓到 2 条 P1：

- **round-1**：bash producer 用 cwd-relative 路径，Python consumer 用 `__file__`-relative，cwd ≠ repo 时 audit 静默丢
- **round-2**：`audit-flush.sh` 用 `python3 scripts/lib/audit_flush.py`（cwd-relative），SessionEnd 在异 cwd 时 file-not-found 被 stderr + `|| true` 静默吞

两条都是「跨语言路径语义」「hook 调用 cwd 不确定性」类系统性 bug，本地测试都过了（因为本地 cwd = repo）。

## 根因

内部 checker 链是按已知模式分类设计的：注入 / 并发 / N+1 / 鉴权绕过 / 异常吞没……每个 checker 在自己的领域内深耕。但「跨语言路径锚定」「hook cwd 假设」这类系统性思考跨在多个 checker 的领域之间，每个 checker 都看不全图，judge 也只综合了既有结果而非自己重新发问。

外部 AI reviewer（Codex / GitHub Copilot Review）是更通用的语言模型，不局限于预设的检查领域，反而能从全局逻辑视角发问，覆盖内部 checker 的盲点。这两类工具是**互补**关系，不是冗余。

## 解法

**Merge 前必过外部 reviewer**——不要因为内部审查全 pass 就跳：

- GitHub PR：开 Codex / Copilot Review（仓库已配自动触发）；如未触发，PR 评论 `@codex review`
- 关键 PR（涉及多语言管道、hook 链、跨进程通信、异步路径）必须主动触发外部 reviewer 至少 1 轮
- 外部 reviewer 的 P1 / P2 finding 必修；P3 / nit 视成本决定

**Round-trip 节奏**：每次修复后再触发一次外部 reviewer（`@codex review`），直到 "no major issues"。

**长期改进**：外部 reviewer 反复抓到的领域 → 反哺内部 checker 设计（如 cross-language-pipeline-path-anchor 经验沉淀后，可以加 `cross-lang-pipeline-checker`）。

## 验证方法

PR 开出后 → 等内部 review 通过 → 触发 `@codex review` → 至少 1 轮 "no major issues" → 才 merge。

## 引用来源

- `requirements/REQ-2026-006/process.txt`（PR #54 Codex round-1/round-2 P1）
- PR #54 review history：`https://github.com/hjaaa/agentic-meta-engineering/pull/54`
- 关联经验：`cross-language-pipeline-path-anchor.md`（被 Codex round-1 抓到的具体场景）
