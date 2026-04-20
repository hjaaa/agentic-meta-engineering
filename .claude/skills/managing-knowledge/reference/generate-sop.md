# 生成 SOP

## 输入

- 用户指定的"目标场景"（如"线上紧急修复流程"、"新 MCP 接入流程"）
- `requirements/*/notes.md` 或 `context/team/experience/` 中的相关实践

## 步骤

1. **收集相关实践**：grep 涉及场景的 notes/experience
2. **识别通用步骤**：出现 ≥ 2 次的操作
3. **识别变化点**：各实践中不同的部分 → 决策点
4. **起草 SOP 结构**：
   ```
   # <场景名> SOP

   ## 触发条件
   ## 前置检查
   ## 主流程
   步骤 1 → 步骤 2 → ... → 步骤 N
   ## 决策点
   ## 完成标准
   ```
5. **先输出结构+几个关键步骤**给用户确认
6. **用户确认后**，写入 `context/team/engineering-spec/sop/<slug>.md`（或 `context/team/experience/`，视适用范围）
7. **更新对应 INDEX.md**

## 硬约束

- SOP 必须包含"完成标准"（可验证的结束条件）
- 步骤必须是可执行的祈使句
- 禁止写成"应该考虑 X"之类的模糊建议
