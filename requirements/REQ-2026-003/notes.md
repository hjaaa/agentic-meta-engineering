# REQ-2026-003 笔记

<!-- 随手记录，不限格式。会议纪要、临时思路、待确认问题均可写在此处。 -->

## 2026-04-30 工程债：canonical phase 枚举 fail-closed

排查 phase-transition 时发现 meta.yaml.phase 被前一次会话写成了非 canonical 名
'technical-research'（应为 'tech-research'），并且门禁链上有 3 层 vacuous pass：
R001 / ReviewVerdictGate / runner 入口都没拦下 typo。已在 commit `a25bfcd`
修复（phase_enum.py 单一事实源 + 三层 fail-closed + 11 个回归测试）。

## 2026-04-30 教训：Edit 顺序错导致 hook 自锁

我在 run.py 里先加了 `_validate_phase_args(args)` 的调用，然后才打算加函数定义；
但中间任何 Edit / Write / Bash 都会触发 PreToolUse hook → hook 跑 run.py →
NameError → rc=1 → hook 拦死全部后续工具。py_compile 只检语法不检 NameError，
fail-open 路径不生效。最终需要用户手动 `! sed -i '' '428,434d' scripts/gates/run.py`
删掉坏调用才解锁。

**规矩**：以后改 hook 链上的关键文件（scripts/gates/run.py / scripts/lib/
check_reviews.py 等），**先加函数定义、再加调用**；或先在 try/except 包住调用，
等定义到位再去掉 try。


## 会话经验（2026-04-30 11:52）

本轮 transcript 仅包含 `/clear` 和 `/exit` 两条本地命令，无实际对话内容。

_本轮无新经验_


## 会话经验（2026-04-30 17:29）

_[hook-skipped: claude-exit-143]_

## 2026-04-30 教训：设计文档落盘后必须先 dry-run gate 再调 reviewer

**现象**：detail-design v2 评审通过 + tty signoff 后跑 `/requirement:next`，GATE-SOURCING
报 4 个 E001/E002——分别是：
- 章节标题 `4 个 [待补充] 之第 2`、`4 个 [待补充] 之第 3` 的元引用被 sourcing
  parser 误判为 unresolved 标记
- 引用括号 `（来源：scope-schema.md:7-25，本需求不动）`、`（来源：requirement.md:73 上限）`
  把"本需求不动"、"上限"塞进了路径片段，触发 E002 引用路径不存在

**根因**：reviewer Agent 评的是设计内容质量，不跑 sourcing 校验；GATE-SOURCING 只在
phase-transition 才跑——产出物落盘 → reviewer → signoff → next 这条路径上，sourcing
是最后一关，发现问题时反审已经全签完了，必须修文档 → 触发 R005 hash drift → 再走一遍
reviewer + signoff，多一轮交互。

**规矩**：以后写完 `artifacts/<阶段>.md` 草稿后，**先本地 dry-run 跑一次**：

```bash
python3 scripts/gates/run.py --trigger=phase-transition --to=<下一阶段> --req=<REQ-ID>
```

只看 GATE-SOURCING 段是否 0 error；有 error 立刻修文档（不需要 commit），然后再调
reviewer Agent。这样 reviewer 看到的就是 sourcing-clean 版本，签完直接能 next，省一轮
hash drift 重审。

**适用范围**：requirement.md / tech-feasibility.md / outline-design.md / detailed-design.md
四个产出物文档；features.json / tasks/*.md 不会被 sourcing 扫（不在 artifacts 顶层 .md 列表）。

**避坑细节**：
- 章节标题里出现 `[待补充]` / `[待用户确认]` 元引用时，改成无方括号的等价表述
  （例 `4 个 outline 待补充项之第 2`），sourcing parser 不会误判
- 来源引用必须是 `（来源：路径）` 或 `（说明；来源：路径）` 格式——把任何文字（如"本需求不动"、
  "上限"）塞在 `路径` 之后会被 parser 当成路径继续匹配，触发 E002


## 会话经验（2026-04-30 22:03）

transcript 仅包含 SessionStart hook、`/clear` 和 `/exit` 三条事件，没有任何用户与 AI 的实际工作交互。

_本轮无新经验_
