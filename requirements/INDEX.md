# 需求索引

本目录承载全部需求的全生命周期产出物。入 git，是团队资产。

## 当前无活跃需求

用 `/requirement:new` 创建你的第一个需求。

## 目录结构（每个需求一个子目录）

```
requirements/REQ-YYYY-NNN/
├── meta.yaml         # 元信息：阶段、分支、服务、门禁历史
├── plan.md           # 阶段级计划
├── process.txt       # 进度日志（Hook 自动追加）
├── notes.md          # 随手笔记
└── artifacts/
    ├── requirement.md          # 需求文档（阶段 2）
    ├── tech-feasibility.md     # 技术预研（阶段 3）
    ├── outline-design.md       # 概要设计（阶段 4）
    ├── detailed-design.md      # 详细设计（阶段 5）
    ├── features.json           # 功能点清单
    ├── tasks/<feature-id>.md   # 任务拆分（阶段 6）
    ├── review-YYYYMMDD-HHMMSS.md   # 代码审查报告（阶段 7）
    └── test-report.md          # 测试报告（阶段 8）
```
