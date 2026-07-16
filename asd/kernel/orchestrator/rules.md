# ASD Orchestrator 规则

> 阶段 1:注入可行性验证最小集。仅含可观察的位置与标记规则,验证通过后再扩充五个注入点。

以下规则是本项目的用户偏好,优先于 Superpowers 插件 skill 中的默认约定:

1. 设计文档(spec)写入 `asd/specs/YYYY-MM-DD-<topic>-design.md`,不写 `docs/superpowers/specs/`。
2. 实现计划(plan)写入 `asd/plans/YYYY-MM-DD-<feature>.md`,不写 `docs/superpowers/plans/`。
3. 每份 spec 与 plan 的标题下第一行必须是:`> ASD-INJECTION: active`
   (注入通道有效性标记,阶段 1 冒烟专用,验证通过后移除本条)。
