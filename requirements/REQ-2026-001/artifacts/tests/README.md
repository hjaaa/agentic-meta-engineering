# REQ-2026-001 集成测试

端到端验证 `extract-experience` Hook 全链路，覆盖 TC-01 ~ TC-10 共 10 个用例。

## 运行

```bash
# 从仓库根目录运行
bash requirements/REQ-2026-001/artifacts/tests/run-e2e.sh
```

**注意**：TC-08（watchdog 超时）需等待约 35s，属正常现象。

## 文件说明

| 文件 | 说明 |
|---|---|
| `run-e2e.sh` | 测试主入口，10 个 TC 全部在此定义 |
| `mock-claude.sh` | claude 命令 stub，通过 `MOCK_CLAUDE_MODE` 控制行为 |
| `fixtures/transcript-normal.jsonl` | 约 20 行真实风格 transcript（TC-01/02/03/04/05/06/07/10）|
| `fixtures/transcript-large.jsonl` | 100 行 transcript，验证 `tail -n 60` 截断（TC-09）|

## mock-claude.sh 模式

通过 `MOCK_CLAUDE_MODE` 环境变量注入（worker 通过 `EXPERIENCE_HOOK_CLAUDE_BIN` 调用）：

| 模式 | 行为 |
|---|---|
| `success`（默认）| 输出固定 markdown 列表，exit 0 |
| `fail` | exit 1（触发 claude-exit-1 路径）|
| `empty` | exit 0 + 空 stdout（触发 bug-7263 路径）|
| `slow` | sleep 60（触发 30s watchdog kill）|

## 退出码

- `0`：全部 PASS
- `1`：有失败，stderr 输出失败 TC 列表
