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
