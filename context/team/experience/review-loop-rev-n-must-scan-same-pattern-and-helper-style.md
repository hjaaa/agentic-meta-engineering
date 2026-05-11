# review-loop rev N 修复派发必含「全文搜同模式 + 同 helper 风格不一致」硬规则

**沉淀原因**：跨需求会重复（A）+ AI 反复错（B）+ 跨会话需保留（C）

## 问题

REQ-2026-009 F-011 / F-012 review-loop 出现 trend-G-meta 反模式——**rev N 修一波 finding 又新引入一波 finding**：

```
F-012 score 演化:
rev1=71 (36 候选 finding)
rev2=78 (修 5 件 → 30 新候选，base 硬编码 / 双向 import / commit 范围 4 项 keep+major 复发)
rev3=78 (修 4 件 → 25 新候选，trend-G-meta 三轮未终结)
rev4=86 (governance gate 落地 → 35 新候选，trend-G-meta 自我误判)
rev5=84 (修 1 真 major → 23 新候选，元信息层 4 candidate major 复发)
rev6=88 (双层终结 → 真闭环)
```

每轮修复 subagent 严格 scope 守住"只修指定 finding"，但 finding 周边的同模式 / 同 helper 风格不一致会反复被 reviewer 抓出来——这不是"reviewer 找茬"，是 dispatch prompt 给的 scope 太窄。

## 根因

review reviewer 看的是"全文一致性 + 风格一致性"，subagent 修的是"指定行 + 指定 finding"。两边视野错位，导致：

- 修了 A 文件 line 56 的 `OSError` 异常处理 → reviewer 在下一轮抓"B 文件 line 100 同模式 OSError 未处理"
- 修了 helper-A 加了某种 fix → reviewer 抓"helper-B 同 helper 类型未应用同 fix"
- 修了 docstring 一处 → reviewer 抓"另两处 docstring 同 pattern 漂移"

D-014 ADR 把它定义为反模式："修一波又新引入一波"。

## 解法

review-loop rev N 修复 subagent dispatch prompt **必须包含**两条硬规则：

```
D-014 硬规则：
1. **同模式全文搜**：keep finding 修复后必须 grep 同 pattern（如 `except yaml.YAMLError`
   全文找 / `OSError` 写盘错处 / `f-string without placeholder` 全仓扫）
2. **同 helper 风格扫**：相同语义的 helper 函数（如 `_commit_signoff` 模板 / `_append_*`
   helper 模板）必须风格一致；任何风格漂移视同 finding 一并修复
```

**禁止规则**：
- 禁止"严格 scope 只修指定 finding"理由偷 follow-up（同语义类别区分允许，跨语义类别保留 follow-up）
- 禁止重构 / 禁止扩 scope（这两条与"同模式全文搜"不矛盾——前者是行为重组，后者是 1:1 fix 复制到其他位置）

## 验证方法

跑 review rev N 后看 trend-G-meta 是否终结：

- ✅ 终结指标：净自引入 candidate finding ≤ 1（且非 major）/ 修复批次 ≤30 行 / 全 keep+minor follow-up
- ❌ 未终结指标：净自引入 candidate ≥ 4 同语义类别 / 反复同类型 finding（如 ADR 数字漂移 / 注释不齐 / commit message 范围）

如未终结，**先在 plan.md 加 ADR 解释 trend-G-meta 模式 + 双层终结路径**（详见 `trend-g-meta-double-layer-termination.md`），再启 rev N+1。

## 引用来源

- `requirements/REQ-2026-009/plan.md:164` — D-014 ADR
- `requirements/REQ-2026-009/process.txt` — F-012 rev1~6 演化记录（11 轮 review-loop 演化曲线）
- `requirements/REQ-2026-009/artifacts/review-20260510-154609.md` — F-011 rev3 trend-G-meta 终结判定
