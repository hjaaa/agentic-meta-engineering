# 门禁系统 A+B 重构 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 PreToolUse 热路径从 1875 行的 god-object 链路重构为 ~60 行独立 bash 脚本（B1），并补 `CLAUDE_GATES_GLOBAL_BYPASS` 全局逃生 / 异步 audit / `run.py` 最外层兜底（A），根治"门禁锁死全部工具"问题。

**Architecture:** 4 个独立可回滚 PR——PR-1 新增热路径脚本（与旧并行）、PR-2 删除旧实现、PR-3 加全局逃生、PR-4 加异步 audit + 最外层兜底。PR-1 必须先合且至少观察 1 天，再做 PR-2。PR-3 / PR-4 顺序无关。

**Tech Stack:** bash + python3 + git。本仓库无 bats / junit；测试用 shell 断言（`assert_exit` helper），跑 `tests/hooks/test_pre_tool_use_guard.sh` 即可。

**前置条件：**
- spec 已 approve：[`design-guidance/gate-system-architecture.md`](../design-guidance/gate-system-architecture.md)（commit `fc7e6b2`）
- 仓库根：`/Users/richardhuang/learnspace/agentic-meta-engineering`
- 当前 develop 已是稳定基线
- 每个 PR 切独立分支：`feat/gate-pr1-guard` / `feat/gate-pr2-cleanup` / `feat/gate-pr3-bypass` / `feat/gate-pr4-async-audit`

**显式不做（Out of Scope）：**
- 不实现 C 方案的"软警告"语义
- 不抽 plugin 公共接口
- 不做 audit 可视化 / dashboard
- 不把规则做成可配置 YAML
- 不批量改老 audit 历史数据

**紧急回滚速查：**

| 阶段 | 锁死了？ | 怎么办 |
|---|---|---|
| 任何时候 | 工具被全部拦死 | `unset` 后跑 `git restore .claude/settings.json` 把 hook 改回原 `protect-branch.sh` |
| PR-1 切换后 | guard.sh 出 bug | 改 `.claude/settings.json` 一行回退 |
| PR-2 删除后 | CI 红 | `git revert <pr2-merge>` |
| PR-3 加 BYPASS 后 | BYPASS 误生效 | 检查环境变量 `env \| grep CLAUDE_GATES` |
| PR-4 改 audit 后 | run.py 启动崩 | `git revert <pr4-merge>` |

---

## File Structure

**Create:**
- `.claude/hooks/pre-tool-use-guard.sh` — PR-1 核心脚本，60 行 bash，零 Python 依赖
- `tests/hooks/test_pre_tool_use_guard.sh` — PR-1 单测套件（plain bash）
- `scripts/lib/audit_async.sh` — PR-4 异步 audit 工具函数
- `scripts/lib/audit_flush.py` — PR-4 SessionEnd 把 .queue 整理成 JSON
- `tests/hooks/test_global_bypass.sh` — PR-3 BYPASS 行为测试
- `tests/gates/test_run_py_outer_catch.py` — PR-4 故障注入测试

**Modify:**
- `.claude/settings.json` — PR-1 切换 hook command
- `scripts/gates/run.py` — PR-3 顶部加 BYPASS；PR-4 audit 调用改异步 + 最外层 try/except
- `scripts/gates/registry.yaml` — PR-2 删两条 gate 条目
- `scripts/gates/triggers/*.sh`（除 pre_tool_use 已删） — PR-3 顶部加 BYPASS
- `.claude/hooks/extract-experience.sh` 或 SessionEnd 钩链 — PR-4 加 audit_flush 调用

**Delete（PR-2）：**
- `.claude/hooks/protect-branch.sh`
- `scripts/gates/triggers/pre_tool_use.sh`
- `scripts/gates/plugins/protect_branch.py`
- `scripts/gates/plugins/bash_write_protect.py`

---

# Phase A · PR-1 新热路径脚本（与旧并行）

> 分支：`feat/gate-pr1-guard`
> 目标：guard.sh + 测试 + 切 settings.json，旧实现保留不动
> 出 PR 后人审 + 至少观察 1 天再合 PR-2

## Task 1.0: 切分支 + 创建测试目录

**Files:** 无修改，纯准备

- [ ] **Step 1: 从 develop 切分支**

```bash
git checkout develop && git pull --ff-only && git checkout -b feat/gate-pr1-guard
```

Expected: 切到新分支，`git status` clean

- [ ] **Step 2: 建测试目录**

```bash
mkdir -p tests/hooks
```

- [ ] **Step 3: 验证当前老 hook 仍生效**

```bash
grep -A2 '"PreToolUse"' .claude/settings.json | grep command
```

Expected 输出包含：`.claude/hooks/protect-branch.sh`

---

## Task 1.1: 测试套件骨架（先有 fail，再有 impl）

**Files:**
- Create: `tests/hooks/test_pre_tool_use_guard.sh`

- [ ] **Step 1: 写测试运行器骨架**

```bash
cat > tests/hooks/test_pre_tool_use_guard.sh <<'BASH'
#!/bin/bash
# 测试 .claude/hooks/pre-tool-use-guard.sh
# 用法: bash tests/hooks/test_pre_tool_use_guard.sh
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
GUARD="$ROOT/.claude/hooks/pre-tool-use-guard.sh"
PASS=0; FAIL=0

assert_exit() {
  local desc="$1" expected="$2" stdin="$3"
  local rc
  rc=$(echo "$stdin" | "$GUARD" 2>/dev/null; echo "RC=$?")
  rc=${rc##*RC=}
  if [[ "$rc" == "$expected" ]]; then
    printf "  ✓ %s\n" "$desc"; PASS=$((PASS+1))
  else
    printf "  ✗ %s (expected exit %s, got %s)\n" "$desc" "$expected" "$rc"
    FAIL=$((FAIL+1))
  fi
}

# 在临时 git 仓库里测试，避免污染当前分支
TMP=$(mktemp -d); trap "rm -rf $TMP" EXIT
cd "$TMP" && git init -q && git config user.email t@t && git config user.name t \
  && git commit -q --allow-empty -m init

run_tests() {
  echo "== branch protect =="
  git checkout -q -B feature/test
  assert_exit "feature branch + Edit → 0" 0 \
    '{"tool_name":"Edit","tool_input":{"file_path":"foo.py"}}'
  git checkout -q -B develop
  assert_exit "develop + Edit → 2" 2 \
    '{"tool_name":"Edit","tool_input":{"file_path":"foo.py"}}'
}

run_tests
echo
echo "PASS=$PASS FAIL=$FAIL"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
BASH
chmod +x tests/hooks/test_pre_tool_use_guard.sh
```

- [ ] **Step 2: 运行 → 应该全 fail（guard.sh 还不存在）**

```bash
bash tests/hooks/test_pre_tool_use_guard.sh; echo "rc=$?"
```

Expected: `rc=1`（脚本不存在所以 assert 失败）

- [ ] **Step 3: 提交测试骨架**

```bash
git add tests/hooks/test_pre_tool_use_guard.sh
git commit -m "test(gate): pre-tool-use-guard 测试套件骨架"
```

---

## Task 1.2: guard.sh 最小骨架（仅 trap + exit 0）

**Files:**
- Create: `.claude/hooks/pre-tool-use-guard.sh`

- [ ] **Step 1: 写最小骨架**

```bash
cat > .claude/hooks/pre-tool-use-guard.sh <<'BASH'
#!/bin/bash
# PreToolUse hook：保护分支 + reviews/*.json 直写
# 设计 spec: context/team/engineering-spec/design-guidance/gate-system-architecture.md
set -u
trap 'exit 0' ERR
exec 2>>/tmp/guard-error.log

main() {
  exit 0
}

main "$@"
BASH
chmod +x .claude/hooks/pre-tool-use-guard.sh
```

- [ ] **Step 2: 跑测试 → 第一条（feature → 0）应通过，第二条（develop → 2）应失败**

```bash
bash tests/hooks/test_pre_tool_use_guard.sh; echo "rc=$?"
```

Expected: `PASS=1 FAIL=1` `rc=1`

- [ ] **Step 3: 提交骨架**

```bash
git add .claude/hooks/pre-tool-use-guard.sh
git commit -m "feat(gate): guard.sh 骨架（仅 trap + exit 0）"
```

---

## Task 1.3: 实现 stdin 解析 + branch protect

**Files:**
- Modify: `.claude/hooks/pre-tool-use-guard.sh`

- [ ] **Step 1: 完整重写脚本，加 JSON 解析 + branch 检查**

```bash
cat > .claude/hooks/pre-tool-use-guard.sh <<'BASH'
#!/bin/bash
# PreToolUse hook：保护分支 + reviews/*.json 直写
# 设计 spec: context/team/engineering-spec/design-guidance/gate-system-architecture.md
set -u
trap 'exit 0' ERR
exec 2>>/tmp/guard-error.log

# JSON 字段提取：jq 优先，回退到 python3
json_get() {
  local key="$1"
  if command -v jq >/dev/null 2>&1; then
    echo "$INPUT" | jq -r "$key // empty"
  else
    echo "$INPUT" | python3 -c "import json,sys;d=json.load(sys.stdin);
def g(p,o):
 for k in p.split('.'):
  o=o.get(k) if isinstance(o,dict) else None
  if o is None: return ''
 return o if o else ''
print(g('$(echo "$key" | sed 's/^\.//; s/\.//g; s/\//./g')','$key'))" 2>/dev/null || echo ""
  fi
}

check_branch_protect() {
  local b
  b=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || return 0
  case "$b" in
    main|master|develop)
      cat >&2 <<EOF
BLOCKED: 当前在 '$b' 分支，禁止直接 Edit/Write/MultiEdit。
规避方式：
  1) 切到 feature 分支（推荐）：git checkout -b feature/req-xxx
  2) 紧急绕过（需理由）：CLAUDE_GATES_GLOBAL_BYPASS="抢救门禁本身被锁死" <重新执行>
EOF
      exit 2
      ;;
  esac
}

main() {
  INPUT=$(cat)
  local tool_name
  tool_name=$(json_get '.tool_name')

  case "$tool_name" in
    Edit|Write|MultiEdit) check_branch_protect ;;
  esac

  exit 0
}

main "$@"
BASH
```

- [ ] **Step 2: 跑测试 → 两条都应通过**

```bash
bash tests/hooks/test_pre_tool_use_guard.sh; echo "rc=$?"
```

Expected: `PASS=2 FAIL=0` `rc=0`

- [ ] **Step 3: 提交**

```bash
git add .claude/hooks/pre-tool-use-guard.sh
git commit -m "feat(gate): guard.sh 实现 branch protect + JSON 解析"
```

---

## Task 1.4: 加 review path 检查 + 测试

**Files:**
- Modify: `.claude/hooks/pre-tool-use-guard.sh`
- Modify: `tests/hooks/test_pre_tool_use_guard.sh`

- [ ] **Step 1: 在测试套件加用例**

在 `tests/hooks/test_pre_tool_use_guard.sh` 的 `run_tests()` 末尾追加：

```bash
# Edit it: append after the last assert_exit in run_tests
sed -i.bak '/^run_tests/i\
add_review_path_tests() {\
  echo "== review path =="\
  git checkout -q -B feature/test\
  assert_exit "Edit reviews/X/reviews/y.json → 2" 2 \
    '"'"'{"tool_name":"Edit","tool_input":{"file_path":"requirements/REQ-X/reviews/y.json"}}'"'"'\
  assert_exit "Edit foo/bar.py → 0" 0 \
    '"'"'{"tool_name":"Edit","tool_input":{"file_path":"foo/bar.py"}}'"'"'\
}' tests/hooks/test_pre_tool_use_guard.sh
sed -i.bak '/^run_tests$/c\
run_tests; add_review_path_tests' tests/hooks/test_pre_tool_use_guard.sh
rm tests/hooks/test_pre_tool_use_guard.sh.bak
```

> 提示：如 sed 替换不顺手，直接用 Edit 工具手动加 `add_review_path_tests` 函数定义和调用。

- [ ] **Step 2: 跑测试 → review path 用例应失败（impl 还没加）**

```bash
bash tests/hooks/test_pre_tool_use_guard.sh; echo "rc=$?"
```

Expected: `PASS=3 FAIL=1`

- [ ] **Step 3: guard.sh 加 check_review_path 函数**

用 Edit 工具修改 `.claude/hooks/pre-tool-use-guard.sh`，在 `check_branch_protect()` 后追加：

```bash
check_review_path() {
  local p="$1"
  [[ -z "$p" ]] && return 0
  if [[ "$p" =~ ^.*requirements/[^/]+/reviews/.+\.json$ ]]; then
    cat >&2 <<EOF
BLOCKED: $p
reviews/*.json 不能直写。必须走 scripts/save-review.sh 或人类 sign-off CLI。
规避方式：CLAUDE_GATES_GLOBAL_BYPASS="<理由>"，但请先停下来想想是不是真的应该绕过。
EOF
    exit 2
  fi
}
```

并修改 `main()` 的 case 分支：

```bash
case "$tool_name" in
  Edit|Write|MultiEdit)
    check_branch_protect
    check_review_path "$(json_get '.tool_input.file_path')"
    ;;
esac
```

- [ ] **Step 4: 再跑 → 全过**

```bash
bash tests/hooks/test_pre_tool_use_guard.sh; echo "rc=$?"
```

Expected: `PASS=4 FAIL=0`

- [ ] **Step 5: 提交**

```bash
git add .claude/hooks/pre-tool-use-guard.sh tests/hooks/test_pre_tool_use_guard.sh
git commit -m "feat(gate): guard.sh 实现 reviews/*.json 直写防护"
```

---

## Task 1.5: 加 bash 写入检查（12 patterns）

**Files:**
- Modify: `.claude/hooks/pre-tool-use-guard.sh`
- Modify: `tests/hooks/test_pre_tool_use_guard.sh`

- [ ] **Step 1: 测试加 12 条 bash 写入用例**

在 test 脚本里加：

```bash
add_bash_write_tests() {
  echo "== bash write =="
  git checkout -q -B feature/test
  local target='requirements/REQ-X/reviews/y.json'
  for cmd in \
    "echo x > $target" \
    "echo x >> $target" \
    "echo x | tee $target" \
    "echo x | tee -a $target" \
    "cat | sponge $target" \
    "dd of=$target" \
    "mv tmp $target" \
    "cp tmp $target" \
    "rsync src $target" \
    "install -m 644 src $target" \
    "python3 -c \"open('$target','w').write('x')\"" \
    "cat <<EOF > $target
foo
EOF"; do
    assert_exit "Bash '$cmd' → 2" 2 \
      "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":$(printf '%s' "$cmd" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')}}"
  done
  # 不应阻断的对照
  assert_exit "Bash 'cat $target' → 0" 0 \
    "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"cat $target\"}}"
}
```

并把 `add_bash_write_tests` 加进 `run_tests; add_review_path_tests` 调用链。

- [ ] **Step 2: 跑测试 → 13 条 bash 用例都失败（除了 cat）**

```bash
bash tests/hooks/test_pre_tool_use_guard.sh; echo "rc=$?"
```

Expected: 12 个 bash 阻断用例 FAIL，cat PASS

- [ ] **Step 3: guard.sh 加 check_bash_writes_review**

用 Edit 工具在 `check_review_path` 后追加：

```bash
check_bash_writes_review() {
  local cmd="$1"
  [[ -z "$cmd" ]] && return 0
  # 12 种写入模式，对应 spec 附录 A
  local rev='requirements/[^/]+/reviews/[^[:space:]\"]+\.json'
  local pattern
  pattern="(>|>>|tee|sponge|dd[[:space:]]+of=|rsync|install|mv|cp)[[:space:]]+[^|;&]*${rev}"
  pattern+="|python3?[[:space:]]+-c[[:space:]]+[\"'].*open\([^)]*${rev}"
  pattern+="|cat[[:space:]]+<<.*>[[:space:]]*[^|;&]*${rev}"
  pattern+="|tee[[:space:]]+-a[[:space:]]+[^|;&]*${rev}"

  if echo "$cmd" | grep -qE "$pattern"; then
    cat >&2 <<EOF
BLOCKED: Bash 写入 requirements/*/reviews/*.json 被禁。
规避方式：scripts/save-review.sh 是 reviewer Agent 的标准入口；
     人类 sign-off 走 scripts/lib/code_review_signoff.py（必须 tty）。
EOF
    exit 2
  fi
}
```

并扩展 `main()` 的 case：

```bash
case "$tool_name" in
  Edit|Write|MultiEdit)
    check_branch_protect
    check_review_path "$(json_get '.tool_input.file_path')"
    ;;
  Bash)
    check_bash_writes_review "$(json_get '.tool_input.command')"
    ;;
esac
```

- [ ] **Step 4: 再跑测试 → 全 PASS**

```bash
bash tests/hooks/test_pre_tool_use_guard.sh; echo "rc=$?"
```

Expected: `PASS=17 FAIL=0`（4 + 13）

- [ ] **Step 5: 提交**

```bash
git add .claude/hooks/pre-tool-use-guard.sh tests/hooks/test_pre_tool_use_guard.sh
git commit -m "feat(gate): guard.sh 实现 bash 写入 reviews/*.json 检测（12 patterns）"
```

---

## Task 1.6: 加 fail-open + audit_log

**Files:**
- Modify: `.claude/hooks/pre-tool-use-guard.sh`
- Modify: `tests/hooks/test_pre_tool_use_guard.sh`

- [ ] **Step 1: 测试加 fail-open 用例**

```bash
add_failopen_tests() {
  echo "== fail-open =="
  git checkout -q -B feature/test
  assert_exit "stdin 不是合法 JSON → 0" 0 'this is not json'
  assert_exit "tool_name 缺失 → 0" 0 '{"tool_input":{"file_path":"x"}}'
  assert_exit "空 stdin → 0" 0 ''
}
```

- [ ] **Step 2: 跑测试 → 已经全 PASS（trap + 默认 exit 0 已覆盖）**

```bash
bash tests/hooks/test_pre_tool_use_guard.sh
```

Expected: `PASS=20 FAIL=0`

- [ ] **Step 3: 加 audit_log helper（为后续 BYPASS PR 准备）**

用 Edit 在 guard.sh 末尾（main 之前）追加：

```bash
audit_log() {
  local line="$(date -Iseconds) $(pwd) $1"
  mkdir -p audit/.queue 2>/dev/null || return 0
  echo "$line" >>"audit/.queue/$(date +%Y-%m-%d).log" 2>/dev/null || true
}
```

- [ ] **Step 4: 跑全套测试，确保没有副作用**

```bash
bash tests/hooks/test_pre_tool_use_guard.sh; echo "rc=$?"
```

Expected: `PASS=20 FAIL=0` `rc=0`

- [ ] **Step 5: 提交**

```bash
git add .claude/hooks/pre-tool-use-guard.sh tests/hooks/test_pre_tool_use_guard.sh
git commit -m "feat(gate): guard.sh 加 fail-open 用例 + audit_log helper"
```

---

## Task 1.7: 切换 settings.json + 手工冒烟

**Files:**
- Modify: `.claude/settings.json`

- [ ] **Step 1: 在 settings.json 切 hook command**

用 Edit 工具改 `.claude/settings.json`，找到 `PreToolUse` 块的：

```json
"command": ".claude/hooks/protect-branch.sh"
```

改为：

```json
"command": ".claude/hooks/pre-tool-use-guard.sh"
```

matcher 保持 `"Bash|Edit|Write|MultiEdit"`。

- [ ] **Step 2: 验证切换生效**

```bash
grep -A2 '"PreToolUse"' .claude/settings.json | grep command
```

Expected: 输出 `.claude/hooks/pre-tool-use-guard.sh`

- [ ] **Step 3: 手工冒烟 1——feature 分支允许写**

```bash
echo "smoke test 1" > /tmp/gate-smoke-1.txt
cat /tmp/gate-smoke-1.txt
rm /tmp/gate-smoke-1.txt
```

Expected: 命令正常执行（当前在 feat/gate-pr1-guard，应该放行）

- [ ] **Step 4: 手工冒烟 2——尝试 reviews/*.json 写入应被拦**

```bash
echo "x" > requirements/REQ-XX/reviews/test.json 2>&1 | head -3
```

Expected: 输出包含 `BLOCKED:` 字样（注意：实际 hook 在 Bash 调用上拦，不是 redirect 本身。如果当前 shell 不走 hook，跳过此步）

- [ ] **Step 5: 跑测试套件最后确认**

```bash
bash tests/hooks/test_pre_tool_use_guard.sh
```

Expected: `PASS=20 FAIL=0`

- [ ] **Step 6: 提交**

```bash
git add .claude/settings.json
git commit -m "feat(gate): 切换 PreToolUse hook 到 pre-tool-use-guard.sh

旧 protect-branch.sh 与下游 run.py 链路保留，本 PR 仅切入口。
PR-2 在本 PR 合入 + 观察 ≥1 天后再删旧实现。"
```

---

## Task 1.8: 推分支 + 提 PR-1

- [ ] **Step 1: push**

```bash
git push -u origin feat/gate-pr1-guard
```

- [ ] **Step 2: 提 PR**

```bash
gh pr create --title "feat(gate): PR-1 新热路径脚本 pre-tool-use-guard.sh" --body "$(cat <<'EOF'
## Summary

- 新增 `.claude/hooks/pre-tool-use-guard.sh`（~80 行 bash）替代原 `protect-branch.sh → pre_tool_use.sh → run.py` 三层链路
- 新增 `tests/hooks/test_pre_tool_use_guard.sh`（20 用例：branch / review path / 12 bash patterns / fail-open）
- 切换 `.claude/settings.json` PreToolUse 入口

## 背景

详见 spec: `context/team/engineering-spec/design-guidance/gate-system-architecture.md`

## 验证

- 测试：`bash tests/hooks/test_pre_tool_use_guard.sh` → `PASS=20 FAIL=0`
- 旧实现保留，下游 run.py 链路不动；本 PR 仅切入口
- 出问题秒回滚：`git revert <merge>` 或改回 settings.json 一行

## 后续

PR-2 在本 PR 合入 + 观察 ≥1 天后删旧实现（protect-branch.sh / pre_tool_use.sh / 两个 plugin）

## Test plan

- [x] 单测全过
- [x] 手工冒烟：feature 分支 Edit 通过、reviews/*.json 写入被拦
- [ ] reviewer 在 develop 上手工触发一次 Edit（应被新 guard.sh 拦）
EOF
)"
```

- [ ] **Step 3: 等 review + merge**

人审 + 至少观察 1 天，确认无锁死投诉，再进 PR-2。

---

# Phase B · PR-2 清理旧代码

> 分支：`feat/gate-pr2-cleanup`
> 前置：PR-1 已 merge 到 develop **且观察 ≥ 1 天**

## Task 2.1: 切分支 + 删 4 个文件

**Files:**
- Delete: `.claude/hooks/protect-branch.sh`
- Delete: `scripts/gates/triggers/pre_tool_use.sh`
- Delete: `scripts/gates/plugins/protect_branch.py`
- Delete: `scripts/gates/plugins/bash_write_protect.py`

- [ ] **Step 1: 切分支**

```bash
git checkout develop && git pull --ff-only && git checkout -b feat/gate-pr2-cleanup
```

- [ ] **Step 2: 用 git rm 删（不能用 rm -rf——deny list 拦）**

```bash
git rm .claude/hooks/protect-branch.sh \
       scripts/gates/triggers/pre_tool_use.sh \
       scripts/gates/plugins/protect_branch.py \
       scripts/gates/plugins/bash_write_protect.py
```

- [ ] **Step 3: 验证**

```bash
git status -s
```

Expected: 4 个 D（deleted）行

- [ ] **Step 4: 提交**

```bash
git commit -m "refactor(gate): 删除已被 guard.sh 替代的 4 个旧文件

PR-1 已稳定运行 ≥1 天，旧实现安全下线。"
```

---

## Task 2.2: 改 registry.yaml 删两条 gate

**Files:**
- Modify: `scripts/gates/registry.yaml`

- [ ] **Step 1: 找到两条 gate 条目**

```bash
grep -n "GATE-PROTECT-BRANCH\|GATE-BASH-WRITE-PROTECT" scripts/gates/registry.yaml
```

- [ ] **Step 2: 用 Edit 工具删除这两个 gate 整段定义**

每个 gate 是 YAML 列表的一个元素，从 `- id: GATE-PROTECT-BRANCH` 到下一个 `- id:` 之前的所有行。`GATE-BASH-WRITE-PROTECT` 同理。

- [ ] **Step 3: 验证 YAML 仍合法**

```bash
python3 -c "import yaml; yaml.safe_load(open('scripts/gates/registry.yaml'))"
echo "rc=$?"
```

Expected: `rc=0`

- [ ] **Step 4: 验证 trigger 枚举不再引用 pre-tool-use**

```bash
grep -n "pre-tool-use" scripts/gates/registry.yaml
```

Expected: 无输出（如果有，按需删除残留）

- [ ] **Step 5: 跑既有 gate 测试，确认其余 gate 仍工作**

```bash
python3 -m pytest tests/gates/ -x -q 2>&1 | tail -20
```

Expected: 全部通过（除非有专门测这两个 gate 的用例，那些应该用 git rm 删除测试文件）

- [ ] **Step 6: 提交**

```bash
git add scripts/gates/registry.yaml
git commit -m "refactor(gate): registry.yaml 删除 GATE-PROTECT-BRANCH / GATE-BASH-WRITE-PROTECT"
```

---

## Task 2.3: 清理引用这两个 plugin 的测试

**Files:**
- Delete: `tests/gates/test_protect_branch_plugin.py`（如有）
- Delete: `tests/gates/test_bash_write_protect_plugin.py`（如有）

- [ ] **Step 1: 找出引用文件**

```bash
grep -rl "protect_branch\|bash_write_protect" tests/ scripts/ 2>/dev/null | grep -v __pycache__
```

- [ ] **Step 2: 对每个引用文件逐个判断**

如果是测试文件且只测这两个 plugin → `git rm`
如果是其他代码引用（比如别的 plugin import）→ 改成不引用或彻底删

- [ ] **Step 3: 跑全量测试**

```bash
python3 -m pytest tests/ -x -q 2>&1 | tail -10
```

Expected: 全过

- [ ] **Step 4: 提交**

```bash
git commit -am "refactor(gate): 清理对 protect_branch / bash_write_protect plugin 的引用"
```

---

## Task 2.4: 跑 sandbox 集成回归

- [ ] **Step 1: 用 sandbox REQ 跑完整生命周期（如有 REQ-2099-001 模板）**

```bash
ls requirements/REQ-2099-001 2>/dev/null && \
  bash tests/integration/run_sandbox_lifecycle.sh REQ-2099-001 2>&1 | tail -30 \
  || echo "sandbox 模板不存在，跳过；改成手工跑一次 phase-transition trigger"
```

如手工跑：

```bash
python3 scripts/gates/run.py --trigger=phase-transition --requirement-id=REQ-2099-001 --from-phase=design --to-phase=development; echo "rc=$?"
```

Expected: rc=0 或有 well-known 业务级 fail（说明 run.py 本身工作）；不能是 import error / NameError。

- [ ] **Step 2: 提交（如有变更）或跳过**

---

## Task 2.5: 推 + 提 PR-2

- [ ] **Step 1: push**

```bash
git push -u origin feat/gate-pr2-cleanup
```

- [ ] **Step 2: gh pr create**

```bash
gh pr create --title "refactor(gate): PR-2 删除被 guard.sh 替代的旧实现" --body "$(cat <<'EOF'
## Summary

PR-1 已稳定运行 ≥1 天，安全下线旧链路：

- 删除 `.claude/hooks/protect-branch.sh`
- 删除 `scripts/gates/triggers/pre_tool_use.sh`
- 删除 `scripts/gates/plugins/{protect_branch,bash_write_protect}.py`
- registry.yaml 删两条 gate 条目
- 清理对应测试文件 + 残留引用

## 净减代码

约 530 行 Python + bash，热路径文件数从 6 个减到 1 个。

## Test plan

- [x] `bash tests/hooks/test_pre_tool_use_guard.sh`
- [x] `pytest tests/gates/`
- [x] sandbox lifecycle 验证
EOF
)"
```

---

# Phase C · PR-3 全局逃生（CLAUDE_GATES_GLOBAL_BYPASS）

> 分支：`feat/gate-pr3-bypass`
> 与 PR-4 顺序无关；可与 PR-2 并行准备但建议 PR-2 先合（避免冲突）

## Task 3.1: 切分支 + 加 BYPASS 测试

**Files:**
- Create: `tests/hooks/test_global_bypass.sh`

- [ ] **Step 1: 切分支**

```bash
git checkout develop && git pull --ff-only && git checkout -b feat/gate-pr3-bypass
```

- [ ] **Step 2: 写 BYPASS 测试套件**

```bash
cat > tests/hooks/test_global_bypass.sh <<'BASH'
#!/bin/bash
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
GUARD="$ROOT/.claude/hooks/pre-tool-use-guard.sh"
RUNPY="python3 $ROOT/scripts/gates/run.py"
PASS=0; FAIL=0

assert_rc() {
  local desc="$1" expected="$2"; shift 2
  local rc
  "$@" >/dev/null 2>&1; rc=$?
  if [[ "$rc" == "$expected" ]]; then printf "  ✓ %s\n" "$desc"; PASS=$((PASS+1))
  else printf "  ✗ %s (expected %s, got %s)\n" "$desc" "$expected" "$rc"; FAIL=$((FAIL+1)); fi
}

TMP=$(mktemp -d); trap "rm -rf $TMP" EXIT
cd "$TMP" && git init -q && git config user.email t@t && git config user.name t \
  && git commit -q --allow-empty -m init && git checkout -q -B develop

echo "== guard.sh BYPASS =="
# 不设 BYPASS：develop + Edit → 阻断
assert_rc "no BYPASS, develop Edit → 2" 2 \
  bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"x\"}}' | $GUARD"
# 设了 BYPASS：放行
CLAUDE_GATES_GLOBAL_BYPASS="测试" assert_rc "BYPASS set, develop Edit → 0" 0 \
  bash -c "CLAUDE_GATES_GLOBAL_BYPASS=测试; echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"x\"}}' | $GUARD"

echo "== run.py BYPASS =="
# 设了 BYPASS 后 run.py 应直接 exit 0
assert_rc "BYPASS set, run.py → 0" 0 \
  env CLAUDE_GATES_GLOBAL_BYPASS="x" $RUNPY --trigger=manual

echo
echo "PASS=$PASS FAIL=$FAIL"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
BASH
chmod +x tests/hooks/test_global_bypass.sh
```

- [ ] **Step 3: 跑测试 → 应全 fail（impl 没加）**

```bash
bash tests/hooks/test_global_bypass.sh; echo "rc=$?"
```

Expected: 至少 2 个 fail

- [ ] **Step 4: 提交测试**

```bash
git add tests/hooks/test_global_bypass.sh
git commit -m "test(gate): CLAUDE_GATES_GLOBAL_BYPASS 行为测试"
```

---

## Task 3.2: guard.sh 实现 BYPASS

**Files:**
- Modify: `.claude/hooks/pre-tool-use-guard.sh`

- [ ] **Step 1: 在 main() 第一行加 BYPASS 检查**

用 Edit 工具，把 `main()` 的开头从：

```bash
main() {
  INPUT=$(cat)
  ...
```

改为：

```bash
main() {
  if [[ -n "${CLAUDE_GATES_GLOBAL_BYPASS:-}" ]]; then
    audit_log "BYPASS used: $CLAUDE_GATES_GLOBAL_BYPASS"
    exit 0
  fi
  INPUT=$(cat)
  ...
```

- [ ] **Step 2: 跑 BYPASS 测试 → guard.sh 部分应过**

```bash
bash tests/hooks/test_global_bypass.sh
```

Expected: 前两个 PASS，run.py 那个仍 FAIL

- [ ] **Step 3: 跑原 guard 测试，确认无回归**

```bash
bash tests/hooks/test_pre_tool_use_guard.sh
```

Expected: `PASS=20 FAIL=0`

- [ ] **Step 4: 提交**

```bash
git add .claude/hooks/pre-tool-use-guard.sh
git commit -m "feat(gate): guard.sh 支持 CLAUDE_GATES_GLOBAL_BYPASS"
```

---

## Task 3.3: run.py 实现 BYPASS

**Files:**
- Modify: `scripts/gates/run.py`

- [ ] **Step 1: 在 run.py 文件最顶部（shebang 后第一行 import 之前）插入**

用 Edit 工具，找到第一个 `import` 之前的位置，插入：

```python
import os, sys
if os.environ.get("CLAUDE_GATES_GLOBAL_BYPASS"):
    reason = os.environ["CLAUDE_GATES_GLOBAL_BYPASS"]
    try:
        from datetime import datetime
        from pathlib import Path
        d = Path("audit/.queue"); d.mkdir(parents=True, exist_ok=True)
        with open(d / f"{datetime.now():%Y-%m-%d}.log", "a") as f:
            f.write(f"{datetime.now().isoformat()} {os.getcwd()} BYPASS used: {reason}\n")
    except Exception:
        pass
    sys.exit(0)
```

注意：必须在所有其他 import 之前（避免被 import 失败影响）。

- [ ] **Step 2: 跑 BYPASS 测试 → 全过**

```bash
bash tests/hooks/test_global_bypass.sh
```

Expected: `PASS=3 FAIL=0`

- [ ] **Step 3: 验证 BYPASS audit 落盘**

```bash
rm -f audit/.queue/$(date +%Y-%m-%d).log 2>/dev/null
CLAUDE_GATES_GLOBAL_BYPASS="测试落盘" python3 scripts/gates/run.py --trigger=manual
grep "BYPASS used: 测试落盘" audit/.queue/$(date +%Y-%m-%d).log
```

Expected: 输出包含一行 BYPASS 记录

> 注：上面的 `rm -f <single-file>` 不命中 deny list（deny 是 `rm -rf:*`）；如仍被拦，用 `git clean -f audit/.queue/`。

- [ ] **Step 4: 跑 gates 全套测试**

```bash
python3 -m pytest tests/gates/ -x -q 2>&1 | tail -10
```

- [ ] **Step 5: 提交**

```bash
git add scripts/gates/run.py
git commit -m "feat(gate): run.py 支持 CLAUDE_GATES_GLOBAL_BYPASS（顶部短路）"
```

---

## Task 3.4: 给其余 trigger.sh 加 BYPASS

**Files:**
- Modify: `scripts/gates/triggers/*.sh`（除 pre_tool_use 已删）

- [ ] **Step 1: 列出所有 trigger 脚本**

```bash
ls scripts/gates/triggers/*.sh
```

- [ ] **Step 2: 对每个脚本，在 shebang 后 + 第一行业务代码前插入 BYPASS 检查**

模板：

```bash
if [[ -n "${CLAUDE_GATES_GLOBAL_BYPASS:-}" ]]; then
  echo "$(date -Iseconds) $(pwd) BYPASS used: $CLAUDE_GATES_GLOBAL_BYPASS" \
    >> "audit/.queue/$(date +%Y-%m-%d).log" 2>/dev/null || true
  exit 0
fi
```

> 用 Edit 工具逐个文件改；不要一次性改多个，避免出错难定位。

- [ ] **Step 3: 跑一个 trigger 验证**

```bash
ls scripts/gates/triggers/ | head -1
# 如有 phase_transition.sh：
CLAUDE_GATES_GLOBAL_BYPASS="x" bash scripts/gates/triggers/phase_transition.sh; echo rc=$?
```

Expected: rc=0，audit/.queue 有新行

- [ ] **Step 4: 提交**

```bash
git add scripts/gates/triggers/
git commit -m "feat(gate): 所有 trigger.sh 顶部加 CLAUDE_GATES_GLOBAL_BYPASS 检查"
```

---

## Task 3.5: 推 + 提 PR-3

- [ ] **Step 1: push + PR**

```bash
git push -u origin feat/gate-pr3-bypass
gh pr create --title "feat(gate): PR-3 CLAUDE_GATES_GLOBAL_BYPASS 全局逃生通道" --body "$(cat <<'EOF'
## Summary

新增全局逃生环境变量 `CLAUDE_GATES_GLOBAL_BYPASS=<reason>`，在 3 个入口生效：

- `.claude/hooks/pre-tool-use-guard.sh`（main 第一行）
- `scripts/gates/run.py`（顶部 import 之前）
- `scripts/gates/triggers/*.sh`（shebang 后）

启用时强制写 audit 行供事后审查。

## 用途

抢救门禁本身被锁死的紧急场景。日常不应使用——所有使用都会落 audit。

## Test plan

- [x] `bash tests/hooks/test_global_bypass.sh` → PASS=3 FAIL=0
- [x] BYPASS audit 落盘验证
- [x] 其余 trigger 不回归
EOF
)"
```

---

# Phase D · PR-4 异步 audit + run.py 最外层兜底

> 分支：`feat/gate-pr4-async-audit`
> 与 PR-3 顺序无关

## Task 4.1: 切分支 + 创建 audit_async.sh

**Files:**
- Create: `scripts/lib/audit_async.sh`
- Create: `scripts/lib/audit_flush.py`

- [ ] **Step 1: 切分支**

```bash
git checkout develop && git pull --ff-only && git checkout -b feat/gate-pr4-async-audit
```

- [ ] **Step 2: 写 audit_async.sh**

```bash
cat > scripts/lib/audit_async.sh <<'BASH'
# 异步 audit 工具函数（供 trigger.sh 和 run.py subprocess 调用）
# Usage: source scripts/lib/audit_async.sh; audit_append_async '{"k":"v"}'
audit_append_async() {
  local line="$1"
  local f="audit/.queue/$(date +%Y-%m-%d).log"
  mkdir -p "$(dirname "$f")" 2>/dev/null || return 0
  # O_APPEND 在 ext4/apfs 原子；不加锁
  echo "$line" >>"$f" 2>/dev/null || true
}

audit_flush_queue() {
  python3 scripts/lib/audit_flush.py 2>/dev/null || true
}
BASH
```

- [ ] **Step 3: 写 audit_flush.py**

```bash
cat > scripts/lib/audit_flush.py <<'PY'
"""把 audit/.queue/*.log 整理成原 audit/<YYYY-MM>/<trigger>-<ts>.json 格式。
SessionEnd hook 调用；失败完全静默。"""
import json, os, sys
from datetime import datetime
from pathlib import Path

QUEUE = Path("audit/.queue")
TARGET = Path("audit")

def main():
    if not QUEUE.exists():
        return
    for log in sorted(QUEUE.glob("*.log")):
        ym = log.stem[:7]  # 2026-05
        out_dir = TARGET / ym
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        out = out_dir / f"flush-{ts}.json"
        records = []
        with log.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # 行格式: "<iso-ts> <cwd> <message-or-json>"
                parts = line.split(" ", 2)
                if len(parts) >= 3:
                    records.append({"ts": parts[0], "cwd": parts[1], "msg": parts[2]})
        if records:
            out.write_text(json.dumps(records, ensure_ascii=False, indent=2))
        log.unlink()  # flush 完成才删

if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)  # 静默失败，不影响 SessionEnd
PY
```

- [ ] **Step 4: 测试 flush**

```bash
mkdir -p audit/.queue
echo "2026-05-03T10:00:00 /tmp test message" > audit/.queue/2026-05-03.log
python3 scripts/lib/audit_flush.py
ls audit/2026-05/ && cat audit/2026-05/flush-*.json
```

Expected: 输出包含 `[{"ts":"2026-05-03T10:00:00","cwd":"/tmp","msg":"test message"}]`

- [ ] **Step 5: 清理测试残留 + 提交**

```bash
git clean -f audit/2026-05/flush-*.json 2>/dev/null
git add scripts/lib/audit_async.sh scripts/lib/audit_flush.py
git commit -m "feat(gate): 异步 audit 工具函数 + flush 脚本"
```

---

## Task 4.2: run.py audit 调用改异步

**Files:**
- Modify: `scripts/gates/run.py`

- [ ] **Step 1: 找到原同步写盘函数**

```bash
grep -n "write_audit\|audit_path\|json.dump.*audit" scripts/gates/run.py | head -20
```

- [ ] **Step 2: 把同步写盘函数体替换为异步追加**

定位到 audit 写函数（spec §4.2 / 当前命名可能是 `write_audit_sync` 或 `audit.py` 里的函数），改成：

```python
def write_audit(record: dict) -> None:
    """异步 audit：追加到 .queue，由 SessionEnd flush 整理。失败完全静默。"""
    try:
        from datetime import datetime
        from pathlib import Path
        d = Path("audit/.queue"); d.mkdir(parents=True, exist_ok=True)
        with open(d / f"{datetime.now():%Y-%m-%d}.log", "a") as f:
            ts = datetime.now().isoformat()
            cwd = os.getcwd()
            f.write(f"{ts} {cwd} {json.dumps(record, ensure_ascii=False)}\n")
    except Exception:
        pass  # audit 失败不影响决策
```

> 如果 audit 函数在 `scripts/lib/audit.py` 之类独立文件，改那个文件即可。

- [ ] **Step 3: 跑全套 gates 测试**

```bash
python3 -m pytest tests/gates/ -x -q 2>&1 | tail -10
```

Expected: 全过

- [ ] **Step 4: 验证 audit 落盘到新位置**

```bash
python3 scripts/gates/run.py --trigger=manual 2>&1 | tail -3
ls audit/.queue/
```

Expected: `.queue` 下有今天的 .log 文件

- [ ] **Step 5: 提交**

```bash
git add scripts/gates/run.py scripts/lib/audit.py 2>/dev/null
git commit -m "refactor(gate): run.py audit 写盘改异步（O_APPEND 到 .queue）"
```

---

## Task 4.3: SessionEnd hook 加 audit_flush

**Files:**
- Modify: `.claude/hooks/extract-experience.sh`（或新建专门 flush hook）

- [ ] **Step 1: 看现有 SessionEnd hook 结构**

```bash
grep -A5 "SessionEnd\|extract-experience" .claude/settings.json
cat .claude/hooks/extract-experience.sh | head -20
```

- [ ] **Step 2: 在 extract-experience.sh 末尾追加 flush 调用**

用 Edit 工具，在脚本末尾（exit 0 前）追加：

```bash
# audit flush（best-effort，失败静默）
python3 scripts/lib/audit_flush.py 2>/dev/null || true
```

- [ ] **Step 3: 手工触发 flush 验证**

```bash
echo "test $(date)" > audit/.queue/$(date +%Y-%m-%d).log
bash .claude/hooks/extract-experience.sh
ls audit/$(date +%Y-%m)/ | grep flush
```

- [ ] **Step 4: 提交**

```bash
git add .claude/hooks/extract-experience.sh
git commit -m "feat(gate): SessionEnd hook 调用 audit_flush 整理 .queue"
```

---

## Task 4.4: run.py 加 main() 最外层 try/except

**Files:**
- Modify: `scripts/gates/run.py`

- [ ] **Step 1: 找现有 main() / `if __name__`**

```bash
grep -n "def main\|if __name__" scripts/gates/run.py | tail -5
```

- [ ] **Step 2: 把现有 main() 改名为 _real_main，新增包装 main()**

用 Edit：

```python
def _real_main():
    # ... 原 main() 内容 ...

def main():
    try:
        return _real_main()
    except SystemExit:
        raise
    except BaseException:
        try:
            from datetime import datetime
            import traceback
            with open("/tmp/run-py-error.log", "a") as f:
                f.write(f"\n--- {datetime.now()} ---\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
        sys.exit(2)  # rc=2 → trigger 层映射为 fail-open
```

- [ ] **Step 3: 写故障注入测试**

```bash
cat > tests/gates/test_run_py_outer_catch.py <<'PY'
"""验证 run.py 的最外层 try/except：注入 NameError 后应 sys.exit(2)，不抛栈。"""
import subprocess, sys

def test_run_py_handles_unexpected_exception(tmp_path, monkeypatch):
    # 用 PYTHONPATH 注入一个会触发 NameError 的 sitecustomize
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "import scripts.gates.run as r\n"
        "_orig = r._real_main\n"
        "def boom(): raise NameError('injected')\n"
        "r._real_main = boom\n"
    )
    env = dict(__import__('os').environ)
    env["PYTHONPATH"] = f"{tmp_path}:{env.get('PYTHONPATH','')}"
    res = subprocess.run(
        [sys.executable, "scripts/gates/run.py", "--trigger=manual"],
        capture_output=True, env=env, text=True
    )
    assert res.returncode == 2, f"expected 2, got {res.returncode}; stderr={res.stderr}"
    assert "Traceback" not in res.stderr, "栈不应泄漏到 stderr"
PY
```

- [ ] **Step 4: 跑测试**

```bash
python3 -m pytest tests/gates/test_run_py_outer_catch.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/gates/run.py tests/gates/test_run_py_outer_catch.py
git commit -m "feat(gate): run.py main() 最外层 try/except → sys.exit(2)"
```

---

## Task 4.5: 推 + 提 PR-4

- [ ] **Step 1: push + PR**

```bash
git push -u origin feat/gate-pr4-async-audit
gh pr create --title "feat(gate): PR-4 异步 audit + run.py 最外层兜底" --body "$(cat <<'EOF'
## Summary

- 新增 `scripts/lib/audit_async.sh` + `scripts/lib/audit_flush.py`
- `run.py` 同步写 audit → 异步追加 `.queue/<date>.log`，SessionEnd 由 flush 整理
- `run.py` `main()` 加最外层 try/except → 任何未捕获异常映射到 sys.exit(2)（trigger 层 fail-open）
- 新增 `tests/gates/test_run_py_outer_catch.py` 故障注入测试

## 兑现的设计承诺

spec §1.2 缺陷 #1（fail-open 不完整）和 #5（audit 与决策共享失败域）的最终修复。

## Test plan

- [x] `pytest tests/gates/test_run_py_outer_catch.py -v` → PASS
- [x] audit 落盘到 .queue → SessionEnd 后 flush 到 audit/<YYYY-MM>/
- [x] 注入 NameError 验证 fail-open
EOF
)"
```

---

# 完成后清理

## Task 5.1: 4 个 PR 全 merge 后归档

- [ ] **Step 1: 验证 develop 上 4 个 commit 全在**

```bash
git log --oneline develop | grep -E "PR-[1-4]" | head
```

- [ ] **Step 2: 把本计划归档**

```bash
git mv context/team/engineering-spec/plans/2026-05-03-gate-system-A+B-refactor.md \
       context/team/engineering-spec/plans/history/
```

- [ ] **Step 3: 更新两个 INDEX**

用 Edit：
- 从 `plans/INDEX.md` 表格删除本计划行
- 在 `plans/history/INDEX.md` 增加一行

- [ ] **Step 4: 剥离 spec 文档的历史段**

把 `context/team/engineering-spec/design-guidance/gate-system-architecture.md` 的 §1.3（已排除的方案）和 §5（迁移步骤）剪到一个新归档 `engineering-spec/specs/2026-05-03-gate-refactor-history.md`，spec 文档剩下纯架构描述。

- [ ] **Step 5: 提交**

```bash
git commit -am "chore(gate): 重构完成，归档 plan + 剥离 spec 历史段"
```

---

# 整体验收

| 指标 | 目标 | 验证命令 |
|---|---|---|
| 单测全过 | `bash tests/hooks/test_pre_tool_use_guard.sh` `PASS=20 FAIL=0` | 跑测试 |
| BYPASS 测试 | `bash tests/hooks/test_global_bypass.sh` `PASS=3 FAIL=0` | 跑测试 |
| 故障注入 | `pytest tests/gates/test_run_py_outer_catch.py` PASS | 跑测试 |
| 锁死复现 | 注入 `raise NameError` 到 run.py，工具仍可用 | 手工 |
| 热路径文件数 | 1（仅 guard.sh） | `wc -l .claude/hooks/pre-tool-use-guard.sh` |
| 全局逃生 | `CLAUDE_GATES_GLOBAL_BYPASS="x" + 任何被拦操作` 通过 | 手工 |
