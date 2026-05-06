---
id: REQ-2026-008
title: 派发链强制结构化升级 · 技术可行性评估
created_at: 2026-05-06T10:30:00+08:00
phase: tech-research
refs-design: true
---

# REQ-2026-008 · 技术可行性评估

## 1. 引言与评估方法

本文评估 REQ-2026-008「派发链强制结构化升级」的实施可行性，按 plan.md 的 5 项风险与 D-005 的 5 项澄清决议为评估单元，逐条复核技术细节。

**可行性结论：high**。无 blocker 级阻碍；所有依赖（PreToolUse hook 通道、gate registry、check 脚本范式、fcntl 标准库、pytest CI 基建）已在仓库内运行，无须引入新工具链或新依赖。3 项中等风险均集中在 detail-design 阶段可关单的具体接口契约层面（settings.json matcher 改法 / V-07 验收措辞 / quality-check.yml pytest 覆盖范围）。

**评估方法**：
- 读取需求文档（来源：requirements/REQ-2026-008/artifacts/requirement.md:1）与计划（来源：requirements/REQ-2026-008/plan.md:1）
- 读取现有 hook 入口：`.claude/settings.json`、`.claude/hooks/pre-tool-use-guard.sh`
- 读取 gate registry / runner / plugin 入口：`scripts/gates/registry.yaml`、`scripts/gates/registry.py`、`scripts/gates/run.py`、`scripts/gates/plugins/`
- 读取 check 脚本参照：`scripts/lib/check_meta.py`、`scripts/lib/check_reviews.py`
- 读取 schema 参照：`context/team/engineering-spec/meta-schema.yaml`、`context/team/engineering-spec/review-schema.yaml`
- 读取 Skill 收口范围：`.claude/skills/feature-lifecycle-manager/SKILL.md`、`.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md`、`.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl`
- 读取 CI 基建：`.github/workflows/quality-check.yml`
- 扫描历史需求 phase 状态（D-005 #5 复核）
- 类比工作量参照：`requirements/REQ-2026-006/artifacts/tech-feasibility.md`、`requirements/REQ-2026-007/artifacts/tech-feasibility.md`

---

## 2. 重点技术评估

### 2.1 PreToolUse hook 拦截 Task / Edit/Write/MultiEdit 的可行性

#### 现状

`.claude/settings.json` 当前 PreToolUse 仅注册一条匹配，matcher 为 `"Bash|Edit|Write|MultiEdit"`（来源：.claude/settings.json:29），统一调度 `pre-tool-use-guard.sh`。`Task` 工具**不在 matcher 范围**内，主 Agent 调 Task tool 派发 subagent 时不会触发任何 hook。

`pre-tool-use-guard.sh` 是单点 dispatcher：
- 顶部 `set -u` + `trap 'exit 0' ERR`（来源：.claude/hooks/pre-tool-use-guard.sh:6）保证任意 jq / 脚本失败 → ERR 触发 → 全局 exit 0（fail-open，绝不阻塞用户）
- `exec 3>&2; exec 2>>/tmp/guard-error.log`（来源：.claude/hooks/pre-tool-use-guard.sh:7）将原 stderr 复制到 fd 3，BLOCKED 消息走 fd 3 回 Claude Code Agent，自身 stderr 进 /tmp 隔离
- main 函数 88 行起 case 分发：`Edit|Write|MultiEdit → check_branch_protect + check_review_path` / `Bash → check_bash_writes_review`（来源：.claude/hooks/pre-tool-use-guard.sh:88）
- 阻断走 `cat >&3 <<EOF ... EOF; exit 2`（来源：.claude/hooks/pre-tool-use-guard.sh:106）

#### 不确定点与结论

Claude Code 的 PreToolUse hook 协议规定：matcher 是 `|` 分隔的 tool 名 regex，stdin 传 `{tool_name, tool_input}` JSON，hook 退出码 2 等于"拒绝该 tool 调用并把 stderr 内容回传给 Agent"。本仓库已多次实操验证（Edit/Write 拒绝写 reviews/*.json，Bash 拒绝绕过 save-review.sh）。`Task` 工具同属 PreToolUse 触发链，在 Claude Code 标准协议下应同等支持，但仓库内**尚无 Task tool 拦截先例**，`tool_input.prompt` 字段名需在 detail-design 首日实跑确认。

#### 推荐方案

**方案 A（推荐）：扩展现有 guard.sh case 分支**

1. 修改 `.claude/settings.json:29`：matcher 由 `"Bash|Edit|Write|MultiEdit"` 改为 `"Bash|Edit|Write|MultiEdit|Task"`
2. `pre-tool-use-guard.sh` 的 case 分支增加 `Task) check_dispatch_precheck "$input" ;;`（input 是已读完的 stdin JSON）
3. `check_dispatch_precheck` 内调 `python3 .claude/hooks/dispatch_precheck.py`，传 stdin JSON；Python 侧解析 prompt + 校验状态 + 写 .dispatch-state.json
4. `Edit|Write|MultiEdit` 分支追加 `check_touches_guard "$file_path"`，调 `python3 .claude/hooks/touches_guard.py`

**为什么不直接在 settings.json 新加一条 matcher**：

新加 `{"matcher": "Task|Edit|Write|MultiEdit", "hooks": [...]}` 会让 Edit/Write/MultiEdit 走两次 hook 链（每条匹配命中独立调度），引入冗余执行 + 时序耦合风险。复用现有 guard.sh 的 case dispatch 是最小变更。

#### 备选

**方案 B：独立 PreToolUse 条目**——单独为 Task 注册一条 matcher。在主对话 hook 数低时实现简单，但会与现有 case dispatch 产生维护双轨；不推荐。

#### 风险

| 风险 | 概率 | 影响 |
|---|---|---|
| Task tool 的 stdin JSON schema 与 Edit/Write 不一致（如 `tool_input.prompt` 字段名不存在）| 中 | 高（dispatch_precheck 解析失败 → ERR trap → exit 0 → 派发不被校验，但不会误伤）|
| guard.sh case fall-through 默认 exit 0 → 新 hook 误装在错位置后静默跳过 | 中 | 中（V-01 沙盒 e2e 必须命中阻断路径才能验通过）|

---

### 2.2 dispatch_precheck.py 的 feature_id 解析双保险（D-005 #3）

#### 现状

D-005 #3 决议（来源：requirements/REQ-2026-008/plan.md:84）：派发 prompt 模板首部硬编码独立行 `feature_id: F-xxx`（hook 优先读首行字段）；缺失时 fallback 正则 `F-\d{3}` 匹配第一个 group。

派发模板当前位置：`.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md:49-93`，其中 49-50 行为模板起始：

```
你是 feat/req-<REQ-ID> 分支上的 feature 实现者。当前任务 F-xxx · <title>。
```

模板首部**无显式 `feature_id:` 字段行**；F-xxx 仅出现在自然语言中（"当前任务 F-xxx · <title>"），且后续 `## 上下文` 段、`## 你的任务` 段、`## 回执状态契约` 段都可能多次提到 F-xxx（如 commit 示例 `feat(F-001): ...`、回执示例）。直接用 `re.search(r"F-\d{3}", prompt)` 匹配第一个 group 在当前模板下能命中标题中的 F-xxx，但若主 Agent 自由调整模板（比如先写 "依赖 F-001、F-002 完成后做 F-003" 这类自然语言），正则会误匹配 F-001。

#### 不确定点与结论

**双保险解析逻辑**：

```python
import re

def parse_feature_id(prompt: str) -> str | None:
    """主路径：首部前 N 行内的 'feature_id: F-xxx' 显式字段；fallback：前 N 行正则。

    fail-open 协议：返回 None 时调用方应 exit 0 放行（不强制识别失败的派发）。
    """
    HEAD_LINES = 5  # 仅在首部 5 行内匹配，避免后文示例污染
    head = "\n".join(prompt.splitlines()[:HEAD_LINES])

    # 主路径：显式 'feature_id: F-xxx' 字段（YAML-like）
    m = re.search(r"^feature_id:\s*(F-\d{3})\s*$", head, re.MULTILINE)
    if m:
        return m.group(1)

    # fallback：首部 5 行内的第一个 F-xxx
    m = re.search(r"\bF-\d{3}\b", head)
    return m.group(0) if m else None
```

**配套**：`subagent-dispatch.md` 模板首部需补两行：

```
feature_id: F-xxx
你是 feat/req-<REQ-ID> 分支上的 feature 实现者。当前任务 F-xxx · <title>。
```

`templates/feature-task.md.tmpl` 同步加 `feature_id: F-xxx` 字段（hook 与 task 文件解耦，task.md frontmatter 自身有 feature_id 字段，是另一份独立来源）。

#### 推荐方案

主路径首部前 5 行的 YAML-like 显式字段；fallback 限定首部 5 行的正则。**fail-open 是底线**：解析失败时 `dispatch_precheck.py` 写 audit 日志后 `exit 0`，不让"模板偶然失修"导致正常派发被拒（与现有 guard.sh 的 fail-open 哲学一致，来源：.claude/hooks/pre-tool-use-guard.sh:6）。

#### 备选

- 改 Task tool prompt 为结构化 YAML+Markdown 双段格式：太重，与 Claude Code Skill 现有自由文本派发风格不兼容
- 强制硬错误（exit 2）当解析失败：违背 fail-open 原则，会因模板小修就阻塞所有派发

#### 风险

| 风险 | 概率 | 影响 |
|---|---|---|
| 主 Agent 自由调整 prompt 模板首部，导致 `feature_id:` 字段缺失或位置漂移 | 中 | 中（fallback 兜底 + fail-open，最坏静默放行该次派发）|
| 一次派发同时改两个 feature（极端违规场景，违背保守档串行约束）| 低 | 低（只校验首个 feature_id，违规仍会被 dispatch_precheck 的"无其他 in-progress"校验阻断）|

---

### 2.3 `.dispatch-state.json` + `fcntl.flock` 并发模型（D-005 #4）

#### 现状

需求中 4 处读写 `.dispatch-state.json`（来源：requirements/REQ-2026-008/artifacts/requirement.md:43）：

1. `dispatch_precheck.py` 派发前置：取锁 → 读（校验无其他 in-progress）→ 写当前 feature_id → 释放
2. `touches_guard.py` Edit/Write 前：取锁 → 读 current_feature → 释放（不写）
3. receipt.json 写完后清理（subagent 无法触发 PostToolUse；由 主 Agent 解析 RECEIPT_WRITTEN 后调清理脚本）：取锁 → 清 current_feature → 释放
4. `/requirement:rollback` 命令：取锁 → 清 → 释放

#### 不确定点与结论

`fcntl.flock(fd, LOCK_EX)` 是 POSIX advisory lock（macOS / Linux 均支持），Python 标准库 `fcntl` 直接提供。本仓库 Python 3.11，无兼容性问题。

**关键点**：advisory lock 不阻止"绕过协议直接 open+write"的进程；但 hook 链上所有写入方都是我方代码（dispatch_precheck / touches_guard / 清理脚本 / rollback hook），只要四方统一走 lock 工具函数，无第三方污染风险。

**5s timeout 合理性**：dispatch_precheck 的写操作在毫秒级完成；touches_guard 仅读；锁等待 5s 足够覆盖任何正常并发；超过 5s 几乎肯定是死锁或异常进程未释放。

**锁泄漏路径**：
- subagent 进程崩溃（或被 Ctrl-C 中断）后未释放：`fcntl.flock` 在 fd 关闭时自动释放，进程退出会触发 OS 级 fd 回收 → 锁自动释放，不会泄漏
- Python 异常未走 finally：用 `with`-statement 上下文管理器封装 `flock_state_file()`，保证异常路径也能释放

**state.json schema 草案**：

```yaml
schema_version: "1.0"
req_id: REQ-2026-008
current_feature: F-002       # 派发中的 feature_id；空闲时为 null
acquired_at: "2026-05-06 10:30:00"   # 取锁时间，便于排查长时间未释放
acquired_by_pid: 12345        # 派发进程 PID（人工排查用，不参与逻辑）
```

锁工具函数实现伪代码（`scripts/lib/dispatch_state.py` 新增）：

```python
import fcntl, json, time
from contextlib import contextmanager
from pathlib import Path

LOCK_TIMEOUT_S = 5

@contextmanager
def flock_state_file(path: Path, mode: str = "r+"):
    """以 LOCK_EX 取独占锁，5s timeout，with 块结束自动释放。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}", encoding="utf-8")
    f = path.open(mode, encoding="utf-8")
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() > deadline:
                f.close()
                raise TimeoutError(f"flock timeout: {path}")
            time.sleep(0.05)
    try:
        yield f
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()
```

#### 推荐方案

LOCK_EX 独占锁 + 5s timeout + `with`-statement 自动释放 + 统一工具函数。`scripts/lib/dispatch_state.py` 单一入口对外暴露 `read_state()` / `write_state(...)` / `clear_state(...)`，禁止直接 open。

#### 备选

- `os.O_CREAT|os.O_EXCL` 原子创建 lockfile：实现稍复杂、清理路径多分支；不推荐
- `filelock` 第三方库：仓库目前避免新增运行依赖（`.github/workflows/quality-check.yml` 仅 install pyyaml/ruamel.yaml/pathspec/ruff/pytest）

#### 风险

| 风险 | 概率 | 影响 |
|---|---|---|
| /tmp 或仓库根挂载点 fcntl 不可用（极端场景，如某些 NFS 卷）| 极低 | 中（macOS / 标准 Linux 全 OK）|
| 锁泄漏（subagent 异常退出未释放）| 低 | 低（fd 关闭自动释放，OS 兜底）|

---

### 2.4 receipt-schema.yaml + check_receipt.py（D-002 / V-02）

#### 现状

参照 schema：
- `context/team/engineering-spec/meta-schema.yaml`（来源：context/team/engineering-spec/meta-schema.yaml:1）：required_fields 按"流程组 / 语义组"分类、enums 白名单、format 正则、conditional_required 阶段触发规则
- `context/team/engineering-spec/review-schema.yaml`（来源：requirements/REQ-2026-008/artifacts/requirement.md:28）

参照 check 脚本：`scripts/lib/check_meta.py`（280 行，来源：scripts/lib/check_meta.py:1）走 `_check_required_fields → _check_enums → _check_format → _check_conditional` 标准管道（来源：scripts/lib/check_meta.py:230），统一通过 `common.Report` + `Severity` + `paint` 工具输出，退出码 0/1/2 由 `report.exit_code(strict=...)` 决定。

#### 推荐方案

**`receipt-schema.yaml` 字段清单**（参照 D-002 决议、V-02 验收点）：

```yaml
# 受益参照：context/team/engineering-spec/meta-schema.yaml
schema_version: "1.0"

required_fields:
  - schema_version       # 必须等于 "1.0"，新版本兼容窗口策略见下
  - status               # 枚举：DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED
  - feature_id           # 格式：F-\d{3}
  - timestamp            # datetime（YYYY-MM-DD HH:MM:SS）

enums:
  status:
    - DONE
    - DONE_WITH_CONCERNS
    - NEEDS_CONTEXT
    - BLOCKED

format:
  feature_id: '^F-\d{3}$'
  schema_version: '^\d+\.\d+$'
  timestamp: datetime
  commit_sha: '^[0-9a-f]{7,40}$'   # 7~40 位短/长 SHA 均接受

conditional_required:
  # status = DONE / DONE_WITH_CONCERNS：必须有 commit_sha 与 files_changed
  - when:
      status_in: [DONE, DONE_WITH_CONCERNS]
    non_empty:
      - commit_sha
      - files_changed
      - test_summary

  - when:
      status: BLOCKED
    non_empty:
      - block_reason

  - when:
      status: NEEDS_CONTEXT
    non_empty:
      - missing_context

optional_fields:
  - touches_violations   # list[str]，越界文件路径；空数组合法
  - concerns             # list[str]，DONE_WITH_CONCERNS 时建议非空
```

**`scripts/lib/check_receipt.py`**（伪代码，参照 check_meta.py 形态）：

```python
"""receipt.json 校验入口

唯一事实源：context/team/engineering-spec/receipt-schema.yaml

用法：
  python3 scripts/lib/check_receipt.py <path> [--strict]

退出码见 common.py。
"""
SCHEMA_PATH = REPO_ROOT / "context" / "team" / "engineering-spec" / "receipt-schema.yaml"

def check_one(receipt_path: Path, schema: dict, report: Report) -> None:
    receipt = json.loads(receipt_path.read_text())
    _check_required_fields(receipt, schema, report, str(receipt_path))
    _check_enums(receipt, schema, report, str(receipt_path))
    _check_format(receipt, schema, report, str(receipt_path))
    _check_conditional(receipt, schema, report, str(receipt_path))
    _check_schema_version(receipt, schema, report, str(receipt_path))
```

主 Agent 取 status 字段 jq 命令（V-02 描述）：
```bash
bash scripts/lib/check_receipt.py "$path"   # 退出码 0 = 合法
status=$(jq -r '.status' "$path")
case "$status" in
  DONE|DONE_WITH_CONCERNS) ... ;;
  NEEDS_CONTEXT) ... ;;
  BLOCKED) ... ;;
esac
```

**schema 演化兼容窗口**（plan.md 风险 3 缓解）：`schema_version` 字段为强制；`check_receipt.py` 维护 `SUPPORTED_VERSIONS = {"1.0"}`；后续升级（如 1.1）保留对 1.0 的兼容期至少一个 release cycle；超出兼容窗口时给 fail 但 fail message 指向迁移脚本。

#### 备选

- JSON Schema (Draft 7+) 替代 YAML 自定义：库依赖（jsonschema），与现有 meta/review schema 风格不一致，不推荐
- 把 receipt-schema 嵌进 meta-schema：扩张 meta-schema 职责，违反单一事实源原则

#### 风险

| 风险 | 概率 | 影响 |
|---|---|---|
| schema 演化导致老 receipt 解析失败 | 中 | 中（schema_version + 兼容窗口可缓解；plan.md 风险 3）|
| 主 Agent jq 失败（缺 jq 命令）| 低 | 低（仓库已强依赖 jq，guard.sh 已用，来源：.claude/hooks/pre-tool-use-guard.sh:84-86）|

---

### 2.5 touches 越界双层拦截（D-003 / V-03）

#### 现状

D-003 决议（来源：requirements/REQ-2026-008/plan.md:67）：开发期 `touches_guard.py` 软拦截放行但写 receipt.touches_violations[]；phase-transition 由新 `GATE-TOUCHES-VIOLATION` 硬挡。

`templates/feature-task.md.tmpl`（来源：requirements/REQ-2026-008/artifacts/requirement.md:138）已存在；frontmatter 应含 `touches: [glob1, glob2, ...]` 字段（具体格式 detail-design 阶段确认）。

#### 推荐方案

**touches_guard.py 实现**（PreToolUse on Edit/Write/MultiEdit 触发）：

1. 解析 stdin JSON：`tool_input.file_path`
2. 读 `.dispatch-state.json` 拿 `current_feature`（不持锁，触发频率高，read-only 用 LOCK_SH 共享锁；若没有 current_feature → 非派发场景，exit 0）
3. 读 `requirements/<id>/artifacts/tasks/<F-xxx>.md` frontmatter → `touches: [...]`
4. 路径标准化：`Path(file_path).resolve().relative_to(REPO_ROOT)`（捕获绝对路径 / `..` / 软链接）
5. 用 `pathspec.GitIgnoreSpec.from_lines(touches)` 做 glob 匹配（仓库已用 pathspec，来源：.github/workflows/quality-check.yml install 列表）
6. 若不命中 → 追加到 `tasks/<F-xxx>.receipt.json.touches_violations[]`（receipt 不存在则创建空骨架）
7. **不阻断**（exit 0），只留痕

**关键边界**：
- 触发 hook 时 receipt.json 通常不存在（subagent 还在写）→ 创建骨架仅含 `feature_id`、`schema_version`、`touches_violations`；subagent 写完整 receipt 时按合并策略追加自身字段（schema 设计：subagent Write 不带 violations 字段时保留已存在 violations，避免覆盖）
- `MultiEdit` 的 file_path 与 Edit 一致；`Write` 同
- 路径未在 REPO_ROOT 之下（极端绕过）：标准化失败 → fail-open exit 0，写 audit "skip: path outside repo"

**GATE-TOUCHES-VIOLATION plugin 草案**（phase-transition 触发）：

```python
class TouchesViolationGate(BaseGate):
    """扫所有 receipt.json，任一 touches_violations 非空 → fail。"""
    plugin_name = "touches_violation"

    def precheck(self, ctx): ...   # ctx.trigger != "phase-transition" → Skip

    def execute(self, ctx) -> GateResult:
        violations = []
        for receipt in (ctx.req_dir / "artifacts/tasks").glob("*.receipt.json"):
            data = json.loads(receipt.read_text())
            for v in data.get("touches_violations", []):
                violations.append(f"{data['feature_id']}: {v}")
        if violations:
            return GateResult.fail(
                message=f"touches 越界 {len(violations)} 项",
                details=violations,
            )
        return GateResult.pass_()
```

#### 备选

- `.gitignore`-style negation pattern：pathspec 原生支持 `!exclude`；当前需求未明确使用
- 阻断式硬拦截：D-003 已明确不采用（误伤多）

#### 风险

| 风险 | 概率 | 影响 |
|---|---|---|
| pathspec glob 与用户预期不一致（如 `src/auth/*` 是否匹配 `src/auth/sub/file.ts`）| 中 | 中（detail-design 阶段需固化 glob 语义并文档化；建议用 `src/auth/**` 表示递归）|
| receipt.json 并发写入冲突（touches_guard 写骨架 + subagent 写完整 receipt 同时发生）| 低 | 中（用 atomic rename 写入 + 追加策略缓解；detail-design 给细节）|

---

### 2.6 4 个新 gate 注册到 registry.yaml（D-004 / V-04 / V-05）

#### 现状

`scripts/gates/registry.yaml` 已有 13 个 gate（来源：scripts/gates/registry.yaml:1）。9 字段命名锁定（id / plugin / severity / triggers / applies_when / dependencies / side_effects / failure_message / tests），来源：scripts/gates/registry.yaml:6-8。

S9 校验：`applies_when.requires` 每项必须以 `meta.` 开头（来源：scripts/gates/registry.py:221）。所以"基于运行时状态"的过滤无法走 `requires` 字段，必须放进 plugin precheck（与 REQ-2026-007 的方案 B 一致）。

`legacy-bypass` tag：仅 GATE-TRACEABILITY 持有（来源：scripts/gates/registry.yaml:191）。`run.py:343` 实现：`is_legacy_meta and "legacy-bypass" in tags → 跳过`（来源：scripts/gates/run.py:343）。**新 4 个 gate 不加此 tag**（D-005 #2 决议）。

`tags: [review-verdict]`：另一类 tag，只影响 escape_hatches 短路（来源：scripts/gates/registry.yaml:163）。新 4 个 gate 不属于 review-verdict 类，不加此 tag。

#### 推荐方案

**4 个 gate 的 registry.yaml 条目**（trigger 矩阵）：

| gate id | plugin | severity | triggers | side_effects |
|---|---|---|---|---|
| GATE-POST-DEV-RECEIPT | post_dev_receipt | error | phase-transition / submit | none |
| GATE-TOUCHES-VIOLATION | touches_violation | error | phase-transition / submit | none |
| GATE-FEATURES-SCHEMA | features_schema | error | pre-commit / phase-transition / submit / ci | none |
| GATE-TASK-FRONTMATTER | task_frontmatter | error | pre-commit / phase-transition / submit / ci | none |

**applies_when**：
- POST-DEV-RECEIPT：`current_phase_in: [development, testing]` + `transition: development->testing` 限定（不影响 definition / tech-research / outline-design / detail-design / task-planning 切换）
- TOUCHES-VIOLATION：同上
- FEATURES-SCHEMA：`changed_files: ["requirements/*/artifacts/features.json"]`
- TASK-FRONTMATTER：`changed_files: ["requirements/*/artifacts/tasks/*.md"]`

**plugin 类骨架**（参照 `scripts/gates/plugins/meta_schema.py` 现有形态）：

```python
class PostDevReceiptGate(BaseGate):
    plugin_name = "post_dev_receipt"

    def precheck(self, ctx) -> Optional[Skip]:
        if ctx.trigger not in ("phase-transition", "submit"):
            return Skip(...)
        if not ctx.req_dir or not (ctx.req_dir / "artifacts/features.json").exists():
            return Skip("无 features.json，跳过")
        return None

    def execute(self, ctx) -> GateResult:
        features = json.loads((ctx.req_dir / "artifacts/features.json").read_text())
        missing = []
        for f in features.get("features", []):
            if f.get("status") != "done":
                continue
            receipt = ctx.req_dir / f"artifacts/tasks/{f['id']}.receipt.json"
            if not receipt.exists():
                missing.append(f"{f['id']}: missing receipt.json")
                continue
            data = json.loads(receipt.read_text())
            if data.get("status") not in ("DONE", "DONE_WITH_CONCERNS"):
                missing.append(f"{f['id']}: receipt.status={data.get('status')!r}")
        if missing:
            return GateResult.fail(message=f"{len(missing)} feature 缺/异常 receipt", details=missing)
        return GateResult.pass_()
```

**tests.fixtures**（S8 校验要求 fixtures 含 pass/fail/skip）：每个 plugin 的 `tests/gates/test_<plugin_name>.py` 必须提供 3 fixture（来源：scripts/gates/registry.yaml:12）。

#### 备选

- 把 4 个 gate 合并为单一 `dispatch_chain` plugin：违反单一职责，难单测；不推荐

#### 风险

| 风险 | 概率 | 影响 |
|---|---|---|
| applies_when.requires 误用为运行时谓词（如 "!receipt_exists"）| 低 | 高（S9 校验拒绝加载，部署即报错）|
| side_effects 误标 write_state（无对应 rollback）| 低 | 低（S7 校验拒绝加载）|

---

### 2.7 V-07 历史 in-flight 兼容（D-005 #5 + 措辞修正）

#### 现状

V-07 验收措辞（来源：requirements/REQ-2026-008/artifacts/requirement.md:124）：

> 跑 `bash scripts/gates/run.py --trigger=ci --req=REQ-2026-001` 等历史已 completed 需求；exit code 不变；新 4 个 gate 在 legacy=true 时短路返回 pass

**问题**：D-005 #2 明确决议"新 4 个 gate 不纳入 legacy 豁免"（来源：requirements/REQ-2026-008/plan.md:84），但 V-07 描述"legacy=true 时短路返回 pass"——**两处自相矛盾**。

**实际兼容路径**（D-005 #5 已扫描，来源：requirements/REQ-2026-008/process.txt:4）：除 REQ-2026-008 自身外，REQ-2026-001/002/003/005/006/007 phase 全部 completed。CI trigger 跑历史 REQ 时：
- GATE-FEATURES-SCHEMA：仅当 `requirements/REQ-2026-001/artifacts/features.json` 在 changed_files 命中时才参与，CI 默认 changed_files 为空（非 pre-commit）→ 不触发
- GATE-TASK-FRONTMATTER：同理 changed_files 路径为 `tasks/*.md`，CI 不触发
- GATE-POST-DEV-RECEIPT：trigger 为 phase-transition / submit，**不在 ci 组**；不触发
- GATE-TOUCHES-VIOLATION：trigger 同上；不触发

**结论**：历史 completed 需求在 CI 通道上**天然不被触发**新 4 个 gate，依赖的不是 legacy 短路，而是 trigger 与 changed_files 的自然路径隔离。

扫描复核（2026-05-06）：
```
requirements/REQ-2026-001/meta.yaml: phase: completed
requirements/REQ-2026-002/meta.yaml: phase: completed
requirements/REQ-2026-003/meta.yaml: phase: completed
requirements/REQ-2026-005/meta.yaml: phase: completed
requirements/REQ-2026-006/meta.yaml: phase: completed
requirements/REQ-2026-007/meta.yaml: phase: completed
requirements/REQ-2026-008/meta.yaml: phase: tech-research
```

#### 推荐方案

**[需用户复评]** 在 detail-design 阶段把 V-07 措辞修订为：

> V-07 回归：跑 `bash scripts/gates/run.py --trigger=ci --req=REQ-2026-001` 等历史 completed 需求；exit code 不变。新 4 个 gate 因 trigger / changed_files / target_phase 等 applies_when 自然过滤，不在 ci 通道触发；不依赖 legacy 短路逻辑。

修订 requirement.md 第 124 行同步 plan.md D-005 #2 决议。

#### 备选

- 改 D-005 #2 决议（让新 gate 加 `legacy-bypass` tag）：违反"机器强制结构化是核心目标，不开后门"原则；不推荐

#### 风险

| 风险 | 概率 | 影响 |
|---|---|---|
| 测试验收 V-07 用例描述与实现不一致，导致 reviewer 反复对账 | 高 | 低（detail-design 阶段修订 V-07 措辞即可）|

---

### 2.8 测试落位与 CI 覆盖（D-005 #1）

#### 现状

`tests/{agents,commands,gates,hooks,integration,lib,lifecycle,skills,benchmarks}` 目录均存在（来源：requirements/REQ-2026-008/artifacts/requirement.md:140）。`pyproject.toml` 配 pytest。`.github/workflows/quality-check.yml` 当前 step：
- `python scripts/gates/run.py --trigger=ci --strict`（gate runner）
- `pytest tests/gates/ -v`（来源：.github/workflows/quality-check.yml:48）—— **仅覆盖 tests/gates/**
- `bats tests/hooks/`（来源：.github/workflows/quality-check.yml:62）—— 覆盖 hook bats 测试
- `ruff check scripts/ --select=F`
- `python3 scripts/gates/migration/render-docs.py --check`（gate-checklist 一致性）

#### 不确定点与结论

V-01 ~ V-08 测试落位：

| 验收点 | 测试目录 | 测试形态 | CI 覆盖 |
|---|---|---|---|
| V-01 dispatch_precheck 拦截 | `tests/hooks/` | bats（端到端 hook 协议）| ✅ |
| V-02 receipt schema 校验 | `tests/lib/` | pytest | ❌ **不在当前 CI 范围** |
| V-03 touches_guard 软拦截 | `tests/hooks/` + `tests/gates/` | bats（hook 端） + pytest（gate 端） | 部分 |
| V-04 GATE-POST-DEV-RECEIPT | `tests/gates/` | pytest | ✅ |
| V-05 GATE-FEATURES-SCHEMA / TASK-FRONTMATTER | `tests/gates/` | pytest | ✅ |
| V-06 dispatch_precheck 并发拦截 | `tests/hooks/` | bats | ✅ |
| V-07 历史 REQ 回归 | `tests/integration/` 或 `tests/lifecycle/` | pytest | ❌ **不在当前 CI 范围** |
| V-08 自举 phase-transition | `tests/integration/` | pytest | ❌ **不在当前 CI 范围** |

**关键缺口**：CI 当前不跑 `tests/lib/` `tests/integration/` `tests/lifecycle/`。V-02 / V-07 / V-08 测试编写后必须扩展 CI 覆盖，否则单测虽存在但**不构成强制墙**。

#### 推荐方案

**`.github/workflows/quality-check.yml` pytest step 修订**：

```yaml
- name: pytest
  run: pytest tests/gates/ tests/lib/ tests/integration/ tests/lifecycle/ -v
```

或更彻底（推荐）：

```yaml
- name: pytest
  run: pytest tests/ -v --ignore=tests/benchmarks/
```

**注**：`tests/benchmarks/` 是性能基准目录，不应在每次 CI 跑（耗时长）；其他目录全覆盖。

修订必须列入本次 PR（V-09 文档收口同 PR），否则 V-02 / V-07 / V-08 形同虚设（来源：requirements/REQ-2026-008/artifacts/requirement.md:159）。

#### 备选

- 拆为独立 PR：违反"分两批 PR 留中间不一致状态"硬约束（关键决策记录"迭代节奏"，来源：requirements/REQ-2026-008/artifacts/requirement.md:159）

#### 风险

| 风险 | 概率 | 影响 |
|---|---|---|
| 扩展后 CI 时长翻倍 | 中 | 低（pytest 总用例数 ~50，目前 gates/ 已 ~20，整体仍 < 1 分钟）|
| 现有 tests/lib/ tests/integration/ 测试有 fail 残留（被 CI 隐藏多月）| 中 | 中（detail-design 阶段先全量 pytest 一次，记录 baseline）|

---

### 2.9 Skill 文档与派发 prompt 模板收口（V-09）

#### 现状

`.claude/skills/feature-lifecycle-manager/SKILL.md`：73 行，含"硬约束"段（来源：requirements/REQ-2026-008/artifacts/requirement.md:16）。

`.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md`：110 行，结构为：
- 「派发前置校验」段：行 13 起（来源：.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md:13）—— 当前为"AI 自觉读 task 文件 + 校验依赖"；hook 上线后此段需精简为"hook 已自动校验，stderr 提示阻断时按提示修复"
- 「派发 Prompt 模板」段：行 40 起（来源：.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md:40）—— 模板首部需补 `feature_id: F-xxx` 显式行
- 「红线」段：行 104 起（来源：.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md:104）—— "禁止改动触及范围之外的文件"由 touches_guard + GATE-TOUCHES-VIOLATION 双层执行；需标注"由 hook/gate 拦截"

`.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl`：存在（来源：.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl）；需检查 frontmatter 是否含 `feature_id` `touches` `status` `depends_on` 字段。

`.claude/skills/managing-requirement-lifecycle/SKILL.md`：现有"硬约束"段反复警告"读清单自答"——本次新增 4 个 gate 后该段需补一条"由 GATE-POST-DEV-RECEIPT / TOUCHES-VIOLATION / FEATURES-SCHEMA / TASK-FRONTMATTER 自动兜底"。

`.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md`：由 `scripts/gates/migration/render-docs.py` 自动生成（来源：.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md:1）；新增 4 gate 后必须 `make gates-render`（或直接跑 `render-docs.py`）重生成；CI 有 `--check` 模式硬校验是否同步（来源：.github/workflows/quality-check.yml:74）。

`context/team/engineering-spec/meta-schema.yaml` 第 135 行起的 `legacy` 字段说明需补一行"不豁免 GATE-POST-DEV-RECEIPT / TOUCHES-VIOLATION / FEATURES-SCHEMA / TASK-FRONTMATTER"（D-005 #2 附带影响，来源：requirements/REQ-2026-008/plan.md:88）。

#### 推荐方案

V-09 的文档收口任务清单（按 feature 拆解到 F-008，见 §4 工作量）：

1. `subagent-dispatch.md` 改：派发前置校验段精简（指引看 stderr）+ 模板首部补 `feature_id: F-xxx` + 红线段加 hook/gate 拦截标注
2. `feature-lifecycle-manager/SKILL.md` 改：硬约束段加"由 hook/gate 拦截，违规会 exit 2"标注
3. `managing-requirement-lifecycle/SKILL.md` 改：新 4 gate 说明
4. `feature-task.md.tmpl` 改：frontmatter 加 `feature_id: F-xxx` 字段（detail-design 阶段确认是否还需加 `touches` `depends_on` 字段，按现有 template 推测应已具备）
5. `meta-schema.yaml` 改：legacy 字段说明补一行
6. `gate-checklist.md` 自动重生成（`scripts/gates/migration/render-docs.py`）

#### 备选

- 不收口文档，仅靠 hook/gate 拦截：违反"文档即记忆"原则（来源：context/team/engineering-spec/design-guidance/context-engineering.md:9）；对人类协作者不友好

#### 风险

| 风险 | 概率 | 影响 |
|---|---|---|
| `gate-checklist.md` 未重新生成导致 CI 报红 | 中 | 低（CI 强校验，PR 立即可见，本地 `make gates-render` 一行解决）|
| 模板首部补 `feature_id:` 后破坏现有派发 prompt 兼容（已有需求的 task.md 不含此字段）| 低 | 低（task.md frontmatter 与派发 prompt 是两份独立来源；现有 completed 需求不会再派发）|

---

## 3. 风险矩阵

| 风险 | 来源 | 概率 | 影响 | 缓解策略 | detail-design 待办 |
|---|---|---|---|---|---|
| R1: dispatch_precheck.py 从 Task prompt 解析 feature_id 不 100% 鲁棒 | requirements/REQ-2026-008/plan.md:38 | 中 | 中 | 双保险：首部 `feature_id:` 显式字段优先 + 5 行内正则 fallback；fail-open（解析失败 exit 0） | 模板首部补字段；fail-open 行为写入接口契约 |
| R2: touches_guard.py 依赖 `.dispatch-state.json` 标记 | requirements/REQ-2026-008/plan.md:39 | 中 | 中 | dispatch_precheck 派发时写；receipt 完成时清；rollback 命令清；并发用 fcntl.flock | state.json schema 草案；锁工具函数 `scripts/lib/dispatch_state.py` 接口确定 |
| R3: receipt schema 后续演化导致老 receipt 不兼容 | requirements/REQ-2026-008/plan.md:40 | 中 | 中 | schema_version 强制字段；check_receipt.py 维护 SUPPORTED_VERSIONS；兼容窗口至少一个 release cycle | 兼容窗口策略文档化；迁移脚本占位 |
| R4: 历史 in-flight 需求未补 receipt 触发 GATE-POST-DEV-RECEIPT | requirements/REQ-2026-008/plan.md:41 | 低 | 低 | D-005 #5 已扫描确认无活跃 in-flight；新 gate 依赖 trigger / changed_files 自然路径隔离，非 legacy 短路；V-07 措辞需修订对齐 | 修订 V-07 措辞（§2.7） |
| R5: hook 链路加长影响交互响应 | requirements/REQ-2026-008/plan.md:42 | 低 | 低 | dispatch_precheck / touches_guard 纯 Python 文件读 + flock，毫秒级；无网络 IO | hyperfine 基准对比 hook 加链前后 |
| R6 (新增): settings.json matcher 漏加 Task | §2.1 | 中 | 高 | settings.json:29 改 `"Bash\|Edit\|Write\|MultiEdit\|Task"`；guard.sh case 加 Task 分支 | 给出 settings.json + guard.sh 精确改动 patch |
| R7 (新增): CI quality-check.yml 不跑 tests/lib/ 等目录 | §2.8 | 高 | 中 | pytest step 改为 `pytest tests/gates/ tests/lib/ tests/integration/ tests/lifecycle/ -v`；本次 PR 同步修订 | 提交 PR 同包含此改动 |
| R8 (新增): V-07 验收措辞与 D-005 #2 决议矛盾 | §2.7 | 高 | 低 | detail-design 阶段修订 V-07 文本（"legacy=true 短路" → "trigger / changed_files 自然路径隔离"）| 一行文本修订 |

---

## 4. 工作量估算

类比参照：REQ-2026-006（门禁系统 A+B 重构）≈ 5.9 人天（来源：requirements/REQ-2026-006/artifacts/tech-feasibility.md:1）；REQ-2026-007（submit Codex review-loop + archive）≈ 7.0 人天（来源：requirements/REQ-2026-007/artifacts/tech-feasibility.md:284）。本需求功能点比 REQ-2026-007 多（2 hook + 3 schema + 3 check 脚本 + 4 gate plugin + 文档收口 + 单测套件），整体复杂度高 30%~40%。

### F-001：receipt-schema.yaml + check_receipt.py

| 子任务 | 改动量 | dev | test |
|---|---|---|---|
| `context/team/engineering-spec/receipt-schema.yaml` 新建 | ~60 行 | 0.2 | - |
| `scripts/lib/check_receipt.py` 新建（参照 check_meta.py） | ~200 行 | 0.5 | - |
| `tests/lib/test_check_receipt.py` 新建（pass/fail/边界）| ~150 行 | - | 0.5 |
| **小计** | ~410 行 | **0.7** | **0.5** |

### F-002：features-schema.yaml + check_features.py + GATE-FEATURES-SCHEMA

| 子任务 | 改动量 | dev | test |
|---|---|---|---|
| `features-schema.yaml` 新建（features.json 字段约束）| ~80 行 | 0.2 | - |
| `scripts/lib/check_features.py` 新建 | ~180 行 | 0.4 | - |
| `scripts/gates/plugins/features_schema.py` 新建 | ~80 行 | 0.2 | - |
| `registry.yaml` 注册 GATE-FEATURES-SCHEMA | ~25 行 | 0.1 | - |
| `tests/lib/test_check_features.py` + `tests/gates/test_features_schema.py` | ~200 行 | - | 0.6 |
| **小计** | ~565 行 | **0.9** | **0.6** |

### F-003：task-frontmatter-schema.yaml + check_task_frontmatter.py + GATE-TASK-FRONTMATTER

| 子任务 | 改动量 | dev | test |
|---|---|---|---|
| `task-frontmatter-schema.yaml` 新建（status / depends_on / touches / feature_id 等）| ~70 行 | 0.2 | - |
| `scripts/lib/check_task_frontmatter.py` 新建 | ~150 行 | 0.4 | - |
| `scripts/gates/plugins/task_frontmatter.py` 新建 | ~80 行 | 0.2 | - |
| `registry.yaml` 注册 GATE-TASK-FRONTMATTER | ~25 行 | 0.1 | - |
| `tests/lib/test_check_task_frontmatter.py` + `tests/gates/test_task_frontmatter.py` | ~180 行 | - | 0.5 |
| **小计** | ~505 行 | **0.9** | **0.5** |

### F-004：dispatch_precheck.py + GATE-POST-DEV-RECEIPT + 锁工具

| 子任务 | 改动量 | dev | test |
|---|---|---|---|
| `scripts/lib/dispatch_state.py` 锁工具（flock_state_file / read / write / clear）| ~120 行 | 0.4 | - |
| `.claude/hooks/dispatch_precheck.py` 新建（Task prompt 解析 + 三重校验 + 状态写入）| ~180 行 | 0.6 | - |
| `pre-tool-use-guard.sh` 加 Task case 分支 | ~15 行 | 0.1 | - |
| `.claude/settings.json` matcher 改 `Bash\|Edit\|Write\|MultiEdit\|Task` | 1 行 | 0.05 | - |
| `scripts/gates/plugins/post_dev_receipt.py` 新建 | ~80 行 | 0.2 | - |
| `registry.yaml` 注册 GATE-POST-DEV-RECEIPT | ~25 行 | 0.1 | - |
| `tests/hooks/test_dispatch_precheck.bats` + `tests/lib/test_dispatch_state.py` + `tests/gates/test_post_dev_receipt.py` | ~280 行 | - | 0.9 |
| **小计** | ~700 行 | **1.45** | **0.9** |

### F-005：touches_guard.py + GATE-TOUCHES-VIOLATION

| 子任务 | 改动量 | dev | test |
|---|---|---|---|
| `.claude/hooks/touches_guard.py` 新建（path 标准化 + glob 匹配 + receipt 追加）| ~150 行 | 0.5 | - |
| `pre-tool-use-guard.sh` 在 Edit/Write/MultiEdit 分支追加调度 | ~10 行 | 0.05 | - |
| `scripts/gates/plugins/touches_violation.py` 新建 | ~80 行 | 0.2 | - |
| `registry.yaml` 注册 GATE-TOUCHES-VIOLATION | ~25 行 | 0.1 | - |
| `tests/hooks/test_touches_guard.bats` + `tests/gates/test_touches_violation.py` | ~220 行 | - | 0.6 |
| **小计** | ~485 行 | **0.85** | **0.6** |

### F-006：CI quality-check.yml 扩展 pytest 覆盖

| 子任务 | 改动量 | dev | test |
|---|---|---|---|
| `.github/workflows/quality-check.yml` pytest step 改 `pytest tests/gates/ tests/lib/ tests/integration/ tests/lifecycle/ -v` | 1 行 | 0.05 | - |
| 修复 / 标记 现有 tests/lib/ tests/integration/ tests/lifecycle/ 残留失败用例 | 视情况 | 0.5 | - |
| **小计** | - | **0.55** | **0** |

### F-007：派发模板与 Skill 文档收口（V-09 文档侧）

| 子任务 | 改动量 | dev | test |
|---|---|---|---|
| `subagent-dispatch.md` 改（前置校验段精简 + 模板首部补 feature_id + 红线段加 hook 标注）| ~50 行 | 0.3 | - |
| `feature-lifecycle-manager/SKILL.md` 硬约束段加 hook/gate 拦截标注 | ~20 行 | 0.1 | - |
| `managing-requirement-lifecycle/SKILL.md` 加新 4 gate 说明 | ~20 行 | 0.1 | - |
| `templates/feature-task.md.tmpl` 加 `feature_id` 字段（如缺）| ~5 行 | 0.05 | - |
| `meta-schema.yaml` legacy 字段说明补一行 | ~3 行 | 0.05 | - |
| `gate-checklist.md` 重生成（`scripts/gates/migration/render-docs.py`）| 自动 | 0.05 | - |
| **小计** | ~100 行 | **0.65** | **0** |

### F-008：沙盒 e2e + 自举回归（V-01~V-08 全跑）

| 子任务 | 改动量 | dev | test |
|---|---|---|---|
| 沙盒需求 `REQ-2099-008` 创建 + V-01~V-06 e2e 用例 | - | 0.3 | 0.6 |
| V-07 历史 REQ 回归（REQ-2026-001..007 跑 ci trigger）| - | 0.1 | 0.3 |
| V-08 自举（REQ-2026-008 develop → testing 自身切换）| - | - | 0.3 |
| V-07 措辞修订 requirement.md（一行）| 1 行 | 0.05 | - |
| **小计** | - | **0.45** | **1.2** |

### 总计

| Feature | dev | test | 合计 |
|---|---|---|---|
| F-001 receipt-schema | 0.7 | 0.5 | 1.2 |
| F-002 features-schema | 0.9 | 0.6 | 1.5 |
| F-003 task-frontmatter-schema | 0.9 | 0.5 | 1.4 |
| F-004 dispatch_precheck + 锁 + GATE-POST-DEV-RECEIPT | 1.45 | 0.9 | 2.35 |
| F-005 touches_guard + GATE-TOUCHES-VIOLATION | 0.85 | 0.6 | 1.45 |
| F-006 CI 扩展 | 0.55 | 0 | 0.55 |
| F-007 文档收口 | 0.65 | 0 | 0.65 |
| F-008 e2e + 回归 | 0.45 | 1.2 | 1.65 |
| **合计** | **6.4** | **4.3** | **10.7** |

**挂钟工期估算**：约 9-11 工作日（含设计 1.5 天 + 开发 6.4 天 + 测试 4.3 天，设计与开发可重叠）。

**串行依赖**：F-001/F-002/F-003 schema 类可并行；F-004 依赖 F-001（receipt schema 是 dispatch_precheck/post_dev_receipt 的契约）；F-005 依赖 F-004 的 `.dispatch-state.json` + 锁工具；F-006 与 F-001~F-005 无依赖（可最早改）；F-007 依赖 F-001~F-005 全部落地后；F-008 e2e 依赖前 7 项全部 ready。

---

## 5. 建议（detail-design 阶段必须先决议的事项）

1. **settings.json + guard.sh 精确 patch**（最高优先级）：detail-design 阶段需给出 `.claude/settings.json:29` matcher 改法（推荐 `"Bash|Edit|Write|MultiEdit|Task"`）和 `pre-tool-use-guard.sh:88-96` case 分支增加 Task / 增加 touches_guard 调度的代码骨架；首日跑一次 Task tool stdin JSON 实采样，确认 `tool_input.prompt` 字段名（§2.1 R6）。

2. **V-07 验收措辞修订**（强约束）：requirement.md:124 描述与 D-005 #2 决议自相矛盾。detail-design 阶段把"legacy=true 时短路返回 pass"改为"因 trigger / changed_files 自然路径隔离不被触发；新 gate 不依赖 legacy 短路"（§2.7 / R8）。

3. **CI quality-check.yml 扩展覆盖**（强约束）：pytest step 当前只跑 `tests/gates/`（来源：.github/workflows/quality-check.yml:48）。本次 PR 必须同步改为 `pytest tests/gates/ tests/lib/ tests/integration/ tests/lifecycle/ -v`，并先全量跑一遍记录 baseline；否则 V-02 / V-07 / V-08 测试形同虚设（§2.8 / R7）。

4. **dispatch_precheck.py fail-open 行为契约**：detail-design 阶段必须明确 prompt 解析失败 / state.json 读写失败 / 锁 timeout 等场景一律 `exit 0`（fail-open），写入接口契约文档；与现有 guard.sh 的 ERR trap 哲学一致（§2.2 R1）。

5. **`.dispatch-state.json` 接口收口**：`scripts/lib/dispatch_state.py` 作为单一锁工具入口；`read_state()` / `write_state(...)` / `clear_state(...)` 三函数对外暴露；禁止 hook / gate / 命令绕过直接 open（§2.3）（来源：requirements/REQ-2026-008/plan.md:85）。

6. **touches glob 语义固化**：detail-design 阶段确定 `touches` 字段是否使用 pathspec gitignore 风格（推荐：`src/auth/**` 表示递归，`src/auth/*` 仅匹配本目录）；写入 `templates/feature-task.md.tmpl` 注释（§2.5）。

7. **schema 演化兼容窗口**：3 份新 schema 均需带 `schema_version: "1.0"` 字段；check 脚本维护 `SUPPORTED_VERSIONS` 集合；兼容窗口至少一个 release cycle，超出时给 fail message 指向迁移脚本占位（§2.4 R3）。

8. **render-docs.py 重生成 gate-checklist.md** 必须列入 PR 提交前清单：CI 有 `--check` 强校验（来源：.github/workflows/quality-check.yml:74），漏跑直接红 PR（§2.9）。

---

## 待澄清清单

> tech-research 阶段新发现 3 条；前序 5 条已在 D-005 关单（来源：requirements/REQ-2026-008/plan.md:79），不再重复列出。

1. **Task tool 的 stdin JSON 字段名 `tool_input.prompt`** [待用户确认]（对应 §2.1 R6）
   - **假设**：Claude Code PreToolUse 协议下 Task tool 的 stdin 是 `{tool_name: "Task", tool_input: {prompt: "...", subagent_type: "...", description: "..."}}`
   - **依据**：仓库现有 hook 仅在 Bash/Edit/Write/MultiEdit 实操，未真采样过 Task tool 的 stdin
   - **风险**：若字段名不同（如 `tool_input.task_prompt`），dispatch_precheck.py 解析路径需调整
   - **验证时机**：detail-design 首日；用最小 hook（只 echo stdin → /tmp/log.json）抓一次实派发样本即可

2. **`templates/feature-task.md.tmpl` 现有 frontmatter 字段** ⚠️ **部分闭环（2026-05-06）**（对应 §2.5 §2.9）
   - **实证结论**：现有 frontmatter 含 `feature_id` / `title` / `status` / `complexity` / `depends_on` / `created_at` / `updated_at` / `review_report` 共 8 字段（来源：.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl:1）；**缺 `touches` 字段**，但模板正文 §"触及范围"段（来源：.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl:32）已留位"从 features.json 的 `touches` 复制"
   - **detail-design 必做**：F-005 / F-007 任务必须把 `touches: __TOUCHES__` 加入 frontmatter（不仅是正文段落），否则 `touches_guard.py` 无法机器化读取范围；同步更新 `task-context-builder` Skill 的填充逻辑
   - **影响**：F-003 task-frontmatter-schema.yaml 字段表必须包含 `touches` 为 required；F-005 touches_guard.py 解析路径直接读 frontmatter，无需 fallback 到正文

3. **`tests/lib/` `tests/integration/` `tests/lifecycle/` 现有测试用例** ✅ **已闭环（2026-05-06）**（对应 §2.8 R7）
   - **实证结论**：`python3 -m pytest tests/ --ignore=tests/benchmarks/` 结果 **603 passed, 8 skipped, 36.04s**，全绿无 fail；skipped 集中在 `tests/skills/test_code_review_prepare_routing.py`（7 项）+ `tests/gates/test_argparse_alias_deprecation.py`（1 项），均属预期跳过
   - **影响**：F-006 CI 扩展覆盖（quality-check.yml pytest step 改为 `pytest tests/ --ignore=tests/benchmarks/`）**零额外修复成本**；可在本次 PR 直接落地，不需要 baseline 修复 step
