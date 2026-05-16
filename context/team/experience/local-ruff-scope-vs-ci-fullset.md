# 本地 ruff 改动文件 scope vs CI 全仓 --select=F 漂移

**沉淀原因**：跨需求会重复（A）+ AI 反复错（B）+ 跨会话需保留（C）

> 与 [`local-pass-vs-ci-pass-rounds.md`](local-pass-vs-ci-pass-rounds.md) 互补——前者覆盖
> 多种环境差异，本条专注 ruff scope 这一具体陷阱。

## 问题

REQ-2026-009 F-012 / F-013 receipt 写"ruff All passed"，PR submit 后 CI quality-check
立即 fail：

```
quality-check fail 1m29s
  ruff lint:
    F541 [×5] f-string without any placeholders
    F401 [×1] `common.WorkflowError` imported but unused
  Found 6 errors.
```

本地 `ruff check scripts/lib/workflow_loader.py ...`（subagent 自检命令）输出 `All
checks passed!`；CI 跑 `ruff check scripts/ --select=F` surface 出 6 个**历史遗留**
错误（与本次 PR 改动无关，是其他 commit 累积的）。

## 根因

subagent 自检 ruff 命令的两种 scope 漂移：

| 命令 | scope | 何时漏检 |
|---|---|---|
| `ruff check <single-file.py>` | 单文件 | 历史遗留错误在其他文件时 |
| `ruff check scripts/lib/<a>.py scripts/lib/<b>.py`（subagent 改动文件枚举） | 改动文件集 | 历史遗留错误在未改动文件时 |
| `ruff check . --select=F`（全仓 + F 规则） | 全仓 + pyflakes | ✅ CI 实际跑的命令 |

**典型陷阱**：subagent 严格 scope 守住"只修指定 finding"，自检也"只跑改动文件"——历史遗留错误就这样在多次 PR 之间累积，直到某次 CI 在某个 lucky commit 上 surface 出来。

## 解法

subagent 自检 ruff 必须**对齐 CI 命令**：

```bash
# CI 实际跑的命令（以本仓库 .github/workflows/quality-check.yml 为准）
python3 -m ruff check scripts/ --select=F

# 不要这样：
# python3 -m ruff check scripts/lib/<改动文件>.py  ← scope 太窄
# python3 -m ruff check .                          ← scope 太宽（surface 非 F 规则噪音）
```

主 Agent 在 `subagent prompt` 中把 CI ruff 命令显式写入"自检 checklist"段，不让
subagent 自由选择 scope。

**对应 dispatch prompt 模板**：

```
## 自检 checklist

```bash
python3 -m ruff check scripts/ --select=F     # 与 CI quality-check 对齐
python3 -m pytest -q --tb=no                  # 与基线对比
```
```

## 验证方法

```bash
# 在 push 前模拟 CI 跑一遍
python3 -m ruff check scripts/ --select=F     # 期望 All checks passed!
python3 -m pytest -q --tb=no                  # 期望 N passed M skipped 0 failed
git push                                       # 推上去看 CI 是否 PASS
```

如本地 CI 命令 PASS 但 CI 仍 fail，看 `.github/workflows/<...>.yml` 是否还有别的
lint/check 步骤（mypy / black / 其他自定义脚本），把全部步骤都纳入本地自检。

## 引用来源

- `requirements/REQ-2026-009/process.txt` — 10:02 CI fail / 10:08 修 6 项 ruff / 10:10 push
- `.github/workflows/quality-check.yml:82` — `ruff check scripts/ --select=F` 唯一事实源
- `local-pass-vs-ci-pass-rounds.md` — 5 种本地 vs CI 漂移类型的总论

## 复发案例 · 2026-05-16（REQ-2026-011）

PR #72 submit 后 CI quality-check 第一次跑挂同模式 4 个 F-class：

```
F401 path_lock.py:33 unused import `sys`（F-008 引入就死，development 期一直没人本地跑 select=F）
F401 workflow_continue.py:33 unused import `_next_node`（F-014 修 P2 时把 router 改走 _select_next_dispatch_target，re-export 变 dead）
F541 workflow_scheduler.py:373-374 两个 f-string 无占位符（pre-existing）
```

链路与 REQ-2026-009 完全一致：development 期所有 commit 都没本地跑 `ruff check scripts/ --select=F`（hook 只跑改动文件的 lint，scope ≠ CI），submit 后才暴露 4 个累积。本案再次验证此条经验**仍然有效**，修复成本固定（1 commit + 1 push 即清掉）。

防御建议：把 `ruff check scripts/ --select=F` 加进 pre-submit hook 或 `/requirement:submit` 的 GATE-RUFF-STRICT 候选 gate。

