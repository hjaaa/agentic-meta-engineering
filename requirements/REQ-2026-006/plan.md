# REQ-2026-006 · 门禁系统 A+B 重构实施（pre-tool-use 热路径解耦 + 全局逃生 + 异步 audit）

## 目标

把每次 Edit/Write/Bash 调用的 hook 链路从 1875 行 god-object 路径压缩到 ~60 行 bash 单文件，
彻底消除"运行时异常 → 工具锁死"故障模式，同时引入全局逃生通道
`CLAUDE_GATES_GLOBAL_BYPASS` 与异步 audit，让审计与决策解耦失败域。

> 来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md
> （commit 51adade，已合入 develop）

## 范围

- 包含：
  - 新增 `.claude/hooks/pre-tool-use-guard.sh`（~60 行 bash，热路径唯一实现）
  - 新增 `scripts/lib/audit_async.sh`（异步 audit 工具函数）
  - 新增 `tests/hooks/test_pre_tool_use_guard.bats`（~10 个用例覆盖 7 类场景）
  - 修改 `.claude/settings.json` hook 矩阵，指向新 guard
  - 修改 `scripts/gates/run.py`：顶部 `CLAUDE_GATES_GLOBAL_BYPASS` 检查 + audit 改异步 + main() 最外层兜底
  - 修改 `scripts/gates/registry.yaml`：删除 `GATE-PROTECT-BRANCH` / `GATE-BASH-WRITE-PROTECT`，移除 `pre-tool-use` trigger 枚举值
  - 修改 `scripts/gates/triggers/*.sh`（除 pre_tool_use 已删）：顶部加 bypass 检查
  - 删除 `.claude/hooks/protect-branch.sh` / `scripts/gates/triggers/pre_tool_use.sh` / 两个 plugin
- 不包含：
  - C 方案（软警告语义）
  - plugin 框架抽象 / hook 热更新 / audit 可视化
  - `CLAUDE_GATES_GLOBAL_BYPASS` 的白名单 / 角色 / TTL 控制
  - `.claude/settings.json` 的 deny list（`rm -rf` 等）调整
  - 把规则做成可配置 YAML

## 里程碑

| 阶段 | 预期完成 |
|---|---|
| definition | 2026-05-04 |
| tech-research | 2026-05-04 |
| outline-design | 2026-05-05 |
| detail-design | 2026-05-06 |
| task-planning | 2026-05-06 |
| development | 2026-05-09（4 个独立可回滚 PR） |
| testing | 2026-05-10 |

## 风险

- bash 写检测正则漏掉某些写法 → reviewer Agent 能绕过 sign-off 安全模型；从老 plugin 完整抄录 12 种 pattern，bats 每种一例
- fail-open 太宽，protect-branch 误漏放行 → develop 上偶发污染；fail-open 时写 `/tmp/guard-error.log`，CI 卡门禁兜底
- `CLAUDE_GATES_GLOBAL_BYPASS` 被滥用 → 安全模型软化；强制 reason + audit 强制记录 + PR review 检查
- jq 不在 PATH → guard 启动报错；回退 python3 -c，最终 trap 兜底 fail-open
- 异步 audit 丢失记录 → 审计完整性下降；接受——决策正确性优先于审计完整

## PR 拆分（4 个独立可回滚）

| PR | 内容 | 验证 | 回滚 |
|---|---|---|---|
| PR-1 | 新增 pre-tool-use-guard.sh + bats + 切 settings.json | sandbox 7 类场景 + 临时分支 30 分钟实跑 | 改回 settings.json 一行 |
| PR-2 | 删除旧 protect-branch.sh / pre_tool_use.sh / 2 个 plugin / registry 两条 gate | CI 全绿 + sandbox 完整 REQ 周期 | git revert |
| PR-3 | A1: `CLAUDE_GATES_GLOBAL_BYPASS`（3 处入口） | 单测 + audit 落盘 | git revert |
| PR-4 | A2 + A3: 异步 audit + run.py 兜底 | 注入异常验 fail-open | git revert |

顺序约束：PR-1 先合（旧脚本失活）→ PR-2 在 PR-1 验证 1-2 天后合 → PR-3 / PR-4 顺序无关可并行。

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 选 B1（彻底解耦）而非 B2/B3
- **Context**：用户痛点是"频繁锁死"，根因是热路径与 god-object 耦合
- **Decision**：B1（pre-tool-use 完全离开通用 runner，bash 单文件实现）；B2（共享 plugin 判断函数）/ B3（run.py 内部分叉）排除
- **Consequences**：好——只有彻底解耦才能根治锁死；坏——bash 与 Python 各维护一套写检测正则（10 行重复换零依赖）
- **时间**：2026-05-03 22:10:26
- **Supersedes**：（无）
- **来源**：spec §1.2 + §9 D-001
