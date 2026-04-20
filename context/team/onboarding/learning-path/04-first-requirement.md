# Stage 4 · 跑完一个完整的 8 阶段小需求

**完成时间**：1-2 人天
**前置**：Phase 2/3 骨架完成（即 Command / Skill / Agent 已建）
**可验证动作**：成功合入 1 个 feature/req-xxx 分支到 main

## 练习需求（任选其一）

1. 给本仓库加一个 `/status-summary` 命令，输出仓库文件数/行数统计
2. 给 `.claude/statusline.sh` 加一个显示当前 Token 用量的段（如果 Claude Code 环境变量暴露了）
3. 在 `context/team/` 下加一份"如何挑选 Claude 模型档位"的规范

## 步骤

1. 运行 `/requirement:new`，填需求元信息
2. 跟随 8 阶段推进：
   - 阶段 1 初始化 → 自动
   - 阶段 2 需求定义 → 用 `requirement-doc-writer` 写需求文档
   - 阶段 3 技术预研 → 评估可行性
   - 阶段 4 概要设计 → 模块划分
   - 阶段 5 详细设计 → 接口签名
   - 阶段 6 任务规划 → 拆分功能点
   - 阶段 7 开发实施 → 编码 + `/code-review`
   - 阶段 8 测试验收 → 写测试 + 追溯链校验
3. 全部通过后合入

## 关键检查点

- [ ] 每次阶段切换都有门禁输出
- [ ] 每个阶段的 `artifacts/*.md` 都有"来源标注"
- [ ] `process.txt` 记录了全部关键动作
- [ ] 最终代码审查报告为 `approved`

## 完成标志

成功合入一个 feature 分支。
