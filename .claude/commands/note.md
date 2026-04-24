---
description: 追加笔记到当前需求的 notes.md
argument-hint: <内容>
---

## 用途

开发过程中随手记录发现、坑、想法。是日常最高频的命令，直接 append 不触发任何 Skill。

**不要用 /note 记 blocker**：阻塞是当前需求的时间线状态，应由主 Agent 委托 `requirement-progress-logger` 写入 `process.txt` 的 `[blocker]` 事件，不走 notes.md。详见 `../skills/managing-requirement-lifecycle/reference/blocker-conventions.md`。

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
   - [YYYY-MM-DD HH:MM:SS] [<phase>] <内容>
   ```
   时间戳取 Asia/Shanghai 当下（`TZ=Asia/Shanghai date +"%Y-%m-%d %H:%M:%S"`，详见 `context/team/engineering-spec/time-format.md`）
4. 输出简短确认（< 50 字）：`已追加到 requirements/<id>/notes.md`
5. **不 commit**—— notes.md 会在 `/requirement:save` 或合适节点由开发者统一提交

## 硬约束

- 单次内容 < 500 字符
- 不 commit
- 格式固定：`- [YYYY-MM-DD HH:MM:SS] [phase] <内容>`（Asia/Shanghai 时区）
