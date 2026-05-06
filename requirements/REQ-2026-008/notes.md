

## 会话经验（2026-05-05 22:31）

_本轮无新经验_


## 会话经验（2026-05-05 22:45）

_本轮无新经验_


## 会话经验（2026-05-05 23:45）

_[hook-skipped: claude-exit-143]_


## 会话经验（2026-05-06 09:00）· tech-research 待澄清条目实证

- **关键发现**：`feature-task.md.tmpl` frontmatter 缺 `touches` 字段（仅在正文 §"触及范围"段有占位）。detail-design F-005 / F-007 必须把 `touches: __TOUCHES__` 加进 frontmatter，否则 `touches_guard.py` 无法机器化读取——这是隐藏的设计前提，不补就 V-03 直接 fail。
- **正面信号**：`pytest tests/ --ignore=tests/benchmarks/` 603 passed / 8 skipped / 36s，CI 扩展覆盖零修复成本，F-006 可直接合入本次 PR。
- **reviewer 体系启示（D-006 衍生）**：reviewer hash 校验无 trivial 豁免通道——任何 artifact 措辞修订都计入"重审"成本（hash drift → R005 硬 fail，stale=true 不豁免）。未来类似情况直接走重审，不再尝试"标 stale 跳过"。
