---
name: traceability-gate-checker
description: 测试阶段切换前的追溯链门禁——校验需求→设计→代码→测试链完整。Phase 2 先做静态检查，Phase 3 后调用 traceability-consistency-checker Agent 做深度校验。
---

## 什么时候用

由 `managing-requirement-lifecycle` 在切换到 `testing` 阶段之前自动调用。

## 核心流程（Phase 2 静态检查版）

1. **读 `features.json`**，列出所有 feature_id
2. **对每个 feature_id，检查**：
   - **出现在 `detailed-design.md`**（grep `@feature:<id>` 或章节标题匹配）
   - **出现在代码变更中**（grep `@feature:<id>` 注解 / commit 消息 / branch 历史）
   - **出现在 `test-report.md`**（每个 feature 至少 1 个测试用例）
3. **收集缺口**：哪些 feature_id 在哪环缺失
4. **输出结论**：
   - 全链完整 → `PASS`，允许进入测试阶段
   - 任一环缺失 → `FAIL`，列出具体缺口 + 阻止切换

## 核心流程（Phase 3 增强版）

上述基础上，调用 `traceability-consistency-checker` Agent 做语义级深度校验：

- 同名接口在设计和代码中的签名一致性
- 测试用例是否覆盖了设计中的所有分支
- 变更范围是否偏离了需求描述

调用方式（Phase 3 起可用）：
```
Task tool (subagent_type=traceability-consistency-checker):
  input: {
    requirement_id: "REQ-001",
    features_json_path: "requirements/REQ-001/artifacts/features.json"
  }
```

## 硬约束

- ❌ 禁止在任一环缺失时输出 PASS
- ❌ 禁止放宽规则（"差不多就行"）
- ✅ FAIL 必须列出具体的缺失 feature_id + 缺失位置（设计/代码/测试）
- ✅ Phase 2 阶段如无法深度校验，输出 "static-pass (deep check pending Phase 3 agent)"

## 输出格式

```
结论: PASS | FAIL | static-pass
缺口（FAIL 时）:
  - F-001: 未在代码中出现 @feature:F-001
  - F-003: 未在 test-report.md 中找到测试用例
```
