---
name: testing
node_id: test-runner-execute
version: 1.0.0
---

# 测试验收阶段（testing）

阶段 8：testing

本阶段包含以下节点：
- `test-traceability-check`（skill: traceability-gate-checker）：校验"需求→设计→代码→测试"追溯链完整性
- `test-fix-loop`（loop）：traceability 校验失败时循环修复，最多 5 次
- `test-runner-execute`（agent: test-runner）：执行 JUnit / PyTest / Go test，产出 `test-report.md`
- `test-report-artifact-check`（artifact）：校验 test-report.md 必填章节
- `test-final-signoff`（approval）：人工确认测试验收通过

测试报告必须包含：
- 总用例数 / 通过数 / 失败数 / 跳过数
- 失败用例详情（含 stack trace）
- 覆盖率（如可获取）

本阶段所有 AI 工作节点均为 skill/agent/loop/artifact/approval 类型，prompt 由各 Agent 定义文件管理。
此文件为阶段占位 prompt，标识本阶段的语义边界。
