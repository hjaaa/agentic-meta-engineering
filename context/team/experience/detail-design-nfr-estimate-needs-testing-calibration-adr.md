# detail-design NFR 估算与 testing 实测差异必落 ADR 校准

## 问题

REQ-2026-013 detail-design 给 F-001 写 NFR 用例骨架 `assert overhead_ratio < 0.05`（normalize 路径相对整文件 hash overhead < 5%），落地实测 30–50% ——`read_text` + 2 轮 `re.sub` 相对 `open` + binary read 的固有成本，无法压到 5%。同需求 F-002 写「hook p99 < 1ms 增量」相对预算 + 估算 baseline ~50ms，testing 实测 p99 = 162ms ——Python 3.14 冷启动 + git subprocess fork 成本主导。两次踩相同模式：detail-design 给的 NFR 阈值是骨架估算，testing 实测必偏离。

## 根因

detail-design 阶段写 NFR 是凭"模块改造点 + 直觉估算"产出，未实测当前环境（Python 版本 / OS / IO 子系统 / subprocess fork 开销 / 测试运行器 startup）的 baseline。相对预算（"+X%"/"+Y ms"）依赖一个未实测的 baseline 假设；一旦假设错，阈值就误判。若直接修改 features.json `acceptance` 字面（如 < 5% 改 < 200%），会触发 R005 hash drift 连锁返工（features.json 整文件 hash 不在 normalize 范围内）。

## 解法

testing 实测与 detail-design 估算偏离 > 2x 时，落 D-XXX ADR 校准为绝对值阈值：

1. **测试阈值**：用 testing 实测 + ~50–85% 余量护栏（如实测 p99=162ms → 阈值 < 300ms），写绝对值进 pytest/bats 用例 + 注释引用 D-XXX
2. **features.json acceptance 字面保留不动**：避免 R005 hash drift 连锁；ADR 作为该字面条款的"校准解释"
3. **ADR 内容三必填**：Context 摆估算 vs 实测差距 + Decision 给绝对阈值数值 + Consequences 显式承认"文档层形式不一致"+ 缓解（测试注释 + ADR 双向引用）
4. **若可能**：detail-design 阶段对 NFR 类用例加 "实测后校准" 占位段，testing 阶段必填，作为流程提醒

## 验证方法

- testing 阶段对每条 NFR 用例跑实测，记录 p99 / overhead / 延迟数值
- 若实测 / 估算偏离 > 2x（粗筛），打开 plan.md 新增 D-XXX 校准 ADR
- PR 描述检查项：含 NFR 的 feature 是否有 D-XXX 校准 ADR（无偏离也可显式注明"实测 ≈ 估算，不需校准"）
- 跨需求观察：未来含 NFR 用例的 REQ 是否复用此模式（实测 + 校准 ADR + features.json 不动），不再因 features.json 写错 NFR 阈值触发 R005

## 关联

- REQ-2026-013 plan.md D-012（F-001 < 5% → < 200% 校准） / D-014（F-002 +1ms → < 300ms 绝对值校准）
- `perf-baseline-sample-size-jitter-trap.md`（性能 baseline 采样 N 次方法论；本经验侧重"估算 vs 实测偏离的校准 ADR 流程"）
- `r005-hash-drift-deadlock-after-reviewer-signoff.md`（说明为什么不直接改 features.json）
