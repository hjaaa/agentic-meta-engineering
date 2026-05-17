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

## F-001 双侧对称 hotfix（2026-05-17 切 testing 阶段）

**现象**：dev→testing 跑 phase-transition gate，GATE-REVIEW-VERDICT 报 5 个 task.md 全 R005 stale。

**根因（深挖）**：D-001 决议「A2 比对侧 normalize 不动 reviewer」**数学上不自洽**——
- 写入侧 `save_review._compute_artifact_hashes` 用 `sha256(整文件)` 写 hash 到 `meta.yaml.reviews.<phase>.artifact_hashes`
- 比对侧 `check_reviews._compute_hash_with_normalize` 算 `sha256(strip status/updated_at 后)` 比较
- task.md schema 必填 status 和 updated_at → 两侧 hash 永不相等 → R005 在「dev 期 task.md 改 status」场景必假阳性

**F-001 落地时为什么没抓到**：`tests/lib/test_check_reviews_normalize.py::test_evolving_status_yields_same_hash` 只在比对侧自闭环验证「3 个 status 取值 normalize 后同 hash」，**没有跨 save_review→check_reviews 的端到端 round-trip 测试**。单侧实施 + 单侧测试 + 假定对侧默契对齐 = 配对失效。

**修法（D-013）**：
1. 写入侧也走 normalize（task.md 路径）：`save_review._compute_artifact_hashes` 调 `_compute_hash_with_normalize`
2. 比对侧加 raw fallback：`_r005_hash_drift` 在 normalize 不等时再比 `_compute_raw_hash`，兼容历史 completed 需求 raw recorded
3. 一次性 meta.yaml schema migration：REQ-2026-013 detail-design 5 个 task.md hash 替换为 normalize 算法值
4. 加 4 个端到端测试覆盖：写入/比对对称 + dev 期 status 演进不假阳性 + 历史 raw fallback + body 真改仍 stale

**经验抽象（候选 → 写入 context/team/experience/）**：
- **多侧实施的规范要做 round-trip 端到端测试**：单侧测试只能证明本侧自洽，不能证明对侧默契。F-001 / GATE-REVIEW-VERDICT / save_review / detail-design.artifact_hashes 这条链路涉及 ≥ 2 侧，必须有「写一遍读一遍验证字段值能对上」的契约测试。
- **算法对称性**：若两侧分别独立实现「等价」算法，CI 必须包含「同输入两侧出同输出」断言。否则一侧改实现另一侧不知道 → 静默失同步。

**关联**：plan.md D-013；F-001 task.md task.md 字段不刷新但因 status 演进触发 R005 是 F-001 acceptance 的 hidden gap；待 testing V-02 端到端验证收尾。
