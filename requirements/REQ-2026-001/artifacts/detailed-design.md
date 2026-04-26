---
id: REQ-2026-001
title: 会话结束经验提取 Hook · 详细设计
created_at: "2026-04-26 13:55:00"
refs-detail-design: true
---

# REQ-2026-001 · 详细设计

## 设计依据

- 需求文档（来源：requirements/REQ-2026-001/artifacts/requirement.md:30）
- 技术预研（来源：requirements/REQ-2026-001/artifacts/tech-feasibility.md:9）
- 概要设计（来源：requirements/REQ-2026-001/artifacts/outline-design.md:9）

本设计将概要设计中的模块展开为可直接实现的伪代码、接口契约、错误码、测试矩阵。

---

## 1. 文件清单与最终路径

| 文件 | 类型 | 来源 |
|---|---|---|
| `.claude/settings.json` | 修改（增 SessionEnd hook 条目） | 已有文件 |
| `.claude/hooks/extract-experience.sh` | 新建（M2 主 Hook） | — |
| `.claude/hooks/extract-experience-worker.sh` | 新建（M3 Worker） | — |
| `.claude/hooks/extract-experience.prompt.md` | 新建（M4 Prompt） | — |
| `requirements/REQ-2026-001/artifacts/tests/run-e2e.sh` | 新建（M5 集成测试入口） | — |
| `requirements/REQ-2026-001/artifacts/tests/fixtures/transcript-normal.jsonl` | 新建（fixture） | — |
| `requirements/REQ-2026-001/artifacts/tests/fixtures/transcript-large.jsonl` | 新建（fixture） | — |
| `context/team/onboarding/agentic-engineer-guide.md` | 修改（增小节） | 已有文件 |

---

## 2. M1 · settings.json 修改

在现有 `hooks` 对象同级追加 `SessionEnd` 数组（来源：requirements/REQ-2026-001/artifacts/outline-design.md:117）：

```json
"hooks": {
  "PreToolUse": [
    /* 已有 protect-branch 配置 */
  ],
  "SessionEnd": [
    {
      "matcher": "prompt_input_exit|logout|other",
      "hooks": [
        {
          "type": "command",
          "command": ".claude/hooks/extract-experience.sh"
        }
      ]
    }
  ]
}
```

**关键点**：matcher 故意排除 `clear`（issue #6428 不稳定），不必特意排除 `bypass_permissions_disabled`（场景罕见）。

---

## 3. M2 · extract-experience.sh （主 Hook）

### 3.1 接口契约

| 项 | 值 |
|---|---|
| 输入 | stdin JSON（含 cwd / transcript_path / reason / hook_event_name / session_id） |
| 输出 | exit 0（任何路径都不阻塞） |
| 副作用 | fork 一个后台 worker（最多 1 个） |
| 主进程耗时 | ≤ 100ms（来源：requirements/REQ-2026-001/artifacts/requirement.md:75） |

### 3.2 完整伪代码

```bash
#!/usr/bin/env bash
# .claude/hooks/extract-experience.sh
# SessionEnd Hook 主入口：守门 + fork worker
# 任何异常都 exit 0，不影响用户退出

set -u

# === 1. 同步读 stdin（绕开 macOS async 空 stdin bug #38162）===
HOOK_INPUT="$(cat)"

# === 2. opt-out env 短路 ===
if [[ "${SKIP_EXPERIENCE_HOOK:-0}" == "1" ]]; then
  exit 0
fi

# === 3. 解析 JSON 字段（python3 macOS/Linux 自带）===
parse_field() {
  echo "$HOOK_INPUT" | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('$1', ''))
except Exception:
    pass
" 2>/dev/null
}

CWD="$(parse_field cwd)"
TRANSCRIPT="$(parse_field transcript_path)"

# === 4. 守门：cwd 必须可访问 ===
[[ -z "$CWD" || ! -d "$CWD" ]] && exit 0
cd "$CWD" || exit 0

# === 5. 守门：当前分支必须匹配 feat/req-* ===
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
[[ "$BRANCH" =~ ^feat/req- ]] || exit 0

# === 6. 守门：对应 meta.yaml 必须存在 ===
REQ_ID="$(echo "$BRANCH" | sed -E 's|^feat/req-||')"
META_FILE="$CWD/requirements/REQ-${REQ_ID}/meta.yaml"
[[ -f "$META_FILE" ]] || {
  # fallback: 试 REQ-YYYY-NNN 格式（branch=feat/req-2026-001 已是这格式）
  exit 0
}

# === 7. 守门：phase 不能是 completed ===
PHASE="$(grep -E '^phase:' "$META_FILE" | head -1 | awk '{print $2}')"
[[ "$PHASE" == "completed" ]] && exit 0

# === 8. 校验 transcript_path 存在 ===
[[ -z "$TRANSCRIPT" || ! -f "$TRANSCRIPT" ]] && exit 0

# === 9. fork worker，disown 脱离进程组（绕 #41577）===
NOTES_FILE="$CWD/requirements/REQ-${REQ_ID}/notes.md"
WORKER="$CWD/.claude/hooks/extract-experience-worker.sh"

[[ -x "$WORKER" ]] || exit 0

nohup bash "$WORKER" "$CWD" "$TRANSCRIPT" "$NOTES_FILE" >/dev/null 2>&1 &
disown $!

exit 0
```

### 3.3 异常处理矩阵

| 异常 | 处理 |
|---|---|
| stdin 不是合法 JSON | parse_field 返回空，cwd 校验失败，exit 0 |
| python3 缺失 | parse_field stderr 被丢弃，返回空，exit 0 |
| 当前不在 git 仓库 | git rev-parse 失败，BRANCH 空，exit 0 |
| meta.yaml phase 字段缺失 | grep 返回空，PHASE 空字符串，不等于 completed，继续 |
| worker 脚本不存在或不可执行 | exit 0 |

---

## 4. M3 · extract-experience-worker.sh （Worker）

### 4.1 接口契约

| 项 | 值 |
|---|---|
| 调用方 | 主 Hook nohup fork |
| 入参 | $1=CWD $2=TRANSCRIPT_PATH $3=NOTES_FILE |
| 输出 | 写 NOTES_FILE / 删 tmp / rmdir 锁 |
| 总超时 | 30 秒（来源：requirements/REQ-2026-001/artifacts/requirement.md:76） |
| 退出码 | 任何路径都 exit 0 |

### 4.2 完整伪代码

```bash
#!/usr/bin/env bash
# .claude/hooks/extract-experience-worker.sh
# 后台 worker：截断 transcript + claude -p + 写 notes.md
# 整体最多运行 30 秒，超时被 watchdog 杀掉

set -u

CWD="$1"
TRANSCRIPT_PATH="$2"
NOTES_FILE="$3"

cd "$CWD" || exit 0  # 修 R-9：worker 必须 cd 回 cwd

# === 1. watchdog：30 秒后 kill 整个 worker ===
SELF_PID=$$
(sleep 30 && kill -9 "$SELF_PID" 2>/dev/null) &
WATCHDOG_PID=$!

# 清理函数（覆盖正常退出 + 超时被杀两种路径）
TMP_FILE="/tmp/req-experience-$$-transcript.jsonl"
RESULT_FILE="/tmp/req-experience-$$-result.txt"
LOCK_DIR="${NOTES_FILE}.lock"

cleanup() {
  rm -f "$TMP_FILE" "$RESULT_FILE" 2>/dev/null
  rmdir "$LOCK_DIR" 2>/dev/null
  kill -9 "$WATCHDOG_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

# === 2. 截断 transcript（最近 60 行 ≈ 30 轮）===
# 数字依据：60 行对应 30 轮（来源：requirements/REQ-2026-001/artifacts/tech-feasibility.md:74）
tail -n 60 "$TRANSCRIPT_PATH" > "$TMP_FILE" 2>/dev/null || {
  append_skip_marker "transcript-truncate-failed"
  exit 0
}

# === 3. 调用 claude -p（prompt 中含 transcript 路径）===
PROMPT_FILE="$CWD/.claude/hooks/extract-experience.prompt.md"
[[ -f "$PROMPT_FILE" ]] || {
  append_skip_marker "prompt-template-missing"
  exit 0
}

PROMPT="$(cat "$PROMPT_FILE")"
PROMPT="${PROMPT//\{\{TRANSCRIPT_PATH\}\}/$TMP_FILE}"

# 关键：</dev/null 关 stdin（绕 #7263），--add-dir 让 claude 能 Read tmp
SKIP_EXPERIENCE_HOOK=1 claude -p "$PROMPT" \
  --add-dir "$(dirname "$TMP_FILE")" \
  --output-format text \
  </dev/null \
  > "$RESULT_FILE" 2>&1
CLAUDE_EXIT=$?

# === 4. 判定结果 ===
if [[ "$CLAUDE_EXIT" -ne 0 ]]; then
  append_skip_marker "claude-exit-${CLAUDE_EXIT}"
  exit 0
fi

if [[ ! -s "$RESULT_FILE" ]]; then
  append_skip_marker "empty-output-bug-7263"
  exit 0
fi

# === 5. mkdir 原子锁 + 追加 notes.md ===
acquire_lock || {
  append_skip_marker "notes-busy" "skip-write"
  exit 0
}

write_section "$(cat "$RESULT_FILE")"
exit 0


# ---------- helper functions ----------

acquire_lock() {
  local i
  for i in 1 2 3 4 5; do
    if mkdir "$LOCK_DIR" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

write_section() {
  local content="$1"
  local stamp
  stamp="$(TZ=Asia/Shanghai date +"%Y-%m-%d %H:%M")"
  {
    printf '\n\n## 会话经验（%s）\n\n%s\n' "$stamp" "$content"
  } >> "$NOTES_FILE"
}

append_skip_marker() {
  local reason="$1"
  local skip_write="${2:-}"
  [[ "$skip_write" == "skip-write" ]] && return 0
  acquire_lock || return 0
  local stamp
  stamp="$(TZ=Asia/Shanghai date +"%Y-%m-%d %H:%M")"
  {
    printf '\n\n## 会话经验（%s）\n\n_[hook-skipped: %s]_\n' "$stamp" "$reason"
  } >> "$NOTES_FILE"
}
```

### 4.3 错误码与日志

| 标记 | 触发场景 | 是否进 notes.md |
|---|---|---|
| `transcript-truncate-failed` | tail 命令失败（罕见） | ✅ |
| `prompt-template-missing` | M4 文件缺失（部署事故） | ✅ |
| `claude-exit-N` | claude -p 非零退出 | ✅ |
| `empty-output-bug-7263` | stdout 为空（hit 大 stdin bug） | ✅ |
| `notes-busy` | 5 次 mkdir 锁失败 | ❌（skip-write，避免死循环写入） |
| 30s 超时被 watchdog 杀 | watchdog kill -9 | ❌（trap 不会跑） |

---

## 5. M4 · extract-experience.prompt.md

```markdown
你是「会话经验提取助手」。请阅读以下 transcript 文件并抽取经验：

  {{TRANSCRIPT_PATH}}

## 抽取目标

仅提取以下三类信息：
1. **关键决策**：用户与 AI 之间做出的取舍（选了什么、放弃了什么、依据是什么）
2. **踩过的坑**：错误信息 + 根因 + 解决方式（已验证可解决的）
3. **验证过的事实**：针对 API、文件路径、命令行为、配置项的探查结论（含具体值）

## 输出格式

- markdown 列表，每条 1 句话，必要时附文件路径或命令
- 不复述对话内容
- 不编造未在 transcript 中出现的信息
- 如本轮 transcript 中无可提取的经验，仅输出一行：`_本轮无新经验_`

## 上下文约束

- 不要使用任何工具（你只需 Read transcript）
- 不要写任何文件
- 输出长度 ≤ 1500 字，超出请保留最重要的条目
```

---

## 6. M5 · 集成测试设计

### 6.1 测试矩阵

| TC | 场景 | 输入 | 期望 |
|---|---|---|---|
| TC-01 | 正常会话提取 | 分支 feat/req-XXX + meta.yaml + 真实 transcript | notes.md 末尾增 `## 会话经验（YYYY-MM-DD HH:MM）` 小节 |
| TC-02 | env opt-out | `SKIP_EXPERIENCE_HOOK=1` | notes.md 不变 |
| TC-03 | 非需求分支 | 分支 develop / hotfix/* | notes.md 不变 |
| TC-04 | meta.yaml 缺失 | 分支匹配但目录不存在 | notes.md 不变（无新建） |
| TC-05 | phase=completed | meta.yaml 设置 phase: completed | notes.md 不变 |
| TC-06 | claude -p 失败 | mock claude 退出码 1 | notes.md 末尾 `[hook-skipped: claude-exit-1]` |
| TC-07 | claude -p 输出为空 | mock claude exit 0 + 空 stdout | notes.md 末尾 `[hook-skipped: empty-output-bug-7263]` |
| TC-08 | 超时 | mock claude sleep 60 | worker 30s 后被 kill，notes.md 不变（trap 不跑） |
| TC-09 | 大 transcript | fixture 100 轮 | tail 60 行后正常工作 |
| TC-10 | 并发写 | 同时启动两个 worker | 至少 1 条 `## 会话经验`（允许 notes-busy 一方走 skip-write 路径不写）；并验证 notes.md 文件未被并发写撕裂（可用 line_count 等粗校验） |
| TC-11 | transcript 截断失败 | 直接调 worker 传不存在的 transcript 路径（绕过主 Hook 的 -f 守门） | notes.md 末尾 `[hook-skipped: transcript-truncate-failed]` |
| TC-12 | prompt 模板缺失 | 手工搭最小 workdir，故意不创建 `.claude/hooks/extract-experience.prompt.md` | notes.md 末尾 `[hook-skipped: prompt-template-missing]` |

### 6.2 fixture 设计

- `transcript-normal.jsonl`：约 20 行，含若干典型决策语句
- `transcript-large.jsonl`：100 行，模拟大 transcript

### 6.3 mock claude

测试时用环境变量 `EXPERIENCE_HOOK_CLAUDE_BIN` 覆盖 `claude` 命令，指向一个 stub shell 脚本，让其按测试场景返回不同 exit code / stdout。worker 实际调用 `${EXPERIENCE_HOOK_CLAUDE_BIN:-claude}`。

> 备注：worker 当前伪代码硬写 `claude`，实现时改为 `"${EXPERIENCE_HOOK_CLAUDE_BIN:-claude}"` 以便测试。

---

## 7. M6 · onboarding 文档更新

在 `context/team/onboarding/agentic-engineer-guide.md` 增一小节：

```markdown
### 自动经验提取（SessionEnd Hook）

需求开发会话结束时（按 ctrl-d、关闭终端等），骨架会自动调用一个小 Agent
分析最近对话，把关键决策 / 踩过的坑 / 验证过的事实追加到当前需求的
`requirements/<id>/notes.md`，便于跨会话复盘。

- 仅在 `feat/req-*` 分支 + 对应需求目录存在时触发
- 临时关闭：`export SKIP_EXPERIENCE_HOOK=1`
- 已知限制：`/exit` 命令不触发（Anthropic issue #17885）
```

---

## 8. 时序图（关键路径）

```
User              Claude Code        extract-experience.sh    worker.sh         claude -p
  |                   |                       |                  |                 |
  |  ctrl-d           |                       |                  |                 |
  |------------------>|                       |                  |                 |
  |                   |  SessionEnd (stdin)   |                  |                 |
  |                   |---------------------->|                  |                 |
  |                   |                       |  cat stdin       |                 |
  |                   |                       |  parse cwd/path  |                 |
  |                   |                       |  guard×4         |                 |
  |                   |                       |  nohup fork      |                 |
  |                   |                       |--+               |                 |
  |                   |                       |  | disown        |                 |
  |                   |                       |<-+               |                 |
  |                   |                       |  exit 0          |                 |
  |                   |<----------------------|                  |                 |
  |  prompt 释放       |                       |                  |                 |
  |<------------------|                       |                  |                 |
  |                   |                       |                  | tail 60 lines   |
  |                   |                       |                  | -tmp.jsonl      |
  |                   |                       |                  |                 |
  |                   |                       |                  |  cmd            |
  |                   |                       |                  |---------------->|
  |                   |                       |                  |  result         |
  |                   |                       |                  |<----------------|
  |                   |                       |                  | mkdir lock      |
  |                   |                       |                  | append notes.md |
  |                   |                       |                  | rmdir lock      |
  |                   |                       |                  | exit 0          |
```

---

## 9. 评审准备

待 `detail-design-quality-reviewer` Agent 评审：
- 接口签名 ✅（M2/M3 入参清晰）
- 数据结构 ✅（stdin JSON、notes.md 写入格式）
- 时序图 ✅（第 8 节）
- features.json ✅（见同级 features.json，由本设计派生）

## 10. 待澄清清单

详细设计阶段无新增 OQ。tech-feasibility 中保留的 3 条（macOS timeout / token 计数 / claude -p 递归）已在本设计就地落实方案：

- macOS timeout → 用纯 bash watchdog（M3 第 1 步），零依赖
- token 计数 → 用 60 行 tail 近似，未来可在 prompt 内加 token 上报
- claude -p 递归 → worker 调用时 `SKIP_EXPERIENCE_HOOK=1` 显式短路（M3 第 3 步）
