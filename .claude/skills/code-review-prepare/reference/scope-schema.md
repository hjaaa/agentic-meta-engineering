# ReviewScope JSON Schema

路径：项目根目录 `.review-scope.json`（运行时临时文件）

## Schema

```json
{
  "mode": "embedded" | "standalone",
  "requirement_id": "REQ-2026-001",
  "feature_id": "F-001",
  "base_sha": "abc1234",
  "head_sha": "def5678",
  "base_branch": "main",
  "current_branch": "feat/req-2026-001",
  "services": ["service-a", "service-b"],
  "stats": {
    "files_changed": 12,
    "insertions": 320,
    "deletions": 45
  },
  "diff_summary": "path/to/file1.go (+12 -3)\npath/to/file2.java (+200 -0)",
  "timestamp": "2026-04-20T15:30:00Z"
}
```

## 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| mode | 是 | embedded / standalone |
| requirement_id | 嵌入模式必填 | 当前需求 ID |
| feature_id | 嵌入+逐 feature 模式可填 | 限定单个 feature 范围 |
| base_sha / head_sha | 是 | Git SHA |
| base_branch | 是 | 对比基线，默认 `main` |
| current_branch | 是 | 当前分支 |
| services | 嵌入模式必填 | 涉及的服务仓库/目录 |
| stats | 是 | diff 统计 |
| diff_summary | 是 | 文件列表+增量（供 checker 快速扫） |

## 生成命令

`.review-scope.json` 由 `code_review_routing.py` 统一生成（含 diff 扫描 + 路由建议 + trivial-skip 短路逻辑 + 自动决策 + 写盘）。自 F-014 起取消人类 tty 卡点 A：

```bash
python3 scripts/lib/code_review_routing.py --mode embedded --requirement-id <id> --base-sha <sha> --head-sha <sha> --base-branch develop --current-branch <branch>
```

请勿手动写盘——路由确认 + `routing_decision` 字段由脚本强制保证。

---

## 新增字段（F-003）

`.review-scope.json` 在原有 11 字段基础上追加以下 4 个字段（合并现有 + 增量）：

```jsonc
{
  // ─────── 现有 11 字段（本需求不动）───────
  "mode": "embedded" | "standalone",
  "requirement_id": "REQ-2026-003",
  "feature_id": "F-003",
  "base_sha": "abc1234",
  "head_sha": "def5678",
  "base_branch": "develop",
  "current_branch": "feat/req-2026-003",
  "services": ["agentic-meta-engineering"],
  "stats": {"files_changed": 12, "insertions": 320, "deletions": 45},
  "diff_summary": "scripts/lib/foo.py (+12 -3)\n.claude/skills/bar/SKILL.md (+8 -2)",
  "timestamp": "2026-04-30T21:23:50+08:00",

  // ─────── 本需求新增/修订字段 ───────

  // 顶层布尔；trivial 100% 命中 → true，其余场景必须 false
  "skipped": false,

  // 本次实际跑的 checker 列表，按 ALL_CHECKERS 顺序
  "checker_route": ["security-checker", "design-consistency-checker"],

  // 被跳过的 checker 及原因（按路径表述，非关键词）
  "skipped_checkers": [
    { "name": "complexity-checker", "reason": "路径未命中 must/suggest 任何规则" },
    { "name": "concurrency-checker", "reason": "路径未命中 must/suggest 任何规则" }
    // ... 共 8 项，除 skipped=true 外 len(skipped_checkers) == 8
  ],

  // 路由元信息（自 F-014 起由 routing.py 自动决策填充）
  "routing_decision": {
    "decision": "accept",          // accept / all / trivial-skipped；F-014 后 custom/abort 不再产生
    "confirmed_at": "2026-04-30 21:23:50",   // YYYY-MM-DD HH:MM:SS Asia/Shanghai
    "confirmed_by": "user@example.com",      // git config user.email（最近一次 git 操作者）
    "tty_verified": true,                    // 标记 scope 通过 routing.py 完整流水校验（含自动路由）
    "files_must_hit": 3,                     // 触发 must 命中的文件数（审计用）
    "files_suggest_hit": 5,
    "files_trivial": 0,
    "files_total": 8
  }
}
```

### 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| skipped | 是 | 布尔；trivial 100% 命中 → true；否则 false。true 时 checker_route=[] 且 skipped_checkers 含 8 个全集 |
| checker_route | 是 | 本次实际执行的 checker 名称列表；元素 ∈ 8-checker 全集；决策为 trivial-skipped 时为空数组 |
| skipped_checkers | 是 | 被跳过的 checker 列表；每项含 `name` + `reason`；总长必须 == 8 |
| routing_decision | 是 | 路由确认元信息子段，见下方不变量说明 |
| routing_decision.decision | 是 | `accept` / `all` / `trivial-skipped`（F-014 后 `custom` / `abort` 不再产生，保留枚举供回滚） |
| routing_decision.confirmed_at | 是 | YYYY-MM-DD HH:MM:SS Asia/Shanghai 时间戳 |
| routing_decision.confirmed_by | 是 | git config user.email；必须匹配 `^[^@\s]+@[^@\s]+\.[^@\s]+$` |
| routing_decision.tty_verified | 是 | 必须为 `true`；表示 scope 由 routing.py 完整流水生成并通过 I1-I8 校验 |
| routing_decision.files_must_hit | 是 | 命中 must 规则的文件数 |
| routing_decision.files_suggest_hit | 是 | 命中 suggest 规则的文件数 |
| routing_decision.files_trivial | 是 | 命中 trivial 白名单的文件数 |
| routing_decision.files_total | 是 | diff 总文件数 |

### 不变量约束（I1-I8）

| 不变量 | 描述 |
|---|---|
| I1 | `decision="trivial-skipped"` ⇔ `skipped=true` ∧ `checker_route=[]` ∧ `len(skipped_checkers)==8` |
| I2 | `decision="all"` ⇔ `skipped=false` ∧ `checker_route` 等于 `ALL_CHECKERS`（顺序敏感） |
| I3 | `decision="custom"` → `checker_route` 必含 plan 中所有 must 命中 checker（用户不可去掉 must） |
| I4 | `decision="abort"` → 不应有 scope 文件（routing.py 不写盘） |
| I5 | `routing_decision.tty_verified` 必须 `true`（F-014 后含义放宽为"由 routing.py 完整流水写盘"） |
| I6 | `confirmed_by` 必须匹配 `^[^@\s]+@[^@\s]+\.[^@\s]+$`，否则 routing.py 退码 1 |
| I7 | `skipped=true` ⇒ `checker_route=[]` 且 `len(skipped_checkers)==8` |
| I8 | `len(checker_route) + len(skipped_checkers) == 8`（除 trivial-skip 外严格成立） |

### reason 三选一模板（D-003 路径表述定稿）

| 触发场景 | reason 字符串 |
|---|---|
| 路径未命中任何 must/suggest 规则 | `"路径未命中 must/suggest 任何规则"` |
| 用户在 custom 子集中未选择 | `"用户在 custom 子集中未选择"` |
| trivial-skip 路径下被全部跳过 | `"diff 全在 trivial 白名单内（skipped=true 全 8 个）"` |

8-checker 全集顺序（固定）：

```
complexity-checker, security-checker, concurrency-checker, performance-checker,
error-handling-checker, design-consistency-checker, history-context-checker, auxiliary-spec-checker
```
