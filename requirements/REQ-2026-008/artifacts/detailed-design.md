---
id: REQ-2026-008
title: 派发链强制结构化升级 · 详细设计
created_at: 2026-05-06T09:50:00+08:00
phase: detail-design
refs-requirement: true
refs-tech-feasibility: true
refs-outline-design: true
---

# REQ-2026-008 · 详细设计

## 文档定位

outline-design.md 已定 4 层视图 / 24 改动文件 / 8 features DAG / 3 时序（来源：requirements/REQ-2026-008/artifacts/outline-design.md:24）。本文档为 detail-design 阶段产出，聚焦：

1. **接口签名 + 数据结构精确化**——为任务规划阶段拆 features.json 提供"实现者照抄即可"的契约
2. **Hook 链精确 patch**——给出 `.claude/settings.json` / `pre-tool-use-guard.sh` 的逐行改动
3. **fail-open / 锁工具 / schema 演化**等关键运行时契约文档化

> outline-design §6 列了 13 项 detail-design 待办；本文档按"先三连（#1 + #3 + #4）→ 再批次推进"的节奏写。本次首批落地 #1 / #3 / #4，剩余项在后续 commit 增量补全。

---

## 1. Hook 链精确 patch（对应 outline-design §6 待办 #1）

### 1.1 settings.json patch

`.claude/settings.json:23-29` 当前 PreToolUse 注册（来源：.claude/settings.json:24）：

```json
"PreToolUse": [
  {
    "matcher": "Bash|Edit|Write|MultiEdit",
    "hooks": [{"type": "command", "command": ".claude/hooks/pre-tool-use-guard.sh"}]
  }
]
```

**改动**（最小变更，新增 `|Task`）：

```diff
-        "matcher": "Bash|Edit|Write|MultiEdit",
+        "matcher": "Bash|Edit|Write|MultiEdit|Task",
```

**关键发现（D-007，来源：requirements/REQ-2026-008/plan.md:95）**：实采样实测 PreToolUse stdin 顶层 `tool_name` 为 `"Agent"`（不是 `"Task"`），但 Claude Code 端 matcher 字符串 `"Task"` 仍能命中 `tool_name=Agent`——matcher 与 tool_name 之间存在别名映射。**配置层保留 `"Task"`**（与官方文档习惯一致），**实现层在 dispatch_precheck.py 内以 `tool_name == "Agent"` 判断**。

> 不引入"独立 PreToolUse 条目"备选（tech-feasibility §2.1 备选 B，来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:62）：避免 Edit/Write/MultiEdit 走两次 hook 链导致执行冗余 + 时序耦合。

### 1.2 pre-tool-use-guard.sh patch

#### 1.2.1 改动定位（精确行号）

guard.sh 现 145 行（来源：.claude/hooks/pre-tool-use-guard.sh:145）；改动集中在 **case 分发段**（line 88-96，来源：.claude/hooks/pre-tool-use-guard.sh:88）：

```sh
# 当前 (line 88-96)
case "$tool_name" in
  Edit|Write|MultiEdit)
    check_branch_protect
    check_review_path "$file_path"
    ;;
  Bash)
    check_bash_writes_review "$command"
    ;;
esac
```

#### 1.2.2 改动后（精确 diff）

```diff
   case "$tool_name" in
+    Agent)
+      # PreToolUse Task 派发：matcher="Task" 命中 tool_name="Agent"（D-007）
+      # 透传退出码——dispatch_precheck.py 自负 fail-open（解析失败 / 锁 timeout 一律 exit 0）
+      exec python3 "$( dirname "${BASH_SOURCE[0]}" )/dispatch_precheck.py" <<<"$input"
+      ;;
     Edit|Write|MultiEdit)
       check_branch_protect
       check_review_path "$file_path"
+      # touches 软拦截：恒 exit 0；任何异常 || true 兜底（绝不阻塞写工具）
+      python3 "$( dirname "${BASH_SOURCE[0]}" )/touches_guard.py" <<<"$input" || true
       ;;
     Bash)
       check_bash_writes_review "$command"
       ;;
   esac
```

#### 1.2.3 设计要点逐条

1. **Agent case 用 `exec`**——直接替换当前 shell 进程，dispatch_precheck.py 的 exit code 透传给 Claude Code Agent；avoid `cat | python3` 的双进程开销。
2. **`<<<"$input"` heredoc 二次喂 stdin**——guard.sh main 函数已 `input=$(cat)` 消费过 stdin（来源：.claude/hooks/pre-tool-use-guard.sh:83），需把保存的 `$input` 重新喂给 Python hook。
3. **touches_guard `|| true` 软拦截**——恒 exit 0；与 guard.sh 顶部 `trap 'exit 0' ERR`（来源：.claude/hooks/pre-tool-use-guard.sh:6）哲学一致：写工具的 hook 链绝不因 touches_guard 异常而误伤合法写入。
4. **Hook 路径用 `$( dirname "${BASH_SOURCE[0]}" )`**——避免假定 cwd=repo root；guard.sh 已用此模式取 `_audit_root`（来源：.claude/hooks/pre-tool-use-guard.sh:43）。
5. **case 顺序无关**——bash case 是首次匹配即返回，但 Agent / Edit|Write|MultiEdit / Bash 三个分支互斥（PreToolUse stdin 的 tool_name 单值），顺序与可读性按"新→旧"排即可。

#### 1.2.4 为什么 Agent case 不写 check_branch_protect

派发本身不写文件；Task tool 的 stdin 不含 file_path / command 字段（实采样确认，来源：requirements/REQ-2026-008/plan.md:95）。分支保护已由 Edit/Write/MultiEdit/Bash 入口侧拦截。

#### 1.2.5 ERR trap 互动

guard.sh 顶部 `set -u` + `trap 'exit 0' ERR`（来源：.claude/hooks/pre-tool-use-guard.sh:6）保证任意失败 → exit 0。新增两个分支的影响：

- **Agent 分支 `exec` 失败**（python3 不存在等极端场景）：`exec` 失败仍触发 ERR → trap 接管 → exit 0（fail-open）。
- **Agent 分支 `exec` 成功后 Python 崩溃**：`exec` 已替换 shell 进程，guard.sh 不再回到 shell，**ERR trap 接不住 Python 内部崩溃**——由 dispatch_precheck.py 自身的 §2.6 顶层 `except Exception` 兜底转 `sys.exit(0)`。两条路径互不重叠。
- **touches_guard 分支 `|| true`**：任意非零退出被吃掉，ERR 不触发。

### 1.3 影响域分析

| 改动 | 触达入口 | 回归风险 | 缓解 |
|---|---|---|---|
| matcher `+\|Task` | 任何 Task tool 派发新增 hook 调用 | dispatch_precheck.py 解析失败时静默放行（fail-open，§2.2） | tech-feasibility §2.1 R6 已实采样确认 stdin schema |
| guard.sh +Agent case | 仅 Agent 工具触发新分支 | python3 启动开销 ~80ms | 现有 hook 已多处 jq+python3，可接受 |
| guard.sh +touches_guard 调度 | 所有 Edit/Write/MultiEdit | 软拦截 `\|\| true` 兜底，最坏静默落 violation 字段 | 单测覆盖 ERR trap / 无 receipt / 无 state.json 三场景 |

### 1.4 单测覆盖（tests/hooks/）

| 用例 ID | 路径 | 场景 | 期望 |
|---|---|---|---|
| TH-001 | `tests/hooks/test_guard_dispatch_route.bats` | tool_name=Agent + 合规 prompt | dispatch_precheck.py 被 exec，guard.sh 不再执行 main 末尾 exit 0 |
| TH-002 | 同上 | tool_name=Agent + dispatch_precheck.py exit 2 | guard.sh 透传 exit 2 |
| TH-003 | 同上 | tool_name=Agent + python3 不存在 | ERR trap → exit 0（fail-open） |
| TH-004 | `tests/hooks/test_guard_touches_route.bats` | tool_name=Edit + touches_guard exit 1 | guard.sh 仍 exit 0（软拦截） |
| TH-005 | 同上 | tool_name=Edit + touches_guard 卡死 5s+ | guard.sh exit 0（外层 ERR 不触发） |

> bats 框架已在仓库使用（来源：tests/hooks/test_pre_tool_use_guard.bats），新增 5 用例延续 bats；stdin 喂入用 bats 的 `run --stdin <<<"$payload"` 模式与既有 hook 测试对齐。

---

## 2. dispatch_precheck.py 接口契约（对应 outline-design §6 待办 #3）

### 2.1 输入 / 输出 / 副作用

```
路径：.claude/hooks/dispatch_precheck.py
触发：guard.sh Agent case 透传 stdin JSON

输入（stdin JSON，实采样确认 D-007）：
  {
    "tool_name": "Agent",
    "tool_input": {
      "prompt": "<派发文本，含首行 feature_id: F-xxx>",
      "subagent_type": "<Explore|general-purpose|...>",
      "description": "<简短标题>"
    },
    "session_id": "<uuid>",
    "transcript_path": "<jsonl path>",
    "cwd": "<repo abs path>",
    "permission_mode": "<auto|...>",
    "hook_event_name": "PreToolUse",
    "tool_use_id": "<toolu_xxx>"
  }

输出（exit code + stderr）：
  exit 0  → 放行（含所有 fail-open 分支）
  exit 2  → 阻断；stderr 输出 BLOCKED 消息（PreToolUse 协议会回传 Agent）

副作用：
  ✅ 成功放行（status / depends_on / 并发三校验全过）→ 写 .dispatch-state.json
     {"schema_version":"1.0","req_id":"REQ-xxx","current_feature":"F-xxx",
      "acquired_at":"<iso8601>","acquired_by_pid":<int>}
  ✅ audit 日志：所有 fail-open / 阻断 / 成功路径都写一行到 audit/.queue/<date>.log
  ❌ 不写其他文件、不读 reviews/、不调 gate
```

### 2.2 fail-open 场景表（穷举）

派发链的红线是"AI 不可被自由意志绕过"，但 dispatch_precheck **本身不应造成误伤**。所有"无法准确判定违规"的场景一律 fail-open exit 0：

| # | 场景 | 检测点 | 行为 | audit 行为 |
|---|---|---|---|---|
| 1 | tool_name 不是 "Agent" | 入口断言 | exit 0 | 不写 audit（误命中） |
| 2 | stdin 解析失败（JSON 非法 / 截断） | json.loads 异常 | exit 0 | `audit_log("FAIL_OPEN: stdin parse error")` |
| 3 | tool_input.prompt 缺失 / 非 string | dict 取值 | exit 0 | `audit_log("FAIL_OPEN: prompt missing")` |
| 4 | feature_id 解析失败（首部 5 行 regex 全 miss） | parse_feature_id 返回 None | exit 0 | `audit_log("FAIL_OPEN: feature_id unresolved | head=<前 5 行 sha256>")` |
| 5 | features.json 不存在（极早期需求） | Path.exists | exit 0 | `audit_log("FAIL_OPEN: features.json absent | req=<id>")` |
| 6 | features.json 解析失败 | yaml/json 异常 | exit 0 | `audit_log("FAIL_OPEN: features.json parse error")` |
| 7 | feature_id 不在 features.json | id 不在列表 | exit 0 | `audit_log("FAIL_OPEN: feature_id <fid> not found")` |
| 8 | .dispatch-state.json 锁 timeout 5s+ | dispatch_state.flock_state_file TimeoutError | exit 0 | `audit_log("FAIL_OPEN: state lock timeout")` |
| 9 | .dispatch-state.json 写失败（磁盘满 / 权限） | OSError | exit 0 | `audit_log("FAIL_OPEN: state write failed | <errno>")` |
| 10 | 任何未预期异常 | 顶层 try/except Exception | exit 0 | `audit_log("FAIL_OPEN: unexpected | <type>:<msg 截断 200 字符>")` |

**fail-open 哲学**（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:124）：与 guard.sh 顶部 `trap 'exit 0' ERR` 一致——**hook 异常绝不阻塞用户**。校验确定性由 gate 层（GATE-POST-DEV-RECEIPT / GATE-TOUCHES-VIOLATION）兜底，hook 层是软线。

### 2.3 阻断场景表（exit 2）

| # | 场景 | 检测点 | stderr BLOCKED 消息 |
|---|---|---|---|
| B-1 | features.json 中 feature 状态 ≠ "pending" | features[fid].status | `BLOCKED: F-xxx 状态为 <s>，期望 pending；如要重派需先回退状态。` |
| B-2 | depends_on 列出的 feature 状态 ≠ "done" | features[fid].depends_on 遍历 | `BLOCKED: F-xxx 依赖 [F-aaa(s),F-bbb(s)] 未全部 done。` |
| B-3 | .dispatch-state.json 已有 current_feature 且不是本 feature_id | state["current_feature"] | `BLOCKED: 已有 F-yyy 派发中（acquired_at=<ts>），保守档串行约束禁止并发派 implementer。` |

> B-1/B-2/B-3 的 stderr 都给"绕过指引"——`CLAUDE_GATES_GLOBAL_BYPASS="<原因>"` 紧急通道与 guard.sh 现有 BYPASS 机制对齐（来源：.claude/hooks/pre-tool-use-guard.sh:62）：dispatch_precheck.py 复用 guard.sh 的 BYPASS 处理路径——guard.sh 入口已校验完 `CLAUDE_GATES_GLOBAL_BYPASS` 后才进入 case 分发（来源：.claude/hooks/pre-tool-use-guard.sh:63），因此 Agent case 抵达时 BYPASS 已被吃掉并 exit 0；dispatch_precheck.py 自身**不再重复实现** BYPASS 校验。reason 长度 ≥ 8 的硬约束沿用 guard.sh main 函数（来源：.claude/hooks/pre-tool-use-guard.sh:70）。

### 2.4 校验链时序

```
入口
  ├─[1] 解析 stdin JSON → 失败 fail-open 返回
  ├─[2] 断言 tool_name == "Agent" → 否则 fail-open（场景 1）
  ├─[3] 取 tool_input.prompt → 缺失 fail-open（场景 3）
  ├─[4] parse_feature_id(prompt) → 失败 fail-open（场景 4）
  ├─[5] req_dir = locate_req_dir_by_branch()
  │      └─ git rev-parse --abbrev-ref HEAD → 匹配 meta.yaml.branch
  │      └─ 失败 fail-open（视同 features.json 不存在场景 5）
  ├─[6] features.json 读 → 解析 / 不存在 fail-open（场景 5/6）
  ├─[7] feature_id ∈ features → 否则 fail-open（场景 7）
  ├─[8] with dispatch_state.flock_state_file(req_dir) as fh:   ← **同一把锁内**完成读+校验+写
  │      ├─[8a] state = fh.read()                                # 锁内读，禁止用 read_state（会取第二把锁）
  │      ├─[8b] 校验 status == "pending"（B-1）
  │      ├─[8c] 校验 depends_on 全 done（B-2）
  │      ├─[8d] 校验 state["current_feature"] is None or == feature_id（B-3）
  │      ├─[8e] 三校验任一失败 → 释放锁（with 自动）→ exit 2 + BLOCKED stderr
  │      └─[8f] 三校验全过 → fh.write(...)（current_feature=feature_id, acquired_at=now, acquired_by_pid=os.getpid()）
  └─[9] exit 0 + audit_log("DISPATCH_OK: F-xxx | req=<id>")
```

**为什么必须单锁**：read_state / write_state 各取独立锁会形成 **TOCTOU 窗口期**——两个进程 A/B 同时跑：A read→B read→A 校验过→A write→B 校验过（B 看到的是 A write 之前的旧 state）→B write 覆盖 A → 并发派发漏过 B-3 校验。`flock_state_file` 上下文管理器把整个 read+三校验+write 包在单把 LOCK_EX 锁内，杜绝中间窗口。

### 2.5 audit 日志路径

复用 guard.sh 的 audit/.queue 机制（来源：.claude/hooks/pre-tool-use-guard.sh:48）：

```python
# 伪代码
def audit_log(line: str) -> None:
    """与 guard.sh audit_log 等价：写 audit/.queue/<date>.log；任何失败 silently swallow"""
    root = os.environ.get("CLAUDE_GATES_AUDIT_ROOT") or _detect_repo_root()
    queue_dir = Path(root) / "audit" / ".queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    cwd = os.getcwd()
    entry = "dispatch-precheck"
    log_line = f"{ts} {cwd} {line} @ entry={entry}\n"
    log_file = queue_dir / f"{date.today():%Y-%m-%d}.log"
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(log_line)
    except OSError:
        pass  # silently swallow，与 guard.sh audit_log 行为一致
```

> entry 字段 `dispatch-precheck`（与 `pre-tool-use-guard` 区分）；`audit_flush.py` 的 `_REPO_ROOT` 检测路径已可识别（来源：.claude/hooks/pre-tool-use-guard.sh:36）。

### 2.6 顶层异常兜底骨架

```python
import sys
import json

def main() -> int:
    try:
        return _main_inner()
    except SystemExit:
        raise
    except Exception as e:  # 场景 10：任何未预期异常
        audit_log(f"FAIL_OPEN: unexpected | {type(e).__name__}:{str(e)[:200]}")
        return 0

if __name__ == "__main__":
    sys.exit(main())
```

`_main_inner()` 跑 §2.4 校验链；任何已知 fail-open 场景内部直接 `return 0`，未预期异常被顶层兜底。**禁止** 在 `_main_inner` 内 raise SystemExit 干扰主调度。

---

## 3. .dispatch-state.json + dispatch_state.py（对应 outline-design §6 待办 #4）

### 3.1 schema 字段表

`requirements/<id>/.dispatch-state.json` 字段（参照 tech-feasibility §2.3 草案，来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:165）：

| 字段 | 类型 | 必填 | 语义 | 示例 |
|---|---|---|---|---|
| `schema_version` | string | ✅ | 兼容窗口标识；初版 `"1.0"` | `"1.0"` |
| `req_id` | string | ✅ | 所属需求 ID（自检冗余；可被 path 推导但便于审计） | `"REQ-2026-008"` |
| `current_feature` | string \| null | ✅ | 派发中的 feature_id；空闲时显式 `null` | `"F-002"` |
| `acquired_at` | string (ISO8601) | 条件 ✅ | current_feature 非 null 时必填；时区 Asia/Shanghai | `"2026-05-06T10:30:00+08:00"` |
| `acquired_by_pid` | int | 条件 ✅ | current_feature 非 null 时必填；派发进程 PID（人工排查用） | `12345` |

**空闲态完整示例**：

```json
{
  "schema_version": "1.0",
  "req_id": "REQ-2026-008",
  "current_feature": null
}
```

**派发中态完整示例**：

```json
{
  "schema_version": "1.0",
  "req_id": "REQ-2026-008",
  "current_feature": "F-002",
  "acquired_at": "2026-05-06T10:30:00+08:00",
  "acquired_by_pid": 12345
}
```

### 3.2 公开 API：四个签名 + 异常契约

#### 3.2.1 设计动机：单锁 vs 多锁

dispatch_precheck.py 的 read + 业务校验段（B-1/B-2/B-3）+ write 必须在**同一把 LOCK_EX 锁**内完成（来源：requirements/REQ-2026-008/reviews/detail-design-001.json）round-001 major required_fix；避免 TOCTOU 漏洞。touches_guard.py 是只读路径，清理脚本/rollback 是只写路径——两类调用方**无 TOCTOU 风险**，独立锁即可。所以公开 API 分两层：

| 层 | 用途 | 锁次数 |
|---|---|---|
| L1 | `flock_state_file(req_dir)` 上下文管理器 | 单把锁；调用方在 with 块内手动 read/write |
| L2 | `read_state` / `write_state` / `clear_state` 简单函数 | 各取独立锁；只适合"单读"或"单写"场景 |

**强约束**（来源：requirements/REQ-2026-008/reviews/detail-design-001.json）：dispatch_precheck.py 必须走 L1 上下文管理器路径；L2 的 `read_state` + `write_state` 顺序调用会造成 TOCTOU 漏洞，禁止在新代码中出现。

#### 3.2.2 签名

```python
# scripts/lib/dispatch_state.py
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, TypedDict, Literal, Iterator

class DispatchState(TypedDict, total=False):
    schema_version: Literal["1.0"]
    req_id: str
    current_feature: Optional[str]
    acquired_at: str       # ISO8601 with offset
    acquired_by_pid: int

class StateFileHandle:
    """flock_state_file 上下文内暴露给调用方的句柄；read/write 不再取锁。"""
    def read(self) -> Optional[DispatchState]: ...
    def write(self, state: DispatchState) -> None: ...

@contextmanager
def flock_state_file(req_dir: Path) -> Iterator[StateFileHandle]:
    """L1 公开 API——LOCK_EX 5s timeout；with 块内 read/write 不再二次取锁。

    用法（dispatch_precheck.py）：
        with flock_state_file(req_dir) as fh:
            state = fh.read()              # 锁内读
            # 业务校验 status / depends_on / current_feature ...
            fh.write({"current_feature": fid, ...})   # 锁内写

    异常：
      - TimeoutError：5s 内未取到锁
      - ValueError：JSON 解析失败
      - OSError：磁盘 / 权限错误
    """

def read_state(req_dir: Path) -> Optional[DispatchState]:
    """L2 简单读——内部调 flock_state_file 取锁后读单次释放。

    适用：touches_guard.py（只读 current_feature，无后续写入）
    禁用：dispatch_precheck.py（必须用 L1，否则 TOCTOU）
    """

def write_state(req_dir: Path, state: DispatchState) -> None:
    """L2 简单写——内部调 flock_state_file 取锁后写单次释放。

    适用：单写场景（不基于读后状态做条件写）
    禁用：与 read_state 顺序调用（TOCTOU；改用 L1）
    """

def clear_state(req_dir: Path) -> None:
    """把 current_feature / acquired_at / acquired_by_pid 清成 None；保留 schema_version / req_id。

    - 等价于 write_state(req_dir, {"schema_version":"1.0","req_id":..,"current_feature":None})
    - 调用方：feature 完成（receipt 写完后清理脚本）+ /requirement:rollback
    - 单写无 TOCTOU 风险；用 L2 即可
    """
```

#### 异常契约

| 异常 | 抛出场景 | 调用方应对 |
|---|---|---|
| `TimeoutError` | LOCK_EX 5s 内未取到（极端死锁 / 异常进程未释放） | hook 层 fail-open exit 0 |
| `ValueError` | JSON 解析失败（手工破坏 / 半写文件） | hook 层 fail-open exit 0 |
| `OSError` | 磁盘满 / 权限拒绝 / fs unmount | hook 层 fail-open exit 0 |
| `AssertionError` | write_state 入参缺字段 | 调用方 bug；不应捕获，让其 crash 暴露问题（hook 层顶层 except Exception 兜底） |

### 3.3 实现要点（fcntl.flock + atomic rename + with）

参照 tech-feasibility §2.3 推荐方案的 `flock_state_file` 上下文管理器（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:182），detail-design 落地版本：

```python
import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, IO

LOCK_TIMEOUT_S = 5.0
POLL_INTERVAL_S = 0.05

class StateFileHandle:
    """flock_state_file 上下文内的句柄；read/write 在外层锁内运行，不再二次取锁。"""
    def __init__(self, path: Path, file_obj: IO):
        self._path = path
        self._f = file_obj  # 已持锁的 fd

    def read(self) -> Optional[DispatchState]:
        self._f.seek(0)
        text = self._f.read()
        if not text.strip():
            return None
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"dispatch-state must be object: {self._path}")
        return data  # type: ignore[return-value]

    def write(self, state: DispatchState) -> None:
        assert "schema_version" in state and state["schema_version"] == "1.0"
        assert "req_id" in state
        if state.get("current_feature") is not None:
            assert "acquired_at" in state and "acquired_by_pid" in state
        # atomic rename 写策略：write tmp + os.replace；锁保护元数据可见性
        tmp_path = self._path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, self._path)


@contextmanager
def flock_state_file(req_dir: Path) -> Iterator[StateFileHandle]:
    """L1 公开 API——LOCK_EX 5s timeout 上下文管理器。

    模式选择：始终用 'r+'。
      - 纯 'r' 模式不允许后续在同一 fd write，限制 read+write 复用
      - 'r+' 模式要求文件预先存在；下方"不存在则建空骨架"分支负责兜底
      - 即使调用方只 read（如 touches_guard.py via L2 read_state），也用 'r+' 简化路径
    """
    path = req_dir / ".dispatch-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # 'r+' 模式要求文件存在；首次访问建空骨架
        # 注意：这是建空 "{}"——调用方 read 后看到 empty dict 应转 None 处理
        path.write_text("{}", encoding="utf-8")
    f = path.open("r+", encoding="utf-8")
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() > deadline:
                f.close()
                raise TimeoutError(f"flock timeout {LOCK_TIMEOUT_S}s: {path}")
            time.sleep(POLL_INTERVAL_S)
    try:
        handle = StateFileHandle(path, f)
        yield handle
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


# ====== L2 简单读/写/清——内部基于 flock_state_file，单读或单写场景使用 ======

def read_state(req_dir: Path) -> Optional[DispatchState]:
    """单读；touches_guard.py 适用。dispatch_precheck.py **禁用**（TOCTOU）。"""
    state_path = req_dir / ".dispatch-state.json"
    if not state_path.exists():
        return None
    with flock_state_file(req_dir) as fh:
        data = fh.read()
    return data


def write_state(req_dir: Path, state: DispatchState) -> None:
    """单写；不基于读后状态做条件写时使用。与 read_state 顺序调用 = TOCTOU 漏洞。"""
    with flock_state_file(req_dir) as fh:
        fh.write(state)


def clear_state(req_dir: Path) -> None:
    """单写：保留 schema_version + req_id，清掉 current_feature 三件套。"""
    state_path = req_dir / ".dispatch-state.json"
    with flock_state_file(req_dir) as fh:
        cur = fh.read() or {"schema_version": "1.0", "req_id": _infer_req_id(req_dir)}
        cleared: DispatchState = {
            "schema_version": "1.0",
            "req_id": cur.get("req_id", _infer_req_id(req_dir)),
            "current_feature": None,
        }
        fh.write(cleared)


def _infer_req_id(req_dir: Path) -> str:
    """req_dir = requirements/REQ-2026-008 → "REQ-2026-008"。"""
    return req_dir.name
```

> **clear_state 用 L1 with 块**：避免内部走 `read_state + write_state` 顺序调用造成 TOCTOU——虽然 clear_state 单调用方场景少，但保持单锁原子是统一约定。

#### 实现要点逐条

1. **LOCK_EX + LOCK_NB + 轮询**：避免阻塞模式 `LOCK_EX` 死等；用 NB + 50ms 轮询 + 5s deadline 控制延迟。
2. **atomic rename**：`tmp_path` 写完后 `os.replace`——POSIX 保证 rename 是原子操作（同一 fs），杜绝读到半写 JSON。
3. **read 锁**：read_state 也取 LOCK_EX（不是 LOCK_SH）——简化锁模型，避免读写交错；read 路径短（毫秒级），不会成为瓶颈。
4. **schema_version 硬断言**：任何 v1.0 之外的 state 在 write 时 crash；read 时由调用方走兼容窗口（首版只支持 1.0）。
5. **fd 关闭顺序**：`finally LOCK_UN → finally close`——避免 close 时 fd 仍持锁导致 OS 资源回收延迟。
6. **req_id 自检**：write_state 不强制校验 req_id 与 path 一致（避免 detail-design 阶段反复修），但 read_state 可由调用方做断言。

### 3.4 调用方一览

| 调用方 | 文件 | 调用 | API 层 | 时机 |
|---|---|---|---|---|
| dispatch_precheck.py | `.claude/hooks/dispatch_precheck.py` | `flock_state_file` 上下文管理器（read+三校验+write 单锁内） | **L1 必选** | PreToolUse Agent 派发前置 |
| touches_guard.py | `.claude/hooks/touches_guard.py` | `read_state`（只读，无后续写入） | L2 简单读 | PreToolUse Edit/Write/MultiEdit 前 |
| receipt 完成清理脚本 | `scripts/lib/dispatch_state_cleanup.py` | `clear_state`（内部走 L1） | L2 简单清 | 主 Agent 解析 RECEIPT_WRITTEN 后 Bash 调用 |
| /requirement:rollback | `managing-requirement-lifecycle` Skill 内 | `clear_state` | L2 简单清 | rollback 命令执行末尾 |

> **dispatch_precheck.py 强制走 L1**——L2 的 `read_state + write_state` 顺序调用形成 TOCTOU 窗口（详见 §3.2.1 / §2.4 [8]）。命名沿用 `scripts/lib/check_*.py` 同级一致风格（来源：scripts/lib/check_meta.py:1）。CLI 形态：`python3 scripts/lib/dispatch_state_cleanup.py --req-dir requirements/<id>`，幂等执行（重复调用安全）。

### 3.5 单测覆盖（tests/lib/test_dispatch_state.py）

| 用例 ID | 场景 | 期望 |
|---|---|---|
| TL-001 | read_state 文件不存在 | 返回 None，不创建文件（注：flock_state_file 触发的空骨架 "{}" 在 read 时仍要返回 None） |
| TL-002 | read 到 JSON 非 object | 抛 ValueError |
| TL-003 | write 缺 schema_version | 抛 AssertionError |
| TL-004 | write current_feature=F-002 缺 acquired_at | 抛 AssertionError |
| TL-005 | write 完后 read 等价 | round-trip 一致 |
| TL-006 | 并发 2 个进程 write_state | 后写者要么成功要么 timeout，绝不交错半写 |
| TL-007 | clear_state 空闲态文件 | 保留 schema_version + req_id，current_feature=null |
| TL-008 | flock_state_file 锁泄漏路径（fd 异常关闭） | 下次取锁立刻成功 |
| TL-009 | **TOCTOU 回归**：进程 A 在 with 块内 read 后未 write 之前，进程 B 调 read_state 是否阻塞 5s timeout | B 必须 timeout（证明 A 的 with 锁未释放，B 无 TOCTOU 窗口可乘） |
| TL-010 | dispatch_precheck.py 模拟单 with 块内 read+三校验+write | 单原子动作；中途无锁释放点 |

> 并发测试用 multiprocessing 模拟；TL-006 + TL-009 + TL-010 是关键回归用例（D-005 #4 决议保障 + reviewer round-001 major TOCTOU 修复）。

---

## 4. 3 份 schema 的 schema_version + SUPPORTED_VERSIONS（对应 outline-design §6 待办 #6）

### 4.1 双层 schema_version 语义

本仓库现有 schema 文件（来源：context/team/engineering-spec/meta-schema.yaml:1）+ `review-schema.yaml`（来源：context/team/engineering-spec/review-schema.yaml）均**未引入 `schema_version` 字段**——靠 PR review + `修改原则: required_fields/enums/format 变更必须走 PR review`（来源：context/team/engineering-spec/meta-schema.yaml:8）保证兼容。本次 3 份新 schema 是仓库**首批**带版本演化机制的 schema 文件，需明确两层语义：

| 层 | 字段位置 | 标识 | 谁读 |
|---|---|---|---|
| L1 schema 文件自身 | `<schema-name>.yaml` 顶部 | schema 文件 layout 版本（YAML 结构演化） | check_*.py 启动时 assert `schema["schema_version"] == "1.0"` |
| L2 数据文件 | `receipt.json` / `features.json` / task frontmatter | 数据载荷版本（被校验对象的字段集合） | check_*.py 校验时 assert `data["schema_version"] in SUPPORTED_VERSIONS` |

**L1 / L2 同名同初值**（均 `"1.0"`），但**版本独立演化**——schema 文件结构稳定时数据载荷可独立升级；反之亦然。

### 4.2 SUPPORTED_VERSIONS 兼容窗口策略

`scripts/lib/check_<X>.py` 顶部声明（伪代码模板）：

```python
SCHEMA_PATH = REPO_ROOT / "context" / "team" / "engineering-spec" / "<X>-schema.yaml"
SUPPORTED_VERSIONS: frozenset[str] = frozenset({"1.0"})
"""数据载荷 schema_version 白名单。

升级策略：
  - 新增 minor（1.0 → 1.1）：仅追加可选字段时，旧版本仍 supported；
    集合更新为 {"1.0", "1.1"}，跨度至少一个 release cycle。
  - 破坏性升级（1.x → 2.0）：required 字段变更或 enum 收紧；
    集合替换为 {"1.x", "2.0"} 至少一个 release cycle，过期后剔除 1.x。
  - 校验逻辑：不在白名单 → fail，stderr 给出迁移脚本路径占位
    `scripts/lib/migrate_<X>_<from>_to_<to>.py`（路径不存在时 stderr 提示
    联系 maintainer，避免静默放行）。
"""
```

#### 校验时序（check_<X>.py 主入口）

```
入口
  ├─[1] 读 SCHEMA_PATH → assert schema["schema_version"] == "1.0"
  │      └─ 失败 → exit 2（schema 文件自身被破坏，不是用户问题）
  ├─[2] 读 data file (receipt.json / features.json / task frontmatter)
  ├─[3] data 顶部必须有 schema_version → 缺失：fail（required_fields 校验）
  ├─[4] data["schema_version"] ∈ SUPPORTED_VERSIONS → 否则 fail
  │      └─ stderr: "<file>: schema_version=<v> 不在 supported 集合 {...}；
  │                  迁移脚本：scripts/lib/migrate_<X>_<v>_to_<latest>.py"
  ├─[5] 走通用管道：_check_required_fields → _check_enums → _check_format → _check_conditional
  │      └─（参照 check_meta.py:230 既有 4 阶段管道）
  └─ exit 0/1（report.exit_code）
```

### 4.3 3 份 schema 的版本演化策略

| schema 文件 | 数据载荷 | 当前 SUPPORTED_VERSIONS | 演化触发 |
|---|---|---|---|
| receipt-schema.yaml | `tasks/<F-xxx>.receipt.json` | `{"1.0"}` | status 枚举变化 / conditional_required 变化 |
| features-schema.yaml | `artifacts/features.json` | `{"1.0"}` | status / complexity 枚举调整 / depends_on 语义变更 |
| task-frontmatter-schema.yaml | `tasks/<F-xxx>.md` frontmatter | `{"1.0"}` | required 字段增减（如新增 review_round 等） |

**升级 SOP**（写进各 schema 文件顶部注释）：
1. 在 schema 文件顶部 `schema_version` 字段升级（如 `"1.0"` → `"1.1"`）
2. `check_<X>.py` 的 `SUPPORTED_VERSIONS` 加入新版本（兼容期保留旧版本）
3. 若是破坏性升级，新增 `scripts/lib/migrate_<X>_<from>_to_<to>.py` 迁移脚本
4. 至少一个 release cycle 后再考虑剔除旧版本

### 4.4 schema_version 字段在 conditional_required 中的位置

参照 tech-feasibility §2.4 的 receipt-schema.yaml 草案（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:244），`schema_version` 列入 `required_fields` 顶层（与 status / feature_id / timestamp 同级），且：

```yaml
format:
  schema_version: '^\d+\.\d+$'    # major.minor 形式；不接受 '1' / '1.0.0' / '1.0-beta'
```

**禁止**用 `enum` 锁定具体取值（会让升级时 schema 文件本身要改两处）；改用 `format` regex + check_*.py 内部的 `SUPPORTED_VERSIONS` 双层校验。

### 4.5 单测覆盖（tests/lib/test_check_*.py 共用 fixtures）

| 用例 ID | 共用场景 | 期望 |
|---|---|---|
| TS-001 | data 缺 schema_version | exit 1，stderr 含 "schema_version 必填" |
| TS-002 | data["schema_version"] = "0.9"（不在 SUPPORTED） | exit 1，stderr 含迁移脚本路径占位 |
| TS-003 | data["schema_version"] = "1.0"（在 SUPPORTED） | 走后续校验 |
| TS-004 | schema 文件自身 schema_version ≠ "1.0" | exit 2（schema 损坏） |
| TS-005 | data["schema_version"] = "1.0.0"（多余 patch 段） | exit 1（format 校验拒绝） |

> TS-001~TS-005 是 check_receipt.py / check_features.py / check_task_frontmatter.py 共用的版本控制回归用例；具体 fixtures 由 task-planning 阶段拆 F-001/F-002/F-003 时落到 `tests/lib/fixtures/<X>/` 目录。

---

## 5. 4 个新 gate 的 applies_when 精确字段（对应 outline-design §6 待办 #8）

### 5.1 触发组矩阵（含字段值）

`scripts/gates/registry.yaml` 9 字段命名锁定（来源：scripts/gates/registry.yaml:7）；`applies_when` 5 子字段：`changed_files / target_phase / current_phase_in / transition / requires`（来源：scripts/gates/registry.yaml:25）。S9 校验要求 `requires` 每项以 `meta.` 开头（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:405），所以"运行时状态"过滤无法走 requires，必须放进 plugin precheck（与 REQ-2026-007 方案 B 一致）。

#### GATE-POST-DEV-RECEIPT

```yaml
- id: GATE-POST-DEV-RECEIPT
  plugin: post_dev_receipt
  severity: error
  triggers:
    - phase-transition
    - submit
  applies_when:
    changed_files: []           # 无 path 限定（features.json status 才是触发条件，但走 plugin precheck）
    target_phase: testing       # 仅 phase-transition development → testing 时命中
    current_phase_in:
      - development
    transition: development->testing
    requires: []                # 不依赖 meta.* 谓词
  dependencies: []
  side_effects: none
  failure_message: |
    {gate_id} 失败：{message}
    修复建议：{fix_hint}
  tests:
    fixtures: [pass, fail, skip]
```

**自然过滤原理**（V-07 D-006，来源：requirements/REQ-2026-008/plan.md:96）：historic completed REQ 在 ci 通道没有 phase-transition trigger（registry.yaml 该 gate 不在 ci 触发组），故**不会被 historic REQ 误命中**；submit trigger 仅活跃 REQ 才会用，本身就有"当前在做"语义。

#### GATE-TOUCHES-VIOLATION

与 POST-DEV-RECEIPT 同形（仅 plugin / failure_message 不同）：

```yaml
- id: GATE-TOUCHES-VIOLATION
  plugin: touches_violation
  severity: error
  triggers:
    - phase-transition
    - submit
  applies_when:
    changed_files: []
    target_phase: testing
    current_phase_in:
      - development
    transition: development->testing
    requires: []
  dependencies: []
  side_effects: none
  failure_message: |
    {gate_id} 失败：{message}
    修复建议：{fix_hint}
  tests:
    fixtures: [pass, fail, skip]
```

#### GATE-FEATURES-SCHEMA

```yaml
- id: GATE-FEATURES-SCHEMA
  plugin: features_schema
  severity: error
  triggers:
    - pre-commit
    - phase-transition
    - submit
    - ci
  applies_when:
    changed_files:
      - "requirements/*/artifacts/features.json"
    target_phase: null
    current_phase_in: []
    transition: null
    requires: []
  dependencies: []
  side_effects: none
  failure_message: |
    {gate_id} 失败：{message}
    修复建议：{fix_hint}
  tests:
    fixtures: [pass, fail, skip]
```

**自然过滤原理**：historic completed REQ 的 features.json 早已落定，不在本次 commit 的 changed_files 列表里 → ci 通道扫不到 → 自然不命中（V-07 D-006）。

#### GATE-TASK-FRONTMATTER

```yaml
- id: GATE-TASK-FRONTMATTER
  plugin: task_frontmatter
  severity: error
  triggers:
    - pre-commit
    - phase-transition
    - submit
    - ci
  applies_when:
    changed_files:
      - "requirements/*/artifacts/tasks/*.md"
    target_phase: null
    current_phase_in: []
    transition: null
    requires: []
  dependencies: []
  side_effects: none
  failure_message: |
    {gate_id} 失败：{message}
    修复建议：{fix_hint}
  tests:
    fixtures: [pass, fail, skip]
```

### 5.2 V-07 路径自然隔离三重保证（D-006 修订要点）

历史 completed REQ 在 ci 通道**绝对不能**因新 gate 而误 fail（V-07 验收，来源：requirements/REQ-2026-008/plan.md:96）。本次设计的三层保证：

| 保证 | 实现 | 验证 fixture |
|---|---|---|
| 1. trigger 自然过滤 | POST-DEV-RECEIPT / TOUCHES-VIOLATION 不在 ci triggers 列表 | tests/gates/test_post_dev_receipt.py 的 skip fixture：trigger=ci 时 plugin 在 precheck 里 Skip |
| 2. changed_files glob 自然过滤 | FEATURES-SCHEMA / TASK-FRONTMATTER 限定 path glob，historic REQ 文件 commit 时不在 diff 里 | tests/gates/test_features_schema.py 的 skip fixture：simulated diff 不含 features.json |
| 3. legacy-bypass tag 显式不加 | 4 个新 gate 都 **不加** `tags: [legacy-bypass]`（与 GATE-TRACEABILITY 区分，来源：scripts/gates/registry.yaml:191） | registry.yaml schema 校验：tags 字段不存在不会触发 legacy 短路（来源：scripts/gates/run.py:343） |

> **危险红线**（防误改 D-005 #2 决议）：未来若有人想给新 4 个 gate 加 `legacy-bypass` tag 让历史 REQ "跳过" → 错误的修复方式。正确思路是检查为什么该 gate 在 historic REQ 上命中（多半是 changed_files 写错了）。

### 5.3 plugin precheck 设计要点

`scripts/gates/plugins/<X>.py` 的 `precheck(ctx)` 方法（参照 outline-design §3.5，来源：requirements/REQ-2026-008/artifacts/outline-design.md:373）：

```python
class PostDevReceiptGate(BaseGate):
    plugin_name = "post_dev_receipt"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        # 第一层：trigger 白名单（registry triggers 已保证，但 plugin 内做防御性确认）
        if ctx.trigger not in ("phase-transition", "submit"):
            return Skip("trigger 不命中")

        # 第二层：req_dir 必须存在（独立模式下 ctx.req_dir 可能为 None）
        if not ctx.req_dir:
            return Skip("无 req_dir")

        # 第三层：features.json 必须存在（早期需求未到 task-planning 阶段时正常缺失）
        if not (ctx.req_dir / "artifacts/features.json").exists():
            return Skip("features.json 不存在")

        # 第四层：phase-transition 时仅 development → testing 触发
        if ctx.trigger == "phase-transition" and ctx.target_phase != "testing":
            return Skip("非 development→testing 切换")

        return None  # 不 skip，进入 execute

    def execute(self, ctx: GateContext) -> GateResult:
        # （见 outline-design §3.5 / tech-feasibility §2.6 推荐方案）
        ...
```

#### precheck 与 applies_when 的分工

| 检查项 | 放哪里 | 原因 |
|---|---|---|
| trigger ∈ {phase-transition, submit} | **registry.yaml triggers** | 静态字段；run.py 注册期就过滤 |
| target_phase == "testing" | **registry.yaml applies_when.target_phase** | 静态匹配；run.py 调度期判定 |
| features.json 存在 | **plugin precheck** | 运行时谓词；S9 不允许 applies_when.requires 出现 path |
| feature.status == "done" 是否所有 | **plugin execute** | 业务逻辑，不属于过滤 |

### 5.4 单测覆盖（tests/gates/test_<gate>.py）

S8 校验要求每个 plugin 的 tests.fixtures 含 `[pass, fail, skip]`（来源：scripts/gates/registry.yaml:38）。本次 4 plugin 各 3 fixture：

| plugin | pass fixture | fail fixture | skip fixture |
|---|---|---|---|
| post_dev_receipt | features.json 列出 F-001 done + receipt.json 含 status=DONE | F-001 done 但 receipt 缺失 | trigger=ci（registry triggers 不含 ci，run.py 直接 skip） |
| touches_violation | 所有 receipt.touches_violations=[] | 任一 receipt 含非空 violations | 同上 |
| features_schema | features.json schema_version=1.0 + 字段全合规 | features.json 缺 required 字段 | 当前 commit 不包含 features.json 改动 |
| task_frontmatter | tasks/F-001.md frontmatter 完整 | tasks/F-001.md 缺 touches 字段（V-03 关键场景） | 当前 commit 不包含 tasks/*.md 改动 |

### 5.5 与 GATE-TRACEABILITY 的边界

GATE-TRACEABILITY 持 `legacy-bypass` tag（来源：scripts/gates/registry.yaml:191），run.py:343 实现 `is_legacy_meta and "legacy-bypass" in tags → 跳过`。本次 4 个 gate **不复用此机制**——historic REQ 在 ci 通道不命中是因 trigger / changed_files 自然隔离，不依赖 legacy 短路（D-006 V-07 修订要点）。

未来若 traceability gate 升级也走自然隔离（即剔除 legacy-bypass tag），可一并简化；当前保留 GATE-TRACEABILITY 的 legacy-bypass 是因其 trigger 含 phase-transition / submit，且 legacy=true 的 REQ 没有完整追溯链——属于另一类问题，不在本需求范围。

---

## 6. meta-schema.yaml legacy 字段说明 patch（对应 outline-design §6 待办 #12）

### 6.1 改动定位

`context/team/engineering-spec/meta-schema.yaml:133` 现有 legacy 字段定义（来源：context/team/engineering-spec/meta-schema.yaml:133）：

```yaml
optional_fields:
  - reviews
  - archived_at   # 归档时间戳；仅 phase=completed 时允许写入
  - legacy   # PR4 新增；boolean，true 表示豁免 reviewer-verdict 校验（仅 check_reviews 跳过）

# ---------- legacy 字段（v2 新增，PR4 引入） ----------
# 用途：标记历史需求豁免 reviewer-verdict 体系的 review 校验
#   - 仅影响 scripts/lib/check_reviews.py 的入口短路
#   - 不影响 check_meta / check_index / check_sourcing
#   - 适用场景：completed 阶段的历史 REQ（PR3 之前产出，meta.yaml 无 reviews 字段）
# 语义：
#   - true：跳过所有 R001~R007 校验
#   - false / 缺省：正常校验
# 引入新字段后切忌泛滥使用；新增 REQ 必须走结构化 reviewer 通道。
```

### 6.2 精确 patch

在第 138 行 `不影响 check_meta / check_index / check_sourcing` 后追加一行（注意保持注释缩进 `#   - `）：

```diff
 # 用途：标记历史需求豁免 reviewer-verdict 体系的 review 校验
 #   - 仅影响 scripts/lib/check_reviews.py 的入口短路
 #   - 不影响 check_meta / check_index / check_sourcing
+#   - 不豁免派发链强制结构 4 gate（GATE-POST-DEV-RECEIPT / GATE-TOUCHES-VIOLATION /
+#     GATE-FEATURES-SCHEMA / GATE-TASK-FRONTMATTER）：D-005 #2 决议——
+#     historic completed REQ 由 trigger / changed_files 路径自然隔离，
+#     不依赖 legacy 短路（D-006 V-07 修订；详见 requirements/REQ-2026-008/artifacts/detailed-design.md §5.2）
 #   - 适用场景：completed 阶段的历史 REQ（PR3 之前产出，meta.yaml 无 reviews 字段）
```

### 6.3 不改动 enum / required / format

D-005 #2 决议（来源：requirements/REQ-2026-008/plan.md:83）只影响**注释语义**，不改 schema 结构：

- `optional_fields` 列表保持现样（不动）
- 不新增 enum / format / conditional_required（4 个新 gate 由 registry.yaml 自身的 trigger / changed_files 过滤，**不读取 meta.legacy 字段**）

> 这是关键设计——避免让 4 个新 gate 与 meta.legacy 字段产生新耦合。所有"为什么 historic REQ 不命中"的逻辑都封装在 registry.yaml 的 applies_when 与 plugin precheck 内（§5.2 三重保证）。

### 6.4 单测覆盖（tests/gates/test_meta_schema.py）

无新增——本 patch 仅改注释，不影响 check_meta.py 行为；既有 fixture 集合保留。

### 6.5 关联文件同步

| 文件 | 是否同步改 | 原因 |
|---|---|---|
| `scripts/lib/check_reviews.py` | ❌ 否 | 注释 patch 不影响 R001~R007 实现 |
| `scripts/lib/check_meta.py` | ❌ 否 | 不读 legacy 字段含义注释 |
| `.claude/skills/managing-requirement-lifecycle/reference/phase-rules.md` | ❌ 否 | legacy 字段语义未变 |
| `requirements/*/meta.yaml`（历史 REQ） | ❌ 否 | 历史 legacy=true 字段值不变 |

---

## 7. CI quality-check.yml pytest 扩展 patch（对应 outline-design §6 待办 #13）

### 7.1 现状

`.github/workflows/quality-check.yml:47-48`（来源：.github/workflows/quality-check.yml:48）：

```yaml
      # F-005：单元测试门禁；确保 gates/ 所有 plugin 测试全绿
      - name: pytest
        run: pytest tests/gates/ -v
```

仅覆盖 `tests/gates/`，新增的 `tests/lib/` / `tests/hooks/`（bats 单独覆盖）/ `tests/integration/` / `tests/lifecycle/` / `tests/skills/` 不在 pytest 通道内——V-02 / V-07 / V-08 测试用例落地后将无 CI 兜底。

### 7.2 精确 patch

```diff
       # F-005：单元测试门禁；确保 gates/ 所有 plugin 测试全绿
       - name: pytest
-        run: pytest tests/gates/ -v
+        run: pytest tests/ --ignore=tests/benchmarks/ -v
```

`--ignore=tests/benchmarks/` 排除性能基线测试（如有）；其他子目录全覆盖。

### 7.3 实证基线

`pytest tests/ --ignore=tests/benchmarks/` 已实证 **603 passed / 8 skipped / 36.04s**（来源：requirements/REQ-2026-008/notes.md:21），CI 扩展**零修复成本**——本次 PR 直接合入。

### 7.4 提交时机（与本 PR 同包）

**必须**与本需求其他改动同 PR 提交，不拆独立 PR：

- 若先合入 CI patch 再合本需求 → CI 触发跑全量 tests/，但本需求新增的 `tests/lib/test_dispatch_state.py` / `tests/gates/test_*.py` 等还未存在 → CI fail（"no tests collected"）
- 若先合本需求再补 CI patch → 中间窗口期 CI 不跑新单测 → V-02 / V-07 / V-08 验收点形同虚设
- **同 PR 提交**：单测文件与 workflow patch 一起入 commit；CI 在 PR push 时一次性跑全集

### 7.5 单测覆盖（无 quality-check.yml 自身的单测）

CI workflow 自身无单测；改动验证三段（**已验证基线**：603 passed / 8 skipped，来源：requirements/REQ-2026-008/notes.md:21）：

- **本地预跑**：commit 前在 feature 分支跑 `pytest tests/ --ignore=tests/benchmarks/ -v`，期望 0 fail（与基线对齐）
- **PR 流水线触发**：push 后观察 quality-check workflow，pytest step 期望 pass
- **回滚预案**：若 CI fail 且无法快速修复，回退本 patch（保留 `tests/gates/` 覆盖），其他改动不受影响

### 7.6 关联 step 不动

`bats tests/hooks/`（line 68）/ `ruff check`（line 73）/ unified gate runner（line 44）保持不变；本 patch 仅改 pytest 一行。

---

## 8. 派发模板 frontmatter `touches` 字段 + task-context-builder 同步（对应 outline-design §6 待办 #7）

### 8.1 feature-task.md.tmpl 改动

`.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl:1-10` 现 frontmatter 8 字段（来源：.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl:1）：

```yaml
---
feature_id: __FEATURE_ID__
title: __TITLE__
status: pending
complexity: __COMPLEXITY__
depends_on: __DEPENDS_ON__
created_at: __ISO8601__
updated_at: __ISO8601__
review_report: null
---
```

#### 精确 patch

在 `depends_on` 后追加 `touches: __TOUCHES__`：

```diff
 ---
 feature_id: __FEATURE_ID__
 title: __TITLE__
 status: pending
 complexity: __COMPLEXITY__
 depends_on: __DEPENDS_ON__
+touches: __TOUCHES__
 created_at: __ISO8601__
 updated_at: __ISO8601__
 review_report: null
 ---
```

> `__TOUCHES__` 占位渲染为 YAML 数组（如 `[".claude/hooks/dispatch_precheck.py", "scripts/lib/dispatch_state.py"]`），空数组写 `[]`。**不允许写 `null`**——schema 把 touches 列为 required（detail-design §4 / outline-design §3.1，来源：requirements/REQ-2026-008/artifacts/outline-design.md:312）。

#### 模板正文段同步

template line 32-34（来源：.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl:32）：

```
## 触及范围

（从 features.json 的 `touches` 复制，作为 subagent 开发边界约束）
```

改为：

```
## 触及范围

（与 frontmatter `touches` 字段一致，作为 subagent 开发边界约束。
frontmatter 是机器读取入口（touches_guard.py / GATE-TOUCHES-VIOLATION），本段是人读快速参考。
两处不一致时以 frontmatter 为准。）
```

### 8.2 task-context-builder Skill 填充逻辑同步

`.claude/skills/task-context-builder/SKILL.md:20`（来源：.claude/skills/task-context-builder/SKILL.md:20）已要求"基本信息"段透出 4 项机读字段（含 touches），但**只透出到上下文文档**——本次需要扩展：

#### 改动要点

| 行为 | 现状 | 改动后 |
|---|---|---|
| 读 features.json | ✅ 已有 | 不变 |
| 透出 touches 到上下文 §"基本信息" | ✅ 已有 | 不变 |
| 渲染 task .md frontmatter `touches` 字段 | ❌ 缺（模板原本无此字段） | ✅ 新增：从 features.json `touches` 数组复制到 frontmatter，YAML 数组格式 |
| 派发 prompt 首部加 `feature_id: F-xxx` 独占首行 | ❌ 缺（模板首行是 "你是..."） | ✅ 新增：D-005 #3 + D-007 强化 |

#### subagent-dispatch.md 模板首部精确 patch

`.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md:50`（来源：.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md:50）现状：

```
你是 feat/req-<REQ-ID> 分支上的 feature 实现者。当前任务 F-xxx · <title>。
```

改为：

```
feature_id: F-xxx
你是 feat/req-<REQ-ID> 分支上的 feature 实现者。当前任务 F-xxx · <title>。
```

> **硬约束**（D-007 来源：requirements/REQ-2026-008/plan.md:95）：`feature_id: F-xxx` 必须**独占首行**且行首无任何前缀（不能是"# feature_id: ..."、不能是"DISPATCH: feature_id: ..."），否则 dispatch_precheck.py 的 `^feature_id:\s*(F-\d{3})\s*$` regex（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:104）解析失败 → fail-open 放行 = 校验形同虚设。

#### 派发模板 §1 触及范围段同步

subagent-dispatch.md line 58-59（来源：.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md:58）现状：

```
1. 按上方上下文实现 F-xxx，严格限制在以下触及范围内：
   <粘贴 touches 字段，如为空则写"未声明，保守处理：仅改与本 feature 直接相关的文件，新增文件优先"）
```

改为：

```
1. 按上方上下文实现 F-xxx，严格限制在以下触及范围内（与 task .md frontmatter touches 一致）：
   <粘贴 touches 字段；若为空数组 `[]` 写"未声明 touches，保守处理：仅改与本 feature 直接相关的文件，新增文件优先；任何越界写入会被 touches_guard.py 软记入 receipt"）
```

### 8.3 task-context-builder 渲染流程

```
入口：feature_id ∈ features.json
  ├─[1] 读 features.json → 取 features[fid]
  ├─[2] 读 detail-design.md / outline-design.md 相关段
  ├─[3] 渲染 task .md
  │      ├─ 模板：feature-task.md.tmpl
  │      ├─ 替换 __FEATURE_ID__ / __TITLE__ / __COMPLEXITY__ / __DEPENDS_ON__
  │      ├─ 替换 __TOUCHES__ ← yaml.safe_dump(features[fid]["touches"], default_flow_style=True)
  │      │      └─ 空数组 → "[]"；非空 → "[\".claude/hooks/x.py\", \"scripts/lib/y.py\"]"
  │      └─ 替换 __ISO8601__ ← TZ=Asia/Shanghai now
  ├─[4] 渲染派发 prompt（subagent-dispatch.md 模板）
  │      ├─ 首行强制 `feature_id: <fid>`
  │      ├─ 第二行起接原模板 "你是 feat/req-..."
  │      └─ §"你的任务" 第 1 项粘贴 touches 数组
  └─ 输出：task .md path + prompt string
```

### 8.4 单测覆盖

| 用例 ID | 路径 | 场景 | 期望 |
|---|---|---|---|
| TT-001 | `tests/skills/test_task_context_builder_render.py` | features[fid].touches=[".claude/hooks/x.py"] | task.md frontmatter `touches: ['.claude/hooks/x.py']` 等价 YAML |
| TT-002 | 同上 | features[fid].touches=[] | task.md frontmatter `touches: []`；prompt 第 1 项写 "未声明 touches..." |
| TT-003 | 同上 | features[fid] 缺 touches 字段（旧 features.json） | task-context-builder 抛 ValueError，要求迁移；不静默写 null |
| TT-004 | 同上 | 派发 prompt 首行 | 严格等于 `feature_id: <fid>`，无前缀无后缀 |
| TT-005 | 同上 | dispatch_precheck.py regex 模拟解析 prompt 输出 | 解析成功，feature_id 命中 |

> TT-005 是 cross-skill 回归用例：用 dispatch_precheck.py 的 `parse_feature_id` 函数做 prompt 输出的反向验证。

### 8.5 关联文件改动一览

| 文件 | 改动类型 | 改动要点 |
|---|---|---|
| `.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl` | 修改 | frontmatter +`touches: __TOUCHES__`；正文段更新引导语 |
| `.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md` | 修改 | prompt 模板首部 +`feature_id: F-xxx`；§"你的任务" 第 1 项更新引导语 |
| `.claude/skills/task-context-builder/SKILL.md` | 修改 | 流程段补 `__TOUCHES__` 渲染逻辑 + prompt 首行强制 |
| `tests/skills/test_task_context_builder_render.py` | 新增 | TT-001 ~ TT-005 五用例 |

---

## 9. render-docs.py 重生成 gate-checklist.md（对应 outline-design §6 待办 #9）

### 9.1 现状

`scripts/gates/migration/render-docs.py:1`（来源：scripts/gates/migration/render-docs.py:1）已具备双模式：

```
python3 scripts/gates/migration/render-docs.py          # 渲染并写入目标文件
python3 scripts/gates/migration/render-docs.py --check  # CI 强校验：diff 非空 exit 1
```

输出：`.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md`（来源：scripts/gates/migration/render-docs.py:9）。

CI 已在 quality-check workflow 集成 `--check` 链路：unified gate runner 走 ci trigger（来源：.github/workflows/quality-check.yml:44）；ruff lint step 紧随其后（来源：.github/workflows/quality-check.yml:73）。漏跑直接红 PR。

### 9.2 PR 提交前必跑步骤

本需求 4 个新 gate 注册到 registry.yaml 后，**强制执行**：

```bash
# 在 feature 分支、registry.yaml 已 add 4 gate 之后
python3 scripts/gates/migration/render-docs.py
git add .claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md
git commit --amend --no-edit  # 或新 commit，按团队习惯
```

> **严禁** 仅 commit registry.yaml 而漏 gate-checklist.md——`--check` 模式会让 CI 红。

### 9.3 提交前清单 PR 模板补丁

`/requirement:submit` PR 模板（详见 `managing-requirement-lifecycle/reference/submit-rules.md` [待补充：本次不改 submit 模板，仅 PR 描述 checklist 补一行]）的"自检清单"段建议手工补一项：

```markdown
- [ ] 4 个新 gate 已 render：`python3 scripts/gates/migration/render-docs.py` + diff 落到 gate-checklist.md
```

> 该补丁是建议性的（用户 PR 描述模板），不强制改 submit-rules.md。强制保证由 CI `--check` 兜底。

### 9.4 单测覆盖

`render-docs.py` 自身已有单测覆盖（来源待确认 [待补充：本次不新增 render-docs.py 测试用例，仅在 PR 自检清单中加 render 步骤]）。本次新增 4 gate 仅改 registry.yaml 数据；不改 render-docs.py 代码逻辑。

### 9.5 失败回滚

若 PR push 后 CI `--check` fail：

1. 本地跑 `python3 scripts/gates/migration/render-docs.py`
2. 检查 diff（必然只动 gate-checklist.md）
3. `git add` + `git commit --amend --no-edit` + force push（**仅在自己的 feature 分支**，与团队 git 规范一致）
4. 重新触发 CI

如果 diff 异常大（比如改动了非 4 gate 的部分），停下来确认 registry.yaml 是否被误改了其他字段——这是 schema 漂移信号，**不要直接 push**。

---

## 99. 后续待办进度（接 outline-design §6）

| # | 待办 | 状态 |
|---|---|---|
| 1 | settings.json + guard.sh 精确 patch | ✅ 本次（§1） |
| 2 | dispatch_precheck.py stdin JSON 实采样 | ✅ 已闭环（D-007） |
| 3 | dispatch_precheck.py fail-open 行为契约 | ✅ 本次（§2） |
| 4 | .dispatch-state.json schema + 三函数签名 | ✅ 本次（§3） |
| 5 | touches glob 语义 | 已收口（outline §3.3） |
| 6 | 3 份 schema 的 schema_version + SUPPORTED_VERSIONS | ✅ 本次（§4） |
| 7 | F-007 派发模板 frontmatter `touches` + 首行 `feature_id` | ✅ 本次（§8） |
| 8 | 4 个新 gate 的 applies_when 字段 | ✅ 本次（§5） |
| 9 | render-docs.py 重生成 gate-checklist.md | ✅ 本次（§9） |
| 10 | F-002/F-003 是否合并 check_schema.py 复评 | ⏳ 后续（可选） |
| 11 | F-001 回归基线 pytest 快照 | 已闭环 |
| 12 | meta-schema.yaml legacy 字段说明 patch | ✅ 本次（§6） |
| 13 | CI quality-check.yml pytest 扩展 patch | ✅ 本次（§7） |

**所有必决项（#1 ~ #9 / #11 ~ #13）已落地**。剩余 #10（B 案合并复评）为可选项，依赖 task-planning 阶段产出 features.json 后再评——届时若 F-002 / F-003 实现重复 > 60% 触发升级 A 案。
