---
name: requirement-session-restorer
description: 跨会话恢复上下文。读 meta.yaml + process.txt + notes.md + plan.md，输出 < 200 字的"恢复摘要"，等用户确认后继续工作。
---

## 什么时候用

用户触发 `/requirement:continue` 或口头说"继续之前的需求"时。

## 核心流程

1. **定位需求**：
   - 如果用户指定了需求 ID，用它
   - 否则扫 `requirements/*/meta.yaml`，找当前分支匹配的（`git branch --show-current`）
   - 都找不到 → 请用户指定

2. **读取四个文件**（**按顺序**）：
   - `meta.yaml` → 知道阶段（同时读 `log_layout` 字段决定下一步读取策略）
   - `process.txt` 末尾 50 行 → **语义事件**（阶段切换 / 评审 / 门禁 / 决策 / 坑 / SESSION_END）
     - `log_layout=split` 时 process.txt 只含语义，50 行信号密度接近 100%
     - `log_layout=legacy` 或缺字段时 process.txt 里混杂工具日志，按"过滤 `tool=` 开头的行"取语义
   - `notes.md` → 已发现的坑/待澄清
   - `plan.md` → 当前计划
   - （可选）`process.tool.log` 末尾 20 行 → 工具活动密度（仅 v2；判断"最近是否活跃"，不进入摘要正文）

3. **输出恢复摘要**（< 200 字）：
   ```
   你在 [需求 ID] 的【[阶段中文名]】阶段，
   上次做到 [最近一个关键动作]，
   卡在 [notes.md 最后一条未解决项]（见 notes.md 第 N 行）。
   ```

4. **等用户确认**：
   - "继续" → 按当前阶段的标准流程推进
   - "先看 X 文件" → 打开 X 文件展示给用户

## 硬约束

- ❌ 禁止不读 process.txt 就直接推进（会漏掉关键上下文）
- ❌ 禁止把 4 个文件全部粘到主对话（会污染上下文）
- ✅ 摘要严格 < 200 字
- ✅ 必须等用户确认才开始新动作
