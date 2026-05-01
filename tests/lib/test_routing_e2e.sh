#!/usr/bin/env bash
# F-004 E2E：真 routing.py 内部函数 + 真 routing.yaml + 假 git diff
# 用 mktemp 起临时 git 仓库 + git commit 制造 diff，触发 routing.py 走完整内部路径
#
# 设计说明：
#   routing.py 的 main() 在步骤 2 强制 tty 检查（sys.stdin.isatty()），
#   非 tty 环境下 E3/E4 的 schema/yaml 错误无法通过 main() CLI 触达（会先退码 2）。
#   因此本脚本对各用例选择最合适的测试路径：
#
#   E1 SKIP — pty 子进程在 bash 内复杂，已由 T1-T3（test_code_review_routing.py）pty 单测覆盖
#   E2 — 改 5 个 .md 文件（全 trivial），直接调用 _build_plan 验证 trivial_only=True
#   E3 — routing.yaml must 写 6 条（超 MAX_MUST_RULES=5），调用 _validate_schema 期望 exit_code=3
#   E4 — routing.yaml 写不合法 yaml，调用 _load_yaml 期望 exit_code=4

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
PASS=0
FAIL=0

cleanup() {
    rm -rf "$WORK"
}
trap cleanup EXIT

pass() { echo "[e2e] $1 PASS"; PASS=$((PASS + 1)); }
skip() { echo "[e2e] $1 SKIP（$2）"; }
fail() { echo "[e2e] $1 FAIL: $2"; FAIL=$((FAIL + 1)); }

# ──────────────────────────────────────────────────
# 准备：建立临时 git 仓库（E2/E3/E4 公用基础结构）
# routing.py import 路径：以 REPO_ROOT 为根，scripts.lib.code_review_routing
# ──────────────────────────────────────────────────

setup_work_dir() {
    local dir="$1"
    mkdir -p "$dir"
    cd "$dir"
    git init -q
    git config user.email "e2e@test.local"
    git config user.name "E2E Test"
    # 建 base commit，防止仓库空
    echo "init" > .gitkeep
    git add .gitkeep
    git commit -q -m "init"
}

# ──────────────────────────────────────────────────
# E1：pty 子进程在 bash 内复杂，已由 T1-T3 单测覆盖
# ──────────────────────────────────────────────────
skip "E1" "pty 子进程在 bash 内复杂，已由 T1-T3（test_code_review_routing.py）pty 单测覆盖"

# ──────────────────────────────────────────────────
# E2：5 个 .md 文件（全 trivial）→ _build_plan 返回 trivial_only=True
#     使用真实 routing.yaml + 真实 git diff（通过 REPO_ROOT 直接运行）
# ──────────────────────────────────────────────────
E2_DIR="$WORK/e2_trivial"
setup_work_dir "$E2_DIR"
BASE_SHA="$(git rev-parse HEAD)"
mkdir -p docs
for i in 1 2 3 4 5; do
    echo "trivial change $i" > "docs/note${i}.md"
done
git add .
git commit -q -m "add 5 trivial md files"
HEAD_SHA="$(git rev-parse HEAD)"

# 直接用 Python 在 REPO_ROOT 内部调用 _build_plan，用 E2_DIR 的真实 git diff
E2_OUT="$(cd "$REPO_ROOT" && python3 - <<PYEOF 2>&1
import subprocess
import sys
sys.path.insert(0, ".")
from scripts.lib.code_review_routing import (
    _build_plan, _validate_schema, _load_yaml, ROUTING_YAML_PATH
)
# 拿到 E2 仓库的 diff 文件列表
result = subprocess.run(
    ["git", "diff", "--name-only", "$BASE_SHA", "$HEAD_SHA"],
    cwd="$E2_DIR",
    capture_output=True, text=True, check=True,
)
files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
config = _validate_schema(_load_yaml(ROUTING_YAML_PATH))
plan = _build_plan(files, config)
print("trivial_only=" + str(plan.trivial_only))
print("files_total=" + str(plan.files_total))
print("files_trivial=" + str(plan.files_trivial))
PYEOF
)" || true

if echo "$E2_OUT" | grep -q "trivial_only=True"; then
    pass "E2"
else
    fail "E2" "期望 trivial_only=True，实际输出：${E2_OUT:0:300}"
fi

# ──────────────────────────────────────────────────
# E3：routing.yaml must 写 6 条（超 MAX_MUST_RULES=5）
#     调用 _validate_schema 期望 RoutingSchemaError，exit_code=3
# ──────────────────────────────────────────────────
E3_YAML="$WORK/e3_routing.yaml"
cat > "$E3_YAML" << 'YAML_EOF'
version: 1
must:
  - pattern: "scripts/lib/*.py"
    checkers: [security-checker]
  - pattern: "scripts/gates/**"
    checkers: [security-checker]
  - pattern: ".claude/commands/**"
    checkers: [design-consistency-checker]
  - pattern: ".claude/skills/**/SKILL.md"
    checkers: [design-consistency-checker]
  - pattern: ".claude/hooks/**"
    checkers: [security-checker]
  - pattern: "extra/rule/*.py"
    checkers: [complexity-checker]
suggest:
  - pattern: "context/team/**"
    checkers: [design-consistency-checker]
trivial_whitelist:
  - "**/*.md"
YAML_EOF

E3_OUT="$(cd "$REPO_ROOT" && python3 - <<PYEOF 2>&1
import sys
sys.path.insert(0, ".")
from pathlib import Path
from scripts.lib.code_review_routing import (
    _validate_schema, _load_yaml, EXIT_SCHEMA_INVALID
)
try:
    raw = _load_yaml(Path("$E3_YAML"))
    _validate_schema(raw)
    print("ERROR: 期望 RoutingSchemaError 但未抛出")
    sys.exit(0)
except Exception as e:
    exit_code = getattr(e, 'exit_code', -1)
    print("exit_code=" + str(exit_code))
    print("detail=" + str(e))
    sys.exit(0)
PYEOF
)" || true

if echo "$E3_OUT" | grep -q "exit_code=3" && echo "$E3_OUT" | grep -q "V3"; then
    pass "E3"
else
    fail "E3" "期望 exit_code=3 且含 V3，实际输出：${E3_OUT:0:300}"
fi

# ──────────────────────────────────────────────────
# E4：routing.yaml 写不合法 yaml → _load_yaml 期望 RoutingYamlError，exit_code=4
# ──────────────────────────────────────────────────
E4_YAML="$WORK/e4_routing.yaml"
cat > "$E4_YAML" << 'YAML_EOF'
version: 1
must:
  - pattern: "scripts/**"
    checkers: [security-checker
suggest:
  - pattern "context/**"
trivial_whitelist:
  - "**/*.md"
YAML_EOF

E4_OUT="$(cd "$REPO_ROOT" && python3 - <<PYEOF 2>&1
import sys
sys.path.insert(0, ".")
from pathlib import Path
from scripts.lib.code_review_routing import (
    _load_yaml, EXIT_YAML_LOAD_ERROR
)
try:
    raw = _load_yaml(Path("$E4_YAML"))
    print("ERROR: 期望 RoutingYamlError 但未抛出")
    sys.exit(0)
except Exception as e:
    exit_code = getattr(e, 'exit_code', -1)
    print("exit_code=" + str(exit_code))
    print("detail=" + str(e))
    sys.exit(0)
PYEOF
)" || true

if echo "$E4_OUT" | grep -q "exit_code=4"; then
    pass "E4"
else
    fail "E4" "期望 exit_code=4，实际输出：${E4_OUT:0:300}"
fi

# ──────────────────────────────────────────────────
# 汇总
# ──────────────────────────────────────────────────
echo ""
echo "[e2e] 汇总：PASS=$PASS  FAIL=$FAIL"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
