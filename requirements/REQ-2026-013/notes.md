# REQ-2026-013 · 工作笔记

<!-- 非正式记录：问题、临时决策、待确认项、外部资源链接。不需要结构化。 -->


## 会话经验（2026-05-17 18:42）

_本轮无新经验_

## dev 期 reminder（来自 detail-design v1 reviewer minor #3）

⚠️ **F-004 实施时第 1 步就落 `requirements/REQ-2026-013/artifacts/experience-baseline-cjk-stats.txt`**（而非延后到 testing 阶段补 baseline）。

**为什么**：detailed-design.md §3.4.2 + features.json F-004 acceptance「count: 38」+ tasks/F-004.md 实施步骤 2 三处口径在「baseline 何时落档」上有过表述差异——detailed-design 阶段已对 features.json 和 detailed-design.md 计算 hash 锁定（reviews.detail-design.artifact_hashes），如果 testing 阶段才回填 baseline，会同时改动这 3 个文件 → 触发 R005 hash drift → 而 F-001 正是在治理 R005 假阳性，这里再造一个新源头很反讽。

**怎么做**：dev 实施 F-004 时**第 1 步**就跑统计脚本生成 38 文件 CJK 字数分布，把数据 commit 进 baseline.txt；之后再改 INDEX.md。这样 baseline 与 INDEX.md 在同一 commit C-D 内同步落档，与 detail-design hash 完全一致。

## F-004 schema drift ack（2026-05-17 21:04）

**Drift 现象**：detail-design / features.json / task.md acceptance 锁死 `count: 38`，但 F-004 实施时 `ls context/team/experience/*.md`（排 INDEX.md）实数 = **41**。差额 3 个文件来源是 detail-design 时间点（18:58）到 F-004 实施（20:54）之间新增的经验沉淀。

**用户决策（hj19961223@gmail.com，2026-05-17 21:04）= (b) ack drift 保持现状**：

- 三处文档不改：features.json F-004.acceptance / F-004.title / task.md acceptance 字面冻结 `count: 38`
- baseline.txt 已落实数 `count: 41` + 头部 3 行 schema drift 警示注释
- 不触发 detail-design review refresh / 不破坏 reviews.detail-design.artifact_hashes
- 后续读者通过 baseline.txt 头注释即可感知差额

**为什么 (b)**：count 是描述性预估而非验证性卡口（detailed-design §3.4.2 自承"由 testing 阶段 V-04 一次性产出"）；D-009 800 字软上限决策依赖 `max=754 < 800`，与 count 数差解耦；改 38→41 会触发 R005 features.json 整文件 hash drift 连锁返工（F-001 normalize 仅覆盖 task.md），返工成本远超 drift 实际危害。

**关联**：审查报告 `requirements/REQ-2026-013/artifacts/review-20260517-210223.md` F-1 follow-up；`requirements/REQ-2026-013/artifacts/tasks/F-004.receipt.json` concerns[0]。
