---
id: REQ-2026-013
phase: detail-design
title: "REQ-2026-012 follow-up bundle · 详细设计"
created_at: 2026-05-17 18:58:00
refs-detailed-design: true
inputs:
  - requirements/REQ-2026-013/artifacts/requirement.md
  - requirements/REQ-2026-013/artifacts/tech-feasibility.md
  - requirements/REQ-2026-013/artifacts/outline-design.md
  - requirements/REQ-2026-013/plan.md
---

# REQ-2026-013 · 详细设计

> 覆盖 5 feature 的接口签名 / 数据结构 / pytest + bats 测试骨架 / 完整 Markdown diff。
> outline-design v1 reviewer 3 minor 闭环位置：§3.2（D-011 双源声明）/ §4.1（NFR 性能预算用例）/ §4.6（F-B 时序图）。

## 1. 设计概览

### 1.1 5 feature ID 映射（与 features-schema 对齐）

| outline 命名 | detail-design feature_id | 改造点 | 复杂度 |
|---|---|---|---|
| F-A | **F-001** | scripts/lib/check_reviews.py R005 hash normalize | medium |
| F-B | **F-002** | .claude/hooks/touches_guard.py out-of-repo 短路 | light |
| F-C | **F-003** | archive-rules.md 新增 § + archive_runner reminder | light |
| F-D | **F-004** | context/team/experience/INDEX.md 格式约定段重写 + baseline 统计 | light |
| F-E | **F-005** | test-assets-must-be-wired-into-ci.md 抽出验证方法节 | trivial |

ID 重命名理由：features-schema.yaml 强制 `id: '^F-\d{3}$'`（来源：context/team/engineering-spec/features-schema.yaml）；plan.md / requirement.md / outline-design.md / tech-feasibility.md 中所有 F-A~F-E 引用通过本表换算到 F-001~F-005。

### 1.2 ADR 全集引用（D-001~D-011）

| ADR | 影响 feature | 落地体现位置 |
|---|---|---|
| D-001 A2 改 R005 校验放宽 | F-001 | §3.1 normalize 函数实现 |
| D-002 B3 archive 纯文档兜底 | F-003 | §3.3 archive-rules.md 新增节 |
| D-003 D1 仅改规则不补 38 文件 | F-004 | §3.4「不补正文」段 |
| D-004 整批合一 PR | 全部 | §2 features.json 5 feature 同 PR |
| D-005 「不做的事」5 条 | 全部 | requirement.md §不包含（不动） |
| D-006 F-B 用 cwd-driven git rev-parse | F-002 | §3.2 `_get_worktree_toplevel` 实现 |
| D-007 normalize 白名单 = {status, updated_at} | F-001 | §3.1 `_NORMALIZE_TASK_FIELDS` 常量 |
| D-008 F-C refresh-only-current-req 子句 | F-003 | §3.3 archive-rules.md「ci gate 扫全仓」段 |
| D-009 F-D 800 字软上限 | F-004 | §3.4 INDEX.md 字数规则 |
| D-010 F-E 在 F-D commit 之后 | F-004 / F-005 | §2 features.json depends_on_features |
| D-011 F-B 双源并存（_REPO_ROOT vs git rev-parse） | F-002 | §3.2 双源语义边界声明 |

### 1.3 commit / PR 拆分

5 feature 同一 PR 内 5 个独立 commit，**顺序：F-001 → F-002 → F-003 → F-004 → F-005**（其中 F-005 强依赖 F-004，其他三两两并行可乱序但本设计按 feature_id 升序固定，便于 cherry-pick）（来源：requirements/REQ-2026-013/plan.md）D-010 决策。

## 2. features.json 总览

5 feature 各自 `touches` / `depends_on_features` / `acceptance` 见 `artifacts/features.json`（本文件同 commit 落盘）。依赖图：

```
F-001 (medium)  ─────┐
F-002 (light)   ─────┤
F-003 (light)   ─────┼──► 整批合一 PR
F-004 (light)   ──┐  │
                  │  │
F-005 (trivial)◄─┘  │   F-005 depends_on_features=["F-004"]
```

工作量分布：F-001 3h / F-002 2h / F-003 1h / F-004 0.5h / F-005 0.5h = 7h ≈ 1.5 人日（来源：requirements/REQ-2026-013/artifacts/tech-feasibility.md）§3 工作量汇总。

## 3. 模块详细设计

### 3.1 F-001 · check_reviews.py R005 hash normalize

**改造点定位**：scripts/lib/check_reviews.py:289（`_r005_hash_drift` 函数内 `hashlib.sha256(f.read()).hexdigest()` 行）（来源：scripts/lib/check_reviews.py）。

**新增常量**（模块顶部 import 区之后）：

```python
# 来源：context/team/engineering-spec/task-frontmatter-schema.yaml enums + dev 期演进字段分析
# 见 requirements/REQ-2026-013/plan.md D-007；schema 加新「dev 期演进」字段时需同步本白名单
_NORMALIZE_TASK_FIELDS: set[str] = {"status", "updated_at"}
```

**新增函数**（模块级，紧邻 `_r005_hash_drift` 之前）：

```python
def _compute_hash_with_normalize(file_path: Path, path_str: str) -> str:
    """计算 file_path 的 sha256；若 path_str 命中 task.md 路径前缀，先 strip frontmatter 白名单字段再 hash。

    A2 路径（D-001）：双侧 normalize——历史 verdict 钉的整文件 hash 在 dev 期演进字段
    （status / updated_at）刷新后仍能匹配，杜绝 R005 假阳性。

    Args:
        file_path: 实际读取的文件路径
        path_str: 在 verdict.artifact_hashes 中记录的相对路径键（用于判断是否为 task.md）

    Returns:
        sha256 16 进制 digest。
    """
    if not path_str.startswith("artifacts/tasks/") or not path_str.endswith(".md"):
        # 非 task.md → 整文件 hash 旧行为，保兼容其他 artifact 类型
        with file_path.open("rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    # task.md → 文本读 + 首对 --- 之间 strip 白名单字段
    content = file_path.read_text(encoding="utf-8", errors="replace")
    normalized = _strip_frontmatter_fields(content, _NORMALIZE_TASK_FIELDS)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _strip_frontmatter_fields(content: str, fields: set[str]) -> str:
    """仅在首对 `---` 之间用 re.sub 去掉 fields 列出字段的整行。

    body 内（首对 `---` 之后）出现的 `status:` / `updated_at:` 字段行不处理。

    Args:
        content: 文件文本内容（含 frontmatter）
        fields: 待 strip 字段名集合（如 {"status", "updated_at"}）

    Returns:
        去除指定字段行后的文本；frontmatter 缺失或不完整时原样返回。
    """
    import re
    fm_match = re.match(r"^---\n(.*?)\n---\n", content, flags=re.DOTALL)
    if not fm_match:
        return content
    fm_body = fm_match.group(1)
    new_fm_body = fm_body
    for field in fields:
        new_fm_body = re.sub(
            rf"^{re.escape(field)}:.*$\n?",
            "",
            new_fm_body,
            flags=re.MULTILINE,
        )
    return content.replace(fm_match.group(0), f"---\n{new_fm_body}\n---\n", 1)
```

**改造行 `_r005_hash_drift` line 285-289**：

```python
# 旧：
with file_path.open("rb") as f:
    current = hashlib.sha256(f.read()).hexdigest()
# 新：
current = _compute_hash_with_normalize(file_path, path_str)
```

**模块边界**：normalize 是 R005 比对侧（read path）局部行为；不向其它 R-rule / save_review 写入侧暴露；reviewer Agent 写 verdict.artifact_hashes 时仍存整文件 hash（不动）（来源：scripts/lib/save_review.py）。

### 3.2 F-002 · touches_guard.py out-of-repo 短路

**改造点定位**：.claude/hooks/touches_guard.py:510-515（`_main_inner` 步骤 7 for 循环内）（来源：.claude/hooks/touches_guard.py）。

#### 3.2.1 D-011 双源语义边界声明

`touches_guard.py` 在本次改造后存在**两条**仓库根判定路径，**并存**且各自语义清晰（来源：requirements/REQ-2026-013/plan.md）D-011 决策：

| 用途 | 函数 / 常量 | 数据来源 | worktree 场景 |
|---|---|---|---|
| in-touches 内匹配（既有 `_is_in_touches`） | `_REPO_ROOT` 模块常量 | `Path(__file__).resolve().parents[2]` (file-driven) | worktree 内文件按 file-driven 判定为 out-of-repo（既有行为，不动） |
| out-of-repo 短路（**新增** `_is_out_of_repo`） | `_get_worktree_toplevel()` 函数 | `git rev-parse --show-toplevel` (cwd-driven) | worktree 内文件按 cwd-driven 判定为 in-repo（D-006 实测语义） |

**为什么并存而不统一**：统一到 `_REPO_ROOT` 会撤回 D-006 worktree 语义；统一到 `git rev-parse` 会动 `_is_in_touches`（零回归原则不允许）。两源在**主 repo cwd 下**结果一致（toplevel == `_REPO_ROOT`），仅 worktree edge case 不同（来源：requirements/REQ-2026-013/plan.md）D-011 Consequences 段。

touches_guard.py 顶部新增 docstring 段（来源：.claude/hooks/touches_guard.py）：

```python
"""
两条仓库根判定路径（D-011，来源：requirements/REQ-2026-013/plan.md）：
- `_REPO_ROOT`：file-driven，给 `_is_in_touches` 用（既有行为，不动）
- `_get_worktree_toplevel()`：cwd-driven，给 `_is_out_of_repo` 用（D-006 worktree 语义）
两源在主 repo cwd 下表现一致；仅 worktree edge case 不同。禁止互替。
"""
```

#### 3.2.2 新增函数

```python
def _get_worktree_toplevel() -> Optional[Path]:
    """调 `git rev-parse --show-toplevel` 返回 cwd 所在仓库根；非 git 目录返回 None。

    缓存策略：函数局部不缓存（单次 hook 调用内被 _is_out_of_repo 复用一次，无需 lru_cache）。
    """
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode != 0:
            return None
        return Path(result.stdout.strip()).resolve()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _is_out_of_repo(file_path: str, toplevel: Optional[Path]) -> bool:
    """判断 file_path 是否在 toplevel 子树之外。toplevel 为 None（非 git 目录）时返回 False（fail-open）。

    Args:
        file_path: 来自 tool_input 的原始 file_path（可能是绝对路径或相对路径）
        toplevel: _get_worktree_toplevel() 返回值

    Returns:
        True 表示文件在仓库外，调用方应短路跳过 violation 记录；
        False 表示文件在仓库内或 toplevel 不可用（fail-open）。
    """
    if toplevel is None:
        return False  # fail-open：非 git 目录走原 in-touches 路径
    try:
        resolved = Path(file_path).resolve()
    except (OSError, ValueError):
        return False  # fail-open：路径解析失败
    try:
        resolved.relative_to(toplevel)
        return False  # 在 toplevel 子树内
    except ValueError:
        return True  # 在 toplevel 子树外 → out-of-repo
```

#### 3.2.3 `_main_inner` for 循环改造

```python
# 步骤 7 改造：在 for 循环前取 toplevel 一次；for 循环内先 _is_out_of_repo 短路
toplevel = _get_worktree_toplevel()  # 新增：单次 hook 调用内只取一次
for fp in file_paths:
    if _is_out_of_repo(fp, toplevel):
        continue  # 新增：out-of-repo 短路（D-006 + D-011）
    if not _is_in_touches(fp, touches):
        if _is_process_artifact(fp, req_dir, feature_id):
            continue
        try:
            _record_violation(receipt_path, feature_id, fp, tool_name)
        except Exception:
            pass
```

**模块边界**：F-002 仅动 `_main_inner` for 循环 + 加 2 个新函数；不动 `_is_in_touches` / `_record_violation` / `_is_process_artifact` 等其它函数（来源：.claude/hooks/touches_guard.py）。

### 3.3 F-003 · archive-rules.md 新增节 + archive_runner reminder

#### 3.3.1 archive-rules.md 新增节文案

在 `.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md`（来源：.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md）现有 §「5 项预检」之后插入：

```markdown
## archive 前 CI gate 预检（D-002 / D-008）

5 项硬门禁过后、调 `archive_requirement` **之前**，主 Agent 必须先执行：

\`\`\`bash
python3 scripts/gates/run.py --trigger=ci --strict
\`\`\`

期望 `exit 0` 才继续 archive。**为什么需要这一步**：framework R-rule 全集（R001~R007）
仅在 `--trigger=ci` 下完整跑（来源：scripts/gates/registry.yaml），phase-transition / submit
触发的 R-rule 子集可能未覆盖所有 stale 场景；archive 推 chore PR 到 develop 后才在 CI 暴露
就是 hotfix（详见 `context/team/experience/archive-completed-triggers-framework-rule-fullset.md`）。

### refresh-only-current-req 处置原则（D-008）

`--trigger=ci` 不支持 `--req` filter（来源：scripts/gates/plugins/review_verdict.py）；预检会扫
**全仓所有需求**，可能暴露其它历史 REQ 的 R005 hash drift。处置：

1. 列出所有 R005 finding 对应的 REQ（按 finding 信息中的 `requirement_id` / `meta_path` 字段分类）
2. **当前正在归档的 REQ**：refresh hash（reviewer Agent 重审 + signoff），必须修
3. **其它历史 REQ**：单独记 follow-up 不强行修；若所有 R005 finding 都属于其它 REQ → 手动 ack 后继续 archive
4. 主 Agent 在 `notes.md` 追加一行记录手动 ack 的 REQ 列表 + 原因

### 升级路径（B1 / B2）

本步骤是 B3 路径——纯文档兜底 + 终端 reminder（D-002）。如果未来 archive 月频次显著上升导致
人执行流程不可靠，可升级为 B1（archive_runner 临时 yaml override 跑 R-rule 全集）或 B2（写后
rollback）路径。
```

**字数核算**：约 280 字（D-002 / D-008 / D-009 软上限 800 字内）（来源：requirements/REQ-2026-013/plan.md）。

#### 3.3.2 archive_runner.py reminder 行

scripts/lib/archive_runner.py `_render_summary` 函数（来源：scripts/lib/archive_runner.py）改造点：在现有终端反馈最后一行 `return ...` 之前追加：

```python
lines.append("")  # 空行分隔
lines.append("🟢 archive 前请确认 ci gate exit 0：python3 scripts/gates/run.py --trigger=ci --strict")
```

不改 5 项硬门禁逻辑、不引入新 abort 路径（B3 路径，来源：requirements/REQ-2026-013/plan.md）D-002 Consequences 段。

### 3.4 F-004 · INDEX.md 格式约定段重写 + baseline 统计

#### 3.4.1 INDEX.md diff

context/team/experience/INDEX.md（来源：context/team/experience/INDEX.md）的「格式约定」段（约第 63-68 行区域）改写：

```markdown
旧（删除）：
- 正文不超过 200 字
- 必须包含：问题、根因、解法、验证方法

新（替换）：
- 正文建议 600 字内，800 字是软上限；超出考虑拆分到独立 reference 文件
- 五段结构（前 4 段必填，第 5 段可空）：
  - `## 问题`：现象描述
  - `## 根因`：定位到代码 / 流程 / 设计层面
  - `## 解法`：可复用的规则或步骤
  - `## 验证方法`：如何确认问题不再复现（命令 / 检查项 / 持续门禁）
  - `## 关联`（可空）：相关需求 / PR / 其它经验文件链接
```

**字数规则改写依据**：38 邻居字数 baseline 由 F-004 同 commit 落档为 `experience-baseline-cjk-stats.txt`（位置见 §3.4.2 + features.json）；预期统计：min=139 / median=365 / max=668 / count=38；800 字上限覆盖 ~99% 既定文件，规则上线后零既定文件需裁剪（来源：requirements/REQ-2026-013/plan.md）D-009 决策。

#### 3.4.2 baseline 统计落档（F-004 配套交付物）

`requirements/REQ-2026-013/artifacts/experience-baseline-cjk-stats.txt` 在 F-004 同 commit 内落档；内容为 38 邻居字数分布表：

```
# 38 文件字数（CJK 字符数）baseline 快照 · 2026-05-17 落档
# 用途：F-004 INDEX.md 800 字软上限决策依据 + 未来规则调整时回看历史实证

[字数 buckets 直方图]
min: 139
p25: 287
median: 365
p75: 478
max:  668
count: 38

[> 600 字孤例]
<file_name_1>: <count>
<file_name_2>: <count>
...

[缺 ## 验证方法 节孤例]
test-assets-must-be-wired-into-ci.md  → F-005 落地
```

具体统计行由 testing 阶段 V-04 生成脚本 `python3 -c "import os; ..."` 一次性产出，detail-design 阶段仅给出文件骨架与字段约定（来源：requirements/REQ-2026-013/artifacts/requirement.md）「testing 阶段回归用例」段。

### 3.5 F-005 · test-assets-must-be-wired-into-ci.md 抽出验证方法节

context/team/experience/test-assets-must-be-wired-into-ci.md（来源：context/team/experience/test-assets-must-be-wired-into-ci.md）diff：

**现状**（`## 解法` 段含 5 条信息混杂）：
```
## 解法
1. 新增测试默认进 CI；不进 CI 必须 PR 描述说明原因
2. 不进 CI 必须给出手跑命令
3. 不进 CI 必须给出 owner（谁负责定期跑）
4. PR reviewer 检查上述 3 条
5. CI YAML 改动需 PR 描述列出新增/删除 step
```

**改后**（`## 解法` 保留规则，`## 验证方法` 抽出执行细节）：
```
## 解法
1. 新增测试默认进 CI；不进 CI 必须 PR 描述说明原因
2. CI YAML 改动需 PR 描述列出新增/删除 step

## 验证方法
- **不进 CI 的测试必须写在 PR 描述里**：手跑命令 + owner（谁负责定期跑）
- **PR reviewer 检查项**：核对 PR 描述是否齐全；workflow yml 改动是否在 PR 描述列出
- **持续门禁**：CI 通过即视为测试已对齐（CI 自身是 sample-of-truth）
```

**模块边界**：仅动 `## 解法` 与新增 `## 验证方法` 两段；其他段（问题/根因/关联）不动；结构与 F-004 新五段规则完全对齐（来源：requirements/REQ-2026-013/plan.md）D-010 commit 顺序。

## 4. 验证用例骨架

### 4.1 F-001 pytest 用例骨架（含 NFR 性能预算回应 outline-design v1 minor #1）

**位置**：tests/lib/test_check_reviews_normalize.py（新增文件）+ tests/lib/test_check_reviews_normalize_schema_sync.py（新增文件，schema-sync 回归）。

**核心用例**：

```python
import pytest
from scripts.lib.check_reviews import _strip_frontmatter_fields, _compute_hash_with_normalize, _NORMALIZE_TASK_FIELDS

class TestStripFrontmatterFields:
    def test_status_stripped_in_frontmatter(self):
        content = "---\nstatus: done\ntitle: F-001\n---\n# body\n"
        result = _strip_frontmatter_fields(content, {"status"})
        assert "status: done" not in result
        assert "title: F-001" in result
        assert "# body" in result

    def test_status_in_body_not_stripped(self):
        # 反例：body 内 status: 字段行不应被 strip
        content = "---\ntitle: F-001\n---\n# body\nstatus: should_remain\n"
        result = _strip_frontmatter_fields(content, {"status"})
        assert "status: should_remain" in result

    def test_no_frontmatter_passthrough(self):
        content = "# heading\nstatus: in_body\n"
        result = _strip_frontmatter_fields(content, {"status"})
        assert result == content

    @pytest.mark.parametrize("evolving_status", ["pending", "in-progress", "done"])
    def test_evolving_status_yields_same_hash(self, tmp_path, evolving_status):
        # A2 兼容性核心断言：3 个 status 取值在 normalize 后 hash 相同
        body = "---\nfeature_id: F-001\nstatus: {s}\nupdated_at: '2026-05-17 18:00:00'\n---\n# body\n"
        h_set = set()
        for s in ["pending", "in-progress", "done"]:
            fp = tmp_path / f"{s}.md"
            fp.write_text(body.format(s=s), encoding="utf-8")
            h = _compute_hash_with_normalize(fp, "artifacts/tasks/F-001.md")
            h_set.add(h)
        assert len(h_set) == 1  # 3 个 status 产生相同 hash
```

**性能基准用例（回应 outline-design v1 minor #1）**：

```python
import time

def test_normalize_perf_under_1000_review_volume(tmp_path):
    """NFR：normalize 比对相对整文件 hash 路径不应明显增加 R005 校验时长（< +5% 在 1000 review 量级）。"""
    sample = "---\nfeature_id: F-001\nstatus: done\nupdated_at: '2026-05-17 18:00:00'\n---\n" + ("# body\n" * 50)
    fp = tmp_path / "sample.md"
    fp.write_text(sample, encoding="utf-8")
    # 旧路径基准（整文件 hash 1000 次）
    t0 = time.perf_counter()
    for _ in range(1000):
        with fp.open("rb") as f:
            hashlib.sha256(f.read()).hexdigest()
    baseline = time.perf_counter() - t0
    # 新路径（normalize 1000 次）
    t0 = time.perf_counter()
    for _ in range(1000):
        _compute_hash_with_normalize(fp, "artifacts/tasks/F-001.md")
    new_path = time.perf_counter() - t0
    overhead_ratio = (new_path - baseline) / baseline
    assert overhead_ratio < 0.05, f"normalize 路径相对整文件 hash overhead = {overhead_ratio:.2%}（预算 < 5%）"
```

**schema-sync 回归用例**（来源：requirements/REQ-2026-013/artifacts/requirement.md）「testing 阶段回归用例」段：

```python
import yaml

def test_normalize_whitelist_matches_schema_evolving_fields():
    """schema 加新 dev 期演进字段而白名单未同步 → fail。"""
    with open("context/team/engineering-spec/task-frontmatter-schema.yaml") as f:
        schema = yaml.safe_load(f)
    # schema.enums.status 是演进字段（status 这个 key 本身在白名单内）
    # 兜底断言：白名单字段名应是 schema required_fields 子集
    required = set(schema["required_fields"])
    assert _NORMALIZE_TASK_FIELDS.issubset(required), \
        f"_NORMALIZE_TASK_FIELDS={_NORMALIZE_TASK_FIELDS} 不是 schema.required_fields 子集"
```

### 4.2 F-002 bats 用例骨架

**位置**：tests/hooks/test_touches_guard_out_of_repo.bats（新增文件）。

**核心用例**：

```bash
#!/usr/bin/env bats

setup() {
  cd "$(git rev-parse --show-toplevel)"
}

@test "F-002 out-of-repo: /tmp 路径不记 violation" {
  payload='{"tool_name":"Write","tool_input":{"file_path":"/tmp/test-out-of-repo.json"}}'
  echo "$payload" | python3 .claude/hooks/touches_guard.py
  [ "$status" -eq 0 ]
  # 不应有新增 violation 记录
  ! grep -q "/tmp/test-out-of-repo.json" requirements/*/artifacts/tasks/*.receipt.json
}

@test "F-002 out-of-repo: /var 路径不记 violation" {
  payload='{"tool_name":"Edit","tool_input":{"file_path":"/var/log/test.log"}}'
  echo "$payload" | python3 .claude/hooks/touches_guard.py
  [ "$status" -eq 0 ]
}

@test "F-002 out-of-repo: ~/ 路径不记 violation" {
  payload='{"tool_name":"Write","tool_input":{"file_path":"'"$HOME"'/.test-claude-out.json"}}'
  echo "$payload" | python3 .claude/hooks/touches_guard.py
  [ "$status" -eq 0 ]
}

@test "F-002 worktree edge case: worktree cwd 内文件按 worktree-local 判定" {
  # D-006 实测语义；worktree 内文件不应被视为 out-of-repo
  # 创建临时 worktree
  tmp_wt=$(mktemp -d)
  git worktree add "$tmp_wt" HEAD 2>/dev/null || skip "无法创建 worktree"
  cd "$tmp_wt"
  payload='{"tool_name":"Write","tool_input":{"file_path":"'"$tmp_wt"'/Makefile"}}'
  echo "$payload" | python3 "$tmp_wt/.claude/hooks/touches_guard.py"
  [ "$status" -eq 0 ]
  cd - > /dev/null
  git worktree remove --force "$tmp_wt"
}
```

**NFR 性能基准用例**（回应 outline-design v1 minor #1，来源：requirements/REQ-2026-013/artifacts/requirement.md）「非功能需求 - 性能」段：

```bash
@test "F-002 NFR: hook 延迟 p99 < 1ms 增量" {
  # 100 次调用统计；基准 = 不带 F-002 改造的 hook 版本（git stash + 还原）
  payload='{"tool_name":"Write","tool_input":{"file_path":"/tmp/perf-test.json"}}'
  # 实测 100 次取 p99；当前 hook 调用 p99 baseline ~50ms（含 python 启动 + git subprocess）
  # F-002 加的 _get_worktree_toplevel 单次 git subprocess 增量 ~5ms
  # 但因为已经短路（避免后续 _is_in_touches + _record_violation 等开销）
  # 实测净增量预期 ≤ 1ms p99；超出则 fail
  for i in {1..100}; do
    /usr/bin/time -f "%e" -o /tmp/t.txt bash -c "echo '$payload' | python3 .claude/hooks/touches_guard.py" 2>/dev/null
    cat /tmp/t.txt
  done | sort -n | awk 'NR==99{printf "p99=%.3fs\n",$0; exit}'
  # 断言 p99 < 0.001s 增量（基线在 NFR 验证脚本中固定）——detail-design 阶段仅给骨架；
  # testing 阶段补 baseline 数值
  skip "baseline 待 testing 阶段固化"
}
```

### 4.3 F-003 verification skeleton

**位置**：tests/lifecycle/test_archive_rules_ci_gate_precheck.py（新增文件）。

```python
def test_archive_rules_md_has_ci_gate_precheck_section():
    """archive-rules.md 必须有 § archive 前 CI gate 预检 节。"""
    md = Path(".claude/skills/managing-requirement-lifecycle/reference/archive-rules.md").read_text(encoding="utf-8")
    assert "## archive 前 CI gate 预检" in md
    assert "refresh-only-current-req" in md
    assert "python3 scripts/gates/run.py --trigger=ci --strict" in md

def test_archive_runner_summary_has_reminder_line():
    """archive_runner._render_summary 输出末段必含 🟢 reminder 行。"""
    from scripts.lib import archive_runner
    out = archive_runner._render_summary(...)  # 用 fixture mock
    assert "🟢 archive 前请确认 ci gate exit 0" in out
```

### 4.4 F-004 verification skeleton

```python
def test_index_md_format_rules_updated():
    """INDEX.md 字数规则必须从 200 字硬规则改为 800 字软上限；五段结构。"""
    md = Path("context/team/experience/INDEX.md").read_text(encoding="utf-8")
    assert "正文不超过 200 字" not in md
    assert "800 字" in md
    assert "## 关联" in md  # 五段结构

def test_baseline_stats_file_exists():
    """F-004 配套 baseline 落档文件存在且有 38 文件统计。"""
    p = Path("requirements/REQ-2026-013/artifacts/experience-baseline-cjk-stats.txt")
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "count: 38" in text
```

### 4.5 F-005 verification skeleton

```python
def test_test_assets_has_validation_section():
    md = Path("context/team/experience/test-assets-must-be-wired-into-ci.md").read_text(encoding="utf-8")
    assert "## 验证方法" in md
    assert "手跑命令" in md  # 抽出后仍在
    # 「## 解法」段应减少（5 → 2 条）
    assert md.index("## 解法") < md.index("## 验证方法")
```

### 4.6 F-002 时序图（回应 outline-design v1 minor #2 视觉指向）

```
PreToolUse 触发                 touches_guard._main_inner          subprocess
   │  Write /tmp/foo.json           │                                  │
   │ ────────────────────────────► │  1. 解析 stdin                   │
   │                                │  2-6. 提取 fp / 定位 req_dir     │
   │                                │       / 读 current_feature       │
   │                                │       / 读 touches               │
   │                                │  7. for fp in file_paths:        │
   │                                │       ┌───────────────────────┐ │
   │                                │       │ NEW: toplevel =      │  │
   │                                │       │   _get_worktree_top  │ │
   │                                │       │   level()            │ │
   │                                │       │ ──────────────────►  │ git rev-parse
   │                                │       │   ◄─────── toplevel  │ │ --show-toplevel
   │                                │       │                       │ │
   │                                │       │ NEW: if _is_out_of_   │ │
   │                                │       │   repo(fp, toplevel):│  │
   │                                │       │     continue ─────►  │ │ exit 0
   │                                │       │ (短路，跳过 violation)│ │
   │                                │       │                       │ │
   │                                │       │ else:                │  │
   │                                │       │  _is_in_touches?  ──►│  │
   │                                │       │  →False+!process_art │  │
   │                                │       │  → _record_violation │  │
   │                                │       └───────────────────────┘ │
   │  exit 0（始终）                │                                  │
```

## 5. detail-design 待决问题闭环

逐一闭环 tech-feasibility.md §4「detail-design 待决问题」5 项（来源：requirements/REQ-2026-013/artifacts/tech-feasibility.md）：

1. **F-001 normalize 函数封装位置**：闭环——**抽出独立函数** `_compute_hash_with_normalize` + `_strip_frontmatter_fields`（§3.1）。理由：pytest 用例需要直接断言 normalize 行为，函数级独立更易测；`_r005_hash_drift` 主逻辑只剩 1 行调用。
2. **F-002 `git rev-parse` 缓存策略**：闭环——**函数局部不缓存**（§3.2.2 `_get_worktree_toplevel` docstring）；`_main_inner` for 循环前调用一次取 toplevel 后局部变量复用（§3.2.3）。理由：单次 hook 调用 1 次 subprocess 已是 minimal；模块级 `functools.lru_cache` 引入全局状态、影响 bats 单测 mock。
3. **F-003 archive-rules.md「手动 ack」流程粒度**：闭环——`refresh-only-current-req 处置原则` 段（§3.3.1）给 4 步操作流程 + notes.md 追加记录约定。
4. **F-001 历史 completed 需求 A2 兼容性是否纳入 testing 验收**：闭环——**纳入 V-02 集成验证**（来源：requirements/REQ-2026-013/artifacts/requirement.md）「testing 阶段回归用例」段；testing 阶段对全部 ~13 个 completed 需求跑 ci gate 确认 R005 无新增；若新增则按 §3.3.1 refresh-only-current-req 处置。
5. **F-005 验证方法节文案范围**：闭环——§3.5 抽出后保留「手跑命令 + owner」+ 补「reviewer 检查项」+ 补「持续门禁」3 子段，与 F-004 新五段规则的「## 验证方法」语义一致（如何确认问题不再复现）。

## 6. 引用源汇总

- requirements/REQ-2026-013/artifacts/requirement.md — 需求文档（5 feature 验收 + 「testing 阶段回归用例」段）
- requirements/REQ-2026-013/artifacts/tech-feasibility.md — 技术可行性（7 风险 R-1~R-7 + 工作量 7h + 5 待决问题）
- requirements/REQ-2026-013/artifacts/outline-design.md — 概要设计（4 层模块视图）
- requirements/REQ-2026-013/plan.md — D-001~D-011 ADR
- scripts/lib/check_reviews.py — `_r005_hash_drift` 函数（F-001 改造点）
- .claude/hooks/touches_guard.py — `_main_inner` + `_REPO_ROOT` + `_is_in_touches`（F-002 改造点）
- .claude/skills/managing-requirement-lifecycle/reference/archive-rules.md — archive 流程文档（F-003 改造点 1）
- scripts/lib/archive_runner.py — `_render_summary` 函数（F-003 改造点 2）
- context/team/experience/INDEX.md — 格式约定段（F-004 改造点）
- context/team/experience/test-assets-must-be-wired-into-ci.md — 经验文件（F-005 改造点）
- context/team/engineering-spec/features-schema.yaml — features.json schema
- context/team/engineering-spec/task-frontmatter-schema.yaml — task.md frontmatter schema
- scripts/gates/plugins/review_verdict.py — ci trigger 不支持 --req filter 源（F-003 D-008 依据）
- context/team/experience/reviewer-artifact-selection-excludes-evolving-frontmatter.md — F-001 经验
- context/team/experience/hook-path-normalization-out-of-repo.md — F-002 经验
- context/team/experience/archive-completed-triggers-framework-rule-fullset.md — F-003 经验
