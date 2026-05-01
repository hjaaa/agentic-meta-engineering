# 设计文档落盘后必先 dry-run gate 再调 reviewer

**沉淀原因**：跨需求会重复（每个需求都有"产出物 → reviewer → signoff → next"流程）、AI 反复犯（reviewer Agent 不跑 sourcing，门禁是最后一关）、跨会话需保留。

## 问题

REQ-2026-003 detail-design v2 评审通过 + tty signoff 后跑 `/requirement:next`，GATE-SOURCING 报 4 个 E001/E002——分别是：

- 章节标题 `4 个 [待补充] 之第 2`、`4 个 [待补充] 之第 3` 的元引用被 sourcing parser 误判为 unresolved 标记
- 引用括号 `（来源：scope-schema.md:7-25，本需求不动）`、`（来源：requirement.md:73 上限）` 把"本需求不动"、"上限"塞进路径片段，触发 E002 引用路径不存在

后果：**修文档 → R005 hash drift → 必须重审 + 重 signoff**——多一轮交互（commit `65db506` + `edb33ba` + `fad1ec0`，3 commit 才闭环）。

## 根因

reviewer Agent 评的是"设计内容质量"，不跑 sourcing 校验。GATE-SOURCING 只在 phase-transition 才跑——产出物落盘 → reviewer → signoff → next 这条路径上，sourcing 是最后一关，发现问题时反审已全签完，必须修文档触发 R005。

## 解法

**写完 `artifacts/<阶段>.md` 草稿后，先本地 dry-run 跑一次**：

```bash
python3 scripts/gates/run.py --trigger=phase-transition --to=<下一阶段> --req=<REQ-ID>
```

只看 GATE-SOURCING 段是否 0 error；有 error 立刻修文档（不需要 commit），然后再调 reviewer Agent。这样 reviewer 看到的就是 sourcing-clean 版本，签完直接能 next，省一轮 hash drift 重审。

**适用范围**：requirement.md / tech-feasibility.md / outline-design.md / detailed-design.md 四个产出物文档（features.json / tasks/*.md 不会被 sourcing 扫，不在豁免范围内）。

**避坑细节**：

- 章节标题里出现 `[待补充]` / `[待用户确认]` 元引用时，改成无方括号的等价表述（例 `4 个 outline 待补充项之第 2`），sourcing parser 不会误判
- 来源引用必须是 `（来源：路径）` 或 `（说明；来源：路径）` 格式——把任何文字（如"本需求不动"、"上限"）塞在 `路径` 之后会被 parser 当成路径继续匹配，触发 E002

## 验证方法

- 草稿文档 `python3 scripts/lib/check_sourcing.py <path.md>` 直接跑，看 0 error
- reviewer dispatch 前必经的步骤；纳入产出阶段 SOP

## 引用来源

- `requirements/REQ-2026-003/notes.md:36-67`
- `scripts/lib/check_sourcing.py`（regex `RE_SRC` / `RE_PENDING_*` / `RE_CONSTRAINT`）
- 同系列经验（hash drift 防御）：`context/team/experience/squash-merged-branch-cannot-be-rebased.md`
