---
id: REQ-2026-006
title: 门禁系统 A+B 重构实施 · 技术可行性评估
created_at: 2026-05-04T00:30:00+08:00
refs-requirement: true
refs-tech-feasibility: true
---

# REQ-2026-006 · 技术可行性评估

## 评估范围

本文评估 REQ-2026-006「门禁系统 A+B 重构实施」的实施可行性，覆盖：

- 依赖工具链在 macOS Darwin 25.4（开发机）和 Linux ubuntu-latest（GitHub Actions CI）的可用性
- Claude Code PreToolUse hook 协议稳定性
- 核心技术风险（正则误报、trap 边界、异步 audit flush、bypass 入口一致性、PR 顺序约束）
- 4 个独立 PR 的工作量拆分

**可行性结论：high**。无 blocker 级阻碍。最大技术风险是 bash 写检测正则对 12 种 pattern 的边界覆盖（见「风险 1」），可通过完整 bats 测试套件覆盖；次要风险是异步 audit 依赖 SessionEnd hook 的 flush 假设——当前 settings.json 中 SessionEnd hook 已存在但绑定的是 `extract-experience.sh`，spec 设想的 `audit_flush_queue` 调用尚无 hook 入口（见「风险 3」）。

---

## 依赖可行性

### bash / jq / git

**macOS（Darwin 25.4，开发机）**

macOS 系统自带 bash 版本为 3.2（GPLv2 限制导致苹果不升级），Homebrew 安装的 bash 5.x 通常位于 `/opt/homebrew/bin/bash` 或 `/usr/local/bin/bash`。`pre-tool-use-guard.sh` 使用 `#!/bin/bash` shebang，在 macOS 上这解析到系统 bash 3.2——存在兼容性疑问，但 spec 骨架用到的语法（`[[ ]]` 双方括号、`case`、`local`、`set -u`、`trap ... ERR`）在 bash 3.2+ 全部支持，无 bash 4+ 专属构造（如 `declare -A` 关联数组、`mapfile`）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:157）。[待用户确认：CI 与开发机的 bash 解析路径，是否需要切到 `#!/usr/bin/env bash` 来用 PATH 中第一个 bash？]

`jq` 在 macOS 不预装，需 `brew install jq`；GitHub Actions `ubuntu-latest` 镜像预装 jq（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:153）。`git` 在两平台均预装，无风险。

**bats 测试框架**

`bats-core` 在 macOS 通过 `brew install bats-core`、Linux 通过 `apt-get install bats` 或 `npm install -g bats` 安装（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:367）。[待用户确认：`.github/workflows/` 下现有 CI 是否已含 bats 安装 step，或本次需新增 quality-check.yml 条目？]

### jq 缺失时的回退路径

spec §4.1 注释提到「jq 不可用时回退到 `python3 -c "import json,sys;..."`」（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:153）。但 spec §4.1 骨架代码直接用 `jq -r '.tool_name // empty'`，没有写显式 fallback；若 jq 不在 PATH，`jq` 命令失败 → `trap 'exit 0' ERR` 兜底 → fail-open（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:160）。

**结论**：jq 缺失的真实处理路径是 fail-open（而非 python3 fallback），这是可接受的安全降级，但与 spec §4.1 注释的表述不完全一致。detail-design 阶段需在「实现 python3 fallback」（每次调用多一个分支，+2ms）与「接受 jq 缺失即 fail-open」之间做出选择，并相应更新 spec 注释。

---

## Hook 协议稳定性

### PreToolUse stdin JSON 字段

从现有实现可推断 hook 协议：`scripts/gates/triggers/pre_tool_use.sh` 的解析逻辑显示 stdin JSON 含以下字段（来源：.claude/hooks/pre-tool-use-guard.sh:64）：

```json
{
  "tool_name": "Edit|Write|MultiEdit|Bash",
  "tool_input": {
    "file_path": "...",   // Edit/Write/MultiEdit 专属
    "command": "..."      // Bash 专属
  }
}
```

`pre_tool_use.sh:41` 同时尝试读取 `inp.get('path')` 作为 `file_path` 的备用字段，说明协议历史上曾有字段名变动，但当前主用 `file_path`（来源：.claude/hooks/pre-tool-use-guard.sh:65）。

REQ-2026-005 的 tech-feasibility 已通过 WebSearch 确认 matcher 语法为管道分隔工具名、大小写敏感、无歧义风险（来源：requirements/REQ-2026-005/artifacts/tech-feasibility.md:83）。

### exit code 语义

当前 `pre_tool_use.sh` 退出码协议：`exit 0 = 放行；exit 2 = 阻断；其他 = non-blocking 警告`（来源：.claude/hooks/pre-tool-use-guard.sh:4）。`context/team/engineering-spec/design-guidance/hook-fail-open.md` 规范确认了相同矩阵（来源：context/team/engineering-spec/design-guidance/hook-fail-open.md:6），与 spec §4.1 一致（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:151）。

### 自身错误重定向

spec 要求 `exec 2>>/tmp/guard-error.log` 把 guard 自身错误隔离到本地文件，避免污染 hook 协议 stderr（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:161）。该设计正确——hook 协议把 stderr 当作"阻断理由"传给 Agent，guard.sh 自身的内部错误不应让 Agent 看到。

**结论**：hook 协议来自已运行多个 REQ 周期的现有实现，字段结构和 exit code 语义稳定，本次重构不引入任何协议侧改动，风险低。

---

## 技术风险与缓解

### 风险 1：bash 写检测正则误报/漏报（中风险）

spec 附录 A 列出 12 种写入模式（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:438）。spec §4.1 给出的 `pattern` 草案（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:224）与现有 `bash_write_protect.py` 中的 `_ALTS` 正则（来源：.claude/hooks/pre-tool-use-guard.sh:13）相比，存在覆盖差异：

**已知边界用例分析**

1. 引号内路径：`echo x > 'requirements/x/reviews/y.json'`——草案用 `[^|;&]*` 通配，引号内能匹配，覆盖。
2. 多空格：`mv  tmp   requirements/x/reviews/y.json`——`[[:space:]]+` 可匹配多空格，覆盖。
3. 转义符：`mv tmp requirements\/x\/reviews\/y.json`——`\/` 在 ERE 下匹配 `/`，覆盖。
4. **printf 重定向**：`printf '%s' "$x" > requirements/x/reviews/y.json`——现有 `bash_write_protect.py:72` 中有专门 pattern 处理 printf（来源：.claude/hooks/pre-tool-use-guard.sh:27）；spec §4.1 草案的 `pattern` 变量仅列出 3 段（>>/tee/sponge/dd/rsync/install/mv/cp、python3、heredoc），未显式覆盖 printf。**这是漏报风险**。
5. heredoc redirect 含 `<<-`：`cat <<-EOF > file`——草案的 `<<.*>` 通配 `<<-` 形式，覆盖。

**缓解**：guard.sh 实现时必须从 `scripts/gates/plugins/bash_write_protect.py:58` 完整抄录全部 `_ALTS`，不依赖 spec §4.1 草案概要；bats 用例对附录 A 全部 12 种 pattern 各加正向用例（应阻断）+ 至少 2 个反例（如 `cat requirements/x/reviews/y.json` 不应阻断）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:455）。

### 风险 2：`trap 'exit 0' ERR` 在 `set -u` 下的边界行为（低风险）

spec 明确选择 `set -u`（不含 `-e`）配合 `trap 'exit 0' ERR`（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:159）。`ERR` trap 触发条件（bash 手册）：命令返回非零 exit code 时，若未被 `if`/`while`/`&&`/`||` 消费，则触发 ERR trap。已知边界：

- `grep -q`：无匹配返回 1。在 `if echo "$cmd" | grep -qE "$pattern"; then ... fi` 中被 `if` 消费，**不触发** ERR，正确。
- `git rev-parse --abbrev-ref HEAD`：不在 git 仓库时返回 128。spec 骨架用 `b=$(... 2>/dev/null) || return 0` 消费，**不触发** ERR，正确（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:193）。
- `jq` 缺失：赋值语句的退出码等于命令退出码，未被消费 → **触发 ERR → exit 0 fail-open**。这是预期行为。

**缓解**：bats 用例增加"jq 不在 PATH"场景，验证 fail-open（V-01 已要求，来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:379）。

### 风险 3：异步 audit "SessionEnd flush" 假设不成立（中风险）

spec §4.2 设计了 `audit_flush_queue()` 函数，并在 §6.2 提到「SessionEnd 后被 flush 成 audit/<YYYY-MM>/*.json」（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:387）。

**现状核查**：`.claude/settings.json` 已有 SessionEnd hook，绑定 `.claude/hooks/extract-experience.sh`，matcher 为 `prompt_input_exit|logout|other`（来源：.claude/settings.json:33）。spec 没有指定调用 `audit_flush_queue` 的 SessionEnd 条目——意味着异步 audit 的 flush 当前没有触发入口。

**影响**：`audit/.queue/*.log` 会持续累积，永远不被整理成 JSON，审计退化为「只写不读」。但根据 D-005：审计是 best-effort，当前 audit 无下游强依赖完整性（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:431）。短期可接受，但需在 PR-4 决定：新增 SessionEnd hook 条目调用 `audit_flush_queue`，或明确放弃 flush（仅保持 append-only log）。

**缓解**：V-04 验收（`audit/.queue` 权限改 555 → 写盘失败被 swallow → 决策正常）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:395）可验证决策不被阻断；flush 完整性问题在 PR-4 detail-design 阶段决议。

### 风险 4：4 条 trigger sh 脚本 bypass 入口一致性（低风险）

spec 要求 bypass 检查加到 `scripts/gates/triggers/*.sh`（除已删的 pre_tool_use.sh）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:129）。

**关键观察**：若 trigger 脚本不加 bypass 检查直接调用 `run.py`，`run.py` 顶部的 bypass 检查（spec §4.3 改动 1）会处理并返回 exit 0，trigger 拿到 0 后正常传递。trigger 层 bypass 检查是**冗余防御**，非必须。

**缓解**：detail-design 阶段统一方案——trigger 层 bypass 仅写 audit 行（标识入口），决策实际委托给 `run.py`，避免双重判断的不一致风险（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:99）。

### 风险 5：删除文件时 settings.json 引用残留（低概率/高影响）

PR-2 删除 `protect-branch.sh` / `pre_tool_use.sh` / 两个 plugin 时，若 PR-1（settings.json 切换到新 guard）尚未合入或被 revert，旧文件删除后 settings.json 仍引用 `.claude/hooks/protect-branch.sh` → hook 命令不存在 → Claude Code 框架行为不受控（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:353）。

**缓解**：严格执行 spec §5 顺序约束（PR-1 验证 1-2 天后合 PR-2）；PR-2 的 CI 检查中增加 settings.json 引用文件存在性校验（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:353）。

### 风险 6：run.py main() 兜底不拦 SystemExit（低风险）

spec §4.3 改动 2 的 `try/except BaseException` 代码（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:302）已正确保留 `except SystemExit: raise`，不拦截 argparse 的正常 exit。run.py 的退出码逻辑（来源：.claude/hooks/pre-tool-use-guard.sh:4）依赖 `sys.exit(1)` 业务 fail 与 `sys.exit(2)` runner 异常；BaseException 捕获后统一 `sys.exit(2)` 符合 hook-fail-open 规范（来源：context/team/engineering-spec/design-guidance/hook-fail-open.md:6）。

---

## 工作量估算

类比参照：REQ-2026-005 的 FG-002（matcher 单行修改）估算 0.4 人天，FG-001（3-4 处 plugin 修改 + 测试）估算 2.2 人天（来源：requirements/REQ-2026-005/artifacts/tech-feasibility.md:427）。本需求改动规模介于两者之间：~60 行 bash + ~80 行 bats + run.py 3 处小改 + settings.json 1 行 + registry.yaml 删 2 条 gate + 删 4 个文件。

### PR-1：新增 guard.sh + bats + settings.json 切换

| 子任务 | 代码量 | dev | test | 验证窗口 |
|---|---|---|---|---|
| `pre-tool-use-guard.sh`（含 12 种 pattern 正则） | ~60 行 | 0.5 | - | - |
| bats 测试套件（≥10 用例覆盖 V-01） | ~80 行 | - | 0.5 | - |
| `scripts/lib/audit_async.sh` | ~30 行 | 0.3 | 0.1 | - |
| settings.json 切换 1 行 | 1 行 | 0.1 | - | - |
| sandbox 30 分钟 + bats 全绿 | - | - | 0.2 | 24h+100 次调用 |
| **小计** | ~170 行 | **0.9** | **0.8** | |

### PR-2：删除 4 个旧文件 + registry 调整

| 子任务 | 代码量 | dev | test |
|---|---|---|---|
| 删 `protect-branch.sh` / `pre_tool_use.sh` / `protect_branch.py` / `bash_write_protect.py` | -450 行 | 0.1 | - |
| `registry.yaml` 删 2 条 gate + 移除 `pre-tool-use` 枚举值 | -20 行 | 0.2 | 0.1 |
| CI 全绿 + sandbox 完整 REQ 周期（V-02） | - | - | 0.3 |
| **小计** | | **0.3** | **0.4** |

### PR-3：CLAUDE_GATES_GLOBAL_BYPASS 三处入口

| 子任务 | 代码量 | dev | test |
|---|---|---|---|
| guard.sh bypass 分支（已含于 PR-1） | 已含 | - | - |
| `run.py` 顶部 bypass（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:284） | ~15 行 | 0.2 | 0.2 |
| triggers/*.sh 顶部 bypass（2-3 处） | ~10 行/处 | 0.2 | 0.2 |
| audit 写入验证（V-05） | - | - | 0.1 |
| **小计** | ~35 行 | **0.4** | **0.5** |

### PR-4：异步 audit + run.py 最外层兜底

| 子任务 | 代码量 | dev | test |
|---|---|---|---|
| `run.py` 改动 2（main BaseException 兜底） | ~15 行 | 0.2 | 0.2 |
| `run.py` 改动 3（write_audit → audit_append_async） | ~10 行 | 0.3 | 0.2 |
| `scripts/lib/audit_flush.py`（flush queue → JSON） | ~40 行 | 0.3 | 0.2 |
| SessionEnd flush 入口策略确认 | - | 0.1 | 0.1 |
| 故障注入 V-03 / V-04 / V-07 | - | - | 0.3 |
| **小计** | ~65 行 | **0.9** | **1.0** |

### 总计

| | design | dev | test | 合计 |
|---|---|---|---|---|
| PR-1 | 0.3 | 0.9 | 0.8 | 2.0 |
| PR-2 | 0.1 | 0.3 | 0.4 | 0.8 |
| PR-3 | 0.1 | 0.4 | 0.5 | 1.0 |
| PR-4 | 0.2 | 0.9 | 1.0 | 2.1 |
| **合计** | **0.7** | **2.5** | **2.7** | **5.9** |

PR-1 验证窗口 1-2 天按挂钟计；PR-3/PR-4 可并行；实际挂钟约 4 天。

---

## 结论与建议

**可行性：high**

所有改动基于项目现有技术栈（bash / jq / python3 / bats），不引入新外部依赖。

**前置条件（detail-design 阶段必须解决）**

1. **macOS bash 解析路径确认**：`#!/bin/bash` shebang 在 CI 与开发机上是否解析到同一版本（系统 3.2 vs Homebrew 5.x）；如需统一行为，改 shebang 为 `#!/usr/bin/env bash`（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:153）。
2. **正则完整抄录**：guard.sh 实现必须从 `scripts/gates/plugins/bash_write_protect.py:58` 抄录 12 条 `_ALTS`，不从 spec §4.1 草案推导（printf pattern 在草案中缺失）（来源：.claude/hooks/pre-tool-use-guard.sh:13）。
3. **SessionEnd flush 策略明确**：PR-4 实施前确定——新增 SessionEnd hook 条目调用 `audit_flush_queue` 或接受 audit 为 append-only log（来源：.claude/settings.json:33）。
4. **bats CI 安装步骤**：检查 `.github/workflows/` 下现有 quality-check.yml 是否需新增 bats-core 安装 step（详见「待澄清清单」#2）。
5. **jq 回退语义统一**：detail-design 阶段在「实现 python3 fallback」与「接受 jq 缺失即 fail-open」之间二选一，并同步更新 spec 注释（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:160）。

**无 blocker 级阻碍**——本评估建议进入概要设计阶段。

---

## 待澄清清单

1. **macOS/CI bash 解析路径** [待用户确认]：`#!/bin/bash` 在两环境是否解析到同一版本？是否需要改为 `#!/usr/bin/env bash`？建议在 detail-design 阶段确认。

2. **bats CI 安装步骤** [待用户确认]：现有 `.github/workflows/` 下是否已含 bats-core 安装；若未含，PR-1 是否打包新增安装 step？建议在 detail-design 阶段确认。
