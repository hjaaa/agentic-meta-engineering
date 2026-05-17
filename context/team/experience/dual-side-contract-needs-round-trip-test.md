# 跨模块算法对称的契约必须有 round-trip 端到端测试

## 问题

REQ-2026-013 F-001 在 `check_reviews._compute_hash_with_normalize`（R005 比对侧）实现了 task.md frontmatter normalize（strip status/updated_at 再 sha256），单测 `test_evolving_status_yields_same_hash` 验证 3 个 status 取值产出同 hash → 全过 → sign-off → development。dev→testing 切阶段时 R005 5 个 task.md 全 stale —— 因为 `save_review._compute_artifact_hashes` 写入侧仍是整文件 sha256，与比对侧 normalize sha256 永不相等。F-001 单侧实施 + 单侧测试，端到端缺口在 phase-transition 才暴露。

## 根因

两侧分别独立实现"等价"算法时，单侧自闭环测试（"3 种输入 → 同输出"）只能证明本侧实现自洽，**不能证明另一侧也用了等价算法**。AI 实现时若 detail-design 或 ADR 明文说"只改 X 侧"（如 D-001 A2 路径），生产侧 / 消费侧的对称性靠"默契"而非测试 → 一旦对侧仍是旧实现，两侧 hash 算法分叉，契约失效但 CI 不报。

## 解法

跨模块契约（writer-reader / encode-decode / serialize-deserialize / 双侧 hash 比对等）必须有 round-trip 测试：

1. **同函数引用**：消费侧引入生产侧的 helper（如 `from save_review import _compute_hash_with_normalize` 反向也成立），契约用同一函数实例，从根上消灭算法分叉
2. **若无法共用函数**（如跨语言 / 跨进程）：必须有"writer 产出 → reader 消费 → 断言字段值一致"的契约测试（pytest 写 + pytest 读 / Go 写 Python 读）
3. **决策层兜底**：ADR 若说"只改一侧"，必须显式回答"另一侧的等价性如何保证"——靠测试还是靠静态分析，不能留空白

## 验证方法

- 改契约相关函数后，跑 round-trip 测试套件
- PR 审查时 grep `def _compute_` / 两侧算法 helper 命名，检查是否被 cross-import
- CI 加 lint：跨模块 helper 若被两侧独立实现而非共享，要求显式 round-trip test 文件存在

## 关联

- REQ-2026-013 plan.md D-013（F-001 双侧对称修正） / D-001（原 A2 单侧实施）
- `tests/lib/test_check_reviews_normalize.py::test_writer_reader_symmetric` / `test_r005_passes_when_only_status_changes`（D-013 落地的 4 个 round-trip 测试）
- `reviewer-artifact-selection-excludes-evolving-frontmatter.md`（相关 R005 hash drift 经验，但侧重 reviewer 选 artifact 范围而非算法对称性）
