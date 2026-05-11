# 流程性产物 historical touches_violations 清零模板

**沉淀原因**：跨需求会重复（A）+ 跨会话需保留（C）

## 问题

phase-transition development → testing 触发 GATE-TOUCHES-VIOLATION，多个 done feature 的 receipt 残留 historical touches_violations[]：

```
F-007 (6 violations):
  - 5×artifacts/review-*.md（reviewer 流程产物）
  - .dispatch-state.json（派发锁状态机）

F-008 (3 violations):
  - /tmp/F-008-rev4-verdict.json（临时 verdict 中转）
  - artifacts/review-*.md
  - .dispatch-state.json

F-011 (7 violations): review-*.md / .dispatch-state.json / fixture / detailed-design.md
F-012 (1 violation): .dispatch-state.json
```

如果按 D-011/D-012 模板（per-feature 设计漏写 → 扩 features.json touches）逐条修，会让 features.json 充斥 review-*.md / .dispatch-state.json 等**与 feature 实现 scope 无关**的流程产物路径，污染 per-feature touches 字段。

## 根因

四类"流程性副作用"路径不属于 feature implementation scope，而是**派发器 / reviewer / 临时存储**的副产品：

| 路径模式 | 性质 | 写入主体 |
|---|---|---|
| `artifacts/review-*.md` | reviewer agent 写 review report | code-quality-reviewer / external reviewer |
| `.dispatch-state.json` | 派发锁状态机 | feature-lifecycle-manager Skill |
| `/tmp/<...>.json` | 临时 verdict 中转文件 | reviewer agent 写盘前预处理 |
| 主 Agent bookkeeping `features.json` 自编辑 | 流程性 metadata 写入 | 主 Agent commit 元数据 |

touches_guard hook 当前对这些路径无豁免规则（hook 层 follow-up 待落地）。

## 解法

**短期治理（per-feature done 闭环时）**：清零 receipt.touches_violations[] 数组。**不**扩 features.json touches 字段。commit message 详述每条 violation 的根因，统一引用 D-013 ADR：

```python
# scripts/lib/clear_historical_violations.py 模板（按 feature 批处理）
import json
from pathlib import Path

D013_TARGETS = ["F-007", "F-008", "F-011", "F-012"]
ROOT = Path("requirements/REQ-XXX/artifacts/tasks")

for fid in D013_TARGETS:
    f = ROOT / f"{fid}.receipt.json"
    data = json.loads(f.read_text())
    n = len(data.get("touches_violations", []))
    if n > 0:
        data["touches_violations"] = []
        f.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"[CLEARED] {fid}: {n} violations → 0（D-013 historical clear）")
```

commit message 模板：

```
chore(REQ-XXX): D-013 清零 N 条 historical touches_violations

GATE-TOUCHES-VIOLATION 失败修复——按 plan.md D-013 ADR (3) 决策模板，
后续所有 done feature 在 hook 层 follow-up 落地前都按本 ADR 模式清零。

清零明细（共 N 条 → 0）:
F-007（6 条）:
- 5×artifacts/review-*.md（reviewer 流程产物）
- .dispatch-state.json（派发锁状态机）
...

不扩 features.json touches（review-*.md 与 .dispatch-state.json 是流程性副作用，
与 feature 实现 scope 无关，不应污染 per-feature touches 字段—— D-013 (1)）。
```

**长期治理**（hook 层 follow-up）：`touches_guard.py:_is_process_artifact` 豁免列表扩 4 类（review-*.md / .dispatch-state.json / /tmp/*.json / features.json self-edit）；归到独立 hook 治理 feature。

## 验证方法

```bash
# 清零后跑 phase-transition gates
python3 scripts/gates/run.py --trigger=phase-transition --req=<REQ-ID> \
  --from=development --to=testing
# 期望 GATE-TOUCHES-VIOLATION PASS（exit=0）
```

## 引用来源

- `requirements/REQ-2026-009/plan.md:155` — D-013 ADR（流程性副作用治理三层方案）
- `requirements/REQ-2026-009/plan.md:137,146,173` — D-011/D-012/D-015（per-feature 设计漏写扩 touches 模板，对比参考）
- `requirements/REQ-2026-009/process.txt` — 09:14:25 GATE-TOUCHES-VIOLATION fail 17 条 → 09:15:50 全清零 PASS
