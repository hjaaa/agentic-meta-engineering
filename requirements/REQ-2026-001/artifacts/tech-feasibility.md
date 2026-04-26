---
id: REQ-2026-001
title: 会话结束经验提取 Hook · 技术可行性评估
created_at: "2026-04-26 10:16:24"
refs-tech-feasibility: true
---

# REQ-2026-001 · 技术可行性评估

## 总结

可行性：**medium**。核心机制（SessionEnd 事件 + transcript_path + claude -p）均有官方支撑，但存在 3 个平台级已知 bug（#38162、#41577、#7263），每个都有 workaround，合并后增加了实现难度和测试覆盖量。无 blocker 级阻碍。

---

## 1. SessionEnd 事件契约

**事件存在性**：官方文档确认 `SessionEnd` 是正式支持的 Hook 事件类型，可在 `settings.json` 的 `hooks` 字段下注册，与现有 `PreToolUse` 配置同构（来源：.claude/settings.json:26）。

**触发时机**：SessionEnd 在会话终止时触发，stdin JSON 的 `reason` 字段区分原因，值为：`clear`（/clear 命令）、`logout`、`prompt_input_exit`（ctrl-d / 关闭终端）、`bypass_permissions_disabled`、`other`。

**已知限制 1 — /exit 不触发**：GitHub issue #17885 和 #35892（2026-03-18）均确认 `/exit` 命令不触发 SessionEnd，Anthropic 已关闭为 not planned。需求场景描述"用户 /clear 或关闭 Claude Code"（来源：requirements/REQ-2026-001/artifacts/requirement.md:35），主流场景（关闭终端、ctrl-d）通过 `prompt_input_exit` reason 覆盖，不作为 blocker。

**已知限制 2 — /clear 触发也不稳定**：issue #6428 报告 `/clear` 不触发 SessionEnd。建议 matcher 配置为 `prompt_input_exit|logout|other`，绕开 /clear 的不确定性。

**Hook 输入格式**：JSON via stdin。字段包括 `session_id`、`transcript_path`（transcript JSONL 绝对路径，格式 `~/.claude/projects/<hash>/sessions/<uuid>.jsonl`）、`cwd`（会话工作目录）、`hook_event_name`（值 `"SessionEnd"`）、`reason`。transcript_path 由平台直接注入，Hook 脚本无需自行推断路径——这是关键设计假设得到验证的结论。

**项目内同类参考**：现有 `.claude/hooks/protect-branch.sh` 仅覆盖 PreToolUse（来源：.claude/hooks/protect-branch.sh:1），无 SessionEnd 实现样例。已废弃的 `[SESSION_END]` process.txt 方案不作为参考（来源：.claude/skills/requirement-progress-logger/SKILL.md:60）。

---

## 2. claude -p CLI 契约

**非交互模式**：`claude -p "<prompt>"` 单次执行后退出，支持 `--output-format text|json|stream-json`（官方 CLI 文档确认，见参考链接）。

**超时控制**：CLI 本身无 `--timeout` 参数，需 shell 端配合。`timeout 30 claude -p ...` 方案在 macOS 不可用（macOS 无原生 `timeout` 命令），需用纯 bash kill watchdog 替代，与 NFR-3 不引入新依赖要求兼容（来源：requirements/REQ-2026-001/artifacts/requirement.md:77）。

**递归 Hook 风险** [待补充]：
- 内容：`claude -p` 在 SessionEnd Hook 内调用时，是否会创建子会话并触发子会话的 SessionEnd，形成递归循环
- 依据：print mode 不触发 tool-use hooks，但 session 生命周期 hooks（SessionEnd）的行为官方文档未明确；`--no-session-persistence` flag 于 2026 年初被移除（issue #20398）
- 风险：若触发递归，notes.md 将被无限追加，进程可能死循环
- 验证时机：开发阶段首次集成测试，观察子进程数量和 notes.md 写入次数；若触发则在子脚本里设 `SKIP_EXPERIENCE_HOOK=1`

**大 stdin 输入 bug**：将 transcript 内容通过 stdin pipe 传给 `claude -p` 时，约 7000 字符以上场景存在返回空输出的已知 bug（issue #7263，open）。缓解方案：不通过 stdin 传入 transcript 内容，改为在 prompt 里提供 `transcript_path` 路径让 claude 用 Read 工具读取，或写入临时文件后用命令替换传参。

---

## 3. Transcript 截断实现

**读取方式**：transcript_path 由 stdin JSON 直接提供，JSONL 格式可用 `tail -n <N>` 取最近 N 轮（一"轮"含 user+assistant 两行，按行数截断时用 `tail -n 60` 对应约 30 轮）。

**Token 计数** [待补充]：
- 内容：如何在 bash 内对 JSONL 内容做 token 级截断（"40K token 谁先到"，来源：requirements/REQ-2026-001/artifacts/requirement.md:69）
- 依据：Claude Code 未暴露内置 tokenizer CLI；常用近似方案是字符数除以 3~4 估算（英文 4 字符/token，中文 1.5 字符/token）
- 风险：估算偏差可能导致截断不足触发大 stdin bug，或截断过激导致经验抽取信息不足
- 验证时机：开发阶段用真实 transcript fixture 测试，验证抽取效果与截断边界

**推荐实现路径**：先用 `tail -n 60 "$TRANSCRIPT_PATH"` 取最近约 30 轮行数，再做字符数估算兜底（字符数超过 120K 则进一步截断），最终写入临时文件传给 `claude -p`，而非通过 stdin pipe。

---

## 4. 后台运行 + 超时实现

**核心问题**：macOS async hook 空 stdin（issue #38162）+ SessionEnd 后台进程被提前杀死（issue #41577）两个 bug 组合，导致直接使用 `"async": true` 或在 nohup 子进程里读 stdin 均不可行。

**推荐方案**（解决两个 bug 的 workaround）：

```bash
# 第一步：主进程同步读 stdin（绕开 #38162，必须在 fork 前完成）
HOOK_INPUT=$(cat)
CWD=$(echo "$HOOK_INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('cwd','.'))" 2>/dev/null || pwd)
TRANSCRIPT=$(echo "$HOOK_INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null || echo "")

# 第二步：fork 后台子进程，disown 脱离进程组（绕开 #41577）
nohup bash "$WORKER_SCRIPT" "$CWD" "$TRANSCRIPT" > /dev/null 2>&1 &
disown $!
```

worker 脚本内部用 `(sleep 30 && kill -9 $WORKER_PID) &` 作为纯 bash 超时看门狗，无需 `timeout` 命令。

**macOS bash 兼容性**：`disown`、`nohup` 在 macOS bash 3.2 可用，`python3` 已内置（macOS 12.3+）。

---

## 5. notes.md 并发写

**风险场景**：同时关闭两个 Claude Code 终端触发两个 SessionEnd，两个 Hook 子进程并发追加同一 `notes.md`。

**flock 不可用**：macOS 无原生 `flock` CLI，与 NFR-3 不引入新依赖要求冲突（来源：requirements/REQ-2026-001/artifacts/requirement.md:77）。

**推荐方案（无依赖）**：用 `mkdir` 原子锁文件：

```bash
LOCK_DIR="${NOTES_FILE}.lock"
until mkdir "$LOCK_DIR" 2>/dev/null; do sleep 0.1; done
trap "rmdir '$LOCK_DIR' 2>/dev/null" EXIT INT TERM
```

`mkdir` 在 POSIX 上是原子操作，macOS/Linux 均兼容，无额外依赖。并发概率低，重试等待开销可忽略。

---

## 风险评估

| # | 类别 | 描述 | 可能性 | 影响 | 缓解策略 |
|---|---|---|---|---|---|
| R-1 | tech | SessionEnd 不触发 /exit（#17885 not planned）、/clear 不稳定（#6428） | high | medium | matcher 指定 prompt_input_exit/logout/other；文档说明已知限制 |
| R-2 | tech | SessionEnd 后台进程被提前杀死（#41577） | high | high | 主进程同步读 stdin；子进程 nohup+disown 脱离进程组 |
| R-3 | tech | macOS async hook 收到空 stdin（#38162） | high | high | 不使用 async:true；主 hook 同步读 stdin 后 fork |
| R-4 | tech | claude -p 大 stdin 输入返回空输出（#7263） | medium | medium | 不走 stdin pipe；用临时文件或路径参数替代 |
| R-5 | tech | claude -p 触发子会话 SessionEnd 形成递归 | low | high | 集成测试验证；触发时在子脚本设 SKIP_EXPERIENCE_HOOK=1 |
| R-6 | ops | macOS 无 timeout 命令，brew coreutils 增加依赖 | medium | low | 纯 bash kill watchdog 替代，零依赖 |
| R-7 | tech | notes.md 并发写撕裂（两个终端同时关闭） | low | low | mkdir 原子锁（POSIX 原子，无依赖） |

---

## 工作量估算

| 子任务 | 内容 | 工时（天） |
|---|---|---|
| 设计确认 | bash 方案验证、workaround 方案选型、集成测试策略 | 0.5 |
| FR-1 | settings.json SessionEnd 注册 | 0.1 |
| FR-2 + FR-7 | 守门脚本（env/branch/meta.yaml/phase 四层短路） | 0.5 |
| FR-3 + 后台方案 | nohup+disown+kill watchdog + stdin 同步读 workaround | 1.0 |
| FR-4 | notes.md 追加逻辑 + mkdir 锁 + 降级写入 | 0.5 |
| FR-5 + FR-6 | Prompt 模板 + transcript 截断（tail + 字符估算） | 0.5 |
| FR-8 | process.txt 隔离验证 | 0.1 |
| 测试 | fixture 构造 + 端到端验证（守门场景 × 5 + 超时 + 并发 + 递归检验） | 1.5 |
| 文档更新 | onboarding-guide.md 小节 | 0.3 |
| **合计** | | **5.0 天** |

---

## 前置条件

1. 在目标 Claude Code 版本实测 `prompt_input_exit` reason 是否稳定触发（与 issue #17885 bug 对比验证）
2. 确认 `claude -p` 子会话是否触发 SessionEnd（递归风险，集成测试验证）
3. 确认 macOS timeout 方案：纯 bash kill watchdog（推荐，零依赖）还是 brew coreutils（需用户明确接受依赖）[待用户确认]

---

## 外部参考

- Claude Code Hooks 官方文档：https://code.claude.com/docs/en/hooks
- Claude Code CLI 参考（headless 模式）：https://code.claude.com/docs/en/headless
- GitHub issue #6428（/clear 不触发 SessionEnd）：https://github.com/anthropics/claude-code/issues/6428
- GitHub issue #17885（/exit 不触发 SessionEnd，not planned）：https://github.com/anthropics/claude-code/issues/17885
- GitHub issue #35892（/exit 不触发 SessionEnd 后续讨论）：https://github.com/anthropics/claude-code/issues/35892
- GitHub issue #38162（macOS async hook 空 stdin）：https://github.com/anthropics/claude-code/issues/38162
- GitHub issue #41577（SessionEnd 后台进程被提前杀死）：https://github.com/anthropics/claude-code/issues/41577
- GitHub issue #7263（claude -p 大 stdin 空输出）：https://github.com/anthropics/claude-code/issues/7263
- GitHub issue #20398（--no-session-persistence 已移除）：https://github.com/anthropics/claude-code/issues/20398

---

## 待澄清清单

下列条目对应正文中已展开的标记（含完整四要素或决策选项），此处仅作汇总索引：

1. macOS timeout 命令处理方式（见正文「2. claude -p CLI 契约 · 超时控制」段）：推荐纯 bash kill watchdog（零依赖），需确认团队是否接受此方案
2. transcript token 计数方式（见正文「3. Transcript 截断实现 · Token 计数」段，含完整假设四要素）：bash 内如何精确或近似计算 JSONL 内容 token 数量，影响 FR-6 截断精度
3. claude -p 子会话 SessionEnd 递归触发行为（见正文「2. claude -p CLI 契约 · 递归 Hook 风险」段，含完整假设四要素）：需集成测试验证，若触发需在调用处设 SKIP_EXPERIENCE_HOOK=1
