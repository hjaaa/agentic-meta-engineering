# 门禁系统架构

| 字段 | 值 |
|---|---|
| 创建 | 2026-05-03 |
| 作者 | huangjian + Claude（结对设计） |
| 状态 | Draft（重构 spec → 待实施） |
| 范围 | `.claude/hooks/`、`scripts/gates/`、`.claude/settings.json` |
| 不在范围 | C 方案的"软警告"语义；任何 plugin 框架抽象；audit 可视化 |

> **文档双重角色说明**
>
> 本文档当前承担两个角色：① 门禁系统架构的权威描述，② A+B 重构的实施 spec。
>
> 重构合入后会做一次清理：§1.3（已排除的方案）与 §5（迁移步骤）将被剥离到 `engineering-spec/specs/` 归档；本文剩下的部分变成稳态的"架构现状描述"，供后人改门禁前先读。
>
> 在那之前（重构未完成期间），本文是单一真相源——任何关于"门禁应该长什么样"的讨论都引用本文。

---

## 1. 背景与问题

### 1.1 当前架构（事实）

每次 Edit/Write/Bash/MultiEdit 调用都触发以下链路：

```
PreToolUse Hook
 → .claude/hooks/protect-branch.sh        (18 行壳)
 → scripts/gates/triggers/pre_tool_use.sh (110 行壳)
 → python3 scripts/gates/run.py           (1045 行 god-object)
   → load registry.yaml                   (300+ 行)
   → importlib 加载 2 个 plugin           (protect_branch + bash_write_protect)
   → 执行 + 写 audit/<YYYY-MM>/*.json
 → 退出码映射回 hook
```

实际只跑 **2 条规则**：
1. `develop` / `main` / `master` 上不能直接 Edit/Write/MultiEdit
2. `requirements/*/reviews/*.json` 不能直写（保护 sign-off `tty` 校验深度防御）

### 1.2 已识别的设计缺陷（按"导致锁死"相关性排序）

1. **fail-open 不完整**
   `pre_tool_use.sh` 用 `py_compile` 在调用前做语法检查 → 文件语法错误 fail-open。但运行时异常（NameError、ImportError、KeyError 等）通过 `py_compile` 但运行时炸 → rc=2 → 实际并未 fail-open。memory 条目 "Edit 顺序错会自锁 hook 链 → NameError → 全部工具被拦死" 是真实事故。

2. **自举死锁（bootstrap deadlock）**
   门禁判断逻辑（`run.py` / `registry.yaml` / 2 个 plugin）和被它保护的代码仓库是同一个仓库。Claude 改门禁本身的代码，半成品状态一旦保存，下一次工具调用立刻锁死，连"撤销"那次错误编辑的 Edit 都做不了。当前没有任何全局逃生通道（`CLAUDE_GATES_BYPASS=1` 仅作用于 `bash_write_protect` 的白名单，不是全局开关）。

3. **god-object 在热路径**
   2 条 pre-tool-use 规则不需要 1045 行的注册表 + 拓扑排序 + audit 子系统 + staged_writes + 14 个 gate 的统一框架。复杂度正比于"出 bug 的概率"，而这条路径在每次工具调用上都跑——出 bug 就是全局锁死。F-018 把 plugin 数量从 14 砍到 2 是创可贴；真正的问题是 pre-tool-use 不应该走通用 runner。

4. **多层壳脚本叠加**
   `settings.json → .sh → .sh → .py → .yaml → .py(plugin)`。每多一层就多一个失败点，调试时栈追溯困难。

5. **audit 与决策共享失败域**
   每次 Edit/Write/Bash 都同步写 `audit/<YYYY-MM>/<trigger>-<timestamp>.json`。磁盘满 / 权限丢 / 文件名冲突 → 异常 → 阻断全部工具。审计信息应当异步、可丢失。

### 1.3 已排除的方案

| 方案 | 排除原因 |
|---|---|
| C（软警告） | 用户决策。reviews/\*.json 软化代价太大（破坏 sign-off 安全模型）；hard-block 的清晰性更重要 |
| B2（共享 plugin 判断函数） | 仍走 importlib，故障面没归零；维护两份判断的恐惧是想象出来的 |
| B3（run.py 内部分叉） | god-object 没拆，只多了一条 if 分支，没解决根本问题 |

---

## 2. 目标架构

### 2.1 热路径（每次工具调用，目标 < 5ms）

```
PreToolUse Hook
 → .claude/hooks/pre-tool-use-guard.sh    (~60 行 bash)
   只做 3 件事：
   ├─ rule 1: develop/main/master 上 Edit/Write/MultiEdit → exit 2
   ├─ rule 2: 写 requirements/*/reviews/*.json → exit 2
   └─ rule 3: Bash 含写操作且目标是 reviews/*.json → exit 2
   不读 registry、不 importlib、不写 audit
   trap 'exit 0' ERR  ← 任何意外都 fail-open
```

### 2.2 低频路径（阶段切换 / PR 提交 / save-review）

`run.py` 保留原有能力，但**只在显式 trigger 调用**：

| trigger | 触发场景 | 跑哪些 gate |
|---|---|---|
| `phase-transition` | `/workflow:next [F-012 待落地]` | traceability、reviews-consistency、sourcing |
| `pr-submit` | `/requirement:submit` | plan-freshness、workspace-clean、ahead-of-origin |
| `save-review` | reviewer Agent 落 verdict | reviews_consistency |
| `manual` | 调试、离线审计 | 全部 |

**完全离开热路径**——慢一点没关系，单次调用 200ms 也无所谓。

### 2.3 全局逃生通道

`CLAUDE_GATES_GLOBAL_BYPASS=<reason>` 在三处入口生效：
- `.claude/hooks/pre-tool-use-guard.sh`
- `scripts/gates/run.py`
- `scripts/gates/triggers/*.sh`（除 `pre_tool_use.sh` 已删）

启用时强制写 audit 行：`BYPASS used: <reason> @ <ts> @ <cwd>`

### 2.4 deny list 不动

`rm -rf` / `git reset --hard` / `git push --force` 仍然走 `.claude/settings.json` 的 deny——这是 Claude Code 框架级保护，和 hook 链解耦，本来就不会引发锁死。

---

## 3. 文件清单

### 3.1 新增

| 文件 | 行数 | 职责 |
|---|---|---|
| `.claude/hooks/pre-tool-use-guard.sh` | ~60 | 热路径 hook 唯一实现 |
| `scripts/lib/audit_async.sh` | ~30 | 异步 audit 工具函数（A2 用） |
| `tests/hooks/test_pre_tool_use_guard.bats` | ~80 | 单测套件 |

### 3.2 修改

| 文件 | 改动 |
|---|---|
| `.claude/settings.json` | hook 矩阵指向 `pre-tool-use-guard.sh` |
| `scripts/gates/run.py` | 顶部加 `CLAUDE_GATES_GLOBAL_BYPASS` 检查；audit 改异步；`main()` 最外层 `try/except BaseException` |
| `scripts/gates/registry.yaml` | 删 `GATE-PROTECT-BRANCH` / `GATE-BASH-WRITE-PROTECT`；`triggers` 字段删除 `pre-tool-use` 枚举值 |
| `scripts/gates/triggers/*.sh`（除 pre_tool_use） | 顶部加 `CLAUDE_GATES_GLOBAL_BYPASS` 检查 |

### 3.3 删除（B1 核心动作）

| 文件 | 理由 |
|---|---|
| `.claude/hooks/protect-branch.sh` | 被 `pre-tool-use-guard.sh` 取代 |
| `scripts/gates/triggers/pre_tool_use.sh` | 同上 |
| `scripts/gates/plugins/protect_branch.py` | 规则迁移到 `pre-tool-use-guard.sh` |
| `scripts/gates/plugins/bash_write_protect.py` | 同上 |

---

## 4. 详细规约

### 4.1 `.claude/hooks/pre-tool-use-guard.sh`

**契约**

| 项 | 值 |
|---|---|
| 输入 | stdin 为 Claude Code Hook JSON：`tool_name` / `tool_input.{file_path,command}` |
| 输出 | `exit 0` = 放行；`exit 2` = 阻断（stderr 文本回传给 Agent）；任何意外 → trap → `exit 0` |
| stderr 用途 | 阻断时输出"为什么阻断 + 怎么规避"；fail-open 自身错误不写 stderr，写 `/tmp/guard-error.log` |
| 依赖 | `bash 4+`、`git`、`grep`、`jq`（如 jq 不可用：`jq` 命令失败 → 赋值非零 → ERR trap → exit 0 fail-open；不实现 python3 fallback，REQ-2026-006 detail-design §2.5 决议） |

**实现骨架（按短路顺序）**

```bash
#!/bin/bash
set -u
trap 'exit 0' ERR
exec 2>>/tmp/guard-error.log  # 自身错误落本地，不污染 hook 协议

main() {
  local input tool_name file_path command branch

  # 0. 全局 bypass（A1 的核心逃生）
  if [[ -n "${CLAUDE_GATES_GLOBAL_BYPASS:-}" ]]; then
    audit_log "BYPASS used: $CLAUDE_GATES_GLOBAL_BYPASS"
    exit 0
  fi

  # 1. 解析 stdin（解析失败 → trap → fail-open）
  input=$(cat)
  tool_name=$(echo "$input" | jq -r '.tool_name // empty')
  file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')
  command=$(echo "$input"  | jq -r '.tool_input.command   // empty')

  case "$tool_name" in
    Edit|Write|MultiEdit)
      check_branch_protect
      check_review_path "$file_path"
      ;;
    Bash)
      check_bash_writes_review "$command"
      ;;
  esac

  exit 0
}

check_branch_protect() {
  local b
  b=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || return 0
  case "$b" in
    main|master|develop)
      cat >&2 <<EOF
BLOCKED: 当前在 '$b' 分支，禁止直接 Edit/Write/MultiEdit。
规避方式：
  1) 切到 feature 分支（推荐）：git checkout -b feature/req-xxx
  2) 紧急绕过（需理由）：CLAUDE_GATES_GLOBAL_BYPASS="抢救门禁本身被锁死" <重新执行操作>
EOF
      exit 2
      ;;
  esac
}

check_review_path() {
  local p="$1"
  [[ -z "$p" ]] && return 0
  if [[ "$p" =~ ^.*requirements/[^/]+/reviews/.+\.json$ ]]; then
    cat >&2 <<EOF
BLOCKED: $p
reviews/*.json 不能直写。必须走 scripts/save-review.sh 或人类 sign-off CLI。
规避方式：CLAUDE_GATES_GLOBAL_BYPASS="<理由>" 但请先停下来想想是不是真的应该绕过。
EOF
    exit 2
  fi
}

check_bash_writes_review() {
  local cmd="$1"
  [[ -z "$cmd" ]] && return 0
  # 12 种写入模式，从 bash_write_protect.py 抄录（见附录 A）
  local pattern='(>|>>|tee|sponge|dd[[:space:]]+of=|rsync|install|mv|cp)[[:space:]]+[^|;&]*requirements/[^/]+/reviews/[^[:space:]]+\.json'
  pattern+='|python3?[[:space:]]+-c[[:space:]]+["'"'"'].*open\([^)]*requirements/[^/]+/reviews/[^)]+\.json'
  pattern+='|cat[[:space:]]+<<.*>[[:space:]]*[^|;&]*requirements/[^/]+/reviews/[^[:space:]]+\.json'

  if echo "$cmd" | grep -qE "$pattern"; then
    cat >&2 <<EOF
BLOCKED: Bash 写入 requirements/*/reviews/*.json 被禁。
规避方式：scripts/save-review.sh 是 reviewer Agent 的标准入口；
     人类 sign-off 走 python3 scripts/lib/save_review.py signoff ...（必须 tty；F-012 后唯一入口）。
EOF
    exit 2
  fi
}

audit_log() {
  local line="$(date -Iseconds) $(pwd) $1"
  mkdir -p audit/.queue 2>/dev/null || return 0
  echo "$line" >>"audit/.queue/$(date +%Y-%m-%d).log" 2>/dev/null || true
}

main "$@"
```

**关键设计选择**

| 选择 | 理由 |
|---|---|
| `set -u` 但不 `set -e` | `set -e` 会被中间命令的非零退出码（如 `grep -q` 不匹配）误伤 |
| `trap 'exit 0' ERR` | 任何 ERR 信号 → fail-open；即使 trap 处理本身报错，bash 默认行为也是 exit 0 |
| `exec 2>>/tmp/guard-error.log` | 自身错误不能进 stderr（会被 hook 协议当成"阻断理由"传给 Agent） |
| 自定义错误信息含"规避方式" | 避免 Agent 反复重试浪费 token |
| jq 解析 JSON | 比 bash regex 健壮；jq 不可用时回退 python3 |
| pattern 写在脚本里 | YAGNI——一年改不到一次，YAML 化是过度抽象 |

**已知限制**

| 项 | 说明 |
|---|---|
| 字面量匹配 | 12 类正则仅匹配命令行中字面量出现的 review 路径；变量间接引用是已知绕过通道，由 BYPASS reason 长度 ≥ 8 + audit reason 全文 + PR review 人工检查共同兜底（REQ-2026-006 F-002 决策） |

### 4.2 `scripts/lib/audit_async.sh`

提供两个函数，供 `run.py`（Python 通过 subprocess 调用）和未来其他 trigger 脚本（bash 直接 source）使用。

> 注：`pre-tool-use-guard.sh` 出于"最小依赖、最快启动"考虑，**不 source 此文件**，自行内联了等价的 `audit_log()`（见 §4.1）。这是有意冗余——10 行重复换来零依赖。

```bash
audit_append_async() {
  local line="$1"
  local f="audit/.queue/$(date +%Y-%m-%d).log"
  mkdir -p "$(dirname "$f")" 2>/dev/null || return 0
  # O_APPEND 在 ext4/apfs 原子；不加锁
  echo "$line" >>"$f" 2>/dev/null || true
}

audit_flush_queue() {
  # SessionEnd hook 调用：把 .queue/*.log 整理成原 JSON 格式
  # 失败完全静默；下次 SessionEnd 再试
  python3 scripts/lib/audit_flush.py 2>/dev/null || true
}
```

`run.py` 替换原来的同步写盘逻辑：所有 `write_audit(...)` 调用改为 `audit_append_async(json.dumps(record))`。

### 4.3 `scripts/gates/run.py` 改动

**改动 1**：文件最顶部（第 1 个 import 之前）加 bypass 检查

```python
import os, sys
if os.environ.get("CLAUDE_GATES_GLOBAL_BYPASS"):
    # 写一行 audit 后直接退出
    reason = os.environ["CLAUDE_GATES_GLOBAL_BYPASS"]
    try:
        from datetime import datetime
        with open(f"audit/.queue/{datetime.now():%Y-%m-%d}.log", "a") as f:
            f.write(f"{datetime.now().isoformat()} {os.getcwd()} BYPASS used: {reason}\n")
    except Exception:
        pass
    sys.exit(0)
```

**改动 2**：`main()` 最外层兜底

```python
def main():
    try:
        return _real_main()
    except SystemExit:
        raise
    except BaseException as e:
        # 任何未捕获异常 → 写 error log → 走 fail-open 协议
        # （rc=2 在 trigger 层映射为 fail-open，参考 hook-fail-open.md）
        try:
            with open("/tmp/run-py-error.log", "a") as f:
                import traceback
                f.write(f"\n--- {datetime.now()} ---\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
        sys.exit(2)
```

**改动 3**：所有 `write_audit_sync(...)` 调用改成 `audit_append_async(...)`

### 4.4 `.claude/settings.json` 改动

只改一处：`hooks.PreToolUse[0].hooks[0].command`

```diff
- "command": ".claude/hooks/protect-branch.sh"
+ "command": ".claude/hooks/pre-tool-use-guard.sh"
```

matcher 保持 `"Bash|Edit|Write|MultiEdit"`。

### 4.5 `scripts/gates/registry.yaml` 改动

```diff
- - id: GATE-PROTECT-BRANCH
-   plugin: protect_branch
-   ...
- - id: GATE-BASH-WRITE-PROTECT
-   plugin: bash_write_protect
-   ...
```

`trigger` 枚举类型移除 `pre-tool-use` 值（如有 schema 定义）。

---

## 5. 迁移步骤（4 个独立可回滚 PR）

| PR | 内容 | 验证 | 回滚 |
|---|---|---|---|
| **PR-1** | 新增 `pre-tool-use-guard.sh` + bats 测试 + 切换 `settings.json` | 在 sandbox 跑完 7 类场景；用临时 feature 分支验证 30 分钟实际工具调用 | 改回 `settings.json` 一行 |
| **PR-2** | 删除 `protect-branch.sh` / `pre_tool_use.sh` / 两个 plugin / registry 两条 gate | CI 全绿；sandbox 跑完整 REQ 周期 | `git revert` |
| **PR-3** | A1: `CLAUDE_GATES_GLOBAL_BYPASS`（3 处入口） | 单测覆盖每个入口；audit 落盘验证 | `git revert` |
| **PR-4** | A2 + A3: 异步 audit + `run.py` 最外层兜底 | 注入异常验证 audit 不卡决策；注入 `KeyError` 验证 fail-open | `git revert` |

**顺序约束**：
- PR-1 必须先合（新旧并行的窗口里不会有工具锁死风险，旧脚本不再被 settings 引用即等同失活）
- PR-2 在 PR-1 验证 1-2 天后合
- PR-3 / PR-4 顺序无关，可并行

---

## 6. 测试方案

### 6.1 单元测试（bats，~10 个用例）

```
✓ branch=develop, tool=Edit                              → exit 2
✓ branch=feature/x, tool=Edit                            → exit 0
✓ tool=Edit, path=requirements/REQ-x/reviews/y.json      → exit 2
✓ tool=Bash, cmd="echo x > requirements/REQ-x/reviews/y.json" → exit 2
✓ tool=Bash, cmd="cat requirements/REQ-x/reviews/y.json" → exit 0
✓ CLAUDE_GATES_GLOBAL_BYPASS="reason" + 上述任一阻断场景 → exit 0
✓ stdin 不是合法 JSON                                    → exit 0（fail-open）
✓ 当前不在 git 仓库                                       → exit 0
✓ tool_name 缺失                                         → exit 0
✓ git 命令不存在（PATH 隔离）                              → exit 0
```

### 6.2 集成测试

用 sandbox `REQ-2099-001` 跑完整需求生命周期，确认：
- 4 个低频 trigger（phase-transition / pr-submit / save-review / manual）仍正确触发剩余 12 条 gate
- audit/.queue 有内容，SessionEnd 后被 flush 成 audit/<YYYY-MM>/*.json

### 6.3 故障注入测试

| 注入 | 预期 |
|---|---|
| `pre-tool-use-guard.sh` 改坏 chmod -x | hook 调用失败 → Claude Code 框架行为兜底（不归我们管） |
| `pre-tool-use-guard.sh` 文件被删 | 同上 |
| `run.py` 顶部加一行 `raise NameError` | rc=2 → trigger 层 fail-open；不锁死 |
| `audit/.queue` 目录权限改 555 | audit 写盘失败被 swallow；决策正常 |
| `CLAUDE_GATES_GLOBAL_BYPASS="x"` 设置后 | 所有 gate 跳过；audit 有 BYPASS 行 |

---

## 7. 风险与对策

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| bash 写检测的 grep pattern 漏掉某些写法 | 中 | reviewers 能绕过 sign-off 安全模型 | 从老 plugin 完整抄 12 种 pattern；测试覆盖每种；附录 A 列出 |
| fail-open 太宽，protect-branch 误漏放行 | 低 | develop 上偶发污染 | fail-open 时写 `/tmp/guard-error.log`，每周人审；CI 也会卡 |
| `CLAUDE_GATES_GLOBAL_BYPASS` 被滥用 | 中 | 安全模型软化 | 必须有 reason；audit 强制记录；PR review 时检查 audit log |
| jq 不在 PATH | 低 | guard 脚本启动报错 | 回退 python3 -c；最终 trap 兜底 |
| 异步 audit 丢失记录 | 中 | 审计完整性下降 | 接受——审计本来就是 best-effort；决策正确性优先 |

---

## 8. 不做的事（YAGNI 边界）

- ❌ 软警告模式（C 方案，已 out of scope）
- ❌ 抽公共 plugin 接口（B1 核心就是不要框架）
- ❌ hook 热更新 / 重载机制
- ❌ audit 可视化 / dashboard
- ❌ 把规则做成可配置 YAML（硬编码 + 单测覆盖比 YAML 更可靠，规则一年改不到一次）
- ❌ 给 `CLAUDE_GATES_GLOBAL_BYPASS` 做白名单 / 角色 / TTL（信任人类操作员；audit 事后审）

---

## 9. 决策记录（Decision Log）

| ID | 决策 | 背景 | 备选 | 选择理由 |
|---|---|---|---|---|
| D-001 | 走 B1 而非 B2/B3 | 用户痛点是"频繁锁死"，根因是热路径与 god-object 耦合 | B2 共享判断函数；B3 内部分叉 | 只有彻底解耦才能根治；2 条规则不需要 plugin 框架抽象 |
| D-002 | 排除 C 方案（软警告） | 用户最初倾向 C，后改 A+B | C 把所有 gate 改提示式 | reviews/\*.json 软化代价太大（破坏 sign-off 安全模型）；hard-block 的清晰性更重要 |
| D-003 | 不在 guard.sh 里调用 Python | Python 启动开销 + 故障面 | 用 Python 实现 guard | bash 足够覆盖 3 条规则；启动快 5x；无 importlib 故障面 |
| D-004 | `CLAUDE_GATES_GLOBAL_BYPASS` 必须带 reason | 防滥用 + 可审计 | 单纯 `=1` | 增加心理负担；audit 可读性高 |
| D-005 | audit 异步 + best-effort（允许丢） | 决策正确性 > 审计完整性 | 同步写 + 失败即阻断 | 当前 audit 没有任何下游消费者强依赖完整性 |
| D-006 | 删除 `pre-tool-use` 作为 trigger 枚举值 | 避免后人误以为还可以注册 | 保留枚举但 deprecated | 一次性清干净；要恢复直接 git revert |

---

## 附录 A：bash 写入 pattern 完整清单

从 `scripts/gates/plugins/bash_write_protect.py` 提取的 12 种写入模式（迁移到 `pre-tool-use-guard.sh` 的正则）：

| # | 模式 | 例子 |
|---|---|---|
| 1 | `> file` | `echo x > a.json` |
| 2 | `>> file` | `echo x >> a.json` |
| 3 | `tee file` | `echo x \| tee a.json` |
| 4 | `tee -a file` | `echo x \| tee -a a.json` |
| 5 | `sponge file` | `cat \| sponge a.json` |
| 6 | `dd of=file` | `dd of=a.json` |
| 7 | `mv src file` | `mv tmp a.json` |
| 8 | `cp src file` | `cp tmp a.json` |
| 9 | `rsync ... file` | `rsync src a.json` |
| 10 | `install ... file` | `install -m 644 src a.json` |
| 11 | `python -c "open(file,'w')"` | `python3 -c "open('a.json','w').write(...)"` |
| 12 | heredoc redirect | `cat <<EOF > a.json` |

正则覆盖见 §4.1 `check_bash_writes_review` 的 `pattern` 变量。每条 pattern 对应一个 bats 测试用例。

---

## 附录 B：与现有规范的关系

| 规范文件 | 关系 |
|---|---|
| `context/team/engineering-spec/design-guidance/hook-fail-open.md` | 本设计**实现**这份规范的承诺（spec 早就要求 fail-open，但实现有 gap），不冲突 |
| `context/team/ai-collaboration.md` 之"sign-off 是人类专属动作" | 本设计**强化**这条——`pre-tool-use-guard.sh` 的 rule 2/3 是 tty 校验的深度防御层，硬阻断保留 |
| `context/team/engineering-spec/design-guidance/four-layer-hierarchy.md` | 本设计涉及 Layer 3（场景规范）和 Layer 4（工具实现）；Layer 1/2 不动 |
| `CLAUDE.md` 项目级"保护分支" | 行为不变；只是实现路径换了 |

---

## 附录 C：度量指标（重构验收标准）

| 指标 | 当前 | 目标 |
|---|---|---|
| 每次 Edit/Write/Bash 的 hook 开销 | ~12-30ms（Python 启动 + 2 plugin 加载） | < 5ms（bash + git rev-parse） |
| 锁死复现率（注入运行时异常到 plugin） | 100%（NameError 锁死） | 0%（fail-open 兜住） |
| 热路径代码量 | 1045 + 300 + 161 + 241 + 110 + 18 = 1875 行 | ~60 行 |
| 热路径文件数 | 6 个 | 1 个 |
| 全局逃生通道 | 无 | `CLAUDE_GATES_GLOBAL_BYPASS` |

---

## 后续步骤

1. 用户 review 本 spec 并确认（或提修改意见）
2. 用 `superpowers:writing-plans` skill 把本 spec 拆成可执行的 4 个 PR 实施计划
3. 每个 PR 走标准 PR 流程：分支 → 实现 → 自测 → `/code-review` → sign-off → merge
