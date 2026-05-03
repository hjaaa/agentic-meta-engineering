---
id: REQ-2026-006
title: 门禁系统 A+B 重构实施（pre-tool-use 热路径解耦 + 全局逃生 + 异步 audit）
created_at: 2026-05-03T22:30:00+08:00
refs-requirement: true   # 供 traceability-gate-checker 识别
---

# REQ-2026-006 · 门禁系统 A+B 重构实施（pre-tool-use 热路径解耦 + 全局逃生 + 异步 audit）

## 背景

本仓库的门禁系统当前在每次 Edit/Write/Bash/MultiEdit 调用时都触发一条长链路 hook：`settings.json → protect-branch.sh → pre_tool_use.sh → run.py（1045 行 god-object） → registry.yaml → importlib 加载 plugin → 写 audit 文件`（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:25）。但实际只跑 2 条规则：分支保护 + reviews/*.json 写保护（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:38）。

这套架构有 5 项已识别缺陷：

1. **fail-open 不完整**：`pre_tool_use.sh` 用 `py_compile` 拦语法错误，但运行时异常（NameError/ImportError/KeyError）通过编译却在执行时炸 → rc=2 → 全部工具锁死。已发生真实事故（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:44）。
2. **自举死锁**：门禁判断逻辑和被它保护的代码在同一仓库；改门禁本身的代码，半成品保存即锁死，连撤销编辑都做不了；当前没有全局逃生通道（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:47）。
3. **god-object 在热路径**：2 条规则不需要 1045 行框架；复杂度正比于出 bug 概率（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:50）。
4. **多层壳脚本叠加**：每多一层失败点 + 调试栈追溯困难（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:53）。
5. **audit 与决策共享失败域**：每次 Edit/Write/Bash 同步写盘；磁盘满 / 权限丢 → 阻断全部工具（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:56）。

spec 已审定 A+B 联合方案（hard-block + 解耦），并显式排除 C（软警告）/ B2（共享 plugin 函数）/ B3（run.py 内部分叉）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:61）。本需求的任务是**实施这个已决议的 spec**，分 4 个独立可回滚 PR 落地。

## 目标

- **主目标**：消除"运行时异常 → 工具锁死"故障模式，把热路径压缩到一个 ~60 行 bash 文件；引入 `CLAUDE_GATES_GLOBAL_BYPASS` 全局逃生通道；audit 与决策解耦失败域（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:71）。
- **次要目标**：保留 reviews/*.json hard-block 不软化，保留 deny list 不动；保留低频 trigger（phase-transition / pr-submit / save-review / manual）的 12 条 gate 能力（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:86）。

## 用户场景

### 场景 1：正常 hard-block（分支保护）
- 角色：主 Agent（Claude）
- 前置：当前 git 分支为 `develop` / `main` / `master`，CLAUDE_GATES_GLOBAL_BYPASS 未设置
- 主流程：Agent 调用 Edit/Write/MultiEdit 工具 → PreToolUse hook 触发 `pre-tool-use-guard.sh` → 检测到分支为保护分支
- 期望结果：exit 2，stderr 输出"BLOCKED: 当前在 '<branch>' 分支，禁止直接 Edit/Write/MultiEdit"+ 规避方式提示（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:191）

### 场景 2：reviews/*.json 写保护（含 Bash 写）
- 角色：Reviewer Agent / 主 Agent
- 前置：尝试写 `requirements/<REQ-ID>/reviews/<rev-id>.json`，无论通过 Edit 还是 Bash 重定向
- 主流程：guard.sh 解析 `tool_input.file_path`（Edit/Write/MultiEdit）或 `tool_input.command`（Bash 12 种写入 pattern：`>` / `>>` / `tee` / `tee -a` / `sponge` / `dd of=` / `mv` / `cp` / `rsync` / `install` / `python -c open()` / heredoc redirect）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:438）
- 期望结果：exit 2，stderr 提示"必须走 scripts/save-review.sh 或人类 sign-off CLI"（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:213）

### 场景 3：全局逃生通道（A1）
- 角色：开发者（修改门禁代码本身、或抢救锁死现场）
- 前置：环境变量 `CLAUDE_GATES_GLOBAL_BYPASS=<非空 reason>` 已设
- 主流程：guard.sh 顶部检查 bypass → 写 audit 行 `BYPASS used: <reason> @ <ts> @ <cwd>` → exit 0；同样的检查也加到 `run.py` 顶部和 `triggers/*.sh`（除已删除的 pre_tool_use）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:99）
- 期望结果：所有 gate 跳过；audit 强制留痕，事后 PR review 可审

### 场景 4：fail-open 自救
- 角色：guard.sh 自身 / `run.py`
- 前置：guard.sh 内部异常（stdin 非合法 JSON / git 不在 PATH / jq 不可用 / 未捕获 ERR），或 `run.py` 抛 NameError/KeyError/ImportError 等任何 BaseException
- 主流程：
  - guard.sh 通过 `trap 'exit 0' ERR` 兜底 → 自身错误写 `/tmp/guard-error.log`（不进 stderr，避免污染 hook 协议）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:160）
  - run.py 在 `main()` 最外层 `try/except BaseException` 捕获 → 写 `/tmp/run-py-error.log` → `sys.exit(2)` → trigger 层映射为 fail-open（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:302）
- 期望结果：exit 0（hook 链）/ 决策不锁死（trigger 链），错误可后审

## 非功能需求

- **性能**：热路径单次 hook 开销 < 5ms（当前 ~12-30ms，来自 Python 启动 + 2 plugin 加载）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:472）
- **兼容性**：低频 trigger（phase-transition / pr-submit / save-review / manual）的 12 条 gate 能力**不变**；`.claude/settings.json` 的 deny list（`rm -rf` / `git reset --hard` / `git push --force`）**不动**，保持框架级保护（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:107）
- **安全/合规**：
  - reviews/*.json hard-block 不可降级为软警告（保护 sign-off tty 校验深度防御层）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:62）
  - `CLAUDE_GATES_GLOBAL_BYPASS` 必须携带非空 reason 字符串；audit 强制记录每次使用（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:432）
  - guard.sh 自身错误日志不写 stderr（避免被 hook 协议当成"阻断理由"传给 Agent）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:253）

## 验收标准

| ID | 验收点 | 来源 |
|---|---|---|
| V-01 | bats 单测套件 ≥10 用例全绿，覆盖 7 类场景：分支保护命中/未命中、reviews 路径 Edit/Bash、BYPASS、stdin 非 JSON、不在 git 仓库、tool_name 缺失、git 不在 PATH | gate-system-architecture.md:368 |
| V-02 | sandbox `REQ-2099-001` 跑完整需求生命周期，4 个低频 trigger 仍正确触发剩余 12 条 gate | gate-system-architecture.md:384 |
| V-03 | 注入 `raise NameError` 到 run.py 顶部 → rc=2 → trigger 层 fail-open，工具不锁死 | gate-system-architecture.md:394 |
| V-04 | `audit/.queue` 目录权限改 555 → audit 写盘失败被 swallow → 决策正常返回 | gate-system-architecture.md:395 |
| V-05 | `CLAUDE_GATES_GLOBAL_BYPASS="x"` 设置后所有 gate 跳过；audit 队列内有 BYPASS 行 | gate-system-architecture.md:396 |
| V-06 | 热路径单次 hook 开销 < 5ms 〔测量方法待用户确认〕 [待用户确认] | gate-system-architecture.md:472 |
| V-07 | 锁死复现率 = 0%（注入运行时异常到任意 plugin → fail-open 兜住） | gate-system-architecture.md:475 |
| V-08 | 热路径文件数 = 1（仅 `pre-tool-use-guard.sh`），代码量 ~60 行 | gate-system-architecture.md:476 |

## 范围

- 包含：
  - 新增 `.claude/hooks/pre-tool-use-guard.sh`（~60 行 bash，热路径唯一实现）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:118）
  - 新增 `scripts/lib/audit_async.sh`（异步 audit 工具函数）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:119）
  - 新增 `tests/hooks/test_pre_tool_use_guard.bats`（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:120）
  - 修改 `.claude/settings.json` 把 PreToolUse hook 命令指向新 guard（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:126）
  - 修改 `scripts/gates/run.py`：顶部加 `CLAUDE_GATES_GLOBAL_BYPASS` 检查 + audit 改异步 + main() 最外层 `try/except BaseException`（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:127）
  - 修改 `scripts/gates/registry.yaml`：删除 `GATE-PROTECT-BRANCH` / `GATE-BASH-WRITE-PROTECT`，移除 `pre-tool-use` trigger 枚举值（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:128）
  - 修改 `scripts/gates/triggers/*.sh`（除 pre_tool_use 已删）顶部加 bypass 检查（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:129）
  - 删除 `.claude/hooks/protect-branch.sh` / `scripts/gates/triggers/pre_tool_use.sh` / `scripts/gates/plugins/protect_branch.py` / `scripts/gates/plugins/bash_write_protect.py`（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:135）
- 不包含：
  - C 方案（软警告语义）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:414）
  - 抽公共 plugin 接口（B1 核心就是不要框架）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:415）
  - hook 热更新 / 重载机制（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:416）
  - audit 可视化 / dashboard（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:417）
  - 把规则做成可配置 YAML（硬编码 + 单测覆盖比 YAML 更可靠）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:418）
  - `CLAUDE_GATES_GLOBAL_BYPASS` 的白名单 / 角色 / TTL（信任人类操作员 + audit 事后审）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:419）

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| D-001 整体方案 | A+B / A+C / B 单独 / C 单独 | **A+B**（hard-block + 解耦） | 用户痛点是"频繁锁死"，根因是热路径与 god-object 耦合，只有彻底解耦才能根治（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:427） |
| D-002 是否软化 reviews 写保护 | 走 C 方案改提示 / 保持 hard-block | **保持 hard-block** | reviews/*.json 软化代价太大，破坏 sign-off 安全模型（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:428） |
| D-003 guard.sh 实现语言 | bash / Python | **bash** | bash 足够覆盖 3 条规则；启动快 5x；无 importlib 故障面（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:429） |
| D-004 BYPASS 是否带 reason | `=1` 即可 / 必须带 reason | **必须带 reason** | 增加心理负担防滥用 + audit 可读性高（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:430） |
| D-005 audit 同步还是异步 | 同步写盘失败即阻断 / 异步 best-effort | **异步 best-effort** | 决策正确性 > 审计完整性；当前 audit 无下游强依赖（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:431） |
| D-006 trigger 枚举是否保留 `pre-tool-use` | 保留 deprecated / 删除 | **删除** | 避免后人误以为还可以注册；要恢复直接 git revert（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:432） |
| D-007 PR 拆分顺序 | 一把梭 / 4 个独立 PR | **4 个独立可回滚 PR**，PR-1 先合，PR-2 在 PR-1 验证 1-2 天后合 〔"1-2 天"度量方式待用户确认〕 [待用户确认]，PR-3/PR-4 可并行 | 每一步可回滚，新旧并行窗口里旧脚本不再被 settings 引用即等同失活（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:351） |

## 待澄清清单

1. **V-06 热路径开销 < 5ms 的测量方法**（对应正文「验收标准」V-06 行）：spec 附录 C 仅给目标值，未约定测量方式。候选：bats 用例里 `time` 命令取均值 / 真实工作流 30 分钟采样 / hyperfine 微基准。建议在 detail-design 阶段定下并写入测试用例。

2. **PR-1 验证 1-2 天的"度量方式"**（对应正文 D-007 决策行）：spec §5 要求 PR-1 合后"1-2 天"再合 PR-2，但未说明是按自然时间还是按真实工具调用次数。建议改为**双重条件**：自然时间 ≥ 24h **且** 工具调用次数 ≥ 100 次无 fail-open 误触发，detail-design 阶段确认。
