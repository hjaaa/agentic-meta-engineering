# Reviewer Verdict 结构化 · PR1 基础设施 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 reviewer verdict 结构化所需的基础设施——`review-schema.yaml` 定义 + `save-review.sh` 写入通道（含 CR-1~CR-6 内部一致性规则）+ `check-reviews.sh` 校验通道（R001~R007）+ `meta-schema.yaml` 新增 `reviews` 顶层字段（PR1 阶段全为可选） + CI 接入但 non-strict。本 PR 不改任何 reviewer Agent，行为零变化。

**Architecture:** 复用 `scripts/lib/common.py` 现有 Severity/Report/exit_code 样板。两个新脚本走相同的"shell 薄壳 + Python 实现"分层（参考 `check-meta.sh` / `check_meta.py`）。CR 规则与 R 规则各自封装为独立函数便于单测。`reviews` 字段加入 `meta-schema.yaml` 时**只声明结构、不声明必填**——避免历史需求 CI 集体红。

**Tech Stack:** 本仓库是 Claude Code 骨架，无 pytest/junit。集成测试用 fixtures + bash 断言（参考 `scripts/check-meta.sh` 的回归方式）。Python 3.11 + PyYAML，新增 hashlib（标准库）。

**前置条件：**
- 设计文档已 approve：`context/team/engineering-spec/specs/2026-04-27-reviewer-verdict-structuring-design.md`（commit `ddbdbcf`）
- 当前所在 spec/roadmap 分支 `docs/gate-improvement-roadmap` 已合并到 `develop`（如未合并，先开 PR 合掉，再执行本计划）
- 仓库根：`/Users/richardhuang/learnspace/agentic-meta-engineering`
- Python 3.11+，已装 `pyyaml`

**显式不做（Out of Scope，留给 PR2/3/4）：**
- **不改任何 reviewer Agent**（`requirement-quality-reviewer.md` 等 4 个）。它们仍把 JSON 返回主对话，行为零变化
- **不改 `gate-checklist.md`**。门禁仍是文本清单
- **不改 `protect-branch.sh`**。reviews 文件目前没人写
- **不加 pre-commit diff 校验**（D7 第二道防线，PR3 落地）
- **不写 `legacy: true` 字段处理**（PR4 落地）
- **CI 不开 `--strict`**（PR4 落地）
- **不动 `requirements/REQ-2026-001/meta.yaml`** 加 reviews 字段（无需求实际产出 review）
- **不实现 `scripts/rebuild-meta-reviews.sh`**（spec §5 提到的重建工具，未来按需）

---

## File Structure

**Create:**
- `context/team/engineering-spec/review-schema.yaml` — review JSON 字段 / 枚举 / CR 规则定义（唯一事实源）
- `scripts/save-review.sh` — bash 薄壳，参数解析 + 调 Python
- `scripts/lib/save_review.py` — schema + CR 校验 + sha256 重算 + 文件写入 + meta.yaml 更新
- `scripts/check-reviews.sh` — bash 薄壳
- `scripts/lib/check_reviews.py` — R001~R007 校验
- `tests/fixtures/reviews/valid-definition-001.json` — 合法 fixture
- `tests/fixtures/reviews/invalid-cr1-approved-with-fixes.json` — 违反 CR-1
- `tests/fixtures/reviews/invalid-cr3-low-dim-approved.json` — 违反 CR-3
- `tests/fixtures/reviews/invalid-schema-missing-field.json` — 缺必填字段
- `tests/fixtures/reviews/run-integration.sh` — 集成测试脚本

**Modify:**
- `context/team/engineering-spec/meta-schema.yaml` — 新增 `reviews` 顶层字段说明（仅描述结构，不入 required_fields / conditional_required）
- `context/team/engineering-spec/INDEX.md` — 加 `review-schema.yaml` 索引项
- `.github/workflows/quality-check.yml` — 新增 step "Check reviews"，**不带 `--strict`**
- `context/team/engineering-spec/plans/INDEX.md` — 注册本 plan

**Delete:** 无

---

## Task 1: 切分支 + 验证前置

**Files:** 无文件改动

- [ ] **Step 1: 验证前置 commit 存在**

```bash
git log --oneline ddbdbcf -1
```
Expected：输出包含 `docs(roadmap): 盘点门禁体系 6 项缺陷 + reviewer verdict 结构化设计`

如果 commit 不存在，先确认 `docs/gate-improvement-roadmap` 已合到 `develop`。

- [ ] **Step 2: 拉最新 develop**

```bash
git checkout develop && git pull origin develop
```
Expected：`Already up to date` 或正常 fast-forward

- [ ] **Step 3: 从 develop 切新分支**

```bash
git checkout -b feat/reviewer-verdict-pr1-infra
```
Expected：`Switched to a new branch 'feat/reviewer-verdict-pr1-infra'`

- [ ] **Step 4: 验证 Python 环境**

```bash
python3 -c "import yaml; print(yaml.__version__)"
```
Expected：输出版本号（如 `6.0.1`），非 ImportError

---

## Task 2: 写 review-schema.yaml

**Files:**
- Create: `context/team/engineering-spec/review-schema.yaml`

- [ ] **Step 1: 创建 schema 文件**

写入 `context/team/engineering-spec/review-schema.yaml`：

```yaml
# review JSON 团队级 Schema 定义
#
# 用途：
#   - save-review.sh 写入前的字段 / 枚举 / CR 规则唯一事实源
#   - check-reviews.sh 读取时的 schema 复检
#
# 修改原则：
#   - 字段增删或 CR 规则调整必须走 PR review（影响所有 reviewer Agent）
#   - schema_version 升 2.0 必须迁移历史 review 文件
#
# 关联文档：
#   - context/team/engineering-spec/specs/2026-04-27-reviewer-verdict-structuring-design.md

schema_version: "1.0"

# ---------- 必填字段 ----------
required_fields:
  - schema_version
  - review_id
  - requirement_id
  - phase
  - reviewer
  - reviewed_at
  - reviewed_commit
  - reviewed_artifacts
  - conclusion
  - score
  - dimensions
  - required_fixes
  - suggestions
  - scope
  - supersedes

# ---------- 枚举 ----------
enums:
  phase:
    - definition
    - outline-design
    - detail-design
    - code           # 注：评审类别名，与生命周期 phase 不同；code 类按 feature_id 多次评审
  reviewer:
    - requirement-quality-reviewer
    - outline-design-quality-reviewer
    - detail-design-quality-reviewer
    - code-quality-reviewer
  conclusion:
    - approved
    - needs_revision
    - rejected
  severity:
    - blocker
    - major
    - minor

# ---------- 字段格式 ----------
format:
  schema_version: '^1\.0$'
  review_id: '^REV-REQ-\d{4}-\d{3}-(definition|outline-design|detail-design|code(-F-\d{3})?)-\d{3}$'
  requirement_id: '^REQ-\d{4}-\d{3}$'
  reviewed_at: datetime          # YYYY-MM-DD HH:MM:SS（time-format.md）
  reviewed_commit: '^[0-9a-f]{7,40}$'

# ---------- 数值范围 ----------
ranges:
  score: [0, 100]
  dimensions_score: [0, 100]    # 各维度 score 也走同一范围

# ---------- CR 规则（C3，烧进 schema 的内部一致性约束） ----------
# 违反任一条 → save-review.sh 拒收，返回 ERROR
cr_rules:
  CR-1:
    description: "conclusion=approved 时 required_fixes 必须为空"
    rule: "approved => required_fixes == []"
  CR-2:
    description: "required_fixes 非空时 conclusion 必须 ∈ {needs_revision, rejected}"
    rule: "len(required_fixes) > 0 => conclusion in [needs_revision, rejected]"
  CR-3:
    description: "任一 dimensions.*.score < 60 时 conclusion 不能为 approved"
    rule: "any dim.score < 60 => conclusion != approved"
  CR-4:
    description: "总评 score < 70 时 conclusion 不能为 approved"
    rule: "score < 70 => conclusion != approved"
  CR-5:
    description: "dimensions.*.issues[] 每项必须有合法 severity 和非空 description"
    rule: "for issue in dim.issues: issue.severity in enums.severity AND issue.description != ''"
  CR-6:
    description: "任一 issue.severity = blocker 时 conclusion 不能为 approved"
    rule: "any issue.severity == blocker => conclusion != approved"

# ---------- scope 约束 ----------
# phase=code 必须有 scope.feature_id；其他 phase 必须 scope=null
scope_rules:
  - when: { phase: code }
    must:
      scope: object
      scope.feature_id: '^F-\d{3}$'
  - when: { phase_not: [code] }
    must:
      scope: null
```

- [ ] **Step 2: 验证 YAML 合法**

```bash
python3 -c "import yaml; yaml.safe_load(open('context/team/engineering-spec/review-schema.yaml'))" && echo "YAML OK"
```
Expected：`YAML OK`

- [ ] **Step 3: Commit**

```bash
git add context/team/engineering-spec/review-schema.yaml
git commit -m "feat(review-schema): 新增 review JSON schema 定义

定义 reviewer Agent 写入的 review JSON 字段 / 枚举 / 格式 /
CR-1~CR-6 内部一致性规则，作为 save-review.sh / check-reviews.sh
的唯一事实源。

设计：specs/2026-04-27-reviewer-verdict-structuring-design.md §3"
```

---

## Task 3: meta-schema.yaml 新增 reviews 字段说明

**Files:**
- Modify: `context/team/engineering-spec/meta-schema.yaml`（追加段，不动现有字段）

- [ ] **Step 1: 在 meta-schema.yaml 末尾追加 reviews 字段说明**

用 Edit 工具在 `meta-schema.yaml` 末尾追加：

```yaml

# ---------- reviews 字段（v2 新增，PR1 阶段全为可选） ----------
# 由 save-review.sh / check-reviews.sh 维护，禁止主对话 LLM 直接 Edit。
# PR1 阶段不入 required_fields，也不入 conditional_required；
# PR4 升 strict 时再加条件必填规则（phase 在 definition 之后）。
#
# 结构示例（不在此处声明 schema，由 review-schema.yaml 间接约束）：
#   reviews:
#     definition:
#       latest: REV-REQ-2026-001-definition-002
#       conclusion: approved
#       reviewed_commit: 2fde52f
#       artifact_hashes:
#         "artifacts/requirement.md": "abc..."
#       history: [REV-..., REV-...]
#       stale: false
#     outline-design: { latest: null }
#     detail-design: { latest: null }
#     code:
#       by_feature:
#         F-001:
#           latest: REV-REQ-2026-001-code-F-001-001
#           conclusion: approved
#           reviewed_commit: ...
#           artifact_hashes: {...}
#           history: [...]
#           stale: false
optional_fields:
  - reviews
```

- [ ] **Step 2: 跑 check-meta.sh 确保未破坏现有需求**

```bash
scripts/check-meta.sh --all --strict
```
Expected：`✓ 无问题`（任一 error/warning 都说明 schema 改动破坏了现有需求，必须修）

- [ ] **Step 3: Commit**

```bash
git add context/team/engineering-spec/meta-schema.yaml
git commit -m "feat(meta-schema): 新增 reviews 顶层字段说明（PR1 全可选）

由 save-review.sh / check-reviews.sh 维护的 reviews 索引段。
PR1 仅声明结构、不入 required_fields，避免破坏现有需求 CI。
PR4 升 strict 时再加条件必填。

设计：specs/2026-04-27-reviewer-verdict-structuring-design.md §3.3"
```

---

## Task 4: 准备 fixtures

**Files:**
- Create: `tests/fixtures/reviews/valid-definition-001.json`
- Create: `tests/fixtures/reviews/invalid-cr1-approved-with-fixes.json`
- Create: `tests/fixtures/reviews/invalid-cr3-low-dim-approved.json`
- Create: `tests/fixtures/reviews/invalid-schema-missing-field.json`

- [ ] **Step 1: 建目录**

```bash
mkdir -p tests/fixtures/reviews
```

- [ ] **Step 2: 写合法 fixture**

`tests/fixtures/reviews/valid-definition-001.json`：

```json
{
  "schema_version": "1.0",
  "review_id": "REV-REQ-2099-999-definition-001",
  "requirement_id": "REQ-2099-999",
  "phase": "definition",
  "reviewer": "requirement-quality-reviewer",
  "reviewed_at": "2026-04-27 10:30:00",
  "reviewed_commit": "deadbee",
  "reviewed_artifacts": [
    {"path": "artifacts/requirement.md", "sha256": "0000000000000000000000000000000000000000000000000000000000000000"}
  ],
  "conclusion": "approved",
  "score": 85,
  "dimensions": {
    "completeness": {"score": 90, "issues": []},
    "consistency":  {"score": 85, "issues": []}
  },
  "required_fixes": [],
  "suggestions": [],
  "scope": null,
  "supersedes": null
}
```

- [ ] **Step 3: 写违反 CR-1 fixture**

`tests/fixtures/reviews/invalid-cr1-approved-with-fixes.json`（approved 但 required_fixes 非空）：

```json
{
  "schema_version": "1.0",
  "review_id": "REV-REQ-2099-999-definition-002",
  "requirement_id": "REQ-2099-999",
  "phase": "definition",
  "reviewer": "requirement-quality-reviewer",
  "reviewed_at": "2026-04-27 10:30:00",
  "reviewed_commit": "deadbee",
  "reviewed_artifacts": [
    {"path": "artifacts/requirement.md", "sha256": "0000000000000000000000000000000000000000000000000000000000000000"}
  ],
  "conclusion": "approved",
  "score": 85,
  "dimensions": {
    "completeness": {"score": 90, "issues": []}
  },
  "required_fixes": [
    {"description": "需求缺乏明确边界", "location": "artifacts/requirement.md:42", "severity": "major"}
  ],
  "suggestions": [],
  "scope": null,
  "supersedes": null
}
```

- [ ] **Step 4: 写违反 CR-3 fixture**

`tests/fixtures/reviews/invalid-cr3-low-dim-approved.json`（某维度 < 60 但 approved）：

```json
{
  "schema_version": "1.0",
  "review_id": "REV-REQ-2099-999-definition-003",
  "requirement_id": "REQ-2099-999",
  "phase": "definition",
  "reviewer": "requirement-quality-reviewer",
  "reviewed_at": "2026-04-27 10:30:00",
  "reviewed_commit": "deadbee",
  "reviewed_artifacts": [
    {"path": "artifacts/requirement.md", "sha256": "0000000000000000000000000000000000000000000000000000000000000000"}
  ],
  "conclusion": "approved",
  "score": 75,
  "dimensions": {
    "completeness": {"score": 90, "issues": []},
    "testability":  {"score": 50, "issues": []}
  },
  "required_fixes": [],
  "suggestions": [],
  "scope": null,
  "supersedes": null
}
```

- [ ] **Step 5: 写缺字段 fixture**

`tests/fixtures/reviews/invalid-schema-missing-field.json`（缺 `reviewed_commit`）：

```json
{
  "schema_version": "1.0",
  "review_id": "REV-REQ-2099-999-definition-004",
  "requirement_id": "REQ-2099-999",
  "phase": "definition",
  "reviewer": "requirement-quality-reviewer",
  "reviewed_at": "2026-04-27 10:30:00",
  "reviewed_artifacts": [
    {"path": "artifacts/requirement.md", "sha256": "0000000000000000000000000000000000000000000000000000000000000000"}
  ],
  "conclusion": "approved",
  "score": 85,
  "dimensions": {
    "completeness": {"score": 90, "issues": []}
  },
  "required_fixes": [],
  "suggestions": [],
  "scope": null,
  "supersedes": null
}
```

- [ ] **Step 6: 验证 4 份 JSON 合法**

```bash
for f in tests/fixtures/reviews/*.json; do
  python3 -c "import json; json.load(open('$f'))" && echo "$f OK"
done
```
Expected：4 行 `<path> OK`，无异常

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/reviews/
git commit -m "test(reviews): 新增 review JSON fixtures

合法 / 违反 CR-1 / 违反 CR-3 / 缺字段 共 4 份 fixture，
供 save_review.py 与 check_reviews.py 集成测试使用。

注意：reviewed_artifacts.sha256 是占位符，集成测试时由
save-review.sh 自动重算（spec §4.2 step 5）。"
```

---

## Task 5: 实现 save_review.py + save-review.sh

按 TDD 思路：先建 fixture（已完成 Task 4），写 Python 实现，每加一项规则跑 fixture 验证。

**Files:**
- Create: `scripts/lib/save_review.py`
- Create: `scripts/save-review.sh`

- [ ] **Step 1: 写 save_review.py 骨架（仅 schema 校验）**

`scripts/lib/save_review.py`：

```python
"""save-review.sh 的 Python 实现：写入 review JSON + 更新 meta.yaml.reviews

唯一事实源：context/team/engineering-spec/review-schema.yaml

用法：
  python3 scripts/lib/save_review.py \\
    --req REQ-2026-001 \\
    --phase definition \\
    --reviewer requirement-quality-reviewer \\
    [--scope feature_id=F-001] \\
    < verdict.json

退出码见 common.py。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from common import REPO_ROOT, Report, Severity, paint, rel

SCHEMA_PATH = REPO_ROOT / "context" / "team" / "engineering-spec" / "review-schema.yaml"
REQUIREMENTS_DIR = REPO_ROOT / "requirements"


def _load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _check_required_fields(verdict: dict, schema: dict, report: Report, label: str) -> None:
    for field in schema.get("required_fields", []):
        if field not in verdict:
            report.add(label, Severity.ERROR, "missing", f"缺少必填字段 {field}")


def _check_enums(verdict: dict, schema: dict, report: Report, label: str) -> None:
    enums = schema.get("enums", {})
    for field, allowed in enums.items():
        if field == "severity":
            continue  # severity 在 issues 内部，单独检查
        value = verdict.get(field)
        if value is None:
            continue
        if value not in allowed:
            report.add(label, Severity.ERROR, "enum", f"字段 {field} 值 {value!r} 不在枚举 {allowed} 内")


def _check_format(verdict: dict, schema: dict, report: Report, label: str) -> None:
    fmt = schema.get("format", {})
    for field, rule in fmt.items():
        value = verdict.get(field)
        if value is None:
            continue
        if rule == "datetime":
            try:
                datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                report.add(label, Severity.ERROR, "format", f"字段 {field} 值 {value!r} 不符合 datetime 格式")
        elif isinstance(rule, str) and rule.startswith("^"):
            if not isinstance(value, str) or not re.match(rule, value):
                report.add(label, Severity.ERROR, "format", f"字段 {field} 值 {value!r} 不匹配正则 {rule}")


def main() -> int:
    parser = argparse.ArgumentParser(description="写入 review JSON + 更新 meta.yaml.reviews")
    parser.add_argument("--req", required=True, help="REQ-YYYY-NNN")
    parser.add_argument("--phase", required=True, help="definition / outline-design / detail-design / code")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--scope", default=None, help="形如 feature_id=F-001（仅 phase=code 必填）")
    args = parser.parse_args()

    try:
        verdict = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(paint(f"❌ stdin JSON 解析失败: {exc}", "red"), file=sys.stderr)
        return 2

    schema = _load_schema()
    report = Report()
    label = f"<stdin>:{args.req}/{args.phase}"

    _check_required_fields(verdict, schema, report, label)
    _check_enums(verdict, schema, report, label)
    _check_format(verdict, schema, report, label)

    print(report.render())
    return report.exit_code(strict=False)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑骨架对合法 fixture（应 pass，但还没写文件）**

```bash
python3 scripts/lib/save_review.py --req REQ-2099-999 --phase definition --reviewer requirement-quality-reviewer < tests/fixtures/reviews/valid-definition-001.json
```
Expected：`✓ 无问题`，退出码 0

- [ ] **Step 3: 跑骨架对缺字段 fixture（应 fail）**

```bash
python3 scripts/lib/save_review.py --req REQ-2099-999 --phase definition --reviewer requirement-quality-reviewer < tests/fixtures/reviews/invalid-schema-missing-field.json
echo "exit=$?"
```
Expected：报错 `❌ missing: 缺少必填字段 reviewed_commit`，`exit=1`

- [ ] **Step 4: 加 CR-1~CR-6 校验函数**

在 `save_review.py` 的 `main()` 之前插入：

```python
def _check_cr_rules(verdict: dict, report: Report, label: str) -> None:
    conclusion = verdict.get("conclusion")
    required_fixes = verdict.get("required_fixes") or []
    score = verdict.get("score")
    dimensions = verdict.get("dimensions") or {}

    # CR-1: approved ⇒ required_fixes == []
    if conclusion == "approved" and len(required_fixes) > 0:
        report.add(label, Severity.ERROR, "CR-1", "conclusion=approved 但 required_fixes 非空")

    # CR-2: required_fixes 非空 ⇒ conclusion ∈ {needs_revision, rejected}
    if len(required_fixes) > 0 and conclusion not in ("needs_revision", "rejected"):
        report.add(label, Severity.ERROR, "CR-2", f"required_fixes 非空但 conclusion={conclusion!r}")

    # CR-3: 任一 dim.score < 60 ⇒ conclusion ≠ approved
    for dim_name, dim in dimensions.items():
        dim_score = dim.get("score") if isinstance(dim, dict) else None
        if isinstance(dim_score, int) and dim_score < 60 and conclusion == "approved":
            report.add(label, Severity.ERROR, "CR-3", f"维度 {dim_name} score={dim_score} < 60 但 conclusion=approved")

    # CR-4: score < 70 ⇒ conclusion ≠ approved
    if isinstance(score, int) and score < 70 and conclusion == "approved":
        report.add(label, Severity.ERROR, "CR-4", f"score={score} < 70 但 conclusion=approved")

    # CR-5: 每个 issue 必须 severity 合法 + description 非空
    for dim_name, dim in dimensions.items():
        issues = dim.get("issues") if isinstance(dim, dict) else []
        for i, issue in enumerate(issues or []):
            if not isinstance(issue, dict):
                report.add(label, Severity.ERROR, "CR-5", f"维度 {dim_name} issues[{i}] 不是 object")
                continue
            sev = issue.get("severity")
            desc = issue.get("description")
            if sev not in ("blocker", "major", "minor"):
                report.add(label, Severity.ERROR, "CR-5", f"维度 {dim_name} issues[{i}] severity={sev!r} 不合法")
            if not desc or not desc.strip():
                report.add(label, Severity.ERROR, "CR-5", f"维度 {dim_name} issues[{i}] description 为空")

    # CR-6: 任一 issue.severity=blocker ⇒ conclusion ≠ approved
    if conclusion == "approved":
        for dim_name, dim in dimensions.items():
            for issue in (dim.get("issues") if isinstance(dim, dict) else []) or []:
                if isinstance(issue, dict) and issue.get("severity") == "blocker":
                    report.add(label, Severity.ERROR, "CR-6", f"维度 {dim_name} 含 blocker issue 但 conclusion=approved")
```

并在 `main()` 的 `_check_format(...)` 之后调用：

```python
    _check_cr_rules(verdict, report, label)
```

- [ ] **Step 5: 跑 CR-1 fixture（应 fail）**

```bash
python3 scripts/lib/save_review.py --req REQ-2099-999 --phase definition --reviewer requirement-quality-reviewer < tests/fixtures/reviews/invalid-cr1-approved-with-fixes.json
echo "exit=$?"
```
Expected：报错 `❌ CR-1: conclusion=approved 但 required_fixes 非空`，`exit=1`

- [ ] **Step 6: 跑 CR-3 fixture（应 fail）**

```bash
python3 scripts/lib/save_review.py --req REQ-2099-999 --phase definition --reviewer requirement-quality-reviewer < tests/fixtures/reviews/invalid-cr3-low-dim-approved.json
echo "exit=$?"
```
Expected：报错包含 `CR-3` 与 `CR-4`（`score=75 < 70`？wait — fixture 是 75，不触发 CR-4；只 CR-3）

注：`invalid-cr3-low-dim-approved.json` 的 score=75 不触发 CR-4（CR-4 是 < 70）。仅 CR-3 应触发：维度 testability=50 < 60。

实际 expected：报错 `❌ CR-3: 维度 testability score=50 < 60 但 conclusion=approved`，`exit=1`

- [ ] **Step 7: 加 git 当前 commit 校验**

在 `_check_cr_rules` 之后、`main()` 写入流程之前，加：

```python
def _git_head_short() -> str | None:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short=7", "HEAD"], cwd=REPO_ROOT, text=True)
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _check_commit_matches_head(verdict: dict, report: Report, label: str) -> None:
    head = _git_head_short()
    if head is None:
        report.add(label, Severity.WARNING, "commit", "无法获取 git HEAD（非 git 仓库或 git 不可用）")
        return
    reviewed = verdict.get("reviewed_commit", "")
    # 兼容 reviewed_commit 是 7+ 位 hash
    if not reviewed.startswith(head) and not head.startswith(reviewed[:7]):
        report.add(label, Severity.ERROR, "commit", f"reviewed_commit={reviewed!r} 与当前 HEAD={head!r} 不匹配")
```

并在 `main()` 中 `_check_cr_rules` 之后调用：

```python
    _check_commit_matches_head(verdict, report, label)
```

- [ ] **Step 8: 加 sha256 重算 + 写入逻辑**

在 `main()` 末尾、`return report.exit_code(...)` 之前插入：

```python
    if report.errors > 0:
        return report.exit_code(strict=False)

    # 重算 reviewed_artifacts[].sha256
    req_dir = REQUIREMENTS_DIR / args.req
    if not req_dir.exists():
        print(paint(f"❌ 需求目录不存在: {rel(req_dir)}", "red"), file=sys.stderr)
        return 2

    for art in verdict.get("reviewed_artifacts", []):
        art_path = req_dir / art["path"]
        if not art_path.exists():
            print(paint(f"❌ artifact 文件不存在: {rel(art_path)}", "red"), file=sys.stderr)
            return 1
        with art_path.open("rb") as f:
            art["sha256"] = hashlib.sha256(f.read()).hexdigest()

    # 算下一个 NNN
    reviews_dir = req_dir / "reviews"
    reviews_dir.mkdir(exist_ok=True)
    phase = args.phase
    if phase == "code":
        if not args.scope or not args.scope.startswith("feature_id="):
            print(paint("❌ phase=code 必须有 --scope feature_id=F-XXX", "red"), file=sys.stderr)
            return 1
        feature_id = args.scope.split("=", 1)[1]
        prefix = f"code-{feature_id}-"
    else:
        prefix = f"{phase}-"
    existing = sorted(reviews_dir.glob(f"{prefix}*.json"))
    next_seq = len(existing) + 1
    out_name = f"{prefix}{next_seq:03d}.json"
    out_path = reviews_dir / out_name

    # 校验 review_id 与 NNN 一致
    expected_id = f"REV-{args.req}-{prefix}{next_seq:03d}"
    if verdict.get("review_id") != expected_id:
        print(paint(f"❌ review_id 应为 {expected_id!r}，实际 {verdict.get('review_id')!r}", "red"), file=sys.stderr)
        return 1

    # 写入 review JSON
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(paint(f"✓ 已写入 {rel(out_path)}", "green"))

    # 更新 meta.yaml.reviews
    meta_path = req_dir / "meta.yaml"
    with meta_path.open("r", encoding="utf-8") as f:
        meta = yaml.safe_load(f) or {}
    reviews = meta.setdefault("reviews", {})
    artifact_hashes = {art["path"]: art["sha256"] for art in verdict["reviewed_artifacts"]}
    entry = {
        "latest": verdict["review_id"],
        "conclusion": verdict["conclusion"],
        "reviewed_commit": verdict["reviewed_commit"],
        "artifact_hashes": artifact_hashes,
        "history": [],
        "stale": False,
    }
    if phase == "code":
        feature_id = args.scope.split("=", 1)[1]
        code_seg = reviews.setdefault("code", {}).setdefault("by_feature", {}).setdefault(feature_id, {"history": []})
        code_seg["history"] = (code_seg.get("history") or []) + [verdict["review_id"]]
        code_seg.update({k: v for k, v in entry.items() if k != "history"})
    else:
        old = reviews.get(phase, {"history": []})
        history = (old.get("history") or []) + [verdict["review_id"]]
        entry["history"] = history
        reviews[phase] = entry

    with meta_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
    print(paint(f"✓ 已更新 {rel(meta_path)} 的 reviews.{phase}", "green"))

    return 0
```

- [ ] **Step 9: 建一个临时假需求做端到端测试**

```bash
mkdir -p requirements/REQ-2099-999/{artifacts,reviews}
cat > requirements/REQ-2099-999/artifacts/requirement.md <<'EOF'
# 测试需求（端到端集成测试用，PR 合并前删除）
EOF
cat > requirements/REQ-2099-999/meta.yaml <<EOF
id: REQ-2099-999
title: 集成测试占位
phase: definition
created_at: "2026-04-27 11:00:00"
branch: feat/reviewer-verdict-pr1-infra
base_branch: develop
project: agentic-meta-engineering
services: []
feature_area: hooks
change_type: feature
affected_modules: []
EOF
```

- [ ] **Step 10: 用合法 fixture 跑端到端写入（修 reviewed_commit 为当前 HEAD）**

```bash
HEAD=$(git rev-parse --short=7 HEAD)
python3 -c "
import json, sys
v = json.load(open('tests/fixtures/reviews/valid-definition-001.json'))
v['reviewed_commit'] = '$HEAD'
json.dump(v, sys.stdout)
" | python3 scripts/lib/save_review.py --req REQ-2099-999 --phase definition --reviewer requirement-quality-reviewer
```
Expected：
```
✓ 已写入 requirements/REQ-2099-999/reviews/definition-001.json
✓ 已更新 requirements/REQ-2099-999/meta.yaml 的 reviews.definition
```

- [ ] **Step 11: 验证写入内容正确**

```bash
cat requirements/REQ-2099-999/reviews/definition-001.json | python3 -c "import json, sys; d=json.load(sys.stdin); print('sha256:', d['reviewed_artifacts'][0]['sha256'][:16], '...'); print('review_id:', d['review_id'])"
yq '.reviews.definition.latest' requirements/REQ-2099-999/meta.yaml
yq '.reviews.definition.stale' requirements/REQ-2099-999/meta.yaml
```
Expected：
- sha256 是真实的 64 位 hex（非全 0）
- review_id 为 `REV-REQ-2099-999-definition-001`
- latest 为 `REV-REQ-2099-999-definition-001`
- stale 为 `false`

- [ ] **Step 12: 写 save-review.sh shell 薄壳**

`scripts/save-review.sh`：

```bash
#!/usr/bin/env bash
# save-review.sh — review JSON 写入通道
#
# 用法：
#   bash scripts/save-review.sh \\
#     --req REQ-2026-001 \\
#     --phase definition \\
#     --reviewer requirement-quality-reviewer \\
#     [--scope feature_id=F-001] \\
#     < verdict.json
#
# 详见：context/team/engineering-spec/specs/2026-04-27-reviewer-verdict-structuring-design.md §4

set -e
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec python3 "$SCRIPT_DIR/lib/save_review.py" "$@"
```

```bash
chmod +x scripts/save-review.sh
```

- [ ] **Step 13: 验证 shell 薄壳工作**

```bash
HEAD=$(git rev-parse --short=7 HEAD)
python3 -c "
import json, sys
v = json.load(open('tests/fixtures/reviews/valid-definition-001.json'))
v['reviewed_commit'] = '$HEAD'
v['review_id'] = 'REV-REQ-2099-999-definition-002'
json.dump(v, sys.stdout)
" | bash scripts/save-review.sh --req REQ-2099-999 --phase definition --reviewer requirement-quality-reviewer
```
Expected：
```
✓ 已写入 requirements/REQ-2099-999/reviews/definition-002.json
✓ 已更新 requirements/REQ-2099-999/meta.yaml 的 reviews.definition
```

且 `meta.yaml.reviews.definition.history` 应有 2 条。

- [ ] **Step 14: 清理临时需求**

```bash
rm -rf requirements/REQ-2099-999
```

- [ ] **Step 15: Commit**

```bash
git add scripts/save-review.sh scripts/lib/save_review.py
git commit -m "feat(save-review): 新增 review JSON 写入通道

- scripts/save-review.sh：bash 薄壳
- scripts/lib/save_review.py：schema 校验 + CR-1~CR-6 + sha256
  重算 + meta.yaml.reviews 更新
- reviewed_commit 必须等于当前 HEAD（防错误 commit 上跑评审）

设计：specs/2026-04-27-reviewer-verdict-structuring-design.md §4"
```

---

## Task 6: 实现 check_reviews.py + check-reviews.sh

**Files:**
- Create: `scripts/lib/check_reviews.py`
- Create: `scripts/check-reviews.sh`

- [ ] **Step 1: 写 check_reviews.py 骨架（先实现 R001 + R003）**

`scripts/lib/check_reviews.py`：

```python
"""check-reviews.sh 的 Python 实现：阶段切换 / submit / CI 的门禁校验

唯一事实源：context/team/engineering-spec/review-schema.yaml

用法：
  python3 scripts/lib/check_reviews.py \\
    --req REQ-2026-001 \\
    --target-phase tech-research \\
    [--strict]

退出码见 common.py。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from common import REPO_ROOT, Report, Severity, paint, rel

REQUIREMENTS_DIR = REPO_ROOT / "requirements"

# target-phase → 必须存在的 review phase 列表
PHASE_REQUIREMENTS: dict[str, list[str]] = {
    "tech-research":  ["definition"],
    "outline-design": ["definition"],
    "detail-design":  ["outline-design"],
    "task-planning":  ["detail-design"],
    "development":    ["detail-design"],
    "testing":        ["detail-design", "code"],   # code 走 by_feature 检查
    "completed":      ["definition", "outline-design", "detail-design"],   # 全量
}


def _load_meta(req: str) -> dict[str, Any]:
    meta_path = REQUIREMENTS_DIR / req / "meta.yaml"
    if not meta_path.exists():
        raise FileNotFoundError(f"{rel(meta_path)} 不存在")
    with meta_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _r001_review_exists(meta: dict, target_phase: str, report: Report, label: str) -> None:
    """R001: target-phase 要求的 review 必须存在（latest != null）"""
    required_phases = PHASE_REQUIREMENTS.get(target_phase, [])
    reviews = meta.get("reviews") or {}
    for phase in required_phases:
        if phase == "code":
            continue  # 由 R007 处理
        entry = reviews.get(phase)
        if not entry or not entry.get("latest"):
            report.add(label, Severity.ERROR, "R001",
                       f"切到 {target_phase} 需要 {phase} 阶段的 review，但 reviews.{phase}.latest 为空")


def _r003_not_rejected(meta: dict, target_phase: str, report: Report, label: str) -> None:
    """R003: latest.conclusion != rejected"""
    required_phases = PHASE_REQUIREMENTS.get(target_phase, [])
    reviews = meta.get("reviews") or {}
    for phase in required_phases:
        if phase == "code":
            continue
        entry = reviews.get(phase) or {}
        if entry.get("conclusion") == "rejected":
            report.add(label, Severity.ERROR, "R003",
                       f"reviews.{phase}.conclusion=rejected，禁止切阶段")


def main() -> int:
    parser = argparse.ArgumentParser(description="reviewer verdict 门禁校验")
    parser.add_argument("--req", required=True)
    parser.add_argument("--target-phase", required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    label = args.req
    report = Report()

    try:
        meta = _load_meta(args.req)
    except FileNotFoundError as exc:
        print(paint(f"❌ {exc}", "red"), file=sys.stderr)
        return 2

    _r001_review_exists(meta, args.target_phase, report, label)
    _r003_not_rejected(meta, args.target_phase, report, label)

    print(report.render())
    return report.exit_code(strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑骨架对真需求验证（应 R001 fail，因 reviews 字段不存在）**

复用 Task 5 的临时假需求做测试：

```bash
mkdir -p requirements/REQ-2099-999/{artifacts,reviews}
cat > requirements/REQ-2099-999/artifacts/requirement.md <<'EOF'
# 测试需求
EOF
cat > requirements/REQ-2099-999/meta.yaml <<EOF
id: REQ-2099-999
title: 集成测试占位
phase: definition
created_at: "2026-04-27 11:00:00"
branch: feat/reviewer-verdict-pr1-infra
base_branch: develop
project: agentic-meta-engineering
services: []
feature_area: hooks
change_type: feature
affected_modules: []
EOF

python3 scripts/lib/check_reviews.py --req REQ-2099-999 --target-phase tech-research
echo "exit=$?"
```
Expected：报错 `❌ R001: 切到 tech-research 需要 definition 阶段的 review，但 reviews.definition.latest 为空`，`exit=1`

- [ ] **Step 3: 跑 save-review 后 R001 应 pass**

```bash
HEAD=$(git rev-parse --short=7 HEAD)
python3 -c "
import json, sys
v = json.load(open('tests/fixtures/reviews/valid-definition-001.json'))
v['reviewed_commit'] = '$HEAD'
v['review_id'] = 'REV-REQ-2099-999-definition-001'
json.dump(v, sys.stdout)
" | bash scripts/save-review.sh --req REQ-2099-999 --phase definition --reviewer requirement-quality-reviewer

python3 scripts/lib/check_reviews.py --req REQ-2099-999 --target-phase tech-research
echo "exit=$?"
```
Expected：`✓ 无问题`，`exit=0`

- [ ] **Step 4: 加 R002（schema 复检）+ R004（needs_revision 警告）+ R005（hash drift）+ R006（supersedes 链）**

在 `_r003_not_rejected` 之后追加：

```python
def _r002_schema_recheck(meta: dict, target_phase: str, report: Report, label: str, req: str) -> None:
    """R002: review JSON schema 合法（复用 save_review 的校验函数）"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import save_review

    schema = save_review._load_schema()
    reviews = meta.get("reviews") or {}
    for phase in PHASE_REQUIREMENTS.get(target_phase, []):
        if phase == "code":
            continue
        entry = reviews.get(phase) or {}
        latest_id = entry.get("latest")
        if not latest_id:
            continue
        # 找到对应 JSON 文件
        review_path = REQUIREMENTS_DIR / req / "reviews" / f"{phase}-{latest_id.rsplit('-', 1)[-1]}.json"
        if not review_path.exists():
            report.add(label, Severity.ERROR, "R002",
                       f"reviews.{phase}.latest={latest_id} 对应的文件 {rel(review_path)} 不存在")
            continue
        try:
            verdict = json.load(review_path.open(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.add(label, Severity.ERROR, "R002", f"{rel(review_path)} JSON 解析失败: {exc}")
            continue
        sub_report = Report()
        save_review._check_required_fields(verdict, schema, sub_report, str(review_path))
        save_review._check_enums(verdict, schema, sub_report, str(review_path))
        save_review._check_format(verdict, schema, sub_report, str(review_path))
        save_review._check_cr_rules(verdict, sub_report, str(review_path))
        for f, sev, code, msg in sub_report._findings:
            report.add(f, sev, f"R002/{code}", msg)


def _r004_needs_revision(meta: dict, target_phase: str, report: Report, label: str) -> None:
    """R004: latest.conclusion = needs_revision → 默认 WARNING，--strict 升 ERROR"""
    reviews = meta.get("reviews") or {}
    for phase in PHASE_REQUIREMENTS.get(target_phase, []):
        if phase == "code":
            continue
        entry = reviews.get(phase) or {}
        if entry.get("conclusion") == "needs_revision":
            report.add(label, Severity.WARNING, "R004",
                       f"reviews.{phase}.conclusion=needs_revision，建议先修后切阶段")


def _r005_hash_drift(meta: dict, target_phase: str, report: Report, label: str, req: str) -> None:
    """R005: reviewed_artifacts 中所有文件当前 sha256 必须匹配"""
    req_dir = REQUIREMENTS_DIR / req
    reviews = meta.get("reviews") or {}
    for phase in PHASE_REQUIREMENTS.get(target_phase, []):
        if phase == "code":
            continue
        entry = reviews.get(phase) or {}
        artifact_hashes = entry.get("artifact_hashes") or {}
        drifted: list[tuple[str, str, str]] = []
        for path_str, recorded in artifact_hashes.items():
            file_path = req_dir / path_str
            if not file_path.exists():
                drifted.append((path_str, recorded, "<missing>"))
                continue
            with file_path.open("rb") as f:
                current = hashlib.sha256(f.read()).hexdigest()
            if current != recorded:
                drifted.append((path_str, recorded, current))
        if drifted:
            for path_str, was, now in drifted:
                report.add(label, Severity.ERROR, "R005",
                           f"reviews.{phase}: {path_str} 已变更（was {was[:8]}..., now {now[:8] if now != '<missing>' else now}），review 已 stale，请重审")
            # 写回 stale=true
            entry["stale"] = True
            meta_path = req_dir / "meta.yaml"
            with meta_path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)


def _r006_supersedes_chain(meta: dict, target_phase: str, report: Report, label: str, req: str) -> None:
    """R006: supersedes 链无环、无悬挂引用"""
    req_dir = REQUIREMENTS_DIR / req
    reviews_dir = req_dir / "reviews"
    if not reviews_dir.exists():
        return
    all_ids: dict[str, dict] = {}
    for jf in reviews_dir.glob("*.json"):
        try:
            v = json.load(jf.open(encoding="utf-8"))
            all_ids[v["review_id"]] = v
        except (json.JSONDecodeError, KeyError):
            continue
    for rid, v in all_ids.items():
        sup = v.get("supersedes")
        if sup is None:
            continue
        if sup not in all_ids:
            report.add(label, Severity.ERROR, "R006", f"{rid} supersedes={sup} 但目标不存在")
            continue
        # 环检测：从 sup 向前走，看能不能回到 rid
        seen = {rid}
        cur = sup
        while cur is not None and cur in all_ids:
            if cur in seen:
                report.add(label, Severity.ERROR, "R006", f"supersedes 链含环：{rid} → ... → {cur}")
                break
            seen.add(cur)
            cur = all_ids[cur].get("supersedes")
```

并在 `main()` 的相应位置调用（次序：R001 → R002 → R003 → R004 → R005 → R006 → R007）。把 main 内调用块改为：

```python
    _r001_review_exists(meta, args.target_phase, report, label)
    _r002_schema_recheck(meta, args.target_phase, report, label, args.req)
    _r003_not_rejected(meta, args.target_phase, report, label)
    _r004_needs_revision(meta, args.target_phase, report, label)
    _r005_hash_drift(meta, args.target_phase, report, label, args.req)
    _r006_supersedes_chain(meta, args.target_phase, report, label, args.req)
```

- [ ] **Step 5: 验证 R005 hash drift**

继续用 Task 6 step 3 的状态。修改 artifact 触发 drift：

```bash
echo "新增一行" >> requirements/REQ-2099-999/artifacts/requirement.md
python3 scripts/lib/check_reviews.py --req REQ-2099-999 --target-phase tech-research
echo "exit=$?"
yq '.reviews.definition.stale' requirements/REQ-2099-999/meta.yaml
```
Expected：
- 报错 `❌ R005: reviews.definition: artifacts/requirement.md 已变更（was ...）`
- `exit=1`
- `stale` 字段值变为 `true`

- [ ] **Step 6: 加 R007（code 类 by_feature 覆盖）**

在 `_r006_supersedes_chain` 之后追加：

```python
def _r007_code_by_feature_coverage(meta: dict, target_phase: str, report: Report, label: str, req: str) -> None:
    """R007: 切到 testing 时，code.by_feature 必须覆盖 features.json 中所有 status=done 的 feature"""
    if target_phase != "testing":
        return
    features_path = REQUIREMENTS_DIR / req / "artifacts" / "features.json"
    if not features_path.exists():
        report.add(label, Severity.ERROR, "R007", f"切到 testing 需要 {rel(features_path)}，但文件不存在")
        return
    try:
        features = json.load(features_path.open(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.add(label, Severity.ERROR, "R007", f"features.json 解析失败: {exc}")
        return
    done_features = [f["id"] for f in features.get("features", []) if f.get("status") == "done"]
    code_seg = (meta.get("reviews") or {}).get("code") or {}
    by_feature = code_seg.get("by_feature") or {}
    for fid in done_features:
        entry = by_feature.get(fid) or {}
        if not entry.get("latest"):
            report.add(label, Severity.ERROR, "R007",
                       f"feature {fid} status=done 但 reviews.code.by_feature.{fid}.latest 为空")
        elif entry.get("conclusion") == "rejected":
            report.add(label, Severity.ERROR, "R007",
                       f"feature {fid} 的 code review conclusion=rejected")
```

并在 main 调用列表末尾加 `_r007_code_by_feature_coverage(meta, args.target_phase, report, label, args.req)`。

- [ ] **Step 7: 写 check-reviews.sh shell 薄壳**

`scripts/check-reviews.sh`：

```bash
#!/usr/bin/env bash
# check-reviews.sh — reviewer verdict 门禁校验
#
# 用法：
#   bash scripts/check-reviews.sh \\
#     --req REQ-2026-001 \\
#     --target-phase tech-research \\
#     [--strict]
#
# 详见：context/team/engineering-spec/specs/2026-04-27-reviewer-verdict-structuring-design.md §5

set -e
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec python3 "$SCRIPT_DIR/lib/check_reviews.py" "$@"
```

```bash
chmod +x scripts/check-reviews.sh
```

- [ ] **Step 8: 端到端验证 needs_revision warning + --strict 升 error**

```bash
# 重置临时需求 review 内容
rm -rf requirements/REQ-2099-999/reviews
yq -i 'del(.reviews)' requirements/REQ-2099-999/meta.yaml

HEAD=$(git rev-parse --short=7 HEAD)
python3 -c "
import json, sys
v = json.load(open('tests/fixtures/reviews/valid-definition-001.json'))
v['reviewed_commit'] = '$HEAD'
v['review_id'] = 'REV-REQ-2099-999-definition-001'
v['conclusion'] = 'needs_revision'
v['required_fixes'] = [{'description': '小问题', 'location': 'requirement.md:10', 'severity': 'minor'}]
json.dump(v, sys.stdout)
" | bash scripts/save-review.sh --req REQ-2099-999 --phase definition --reviewer requirement-quality-reviewer

# 默认非 strict：仅 warning
bash scripts/check-reviews.sh --req REQ-2099-999 --target-phase tech-research
echo "exit=$?"

# strict：升 error
bash scripts/check-reviews.sh --req REQ-2099-999 --target-phase tech-research --strict
echo "exit=$?"
```
Expected：
- 第一次 `⚠️  R004: ...needs_revision...`，`exit=0`
- 第二次同样的 warning，`exit=1`

- [ ] **Step 9: 清理临时需求**

```bash
rm -rf requirements/REQ-2099-999
```

- [ ] **Step 10: Commit**

```bash
git add scripts/check-reviews.sh scripts/lib/check_reviews.py
git commit -m "feat(check-reviews): 新增 review 门禁校验（R001~R007）

- scripts/check-reviews.sh：bash 薄壳
- scripts/lib/check_reviews.py：
  · R001 review 文件存在
  · R002 schema 复检（复用 save_review 校验函数）
  · R003 conclusion ≠ rejected
  · R004 needs_revision → WARNING / --strict ERROR
  · R005 hash drift → 标 stale + ERROR
  · R006 supersedes 链无环
  · R007 切 testing 时 code.by_feature 覆盖 done features

设计：specs/2026-04-27-reviewer-verdict-structuring-design.md §5"
```

---

## Task 7: CI 接入（non-strict）

**Files:**
- Modify: `.github/workflows/quality-check.yml`

- [ ] **Step 1: 在 sourcing check 之后追加 reviews check step**

用 Edit 工具在 `.github/workflows/quality-check.yml` 的 `Check sourcing` 之后插入：

```yaml

      - name: Check reviews (non-strict, PR1)
        run: |
          for dir in requirements/*/; do
            req=$(basename "$dir")
            [ -f "$dir/meta.yaml" ] || continue
            phase=$(python3 -c "import yaml; print(yaml.safe_load(open('$dir/meta.yaml')).get('phase', ''))")
            [ -z "$phase" ] && continue
            # PR1：不强制 strict；仅打日志，不挂 CI
            bash scripts/check-reviews.sh --req "$req" --target-phase "$phase" || \
              echo "::warning::check-reviews failed for $req (non-strict, PR1)"
          done
```

- [ ] **Step 2: 本地 dry-run（模拟 CI）**

```bash
for dir in requirements/*/; do
  req=$(basename "$dir")
  [ -f "$dir/meta.yaml" ] || continue
  phase=$(python3 -c "import yaml; print(yaml.safe_load(open('$dir/meta.yaml')).get('phase', ''))")
  [ -z "$phase" ] && continue
  bash scripts/check-reviews.sh --req "$req" --target-phase "$phase" || echo "WARN $req"
done
```
Expected：现有 `REQ-2026-001` 应 R001 fail（无 reviews 字段），输出 `WARN REQ-2026-001`，但脚本本身退出码 0（因 `||`）

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/quality-check.yml
git commit -m "ci(quality-check): 新增 check-reviews step（non-strict）

PR1 阶段不挂 CI（用 || 兜底），仅打 warning 日志。
PR4 升 strict 时改为强制阻断。

设计：specs/2026-04-27-reviewer-verdict-structuring-design.md §6.4"
```

---

## Task 8: 整理索引 + 注册 plan

**Files:**
- Modify: `context/team/engineering-spec/INDEX.md`
- Modify: `context/team/engineering-spec/plans/INDEX.md`

- [ ] **Step 1: 在 engineering-spec/INDEX.md 的"数据格式约定"段加 review-schema.yaml**

用 Edit 工具改 `context/team/engineering-spec/INDEX.md`，在 `meta-schema.yaml` 行之后加：

```markdown
- [`review-schema.yaml`](review-schema.yaml) — `requirements/<id>/reviews/*.json` 的字段 schema / 枚举 / CR 规则
```

- [ ] **Step 2: 把 plans/INDEX.md 中本 plan 的状态从「📋 待启动」切到「🔄 执行中」**

`plans/INDEX.md` 中本 plan 的条目已在 docs PR #35 加入，状态为 `📋 待启动（待 docs PR #35 合入）`。本 step 改为：

用 Edit 工具把该行末两列改成 `feat/reviewer-verdict-pr1-infra | 🔄 执行中`（去掉「（待建）」与「待启动」备注）。

- [ ] **Step 3: 跑 check-index.sh 验证 INDEX 完整**

```bash
scripts/check-index.sh --strict
```
Expected：`✓ 无问题`

- [ ] **Step 4: Commit**

```bash
git add context/team/engineering-spec/INDEX.md context/team/engineering-spec/plans/INDEX.md
git commit -m "docs(index): 注册 review-schema.yaml 与 PR1 plan"
```

---

## Task 9: 最终回归 + 推分支 + 开 PR

**Files:** 无文件改动

- [ ] **Step 1: 跑全套既有 check 不挂**

```bash
scripts/check-meta.sh --all --strict
scripts/check-index.sh --strict
scripts/check-sourcing.sh --all --strict
```
Expected：3 个都 `✓ 无问题`

- [ ] **Step 2: 验证临时假需求确实清理干净**

```bash
ls requirements/ | grep REQ-2099 && echo "FAIL：临时需求未清理" || echo "OK"
```
Expected：`OK`

- [ ] **Step 3: 看 commit 历史**

```bash
git log --oneline develop..HEAD
```
Expected：约 7 个 commit（Task 2/3/4/5/6/7/8 各一个）

- [ ] **Step 4: 推分支**

```bash
git push -u origin feat/reviewer-verdict-pr1-infra
```

- [ ] **Step 5: 开 PR（手动或用 gh）**

```bash
gh pr create --base develop --title "feat: reviewer verdict 结构化 PR1（基础设施）" --body "$(cat <<'EOF'
## Summary
- 新增 `review-schema.yaml`：定义 review JSON 字段 / 枚举 / CR-1~CR-6
- 新增 `scripts/save-review.sh` + `scripts/lib/save_review.py`：写入通道
- 新增 `scripts/check-reviews.sh` + `scripts/lib/check_reviews.py`：R001~R007 校验
- `meta-schema.yaml` 新增 `reviews` 顶层字段（PR1 全可选）
- CI 接入但 non-strict（PR1 仅打 warning）

## Out of Scope（PR2/3/4）
- PR2：试点 `requirement-quality-reviewer` + 改 `gate-checklist.md`
- PR3：剩余 3 reviewer 全切 + protect-branch 禁写 + pre-commit diff
- PR4：CI 升 `--strict` + `legacy: true` 治理 + roadmap G3 done

## 关联设计
- spec：`context/team/engineering-spec/specs/2026-04-27-reviewer-verdict-structuring-design.md`
- plan：`context/team/engineering-spec/plans/2026-04-27-reviewer-verdict-pr1-infra.md`
- roadmap：G3（见 roadmap.md "门禁体系缺陷与演进"）

## Test Plan
- [ ] CI 全套绿
- [ ] 手动跑 `bash scripts/save-review.sh < tests/fixtures/reviews/valid-definition-001.json` 端到端走通
- [ ] 手动跑 `bash scripts/check-reviews.sh --req <existing-req> --target-phase <phase>` 应 R001 fail
EOF
)"
```

- [ ] **Step 6: 把 plan 标记为 ✅ 待 review（plans/INDEX.md）**

PR 通过 review 合入后，把 `plans/INDEX.md` 状态改为已合入，并把 plan 文件 `git mv` 到 `plans/history/`。这一步不在本 plan 内，由 PR merger 操作。

---

## 验证清单（每个 task 内已包含，此处汇总）

提交 PR 前必跑：

- [ ] `scripts/check-meta.sh --all --strict` → ✓
- [ ] `scripts/check-index.sh --strict` → ✓
- [ ] `scripts/check-sourcing.sh --all --strict` → ✓
- [ ] `bash scripts/save-review.sh` 端到端可写入 review JSON 与 meta.yaml.reviews
- [ ] `bash scripts/check-reviews.sh` 7 项规则都能正确触发
- [ ] CI workflow 在 PR 上跑通（含新加的 Check reviews step）
- [ ] 无遗留 `requirements/REQ-2099-*` 临时目录

---

## 风险与回滚

| 风险 | 触发条件 | 回滚 |
|---|---|---|
| save_review.py 写 meta.yaml 时丢失原有字段顺序 | yaml.safe_dump 默认排序 | 已用 `sort_keys=False`，但实测如出现顺序乱，改用 `ruamel.yaml` 保持往返一致 |
| CI step 因 yq / python 缺失挂掉 | `actions/setup-python` 已装 pyyaml；yq 在 ubuntu-latest 自带；如无 yq 改用 python -c 读 yaml | 改 step 用 python 而非 yq |
| 现有 REQ-2026-001 在新 CI step 被 warn 刷屏 | 预期行为（PR1 non-strict） | 不回滚；PR4 用 `legacy: true` 豁免 |
| 整 PR 出问题 | 回滚到合入前 commit；4 reviewer Agent 与 gate-checklist 未改，体系功能完全未变 | `git revert` PR 即可 |
