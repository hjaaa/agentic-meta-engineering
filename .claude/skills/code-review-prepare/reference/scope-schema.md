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

`.review-scope.json` 由 `code_review_routing.py` 统一生成（含 diff 扫描 + 路由建议 + tty 确认 + 写盘）：

```bash
python3 scripts/lib/code_review_routing.py
```

请勿手动写盘——路由确认 + `routing_confirmed_by` 字段由脚本强制保证。

---

## 新增字段（F-002）

`.review-scope.json` 在原有字段基础上追加以下 4 个字段：

```jsonc
{
  // 原有字段（mode / requirement_id / feature_id / base_sha / head_sha / ...）保持不变

  // 本次实际运行的 checker 列表（按 ALL_CHECKERS 顺序）
  "checker_route": ["complexity-checker", "security-checker", "..."],

  // 被路由规则跳过的 checker 及跳过原因
  "skipped_checkers": [
    { "name": "concurrency-checker", "reason": "diff 未命中 concurrency 关键字" }
  ],

  // 路由模式提示，透传给下游
  // "default" — 默认两阶段确认；"all" — 用户选 all；"trivial" — --trivial 透传
  "mode_hint": "default" | "all" | "trivial",

  // 卡点 A 路由确认元信息
  "routing_confirmed_by": {
    "decision": "accept" | "all" | "custom" | "abort",
    "confirmed_at": "2026-04-30T10:00:00+08:00",  // ISO8601 含时区
    "confirmed_by": "user@example.com",            // git config user.email
    "tty_verified": true                           // 必须为 true，非 tty 不写盘
  }
}
```

### 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| checker_route | 是 | 本次实际执行的 checker 名称列表；元素 ∈ 8-checker 全集；元素互斥；`mode_hint=trivial` 时可为空数组 |
| skipped_checkers | 是 | 被跳过的 checker 列表；每项含 `name` + `reason` |
| mode_hint | 是 | `"default"` / `"all"` / `"trivial"` 三选一 |
| routing_confirmed_by | 是 | 路由确认元信息子段，见下方不变量说明 |
| routing_confirmed_by.decision | 是 | `accept` / `all` / `custom` / `abort`；`abort` 时不写盘 |
| routing_confirmed_by.confirmed_at | 是 | ISO8601 含时区时间戳 |
| routing_confirmed_by.confirmed_by | 是 | git config user.email；必须匹配 `^[^@\s]+@[^@\s]+\.[^@\s]+$` |
| routing_confirmed_by.tty_verified | 是 | 必须为 `true`；非 tty 路径拒绝写盘 |

### 不变量约束

- `checker_route` 元素 ∈ 8-checker 全集（`complexity / security / concurrency / performance / error-handling / design-consistency / history-context / auxiliary-spec`）
- `decision="all"` ⇔ `checker_route` = 8 全集 ∧ `mode_hint="all"`
- `decision="abort"` → 脚本不写盘，直接正常退出
- `tty_verified` 必须 `true`（脚本在非 tty 环境退出码 2，不写盘）
- `confirmed_by` 从 `git config user.email` 读取；空值或无 `@` → 退出码 1

8-checker 全集顺序（固定）：

```
complexity-checker, security-checker, concurrency-checker, performance-checker,
error-handling-checker, design-consistency-checker, history-context-checker, auxiliary-spec-checker
```
