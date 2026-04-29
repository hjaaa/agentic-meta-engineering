

## 会话经验（2026-04-27 23:05）

_[hook-skipped: claude-exit-1]_


## 会话经验（2026-04-28 10:22）

_本轮无新经验_


## 会话经验（2026-04-28 10:36）

_本轮无新经验_


## 会话经验（2026-04-28 15:30）— F-003 实现期两次 PreToolUse 锁死的根因与硬规则

### 现象
- **Round 1 H5**：subagent 先 commit「薄壳 hook + registry 引用未完成的 `bash_write_protect.py`（语法错）」→ runner `load_registry` 抛 `SyntaxError` → hook exit 2 → 所有 Edit/Write/Bash 阻断；用户终端 `rm` 坏 plugin + `git restore registry.yaml` 解锁
- **Round 2 F-018**：subagent 先改调用方传 `_validate_one_entry(entry, skip_import=skip_import)` 再去改 `_validate_one_entry` 函数本体签名 → runner `load_registry` 抛 `TypeError: unexpected keyword argument 'skip_import'` → 同样锁死；用户终端 `sed` 改回 `_validate_one_entry(entry)` 解锁

### 根因
F-003 改造的就是 PreToolUse hook 链路本身：

```
Edit/Write/Bash → settings.json PreToolUse Hook
                → .claude/hooks/protect-branch.sh（H5 已薄壳）
                → scripts/gates/triggers/pre_tool_use.sh
                → python3 scripts/gates/run.py --trigger=pre-tool-use
                → load_registry() → 校验全部 plugin 可 import
```

runner 同时是「被改对象」与「看门人」。runner 启动期可见的任何破坏（plugin 语法错 / runner 自身 TypeError / registry 引用不存在 plugin），都立刻让看门人变成阻断者；逃生口（`CLAUDE_GATES_BYPASS` env）藏在 plugin 内部判定，runner 启动失败前根本到不了。

### 硬规则（F-003 round 2+ 与改造 hook 路径代码时强约束）
1. **先改实现，后改调用**：函数签名升级先让本体兼容默认参（`skip_import: bool = False`），import 验证通过再切调用方
2. **每改 plugin 立即 import 验证**：`python3 -c "from scripts.gates.plugins import <name>"` 通过才能改 registry
3. **每改 registry 立即 `make gates-validate`**：S1~S10 全过才能 commit
4. **不在同一 commit 里既加新依赖又把 hook 切到新通道**：「先加新代码不接通 → 验证 → 再切开关」分两 commit；H5 第一次锁死正是违反此条
5. 被锁后**只有用户在终端**能解锁（`git restore` / `sed` / `rm`），主 Agent 与 subagent 自己解不了——因为所有写工具都走 hook

### F-004 应承接的 follow-up（防御补强）
- **shell 层逃生口**：`protect-branch.sh` / `pre_tool_use.sh` 入口判定 `[ -n "$CLAUDE_GATES_HOOK_DISABLED" ] && exit 0`，让用户在 runner 自身坏掉时不依赖 plugin/runner 解锁
- **runner self-test 模式**：`run.py --self-check`，纯 import 不跑 plugin 主体，给 subagent 在 commit 前一个独立 dry-run 闸门
- 否则 H5 把 hook 链路统一通道化的好处会被「自指系统死锁风险」抵消


## 会话经验（2026-04-28 16:04）

_[hook-skipped: claude-exit-1]_


## 会话经验（2026-04-28 20:30）— F-003 round-3 修 spec 触发 R005 stale 的治理缺口

### 现象
F-003 round-3 13 条 must_fix 中 4 条要求改 detailed-design.md（F-001 audit schema 增字段、F-003 RE_WRITE_OPS 同步、F-004 _caller_is_save_review_sh 签名、F-022 GateContext.env 注释）。改完后 check-reviews 跑 R005 hash drift，记录的 sha256 != 当前 sha256 → ERROR + 自动写盘 stale=true。

### 根因
- detail-design 阶段已切到 development，按规范 spec 不该再变；但 review 报告本身要求"修 spec"，矛盾
- R005 不读 stale 状态，每次都比对 hash → 无法靠 stale=true 静音 ERROR
- subagent 不能自行调 save-review.sh 重审 detail-design（reviewer agent 才是正确入口）
- 这导致「round-3 修完 must_fix → check-reviews fail，但 fail 不是 round-3 引入的回归，是规范缺口」

### 处置
1. round-3 commit stale=true 自动写盘结果
2. 把"重审 detail-design 至 round-3 head"登记 F-004 carry-over
3. round-3 reviewer 跑 code-review F-003 后，主 Agent 触发 detail-design 重审（reviewer agent + save-review.sh），更新 reviewed_commit 与 artifact_hashes，降 stale=false

### 防御补强（F-004 候选）
- check-reviews R005 增 `--allow-stale` 或 ctx.cli_flags 旁路：development 阶段允许 stale=true 时降级 ERROR → WARNING（不阻断当前阶段流程）
- 或 reviewer agent 接到「修 spec」类 must_fix 时自动跟 detail-design 重审任务，避免 round-3 留 R005 残留


## 会话经验（2026-04-29 09:35）

_[hook-skipped: claude-exit-1]_


## 会话经验（2026-04-29 10:50）

_本轮无新经验_

- [2026-04-29 15:52:26] [completed] hook 第二次死锁（重构 in-flight）：改 _finalize_audit 签名漏改 call site 引发 TypeError。C-009 v1 加 py_compile pre-check 只抓静态 syntax 错（marker / 不闭合括号），抓不到 runtime 异常（TypeError / AttributeError / KeyError）。两次同源（hook 自指 + fail-closed）但层级不同：第 1 次 parse-time 崩、第 2 次 runtime 才崩。C-012 v2 待修：A) trigger 抓 stderr 含 "Traceback" → fail-open；B) run.py 顶层 try/except → 未捕获异常归 exit 2 与业务 fail (rc=1) 区分；A+B 组合 defense in depth (L1 静态 + L2 runtime + L3 stderr 兜底 + L4 用户终端 escape)。教训：fail-open 不能假设单一检测覆盖所有故障类型，必须分层独立兜底；修过一次的死锁问题给"假安全感"，下次重构同一层时必复发。
