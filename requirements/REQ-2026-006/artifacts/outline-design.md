---
id: REQ-2026-006
title: 门禁系统 A+B 重构实施 · 概要设计
created_at: 2026-05-04T00:40:00+08:00
refs-requirement: true
refs-outline-design: true
---

# REQ-2026-006 · 概要设计

## 文档定位

spec（`context/team/engineering-spec/design-guidance/gate-system-architecture.md`，commit 51adade）已经审定了"目标架构"的方案与决策。本文档不重新论证方案，只做两件事：

1. **落实 tech-feasibility 提出的 5 项前置条件**——每条给出建议方案 + 备选
2. **把 spec 的目标架构翻译成可实施的模块/数据流/回滚预案**——为 detail-design 阶段写接口签名做准备

---

## 1. 总体架构

### 1.1 三条路径解耦

```
                    ┌─────────────────────────────────────────┐
                    │ Claude Code 框架（PreToolUse / SessionEnd）│
                    └─────────────────────────────────────────┘
                              │                      │
        热路径（每次工具调用）  │                      │ 异步路径（会话结束）
                              ▼                      ▼
        ┌───────────────────────────────┐    ┌──────────────────────────┐
        │ .claude/hooks/                 │    │ .claude/hooks/           │
        │   pre-tool-use-guard.sh (~60行)│    │   audit-flush.sh (~5行)  │
        │   ├─ rule 1: branch protect    │    │   └─ python3 audit_flush │
        │   ├─ rule 2: reviews 路径      │    └──────────────────────────┘
        │   ├─ rule 3: Bash 写 reviews   │              │
        │   └─ trap ERR → fail-open     │              ▼
        └───────────────────────────────┘    ┌──────────────────────────┐
                              │                │ scripts/lib/audit_flush  │
                              │ 仅写 audit/.queue/*.log │                │   .py            │
                              ▼                └──────────────────────────┘
        ┌──────────────────────────────────┐              │
        │ audit/.queue/<YYYY-MM-DD>.log    │◄─────────────┘
        │ （append-only，每行 1 事件）      │
        └──────────────────────────────────┘

        低频路径（阶段切换 / PR 提交 / save-review / manual）
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │ scripts/gates/triggers/<trigger>.sh  │
        │   ├─ check CLAUDE_GATES_GLOBAL_BYPASS│ ──→ audit_log → exit 0
        │   └─ exec python3 run.py ...         │
        └──────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │ scripts/gates/run.py                 │
        │   ├─ check CLAUDE_GATES_GLOBAL_BYPASS│ ──→ audit_log → exit 0
        │   ├─ load registry.yaml (12 gates)   │
        │   ├─ topo sort + 顺序执行            │
        │   ├─ audit_append_async（不阻断）    │
        │   └─ try/except BaseException 兜底  │ ──→ exit 2 → trigger fail-open
        └──────────────────────────────────────┘
```

### 1.2 模块清单

| 模块 | 文件 | 职责 | 新增/修改/删除 |
|---|---|---|---|
| 热路径 hook | `.claude/hooks/pre-tool-use-guard.sh` | 3 条规则 + trap fail-open + audit 留痕 | 新增 |
| 异步 audit 工具 | `scripts/lib/audit_async.sh` | append-only log 函数（供 run.py 调用） | 新增 |
| audit flush 实现 | `scripts/lib/audit_flush.py` | 把 `.queue/*.log` 整理回 JSON | 新增 |
| flush 触发 hook | `.claude/hooks/audit-flush.sh` | SessionEnd 入口（薄壳） | 新增 |
| bats 单测 | `tests/hooks/test_pre_tool_use_guard.bats` | 12 种 pattern + V-01 全部场景 | 新增 |
| 框架配置 | `.claude/settings.json` | PreToolUse 切到新 guard；SessionEnd 加 audit-flush 条目 | 修改 |
| 通用 runner | `scripts/gates/run.py` | 顶部 bypass 检查 + audit 改异步 + main BaseException 兜底 | 修改 |
| 规则注册 | `scripts/gates/registry.yaml` | 删 GATE-PROTECT-BRANCH / GATE-BASH-WRITE-PROTECT；移除 `pre-tool-use` 枚举值 | 修改 |
| 触发器 | `scripts/gates/triggers/<*>.sh` | 顶部加 bypass 检查（仅 audit 留痕，决策委托 run.py） | 修改 |
| 旧热路径 hook | `.claude/hooks/protect-branch.sh` | 退役 | 删除 |
| 旧 trigger | `scripts/gates/triggers/pre_tool_use.sh` | 退役 | 删除 |
| 旧 plugin × 2 | `scripts/gates/plugins/protect_branch.py`、`bash_write_protect.py` | 规则迁移到 guard.sh | 删除 |

### 1.3 数据流

**热路径（每次 Edit/Write/Bash/MultiEdit）**

```
Claude Code 框架
  └─ PreToolUse hook 调用 guard.sh
       ├─ stdin = JSON: {tool_name, tool_input.{file_path|command}}
       ├─ exec 2>>/tmp/guard-error.log（自身错误隔离）
       ├─ check $CLAUDE_GATES_GLOBAL_BYPASS
       │    └─ 非空 → audit_log + exit 0
       ├─ 解析 stdin（jq；失败 → ERR trap → exit 0）
       ├─ case $tool_name:
       │    ├─ Edit|Write|MultiEdit → check_branch + check_review_path
       │    └─ Bash → check_bash_writes_review（12 种 pattern）
       └─ exit 0
  └─ 框架按 exit code 决定放行（0）/ 阻断（2）/ 警告（其他）
```

**低频路径（阶段切换 / PR 提交 / save-review / manual）**

```
trigger 入口（如 phase_transition.sh）
  └─ check $CLAUDE_GATES_GLOBAL_BYPASS（仅 audit 留痕）
       └─ exec python3 run.py --trigger=<X> --req=<REQ-ID> ...
            ├─ 顶部 check $CLAUDE_GATES_GLOBAL_BYPASS（决策真正生效点）
            │    └─ 非空 → audit_log + sys.exit(0)
            ├─ load registry → topo sort → 跑 12 条 gate
            ├─ audit_append_async（best-effort，决策不依赖）
            └─ try/except BaseException → sys.exit(2) → trigger fail-open
```

**异步 audit flush**

```
SessionEnd hook（matcher: prompt_input_exit|logout|other）
  └─ audit-flush.sh
       └─ python3 scripts/lib/audit_flush.py
            ├─ 读 audit/.queue/<YYYY-MM-DD>.log
            ├─ 整理成 audit/<YYYY-MM>/<entry>-<YYYY-MM-DD>.json（按 entry 分桶；entry=runner/submit/triggers/...）
            │   注：entry 是"产生 audit 的代码入口"，与 trigger（hook 事件枚举）不是 1:1。详细命名约定见 detail-design §4.3
            └─ 失败完全静默（下次 SessionEnd 再试）
```

---

## 2. 落实 tech-feasibility 的 5 项前置条件

### 2.1 macOS / CI bash shebang 路径（前置 #1）

**决议**：guard.sh / audit-flush.sh / audit_async.sh 统一使用 `#!/usr/bin/env bash`

| 选项 | 优势 | 劣势 |
|---|---|---|
| `#!/bin/bash`（spec 草案） | 简单直接 | macOS 系统 3.2 vs Homebrew 5.x 行为差异；开发机/CI 不一致风险 |
| ✅ `#!/usr/bin/env bash` | 取 PATH 中第一个 bash，统一开发机（Homebrew 5.x）与 CI（apt 5.x）行为 | env 解析多一次 fork（~1ms）——可忽略 |

**实现影响**：spec §4.1 骨架第一行从 `#!/bin/bash` 改为 `#!/usr/bin/env bash`，其余不变（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:158）。spec 骨架未使用任何 bash 4+ 专属语法（`declare -A` / `mapfile` / `${var^^}`），3.2/5.x 行为一致（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:157）。

### 2.2 12 条正则的来源与抄录方式（前置 #2）

**决议**：从 `scripts/gates/plugins/bash_write_protect.py:58` 的 `_ALTS` 列表完整抄录到 guard.sh 内联正则；**不**沿用 spec §4.1 草案的 3 段 pattern 拼接（草案缺 `printf` 重定向）

**实施约束**：
- guard.sh 内的正则字符串以注释标明来源行号 `# 抄自 scripts/gates/plugins/bash_write_protect.py:58 _ALTS`
- bats 用例对附录 A 全部 12 种 pattern 各加正向用例（应阻断）+ 至少 2 个反例（如 `cat requirements/x/reviews/y.json` 应放行）（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:455）
- 后续若 `_ALTS` 改动，需同步改 guard.sh + bats（在 PR 模板中提示）

**正则维护双轨说明**：guard.sh 与 `bash_write_protect.py` 在 PR-2 后只剩 guard.sh 一处；本期 PR-1/PR-2 期间是双轨过渡（spec D-003 接受这点冗余以换 zero-importlib，来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:429）。

### 2.3 SessionEnd flush 入口（前置 #3）

**决议**：PR-4 同时新增 `.claude/hooks/audit-flush.sh`（薄壳）与 `.claude/settings.json` 的 SessionEnd 条目

| 选项 | 优势 | 劣势 |
|---|---|---|
| ✅ 新增 SessionEnd 条目调 audit_flush.py | 审计完整性可恢复；与现有 `extract-experience.sh` 并列；失败静默不影响其他 hook | settings.json 多 1 条 hook |
| 接受 append-only log 不 flush | 实现简单 | audit/.queue/*.log 永远累积；spec §6.2 验证标准（"SessionEnd 后被 flush"，来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:387）无法通过 |
| 新增独立 cron / housekeeping 脚本 | 与会话生命周期解耦 | 引入新调度依赖，YAGNI |

**新增 SessionEnd 条目（伪 JSON 片段）**：

```json
{
  "matcher": "prompt_input_exit|logout|other",
  "hooks": [
    { "type": "command", "command": ".claude/hooks/extract-experience.sh" },
    { "type": "command", "command": ".claude/hooks/audit-flush.sh" }
  ]
}
```

`audit-flush.sh` 内容：

```bash
#!/usr/bin/env bash
# 失败完全静默——下次 SessionEnd 再试（D-005 best-effort，来源：spec:431）
python3 scripts/lib/audit_flush.py 2>/dev/null || true
```

### 2.4 bats CI 安装方式（前置 #4）

**决议**：在 PR-1 内同步修改 `.github/workflows/quality-check.yml`，在跑测试 step 前新增：

```yaml
- name: Install bats-core
  run: |
    if ! command -v bats >/dev/null; then
      sudo apt-get update && sudo apt-get install -y bats
    fi
- name: Run bats hook tests
  run: bats tests/hooks/
```

实际 yml 路径与 step 编排在 detail-design 阶段确定（需 read 现有 quality-check.yml 才能写精确 patch）。本地开发用 `brew install bats-core` 即可。

### 2.5 jq 缺失语义（前置 #5）

**决议**：接受 jq 缺失即 ERR trap fail-open；**不**实现 python3 fallback；同步把 spec §4.1 注释中"回退到 python3"改为"jq 缺失即 fail-open"（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:160）

**理由**：
- python3 fallback 每次调用多一个分支判断，+约 2ms；与"热路径 < 5ms"目标接近警戒线
- 实际部署中 jq 缺失是极小概率（macOS Homebrew 默认装 + ubuntu-latest 预装）
- ERR trap fail-open 已经是安全降级，符合 spec §1.2.1 的 fail-open 承诺
- spec §4.1 表格中"jq 不可用时回退到 python3"是注释而非硬规约，可改

**spec 同步**：本 PR 顺手修 `gate-system-architecture.md:153` 的依赖说明表，将"如 jq 不可用，回退到 `python3 -c ...`"改为"如 jq 不可用，trap ERR → fail-open"。

---

## 3. bypass 入口的统一签名

spec 要求 bypass 在 3 处入口生效：guard.sh / run.py / triggers/*.sh。tech-feasibility R4 指出 trigger 层 bypass 是冗余防御（决策实际由 run.py 顶部检查决定）。

**统一方案**：trigger 层 bypass **仅写 audit 留痕**（标识入口），决策不在此处生效，委托 run.py。这样三处入口职责清晰：

| 入口 | 触发频率 | bypass 行为 |
|---|---|---|
| `guard.sh`（热路径） | 每次工具调用 | 检查 → audit_log → exit 0（决策点） |
| `triggers/*.sh`（低频） | 阶段切换/PR 提交等 | 检查 → audit_log（仅留痕，标识哪个 trigger 入口被 bypass）→ 仍调 run.py |
| `run.py`（低频核心） | trigger 调用进来 | 检查 → audit_log → sys.exit(0)（决策点） |

### audit 行格式（统一）

```
<ISO8601 timestamp> <cwd> BYPASS used: <reason> @ entry=<entry-name>
```

| 入口 | entry-name 取值 |
|---|---|
| guard.sh | `pre-tool-use-guard` |
| triggers/phase_transition.sh | `trigger:phase-transition` |
| triggers/submit.py（如改造） | `trigger:submit` |
| run.py（直接调用） | `runner` |

写入路径统一为 `audit/.queue/<YYYY-MM-DD>.log`。SessionEnd 后由 `audit_flush.py` 整理。

---

## 4. 4 个 PR 的依赖图

```
        ┌──────────┐
        │  PR-1    │  新增 guard.sh + bats + 切换 settings.json
        └────┬─────┘
             │ 验证 1-2 天（24h+100 次调用，来源：plan.md:60）
             ▼
        ┌──────────┐
        │  PR-2    │  删 4 个旧文件 + registry 调整
        └────┬─────┘
             │ CI 全绿
             ▼
        ┌──────────┐    可并行    ┌──────────┐
        │  PR-3    │ ◄─────────► │  PR-4    │
        │ BYPASS   │              │ 异步 audit │
        │ 三处入口 │              │ + run.py  │
        └──────────┘              │ 兜底       │
                                  └──────────┘
```

**为什么 PR-3 / PR-4 可并行**：PR-3 改 bypass 检查（顶部 if 分支），PR-4 改 audit 写入路径与 main() 兜底；两者改动文件高度重叠（都改 `run.py`）但**改动行不重合**——PR-3 加在第一个 import 之前（spec §4.3 改动 1，来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:286），PR-4 改 main() 函数体（spec §4.3 改动 2/3，来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:302）。两 PR 同时开但合并时第二个会有 import-block 之外的小冲突，rebase 解决即可。

---

## 5. 回滚预案

| PR | 回滚动作 | 风险 | 验证回滚成功 |
|---|---|---|---|
| PR-1 | `.claude/settings.json` 改回旧 hook 路径（1 行） | 低——旧 hook 文件 PR-2 前还在 | 任意 Edit develop 分支 → exit 2 |
| PR-2 | `git revert <PR-2-merge-commit>` 恢复 4 个文件 + registry | 低——纯文件恢复 | `python3 scripts/gates/run.py --validate-registry` exit 0 |
| PR-3 | `git revert` 三处 bypass 检查 | 低——仅删代码不删文件 | 设 BYPASS 后跑 phase-transition gate 应被阻断（旧行为） |
| PR-4 | `git revert` audit 路径与 main 兜底改动 | 中——回滚后异步 audit 队列要清空，否则下次 flush 处理不一致 | 删 `audit/.queue/` 目录 + 跑 phase-transition gate |

**全局逃生**：任何 PR 合入后若 hook 链锁死，立即用 `CLAUDE_GATES_GLOBAL_BYPASS="<原因>"` 设环境变量，所有工具放行；配合 `git revert` 回滚（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:99）。

---

## 6. 与现有规范的对齐

| 规范文件 | 关系 | 本设计动作 |
|---|---|---|
| `context/team/engineering-spec/design-guidance/hook-fail-open.md` | 本设计是该规范的"实现"——之前规范要求 fail-open 但实现有 gap（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:464） | guard.sh 通过 trap、run.py 通过 BaseException 兜底，闭合规范承诺 |
| `context/team/engineering-spec/design-guidance/four-layer-hierarchy.md` | 涉及 Layer 3（场景规范）和 Layer 4（工具实现）；Layer 1/2 不动（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:466） | 不影响 Layer 1/2；Layer 3 微调（jq fallback 描述） |
| `context/team/git-workflow.md` | 4 个 PR 走标准 feat/req-* 分支流程 | 无新增约束 |
| `CLAUDE.md`（项目级"保护分支"） | 行为不变；只是实现路径换了（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:467） | 不需要文档同步修改 |

---

## 7. 验收对齐（与 requirement.md V-01~V-08 的映射）

| V- | 验收点 | 本概要设计承担动作 |
|---|---|---|
| V-01 | bats ≥10 用例覆盖 7 类场景 | §1.2 bats 模块 + §2.2 正则抄录约束 |
| V-02 | sandbox 完整生命周期，4 trigger 仍跑 12 gate | §1.3 数据流低频路径 + §1.2 registry 改动（保留 12 条） |
| V-03 | 注入 NameError → fail-open | §1.3 数据流 try/except BaseException + §5 PR-4 |
| V-04 | audit 权限 555 → 决策不阻断 | §1.3 数据流 audit_append_async（best-effort） |
| V-05 | BYPASS 跳过 + audit 留痕 | §3 bypass 入口统一签名 |
| V-06 | 热路径 < 5ms 〔测量方法待用户确认〕 | §2.1 选 `#!/usr/bin/env bash` 确保统一基准；测量方法 detail-design 阶段定 |
| V-07 | 锁死率 0% | §1.3 trap ERR + try/except BaseException 双层兜底 |
| V-08 | 热路径文件数 = 1 | §1.2 仅 guard.sh 在 PreToolUse 链路；audit_async.sh 在低频路径不计入 |

---

## 8. 进入 detail-design 的待办

| 项 | 必须在 detail-design 决议 |
|---|---|
| guard.sh 的完整正则字符串（从 `_ALTS` 抄录后的具体 ERE 形式） | ✅ |
| bats 用例的具体输入/期望 exit code 表（≥12 正向 + ≥2 反例 + V-01 全部 7 类场景） | ✅ |
| `.github/workflows/quality-check.yml` 的精确 patch（含 step 顺序） | ✅ |
| settings.json 的完整 diff（PreToolUse 切换 + SessionEnd 新增条目） | ✅ |
| run.py 三处改动的具体代码片段（含 import 顺序、main 函数体修改点行号） | ✅ |
| audit_async.sh / audit_flush.py 的接口签名（函数名、参数、返回值） | ✅ |
| 热路径性能基准的测量方法（V-06 落 [待用户确认]） | ✅ |

---

## 待澄清清单

1. **V-06 热路径开销 < 5ms 的测量方法**（沿用自 requirement.md 第 75 行）：本概要设计已通过 §2.1 锁定 `#!/usr/bin/env bash` 作为统一基准，但测量工具与采样方式（bats `time` / hyperfine 微基准 / 真实 30 分钟工作流采样）仍待 detail-design 阶段定下并写入测试用例。

## 不在本设计范围

- **C 方案软警告**（spec §1.3 已排除，来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:62）
- **plugin 框架抽象**（D-002 已决议不要框架，来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:415）
- **BYPASS 白名单 / 角色 / TTL**（信任人类操作员 + audit 事后审，来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:419）
- **deny list 调整**（settings.json 框架级保护不动，来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:107）
- **audit 可视化 / dashboard**（YAGNI，来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:417）
