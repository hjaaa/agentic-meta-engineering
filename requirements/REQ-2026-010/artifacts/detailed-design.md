---
id: REQ-2026-010
phase: detail-design
title: workflow 引擎 main loop 与 bootstrap 完整化 · 详细设计
---

# REQ-2026-010 · 详细设计

承接 `outline-design.md` 的模块视图与决策记录。本文给出可直接对照编码的接口签名、数据结构、伪代码、节点 schema 定义、测试 fixture 与 features.json 拆解。

## 1. 接口签名

### 1.1 `_generate_req_id`（新增 / AC-01）

```python
# scripts/lib/workflow_run.py
_REQ_ID_MAX_RETRIES = 3
_REQ_ID_PATTERN = re.compile(r"^REQ-(\d{4})-(\d{3})$")

def _generate_req_id(repo_root: Path) -> str:
    """扫 requirements/ 下现有 REQ-YYYY-NNN 取 max+1，原子化建目录。

    并发安全：mkdir(exist_ok=False) + EEXIST 重试，与 _generate_run_id 一致。

    返回：成功创建目录的 REQ-ID（str）。
    抛出：WorkflowError 若超 _REQ_ID_MAX_RETRIES。
    """
```

副作用：mkdir `requirements/REQ-YYYY-NNN/`（仅建顶层目录，artifacts/ 由 `_bootstrap_requirement` 建）。

### 1.2 `_bootstrap_requirement`（新增 / AC-01）

```python
# scripts/lib/workflow_run.py
def _bootstrap_requirement(
    req_id: str,
    title: str,
    template_id: str,
    template_path: Path,
    arguments: str,
    repo_root: Path,
) -> Path:
    """完成需求类 bootstrap 副作用三步：建目录文件 + 切分支 + 写 jsonl。

    步骤：
      1. mkdir requirements/<req_id>/artifacts/
      2. write meta.yaml (基于 templates/meta.yaml.tmpl)
      3. write plan.md   (基于 templates/plan.md.tmpl，含 title)
      4. write process.txt (空)
      5. git checkout -b feat/req-<strip_prefix(req_id, "REQ-").lower()>
         例：REQ-2026-010 → feat/req-2026-010（与 yaml 中 $BRANCH_NAME 注入约定一致）
      6. append_event jsonl workflow_started

    返回：requirements/<req_id>/ 路径（Path）。
    抛出：BootstrapError；触发 _bootstrap_rollback 反向撤销。
    """
```

### 1.3 `_bootstrap_rollback`（新增 / AC-01）

```python
def _bootstrap_rollback(
    req_id: str,
    repo_root: Path,
    previous_branch: str,
    artifacts_created: bool,
    branch_created: bool,
) -> None:
    """bootstrap 失败时反向撤销。

    顺序：
      1. 若 branch_created：git checkout <previous_branch> + git branch -D feat/req-<id>
      2. 若 artifacts_created：shutil.rmtree(requirements/<req_id>)
      3. 任一步 IOError 不抛出，打 ERROR 日志（避免吞掉原始错误）
    """
```

幂等：可在 try/except finally 块中重复调用。

### 1.4 `workflow_run.main` 改造（AC-01）

```python
def main(args: list[str], repo_root: Path | None = None) -> int:
    root = repo_root or REPO_ROOT
    template_id, template_args, title = _parse_args(args)  # title=template_args 当模板要求时
    template_path = _resolve_template_path(template_id, root)

    # 新：先校验模板 schema
    result = load_workflow(template_path)
    if result.report.errors:
        print(result.report.render(), file=sys.stderr)
        return 1

    workflow = result.workflow

    # 按模板分类生成 ID
    if workflow.category == "requirement":   # standard-8phase
        req_id = _generate_req_id(root)
        previous_branch = _current_branch(root)
        try:
            run_dir = _bootstrap_requirement(req_id, title, template_id, template_path, template_args, root)
        except BootstrapError as exc:
            _bootstrap_rollback(req_id, root, previous_branch, exc.artifacts_created, exc.branch_created)
            print(f"ERROR: bootstrap 失败：{exc}", file=sys.stderr)
            return 1
    else:                                    # code-review-embedded 等
        run_id = _generate_run_id(root)
        run_dir = root / "runs" / run_id
        # 走原有最薄 bootstrap 路径（保留向后兼容）

    # 后续写 meta.yaml + workflow_started（已有逻辑）
    ...
```

### 1.5 `DispatchResult` & `dispatch_node`（新增 / AC-02）

```python
# scripts/lib/workflow_dispatcher.py（新建）
from dataclasses import dataclass
from typing import Any, Literal, Optional

DispatchOutcome = Literal[
    "completed",
    "approval_pending",
    "failed",
    "loop_continue",
    "loop_done",
    "sub_workflow_pending",
    "sub_workflow_done",
]

@dataclass
class DispatchResult:
    outcome: DispatchOutcome
    output: Any | None = None
    error: str | None = None
    next_node_hint: str | None = None  # 显式覆盖默认拓扑（on_reject 等）

def dispatch_node(
    node: dict,
    run_state: RunState,
    run_dir: Path,
    root: Path,
    env: dict[str, Any],
    jsonl_path: Path,
) -> DispatchResult:
    """按 node 类型派发。所有事件写入由本函数负责。

    env 必含：RUN_ID / RUN_DIR / META_PATH / ARTIFACTS_DIR / ARGUMENTS
            + 每个已 completed 上游节点的 `<nodeId>.output`。

    异常：捕获所有，转为 DispatchResult(outcome="failed", error=str(exc))。
    """
    node_id = node["id"]
    append_event(jsonl_path, {"type": "node_started", "node_id": node_id})
    try:
        if "agent" in node:                         return _dispatch_agent_node(node, env, jsonl_path)
        if "skill" in node:                         return _dispatch_skill_node(node, env, jsonl_path)
        if "prompt" in node or "prompt_file" in node: return _dispatch_prompt_node(node, env, jsonl_path)
        if "bash" in node:                          return _dispatch_bash_node(node, env, run_dir, jsonl_path)
        if "approval" in node:     return _dispatch_approval_node(node, env, jsonl_path)
        if "loop" in node:         return _dispatch_loop_node(node, env, run_state, jsonl_path)
        if "sub_workflow" in node: return _dispatch_sub_workflow_node(node, env, run_dir, root, jsonl_path)
        raise WorkflowError(f"未知节点类型：{node_id}")
    except Exception as exc:
        append_event(jsonl_path, {"type": "node_failed", "node_id": node_id, "data": {"error": str(exc)}})
        return DispatchResult(outcome="failed", error=str(exc))
```

### 1.6 7 类节点 dispatcher 函数签名

```python
def _dispatch_agent_node(node, env, jsonl_path) -> DispatchResult: ...
def _dispatch_skill_node(node, run_state, env, jsonl_path) -> DispatchResult: ...
def _dispatch_prompt_node(node, run_state, env, run_dir, root, jsonl_path) -> DispatchResult: ...
def _dispatch_bash_node(node, run_state, env, run_dir, root, jsonl_path) -> DispatchResult: ...
def _dispatch_approval_node(node, env, run_state, jsonl_path) -> DispatchResult:
    """写 approval_pending 事件后立即 return（方案 ii）。"""
    append_event(jsonl_path, {
        "type": "approval_pending",
        "node_id": node["id"],
        "data": {"prompt": substitute_vars(node["approval"].get("prompt", ""), run_state.node_outputs, env)},
    })
    return DispatchResult(outcome="approval_pending")

def _dispatch_loop_node(node, env, run_state, jsonl_path) -> DispatchResult:
    """loop 节点：迭代计数从 run_state.loop_counters[node_id] 读取。"""
    ...

def _dispatch_sub_workflow_node(node, env, run_dir, root, jsonl_path) -> DispatchResult:
    """派子 run：调 workflow_run.main，子 run 目录挂 run_dir/sub_runs/<node_id>/。"""
    ...
```

### 1.7 `workflow_continue.main loop`（AC-02 替换 stub）

```python
# scripts/lib/workflow_continue.py
def _main_loop(run_state, workflow, run_dir, root, jsonl_path) -> None:
    """主循环：直到 state 不再是 running 或无后继节点。"""
    node_map = {n["id"]: n for n in workflow.nodes}
    while run_state.state == "running" and run_state.current_node:
        node = node_map.get(run_state.current_node)
        if node is None:
            append_event(jsonl_path, {"type": "workflow_failed", "data": {"error": f"未知节点 {run_state.current_node}"}})
            run_state.state = "failed"
            break

        env = _build_env(run_state, run_dir, root)
        result = dispatch_node(node, run_state, run_dir, root, env, jsonl_path)

        if result.outcome == "completed":
            append_event(jsonl_path, {"type": "node_completed", "node_id": node["id"], "data": {"output": result.output}})
            run_state.node_outputs[node["id"]] = result.output
            run_state.current_node = _next_node(node, node_map, result.next_node_hint)
        elif result.outcome == "loop_continue":
            run_state.loop_counters[node["id"]] = run_state.loop_counters.get(node["id"], 0) + 1
            # current_node 不变
        elif result.outcome in ("loop_done", "sub_workflow_done"):
            run_state.current_node = _next_node(node, node_map, result.next_node_hint)
        elif result.outcome in ("approval_pending", "sub_workflow_pending"):
            run_state.state = "approval_pending" if result.outcome == "approval_pending" else "running"
            break
        elif result.outcome == "failed":
            on_failure = node.get("on_failure", "retry")
            _handle_failure(run_state, node, on_failure, jsonl_path, error=result.error)
            break

def _handle_failure(
    run_state: RunState,
    node: dict,
    on_failure: Literal["retry", "skip", "abort"],
    jsonl_path: Path,
    error: str | None,
) -> None:
    """按 on_failure 处理失败节点。

    - retry：current_node 不变；下次 /workflow:continue 时重派；连续失败 ≥ max_retries（默认 3）
            升级为 abort 并写 workflow_failed
    - skip：写 node_skipped + current_node 推进到 topology.next；state 保持 running
    - abort：写 workflow_failed + state=failed；用户必须 /workflow:rollback 回退
    """
    node_id = node["id"]
    max_retries = node.get("max_retries", 3)
    retry_count = sum(
        1 for e in read_events(jsonl_path)[0]
        if e.get("type") == "node_failed" and e.get("node_id") == node_id
    )
    if on_failure == "retry" and retry_count < max_retries:
        # current_node 保持指向失败节点，state 保持 running，下次 continue 自动重派
        return
    if on_failure == "skip":
        append_event(jsonl_path, {"type": "node_skipped", "node_id": node_id, "data": {"reason": error}})
        run_state.current_node = _next_node(node, node_map, None)
        return
    # abort 或 retry 用尽
    append_event(jsonl_path, {"type": "workflow_failed", "data": {"node_id": node_id, "error": error}})
    run_state.state = "failed"
```

## 2. 数据结构

### 2.1 jsonl 新增事件类型

| type | 写入时机 | data 字段 |
|---|---|---|
| `node_started` | dispatcher 进入节点 | `{}` |
| `node_completed` | 节点成功 | `{output: <node output>}` |
| `node_failed` | 节点失败 | `{error: <str>}` |
| `node_skipped` | on_failure=skip 时 | `{reason: <str>}` |
| `approval_pending` | approval 节点写后 return | `{prompt: <substituted str>}` |
| `loop_iteration_started` | loop 节点每轮开始 | `{iteration: N}` |
| `loop_iteration_completed` | loop 节点每轮结束 | `{iteration: N, output: <any>}` |

### 2.2 RunState 字段扩展

```python
@dataclass
class RunState:
    # 已有字段
    run_id: str                        # workflow_started 事件的 run_id
    state: Literal["running", "paused", "failed", "approval_pending", "completed", "cancelled"]
    current_node: str | None
    node_outputs: dict[str, Any]
    pending_approval: str | None
    warnings: list[str]
    # 新增（AC-02）
    arguments: str                     # workflow_started 事件的 data.arguments 字面量
    loop_counters: dict[str, int]      # node_id → 当前迭代数
```

`rebuild` 算法事件覆盖（按出现顺序处理，幂等）：

- `workflow_started` → 初始化 `run_id`、`arguments = data.arguments`、`state = "running"`、`current_node = workflow.nodes[0].id`
- `node_started` → 记录 `current_node = node_id`（用于失败重派定位）
- `node_completed` → `node_outputs[node_id] = data.output`、`current_node = topology.next(...)`
- `node_failed` → `state = "failed"`、保留 `current_node` 不变（供 retry 续跑）
- `node_skipped` → `current_node = topology.next(...)`（on_failure=skip 路径）
- `loop_iteration_started` → `loop_counters[node_id] = data.iteration`
- `loop_iteration_completed` → `loop_counters[node_id] = data.iteration`
- `approval_pending` → `state = "approval_pending"`、`pending_approval = node_id`
- `approval_approved` → `state = "running"`、`pending_approval = None`、`current_node` 跳到 `data.next_node` 或拓扑下游
- `approval_rejected` → 按 `on_reject` 走，`current_node = data.next_node` 或重派
- `workflow_failed` / `workflow_completed` / `workflow_cancelled` → 终态 `state`
- `run_resumed` / `[save]` → 仅审计语义，不改 RunState
- 未知事件 type → 追加到 `warnings`，不抛出（向前兼容）

### 2.3 `_build_env`（dispatcher 派发前）

```python
def _build_env(run_state, run_dir, root) -> dict[str, str]:
    # 计算 BRANCH_NAME：去掉 REQ- 前缀（如有）+ 小写，与 _bootstrap_requirement 切分支约定一致
    short_id = run_state.run_id.removeprefix("REQ-").lower()
    branch_name = f"feat/req-{short_id}"

    env = {
        "RUN_ID": run_state.run_id,
        "RUN_DIR": str(run_dir),
        "META_PATH": str(run_dir / "meta.yaml"),
        "ARTIFACTS_DIR": str(run_dir / "artifacts"),
        "ARGUMENTS": run_state.arguments,
        "BRANCH_NAME": branch_name,
    }
    # 注入每个 completed 节点的 output（供下游 $<nodeId>.output 引用）
    for node_id, output in run_state.node_outputs.items():
        env[f"{node_id}.output"] = json.dumps(output) if not isinstance(output, str) else output
    return env
```

`substitute_vars(template, node_outputs, env, escape_for_bash=<bool>)` 已实现（来源：scripts/lib/substitute_vars.py:61）。bash 节点 `escape_for_bash=False`；skill / prompt / approval 节点走默认 `True`（防注入）。

## 3. AC-03 yaml 模板改造清单

`.claude/workflows/requirement/standard-8phase.yaml` 中硬编码路径的实际位置（grep 已确认 10 处 `runs/$RUN_ID/` 字面量 + 3 处 `feat/req-$RUN_ID` 字面量，来源：.claude/workflows/requirement/standard-8phase.yaml:175）改造：

| 节点 id | 行号 | 原 | 新 |
|---|---|---|---|
| `phase-to-tech-research` | :175-176 | `yq e ".phase = ..." -i runs/$RUN_ID/meta.yaml` + `yq e ".gates_passed += ..." -i runs/$RUN_ID/meta.yaml` | 全部 → `-i "$META_PATH"` |
| `phase-to-outline-design` | :262-263 | `yq e ".phase = ..." -i runs/$RUN_ID/meta.yaml` + `yq e ".affected_modules = ..." -i runs/$RUN_ID/meta.yaml` | 同上 |
| `phase-to-detail-design` | :339 | `yq e ".phase = ..." -i runs/$RUN_ID/meta.yaml` | 同上 |
| `phase-to-task-planning` | :457 | 同上 | 同上 |
| `phase-to-development` | :513 | 同上 | 同上 |
| `phase-to-testing` | :555 | 同上 | 同上 |
| `pr-submit` | :669-670, :678 | `git push origin "feat/req-$RUN_ID"` + `gh pr list --head "feat/req-$RUN_ID"` + `yq e ".pr_url = ..." -i runs/$RUN_ID/meta.yaml` | `git push origin "$BRANCH_NAME"` + `gh pr list --head "$BRANCH_NAME"` + `-i "$META_PATH"` |
| `archive-finalize` | :703, :706 | `yq e "..." -i runs/$RUN_ID/meta.yaml` + `echo "建议手动跑：git branch -d feat/req-$RUN_ID"` | `-i "$META_PATH"` + `echo "...git branch -d $BRANCH_NAME"` |

**新增引擎注入变量**：

- `$RUN_ID`：保持原值（如 `REQ-2026-010`），向后兼容
- `$RUN_DIR`：`_resolve_run_dir(run_id, root)` 解析的绝对路径
- `$META_PATH`：`$RUN_DIR/meta.yaml`
- `$ARTIFACTS_DIR`：`$RUN_DIR/artifacts`
- `$BRANCH_NAME`：**新增**，由 `_build_env` 计算 = `"feat/req-" + strip_prefix(run_id, "REQ-").lower()`（如 `REQ-2026-010` → `feat/req-2026-010`），与 `_bootstrap_requirement` 切分支约定保持一致

**为什么需要 `$BRANCH_NAME`**：直接展开 `feat/req-$RUN_ID` 会得到 `feat/req-REQ-2026-010`（保留 REQ- 前缀 + 大写），与 bootstrap 实际切出的小写无前缀分支名不一致。`$BRANCH_NAME` 显式注入避免大小写 / 前缀两类 bug。

bash 节点通过 `substitute_vars(escape_for_bash=False)` 替换后形成裸路径字面值；`artifact.must_exist` 路径（已用 `$ARTIFACTS_DIR`）无需改造。

## 4. AC-04 路径收敛改造

`scripts/lib/workflow_status.py:41-56` 现有：

```python
nodes_dir = run_dir / "nodes"
if nodes_dir.is_dir():
    for node_dir in sorted(nodes_dir.iterdir()):
        sub_run_id_file = node_dir / "run_id"
        if sub_run_id_file.is_file():
            sub_run_id = sub_run_id_file.read_text().strip()
            sub_dir = _resolve_run_dir(sub_run_id, run_dir.parent.parent)
            ...
```

改造为：

```python
sub_runs_dir = run_dir / "sub_runs"
if sub_runs_dir.is_dir():
    for sub_run_dir in sorted(sub_runs_dir.iterdir()):
        if not sub_run_dir.is_dir():
            continue
        sub_run_id = sub_run_dir.name  # 目录名即子 run id（与 rollback_subrun 约定一致）
        try:
            sub_events, sub_warnings = read_events(sub_run_dir / "run-state.jsonl")
            sub_state = RunState.rebuild(sub_events, run_id=sub_run_id, warnings=sub_warnings)
            ...
```

`workflow_rollback_subrun.py:79` 已默认走 `sub_runs/`，无需改动。

`workflow_dispatcher._dispatch_sub_workflow_node` 派子 run 时，子 run dir 路径设为 `run_dir / "sub_runs" / node_id`，与上述发现策略一致。

## 5. AC-05 mock LLM dispatcher 测试架构

### 5.1 mock fixture（pytest）

```python
# tests/e2e/conftest.py 或测试文件内
@pytest.fixture
def mock_agent_dispatch(monkeypatch):
    """mock _dispatch_agent_node，返回预设 output 但走完整 main loop。"""
    captured_calls: list[dict] = []

    def _fake_dispatch(node, env, jsonl_path):
        captured_calls.append({"node_id": node["id"], "env_keys": list(env.keys())})
        # 按 node["mock_response"] 取预设输出，缺省时返回最小 dict
        preset = node.get("mock_response", {"verdict": "approved", "score": 90})
        return DispatchResult(outcome="completed", output=preset)

    from workflow_dispatcher import _dispatch_agent_node as _real
    monkeypatch.setattr("workflow_dispatcher._dispatch_agent_node", _fake_dispatch)
    yield captured_calls
```

### 5.2 改造后的测试断言（AC-05 验收）

```python
def test_main_loop_dispatches_three_nodes_with_approval(mock_agent_dispatch, tmp_repo):
    """given_workflow_with_3_nodes_and_one_approval_when_continue_then_jsonl_complete"""
    # 起 run、走 main loop
    rc = workflow_continue.main([run_id], repo_root=tmp_repo)
    assert rc == 0

    events = read_jsonl(tmp_repo / "runs" / run_id / "run-state.jsonl")
    # AC-02 断言：至少 3 node_completed + 1 approval_pending
    completed_nodes = [e for e in events if e["type"] == "node_completed"]
    assert len(completed_nodes) >= 3
    assert any(e["type"] == "approval_pending" for e in events)

    # AC-05 断言：node_completed 的 output 非空
    for ev in completed_nodes:
        output = ev["data"]["output"]
        assert len(json.dumps(output)) > 0
```

替换 `tests/e2e/test_code_review_embedded.py:8` 与 `tests/e2e/test_sub_workflow_lifecycle.py:12` 中现有的"全 mock 跳过"逻辑为上述真 e2e + mock dispatcher 层方案。

## 6. 失败处理矩阵（细化 outline §5.2.2）

| 失败位置 | 触发条件 | dispatcher 行为 | jsonl 事件 | main loop 行为 | 续跑路径 |
|---|---|---|---|---|---|
| bash 节点 subprocess 退出码 ≠ 0 | `subprocess.run` returncode | 捕获 `CalledProcessError`，stderr 入 error | `node_failed{error: stderr}` | 按 `on_failure` 分支 | retry 重派；skip 跳过；abort state=failed |
| agent 节点 LLM 解析失败 | output_format JSON 解析错 | catch JSONDecodeError | `node_failed{error: ...}` | 同上 | retry 推荐 |
| approval `max_attempts` 用尽 | reject 次数 > max_attempts | 写 `approval_rejected_final` | `approval_rejected_final` | state=rejected, break | 用户必须 rollback |
| sub_workflow 子 run failed | 子 jsonl 末事件 = workflow_failed | 父 dispatch 返回 failed | `node_failed{sub_run: <id>}` | 按 `on_failure` 分支 | retry 子 run 不重新派，等用户 rollback |
| loop iteration 失败 | 单轮 dispatch 失败 | 内部 dispatch 失败 | `loop_iteration_failed{iteration: N}` | 按节点 `on_failure` | retry 同一 iteration；skip 跳出 loop |

## 7. 模块文件清单

| 文件 | 操作 | 行数估算 | AC |
|---|---|---|---|
| `scripts/lib/workflow_run.py` | 扩展 | +120 | AC-01 |
| `scripts/lib/workflow_dispatcher.py` | 新建 | ~400 | AC-02 |
| `scripts/lib/workflow_continue.py` | 替换 stub | +80 | AC-02 |
| `scripts/lib/workflow_status.py` | 修改 | ~-10/+10 | AC-04 |
| `scripts/lib/run_state.py` | 扩展（loop_counters / arguments 字段） | +20 | AC-02 |
| `.claude/workflows/requirement/standard-8phase.yaml` | 修改 | 7 处节点改 | AC-03 |
| `tests/e2e/test_code_review_embedded.py` | 重写 | ~-50/+80 | AC-05 |
| `tests/e2e/test_sub_workflow_lifecycle.py` | 重写 | ~-50/+80 | AC-05 |
| `tests/e2e/conftest.py` | 新增 mock_agent_dispatch fixture | +30 | AC-05 |
| `templates/plan.md.tmpl` | 已有，确认即可 | 0 | AC-01 |
| `templates/meta.yaml.tmpl` | 已有，确认即可 | 0 | AC-01 |

## 8. features.json（任务规划阶段 6 输入）

> **注**：本节展示的是按 AC 维度组织的拆解思路（用 F-A* / F-B* 命名便于阅读）；正式 features.json 已按 features-schema.yaml 落盘到同级 `artifacts/features.json`，使用规范 ID（F-001 ~ F-011），字段含 description / modules / depends_on_features / complexity / acceptance 全部必填项。本节与 features.json 通过 `ac_refs` + `pr_group` 字段双向追溯，编号对照见 §9。

```json
{
  "features": [
    {
      "id": "F-A1",
      "title": "_generate_req_id + REQ-YYYY-NNN 编号策略",
      "ac_refs": ["AC-01"],
      "pr": "PR-A",
      "touches": ["scripts/lib/workflow_run.py"],
      "estimated_hours": 4,
      "depends_on": [],
      "status": "pending"
    },
    {
      "id": "F-A2",
      "title": "_bootstrap_requirement + _bootstrap_rollback（建目录/切分支/失败兜底）",
      "ac_refs": ["AC-01"],
      "pr": "PR-A",
      "touches": ["scripts/lib/workflow_run.py", "templates/plan.md.tmpl"],
      "estimated_hours": 8,
      "depends_on": ["F-A1"],
      "status": "pending"
    },
    {
      "id": "F-A3",
      "title": "挂载 load_workflow schema 校验",
      "ac_refs": ["AC-01"],
      "pr": "PR-A",
      "touches": ["scripts/lib/workflow_run.py"],
      "estimated_hours": 2,
      "depends_on": [],
      "status": "pending"
    },
    {
      "id": "F-A4",
      "title": "standard-8phase.yaml 7 处节点路径参数化（$RUN_DIR/$META_PATH）",
      "ac_refs": ["AC-03"],
      "pr": "PR-A",
      "touches": [".claude/workflows/requirement/standard-8phase.yaml"],
      "estimated_hours": 4,
      "depends_on": ["F-A2"],
      "status": "pending"
    },
    {
      "id": "F-B1",
      "title": "workflow_dispatcher.py 框架（DispatchResult + dispatch_node + 7 类节点 stub）",
      "ac_refs": ["AC-02"],
      "pr": "PR-B",
      "touches": ["scripts/lib/workflow_dispatcher.py"],
      "estimated_hours": 6,
      "depends_on": ["F-A4"],
      "status": "pending"
    },
    {
      "id": "F-B2",
      "title": "bash/skill/prompt 节点完整实现 + 变量注入 _build_env",
      "ac_refs": ["AC-02", "AC-03"],
      "pr": "PR-B",
      "touches": ["scripts/lib/workflow_dispatcher.py", "scripts/lib/run_state.py"],
      "estimated_hours": 6,
      "depends_on": ["F-B1"],
      "status": "pending"
    },
    {
      "id": "F-B3",
      "title": "approval 节点 + main loop break 续跑（方案 ii）",
      "ac_refs": ["AC-02"],
      "pr": "PR-B",
      "touches": ["scripts/lib/workflow_dispatcher.py", "scripts/lib/workflow_continue.py"],
      "estimated_hours": 4,
      "depends_on": ["F-B1"],
      "status": "pending"
    },
    {
      "id": "F-B4",
      "title": "main loop 替换 stub + 失败处理矩阵（retry/skip/abort）",
      "ac_refs": ["AC-02"],
      "pr": "PR-B",
      "touches": ["scripts/lib/workflow_continue.py"],
      "estimated_hours": 6,
      "depends_on": ["F-B2", "F-B3"],
      "status": "pending"
    },
    {
      "id": "F-B5",
      "title": "workflow_status.py 父子路径收敛到 sub_runs/",
      "ac_refs": ["AC-04"],
      "pr": "PR-B",
      "touches": ["scripts/lib/workflow_status.py"],
      "estimated_hours": 2,
      "depends_on": [],
      "status": "pending"
    },
    {
      "id": "F-B6",
      "title": "AC-05 mock_agent_dispatch fixture + 替换 2 条占位 e2e",
      "ac_refs": ["AC-05"],
      "pr": "PR-B",
      "touches": [
        "tests/e2e/conftest.py",
        "tests/e2e/test_code_review_embedded.py",
        "tests/e2e/test_sub_workflow_lifecycle.py"
      ],
      "estimated_hours": 8,
      "depends_on": ["F-B4"],
      "status": "pending"
    },
    {
      "id": "F-B7",
      "title": "loop / sub_workflow 节点最小实现（占位 outcome，深度联动留后续）",
      "ac_refs": ["AC-02"],
      "pr": "PR-B",
      "touches": ["scripts/lib/workflow_dispatcher.py"],
      "estimated_hours": 4,
      "depends_on": ["F-B1"],
      "status": "pending"
    }
  ],
  "pr_groups": {
    "PR-A": ["F-A1", "F-A2", "F-A3", "F-A4"],
    "PR-B": ["F-B1", "F-B2", "F-B3", "F-B4", "F-B5", "F-B6", "F-B7"]
  },
  "totals": {
    "estimated_hours": 54,
    "estimated_days": "约 6.75 工日（按 8h/天），含 design + dev；test 工作量已分摊到各 feature"
  }
}
```

工作量与 tech-research §3 估算的 9.8 天对比偏少，是因为 tech-research 含 design 1.8 天独立段，本 features.json 已把 design 摊到各 feature；总量基本一致。

## 9. 决策回引（追溯链）

| 接口/数据结构 | requirement AC | outline 章节 | 正式 features.json id | 备注 |
|---|---|---|---|---|
| `_bootstrap_requirement` | AC-01 | §2.2 | F-002 | 反向撤销三步顺序锁定 |
| `_generate_req_id` | AC-01 | §2.2 | F-001 | EEXIST 重试 3 次 |
| `load_workflow` 挂载 | AC-01 | §4.1 | F-003 | report.errors > 0 时 exit 1 |
| `$BRANCH_NAME` 等变量 + yaml 改造 | AC-03 | §4.4 | F-004 | 10 处 `runs/$RUN_ID/` + 3 处 `feat/req-$RUN_ID` |
| `DispatchResult` 7 outcome + 框架 | AC-02 | §4.3 | F-005 | 闭环 outline review 002 required_fix |
| `_dispatch_bash/skill/prompt_node` | AC-02 / AC-03 | §4.3 | F-006 | escape_for_bash 控制 |
| `_dispatch_approval_node` 方案 ii | AC-02 | §3 approval 决策 | F-007 | jsonl 反扫重建 |
| main loop 替换 stub + 失败矩阵 | AC-02 | §5.2 | F-008 | retry / skip / abort |
| `_dispatch_sub_workflow_node` 路径 | AC-04 | §3 父子路径决策 | F-009（status 改造）+ F-011（dispatcher 端）| run_dir/sub_runs/<node_id>/ |
| `mock_agent_dispatch` fixture + 2 e2e 重写 | AC-05 | §4.3 mock 切入点 | F-010 | 阶段 3 用户确认 |
| `_dispatch_loop_node` + `_dispatch_sub_workflow_node` | AC-02 | §4.3 | F-011 | 深度联动留后续 |
| `_handle_failure` retry/skip/abort | AC-02 | §5.2 | F-008 | 闭环 outline review 002 required_fix |

**F-A* / F-B* 编号到 F-NNN 的映射**（§8 内嵌示意 → 正式 features.json）：

| §8 示意 ID | 正式 ID | §8 示意 ID | 正式 ID |
|---|---|---|---|
| F-A1 | F-001 | F-B1 | F-005 |
| F-A2 | F-002 | F-B2 | F-006 |
| F-A3 | F-003 | F-B3 | F-007 |
| F-A4 | F-004 | F-B4 | F-008 |
|       |       | F-B5 | F-009 |
|       |       | F-B6 | F-010 |
|       |       | F-B7 | F-011 |

## 待澄清清单

无新增。features.json 中 F-A* / F-B* 顺序与 PR 拆分均已锁定，阶段 6 任务规划直接采纳本文 §8 的 features.json 作为输入。
