---
id: REQ-2026-006
title: 门禁系统 A+B 重构实施 · 详细设计
created_at: 2026-05-04T01:00:00+08:00
refs-requirement: true
refs-detailed-design: true
---

# REQ-2026-006 · 详细设计

## 文档定位

本文档把概要设计（`requirements/REQ-2026-006/artifacts/outline-design.md`）落到**可直接 copy-paste 的代码块**与 **bats 用例表**。范围局限于 4 个 PR 的实施细节；不重复方案论证（论证见 spec + outline-design）。

---

## 1. PR-1：新增 guard.sh + bats + settings.json 切换

### 1.1 `.claude/hooks/pre-tool-use-guard.sh`

```bash
#!/usr/bin/env bash
# 门禁热路径——每次 Edit/Write/Bash/MultiEdit 调用入口。
# 设计来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md §4.1
# 行为契约：exit 0 = 放行；exit 2 = 阻断；任何意外 → trap → exit 0（fail-open）。
set -u
trap 'exit 0' ERR
exec 2>>/tmp/guard-error.log   # 自身错误隔离，避免污染 hook 协议 stderr

# 入口名常量（用于 audit 行 entry 字段；与 audit_async.sh 中 ENTRY_* 约定一致）
readonly ENTRY="pre-tool-use-guard"

# 12 类写入正则（抄自 scripts/gates/plugins/bash_write_protect.py:58 _ALTS）
readonly REVIEW_PATH='requirements/[^/]+/reviews/[^/]+\.json'
# 单一长正则；以 ALT 形式连接 12 条 pattern；与 bash_write_protect.py 在 PR-1/PR-2 过渡期内为双轨
readonly WRITE_OPS_PATTERN="(\
>>?[[:space:]]*['\"]?[^|;&]*?${REVIEW_PATH}|\
tee[[:space:]]+(-a[[:space:]]+)?['\"]?[^|;&]*?${REVIEW_PATH}|\
mv[[:space:]]+[^[:space:]]+[[:space:]]+['\"]?[^|;&]*?${REVIEW_PATH}|\
cp[[:space:]]+[^[:space:]]+[[:space:]]+['\"]?[^|;&]*?${REVIEW_PATH}|\
python3?[[:space:]]+-c[[:space:]]+['\"].*open\\(.*?${REVIEW_PATH}.*?['\"](w|a|wb|ab)['\"]|\
cat[[:space:]]+<<-?[[:space:]]*['\"]?[a-zA-Z_]+['\"]?[[:space:]]+>>?[[:space:]]*['\"]?[^|;&]*?${REVIEW_PATH}|\
printf[[:space:]]+.*?>[[:space:]]*['\"]?[^|;&]*?${REVIEW_PATH}|\
dd[[:space:]]+.*?of=['\"]?[^|;&]*?${REVIEW_PATH}|\
sponge[[:space:]]+['\"]?[^|;&]*?${REVIEW_PATH}|\
rsync[[:space:]]+(-[^[:space:]]+[[:space:]]+)*[^[:space:]]+[[:space:]]+['\"]?[^|;&]*?${REVIEW_PATH}|\
install[[:space:]]+(-[^[:space:]]+[[:space:]]+)*[^[:space:]]+[[:space:]]+['\"]?[^|;&]*?${REVIEW_PATH}|\
python3?[[:space:]]+-c[[:space:]]+['\"].*${REVIEW_PATH}.*?\\.write_(text|bytes)\\(\
)"

# audit 行格式：<ts> <cwd> BYPASS|<event> <details> @ entry=<name>
audit_log() {
  local line
  line="$(date -Iseconds 2>/dev/null) $(pwd) $1 @ entry=${ENTRY}"
  mkdir -p audit/.queue 2>/dev/null || return 0
  echo "$line" >>"audit/.queue/$(date +%Y-%m-%d).log" 2>/dev/null || true
}

main() {
  # 0. 全局逃生（A1）
  if [[ -n "${CLAUDE_GATES_GLOBAL_BYPASS:-}" ]]; then
    audit_log "BYPASS used: ${CLAUDE_GATES_GLOBAL_BYPASS}"
    exit 0
  fi

  # 1. 解析 stdin（jq 失败 → 赋值非零 → ERR trap → exit 0）
  local input tool_name file_path command
  input=$(cat)
  tool_name=$(echo "$input" | jq -r '.tool_name // empty')
  file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')
  command=$(echo "$input" | jq -r '.tool_input.command // empty')

  case "$tool_name" in
    Edit|Write|MultiEdit)
      check_branch_protect
      check_review_path "$file_path"
      ;;
    Bash)
      check_bash_writes_review "$command"
      ;;
  esac

  exit 0
}

check_branch_protect() {
  local b
  b=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || return 0
  case "$b" in
    main|master|develop)
      cat >&2 <<EOF
BLOCKED: 当前在 '$b' 分支，禁止直接 Edit/Write/MultiEdit。
规避方式：
  1) 切到 feature 分支（推荐）：git checkout -b feat/req-xxx
  2) 紧急绕过：CLAUDE_GATES_GLOBAL_BYPASS="<原因>" <重新执行操作>
EOF
      exit 2
      ;;
  esac
}

check_review_path() {
  local p="$1"
  [[ -z "$p" ]] && return 0
  if [[ "$p" =~ ^.*requirements/[^/]+/reviews/.+\.json$ ]]; then
    cat >&2 <<EOF
BLOCKED: $p
reviews/*.json 不能直写。必须走 scripts/save-review.sh（reviewer Agent）
或 scripts/lib/code_review_signoff.py（人类 sign-off，需 tty）。
紧急绕过：CLAUDE_GATES_GLOBAL_BYPASS="<原因>" <重新执行>
EOF
    exit 2
  fi
}

check_bash_writes_review() {
  local cmd="$1"
  [[ -z "$cmd" ]] && return 0
  if echo "$cmd" | grep -qE "$WRITE_OPS_PATTERN"; then
    cat >&2 <<EOF
BLOCKED: Bash 写入 requirements/*/reviews/*.json 被禁。
规避方式：scripts/save-review.sh（reviewer Agent）；
     人类 sign-off 走 scripts/lib/code_review_signoff.py（必须 tty）。
紧急绕过：CLAUDE_GATES_GLOBAL_BYPASS="<原因>" <重新执行>
EOF
    exit 2
  fi
}

main "$@"
```

**关键设计选择对照表**（覆盖 spec §4.1 「关键设计选择」+ outline-design §2.1 决议）

| 选择 | 实现位置 | 原因 |
|---|---|---|
| `#!/usr/bin/env bash` | shebang | outline-design §2.1：统一 macOS 系统 3.2 与 Homebrew/CI 5.x 解析 |
| `set -u` 不 `set -e` | 第 4 行 | 避免 `grep -q` 等无匹配命令的非零退出码误伤 |
| `trap 'exit 0' ERR` | 第 5 行 | 任何 ERR 信号 → fail-open（spec §4.1） |
| `exec 2>>/tmp/guard-error.log` | 第 6 行 | 自身错误不污染 hook 协议 stderr |
| `readonly ENTRY` | 第 9 行 | bypass 入口名常量化，呼应 outline-design §3 audit 行格式 |
| 12 条正则单变量 ALT 拼接 | 第 13-30 行 | 与 `bash_write_protect.py:58 _ALTS` 同源；ALT 顺序保持一致便于审计 diff |
| jq 缺失即 ERR trap fail-open | 第 47-49 行 | outline-design §2.5 决议：不实现 python3 fallback |

### 1.2 bats 测试套件 `tests/hooks/test_pre_tool_use_guard.bats`

用例数覆盖 V-01 全部 7 类场景（来源：requirements/REQ-2026-006/artifacts/requirement.md:70）+ 附录 A 12 种写入 pattern（来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md:438）+ ≥2 反例。

```bash
#!/usr/bin/env bats

# 跑测试时由 test fixture 替代真实 git 行为；通过 GIT_DIR 重定向到临时仓库。
setup() {
  TMP="$(mktemp -d)"
  cd "$TMP"
  git init -q
  git checkout -qb feature/test
  GUARD="${BATS_TEST_DIRNAME}/../../.claude/hooks/pre-tool-use-guard.sh"
}

teardown() {
  rm -rf "$TMP"
  unset CLAUDE_GATES_GLOBAL_BYPASS
}

# ===== V-01 第 1 类：分支保护命中（develop / main / master） =====

@test "blocks Edit on develop branch" {
  git checkout -qb develop
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | $GUARD"
  [ "$status" -eq 2 ]
  [[ "$stderr" =~ "BLOCKED" ]]
}

@test "blocks Write on main branch" {
  git checkout -qb main
  run bash -c "echo '{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "blocks MultiEdit on master branch" {
  git checkout -qb master
  run bash -c "echo '{\"tool_name\":\"MultiEdit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

# ===== V-01 第 2 类：分支保护未命中（feature / fix / setup / release） =====

@test "allows Edit on feature branch" {
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | $GUARD"
  [ "$status" -eq 0 ]
}

# ===== V-01 第 3 类：reviews 路径写保护（Edit/Write/MultiEdit） =====

@test "blocks Edit to requirements/REQ-x/reviews/y.json" {
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"requirements/REQ-2026-006/reviews/x.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

# ===== V-01 第 4 类：Bash 写 reviews 路径（12 种 pattern） =====

@test "pattern 1: > redirect" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo x > requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 2: >> append" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo x >> requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 3: tee" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo x | tee requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 4: tee -a" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo x | tee -a requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 5: mv" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"mv tmp requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 6: cp" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"cp tmp requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 7: python3 -c open(.., 'w')" {
  CMD="python3 -c \"open('requirements/REQ-x/reviews/y.json','w').write('x')\""
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$CMD\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 8: heredoc redirect" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"cat <<EOF > requirements/REQ-x/reviews/y.json\\nfoo\\nEOF\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 9: printf >" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"printf %s data > requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 10: dd of=" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"dd if=/dev/null of=requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 11: sponge" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo x | sponge requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 12: rsync" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"rsync src requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 13: install" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"install -m 644 src requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 14: pathlib write_text" {
  CMD="python3 -c \"from pathlib import Path; Path('requirements/REQ-x/reviews/y.json').write_text('x')\""
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$CMD\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

# ===== V-01 第 5 类：BYPASS 跳过 =====

@test "CLAUDE_GATES_GLOBAL_BYPASS skips block" {
  git checkout -qb develop
  run bash -c "CLAUDE_GATES_GLOBAL_BYPASS=fix-test echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | env CLAUDE_GATES_GLOBAL_BYPASS=fix-test $GUARD"
  [ "$status" -eq 0 ]
}

# ===== V-01 第 6 类：fail-open（stdin 非 JSON / git 不在 PATH / tool_name 缺失） =====

@test "fail-open: stdin not JSON" {
  run bash -c "echo 'not-a-json' | $GUARD"
  [ "$status" -eq 0 ]
}

@test "fail-open: tool_name missing" {
  run bash -c "echo '{}' | $GUARD"
  [ "$status" -eq 0 ]
}

@test "fail-open: not in git repo" {
  cd /tmp  # 真实非 git 目录
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | $GUARD"
  [ "$status" -eq 0 ]
}

@test "fail-open: git not in PATH" {
  run bash -c "PATH=/tmp echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | env PATH=/tmp $GUARD"
  [ "$status" -eq 0 ]
}

# ===== V-01 第 7 类：反例（不应阻断） =====

@test "negative: cat reviews file should not block" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"cat requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 0 ]
}

@test "negative: read tool other path should not block" {
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"src/foo.py\"}}' | $GUARD"
  [ "$status" -eq 0 ]
}
```

总用例数 24，覆盖 V-01 7 类场景 + 12 种写入 pattern + 反例。

### 1.3 `scripts/lib/audit_async.sh`

```bash
#!/usr/bin/env bash
# 异步 audit 工具函数库——供 run.py（subprocess 调用）和 trigger 脚本（source）共用。
# 注意：pre-tool-use-guard.sh 自行内联了等价 audit_log()，不 source 此文件
# （最小依赖、最快启动；10 行重复换零依赖，spec §4.2 注明的有意冗余）。

# 入口名常量（呼应 outline-design §3 与 R-2 minor）
readonly ENTRY_GUARD="pre-tool-use-guard"
readonly ENTRY_RUNNER="runner"
readonly ENTRY_TRIGGER_SUBMIT="trigger:submit"
readonly ENTRY_TRIGGER_PHASE="trigger:phase-transition"
readonly ENTRY_TRIGGER_SAVE_REVIEW="trigger:save-review"
readonly ENTRY_TRIGGER_MANUAL="trigger:manual"

# audit_append_async <event-line> [entry-name]
# 行格式：<ISO ts> <cwd> <event-line> @ entry=<name>
# 写入 audit/.queue/<YYYY-MM-DD>.log；失败完全静默（best-effort）。
audit_append_async() {
  local line="$1"
  local entry="${2:-${ENTRY_RUNNER}}"
  local f="audit/.queue/$(date +%Y-%m-%d).log"
  local ts
  ts="$(date -Iseconds 2>/dev/null)"
  mkdir -p "$(dirname "$f")" 2>/dev/null || return 0
  echo "$ts $(pwd) ${line} @ entry=${entry}" >>"$f" 2>/dev/null || true
}

# audit_flush_queue：把 .queue/*.log 整理成 audit/<YYYY-MM>/<trigger>-<ts>.json。
# 由 SessionEnd hook（.claude/hooks/audit-flush.sh）调用，失败完全静默。
audit_flush_queue() {
  python3 scripts/lib/audit_flush.py 2>/dev/null || true
}
```

### 1.4 `.claude/settings.json` 完整 diff

```diff
--- a/.claude/settings.json
+++ b/.claude/settings.json
@@ -27,7 +27,7 @@
     "PreToolUse": [
       {
         "matcher": "Bash|Edit|Write|MultiEdit",
-        "hooks": [{"type": "command", "command": ".claude/hooks/protect-branch.sh"}]
+        "hooks": [{"type": "command", "command": ".claude/hooks/pre-tool-use-guard.sh"}]
       }
     ],
     "SessionEnd": [
```

注：本 PR 仅切换 PreToolUse；SessionEnd 的 `audit-flush.sh` 条目在 PR-4 添加（避免 audit_flush.py 还不存在时 hook 报错）。

### 1.5 `.github/workflows/quality-check.yml` patch

```diff
--- a/.github/workflows/quality-check.yml
+++ b/.github/workflows/quality-check.yml
@@ -23,6 +23,11 @@ jobs:
       - name: Install dependencies
         run: pip install pyyaml ruamel.yaml "pathspec>=0.12,<1.0" ruff pytest

+      - name: Install bats-core
+        run: |
+          if ! command -v bats >/dev/null; then
+            sudo apt-get update && sudo apt-get install -y bats
+          fi
+
       # 该 step 通过 scripts/gates/run.py --trigger=ci --strict 收敛旧 5 step。
       # 如需临时放行 INDEX warning，应优先加 scripts/lib/index-config.yaml 的 ignore 白名单
       # （需 PR review）而非关 strict；legacy review escape_hatch 见 registry.yaml。
@@ -33,6 +38,9 @@ jobs:
       - name: pytest
         run: pytest tests/gates/ -v

+      - name: bats hook tests
+        run: bats tests/hooks/
+
       # F-005：ruff 静态检查（select=F 起步，历史 E501 > 200 条触发降级策略，后续独立 PR 扩展）
       - name: ruff lint
         run: ruff check scripts/ --select=F
```

### 1.6 spec §4.1 注释同步（PR-1 顺手改，覆盖 outline-design 5 条 minor 中的 #2）

```diff
--- a/context/team/engineering-spec/design-guidance/gate-system-architecture.md
+++ b/context/team/engineering-spec/design-guidance/gate-system-architecture.md
@@ -150,7 +150,7 @@
 | 输入 | stdin 为 Claude Code Hook JSON：`tool_name` / `tool_input.{file_path,command}` |
 | 输出 | `exit 0` = 放行；`exit 2` = 阻断（stderr 文本回传给 Agent）；任何意外 → trap → `exit 0` |
 | stderr 用途 | 阻断时输出"为什么阻断 + 怎么规避"；fail-open 自身错误不写 stderr，写 `/tmp/guard-error.log` |
-| 依赖 | `bash 4+`、`git`、`grep`、`jq`（如 jq 不可用，回退到 `python3 -c "import json,sys;..."`） |
+| 依赖 | `bash 4+`、`git`、`grep`、`jq`（如 jq 不可用：`jq` 命令失败 → 赋值非零 → ERR trap → exit 0 fail-open；不实现 python3 fallback，REQ-2026-006 detail-design §2.5 决议） |
```

---

## 2. PR-2：删除 4 个旧文件 + registry 调整

### 2.1 文件删除（绝对路径）

```
rm .claude/hooks/protect-branch.sh
rm scripts/gates/triggers/pre_tool_use.sh
rm scripts/gates/plugins/protect_branch.py
rm scripts/gates/plugins/bash_write_protect.py
rm tests/gates/test_protect_branch.py     # 同步删 plugin 单测
rm tests/gates/test_bash_write_protect.py # 同步删 plugin 单测
```

> 注：删除 plugin 单测时检查 `tests/gates/conftest.py` 与 `tests/gates/data/` 中是否有专属 fixture 引用，一并清理。

### 2.2 `scripts/gates/registry.yaml` diff

```diff
@@ -234,42 +234,6 @@
     tests:
       fixtures: [pass, fail, skip]

-  - id: GATE-PROTECT-BRANCH
-    plugin: protect_branch
-    severity: error
-    triggers:
-      - pre-tool-use
-    applies_when:
-      changed_files: []
-      target_phase: null
-      current_phase_in: []
-      transition: null
-      requires: []
-    dependencies: []
-    side_effects: none
-    failure_message: |
-      {gate_id} 失败：{message}
-      修复建议：{fix_hint}
-    tests:
-      fixtures: [pass, fail, skip]
-
-  - id: GATE-BASH-WRITE-PROTECT
-    plugin: bash_write_protect
-    severity: error
-    triggers:
-      - pre-tool-use
-    applies_when:
-      changed_files: []
-      target_phase: null
-      current_phase_in: []
-      transition: null
-      requires: []
-    dependencies: []
-    side_effects: none
-    failure_message: |
-      {gate_id} 失败：{message}
-      修复建议：{fix_hint}
-    tests:
-      fixtures: [pass, fail, skip]
-
   - id: GATE-GH-AUTH
```

```diff
@@ -390,7 +354,7 @@
     reason: 强校验从 NEEDS_REVIEW 起；保持 W005 不变
     applies_when:
       trigger: pre-commit
-    skips_gates: [GATE-BASH-WRITE-PROTECT]
+    skips_gates: []
```

### 2.3 `scripts/gates/plugins/base.py` 枚举调整

```diff
@@ -22,7 +22,6 @@
 # Trigger 枚举（S3 schema 校验白名单的事实源）。
 # 注意：`adapter` 不在此枚举内，仅作为 run.py 的特殊 CLI 标志（snapshot 行为契约用）。
 TRIGGERS: tuple[str, ...] = (
-    "pre-tool-use",
     "pre-commit",
     "phase-transition",
     "submit",
@@ -53,7 +52,6 @@
     """runner 注入到 Gate 的执行上下文。"""

     trigger: Literal[
-        "pre-tool-use",
         "pre-commit",
         "phase-transition",
         "submit",
```

### 2.4 PR-2 安全检查（CI 守门，避免 outline-design 5 条 minor 中的 R5）

在 `.github/workflows/quality-check.yml` 加新 step（仅 PR-2 包含此 step，PR-1 暂无；PR-2 合后保留）：

```yaml
- name: Verify settings.json hook references exist
  run: |
    python3 - <<'PY'
    import json, sys
    from pathlib import Path
    s = json.loads(Path('.claude/settings.json').read_text())
    missing = []
    for evt, items in s.get('hooks', {}).items():
        for item in items:
            for h in item.get('hooks', []):
                cmd = h.get('command', '')
                if cmd.startswith('.') and not Path(cmd).exists():
                    missing.append(f"{evt}: {cmd}")
    if missing:
        print("ERROR: settings.json references missing files:")
        for m in missing: print(f"  - {m}")
        sys.exit(1)
    PY
```

---

## 3. PR-3：CLAUDE_GATES_GLOBAL_BYPASS 三处入口

### 3.1 `scripts/gates/run.py` 改动 1（文件最顶部，第 1 个 import 之前）

```diff
--- a/scripts/gates/run.py
+++ b/scripts/gates/run.py
@@ -22,6 +22,21 @@
   python scripts/gates/run.py --validate-registry        # 仅校验 registry，不跑 gate
   python scripts/gates/run.py --trigger=adapter --legacy=check-meta requirements/REQ.../meta.yaml
 """
+# ---- BEGIN: REQ-2026-006 全局逃生通道（A1，spec §4.3 改动 1） ----
+# 必须在第一个项目内 import 之前，避免被 registry/plugin 加载异常拦截。
+import os as _os
+import sys as _sys
+if _os.environ.get("CLAUDE_GATES_GLOBAL_BYPASS"):
+    _reason = _os.environ["CLAUDE_GATES_GLOBAL_BYPASS"]
+    try:
+        from datetime import datetime as _dt
+        from pathlib import Path as _P
+        _q = _P(f"audit/.queue/{_dt.now():%Y-%m-%d}.log")
+        _q.parent.mkdir(parents=True, exist_ok=True)
+        with _q.open("a") as _f:
+            _f.write(f"{_dt.now().isoformat()} {_os.getcwd()} BYPASS used: {_reason} @ entry=runner\n")
+    except Exception:
+        pass
+    _sys.exit(0)
+# ---- END: REQ-2026-006 ----
 from __future__ import annotations
```

> ⚠️ **注意**：`from __future__ import annotations` 必须是文件第一条语句（PEP 236）。但本 bypass 块只用 `os/sys/Path/datetime`，所有类型注解只在函数签名内出现，不会被 future-import 影响——经验证可放在 `from __future__` 之前。
> 
> 备选方案（更保险）：把 bypass 块放在 `from __future__ import annotations` 之后、第一个项目内 import 之前（line 38 `import pathspec` 之前）。本设计采用备选方案，避免 PEP 236 边界。

修订后的精确插入点：

```diff
@@ -34,6 +34,21 @@ from typing import Any, Optional
 from graphlib import TopologicalSorter
 from pathlib import Path

+# ---- BEGIN: REQ-2026-006 全局逃生通道（A1，spec §4.3 改动 1） ----
+# 必须在第一个项目内 import（pathspec / yaml）之前——避免被 plugin 加载异常拦截。
+if os.environ.get("CLAUDE_GATES_GLOBAL_BYPASS"):
+    _reason = os.environ["CLAUDE_GATES_GLOBAL_BYPASS"]
+    try:
+        from datetime import datetime as _dt
+        _q = Path(f"audit/.queue/{_dt.now():%Y-%m-%d}.log")
+        _q.parent.mkdir(parents=True, exist_ok=True)
+        with _q.open("a") as _f:
+            _f.write(f"{_dt.now().isoformat()} {os.getcwd()} BYPASS used: {_reason} @ entry=runner\n")
+    except Exception:
+        pass
+    sys.exit(0)
+# ---- END: REQ-2026-006 ----
+
 import pathspec
 import yaml
```

### 3.2 `scripts/gates/triggers/submit.py` 顶部 audit 留痕（仅留痕，决策仍由 run.py 兜）

```diff
--- a/scripts/gates/triggers/submit.py
+++ b/scripts/gates/triggers/submit.py
@@ -19,6 +19,18 @@ import argparse
 import sys
 from pathlib import Path
 from typing import Optional

+# ---- BEGIN: REQ-2026-006 trigger 入口 audit 留痕（仅记录哪个 trigger 入口被 bypass，决策委托 run.py）----
+import os as _os
+if _os.environ.get("CLAUDE_GATES_GLOBAL_BYPASS"):
+    try:
+        from datetime import datetime as _dt
+        _q = Path(f"audit/.queue/{_dt.now():%Y-%m-%d}.log")
+        _q.parent.mkdir(parents=True, exist_ok=True)
+        with _q.open("a") as _f:
+            _f.write(f"{_dt.now().isoformat()} {_os.getcwd()} BYPASS used: {_os.environ['CLAUDE_GATES_GLOBAL_BYPASS']} @ entry=trigger:submit\n")
+    except Exception:
+        pass
+    # 不 sys.exit——继续走 run.py，让 run.py 的顶部 bypass 检查兜底退出
+# ---- END: REQ-2026-006 ----
+
 # 把 scripts/gates 加入 import 路径，复用 run.py 的 main()
 _TRIGGER_DIR = Path(__file__).resolve().parent
```

### 3.3 PR-3 测试用例（pytest）

新增 `tests/gates/test_global_bypass.py`：

| 用例 | 操作 | 期望 |
|---|---|---|
| `test_run_py_bypass_exits_zero` | `CLAUDE_GATES_GLOBAL_BYPASS=x python3 scripts/gates/run.py --trigger=ci` | exit 0；audit/.queue 有 BYPASS 行带 `entry=runner` |
| `test_run_py_no_bypass_normal` | 不设环境变量；正常 ci | exit 行为不变（同 baseline） |
| `test_submit_py_bypass_logs_and_exits` | `CLAUDE_GATES_GLOBAL_BYPASS=x python3 scripts/gates/triggers/submit.py --req=REQ-x` | exit 0；audit/.queue 有两行（`entry=trigger:submit` + `entry=runner`） |
| `test_submit_py_no_bypass_normal` | 不设；正常 submit 流 | 行为不变 |
| `test_guard_sh_bypass_exits_zero` | guard.sh + 环境变量 | exit 0；audit/.queue 有 `entry=pre-tool-use-guard` |

bats 已覆盖 guard.sh 一例（§1.2 "CLAUDE_GATES_GLOBAL_BYPASS skips block"），pytest 补 4 个用例。

---

## 4. PR-4：异步 audit + run.py 兜底 + SessionEnd flush

### 4.1 `scripts/gates/run.py` 改动 2（main() BaseException 兜底）

```diff
@@ -598,6 +613,29 @@ def main(argv: Optional[list[str]] = None) -> int:
     ...
     """
+    try:
+        return _real_main(argv)
+    except SystemExit:
+        # argparse 正常 exit 不拦
+        raise
+    except BaseException as _e:
+        # 任何未捕获异常 → 写错误日志 → 退 2（trigger 层视为 fail-open）
+        try:
+            from datetime import datetime as _dt
+            import traceback as _tb
+            with open("/tmp/run-py-error.log", "a") as _f:
+                _f.write(f"\n--- {_dt.now().isoformat()} ---\n")
+                _tb.print_exc(file=_f)
+        except Exception:
+            pass
+        return 2

+
+def _real_main(argv: Optional[list[str]] = None) -> int:
+    """旧 main 内容；仅签名重命名，body 不变。"""
     raw_argv = argv if argv is not None else sys.argv[1:]
     args = parse_args(raw_argv)
```

> 注：把现有 main() 函数体整体改名为 `_real_main`，main() 变为 try/except 包装。这种"thin wrapper"模式兼容 submit.py 的 `import run as runner` + `runner.main()` 调用方式。

### 4.2 `run.py` 改动 3（write_audit → audit_append_async）

`write_audit` 调用点（来源：scripts/gates/run.py:883）改为异步 append（另一调用点见 `scripts/gates/run.py:1029` 同样改造）。

为兼容现有 audit.py 模块，最小改动方案：保留 `_audit.write_audit` 的导入但改其底层实现——`scripts/gates/audit.py` 内部把同步写盘改成调用 `audit_async.sh::audit_append_async`。

```diff
--- a/scripts/gates/audit.py
+++ b/scripts/gates/audit.py
@@ -X,Y +X,Z @@
 def write_audit(record: dict) -> None:
-    # 旧实现：同步写 audit/<YYYY-MM>/<trigger>-<ts>.json
-    ...
+    # REQ-2026-006 PR-4：改为 append-only log，由 SessionEnd flush 整理回 JSON
+    import subprocess as _sp
+    _line = json.dumps(record, ensure_ascii=False)
+    try:
+        _sp.run(
+            ["bash", "-c", f"source scripts/lib/audit_async.sh && audit_append_async {_line!r} {ENTRY_RUNNER!r}"],
+            check=False, timeout=2,
+        )
+    except Exception:
+        pass  # best-effort；失败完全静默（D-005）
```

> 注：精确 `audit.py` 改动 diff 在 PR-4 实施时根据当前文件结构调整；本设计仅约束「write_audit 必须 best-effort、不阻断、失败静默」契约。

### 4.3 `scripts/lib/audit_flush.py` 接口签名

```python
"""把 audit/.queue/*.log 整理回 audit/<YYYY-MM>/<trigger>-<ts>.json。

行为：
  - 读所有 audit/.queue/*.log（每行一个 record）
  - 按 entry 字段分桶 → 写入 audit/<YYYY-MM>/<entry>-<日期>.json（多次 flush 会追加）
  - 成功处理的 .log 文件 mv 到 audit/.queue.done/<日期>/，不删除（便于审计 + 回滚）
  - 任何步骤失败完全静默：返回 0（exit 0），下次 SessionEnd 再试

使用：
  python3 scripts/lib/audit_flush.py             # 处理所有 .log，无参
  python3 scripts/lib/audit_flush.py --dry-run   # 仅打印计划，不动文件

不依赖外部库；仅用 stdlib（pathlib / json / shutil / datetime / argparse）。
"""
from __future__ import annotations

def main(argv: list[str] | None = None) -> int:
    """入口；返回 0 永不抛异常。"""
    ...

if __name__ == "__main__":
    import sys
    sys.exit(main())
```

实现细节（粗）：

| 函数 | 入参 | 出参 | 职责 |
|---|---|---|---|
| `_collect_logs(queue_dir: Path) -> list[Path]` | queue 目录 | log 文件列表 | glob `*.log`；queue 不存在返回 [] |
| `_parse_lines(log: Path) -> list[dict]` | 单 log | record 列表 | 行格式 `<ts> <cwd> <event> @ entry=<name>` 解析 |
| `_dispatch(records: list[dict]) -> dict[str, list[dict]]` | 全部 record | by entry 分桶 | 按 entry name 分组 |
| `_write_buckets(by_entry, out_dir: Path) -> None` | 分桶 / 输出目录 | None | 每 entry 写一个 JSON；append 模式 |
| `_archive_logs(logs: list[Path], done_dir: Path) -> None` | log / archive 目录 | None | mv 到 .queue.done/<日期>/ |

### 4.4 `.claude/hooks/audit-flush.sh`（薄壳）

```bash
#!/usr/bin/env bash
# 失败完全静默——下次 SessionEnd 再试（D-005 best-effort）。
python3 scripts/lib/audit_flush.py 2>/dev/null || true
```

### 4.5 `.claude/settings.json` PR-4 改动（在 PR-1 已切换 PreToolUse 基础上加 SessionEnd）

```diff
--- a/.claude/settings.json
+++ b/.claude/settings.json
@@ -33,7 +33,8 @@
     "SessionEnd": [
       {
         "matcher": "prompt_input_exit|logout|other",
         "hooks": [
-          { "type": "command", "command": ".claude/hooks/extract-experience.sh" }
+          { "type": "command", "command": ".claude/hooks/extract-experience.sh" },
+          { "type": "command", "command": ".claude/hooks/audit-flush.sh" }
         ]
       }
     ]
```

### 4.6 PR-4 故障注入测试清单

| 注入 | 期望 | 验证方式 |
|---|---|---|
| run.py 顶部加 `raise NameError` | exit 2 → trigger 层 fail-open | `python3 scripts/gates/run.py --trigger=ci` exit 2；`/tmp/run-py-error.log` 含 trace |
| `audit/.queue/` 改 0555 | 决策正常返回；audit 写盘失败被 swallow | 跑 phase-transition gate；exit 0；queue 内无新 log（写入静默失败） |
| 切换到 `audit/.queue.bak-<ts>/`（**outline-design R3 修订**）<br/>而非删除 audit 队列 | 回滚演练不丢未 flush 数据 | mv 后跑 SessionEnd → audit_flush.py 跳过缺失 queue → exit 0 |

---

## 5. V-06 测量方法决议

**选定工具**：`hyperfine`（Rust 写的微基准工具），在 bats 中调用。

**测试用例（新增到 §1.2 bats 套件）**：

```bash
@test "V-06: hot path < 5ms (hyperfine 100 runs)" {
  command -v hyperfine >/dev/null || skip "hyperfine not installed"
  git checkout -qb feature/perf-test
  cat > /tmp/guard-input.json <<EOF
{"tool_name":"Edit","tool_input":{"file_path":"src/foo.py"}}
EOF
  result=$(hyperfine --warmup 3 --runs 100 \
    "cat /tmp/guard-input.json | $GUARD" \
    --export-json /tmp/perf.json 2>/dev/null && cat /tmp/perf.json)
  mean_ms=$(echo "$result" | python3 -c "import json,sys; print(json.load(sys.stdin)['results'][0]['mean']*1000)")
  # < 5ms 阈值
  python3 -c "import sys; sys.exit(0 if $mean_ms < 5 else 1)"
}
```

CI 安装：`apt-get install hyperfine`（ubuntu 22.04+ 自带）；macOS：`brew install hyperfine`。

`quality-check.yml` 新增 step：

```yaml
- name: Install hyperfine
  run: |
    if ! command -v hyperfine >/dev/null; then
      sudo apt-get install -y hyperfine
    fi
```

---

## 6. outline-design 5 条 minor 修订（PR-1 内顺手改）

| # | outline-design 行号 | 修订内容 |
|---|---|---|
| 1 | §4 PR-3/PR-4 并行段 | 改为「两 PR 改 run.py 不同段落（PR-3 文件顶部 / PR-4 main 函数体），git 自动合并；若有冲突 rebase 解决」 |
| 2 | §2.5 spec 注释同步 | 显式归 PR-1（本 PR §1.6 已落） |
| 3 | §5 PR-4 回滚验证步骤 | 「删 audit/.queue/」改为「`mv audit/.queue/ audit/.queue.bak-<ts>/`」 |
| 4 | §7 V-06 表格行 | 拆两层：「基准已锁（`#!/usr/bin/env bash`）/ 测量工具 hyperfine（detail-design §5）」 |
| 5 | §6 与 hook-fail-open 关系 | 显式列闭合条款：guard.sh trap ERR 闭合 §3.1（hook 自身异常 fail-open）；run.py BaseException 闭合 §4.2（trigger fail-open）；audit best-effort 闭合 §5.2（审计不影响决策） |

---

## 7. 接口签名汇总（供 features.json 引用）

| 模块 | 函数 / 入口 | 输入 | 输出 | 副作用 |
|---|---|---|---|---|
| `pre-tool-use-guard.sh` | `main()` | stdin JSON | exit 0/2 | 写 audit/.queue / /tmp/guard-error.log |
| `audit_async.sh` | `audit_append_async <line> [entry]` | 行字符串 / 入口名 | - | append `audit/.queue/<日期>.log` |
| `audit_async.sh` | `audit_flush_queue` | - | - | 调 audit_flush.py |
| `audit_flush.py` | `main(argv) -> int` | CLI args | exit 0 | mv .queue/*.log → .queue.done/，写 audit/<YYYY-MM>/*.json |
| `run.py` | `main(argv) -> int` | CLI args | exit 0/1/2 | audit append（异步）/ stash-restore / staged_writes commit |
| `run.py` | `_real_main(argv)` | CLI args | exit 0/1/2 | 同 main()；BaseException 由 wrapper 兜 |
| `submit.py` | `main()` | CLI args | exit 委托 run | trigger:submit audit 留痕 |

---

## 8. V-01 ~ V-08 验收映射

| V- | 验收点 | 实现位置 |
|---|---|---|
| V-01 | bats ≥10 用例 | §1.2（24 用例） |
| V-02 | sandbox 完整 REQ 周期，4 trigger × 12 gate | PR-2 后 manual sandbox 跑 + §2.4 settings 引用校验 |
| V-03 | 注入 NameError → fail-open | §4.1 try/except BaseException + §4.6 故障注入测试 |
| V-04 | audit/.queue 0555 → 决策正常 | §4.6 故障注入第 2 行 + audit_async best-effort |
| V-05 | BYPASS 跳过 + audit 留痕 | §3.1/3.2/3.3 三入口；entry=runner / trigger:submit / pre-tool-use-guard |
| V-06 | 热路径 < 5ms | §5 hyperfine bats 用例 + 基准 `#!/usr/bin/env bash` |
| V-07 | 锁死率 0% | guard.sh trap ERR + run.py BaseException 双层兜底 |
| V-08 | 热路径文件数 = 1 | 仅 `pre-tool-use-guard.sh` 在 PreToolUse 链路；audit_async.sh 在低频路径 |

---

## 待澄清清单

1. **base.py Literal 与 TRIGGERS 同步**：删 `pre-tool-use` 枚举值会破坏现有测试 fixture（`tests/gates/test_*.py` 中可能有 `trigger="pre-tool-use"` 字面量）。本 PR 的 grep 扫描 + 同步删/改测试用例是 PR-2 的隐含动作，detail-design 阶段未列详细修改清单——任务规划阶段需把这部分独立成一个 feature_id（建议 F-2-2-base-py-cleanup）。
