# Phase 4 未立即修复的观察项

**沉淀原因**：供未来真实业务需求参考

## G-02：Agent Task tool 调用路径未经真实验证

Phase 4 集成验收时，需求阶段的 Agent（requirement-bootstrapper / input-normalizer / quality-reviewer / tech-feasibility-assessor / outline-design-quality-reviewer / detail-design-quality-reviewer / test-runner / traceability-consistency-checker）以及代码审查的 8 个 Agent 都由主 Agent 按 `.claude/agents/<name>.md` 的 spec "模拟"执行，未实际通过 Task tool 调用。

**原因**：Phase 4 目标是验证**流程骨架**，不是验证具体 Agent 实现细节。

**何时验证**：第一个真实业务需求时，至少有一个 Agent 需要真实 Task tool 调用，观察：
- Task tool 的 subagent_type 参数是否能正确路由到 `.claude/agents/` 下的 Agent 定义
- Agent 返回的结构化输出能否被主 Agent 正确解析
- Agent 的 tools 字段声明是否生效

## G-06：.review-scope.json 在 gitignore 的合理性

当前设计：`.review-scope.json` 是每次 `/code-review` 重写的临时文件，入 `.gitignore`。

**讨论**：是否应入库？
- 反对：每次重写，持久化无收益
- 支持：失败时可复现审查场景

**结论**：保持当前设计（gitignore）。失败复现可通过 `git log` + commit SHA 重新生成 scope。
