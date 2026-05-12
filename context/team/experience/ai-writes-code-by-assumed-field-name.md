# AI 按熟悉字段名写代码，不查 schema

**沉淀原因**：AI 反复错 + 跨项目重复 + 跨会话保留

## 问题

AI 在跨模块开发时容易凭直觉写消费方字段名（如 `prompt` / `workflow_template_path` / `template_id`），与 schema 定义或产出方实际字段名（`message` / `template_path` / `template`）不一致。结果消费方读不到值（返回空串 / `.get` 拿 default），运行时不报错但语义被掏空。codex 第 N 轮 review 才抓到。

## 根因

字段名"想当然"——schema 定义在 workflow_loader / spec yaml 等"非热点"文件，AI 写消费方代码时不主动跨文件 grep 验证。`.get("X", "")` 默认值掩盖 KeyError，错误从硬失败降级为"功能静默缺失"。

## 解法

写消费方读 dict / yaml 字段前**必跨文件验证**：

1. `grep -rn "<字段名>" scripts/lib/<schema-loader>.py` 查 schema 定义
2. `grep -rn '"<字段名>"' .claude/workflows/ requirements/` 查实际产出
3. 名字不一致：以**产出方为事实**对齐消费方（见 [[spec-drift-consumer-aligns-with-producer]]）

代码层守护：消费方读字段优先 schema 名，老字段名作 legacy fallback 串联（`get("new") or get("old")`）；删 fallback 时配 deprecation 周期。

## 验证方法

- `grep -rn "<消费方读法>" scripts/` 与 `grep -rn '"<字段>"' <写入方文件>` 输出字段名一致
- 添加单测断言：消费方对 schema canonical key + legacy key 双案例都能读出值

## 引用来源

- `requirements/REQ-2026-010/artifacts/codex-reviews/round-3.md`（approval prompt vs message）
- `requirements/REQ-2026-010/artifacts/codex-reviews/round-2.md`（workflow_template_path vs template_path）
- `requirements/REQ-2026-010/notes.md`（F-010 / F-011 周期 codex 6 轮抓到 3 处此类）
- 相关：[[spec-drift-consumer-aligns-with-producer]]
