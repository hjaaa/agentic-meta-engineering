# 性能 baseline 样本量陷阱：5 次中位数会被 50ms 抖动放大

**沉淀原因**：跨需求重复（凡涉及性能 baseline / 退化阈值的需求都会撞）、AI 反复错（直接照搬"5 次中位数"模板）、跨会话保留（性能验证方法学需要固化）。

## 问题

REQ-2026-005 F-003 详细设计原文 TC-FG3-3 写「5 次中位数」抓门禁 runner baseline，要求 +20% 内通过。F-003 实施后第一次跑：

- baseline median 0.21s
- after median 0.26s
- 涨幅 **+23.8%** → 触发降级方案（保留 plugin 内 changed_files 副本）

实际原因：runner 单次执行只 ~210ms，5 次样本里只要有 1 次被磁盘 IO / GC 抖动 +50ms 就够把中位数推到 +24%。把样本量扩到 11 次 perf_counter 后稳定到 **+4.88%**，远低于阈值，根本不需要降级。

差点为了量化误判去搞一套并不需要的代码兜底。

## 根因

性能 baseline 的"样本量 vs 噪声幅度"关系是隐藏前提。模板写「5 次中位数」时通常默认单次耗时是秒级，那时 5 次足够稳定。但当被测项 < 1s（如 ms 级单元测试 / 短脚本）时，环境抖动（磁盘 cache miss / Python GC / OS scheduling）相对噪声占比急剧上升，5 次中位数对单次极端值过于敏感。

详设 / 验收标准定"N 次中位数 + ±X%"时没问"被测项时长量级"。

## 解法

**性能 baseline 三步评估**：

1. **先量被测时长量级**：跑 1 次粗测，记 t_single。
2. **再定样本量 N**：
   - t_single > 5s → N = 3-5 即可
   - 1s < t_single < 5s → N = 5-10
   - t_single < 1s（ms 级）→ **N ≥ 10**，且用 `time.perf_counter` 而非 `time` shell 命令（后者粒度差）
3. **同时报 stdev**：median + stdev 一起看，stdev / median > 5% 时再加样本量；只看 median 会被异常值带偏
4. **物理隔离**：必要时关闭其他后台进程 / 在 idle 时段跑 / 用 worktree 隔离 IO

详细设计 / 验收标准里"N 次中位数 + ±X%"模板必须先用 t_single 调档。

## 验证方法

- F-003 案例：`scripts/gates/run.py` baseline 重测，N=5 → +23.8%（拒绝），N=11 → +4.88%（通过）
- 同样命令 N=11 重跑 5 轮，median 偏差应 < 1%（说明样本量足够）

## 引用来源

- `requirements/REQ-2026-005/notes.md:69`（baseline 测量方法 + 11 次 perf_counter 修订）
- `requirements/REQ-2026-005/artifacts/detailed-design.md` §8 TC-FG3-3（原"5 次中位数"模板）
- 推论：所有详设 / acceptance 写"N 次"的位置应主动核对样本量
