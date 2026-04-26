---
id: REQ-2026-001
title: 会话结束经验提取 Hook · 概要设计
created_at: "2026-04-26 10:25:00"
refs-outline-design: true
---

# REQ-2026-001 · 概要设计

## 设计目标

根据需求（来源：requirements/REQ-2026-001/artifacts/requirement.md:30）和技术预研（来源：requirements/REQ-2026-001/artifacts/tech-feasibility.md:9）的结论，本设计需要：

1. **不阻塞退出**：主进程 ≤ 100ms，所有耗时操作（claude -p 调用、notes.md 写入）在后台子进程完成
2. **绕开 4 个已知 bug**：#38162（async 空 stdin）/ #41577（后台被杀）/ #7263（大 stdin 空输出）/ #17885（/exit 不触发）
3. **零新增依赖**：不引入 brew coreutils、不引入 Python 第三方包，仅使用 macOS / Linux 自带的 bash / python3 / mkdir / nohup / disown
4. **守门严格**：四层短路（env / branch / meta.yaml / phase）任一未过则静默退出

## 架构概览

```
┌─────────────────────┐
│ Claude Code 主进程  │   用户 ctrl-d / 关闭终端
└──────────┬──────────┘
           │ SessionEnd 事件 (stdin JSON)
           ▼
┌────────────────────────────────────────────────┐
│ extract-experience.sh （主 Hook 脚本，同步）   │
│  ① 同步读 stdin (绕开 #38162)                  │
│  ② 守门四层短路（env / branch / meta / phase） │
│  ③ nohup fork worker 子进程，disown            │
│  ④ exit 0（≤100ms 让主进程释放）              │
└──────────┬─────────────────────────────────────┘
           │ 后台 fork
           ▼
┌────────────────────────────────────────────────┐
│ extract-experience-worker.sh （后台 worker）   │
│  ① mkdir 锁 notes.md                           │
│  ② tail -n 60 transcript.jsonl > tmp           │
│  ③ (sleep 30 && kill -9 $$) & 看门狗           │
│  ④ claude -p "$(cat prompt.md)" --input-file   │
│     tmp.jsonl --output-format text             │
│  ⑤ 成功 → append notes.md ## 会话经验小节      │
│     失败/超时 → append [hook-skipped: <原因>] │
│  ⑥ rmdir 锁                                    │
└────────────────────────────────────────────────┘
```

## 模块划分

| 模块 | 路径 | 职责 | 行数预估 |
|---|---|---|---|
| **M1 配置注册** | `.claude/settings.json` | 在 `hooks.SessionEnd` 注册 matcher + command | +6 |
| **M2 主 Hook 脚本** | `.claude/hooks/extract-experience.sh` | 同步读 stdin / 守门 / fork worker | ~60 |
| **M3 Worker 脚本** | `.claude/hooks/extract-experience-worker.sh` | 截断 / 调用 claude -p / 写 notes.md / 异常降级 | ~120 |
| **M4 Prompt 模板** | `.claude/hooks/extract-experience.prompt.md` | 抽取指令模板，便于团队迭代调优 | ~40 |
| **M5 集成测试** | `requirements/REQ-2026-001/artifacts/tests/` | fixture 构造 + 端到端验证脚本 | ~150 |
| **M6 文档更新** | `context/team/onboarding/agentic-engineer-guide.md` | 增"自动经验提取"说明小节 | +20 |

总代码量约 **400 行**（含测试），符合 tech-feasibility 估算的 5 工时天。

## 关键流程

### 主流程（正常路径）

```
T+0ms     SessionEnd 触发
T+1ms     extract-experience.sh 启动
T+5ms     同步 cat stdin → HOOK_INPUT
T+10ms    python3 解析 JSON 取 cwd / transcript_path / reason
T+15ms    守门四层（env / branch=feat/req-* / meta.yaml 存在 / phase != completed）
T+20ms    nohup bash worker.sh "$@" >/dev/null 2>&1 &
T+25ms    disown
T+30ms    exit 0  ← 主进程释放，用户感知不到
T+100ms+  worker 后台运行，最多 30s
```

### Worker 流程

数字依据：60 行对应"最近约 30 轮"（来源：requirements/REQ-2026-001/artifacts/tech-feasibility.md:74）；30 秒超时（来源：requirements/REQ-2026-001/artifacts/requirement.md:76）。

1. **加锁**：`mkdir "${NOTES_FILE}.lock"`，失败则 sleep 0.1 重试，最多 5 次
2. **截断**：`tail -n 60 "$TRANSCRIPT_PATH" > /tmp/req-2026-001-worker-$$.jsonl`
3. **看门狗**：`(sleep 30 && kill -9 $$) &`，记录 watchdog PID 用于完成时清理
4. **调用**：`claude -p "$(cat prompt.md)\n\nTRANSCRIPT_PATH: $TMP_FILE" --output-format text > /tmp/result-$$.txt 2>&1`
   - **不**通过 stdin pipe 传 transcript 内容（绕开 #7263）
   - **不**用 `--allowed-tools` 收紧（只读场景，不需要写工具）
   - 在 prompt 里写"请用 Read 工具读取上述文件并抽取经验"
5. **判定**：根据 exit code + result.txt 内容长度判定成败
6. **写入 notes.md**（详见下节"接口契约"）
7. **清理**：删 tmp、rmdir 锁、kill watchdog

### 异常路径

| 场景 | worker 处理 |
|---|---|
| stdin JSON 解析失败 | 主 Hook 层就 exit 0，不走 worker |
| transcript_path 文件不存在 | worker 写 `[hook-skipped: transcript not found]` |
| claude -p 退出非零 | worker 写 `[hook-skipped: claude exit <code>: <stderr 头 100 字符>]` |
| claude -p 输出为空 | worker 写 `[hook-skipped: empty output, possibly stdin bug #7263]` |
| 30 秒超时（被 watchdog 杀） | worker 在 trap EXIT 处理写 `[hook-skipped: timeout 30s]` |
| mkdir 锁 5 次都失败 | worker 写 `[hook-skipped: notes.md busy]` 到日志（不污染 notes.md） |

## 接口契约

### Hook 输入（来自 Claude Code）

stdin JSON（来源：requirements/REQ-2026-001/artifacts/tech-feasibility.md:25）：
```json
{
  "session_id": "uuid",
  "transcript_path": "/Users/.../sessions/<uuid>.jsonl",
  "cwd": "/Users/.../agentic-meta-engineering",
  "hook_event_name": "SessionEnd",
  "reason": "prompt_input_exit"
}
```

### 配置注册（settings.json）

```json
"hooks": {
  "PreToolUse": [...],
  "SessionEnd": [
    {
      "matcher": "prompt_input_exit|logout|other",
      "hooks": [
        {"type": "command", "command": ".claude/hooks/extract-experience.sh"}
      ]
    }
  ]
}
```

### notes.md 写入格式

成功路径：
```markdown
## 会话经验（2026-04-26 14:32）
<claude -p 输出，原样追加，不再加工>
```

失败/降级路径（同样小节标题，便于审计）：
```markdown
## 会话经验（2026-04-26 14:32）
_[hook-skipped: <原因>]_
```

格式约束（来源：requirements/REQ-2026-001/artifacts/requirement.md:96）：
- 小节标题 `## 会话经验（YYYY-MM-DD HH:MM）` 作为后续 `/knowledge:extract-experience` 的解析锚点
- 时间戳取**写入 notes.md 当下**的东八区时间，非会话开始时间
- append 模式，绝不覆盖

### claude -p 调用契约

```bash
claude -p "$(cat .claude/hooks/extract-experience.prompt.md)" \
  --output-format text \
  --add-dir "$CWD" \
  </dev/null \
  > /tmp/result-$$.txt 2>&1
```

- `--add-dir "$CWD"` 让 claude 能读到 transcript 路径
- `</dev/null` 显式关闭 stdin（绕开 #7263 大 stdin 空输出 bug）
- prompt 内容里包含具体 transcript_path 路径，让 claude 自行 Read

### Prompt 模板（M4）骨架

```
你是「会话经验提取助手」。请阅读以下 transcript 文件：

  {{TRANSCRIPT_PATH}}

提取本轮会话中的：
1. 关键决策（不含原因的决定 / 选项之间的取舍依据）
2. 踩过的坑（错误信息 + 根因 + 解决方式）
3. 验证过的事实（针对 API / 文件 / 行为的探查结论）

输出格式：
- 用 markdown 列表，每条 1 句话
- 不要复述对话内容
- 不要编造信息
- 如果对话中无可提取的经验，仅输出一行 "_本轮无新经验_"
```

## 技术选型理由（沿用 tech-feasibility 决策）

| 决策 | 选择 | 弃选 |
|---|---|---|
| Hook 异步模式 | 主进程同步 + nohup fork + disown | `"async": true`（#38162） |
| transcript 传递方式 | --add-dir + prompt 含路径 + claude 自行 Read | stdin pipe（#7263） |
| 超时控制 | bash `(sleep 30 && kill -9) &` | `timeout` CLI（macOS 无） |
| 文件锁 | `mkdir` 原子锁 | `flock`（macOS 无原生） |
| 退出事件 matcher | `prompt_input_exit\|logout\|other` | 默认全匹配（/exit /clear 不稳定） |
| Prompt 载体 | 独立 `.prompt.md` 文件 | 内嵌在 sh 里（不便于调优） |

## 风险与应对（继承 tech-feasibility R-1 ~ R-7）

本节不重复 7 条风险表，仅追加**设计层面的新风险**：

- **R-8 worker 子进程僵尸**：watchdog kill -9 后子进程可能未被回收 → 用 `wait` + `trap EXIT` 兜底
- **R-9 claude -p 在 worker 里调用，CWD 已切换**：claude 内部 git 查询会失败 → 在 worker 第一行 `cd "$CWD"`
- **R-10 prompt 模板变更回滚困难**：模板独立文件 + git 版本化（M4 设计），团队可 PR 迭代

## 评审

待 `outline-design-quality-reviewer` Agent 评审。Phase 4 评审通过后方可进入详细设计。

## 待澄清清单

本概要设计无新增需要用户确认或补充假设的事项。tech-feasibility 中保留的 3 条 OQ（macOS timeout 方案、token 计数、claude -p 递归触发）在详细设计阶段一并落实。
