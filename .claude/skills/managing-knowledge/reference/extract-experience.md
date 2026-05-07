# 从 notes.md 提取经验

## 输入

- `requirements/<id>/notes.md`（或指定 notes 文件）

## 步骤

1. **扫描 notes.md**，找出"踩坑/教训/发现"类条目
2. **对每条候选**，按三必要条件评估：
   - 跨需求会重复出现？
   - AI 反复犯此类错？
   - 跨会话/跨人需要保留？
3. **至少满足一条**才进入候选清单
4. **输出候选清单**给用户：
   ```
   候选经验（N 条）：
   1. <标题> [满足条件：A/B/C] — 简要描述
   2. ...
   ```
5. **用户确认要沉淀哪几条**
6. **对每条，决定归属**：
   - 项目特有 → `context/project/<X>/experience/<slug>.md`
   - 跨项目 → `context/team/experience/<slug>.md`
7. **写文件**（格式见下）
8. **更新对应 INDEX.md**
9. **收尾标记沉淀完成**（强制；本步骤不可跳过）：

   ```bash
   python3 scripts/lib/mark_lessons_extracted.py <REQ-ID>
   ```

   该脚本把对应需求的 `meta.yaml.lessons_extracted` 翻为 `True`（幂等；已是 True
   则跳过）。**这是 archive 预检 5 (`R-ARCHIVE-LESSONS-NOT-EXTRACTED`) 通过的唯一
   合法路径**——禁止 AI Edit / Write 工具或人工编辑 meta.yaml 来翻这个字段，
   archive_runner 不会做内容来源校验，但用户和团队的工程纪律靠这条规范守住。

   即使第 1~7 步发现"无新经验"（输出"_本轮无新经验_"），第 8 步更新 INDEX 不
   适用，第 9 步**仍需执行**——用户确认"已检视过这次的 notes.md，确实没有可
   沉淀经验"也是一种沉淀结论，meta.lessons_extracted 应当翻为 True 以解锁 archive。

## 文件格式

```markdown
# <标题>

**沉淀原因**：满足 A / B / C（至少一条）

## 问题

（场景描述，< 100 字）

## 根因

（< 100 字）

## 解法

（具体操作或规范，< 100 字）

## 验证方法

（如何确认问题不再出现）

## 引用来源

- `requirements/<id>/notes.md:<行号>`
```

## 反例（不应沉淀）

- 偶发问题（只发生过一次且无再现风险）
- 纯常识
- 只与当前需求相关、无复用价值
