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

## 生成命令示例

```bash
python3 <<'EOF'
import json, subprocess, os
from datetime import datetime, timezone

base = "main"
head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
base_sha = subprocess.check_output(["git", "rev-parse", base], text=True).strip()
branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()

stat = subprocess.check_output(["git", "diff", "--shortstat", f"{base}...HEAD"], text=True)
diff = subprocess.check_output(["git", "diff", "--stat", f"{base}...HEAD"], text=True)

scope = {
    "mode": "standalone",
    "base_sha": base_sha,
    "head_sha": head_sha,
    "base_branch": base,
    "current_branch": branch,
    "services": [],
    "stats": {"raw": stat.strip()},
    "diff_summary": diff.strip(),
    "timestamp": datetime.now(timezone.utc).isoformat()
}
with open(".review-scope.json", "w") as f:
    json.dump(scope, f, indent=2, ensure_ascii=False)
print(f".review-scope.json written ({scope['stats']['raw']})")
EOF
```
