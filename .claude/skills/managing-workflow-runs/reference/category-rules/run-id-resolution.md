# Run-ID 解析规则（D-007 双路径）

来源：requirements/REQ-2026-009/plan.md D-007（行 110-117）

## 规则

所有需要 run 上下文的子动作（continue / save / status / approve / reject / rollback / cancel），run-id 解析必须调用：

```python
from run_state import _resolve_run_dir

run_dir = _resolve_run_dir(run_id, repo_root)
```

禁止重写双路径逻辑。

## 双路径逻辑（已在 run_state.py:290 实现）

1. 先检查 `requirements/<run_id>/`（兼容旧需求目录）
2. 不存在则检查 `runs/<run_id>/`（新 run 目录）
3. 两者都不存在 → 抛 `WorkflowError`

## run-id 推断（无 run-id 参数时）

当命令未传 run-id，按以下顺序推断：

1. 读当前 git 分支名，格式 `feat/req-<id>` → 提取 `<id>` 作为 run-id
2. 推断失败 → 列出候选（ls `requirements/*/` + `runs/*/`）+ 要求用户明确指定

## jsonl 路径约定

run-id 解析得到 `run_dir` 后，jsonl 路径为：

```python
jsonl_path = run_dir / "run-state.jsonl"
```
