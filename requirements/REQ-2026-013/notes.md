# REQ-2026-013 · 工作笔记

<!-- 非正式记录：问题、临时决策、待确认项、外部资源链接。不需要结构化。 -->


## 会话经验（2026-05-17 18:42）

_本轮无新经验_

## dev 期 reminder（来自 detail-design v1 reviewer minor #3）

⚠️ **F-004 实施时第 1 步就落 `requirements/REQ-2026-013/artifacts/experience-baseline-cjk-stats.txt`**（而非延后到 testing 阶段补 baseline）。

**为什么**：detailed-design.md §3.4.2 + features.json F-004 acceptance「count: 38」+ tasks/F-004.md 实施步骤 2 三处口径在「baseline 何时落档」上有过表述差异——detailed-design 阶段已对 features.json 和 detailed-design.md 计算 hash 锁定（reviews.detail-design.artifact_hashes），如果 testing 阶段才回填 baseline，会同时改动这 3 个文件 → 触发 R005 hash drift → 而 F-001 正是在治理 R005 假阳性，这里再造一个新源头很反讽。

**怎么做**：dev 实施 F-004 时**第 1 步**就跑统计脚本生成 38 文件 CJK 字数分布，把数据 commit 进 baseline.txt；之后再改 INDEX.md。这样 baseline 与 INDEX.md 在同一 commit C-D 内同步落档，与 detail-design hash 完全一致。
