---
name: traceability-gate-checker
description: 测试阶段切换前的追溯链门禁——校验需求→设计→代码→测试链完整。调用 traceability-consistency-checker Agent 做深度语义校验。
---

## 什么时候用

由 `managing-requirement-lifecycle` 在切换到 `testing` 阶段之前自动调用。

## 核心流程

由 `managing-requirement-lifecycle` 在切换到 `testing` 阶段之前自动调用。

1. **准备输入**：读 `features.json` 列出所有 feature_id
2. **调用 `traceability-consistency-checker` Agent**（`check_depth=semantic`）做深度校验：
   - 需求 → 设计（feature_id 出现在 detailed-design.md）
   - 设计 → 代码（grep `@feature:<id>` / commit 消息 / 代码注释）
   - 代码 → 测试（test-report.md 每 feature 有测试用例）
   - 接口签名一致性
   - 测试覆盖分支一致性
3. **根据 Agent 返回的 conclusion**：
   - `PASS` → 允许进入测试阶段
   - `FAIL` → 阻止切换，列出 `checks` 中各环节的具体缺口

调用方式：
```
Task tool (subagent_type=traceability-consistency-checker):
  input: {
    requirement_id: "REQ-001",
    features_json_path: "requirements/REQ-001/artifacts/features.json",
    check_depth: "semantic"
  }
```

## 硬约束

- ❌ 禁止在任一环缺失时输出 PASS
- ❌ 禁止放宽规则（"差不多就行"）
- ✅ FAIL 必须列出具体的缺失 feature_id + 缺失位置（设计/代码/测试）

## 输出格式

```
结论: PASS | FAIL
缺口（FAIL 时）:
  - F-001: 未在代码中出现 @feature:F-001
  - F-003: 未在 test-report.md 中找到测试用例
```
