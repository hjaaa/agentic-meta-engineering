# 本地通过 vs CI 通过的多轮往返陷阱

**沉淀原因**：跨需求会重复（A）+ AI 反复错（B）+ 跨会话需保留（C）

## 问题

REQ-2026-006 PR #54 本地全部测试 + 门禁全过，submit 后 5 轮 CI 修复才绿：

| 轮 | 失败 | 根因 |
|---|---|---|
| 1 | GATE-SOURCING E002 ×10 | F-002 删历史代码触发档案需求引用 stale（CI 全量扫，本地单需求模式没扫） |
| 2 | bats 30 用例 abort | CI runner 无 git global `user.email/user.name`（本地全局已配） |
| 3 | bats 2 用例 fail | CI runner `git init` 默认 `master`（本地是 `main`） |
| 4 | ruff F401 unused import | 本地 ruff 没装 / 没跑 |
| 5 | gate-checklist.md 与 registry 不同步 | render-docs.py 是 CI 检查项，本地 commit 时没强制重渲染 |

5 轮 = 5 次 push + 5 次 CI ~40s + 5 次断点切换。修复都是 1 行级别但 round-trip 累计 ~30 分钟。

## 根因

**本地与 CI 环境差异**永远存在但常被低估：
- 全局 git config（user / defaultBranch）
- 工具版本与默认值（git 老版默认 master）
- lint/format 工具可选安装
- "auto-render 同步检查"类 CI 步骤本地无对应触发
- CI strict 模式（`--strict`）放大 warning 为 error
- CI 工作目录与权限（`/tmp` vs `~/...`）

AI 实现时按自己环境写测试，假设"我能跑就所有人能跑"。

## 解法

**Submit 前必跑本地 CI 模拟清单**：

```bash
# 1. CI strict 模式跑全套门禁
python3 scripts/gates/run.py --trigger=ci --strict

# 2. 全量 lint
ruff check scripts/

# 3. 全量测试（含 bats / pytest / 各 venv 隔离套件）
python3 -m pytest tests/ -q
bats tests/hooks/*.bats

# 4. auto-render 类同步检查
python3 scripts/gates/migration/render-docs.py --check
# 任何 --check 模式工具：跑一遍

# 5. 模拟 CI 环境（关键）
git -C /tmp/test-clone clone . && cd /tmp/test-clone
unset GIT_*  # 清掉本地 env 影响
git config --unset-all user.email 2>/dev/null
# 在干净 clone 上跑测试
```

**测试 fixture 必须自给自足**：
- bats setup 显式 `git config user.email / user.name local`，不依赖全局
- bats setup `git -c init.defaultBranch=main init`，不依赖系统默认
- pytest `tmp_path` 隔离，不依赖固定路径
- 测试 import 不依赖未声明的可选包

**新增 CI 检查项时**同步在 `engineering-spec/onboarding-cicd.md` 列出本地等价命令。

## 验证方法

submit 前依次跑上面 5 步本地 CI 模拟，全过才 push。submit 后被 CI 卡的事件率应降到 < 1 次/PR。

## 引用来源

- `requirements/REQ-2026-006/process.txt`（PR #54 5 轮 CI 修复）
- 修复 commits：`2d93a2f` / `b1aaed2` / `2f09b15` / `49e0bde` / `686d2d2`
- `tests/hooks/test_pre_tool_use_guard.bats`（setup 新增 user / defaultBranch fixture）
