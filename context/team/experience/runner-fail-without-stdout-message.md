# runner gate FAIL 时 plugin message 不输出到 stdout（CI 排查盲）

**沉淀原因**：跨需求重复（任何 multi-plugin runner 都可能踩可见性 bug）、AI 反复错（debug CI 失败时找不到原因）、跨会话保留（runner 设计原则需要固化）。

## 问题

REQ-2026-005 PR #50 CI 失败：`quality-check` exit 1，但 GitHub Actions 日志里只看到 6 行 `INFO gate.start gate_id=...` 然后直接 `##[error]Process completed with exit code 1`，**没有任何 plugin 的失败原因输出**。

本地 reproduce 也是 `python3 scripts/gates/run.py --trigger=ci --strict` exit=1 但 stdout 同样空。直到用 Python REPL 直接 invoke plugin（`from plugins import reviews_consistency; gate.run(ctx)` → 看 `report.message`）才看到完整 9 条不一致清单。

## 根因

`scripts/gates/run.py:_run_gates` 收到 plugin 的 `Decision.FAIL` Report 后只是 `raise GateFailed(r)`，后续 `_handle_gate_failed` 走 rollback、`_finalize_audit` 写 audit log，**没有任何环节把 plugin 的 `report.message` 渲染到 stdout/stderr**。

audit log 是 JSON 落盘到 `audit/<YYYY-MM>/<trigger>-<timestamp>.json`，CI 不会自动 cat。本地用户至少能去翻 audit 文件，CI 就完全看不到——只能"没输出 + exit 1 → 一头雾水"。

可见性 bug 不影响功能但极大拖慢调试。

## 解法

**runner 设计原则**：plugin 任何 FAIL 路径必须把 `code` + `message` + `fix_hint` 渲染到 stderr，独立于 audit 落盘。

最小补丁（在 `_run_gates` 抛 `GateFailed` 前 / `GateFailed` 异常 handler 里）：

```python
print(
    f"FAIL {r.gate_id} code={r.code} severity={sev}\n  {r.message}\n  fix: {r.fix_hint}",
    file=sys.stderr,
)
```

**测试约束**：runner 的失败路径单测必须 assert stderr 含 `report.message`，避免回退。

## 验证方法

- 故意构造一个 FAIL 场景跑 runner，CI / 本地 stderr 都能看到 message
- 加单测：`tests/gates/test_runner.py::test_runner_prints_report_message_on_fail`

## 引用来源

- `scripts/gates/run.py:_run_gates`（漏 print 的位置）
- `scripts/gates/plugins/reviews_consistency.py:_run_ci_full_scan`（FAIL message 含 9 条不一致但没渲染）
- REQ-2026-005 PR #50 CI 失败排查过程（gh run view 25274084226 看到的空白）
- **follow-up REQ 候选**：runner 可见性补丁 + 单测覆盖
