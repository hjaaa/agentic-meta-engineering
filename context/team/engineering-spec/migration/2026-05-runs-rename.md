# runs/ 迁移说明：requirements/ → runs/ 批量 rename

## 背景

REQ-2026-009 决定将需求存放目录从 `requirements/REQ-*/` 迁移到 `runs/REQ-*/`，
以与"工作流运行记录"语义对齐（详见 plan.md D-002 / D-007 决策）。

本文档说明迁移工具的使用方式、安装步骤、顺序约束，以及 risky_unmapped 人工 review 指引。

来源：`requirements/REQ-2026-009/artifacts/detailed-design.md` §9（行 1137-1285）

---

## 工具位置

| 文件 | 作用 |
|---|---|
| `scripts/lib/migrate_requirements_to_runs.py` | 批量扫描 + 替换工具（Python） |
| `scripts/git-hooks/pre-commit-rename-guard.sh` | git pre-commit hook，拦截新增 `requirements/REQ-` 字面量 |

---

## 迁移顺序约束（§9.8）

⚠️ **严格遵守以下 4 步顺序**，禁止跳过 dry_run 或直接 wet_run：

```text
1. dry_run（本工具）       → 查看报告，确认引用数量与 risky_unmapped 清单
2. 人工 review            → 逐条处理 risky_unmapped（f-string / concat 引用）
3. wet_run（本工具）       → 执行真正替换
4. 自检                   → grep 字面量数 ≤ 白名单数
```

F-013 仅交付工具本身，**不在本 feature 执行真正的 wet_run**。
wet_run 留待 F-012 Plan 7 清理阶段由人工触发。

---

## 使用方法

### 1. dry_run（推荐先跑）

```bash
python3 scripts/lib/migrate_requirements_to_runs.py
```

默认 `dry_run=True`，只输出报告，不写任何文件。

### 2. 查看报告字段

| 字段 | 含义 |
|---|---|
| `scanned_files` | 扫描的文件总数 |
| `references_found` | 可自动改的字面量引用 |
| `risky_unmapped` | 需人工 review 的 f-string / concat 引用 |
| `skipped_whitelist` | 命中白名单、跳过的引用 |
| `files_changed` | wet_run 实际修改的文件（dry_run 下为空） |
| `dry_run` | `True` = 仅报告，`False` = 真正替换 |
| `duration_ms` | 扫描耗时（毫秒） |

### 3. 处理 risky_unmapped

`risky_unmapped` 中的引用（`f_string` / `concat` kind）**不会被自动改写**。
需人工将其改为使用 `_resolve_run_dir(req_id)`（双路径 loader，F-011 D-007 实现）：

```python
# 改写前（risky_unmapped）
path = Path(f"requirements/{req_id}/artifacts")
path = Path("requirements/" + req_id + "/plan.md")

# 改写后（推荐，兼容迁移过渡期）
from workflow_loader import _resolve_run_dir
path = _resolve_run_dir(req_id) / "artifacts"
path = _resolve_run_dir(req_id) / "plan.md"
```

### 4. wet_run（人工确认后执行）

```bash
python3 scripts/lib/migrate_requirements_to_runs.py --wet-run
```

### 5. 自检

```bash
# 自检：字面量残留数应 ≤ 白名单文件数
grep -rn "requirements/REQ-" . \
  --include="*.py" --include="*.sh" --include="*.yaml" --include="*.md" \
  | grep -v "requirements/INDEX.md" \
  | grep -v "requirements/REQ-.*/plan.md" \
  | grep -v ".archived/" \
  | wc -l
```

---

## pre-commit hook 安装

### 方式一：symlink（推荐，开箱即用）

```bash
# 与既有 pre-commit hook 联动（在 scripts/git-hooks/pre-commit 末尾追加调用）
echo '' >> scripts/git-hooks/pre-commit
echo '# F-013: rename guard' >> scripts/git-hooks/pre-commit
echo 'bash scripts/git-hooks/pre-commit-rename-guard.sh' >> scripts/git-hooks/pre-commit
```

### 方式二：独立安装为 git hook

```bash
# 已有 core.hooksPath 指向 scripts/git-hooks 的团队：直接生效（无需额外操作）
# 核查：
git config core.hooksPath
# 应输出：scripts/git-hooks

# 如未配置，一次性设置：
git config core.hooksPath scripts/git-hooks
```

### 验证安装

```bash
# 模拟新增 requirements/REQ- 引用，应 exit 2
echo '+new_path = "requirements/REQ-2026-001/plan.md"' | \
  CLAUDE_GATES_GLOBAL_BYPASS="" bash scripts/git-hooks/pre-commit-rename-guard.sh
# 预期：exit 2 + stderr 提示
```

---

## hook 放行规则

| 情况 | 行为 |
|---|---|
| 命中白名单路径 | 放行 |
| `*.md` 文件中 markdown 引用块（`> ...`）内 | 放行（叙述性引用） |
| `*.md` 文件中代码块（``` ``` ```）内 | 放行（叙述性引用） |
| 新增 `requirements/REQ-` 字面量（正文） | 阻止 exit 2 |

---

## 白名单规则

以下路径的字面量引用**不会被改写**，也不会被 hook 拦截（即使新增）：

- `requirements/INDEX.md`
- `requirements/REQ-*/plan.md`（历史 ADR 段）
- `*.archived/` 目录下所有文件
- 工具自身文件（`scripts/lib/migrate_requirements_to_runs.py` / `scripts/git-hooks/pre-commit-rename-guard.sh`）
- 测试文件 / fixture（`tests/tools/`）
- 本迁移文档（`context/team/engineering-spec/migration/`）

---

## 紧急绕过（慎用）

hook 支持全局逃生变量（与 `.claude/hooks/pre-tool-use-guard.sh` 同口径）：

```bash
CLAUDE_GATES_GLOBAL_BYPASS="emergency-fix-pr-123" git commit -m "..."
```

- reason 字符串 strip 后须 ≥ 8 字符，否则仍阻止
- bypass 操作会记录到 audit 日志

---

## 影响域

**本 feature（F-013）新增文件**：
- `scripts/lib/migrate_requirements_to_runs.py`
- `scripts/git-hooks/pre-commit-rename-guard.sh`
- `tests/tools/test_migrate_requirements.py`
- `tests/tools/fixtures/migrate_requirements/`
- `context/team/engineering-spec/migration/2026-05-runs-rename.md`（本文件）

**不在本 feature 中修改**：
- `requirements/INDEX.md`（等 F-012 真迁移时由工具自身重写）
- `scripts/lib/workflow_loader.py`（D-007 双路径 loader，调用方）
- 历史 commit message（git history 不可改）
- 已 sign-off 的 review verdict JSON
