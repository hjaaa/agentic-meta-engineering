# REQ-2026-001 测试报告

## 基本信息

| 项目 | 值 |
|---|---|
| 需求编号 | REQ-2026-001 |
| 测试模式 | execute（真实执行） |
| 执行开始时间 | 2026-04-26 18:36:57（Asia/Shanghai） |
| 执行结束时间 | 2026-04-26 18:37:48（Asia/Shanghai） |
| 总耗时 | 约 51 秒（含 TC-08 watchdog 35s） |

## 测试命令

```
bash requirements/REQ-2026-001/artifacts/tests/run-e2e.sh
```

完整路径：`/Users/richardhuang/learnspace/agentic-meta-engineering/requirements/REQ-2026-001/artifacts/tests/run-e2e.sh`

## 执行环境

| 项目 | 值 |
|---|---|
| 操作系统 | Darwin RichardHuangdeMacBook-Pro.local 25.4.0 Darwin Kernel Version 25.4.0: Thu Mar 19 19:30:44 PDT 2026; root:xnu-12377.101.15~1/RELEASE_ARM64_T6000 arm64 |
| Bash 版本 | GNU bash, version 3.2.57(1)-release (arm64-apple-darwin25) |
| 平台 | macOS (ARM64 / Apple Silicon) |

## 结果摘要

| 指标 | 值 |
|---|---|
| 总用例数 | 12 |
| PASS | 12 |
| FAIL | 0 |
| SKIP | 0 |
| 覆盖估算 | 见下方覆盖缺口分析 |

**结论：全部 PASS (12/12)**

## 12 个 TC 的 PASS/FAIL 矩阵

| TC 编号 | 场景描述 | 结果 | 备注 |
|---|---|---|---|
| TC-01 | 正常会话提取（notes.md 增 ## 会话经验 小节） | **PASS** | — |
| TC-02 | env opt-out（SKIP_EXPERIENCE_HOOK=1，notes.md 不变） | **PASS** | — |
| TC-03 | 非需求分支（develop 分支，notes.md 不变） | **PASS** | — |
| TC-04 | meta.yaml 缺失（notes.md 不被新建） | **PASS** | — |
| TC-05 | phase=completed（notes.md 不变） | **PASS** | — |
| TC-06 | claude -p 失败（exit 1，写入 hook-skipped: claude-exit-1） | **PASS** | — |
| TC-07 | claude -p 输出为空（bug-7263，写入 hook-skipped: empty-output-bug-7263） | **PASS** | — |
| TC-08 | 超时 watchdog（worker 被 kill -9，约 35s，notes.md 不变） | **PASS** | 等待约 35s，属设计预期 |
| TC-09 | 大 transcript（100 行，tail 截断后正常写入） | **PASS** | — |
| TC-10 | 并发写 notes.md（至少 1 条经验记录，无内容撕裂） | **PASS** | — |
| TC-11 | transcript 截断失败（写入 hook-skipped: transcript-truncate-failed） | **PASS** | — |
| TC-12 | prompt 模板缺失（写入 hook-skipped: prompt-template-missing） | **PASS** | — |

## 失败详情

无。所有 12 个用例均通过。

## 覆盖缺口分析（features.json 对齐）

### F-001：settings.json SessionEnd 注册 + 主 Hook 守门脚本

| acceptance 条目 | 覆盖 TC | 状态 |
|---|---|---|
| shellcheck 通过 | 无专用 TC（前置条件，开发阶段已验证） | 未在 e2e 中自动化；属设计接受 |
| TC-02/TC-03/TC-04/TC-05 守门用例通过 | TC-02、TC-03、TC-04、TC-05 | 已覆盖 |
| 主 Hook 在守门失败路径下耗时 ≤ 100ms | 无专用 TC（详见已知限制） | 未覆盖：100ms 时延断言无自动化，设计接受手工 `time` 验证 |

### F-002：Worker 后台脚本

| acceptance 条目 | 覆盖 TC | 状态 |
|---|---|---|
| shellcheck 通过 | 同 F-001 说明 | 未在 e2e 中自动化；属设计接受 |
| TC-01 正常路径 notes.md 增 ## 会话经验 小节 | TC-01 | 已覆盖 |
| TC-06/TC-07/TC-11/TC-12 失败路径写入 [hook-skipped: <reason>] | TC-06、TC-07、TC-11、TC-12 | 已覆盖 |
| TC-08 超时被 watchdog kill，30s 后 worker 进程不存在 | TC-08 | 已覆盖 |
| TC-10 并发写测试不撕裂内容 | TC-10 | 已覆盖 |

### F-003：extract-experience.prompt.md 模板

| acceptance 条目 | 覆盖 TC | 状态 |
|---|---|---|
| 包含 {{TRANSCRIPT_PATH}} 占位符 | 无专用 e2e TC（TC-12 间接验证 prompt 缺失路径） | 未自动化验证占位符内容；属设计接受（静态文件内容审查） |
| 明确禁止使用工具与编造信息 | 同上 | 同上 |
| 在真实 transcript 上手工跑一次能产出 markdown 列表 | 无 TC（手工验证项） | 未覆盖：e2e 范围外，设计接受为手工验证 |

### F-004：集成测试 fixture + 端到端验证脚本

| acceptance 条目 | 覆盖 TC | 状态 |
|---|---|---|
| 12 个 TC 全部 PASS | TC-01 ~ TC-12 | 已覆盖（全 PASS） |
| 测试可在 macOS bash 3.2 + Linux bash 5 上重复运行 | 本次在 bash 3.2.57 / macOS 验证通过 | macOS 已覆盖；Linux 未在本次执行中验证（CI 环境可补充） |
| 测试不污染仓库（所有产物在 tmp 或测试目录内） | 所有 TC（run-e2e.sh 末尾 cleanup 验证） | 已覆盖；脚本输出"临时文件清理验证: OK" |

### F-005：onboarding-guide 增加自动经验提取小节

| acceptance 条目 | 覆盖 TC | 状态 |
|---|---|---|
| small section 文字 ≤ 200 字 | 不在 e2e 范围 | 未覆盖：属文档变更，已在 review-20260426-171506.md 通过审查 |
| 明示 SKIP_EXPERIENCE_HOOK=1 与 /exit 已知限制 | 不在 e2e 范围 | 同上 |
| check-index.sh 通过 | 不在 e2e 范围 | 同上 |

**F-005 整体说明**：onboarding 文档变更不在 e2e 测试范围内，属设计文档变更，已在代码审查报告（review-20260426-171506.md）中通过验收，此处标记为"e2e 未覆盖，文档审查已通过"，不计入缺陷。

## 已知限制（设计预期，不算缺陷）

1. **TC-08 watchdog kill -9 时 trap EXIT 不跑**：`kill -9` 是非捕获信号，worker 的 `trap EXIT` 不会执行，所以 notes.md 不会写入任何 skipped 标记。这是设计预期行为，TC-08 的断言正是验证此场景（notes.md 应与初始相同）。

2. **100ms 时延断言无自动化**：主 Hook 守门失败路径耗时 ≤ 100ms 的验收标准无法在 e2e 脚本中精确自动化断言（shell 层计时误差过大）。设计接受为手工使用 `time bash .claude/hooks/extract-experience.sh` 验证，已在开发阶段确认。

3. **F-005 onboarding 文档变更不在 e2e 范围**：`context/team/onboarding/agentic-engineer-guide.md` 的新增小节属于文档变更，不适合 e2e bash 脚本验证，已通过独立代码审查流程覆盖。

4. **F-003 prompt.md 静态内容未在 e2e 中验证**：`{{TRANSCRIPT_PATH}}` 占位符和禁止工具的要求是模板文件的静态内容，e2e 未做 grep 断言，属设计接受（开发阶段静态审查已覆盖）。

5. **Linux bash 5 环境未在本次执行验证**：本次测试环境为 macOS bash 3.2.57，Linux 兼容性需在 CI 中补充验证。

## 临时文件清理

测试完成后，脚本验证结果：`临时文件清理验证: OK（/tmp/req-experience-* 为空）`，仓库目录无污染。
