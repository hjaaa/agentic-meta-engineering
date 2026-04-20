---
description: 追加笔记到当前需求的 notes.md
argument-hint: <内容>
---

## 用途

开发过程中随手记录发现、坑、想法。是日常最高频的命令，直接 append 不触发任何 Skill。

## 预检

1. 当前分支对应 `requirements/*/meta.yaml` 存在（需要 notes.md 归属）
2. 参数 `<内容>` 非空
3. `<内容>` 长度 < 500 字符（超了引导用户分多次 `/note`）

## 行为

不委托 Skill。直接执行：

1. 反查 `requirements/*/meta.yaml` 找到 branch 匹配的需求
2. 读 `meta.yaml.phase`
3. 追加到 `requirements/<id>/notes.md` 末尾：
   ```
   - [<ISO8601>] [<phase>] <内容>
   ```
4. 输出简短确认（< 50 字）：`已追加到 requirements/<id>/notes.md`
5. **不 commit**—— notes.md 会在 `/requirement:save` 或合适节点由开发者统一提交

## 硬约束

- 单次内容 < 500 字符
- 不 commit
- 格式固定：`- [ISO8601] [phase] <内容>`
